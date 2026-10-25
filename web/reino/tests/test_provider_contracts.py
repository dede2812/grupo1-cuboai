"""HTTP contract tests. Mocked transport does NOT certify provider connectivity."""
import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch
from django.core import signing
from django.test import Client, override_settings
from django.urls import reverse
from reino import services_payments as pay
from reino.models import PaymentAttempt
from reino.payments.http import ProviderError, request_json
from reino.tests.test_payments import PaymentBase

CONFIG = {
    'paypal': {'wk-test': {'ACCOUNT_REF': 'merchant-A', 'CLIENT_ID': 'client', 'CLIENT_SECRET': 'test-secret',
        'WEBHOOK_ID': 'hook', 'ENVIRONMENT': 'test', 'RETURN_URL': 'https://shop.example/pagos/retorno/paypal/',
        'CANCEL_URL': 'https://shop.example/'}},
    'btcpay': {'wk-test': {'ACCOUNT_REF': 'btc-store', 'API_KEY': 'test-api', 'WEBHOOK_SECRET': 'test-webhook',
        'ENVIRONMENT': 'test', 'BASE_URL': 'https://btc.example'}},
    'wompi': {'wk-test': {'ACCOUNT_REF': 'app-id', 'CLIENT_ID': 'app-id', 'CLIENT_SECRET': 'test-secret',
        'ENVIRONMENT': 'test', 'WEBHOOK_URL': 'https://shop.example/pagos/webhook/wompi/',
        'RETURN_URL': 'https://shop.example/pagos/retorno/wompi/'}},
}


