"""HTTP de proveedores: HTTPS, timeout, sin redirecciones ni reintentos de POST."""
import base64
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import Request, HTTPRedirectHandler, build_opener
from django.conf import settings
from .base import AdapterResponse, PaymentAdapter


class ProviderError(Exception):
    def __init__(self, message, ambiguous=False):
        super().__init__(message)
        self.ambiguous = ambiguous


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(method, url, headers=None, payload=None, form=None):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ProviderError('El proveedor requiere una URL HTTPS sin credenciales incrustadas.')
    headers = {'Accept': 'application/json', **(headers or {})}
    data = None
    if form is not None:
        data = urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    elif payload is not None:
        data = json.dumps(payload, separators=(',', ':')).encode()
        headers['Content-Type'] = 'application/json'
    try:
        with build_opener(NoRedirect()).open(Request(url, data=data, method=method, headers=headers), timeout=15) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ProviderError('Respuesta del proveedor demasiado grande.', ambiguous=method != 'GET')
            result = json.loads(raw or b'{}')
            if not isinstance(result, (dict, list)):
                raise ValueError
            return result
    except HTTPError as exc:
        raise ProviderError(f'Proveedor respondió HTTP {exc.code}; revisar el registro del proveedor.',
            ambiguous=method != 'GET' and (exc.code >= 500 or exc.code == 408)) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ProviderError('No se pudo confirmar la respuesta del proveedor; conciliar antes de reintentar.',
            ambiguous=method != 'GET') from None


def basic_auth(client_id, secret):
    return 'Basic ' + base64.b64encode(f'{client_id}:{secret}'.encode()).decode()


def accounts(setting='REINO_PAYMENT_ACCOUNTS'):
    configured = getattr(settings, setting, None)
    if configured is None:
        try:
            configured = json.loads(os.environ.get(setting, '{}'))
        except ValueError:
            return {}
    return configured if isinstance(configured, dict) else {}


class ConfiguredPaymentAdapter(PaymentAdapter):
    required = ('ACCOUNT_REF',)

    def configuration(self, store):
        config = accounts().get(self.key, {}).get(store.slug, {})
        if not isinstance(config, dict) or not all(config.get(key) for key in self.required):
            return {}
        return config

    def config_for(self, attempt):
        config = self.configuration(attempt.order.store)
        if not config or config['ACCOUNT_REF'] != attempt.account_ref or config.get('ENVIRONMENT', 'test') != attempt.environment:
            raise ProviderError('La cuenta o el entorno del proveedor no corresponden al intento.')
        return config

    def failure(self, exc):
        return AdapterResponse(ok=False, provider=self.key, error=str(exc), safe={'ambiguous': exc.ambiguous})

    def return_url(self, attempt, config):
        from django.core import signing
        url = urlsplit(config['RETURN_URL'])
        if url.scheme != 'https' or not url.hostname:
            raise ProviderError('La URL de retorno debe usar HTTPS.')
        query = dict(parse_qsl(url.query))
        query['state'] = signing.dumps(str(attempt.public_id), salt='reino-payment-return')
        return urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), ''))

    def capabilities(self, account=None):
        configured = bool(account and all(account.get(key) for key in self.required))
        return {'create': configured, 'capture': False, 'refund': False,
            'webhook': configured, 'hosted': configured, 'configured': configured,
            'connection_verified': False}
