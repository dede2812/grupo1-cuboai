"""Regresiones financieras y de despacho descubiertas durante el cierre final."""
from decimal import Decimal
from unittest.mock import patch
from django.urls import reverse
from reino import services_payments as pay, services_shipping as ship, services_commerce as commerce
from reino.models import PaymentAttempt, Shipment, Order
from reino.payments.base import AdapterResponse
from reino.shipping.base import ShipResponse
from reino.tests.test_payments import PaymentBase
from reino.tests.test_shipping import ShippingBase


class PaymentIntegrityTests(PaymentBase):
    def captured(self, provider='fake'):
        order = self._order()
        attempt, _ = pay.create_attempt(order, provider, 'integrity-pay')
        attempt, _ = pay.apply_provider_state(attempt, 'captured')
        return order, attempt

    def test_idempotency_key_cannot_cross_orders(self):
        first = self._order('one')
        second = self._order('two')
        pay.create_attempt(first, 'fake', 'shared')
        with self.assertRaises(commerce.CartError):
            pay.create_attempt(second, 'fake', 'shared')

    def test_active_attempt_blocks_second_charge(self):
        order = self._order()
        pay.create_attempt(order, 'fake', 'one')
        with self.assertRaises(commerce.CartError):
            pay.create_attempt(order, 'fake', 'two')

    def test_capture_and_order_effects_roll_back_together(self):
        order = self._order()
        attempt, _ = pay.create_attempt(order, 'fake', 'atomic')
        with patch.object(commerce, 'apply_transition', side_effect=commerce.CartError('failure')):
            with self.assertRaises(commerce.CartError):
                pay.apply_provider_state(attempt, 'captured', event_id='atomic')
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, 'requires_action')
        self.assertFalse(attempt.events.filter(provider_event_id='atomic').exists())

    def test_capture_records_captured_amount(self):
        _, attempt = self.captured()
        self.assertEqual(attempt.captured_amount, attempt.amount)

    def test_arbitrary_state_is_rejected(self):
        _, attempt = self.captured()
        with self.assertRaises(commerce.CartError):
            pay.apply_provider_state(attempt, 'banana')

    def test_multiple_partial_refunds_accumulate_and_default_refunds_remaining(self):
        order, stale = self.captured()
        pay.refund_attempt(stale, 10, 'first', idempotency_key='r1')
        pay.refund_attempt(stale, 15, 'second', idempotency_key='r2')
        order.refresh_from_db()
        self.assertEqual(order.refund_amount, Decimal('25'))
        final = pay.refund_attempt(stale, note='remaining', idempotency_key='r3')
        order.refresh_from_db()
        self.assertEqual(final.refunded_amount, final.amount)
        self.assertEqual(order.refund_amount, order.total)

    def test_duplicate_refund_request_never_calls_provider_twice(self):
        _, attempt = self.captured()
        adapter = pay.adapter_for('fake')
        with patch.object(adapter, 'refund', wraps=adapter.refund) as request:
            pay.refund_attempt(attempt, 10, 'same', idempotency_key='same')
            pay.refund_attempt(attempt, 10, 'same', idempotency_key='same')
        self.assertEqual(request.call_count, 1)

    def test_stale_object_cannot_refund_more_than_remaining(self):
        _, stale = self.captured()
        pay.refund_attempt(stale, 50, 'first')
        with self.assertRaises(commerce.CartError):
            pay.refund_attempt(stale, 20, 'second')

    def test_manual_refund_stays_pending_without_claiming_money_returned(self):
        order, attempt = self.captured('manual')
        attempt = pay.refund_attempt(attempt, 10, 'bank request')
        order.refresh_from_db()
        self.assertEqual(attempt.state, 'refund_pending')
        self.assertEqual(attempt.refunded_amount, 0)
        self.assertEqual(order.payment_status, 'paid')
        self.assertFalse(order.refund_amount)

    def test_ambiguous_refund_preserves_reservation_and_blocks_retry(self):
        _, attempt = self.captured()
        with patch.object(pay.adapter_for('fake'), 'refund', return_value=AdapterResponse(
                ok=False, provider='fake', error='timeout', safe={'ambiguous': True})) as request:
            with self.assertRaises(commerce.CartError):
                pay.refund_attempt(attempt, 10, 'ambiguous', idempotency_key='timeout')
            pay.refund_attempt(attempt, 10, 'ambiguous', idempotency_key='timeout')
            self.assertEqual(request.call_count, 1)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, 'refund_pending')
        self.assertEqual(attempt.refunded_amount, 0)

    def test_fake_public_webhook_is_unavailable(self):
        response = self.client.post(reverse('reino_payment_webhook', args=['fake']),
            data='{}', content_type='application/json', HTTP_X_FAKE_SIGNATURE='firma-de-prueba')
        self.assertEqual(response.status_code, 404)

    def test_refund_webhook_arriving_before_http_response_is_not_counted_twice(self):
        order, attempt = self.captured()
        def response_with_racing_webhook(current, amount=None, note=''):
            pay.apply_provider_state(current, 'partially_refunded', refunded_amount=amount, event_id='racing-hook')
            return AdapterResponse(ok=True, provider='fake', state='refunded', amount=str(amount))
        with patch.object(pay.adapter_for('fake'), 'refund', side_effect=response_with_racing_webhook):
            result = pay.refund_attempt(attempt, 10, 'race', idempotency_key='race')
        order.refresh_from_db()
        self.assertEqual(result.refunded_amount, Decimal('10'))
        self.assertEqual(order.refund_amount, Decimal('10'))

    def test_verified_refund_survives_later_http_error_or_pending_response(self):
        for response in (
            AdapterResponse(ok=False, provider='fake', error='rejected'),
            AdapterResponse(ok=False, provider='fake', error='timeout', safe={'ambiguous': True}),
            AdapterResponse(ok=True, provider='fake', state='refund_pending'),
        ):
            with self.subTest(response=response):
                order = self._order('racing-' + str(len(PaymentAttempt.objects.all())))
                attempt, _ = pay.create_attempt(order, 'fake', 'racing-' + str(order.pk))
                attempt, _ = pay.apply_provider_state(attempt, 'captured')
                def response_with_racing_webhook(current, amount=None, note=''):
                    pay.apply_provider_state(current, 'partially_refunded', refunded_amount=amount,
                        event_id='verified-refund')
                    return response
                with patch.object(pay.adapter_for('fake'), 'refund', side_effect=response_with_racing_webhook) as request:
                    result = pay.refund_attempt(attempt, 10, 'race', idempotency_key='verified-race')
                    pay.refund_attempt(attempt, 10, 'race', idempotency_key='verified-race')
                self.assertEqual(request.call_count, 1)
                self.assertEqual(result.state, 'partially_refunded')
                self.assertEqual(result.refunded_amount, Decimal('10'))
                self.assertEqual(result.events.get(kind='refund-request').payload['status'], 'completed')
                order.refresh_from_db()
                self.assertEqual(order.payment_status, 'partially_refunded')
                self.assertEqual(order.refund_amount, Decimal('10'))

    def test_full_refund_rejects_incomplete_refund_amount(self):
        order, attempt = self.captured()
        with self.assertRaises(commerce.CartError):
            pay.apply_provider_state(attempt, 'refunded', refunded_amount=Decimal('1'), event_id='invalid-full')
        attempt.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(attempt.state, 'captured')
        self.assertEqual(order.payment_status, 'paid')
        self.assertFalse(attempt.events.filter(provider_event_id='invalid-full').exists())

    def test_reconciliation_rejects_wrong_amount(self):
        order, attempt = self.captured()
        with patch.object(pay.adapter_for('fake'), 'get_payment', return_value=AdapterResponse(
            ok=True, provider='fake', external_ref=attempt.external_ref, amount='0.01', currency='USD', state='refunded')):
            _, error = pay.reconcile_attempt(attempt)
        self.assertIsNotNone(error)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')


