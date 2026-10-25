"""PayPal Orders v2 + Payments v2. Las credenciales y el receptor son por tienda."""
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from .base import AdapterResponse
from .http import ConfiguredPaymentAdapter, ProviderError, basic_auth, request_json


class PayPalAdapter(ConfiguredPaymentAdapter):
    key = 'paypal'
    label = 'PayPal'
    required = ('ACCOUNT_REF', 'CLIENT_ID', 'CLIENT_SECRET', 'WEBHOOK_ID', 'RETURN_URL', 'CANCEL_URL')

    def _api(self, attempt, method, path, payload=None, request_id=None):
        config = self.config_for(attempt)
        base = 'https://api-m.paypal.com' if attempt.environment == 'live' else 'https://api-m.sandbox.paypal.com'
        auth = request_json('POST', base + '/v1/oauth2/token',
            {'Authorization': basic_auth(config['CLIENT_ID'], config['CLIENT_SECRET'])}, form={'grant_type': 'client_credentials'})
        if not auth.get('access_token'):
            raise ProviderError('PayPal no devolvió un token de acceso.')
        headers = {'Authorization': 'Bearer ' + auth['access_token']}
        if request_id:
            headers['PayPal-Request-Id'] = request_id
        return request_json(method, base + path, headers, payload=payload)

    def _normalise(self, data):
        units = data.get('purchase_units') or []
        if len(units) != 1:
            raise ProviderError('PayPal devolvió unidades de compra inesperadas.')
        unit = units[0]
        captures = (unit.get('payments') or {}).get('captures') or []
        capture = captures[0] if len(captures) == 1 else {}
        if len(captures) > 1:
            raise ProviderError('Múltiples capturas requieren conciliación manual.')
        state = {'CREATED': 'requires_action', 'PAYER_ACTION_REQUIRED': 'requires_action',
            'APPROVED': 'authorized', 'VOIDED': 'cancelled', 'SAVED': 'pending'}.get(data.get('status'), 'pending')
        if data.get('status') == 'COMPLETED':
            state = {'COMPLETED': 'captured', 'REFUNDED': 'refunded', 'PARTIALLY_REFUNDED': 'partially_refunded',
                'PENDING': 'pending', 'DECLINED': 'failed'}.get(capture.get('status'), 'pending')
        amount = capture.get('amount') or unit.get('amount') or {}
        safe = {'order_id': str(unit.get('custom_id', '')),
            'account_ref': (unit.get('payee') or {}).get('merchant_id', ''), 'capture_id': capture.get('id', '')}
        refunds = (unit.get('payments') or {}).get('refunds') or []
        if refunds:
            safe['refunded_amount'] = str(sum(Decimal(r['amount']['value']) for r in refunds if r.get('status') == 'COMPLETED'))
        return AdapterResponse(ok=True, provider=self.key, state=state, provider_state=data.get('status', ''),
            external_ref=data.get('id', ''), amount=amount.get('value', ''), currency=amount.get('currency_code', ''),
            redirect_url=next((link['href'] for link in data.get('links', []) if link.get('rel') in ('approve', 'payer-action')), ''), safe=safe)

    def create_payment(self, attempt):
        try:
            config = self.config_for(attempt)
            data = self._api(attempt, 'POST', '/v2/checkout/orders', {
                'intent': 'CAPTURE', 'purchase_units': [{'reference_id': str(attempt.public_id),
                    'custom_id': str(attempt.order.public_id), 'invoice_id': str(attempt.public_id),
                    'payee': {'merchant_id': attempt.account_ref},
                    'amount': {'currency_code': attempt.currency, 'value': str(attempt.amount)}}],
                'payment_source': {'paypal': {'experience_context': {'return_url': self.return_url(attempt, config),
                    'cancel_url': config['CANCEL_URL'], 'user_action': 'PAY_NOW', 'shipping_preference': 'NO_SHIPPING'}}}
            }, request_id=str(attempt.public_id))
            # Prefer: return=representation is not guaranteed; GET supplies authoritative purchase units.
            if not data.get('purchase_units'):
                full = self._api(attempt, 'GET', '/v2/checkout/orders/' + quote(data['id'], safe=''))
                full.setdefault('links', data.get('links', []))
                data = full
            return self._normalise(data)
        except (ProviderError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return self.failure(exc if isinstance(exc, ProviderError) else ProviderError('Respuesta PayPal incompleta.', ambiguous=True))

    def get_payment(self, attempt):
        try:
            if not attempt.external_ref:
                raise ProviderError('Falta referencia PayPal; consultar el panel antes de crear otro intento.')
            return self._normalise(self._api(attempt, 'GET', '/v2/checkout/orders/' + quote(attempt.external_ref, safe='')))
        except (ProviderError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return self.failure(exc if isinstance(exc, ProviderError) else ProviderError('Respuesta PayPal incompleta.'))

    def capture(self, attempt):
        try:
            data = self._api(attempt, 'POST', '/v2/checkout/orders/' + quote(attempt.external_ref, safe='') + '/capture',
                {}, request_id='capture-' + str(attempt.public_id))
            return self._normalise(data)
        except (ProviderError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return self.failure(exc if isinstance(exc, ProviderError) else ProviderError('Captura PayPal no confirmada.', ambiguous=True))

    def refund(self, attempt, amount=None, note=''):
        try:
            capture_id = attempt.safe_payload.get('capture_id')
            if not capture_id:
                raise ProviderError('Conciliar el cobro para obtener la referencia de captura antes de devolver.')
            data = self._api(attempt, 'POST', '/v2/payments/captures/' + quote(capture_id, safe='') + '/refund',
                {'amount': {'value': str(amount), 'currency_code': attempt.currency}, 'note_to_payer': note[:255]},
                request_id=attempt.safe_payload['refund_request_key'][:108])
            refund_money = data.get('amount') or {}
            if (Decimal(str(refund_money.get('value'))) != Decimal(str(amount)) or
                    refund_money.get('currency_code') != attempt.currency):
                raise ProviderError('Importe de devolución PayPal no coincide.', ambiguous=True)
            state = {'COMPLETED': 'refunded', 'PENDING': 'refund_pending'}.get(data.get('status'))
            if not state:
                raise ProviderError('PayPal no confirmó el reembolso.', ambiguous=True)
            return AdapterResponse(ok=True, provider=self.key, state=state, external_ref=data['id'], amount=str(amount))
        except (ProviderError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return self.failure(exc if isinstance(exc, ProviderError) else ProviderError('Reembolso PayPal no confirmado.', ambiguous=True))

    def notification_reference(self, parsed):
        resource = parsed.get('resource') or {}
        return str((resource.get('supplementary_data') or {}).get('related_ids', {}).get('order_id') or
            (resource.get('id') if parsed.get('event_type', '').startswith('CHECKOUT.ORDER.') else '') or '')

    def verify_notification(self, headers, raw_body, attempt=None):
        try:
            config = self.config_for(attempt)
            headers = {key.lower(): value for key, value in headers.items()}
            payload = {key.replace('-', '_'): headers['paypal-' + key] for key in
                ('auth-algo', 'cert-url', 'transmission-id', 'transmission-sig', 'transmission-time')}
            payload.update(webhook_id=config['WEBHOOK_ID'], webhook_event=json.loads(raw_body))
            return self._api(attempt, 'POST', '/v1/notifications/verify-webhook-signature', payload).get('verification_status') == 'SUCCESS'
        except (ProviderError, KeyError, TypeError, ValueError):
            return False