@override_settings(REINO_PAYMENT_ACCOUNTS=CONFIG)
class ProviderContractTests(PaymentBase):
    def attempt(self, provider):
        order = self._order(provider)
        return PaymentAttempt.objects.create(order=order, provider=provider,
            amount=order.total, currency='USD', account_ref=CONFIG[provider]['wk-test']['ACCOUNT_REF'],
            idempotency_key=provider, external_ref=provider + '-ref')

    def paypal_data(self, attempt, status='COMPLETED', custom_id=None, merchant='merchant-A'):
        unit = {'custom_id': custom_id or str(attempt.order.public_id),
            'payee': {'merchant_id': merchant}, 'amount': {'value': str(attempt.amount), 'currency_code': 'USD'}}
        if status == 'COMPLETED':
            unit['payments'] = {'captures': [{'id': 'capture-1', 'status': 'COMPLETED', 'amount': unit['amount']}]}
        return {'id': attempt.external_ref, 'status': status, 'purchase_units': [unit]}

    def test_paypal_creation_uses_server_amount_and_idempotency_header(self):
        attempt = self.attempt('paypal')
        data = self.paypal_data(attempt, 'CREATED')
        with patch('reino.payments.paypal.request_json', side_effect=[{'access_token': 'token'}, data]) as http:
            result = pay.adapter_for('paypal').create_payment(attempt)
        self.assertTrue(result.ok)
        call = http.call_args_list[1]
        self.assertEqual(call.args[1], 'https://api-m.sandbox.paypal.com/v2/checkout/orders')
        self.assertEqual(call.args[2]['PayPal-Request-Id'], str(attempt.public_id))
        self.assertEqual(call.kwargs['payload']['purchase_units'][0]['amount']['value'], str(attempt.order.total))
        self.assertIn('state=', call.kwargs['payload']['payment_source']['paypal']['experience_context']['return_url'])

    def test_paypal_query_wrong_merchant_never_marks_paid(self):
        attempt = self.attempt('paypal')
        with patch('reino.payments.paypal.request_json', side_effect=[{'access_token': 'token'}, self.paypal_data(attempt, merchant='other')]):
            _, error = pay.reconcile_attempt(attempt)
        self.assertEqual(error, 'cuenta no coincide')
        attempt.order.refresh_from_db()
        self.assertEqual(attempt.order.payment_status, 'pending')

    def test_paypal_authentic_query_confirms_amount_and_capture(self):
        attempt = self.attempt('paypal')
        with patch('reino.payments.paypal.request_json', side_effect=[{'access_token': 'token'}, self.paypal_data(attempt)]):
            result, error = pay.reconcile_attempt(attempt)
        self.assertIsNone(error)
        self.assertEqual(result.state, 'captured')
        self.assertEqual(result.safe_payload['capture_id'], 'capture-1')

    def test_paypal_signature_verification_uses_official_endpoint(self):
        attempt = self.attempt('paypal')
        headers = {'PAYPAL-' + name: name for name in ('AUTH-ALGO', 'CERT-URL', 'TRANSMISSION-ID', 'TRANSMISSION-SIG', 'TRANSMISSION-TIME')}
        with patch('reino.payments.paypal.request_json', side_effect=[{'access_token': 'token'}, {'verification_status': 'SUCCESS'}]) as http:
            self.assertTrue(pay.adapter_for('paypal').verify_notification(headers, b'{}', attempt))
        self.assertTrue(http.call_args.args[1].endswith('/v1/notifications/verify-webhook-signature'))
        self.assertEqual(http.call_args.kwargs['payload']['webhook_id'], 'hook')

    def test_paypal_refund_compares_money_numerically_and_sends_idempotency_key(self):
        attempt = self.attempt('paypal')
        attempt.safe_payload = {'capture_id': 'capture-1', 'refund_request_key': 'refund-key'}
        with patch('reino.payments.paypal.request_json', side_effect=[{'access_token': 'token'},
                {'id': 'refund-1', 'status': 'COMPLETED', 'amount': {'value': '10.00', 'currency_code': 'USD'}}]) as http:
            result = pay.adapter_for('paypal').refund(attempt, amount=Decimal('10'), note='returned')
        self.assertTrue(result.ok)
        self.assertEqual(result.state, 'refunded')
        self.assertEqual(http.call_args.args[2]['PayPal-Request-Id'], 'refund-key')

    def test_btcpay_hmac_exact_body_and_store(self):
        attempt = self.attempt('btcpay')
        body = json.dumps({'storeId': 'btc-store', 'invoiceId': attempt.external_ref}).encode()
        signature = 'sha256=' + hmac.new(b'test-webhook', body, hashlib.sha256).hexdigest()
        adapter = pay.adapter_for('btcpay')
        self.assertTrue(adapter.verify_notification({'BTCPay-Sig': signature}, body, attempt))
        self.assertFalse(adapter.verify_notification({'BTCPay-Sig': signature}, body + b' ', attempt))
        self.assertFalse(adapter.verify_notification({}, body, attempt))

    def test_btcpay_refund_request_is_not_confirmed_money(self):
        attempt = self.attempt('btcpay')
        with patch('reino.payments.btcpay.request_json', return_value={'id': 'pull-1', 'viewLink': 'https://btc.example/refund'}):
            result = pay.adapter_for('btcpay').refund(attempt, Decimal('10'), 'return')
        self.assertTrue(result.ok)
        self.assertEqual(result.state, 'refund_pending')

    def test_wompi_untrusted_webhook_state_ignored_in_favour_of_api(self):
        attempt = self.attempt('wompi')
        data = {'idEnlace': attempt.external_ref, 'idAplicativo': 'app-id',
            'nombreEnlace': str(attempt.order.public_id), 'monto': float(attempt.amount),
            'estaProductivo': False, 'transaccionCompra': None}
        with patch('reino.payments.wompi.request_json', side_effect=[{'access_token': 'token'}, data]):
            result, error = pay.verify_and_apply_notification('wompi', {}, b'{}',
                {'EnlacePago': {'Id': attempt.external_ref}, 'state': 'captured'})
        self.assertIsNone(error)
        self.assertEqual(result.state, 'pending')
        attempt.order.refresh_from_db()
        self.assertEqual(attempt.order.payment_status, 'pending')

    def test_wompi_live_transaction_cannot_confirm_test_attempt(self):
        attempt = self.attempt('wompi')
        with patch('reino.payments.wompi.request_json', side_effect=[{'access_token': 'token'}, {'estaProductivo': True}]):
            result = pay.adapter_for('wompi').get_payment(attempt)
        self.assertFalse(result.ok)

    def test_transport_rejects_insecure_url_before_http(self):
        with self.assertRaises(ProviderError):
            request_json('POST', 'http://provider.example/pay', payload={})

    def test_configuration_does_not_bleed_to_other_store(self):
        self.assertFalse(pay.adapter_for('paypal').configuration(self.store_b))

    def test_malformed_webhook_nesting_does_not_raise_server_error(self):
        result, error = pay.verify_and_apply_notification('paypal', {}, b'{}', {'resource': 'not-an-object'})
        self.assertIsNone(result)
        self.assertEqual(error, 'cuerpo inválido')

    def test_bitcoin_discount_cannot_be_paid_using_card_provider(self):
        order = self._order()
        order.payment_method = 'bitcoin'
        order.save(update_fields=['payment_method'])
        self.assertEqual([row['provider'] for row in pay.checkout_options(order)], ['btcpay'])
        from reino.services_commerce import CartError
        with self.assertRaises(CartError):
            pay.create_attempt(order, 'paypal', 'discount-card')

    def test_payment_start_requires_guest_token_and_csrf(self):
        order = self._order()
        url = reverse('reino_payment_start', args=[order.store.slug, order.public_id, 'paypal'])
        self.assertEqual(self.client.post(url).status_code, 404)
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf_client.post(url, {'order_token': order.access_token}).status_code, 403)

    def test_checkout_button_starts_one_hosted_payment_across_duplicate_posts(self):
        from reino.payments.base import AdapterResponse
        order = self._order()
        url = reverse('reino_payment_start', args=[order.store.slug, order.public_id, 'paypal'])
        result = AdapterResponse(ok=True, provider='paypal', state='requires_action', external_ref='paypal-checkout',
            redirect_url='https://www.sandbox.paypal.com/checkoutnow?token=paypal-checkout', amount=str(order.total), currency='USD',
            safe={'order_id': str(order.public_id), 'account_ref': 'merchant-A'})
        with patch.object(pay.adapter_for('paypal'), 'create_payment', return_value=result) as create:
            first = self.client.post(url, {'order_token': order.access_token})
            second = self.client.post(url, {'order_token': order.access_token})
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first['Location'], result.redirect_url)
        self.assertEqual(second['Location'], result.redirect_url)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(order.payment_attempts.count(), 1)
        page = self.client.get(reverse('reino_order_guest', args=[order.store.slug, order.public_id, order.access_token]))
        self.assertContains(page, 'Continuar con el proveedor')
        self.assertNotContains(page, 'Pago confirmado.')

    def test_return_requires_initiating_session_and_matching_paypal_reference(self):
        attempt = self.attempt('paypal')
        state = signing.dumps(str(attempt.public_id), salt='reino-payment-return')
        url = reverse('reino_payment_return', args=['paypal'])
        self.assertEqual(self.client.get(url, {'state': state, 'token': attempt.external_ref}).status_code, 404)
        session = self.client.session
        session['reino_payment_attempts'] = [str(attempt.public_id)]
        session.save()
        self.assertEqual(self.client.get(url, {'state': state, 'token': 'wrong'}).status_code, 404)
        result = self.client.get(url, {'state': state, 'token': attempt.external_ref, 'success': 'true'})
        self.assertEqual(result.status_code, 302)
        attempt.order.refresh_from_db()
        self.assertEqual(attempt.order.payment_status, 'pending')