class ShippingIntegrityTests(ShippingBase):
    def test_legacy_delivery_history_does_not_restore_shipped_stock_after_incident(self):
        for final_delivery in ('incident', 'returned'):
            with self.subTest(final_delivery=final_delivery):
                order = self._order('legacy-' + final_delivery, qty=2)
                variant = order.items.get().variant
                before = variant.stock
                for state in ('scheduled', 'shipped', final_delivery):
                    commerce.apply_transition(order, 'delivery_status', state)
                commerce.apply_transition(order, 'status', 'cancelled')
                variant.refresh_from_db()
                self.assertEqual(variant.stock, before)
                order.refresh_from_db()
                self.assertIsNone(order.stock_restored_at)

    def test_transit_history_survives_incident_and_blocks_false_restock(self):
        order = self._order(qty=2)
        item = order.items.get()
        variant = item.variant
        before = variant.stock
        shipment = ship.create_shipment(order, lines=[{'order_item_id': item.pk, 'quantity': 1}])
        ship.mark_status(shipment, 'in_transit')
        ship.mark_status(shipment, 'issue')
        with self.assertRaises(commerce.CartError):
            ship.mark_status(shipment, 'cancelled')
        commerce.apply_transition(order, 'status', 'cancelled')
        variant.refresh_from_db()
        self.assertEqual(variant.stock, before + 1)
        self.assertEqual(order.shipments.get().status, 'issue')

    def test_distinct_operation_keys_allow_identical_partial_dispatches(self):
        order = self._order(qty=2)
        lines = [{'order_item_id': order.items.get().pk, 'quantity': 1}]
        first = ship.create_shipment(order, lines=lines, idempotency_key='parcel-1')
        second = ship.create_shipment(order, lines=lines, idempotency_key='parcel-2')
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(ship.create_shipment(order, lines=lines, idempotency_key='parcel-1').pk, first.pk)
        self.assertEqual(ship.create_shipment(order, idempotency_key='parcel-2').pk, second.pk)
        self.assertEqual(ship.shippable_lines(order), [])
        with self.assertRaises(commerce.CartError):
            ship.create_shipment(order, lines=lines, idempotency_key='parcel-3')

    def test_operation_key_cannot_change_dispatch_contents(self):
        order = self._order(qty=2)
        line = {'order_item_id': order.items.get().pk, 'quantity': 1}
        ship.create_shipment(order, lines=[line], address={'city': 'A'}, idempotency_key='parcel')
        for overrides in ({'lines': [{**line, 'quantity': 2}]}, {'address': {'city': 'B'}}, {'service': 'other'}):
            with self.subTest(overrides=overrides), self.assertRaises(commerce.CartError):
                ship.create_shipment(order, idempotency_key='parcel', **overrides)
        self.assertEqual(order.shipments.count(), 1)

    def test_explicit_operation_key_retries_uncertain_dispatch_without_http(self):
        order = self._order()
        with patch.object(ship.adapter_for('manual'), 'create_shipment', return_value=ShipResponse(
                ok=False, provider='manual', error='timeout', safe={'ambiguous': True})) as request:
            with self.assertRaises(commerce.CartError):
                ship.create_shipment(order, idempotency_key='uncertain')
            existing = ship.create_shipment(order, idempotency_key='uncertain')
        self.assertEqual(request.call_count, 1)
        self.assertEqual(existing.status, 'issue')

    def test_explicit_full_dispatch_retry_is_idempotent(self):
        order = self._order(qty=2)
        lines = [{'order_item_id': order.items.get().pk, 'quantity': 2}]
        first = ship.create_shipment(order, lines=lines)
        self.assertEqual(ship.create_shipment(order, lines=lines).pk, first.pk)

    def test_duplicate_lines_cannot_overdispatch(self):
        order = self._order(qty=2)
        line = {'order_item_id': order.items.get().pk, 'quantity': 2}
        with self.assertRaises(commerce.CartError):
            ship.create_shipment(order, lines=[line, line])
        self.assertFalse(order.shipments.exists())

    def test_explicit_digital_line_cannot_be_dispatched(self):
        order = self._order()
        item = order.items.get()
        if hasattr(item, 'offer_type'):
            item.offer_type = 'digital'
            item.save(update_fields=['offer_type'])
        else:
            item.variant.product.offer_type = 'digital'
            item.variant.product.save()
        with self.assertRaises(commerce.CartError):
            ship.create_shipment(order, lines=[{'order_item_id': item.pk, 'quantity': 1}])

    def test_cross_order_lines_are_rejected_as_domain_error(self):
        first = self._order('first')
        second = self._order('second')
        with self.assertRaises(commerce.CartError):
            ship.create_shipment(first, lines=[{'order_item_id': second.items.get().pk, 'quantity': 1}])

    def test_definitive_provider_failure_releases_shipping_reservation(self):
        order = self._order()
        with patch.object(ship.adapter_for('manual'), 'create_shipment', return_value=ShipResponse(
                ok=False, provider='manual', error='address rejected')):
            with self.assertRaises(commerce.CartError):
                ship.create_shipment(order)
        self.assertEqual(ship.shippable_lines(order)[0]['pending'], 2)
        self.assertEqual(order.shipments.get().status, 'cancelled')

    def test_timeout_never_creates_duplicate_label(self):
        order = self._order()
        with patch.object(ship.adapter_for('manual'), 'create_shipment', return_value=ShipResponse(
                ok=False, provider='manual', error='timeout', safe={'ambiguous': True})) as request:
            with self.assertRaises(commerce.CartError):
                ship.create_shipment(order)
            existing = ship.create_shipment(order)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(existing.status, 'issue')

    def test_shipped_units_are_not_restocked_by_order_cancellation(self):
        order = self._order(qty=2)
        variant = order.items.get().variant
        variant.refresh_from_db()
        stock = variant.stock
        shipment = ship.create_shipment(order)
        ship.mark_status(shipment, 'in_transit')
        commerce.apply_transition(order, 'status', 'cancelled')
        variant.refresh_from_db()
        self.assertEqual(variant.stock, stock)

    def test_cancelled_order_cannot_ship(self):
        order = self._order()
        commerce.apply_transition(order, 'status', 'cancelled')
        with self.assertRaises(commerce.CartError):
            ship.create_shipment(order)

    def test_partial_dispatch_cancellation_restores_only_units_still_in_store(self):
        order = self._order(qty=2)
        item = order.items.get()
        variant = item.variant
        original = variant.stock
        shipment = ship.create_shipment(order, lines=[{'order_item_id': item.pk, 'quantity': 1}])
        ship.mark_status(shipment, 'in_transit')
        commerce.apply_transition(order, 'status', 'cancelled')
        commerce.apply_transition(order, 'status', 'cancelled')
        variant.refresh_from_db()
        self.assertEqual(variant.stock, original + 1)

