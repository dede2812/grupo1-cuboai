"""Despacho manual visible: permisos, cantidades, reintentos y evidencia."""
from django.contrib.auth.models import User
from django.test import Client, override_settings
from django.urls import reverse

from reino import services_commerce as commerce, services_payments as pay
from reino.models import MerchantMember
from reino.tests.test_shipping import ShippingBase
from reino.tests.test_provider_contracts import CONFIG


class ShippingViewTests(ShippingBase):
    def setUp(self):
        self.user = User.objects.create_user('shipping-owner', password='test')
        self.member = MerchantMember.objects.create(user=self.user, merchant=self.merchant_a, role='owner')
        self.client.force_login(self.user)
        self.order = self._order(qty=2)
        self.url = reverse('reino_merchant_shipments', args=[self.store_a.slug, self.order.public_id])
        self.create_url = reverse('reino_merchant_shipment_create', args=[self.store_a.slug, self.order.public_id])

    def form(self, quantity=1):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return {'action_token': response.context['action_token'],
                f'quantity_{self.order.items.get().pk}': quantity}

    def update_url(self, shipment):
        return reverse('reino_merchant_shipment_update', args=[self.store_a.slug, self.order.public_id, shipment.public_id])

    def test_two_identical_partials_and_repeated_form_are_distinct_correctly(self):
        first = self.form()
        self.client.post(self.create_url, first)
        self.client.post(self.create_url, first)
        self.assertEqual(self.order.shipments.count(), 1)
        self.client.post(self.create_url, self.form())
        self.assertEqual(self.order.shipments.count(), 2)
        self.assertContains(self.client.get(self.url), 'No hay unidades físicas pendientes')

    def test_dispatch_changes_keep_actor_evidence_and_tracking(self):
        self.client.post(self.create_url, self.form())
        shipment = self.order.shipments.get()
        response = self.client.post(self.update_url(shipment), {'status': 'in_transit', 'note': 'Retirado por mensajero', 'tracking': 'LOCAL-123'})
        self.assertEqual(response.status_code, 302)
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, 'in_transit')
        self.assertEqual(shipment.tracking, 'LOCAL-123')
        self.assertTrue(self.order.events.filter(by=self.user, note='Retirado por mensajero').exists())
        self.client.post(self.update_url(shipment), {'status': 'cancelled', 'note': 'No sale'})
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, 'in_transit')

    def test_missing_evidence_cannot_change_state(self):
        self.client.post(self.create_url, self.form())
        shipment = self.order.shipments.get()
        self.client.post(self.update_url(shipment), {'status': 'delivered'})
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, 'preparing')

    def test_tracking_can_be_updated_without_fabricating_a_state_change(self):
        self.client.post(self.create_url, self.form())
        shipment = self.order.shipments.get()
        self.client.post(self.update_url(shipment), {'status': 'preparing', 'note': 'Asignación de mensajero', 'tracking': 'LOCAL-124'})
        shipment.refresh_from_db()
        self.assertEqual(shipment.status, 'preparing')
        self.assertEqual(shipment.tracking, 'LOCAL-124')
        self.assertTrue(self.order.events.filter(field='shipment_tracking', by=self.user).exists())

    def test_logistics_role_can_dispatch_but_foreign_store_cannot(self):
        self.member.role = 'logistics'; self.member.save()
        self.client.post(self.create_url, self.form())
        self.assertEqual(self.order.shipments.count(), 1)
        self.member.merchant = self.merchant_b; self.member.save()
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.create_url, {}).status_code, 403)

    def test_signed_token_cannot_be_reused_for_another_order(self):
        data = self.form()
        other = self._order('other-shipping')
        data = {**data, f'quantity_{other.items.get().pk}': 1}
        target = reverse('reino_merchant_shipment_create', args=[self.store_a.slug, other.public_id])
        self.client.post(target, data)
        self.assertFalse(other.shipments.exists())

    def test_tampered_token_and_excess_quantity_do_not_create_shipment(self):
        self.client.post(self.create_url, {'action_token': 'not-signed', f'quantity_{self.order.items.get().pk}': 1})
        self.client.post(self.create_url, self.form(quantity=3))
        self.assertFalse(self.order.shipments.exists())

    def test_create_is_post_only_and_requires_csrf(self):
        self.assertEqual(self.client.get(self.create_url).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(self.create_url, self.form()).status_code, 403)


class CheckoutConfigurationCopyTests(ShippingBase):
    def checkout(self):
        session = self.client.session
        session['reino_seeded'] = True
        session.save()
        cart = commerce.get_open_cart(self.store_a, session.session_key, create=True)
        commerce.add_item(cart, self.product.variants.get(option_label='Talla M'), 1)
        return self.client.get(reverse('reino_checkout', args=[self.store_a.slug]))

    @override_settings(REINO_PAYMENT_ACCOUNTS=CONFIG)
    def test_enabled_provider_copy_uses_shared_configuration(self):
        response = self.checkout()
        self.assertContains(response, 'PayPal (pruebas)')
        self.assertNotContains(response, 'Ningún cobro electrónico')
        self.assertEqual(pay.configured_checkout_options(self.store_a, 'bitcoin')[0]['provider'], 'btcpay')

    @override_settings(REINO_PAYMENT_ACCOUNTS={})
    def test_unconfigured_checkout_explicitly_uses_manual_payment(self):
        self.assertContains(self.checkout(), 'Ningún cobro electrónico está habilitado')
