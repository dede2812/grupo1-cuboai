"""MyDHL API: tarifas y seguimiento autenticados; capacidades sin inventar."""
from urllib.parse import urlencode, quote
from decimal import Decimal, InvalidOperation
from .base import ShipResponse, ShippingAdapter
from ..payments.http import ProviderError, accounts, basic_auth, request_json


class MyDHLAdapter(ShippingAdapter):
    key = 'mydhl'
    label = 'DHL Express · MyDHL'

    def configuration(self, store_slug):
        config = accounts('REINO_SHIPPING_ACCOUNTS').get(self.key, {}).get(store_slug, {})
        if not all(config.get(key) for key in ('USERNAME', 'PASSWORD', 'ACCOUNT_REF')):
            raise ProviderError('MyDHL no configurado para esta tienda.')
        return config

    def capabilities(self, account=None):
        configured = bool(account and all(account.get(key) for key in ('USERNAME', 'PASSWORD', 'ACCOUNT_REF')))
        return {'quote': configured, 'track': configured, 'create': False, 'label': False,
            'cancel': False, 'configured': configured, 'connection_verified': False}

    def _api(self, config, path):
        base = 'https://express.api.dhl.com/mydhlapi'
        if config.get('ENVIRONMENT', 'test') == 'test':
            base += '/test'
        elif config.get('ENVIRONMENT') != 'live':
            raise ProviderError('Entorno MyDHL inválido.')
        return request_json('GET', base + path,
            {'Authorization': basic_auth(config['USERNAME'], config['PASSWORD']), 'x-version': '3.3.4'})

    def quote(self, origin, destination, packages, service=None):
        try:
            config = self.configuration(origin.get('store_slug', ''))
            if len(packages) != 1:
                raise ProviderError('Esta cotización MyDHL requiere exactamente un paquete medido.')
            package = packages[0]
            numbers = {key: Decimal(str(package[key])) for key in ('weight', 'length', 'width', 'height')}
            if any(not value.is_finite() or value <= 0 for value in numbers.values()):
                raise ProviderError('Peso y dimensiones deben ser positivos y finitos.')
            query = {'accountNumber': config['ACCOUNT_REF'], 'originCountryCode': origin['countryCode'],
                'originPostalCode': origin.get('postalCode', ''), 'originCityName': origin['cityName'],
                'destinationCountryCode': destination['countryCode'], 'destinationPostalCode': destination.get('postalCode', ''),
                'destinationCityName': destination['cityName'], 'plannedShippingDate': origin['plannedShippingDate'],
                'isCustomsDeclarable': 'true' if origin['countryCode'] != destination['countryCode'] else 'false',
                'unitOfMeasurement': 'metric', **numbers}
            data = self._api(config, '/rates?' + urlencode(query))
            products = [product for product in data.get('products', []) if not service or product.get('productCode') == service]
            if len(products) != 1:
                raise ProviderError('Seleccioná un servicio DHL disponible antes de confirmar la tarifa.')
            product = products[0]
            prices = [price for price in product.get('totalPrice', []) if price.get('currencyType') == 'BILLC']
            if len(prices) != 1:
                raise ProviderError('DHL no devolvió una tarifa de facturación inequívoca.')
            return ShipResponse(ok=True, provider=self.key, state='quoted', amount=str(prices[0]['price']),
                currency=prices[0]['priceCurrency'], safe={'service': product['productCode'], 'estimated': True})
        except (ProviderError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return ShipResponse(ok=False, provider=self.key, error=str(exc) if isinstance(exc, ProviderError) else 'Dirección o paquete incompleto.')

    def track(self, shipment):
        try:
            config = self.configuration(shipment.order.store.slug)
            # Sin AWB se consulta por referencia + cuenta; jamás se compra otra etiqueta.
            query = ({'shipmentTrackingNumber': shipment.external_ref} if shipment.external_ref else
                {'shipmentReference': str(shipment.public_id), 'shipperAccountNumber': config['ACCOUNT_REF']})
            data = self._api(config, '/tracking?' + urlencode(query))
            matches = data.get('shipments') or []
            if len(matches) != 1:
                raise ProviderError('DHL no devolvió un único envío; requiere conciliación.')
            record = matches[0]
            if shipment.external_ref and record.get('shipmentTrackingNumber') != shipment.external_ref:
                raise ProviderError('La referencia DHL no coincide.')
            events = record.get('events') or []
            event = sorted(events, key=lambda e: (e.get('date', ''), e.get('time', '')))[-1] if events else {}
            code = event.get('typeCode')
            state = {'OK': 'delivered', 'PU': 'picked_up', 'DF': 'in_transit', 'AF': 'in_transit',
                'PL': 'in_transit', 'WC': 'in_transit'}.get(code, '')
            return ShipResponse(ok=True, provider=self.key, state=state, provider_state=code or '',
                external_ref=record.get('shipmentTrackingNumber', ''), tracking=record.get('shipmentTrackingNumber', ''),
                safe={'events': [{'code': e.get('typeCode'), 'date': e.get('date'), 'time': e.get('time')} for e in events]})
        except (ProviderError, KeyError, TypeError, ValueError) as exc:
            return ShipResponse(ok=False, provider=self.key, error=str(exc) if isinstance(exc, ProviderError) else 'Respuesta DHL inválida.')

    def create_shipment(self, shipment):
        return ShipResponse(ok=False, provider=self.key,
            error='La compra de etiqueta MyDHL requiere completar el paquete, origen y declaración aduanera y validar la cuenta; todavía no está habilitada.')