# Races require the row-lock semantics of PostgreSQL, not SQLite emulation.
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.db import connection, connections, close_old_connections
from django.test import TransactionTestCase
from reino.models import Merchant, Store


@skipUnless(connection.vendor == 'postgresql', 'Carrera real requiere PostgreSQL')
class PaymentPostgresRaceTests(TransactionTestCase):
    def setUp(self):
        merchant = Merchant.objects.create(name='Race merchant', status='pilot')
        store = Store.objects.create(merchant=merchant, slug='payment-race', name='Race', status='active')
        self.order = Order.objects.create(store=store, reference='RACE-1', idempotency_key='race-order',
            subtotal=100, total=100, shipping_amount=0, customer_name='Race', customer_email='race@example.invalid',
            payment_status='paid')
        self.attempt = PaymentAttempt.objects.create(order=self.order, provider='fake', amount=100,
            captured_amount=100, currency='USD', state='captured', external_ref='fake-race', idempotency_key='race-attempt')

    def run_race(self, amounts):
        barrier = Barrier(2)
        def worker(index):
            close_old_connections()
            try:
                stale = PaymentAttempt.objects.get(pk=self.attempt.pk)
                barrier.wait(timeout=10)
                result = pay.refund_attempt(stale, amounts[index], 'race', idempotency_key=f'race-{index}')
                return ('ok', result.refunded_amount)
            except commerce.CartError as exc:
                return ('rejected', str(exc))
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, (0, 1)))

    def test_two_refunds_cannot_exceed_captured_amount(self):
        outcomes = self.run_race([70, 70])
        self.attempt.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual([outcome[0] for outcome in outcomes].count('ok'), 1)
        self.assertEqual([outcome[0] for outcome in outcomes].count('rejected'), 1)
        self.assertEqual(self.attempt.refunded_amount, Decimal('70'))
        self.assertEqual(self.order.refund_amount, Decimal('70'))
