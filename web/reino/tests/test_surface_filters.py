"""Regressions for public filters and merchant summaries with incomplete data."""
from decimal import Decimal

from django.contrib.auth.models import User

from reino import services_search
from reino.models import MerchantMember, Order, Product
from reino.tests import ReinoTestCase


class SearchFilterBoundaryTests(ReinoTestCase):
    def test_nonfinite_negative_and_malformed_budget_is_rejected(self):
        for value in ("NaN", "sNaN", "Infinity", "-Infinity", "-1", "bad"):
            with self.subTest(value=value):
                response = self.client.get("/buscar/", {"q": "arnes", "max": value})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Ingresá un precio máximo válido")
                self.assertEqual(response.context["results"], [])

    def test_category_only_search_is_executed_and_preserved(self):
        response = self.client.get("/buscar/", {"categoria": "moda canina"})
        self.assertTrue(response.context["searched"])
        self.assertContains(response, "Arnés Real")
        self.assertContains(response, 'name="categoria" value="moda canina"')
        self.assertNotContains(response, "Cuaderno Nube")

    def test_zero_budget_is_a_constraint_and_input_retains_decimal_budget(self):
        self.assertEqual(services_search.search_catalog(max_price=Decimal("0")), [])
        self.assertEqual(self.client.get("/buscar/", {"max": "0"}).context["results"], [])
        response = self.client.get("/buscar/", {"max": "63.50"})
        self.assertContains(response, 'name="max" value="63.50"')
        self.assertEqual(len(response.context["results"]), 1)


class MerchantSummaryBoundaryTests(ReinoTestCase):
    def setUp(self):
        self.user = User.objects.create_user("summary-owner", password="test-only")
        MerchantMember.objects.create(user=self.user, merchant=self.merchant_a, role="owner")
        self.client.force_login(self.user)
        self.serial = 0
        self.base = f"/negocio/{self.store_a.slug}/"

    def order(self, **kwargs):
        self.serial += 1
        values = dict(store=self.store_a, reference=f"SURFACE-{self.serial}",
                      idempotency_key=f"surface-{self.serial}", subtotal=Decimal("100"),
                      total=Decimal("100"), shipping_amount=Decimal("0"),
                      customer_name="Cliente de prueba", customer_email="buyer@example.test",
                      payment_status="paid", status="confirmed", currency="USD")
        values.update(kwargs)
        return Order.objects.create(**values)

    def test_missing_refund_never_becomes_an_invented_amount(self):
        self.order(payment_status="refunded", refund_amount=None)
        self.order()
        finance = self.client.get(self.base + "finanzas/")
        self.assertIsNone(finance.context["kpis"]["cobrado"])
        self.assertContains(finance, "Sin datos suficientes")
        self.assertContains(finance, "Importe no registrado")
        self.assertNotContains(finance, "$None")
        dashboard = self.client.get(self.base)
        self.assertIsNone(dashboard.context["kpis"]["ventas"])
        self.assertContains(dashboard, "Sin datos suficientes")
        customers = self.client.get(self.base + "clientes/")
        self.assertIsNone(customers.context["customers"][0]["paid_total"])
        self.assertContains(customers, "Sin datos suficientes")

    def test_cumulative_refunds_and_casefolded_customer_are_counted_once(self):
        self.order(payment_status="partially_refunded", refund_amount=Decimal("25"))
        self.order(payment_status="refunded", refund_amount=Decimal("100"),
                   customer_email="BUYER@example.test")
        self.order(payment_status="pending")
        finance = self.client.get(self.base + "finanzas/")
        self.assertEqual(finance.context["kpis"]["cobrado"], Decimal("75"))
        customers = self.client.get(self.base + "clientes/").context["customers"]
        self.assertEqual(len(customers), 1)
        self.assertEqual(customers[0]["orders"], 3)
        self.assertEqual(customers[0]["paid_total"], Decimal("75"))

    def test_currency_amounts_are_not_added_without_conversion(self):
        self.order()
        self.order(currency="EUR", total=Decimal("999"))
        for path, key in (("", "ventas"), ("finanzas/", "cobrado")):
            response = self.client.get(self.base + path)
            self.assertEqual(response.context["kpis"][key], Decimal("100"))
            self.assertContains(response, "otra moneda excluidos")
        customers = self.client.get(self.base + "clientes/")
        self.assertEqual(customers.context["customers"][0]["paid_total"], Decimal("100"))
        self.assertEqual(customers.context["other_currency_orders"], 1)

    def test_catalog_navigation_reaches_records_beyond_first_page(self):
        Product.objects.bulk_create([Product(store=self.store_a, slug=f"extra-{i}",
            title=f"Z extra {i:02}", short_title=f"Z extra {i:02}", base_price=1)
            for i in range(25)])
        first = self.client.get(self.base + "catalogo/")
        self.assertContains(first, 'href="?page=2"')
        self.assertEqual(len(first.context["products"]), 24)
        second = self.client.get(self.base + "catalogo/?page=2")
        self.assertEqual(len(second.context["products"]), 3)
        self.assertContains(second, "Página 2 de 2")

    def test_order_navigation_preserves_status_filter(self):
        for _ in range(31):
            self.order()
        self.order(status="cancelled")
        first = self.client.get(self.base + "pedidos/?estado=confirmed")
        self.assertContains(first, 'href="?page=2&amp;estado=confirmed"')
        second = self.client.get(self.base + "pedidos/?estado=confirmed&page=2")
        self.assertEqual(len(second.context["orders"]), 1)
        self.assertEqual(second.context["orders"][0].status, "confirmed")
