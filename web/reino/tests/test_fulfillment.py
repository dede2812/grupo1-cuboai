"""G2: ofertas no físicas — descarga digital autorizada y reserva de
servicio con capacidad real (A33/A34, §12.2, §13)."""

from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from reino import services_commerce as c
from reino import services_fulfillment as f
from reino.models import (Booking, DigitalAsset, DigitalGrant, Order, Product,
                          ServiceSlot, Variant)
from reino.tests import ReinoTestCase


class FulfillmentBase(ReinoTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ebook = Product.objects.create(
            store=cls.store_b, slug="guia-nube-digital", title="Guía Nube (digital)",
            short_title="Guía Nube PDF", base_price="9.00", status="published",
            offer_type="digital", reason="Archivo de prueba identificado como demo",
        )
        cls.ebook_v = Variant.objects.create(
            product=cls.ebook, sku="GUIA-PDF", option_label="PDF", stock=999)
        cls.asset = DigitalAsset.objects.create(
            product=cls.ebook, version="1.0",
            file=SimpleUploadedFile("guia.pdf", b"%PDF-1.4 demo", content_type="application/pdf"))
        cls.pase = Product.objects.create(
            store=cls.store_b, slug="taller-nube", title="Taller de lettering",
            short_title="Taller lettering", base_price="25.00", status="published",
            offer_type="service", reason="Servicio de prueba identificado como demo",
        )
        cls.pase_v = Variant.objects.create(
            product=cls.pase, sku="TALLER-1", option_label="Cupón", stock=50)
        cls.slot = ServiceSlot.objects.create(
            product=cls.pase, starts_at=timezone.now() + timedelta(days=7),
            duration_minutes=90, capacity=1)


class DigitalDownloadTests(FulfillmentBase):
    def _buy_ebook(self, session="dig-1"):
        cart = c.get_open_cart(self.store_b, session, create=True)
        c.add_item(cart, self.ebook_v, 1)
        ch = c.prepare_checkout(cart, "manual", idempotency_key=session)
        return c.confirm_checkout(ch, {"name": "Ana", "email": "ana@e.invalid"},
                                  ch.idempotency_key)

    def test_checkout_digital_no_cobra_ni_exige_envio(self):
        order = self._buy_ebook()
        self.assertEqual(order.delivery_mode, "none")
        self.assertEqual(str(order.shipping_amount), "0.00")

    def test_sin_pago_no_hay_descarga(self):
        order = self._buy_ebook()
        self.assertEqual(DigitalGrant.objects.count(), 0)
        # Y el endpoint defiende aunque alguien fabrique un token.
        r = self.client.get(f"/s/{self.store_b.slug}/descargar/{order.access_token}/")
        self.assertIn(r.status_code, (403, 404, 410))

    def test_pago_confirmado_habilita_descarga_una_vez(self):
        order = self._buy_ebook()
        c.apply_transition(order, "payment_status", "paid", note="TRANS-1")
        grants = DigitalGrant.objects.all()
        self.assertEqual(len(grants), 1)
        # Repetir la transición (no-op) NO duplica el derecho.
        c.apply_transition(order, "payment_status", "paid", note="TRANS-1")
        self.assertEqual(DigitalGrant.objects.count(), 1)
        # La página del pedido muestra el enlace.
        r = self.client.get(f"/s/{self.store_b.slug}/pedido/{order.public_id}/{order.access_token}/")
        self.assertContains(r, "Descargar")

    def test_descarga_http_con_sesion_propietaria(self):
        # Compra por HTTP para ligar la sesión de prueba al pedido.
        self.client.post(f"/s/{self.store_b.slug}/carrito/agregar/",
                         {"variant": str(self.ebook_v.public_id), "quantity": 1})
        self.client.post(f"/s/{self.store_b.slug}/checkout/", {
            "step": "review", "name": "Ana", "email": "ana@e.invalid",
            "delivery_mode": "pickup", "payment_method": "manual"})
        session_key = self.client.session.session_key
        cart = c.get_open_cart(self.store_b, session_key)
        ch = c.prepare_checkout(cart, "manual", idempotency_key=f"reino_idem_{self.store_b.slug}")
        order = c.confirm_checkout(ch, {"name": "Ana", "email": "ana@e.invalid"},
                                   ch.idempotency_key)
        c.apply_transition(order, "payment_status", "paid", note="TRANS-HTTP")
        grant = DigitalGrant.objects.get()
        r = self.client.get(f"/s/{self.store_b.slug}/descargar/{grant.token}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 demo")
        # Otra sesión NO puede descargarla (A33: autorización, no obscuridad).
        other = self.client_class()
        r2 = other.get(f"/s/{self.store_b.slug}/descargar/{grant.token}/")
        self.assertEqual(r2.status_code, 403)

    def test_digital_entitlement_uses_purchase_snapshot_after_catalog_edit(self):
        order = self._buy_ebook("digital-snapshot")
        self.ebook.offer_type = "physical"
        self.ebook.save(update_fields=["offer_type"])
        c.apply_transition(order, "payment_status", "paid", note="TEST-SNAPSHOT")
        self.assertEqual(order.items.get().offer_type, "digital")
        self.assertEqual(DigitalGrant.objects.filter(order=order).count(), 1)

    def test_stale_download_grant_cannot_exceed_limit(self):
        order = self._buy_ebook("digital-limit")
        c.apply_transition(order, "payment_status", "paid", note="TEST-LIMIT")
        DigitalGrant.objects.filter(order=order).update(max_downloads=1)
        first = DigitalGrant.objects.get(order=order)
        stale = DigitalGrant.objects.get(order=order)
        self.assertEqual(f.register_download(first), 1)
        with self.assertRaises(f.FulfillmentError):
            f.register_download(stale)
        first.refresh_from_db()
        self.assertEqual(first.downloads, 1)

    def test_refund_revokes_download_even_for_previously_loaded_grant(self):
        order = self._buy_ebook("digital-refund")
        c.apply_transition(order, "payment_status", "paid", note="TEST-PAID")
        grant = DigitalGrant.objects.get(order=order)
        self.assertIsNone(f.authorized_download(grant.token)[1])
        c.apply_transition(order, "payment_status", "refunded", note="TEST-REFUND",
                           refund_amount=order.total)
        self.assertIsNone(f.authorized_download(grant.token)[0])
        with self.assertRaises(f.FulfillmentError):
            f.register_download(grant)
        grant.refresh_from_db()
        self.assertEqual(grant.downloads, 0)

    def test_expired_inactive_and_cancelled_downloads_are_rechecked(self):
        order = self._buy_ebook("digital-unavailable")
        c.apply_transition(order, "payment_status", "paid", note="TEST-PAID")
        grant = DigitalGrant.objects.get(order=order)
        cases = (
            (DigitalGrant.objects.filter(pk=grant.pk), {"expires_at": timezone.now() - timedelta(seconds=1)},
             {"expires_at": timezone.now() + timedelta(days=1)}),
            (DigitalAsset.objects.filter(pk=grant.asset_id), {"is_active": False}, {"is_active": True}),
            (Order.objects.filter(pk=order.pk), {"status": "cancelled"}, {"status": "placed"}),
        )
        for queryset, invalid, restore in cases:
            with self.subTest(invalid=invalid):
                queryset.update(**invalid)
                self.assertIsNone(f.authorized_download(grant.token)[0])
                with self.assertRaises(f.FulfillmentError):
                    f.register_download(grant)
                queryset.update(**restore)


class ServiceBookingTests(FulfillmentBase):
    def _buy_seat(self, session):
        cart = c.get_open_cart(self.store_b, session, create=True)
        c.add_item(cart, self.pase_v, 1, service_slot=self.slot)
        ch = c.prepare_checkout(cart, "manual", idempotency_key=session)
        return c.confirm_checkout(ch, {"name": session, "email": f"{session}@e.invalid"},
                                  ch.idempotency_key)

    def test_reserva_confirma_y_ocupa_cupo(self):
        order = self._buy_seat("svc-1")
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked, 1)
        self.assertEqual(Booking.objects.filter(order=order).count(), 1)

    def test_ultima_franja_un_segundo_comprador_recibe_conflicto_claro(self):
        self._buy_seat("svc-2")
        with self.assertRaises(f.FulfillmentError):
            self._buy_seat("svc-3")
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked, 1, "la capacidad nunca se excede")
        self.assertEqual(Booking.objects.count(), 1)

    def test_agregar_sin_franja_es_rechazado(self):
        cart = c.get_open_cart(self.store_b, "svc-4", create=True)
        with self.assertRaises(c.CartError):
            c.add_item(cart, self.pase_v, 1)

    def test_cancelar_pedido_libera_la_franja_una_vez(self):
        order = self._buy_seat("svc-5")
        c.apply_transition(order, "status", "cancelled")
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked, 0)
        # Repetición: no vuelve a liberar (ni baja de cero).
        c.apply_transition(order, "status", "cancelled")
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked, 0)
        self.assertEqual(Booking.objects.get().status, "cancelled")

    def test_carrito_mixto_si_requiere_envio(self):
        cart = c.get_open_cart(self.store_b, "mix-1", create=True)
        c.add_item(cart, self.product_b.variants.get(), 1)   # físico
        c.add_item(cart, self.ebook_v, 1)                    # digital
        self.assertTrue(c.cart_requires_shipping(cart))
        # Y uno solo digital/servicio no:
        cart2 = c.get_open_cart(self.store_b, "mix-2", create=True)
        c.add_item(cart2, self.ebook_v, 1)
        self.assertFalse(c.cart_requires_shipping(cart2))

    def test_multiple_variants_share_capacity_and_release_exact_quantities_once(self):
        self.slot.capacity = 3
        self.slot.save(update_fields=["capacity"])
        second = Variant.objects.create(product=self.pase, sku="TALLER-2", stock=5)
        cart = c.get_open_cart(self.store_b, "group-service", create=True)
        c.add_item(cart, self.pase_v, 2, service_slot=self.slot)
        c.add_item(cart, second, 1, service_slot=self.slot)
        checkout = c.prepare_checkout(cart, "manual", idempotency_key="group-service")
        order = c.confirm_checkout(checkout, {"name": "Prueba", "email": "test@example.invalid"},
                                   checkout.idempotency_key)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked, 3)
        self.assertEqual(Booking.objects.get(order=order).quantity, 3)
        f.reserve_service_slots(order)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked, 3)
        c.apply_transition(order, "status", "cancelled")
        c.apply_transition(order, "status", "cancelled")
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked, 0)

    def test_shared_slot_over_capacity_rolls_back_order_and_inventory(self):
        self.slot.capacity = 2
        self.slot.save(update_fields=["capacity"])
        second = Variant.objects.create(product=self.pase, sku="OVER-CAPACITY", stock=5)
        cart = c.get_open_cart(self.store_b, "over-capacity", create=True)
        c.add_item(cart, self.pase_v, 2, service_slot=self.slot)
        c.add_item(cart, second, 1, service_slot=self.slot)
        checkout = c.prepare_checkout(cart, "manual", idempotency_key="over-capacity")
        with self.assertRaises(f.FulfillmentError):
            c.confirm_checkout(checkout, {"name": "Prueba", "email": "test@example.invalid"},
                               checkout.idempotency_key)
        self.slot.refresh_from_db()
        self.pase_v.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.slot.booked, 0)
        self.assertEqual(self.pase_v.stock, 50)
        self.assertEqual(second.stock, 5)
        self.assertFalse(Booking.objects.exists())
        self.assertFalse(Order.objects.filter(cart=cart).exists())

    def test_service_quantity_string_is_validated_before_capacity(self):
        cart = c.get_open_cart(self.store_b, "service-string", create=True)
        with self.assertRaises(c.CartError):
            c.add_item(cart, self.pase_v, "invalid", service_slot=self.slot)
        c.add_item(cart, self.pase_v, "1", service_slot=self.slot)
        self.assertEqual(cart.items.get().quantity, 1)

    def test_changing_slot_does_not_silently_book_previous_time(self):
        cart = c.get_open_cart(self.store_b, "service-slot-change", create=True)
        alternate = ServiceSlot.objects.create(
            product=self.pase, starts_at=timezone.now() + timedelta(days=8), capacity=5)
        c.add_item(cart, self.pase_v, 1, service_slot=self.slot)
        with self.assertRaises(c.CartError):
            c.add_item(cart, self.pase_v, 1, service_slot=alternate)
        self.assertEqual(cart.items.get().service_slot_id, self.slot.pk)
        self.assertEqual(cart.items.get().quantity, 1)


