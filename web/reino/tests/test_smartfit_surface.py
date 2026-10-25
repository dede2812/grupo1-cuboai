"""Browser-facing Smart Fit works without a saved profile or product query."""
from reino import services_commerce as commerce
from reino.models import Consent, FitRule, Measurement
from reino.tests import ReinoTestCase


class SmartFitSurfaceTests(ReinoTestCase):
    measures = {"chest": "36.5", "neck": "24", "back": "28", "unit": "cm"}

    def setUp(self):
        self.url = f"/s/{self.store_a.slug}/tallas/"

    def test_anonymous_general_page_evaluates_guides_without_storing_measures(self):
        response = self.client.post(self.url, self.measures)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resultado de tus medidas")
        self.assertEqual(len(response.context["results"]), 2)
        self.assertEqual(response.context["results"][0]["fit"]["candidates"], ["S"])
        self.assertContains(response, "Ver Arnés Real y elegir talla")
        self.assertNotContains(response, "Usar estas medidas")
        self.assertEqual(Measurement.objects.count(), 0)
        self.assertEqual(Consent.objects.count(), 0)

    def test_selected_product_is_preserved_and_only_that_product_evaluated(self):
        response = self.client.post(self.url, {**self.measures, "producto": self.product.slug})
        self.assertEqual(len(response.context["results"]), 1)
        self.assertEqual(response.context["result"]["candidates"], ["S"])
        self.assertContains(response, f'value="{self.product.slug}" selected')

    def test_product_from_another_tenant_is_rejected(self):
        self.product_b.slug = "only-other-store"
        self.product_b.save(update_fields=["slug"])
        response = self.client.post(self.url, {**self.measures, "producto": self.product_b.slug})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Elegí una prenda publicada de esta tienda", status_code=400)
        self.assertEqual(response.context["results"], [])
        self.assertEqual(Measurement.objects.count(), 0)

    def test_invalid_inches_keep_unit_and_values(self):
        response = self.client.post(self.url, {"unit": "in", "chest": "abc", "neck": "9", "back": "11"})
        self.assertContains(response, 'name="unit" value="in" checked')
        self.assertNotContains(response, 'name="unit" value="cm" checked')
        self.assertContains(response, 'name="chest" inputmode="decimal" value="abc"')
        self.assertFalse(response.context["evaluated"])

    def test_incomplete_measurements_produce_honest_unknown_results(self):
        response = self.client.post(self.url, {"unit": "cm", "chest": "36.5"})
        self.assertContains(response, "Datos insuficientes")
        self.assertTrue(all(row["fit"]["state"] == "sin_datos" for row in response.context["results"]))

    def test_available_sizes_exclude_existing_checkout_reservations(self):
        variant = self.product.variants.get(option_label="Talla S")
        cart = commerce.get_open_cart(self.store_a, "other-buyer", create=True)
        commerce.add_item(cart, variant, variant.stock)
        commerce.prepare_checkout(cart, "manual", idempotency_key="fit-reservation")
        response = self.client.post(self.url, {**self.measures, "producto": self.product.slug})
        self.assertEqual(response.context["result"]["candidates"], ["S"])
        self.assertEqual(response.context["results"][0]["available_sizes"], [])
        self.assertContains(response, "Las tallas sugeridas no tienen existencias disponibles ahora")

    def test_empty_guide_collection_has_a_visible_explanation(self):
        FitRule.objects.filter(product__store=self.store_a).update(is_active=False)
        response = self.client.post(self.url, self.measures)
        self.assertContains(response, "Esta tienda todavía no tiene prendas con una guía publicada")
        self.assertEqual(response.context["results"], [])
