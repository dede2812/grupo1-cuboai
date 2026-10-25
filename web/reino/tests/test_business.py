"""Accounting/cohort definitions, privacy, attribution and report HTTP contracts."""
from datetime import timedelta
from decimal import Decimal
import csv
import io

from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from reino.models import AnalyticsEvent, Cart, MerchantMember, Order, OrderItem
from reino.services_analytics import track_once
from reino.services_business import ReportFilters, build_report, financial_summary, order_scope, percent_change
from reino.tests import ReinoTestCase


class BusinessTests(ReinoTestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.filters = ReportFilters(self.today - timedelta(days=6), self.today)
        self.owner = User.objects.create_user(username="owner-bi", password="x")
        MerchantMember.objects.create(user=self.owner, merchant=self.merchant_a, role="owner")
        self.client.force_login(self.owner)
        self.path = f"/negocio/{self.store_a.slug}/estadisticas/"
        self.serial = 0

    def order(self, store=None, days_ago=1, **kwargs):
        self.serial += 1
        store = store or self.store_a
        data = dict(store=store, reference=f"BI-{self.serial}", idempotency_key=f"bi-{self.serial}",
                    subtotal=Decimal("100.00"), discount_amount=Decimal("10.00"),
                    shipping_amount=Decimal("5.00"), total=Decimal("95.00"),
                    customer_name="Private Name", customer_email="person@example.test",
                    payment_status="paid", status="confirmed")
        data.update(kwargs)
        order = Order.objects.create(**data)
        Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        order.refresh_from_db()
        return order

    def line(self, order, product=None, amount="100.00"):
        product = product or self.product
        return OrderItem.objects.create(order=order, variant=product.variants.first(), sku="SNAPSHOT",
             title=product.short_title, quantity=1, unit_price=Decimal(amount), subtotal=Decimal(amount))

    def event(self, name, key="buyer", payload=None, days_ago=2):
        event = AnalyticsEvent.objects.create(store=self.store_a, name=name, session_key=key,
            request_id=f"event-{AnalyticsEvent.objects.count()}", payload=payload or {})
        AnalyticsEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        return event

    def test_refunded_orders_are_included_and_cumulative_refund_subtracted_once(self):
        self.order()
        self.order(payment_status="partially_refunded", refund_amount=Decimal("25"))
        self.order(payment_status="refunded", refund_amount=Decimal("95"))
        self.order(payment_status="pending")
        self.order(payment_status="failed")
        self.order(payment_status="disputed")
        report = build_report(self.store_a, self.filters)
        self.assertEqual(report["current"]["gross"], Decimal("300"))
        self.assertEqual(report["current"]["discounts"], Decimal("30"))
        self.assertEqual(report["current"]["shipping"], Decimal("15"))
        self.assertEqual(report["current"]["charged"], Decimal("285"))
        self.assertEqual(report["current"]["refunds"], Decimal("120"))
        self.assertEqual(report["current"]["net_receipts"], Decimal("165"))
        self.assertEqual(report["current"]["average_order"], Decimal("95"))
        self.assertIsNone(report["current"]["net_sales"])
        self.assertIsNone(report["current"]["tax"])
        self.assertEqual(report["current"]["disputed_orders"], 1)

    def test_period_comparison_has_equal_length_and_zero_denominator_is_unknown(self):
        self.order(total=Decimal("190"))
        self.order(days_ago=8)
        self.order(days_ago=15, total=Decimal("999"))
        report = build_report(self.store_a, self.filters)
        self.assertEqual(report["changes"]["net_receipts"], Decimal("100"))
        self.assertEqual(self.filters.days, self.filters.previous().days)
        self.assertIsNone(percent_change(10, 0))
        self.assertEqual(percent_change(0, 10), Decimal("-100"))

    def test_other_tenant_and_currency_never_affect_money(self):
        self.order()
        self.order(store=self.store_b, total=Decimal("9999"))
        self.order(currency="EUR", total=Decimal("8888"))
        report = build_report(self.store_a, self.filters)
        self.assertEqual(report["current"]["net_receipts"], Decimal("95"))
        self.assertEqual(report["other_currency_orders"], 1)

    def test_product_filter_selects_whole_order_once_for_multiple_lines(self):
        order = self.order()
        self.line(order, amount="40")
        self.line(order, amount="60")
        self.order()
        filters = ReportFilters(self.filters.start, self.filters.end, product_id=self.product.pk)
        report = build_report(self.store_a, filters)
        self.assertEqual(report["current"]["net_receipts"], Decimal("95"))
        self.assertEqual(report["current"]["orders"], 1)
        self.assertFalse(report["funnel_available"])

    def test_category_and_status_filters_are_applied_together(self):
        self.product.category = "harness"
        self.product.save()
        self.line(self.order(), self.product)
        self.line(self.order(status="cancelled"), self.product)
        self.line(self.order(), self.product2)
        filters = ReportFilters(self.filters.start, self.filters.end, category="harness", status="confirmed")
        self.assertEqual(order_scope(self.store_a, filters).count(), 1)

    def test_customers_normalize_email_and_check_history(self):
        self.order(days_ago=20, customer_email="Person@example.test")
        self.order(customer_email="person@example.test")
        self.order(customer_email="new@example.test")
        self.order(customer_email="NEW@example.test")
        report = build_report(self.store_a, self.filters)
        self.assertEqual(report["new_customers"], 1)
        self.assertEqual(report["returning_customers"], 1)
        self.assertEqual(report["repeat_rate"], 50)

    def test_empty_report_is_honest_and_has_zero_filled_series(self):
        report = build_report(self.store_a, self.filters)
        self.assertEqual(len(report["series"]), 7)
        self.assertTrue(all(point["net"] == 0 for point in report["series"]))
        self.assertIsNone(report["conversion"])
        self.assertIsNone(report["repeat_rate"])
        self.assertIsNone(report["current"]["average_order"])

    def test_historical_refund_without_amount_is_unknown_not_zero(self):
        self.order(payment_status="refunded", refund_amount=None)
        report = build_report(self.store_a, self.filters)
        self.assertIsNone(report["current"]["net_receipts"])
        self.assertIsNone(report["current"]["net_sales"])
        self.assertEqual(report["current"]["missing_refunds"], 1)
        self.assertTrue(any(point["net"] is None for point in report["series"]))
        response = self.client.get(self.path)
        self.assertContains(response, "Sin datos suficientes")
        response = self.client.get(self.path + "exportar/")
        self.assertIn("Sin importe registrado", response.content.decode("utf-8-sig"))

    def test_unknown_shipping_is_not_reported_as_free(self):
        self.order(shipping_amount=None)
        summary = financial_summary(order_scope(self.store_a, self.filters))
        self.assertIsNone(summary["shipping"])
        self.assertEqual(summary["net_receipts"], Decimal("95"))

    def test_week_and_month_series_preserve_totals(self):
        self.order()
        self.order(days_ago=6, payment_status="partially_refunded", refund_amount=Decimal("20"))
        for bucket in ("week", "month"):
            report = build_report(self.store_a, ReportFilters(self.filters.start, self.filters.end, bucket=bucket))
            self.assertEqual(sum(point["net"] for point in report["series"]), 170)
            self.assertEqual(sum(point["orders"] for point in report["series"]), 2)

    def test_funnel_requires_matching_sessions_and_excludes_anonymous(self):
        cart = Cart.objects.create(store=self.store_a, session_key="buyer")
        self.order(cart=cart)
        for name in ("product_view", "cart_added", "checkout_started", "order_placed"):
            self.event(name)
            self.event(name, key="")
        self.event("product_view", key="visitor-only")
        self.event("cart_added", key="unrelated")
        report = build_report(self.store_a, self.filters)
        self.assertEqual([step["count"] for step in report["funnel"]], [2, 1, 1, 1, 1])
        self.assertEqual(report["conversion"], 50)

    def test_ai_requires_matching_cart_variant_and_preceding_confirmation(self):
        cart = Cart.objects.create(store=self.store_a, session_key="buyer")
        order = self.order(cart=cart)
        line = self.line(order)
        payload = {"cart": str(cart.public_id), "variant": str(line.variant.public_id), "action": "add_to_cart"}
        self.event("advisor_action_confirmed", payload=payload)
        self.event("advisor_action_confirmed", payload=payload)  # multiple actions, one order
        self.event("advisor_action_confirmed", payload={**payload, "cart": "foreign"})
        report = build_report(self.store_a, self.filters)
        self.assertEqual(report["ai_orders"], 1)
        self.assertEqual(report["ai_net_receipts"], Decimal("95"))
        AnalyticsEvent.objects.all().update(created_at=timezone.now())
        self.assertEqual(build_report(self.store_a, self.filters)["ai_orders"], 0)

    def test_removed_recommended_variant_does_not_attribute_order(self):
        cart = Cart.objects.create(store=self.store_a, session_key="buyer")
        order = self.order(cart=cart)
        self.line(order, self.product2)
        self.event("advisor_action_confirmed", payload={"cart": str(cart.public_id),
            "variant": str(self.product.variants.first().public_id), "action": "add_to_cart"})
        self.assertEqual(build_report(self.store_a, self.filters)["ai_orders"], 0)

    def test_top_products_preserve_snapshot_prices_and_bought_together(self):
        for _ in range(2):
            order = self.order()
            self.line(order, self.product, "40")
            self.line(order, self.product2, "60")
        self.product.base_price = Decimal("9999")
        self.product.save()
        report = build_report(self.store_a, self.filters)
        self.assertEqual(report["top_products"][0]["revenue"], Decimal("120"))
        self.assertEqual(report["pairs"][0]["orders"], 2)

    def test_query_count_does_not_grow_with_order_count(self):
        for _ in range(15):
            self.line(self.order())
        with CaptureQueriesContext(connection) as queries:
            build_report(self.store_a, self.filters)
        self.assertLessEqual(len(queries), 28)

    def test_owner_gets_dashboard_with_explanations_and_no_customer_data(self):
        self.order()
        response = self.client.get(self.path)
        self.assertContains(response, "Tu negocio, con perspectiva.")
        self.assertContains(response, "Cobro neto verificado")
        self.assertContains(response, "Impuestos: no desglosados")
        self.assertNotContains(response, "Private Name")
        self.assertNotContains(response, "person@example.test")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_other_tenant_denied_for_dashboard_and_csv(self):
        for suffix in ("estadisticas/", "estadisticas/exportar/"):
            response = self.client.get(f"/negocio/{self.store_b.slug}/{suffix}")
            self.assertEqual(response.status_code, 403)

    def test_logistics_and_catalog_staff_cannot_export_financial_report(self):
        member = MerchantMember.objects.get(user=self.owner)
        for role in ("staff", "logistics"):
            member.role = role
            member.save()
            self.assertEqual(self.client.get(self.path).status_code, 403)
            self.assertEqual(self.client.get(self.path + "exportar/").status_code, 403)

    def test_unauthenticated_access_redirects_to_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.path).status_code, 302)

    def test_foreign_product_filter_is_rejected(self):
        self.assertEqual(self.client.get(self.path, {"product": self.product_b.pk}).status_code, 400)
        self.assertEqual(self.client.get(self.path + "exportar/", {"product": self.product_b.pk}).status_code, 400)

    def test_bad_date_range_and_invalid_filters_are_rejected(self):
        for params in ({"start": "bad"}, {"start": self.today, "end": self.today - timedelta(days=1)},
                       {"start": self.today - timedelta(days=367)}, {"end": self.today + timedelta(days=1)},
                       {"status": "invalid"}, {"bucket": "hour"}, {"category": "foreign"},
                       {"start": "0001-01-01", "end": "0001-01-02"}):
            self.assertEqual(self.client.get(self.path, params).status_code, 400)

    def test_csv_escapes_formula_and_separates_refund_from_pending_total(self):
        self.order(reference="=1+1", payment_status="partially_refunded", refund_amount=Decimal("20"), discount_note="@SUM(A1)")
        self.order(payment_status="pending")
        self.order(store=self.store_b, reference="PRIVATE-B")
        response = self.client.get(self.path + "exportar/")
        self.assertEqual(response.status_code, 200)
        text = response.content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        self.assertTrue(rows[1][0].startswith("'="))
        self.assertEqual(rows[1][11], "75.00")
        self.assertTrue(rows[1][12].startswith("'@"))
        self.assertEqual(rows[2][11], "")
        self.assertNotIn("PRIVATE-B", text)
        self.assertNotIn("person@example.test", text)

    def test_dedupe_is_scoped_to_tenant_session_event_and_key(self):
        kwargs = {"session_key": "same", "key": "same"}
        self.assertTrue(track_once("product_view", store=self.store_a, **kwargs))
        self.assertFalse(track_once("product_view", store=self.store_a, **kwargs))
        self.assertTrue(track_once("product_view", store=self.store_b, **kwargs))
        self.assertTrue(track_once("cart_added", store=self.store_a, **kwargs))
        self.assertEqual(AnalyticsEvent.objects.count(), 3)

    def test_product_refresh_and_checkout_refresh_do_not_duplicate_events(self):
        url = f"/s/{self.store_a.slug}/producto/{self.product.slug}/"
        self.client.get(url)
        self.client.get(url)
        self.assertEqual(AnalyticsEvent.objects.filter(name="product_view").count(), 1)
        self.client.post(f"/s/{self.store_a.slug}/carrito/agregar/", {"variant": str(self.product.variants.first().public_id), "quantity": 1})
        self.client.get(f"/s/{self.store_a.slug}/checkout/")
        self.client.get(f"/s/{self.store_a.slug}/checkout/")
        self.assertEqual(AnalyticsEvent.objects.filter(name="checkout_started").count(), 1)

    def test_search_is_instrumented_without_saving_raw_query(self):
        self.client.get(f"/s/{self.store_a.slug}/coleccion/", {"q": "private query"})
        self.client.get(f"/s/{self.store_a.slug}/coleccion/", {"q": "private query"})
        event = AnalyticsEvent.objects.get(name="search", store=self.store_a)
        self.assertEqual(event.payload["result_count"], 0)
        self.assertNotIn("private query", str(event.payload))
