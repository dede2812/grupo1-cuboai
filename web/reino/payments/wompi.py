"""Wompi El Salvador: enlaces USD de un uso. No usar el contrato colombiano.

El webhook documentado no firma el cuerpo: es sólo una señal para hacer GET
con OAuth y comprobar el enlace, aplicativo, entorno, referencia e importe.
"""
from urllib.parse import quote
from decimal import Decimal, InvalidOperation
from .base import AdapterResponse
from .http import ConfiguredPaymentAdapter, ProviderError, request_json


class WompiAdapter(ConfiguredPaymentAdapter):
    key = 'wompi'
    label = 'Tarjetas · Wompi El Salvador'
    required = ('ACCOUNT_REF', 'CLIENT_ID', 'CLIENT_SECRET', 'WEBHOOK_URL', 'RETURN_URL')
    notification_requires_lookup = True

    def _api(self, attempt, method, path, payload=None):
        config = self.config_for(attempt)
        if config['CLIENT_ID'] != attempt.account_ref:
            raise ProviderError('El aplicativo Wompi debe corresponder a la cuenta del intento.')
        token = request_json('POST', 'https://id.wompi.sv/connect/token', form={
            'grant_type': 'client_credentials', 'client_id': config['CLIENT_ID'],
            'client_secret': config['CLIENT_SECRET'], 'scope': 'wompi_api'})
        if not token.get('access_token'):
            raise ProviderError('Wompi no devolvió un token.')
        return request_json(method, 'https://api.wompi.sv' + path,
            {'Authorization': 'Bearer ' + token['access_token']}, payload=payload)

    def create_payment(self, attempt):
        try:
            config = self.config_for(attempt)
            if attempt.currency != 'USD':
                raise ProviderError('Este adaptador Wompi El Salvador sólo admite USD.')
            data = self._api(attempt, 'POST', '/EnlacePago', {
                'identificadorEnlaceComercio': str(attempt.order.public_id), 'nombreProducto': attempt.order.reference,
                'monto': float(attempt.amount), 'limitesDeUso': {'cantidadMaximaPagosExitosos': 1},
                'configuracion': {'esMontoEditable': False, 'esCantidadEditable': False, 'cantidadPorDefecto': 1,
                    'urlWebhook': config['WEBHOOK_URL'], 'urlRedirect': self.return_url(attempt, config),
                    'notificarTransaccionCliente': False}})
            if data.get('estaProductivo') is not (attempt.environment == 'live'):
                raise ProviderError('El entorno del enlace Wompi no coincide.', ambiguous=True)
            if not data.get('idEnlace') or not data.get('urlEnlace'):
                raise ProviderError('Wompi no devolvió un enlace verificable.', ambiguous=True)
            return AdapterResponse(ok=True, provider=self.key, state='requires_action',
                external_ref=str(data['idEnlace']), redirect_url=data['urlEnlace'], amount=str(attempt.amount), currency='USD',
                safe={'order_id': str(attempt.order.public_id), 'account_ref': attempt.account_ref})
        except (ProviderError, ValueError, TypeError) as exc:
            return self.failure(exc if isinstance(exc, ProviderError) else ProviderError('Enlace Wompi no confirmado.', ambiguous=True))

    def get_payment(self, attempt):
        try:
            if not attempt.external_ref:
                raise ProviderError('Enlace sin referencia: conciliar en Wompi antes de crear otro.')
            data = self._api(attempt, 'GET', '/EnlacePago/' + quote(attempt.external_ref, safe=''))
            if data.get('estaProductivo') is not (attempt.environment == 'live'):
                raise ProviderError('El entorno Wompi no coincide.')
            tx = data.get('transaccionCompra') or {}
            approved = tx.get('esAprobada') is True
            if approved and tx.get('esReal') is not (attempt.environment == 'live'):
                raise ProviderError('El entorno de la transacción Wompi no coincide.')
            if approved and str(tx.get('monto')) != str(data.get('monto')):
                if Decimal(str(tx.get('monto'))) != Decimal(str(data.get('monto'))):
                    raise ProviderError('El importe del cobro Wompi no coincide con el enlace.')
            return AdapterResponse(ok=True, provider=self.key, state='captured' if approved else 'pending',
                external_ref=str(data.get('idEnlace', '')), amount=str(tx.get('monto') if approved else data.get('monto', '')),
                currency='USD', provider_state='approved' if approved else 'awaiting_payment',
                safe={'order_id': str(data.get('nombreEnlace', '')), 'account_ref': str(data.get('idAplicativo', '')),
                      'transaction_id': tx.get('idTransaccion', '')})
        except (ProviderError, ValueError, TypeError, InvalidOperation) as exc:
            return self.failure(exc if isinstance(exc, ProviderError) else ProviderError('Respuesta Wompi inválida.'))

    def notification_reference(self, parsed):
        return str((parsed.get('EnlacePago') or {}).get('Id') or '')

    def refund(self, attempt, amount=None, note=''):
        return AdapterResponse(ok=False, provider=self.key,
            error='La API pública Wompi SV consultada no documenta reembolso de estos enlaces; tramitarlo y conciliar evidencia en Wompi.')
