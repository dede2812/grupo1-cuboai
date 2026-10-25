"""BTCPay Greenfield: facturas, consulta y firmas HMAC del cuerpo exacto."""
import hashlib
import hmac
import json
from urllib.parse import quote
from .base import AdapterResponse
from .http import ConfiguredPaymentAdapter, ProviderError, request_json


class BTCPayAdapter(ConfiguredPaymentAdapter):
    key = 'btcpay'
    label = 'Bitcoin · BTCPay Server'
    required = ('ACCOUNT_REF', 'BASE_URL', 'API_KEY', 'WEBHOOK_SECRET')

    def _api(self, attempt, method, path, payload=None):
        config = self.config_for(attempt)
        return request_json(method, config['BASE_URL'].rstrip('/') + path,
            {'Authorization': 'token ' + config['API_KEY']}, payload=payload)

    def _normalise(self, data, attempt):
        status = data.get('status')
        state = {'New': 'requires_action', 'Processing': 'pending', 'Settled': 'captured',
            'Expired': 'expired', 'Invalid': 'failed'}.get(status)
        if not state:
            raise ProviderError('Estado de factura BTCPay desconocido.')
        return AdapterResponse(ok=True, provider=self.key, state=state, provider_state=status,
            external_ref=data.get('id', ''), amount=str(data.get('amount', '')), currency=data.get('currency', ''),
            redirect_url=data.get('checkoutLink', ''), safe={
                'order_id': str((data.get('metadata') or {}).get('orderId', '')),
                # La ruta autenticada está ligada a esta tienda BTCPay; no hay ruta global.
                'account_ref': attempt.account_ref})

    def create_payment(self, attempt):
        try:
            self.config_for(attempt)
            data = self._api(attempt, 'POST', '/api/v1/stores/' + quote(attempt.account_ref, safe='') + '/invoices',
                {'amount': str(attempt.amount), 'currency': attempt.currency,
                 'metadata': {'orderId': str(attempt.order.public_id), 'attemptId': str(attempt.public_id)}})
            return self._normalise(data, attempt)
        except (ProviderError, ValueError, TypeError) as exc:
            return self.failure(exc if isinstance(exc, ProviderError) else ProviderError('Factura no confirmada.', ambiguous=True))

    def get_payment(self, attempt):
        try:
            if not attempt.external_ref:
                raise ProviderError('Factura sin referencia: revisar BTCPay antes de crear otra.')
            return self._normalise(self._api(attempt, 'GET', '/api/v1/stores/' + quote(attempt.account_ref, safe='') +
                '/invoices/' + quote(attempt.external_ref, safe='')), attempt)
        except (ProviderError, ValueError, TypeError) as exc:
            return self.failure(exc if isinstance(exc, ProviderError) else ProviderError('Respuesta de factura inválida.'))

    def notification_reference(self, parsed):
        return str(parsed.get('invoiceId') or '')

    def verify_notification(self, headers, raw_body, attempt=None):
        try:
            config = self.config_for(attempt)
            headers = {key.lower(): value for key, value in headers.items()}
            signature = 'sha256=' + hmac.new(config['WEBHOOK_SECRET'].encode(), raw_body, hashlib.sha256).hexdigest()
            return hmac.compare_digest(signature, headers.get('btcpay-sig', '')) and json.loads(raw_body).get('storeId') == attempt.account_ref
        except (ProviderError, ValueError, TypeError):
            return False

    def refund(self, attempt, amount=None, note=''):
        # Un pull payment es una solicitud: nunca equivale a fondos ya devueltos.
        try:
            data = self._api(attempt, 'POST', '/api/v1/invoices/' + quote(attempt.external_ref, safe='') + '/refund',
                {'name': 'Reembolso ' + str(attempt.order.reference), 'description': note[:200],
                 'refundVariant': 'Custom', 'customAmount': str(amount), 'customCurrency': attempt.currency})
            if not data.get('id'):
                raise ProviderError('BTCPay no confirmó la solicitud de devolución.', ambiguous=True)
            return AdapterResponse(ok=True, provider=self.key, state='refund_pending',
                external_ref=data['id'], amount=str(amount), safe={'claim_url': data.get('viewLink', '')})
        except (ProviderError, ValueError, TypeError) as exc:
            return self.failure(exc if isinstance(exc, ProviderError) else ProviderError('Devolución no confirmada.', ambiguous=True))