class MultiCategoryTests(ReinoTestCase):
    """A32: seis categorías físicas conviven: crear, buscar, comparar y
    comprar sin lógica exclusiva de moda canina."""

    CATS = ("hogar", "tecnologia", "cuidado personal", "papeleria",
            "moda humana", "juguetes")

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.market = cls.store_b  # tienda demo existente como anfitriona
        cls.by_cat = {}
        for cat in cls.CATS:
            p = Product.objects.create(
                store=cls.market, slug=f"demo-{cat.replace(' ', '-')}",
                title=f"Producto {cat} demo", short_title=f"Pieza {cat}",
                base_price="11.00", status="published", category=cat,
                reason="Producto ficticio de demostración")
            cls.by_cat[cat] = Variant.objects.create(
                product=p, sku=f"D-{cat[:4].upper()}", option_label="Estándar", stock=4)

    def test_seis_categorias_se_buscan(self):
        from reino import services_search as s
        for cat, variant in self.by_cat.items():
            results = s.search_catalog(cat.split()[0], store=self.market,
                                       include_demo=True)
            self.assertTrue(any(r["product"].pk == variant.product_id for r in results),
                            f"{cat} no se encontró")

    def test_comparar_misma_categoria_y_compra(self):
        from reino import services_compare as cmp
        v2 = Variant.objects.create(
            product=self.by_cat["hogar"].product, sku="D-HOG2",
            option_label="Grande", stock=2)
        cmp.add_item("a32", str(self.by_cat["hogar"].public_id))
        cmp.add_item("a32", str(v2.public_id))
        data = cmp.build_comparison(session_key="a32")
        self.assertEqual(len(data["columns"]), 2)
        # Comprar una pieza de una categoría sin talla: flujo genérico.
        cart = c.get_open_cart(self.market, "a32-buy", create=True)
        c.add_item(cart, self.by_cat["tecnologia"], 1)
        ch = c.prepare_checkout(cart, "manual", idempotency_key="a32-buy")
        order = c.confirm_checkout(ch, {"name": "A", "email": "a@e.invalid"},
                                   ch.idempotency_key)
        self.assertTrue(order.reference)

    def test_categoria_sin_talla_no_pide_medidas_caninas(self):
        r = self.client.get(
            f"/s/{self.market.slug}/producto/{self.by_cat['hogar'].product.slug}/")
        self.assertNotContains(r, "cuello")
        self.assertNotContains(r, "pecho del perro")