@override_settings(REINO_SHIPPING_ACCOUNTS={'mydhl': {'wk-test': {
    'USERNAME': 'test-user', 'PASSWORD': 'test-password', 'ACCOUNT_REF': 'account', 'ENVIRONMENT': 'test'}}})
class MyDHLContractTests(PaymentBase):
    def test_rates_use_test_host_measured_package_and_selected_currency(self):
        from reino.shipping.mydhl import MyDHLAdapter
        with patch('reino.shipping.mydhl.request_json', return_value={'products': [{'productCode': 'P',
                'totalPrice': [{'currencyType': 'BILLC', 'price': 27.5, 'priceCurrency': 'USD'}]}]}) as http:
            result = MyDHLAdapter().quote({'store_slug': 'wk-test', 'countryCode': 'SV', 'cityName': 'San Salvador',
                'postalCode': '1101', 'plannedShippingDate': '2026-10-25'},
                {'countryCode': 'US', 'cityName': 'Miami', 'postalCode': '33101'},
                [{'weight': 1, 'length': 20, 'width': 15, 'height': 10}], service='P')
        self.assertTrue(result.ok)
        self.assertEqual(result.amount, '27.5')
        self.assertEqual(result.currency, 'USD')
        self.assertIn('/mydhlapi/test/rates?', http.call_args.args[1])
        self.assertIn('accountNumber=account', http.call_args.args[1])

    def test_no_label_capability_is_falsely_advertised(self):
        from reino.shipping.mydhl import MyDHLAdapter
        capabilities = MyDHLAdapter().capabilities({'USERNAME': 'u', 'PASSWORD': 'p', 'ACCOUNT_REF': 'a'})
        self.assertTrue(capabilities['quote'])
        self.assertFalse(capabilities['create'])
        self.assertFalse(capabilities['label'])
        self.assertFalse(capabilities['connection_verified'])

    def test_bad_package_never_reaches_dhl(self):
        from reino.shipping.mydhl import MyDHLAdapter
        with patch('reino.shipping.mydhl.request_json') as http:
            result = MyDHLAdapter().quote({'store_slug': 'wk-test'}, {},
                [{'weight': -1, 'length': 2, 'width': 2, 'height': 2}], service='P')
        self.assertFalse(result.ok)
        http.assert_not_called()
