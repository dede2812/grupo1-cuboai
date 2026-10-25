"""Customer identity survives session rotation without crossing account owners."""
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from reino import services_commerce, services_identity, services_memory
from reino.ai import orchestrator
from reino.models import AIConversation, AIUsageCounter, Cart, Consent, CustomerIdentity, Look, RecipientProfile
from reino.tests import ReinoTestCase


PASSWORD = "Royal-account-47!Strong"


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SharedLoginQuotaTests(ReinoTestCase):
    def test_panel_and_customer_posts_share_one_budget(self):
        get_user_model().objects.create_user(username="quota-user", password=PASSWORD, is_staff=True)
        endpoints = ("/panel/login/", "/cuenta/ingresar/")
        for attempt in range(20):
            response = self.client.post(endpoints[attempt % 2], {"username": "quota-user", "password": "wrong"})
            self.assertEqual(response.status_code, 200)
        counter = AIUsageCounter.objects.get(key__startswith="auth:")
        self.assertEqual(counter.count, 20)
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                response = self.client.post(endpoint, {"username": "quota-user", "password": PASSWORD})
                self.assertNotIn("_auth_user_id", self.client.session)
                self.assertContains(response, "15 minutos" if endpoint.startswith("/cuenta/") else "15 minutes",
                                    status_code=200 if endpoint.startswith("/cuenta/") else 429)
        counter.refresh_from_db()
        self.assertEqual(counter.count, 20)
        other_ip = Client(REMOTE_ADDR="192.0.2.44")
        self.assertEqual(other_ip.post("/panel/login/", {"username": "quota-user", "password": PASSWORD}).status_code, 302)

    def test_login_gets_do_not_consume_attempt_budget(self):
        for endpoint in ("/panel/login/", "/cuenta/ingresar/"):
            for _ in range(3):
                self.assertEqual(self.client.get(endpoint).status_code, 200)
        self.assertFalse(AIUsageCounter.objects.filter(key__startswith="auth:").exists())
        for endpoint in ("/panel/login/", "/cuenta/ingresar/"):
            self.client.post(endpoint, {"username": "missing", "password": "wrong"})
        self.assertEqual(AIUsageCounter.objects.get(key__startswith="auth:").count, 2)


class CustomerAccountTests(ReinoTestCase):
    def guest_profile(self):
        self.client.get(f"/s/{self.store_a.slug}/")
        return self._profile(self.store_a, session=self.client.session.session_key, alias="Mi Bruno")

    def register(self, **extra):
        return self.client.post("/cuenta/registro/", {
            "username": "customer-one", "email": "customer@example.invalid",
            "password1": PASSWORD, "password2": PASSWORD, **extra,
        })

    def test_registration_import_is_explicit_and_preserves_cart_profile_conversation(self):
        profile = self.guest_profile()
        guest_key = profile.session_key
        cart = services_commerce.get_open_cart(self.store_a, guest_key, create=True)
        services_commerce.add_item(cart, self.product.variants.get(option_label="Talla M"), 2, recipient=profile)
        conversation = orchestrator.get_conversation(self.store_a, guest_key)
        conversation.messages.create(role="user", content="Mi consulta guardada")
        self.assertEqual(self.register(keep_guest_data="on", is_staff="1", is_superuser="1").status_code, 302)
        user = get_user_model().objects.get(username="customer-one")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        owner = user.customer_identity.owner_key
        self.assertNotEqual(self.client.session.session_key, guest_key)
        profile.refresh_from_db()
        cart.refresh_from_db()
        conversation.refresh_from_db()
        self.assertEqual(profile.session_key, owner)
        self.assertEqual(cart.session_key, owner)
        self.assertEqual(conversation.session_key, owner)
        self.assertEqual(cart.items.get().quantity, 2)
        self.assertContains(self.client.get("/cuenta/"), "Mi Bruno")

    def test_guest_data_not_imported_without_checkbox(self):
        profile = self.guest_profile()
        old_key = profile.session_key
        self.register()
        profile.refresh_from_db()
        self.assertEqual(profile.session_key, old_key)
        self.assertNotContains(self.client.get("/cuenta/"), "Mi Bruno")

    def test_data_follows_account_to_another_device(self):
        profile = self.guest_profile()
        self.register(keep_guest_data="on")
        second = Client()
        response = second.post("/cuenta/ingresar/", {"username": "customer-one", "password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertContains(second.get("/cuenta/"), profile.alias)
        self.assertNotEqual(second.session.session_key, self.client.session.session_key)

    def test_logout_and_other_account_cannot_view_or_import_previous_customer(self):
        profile = self.guest_profile()
        self.register(keep_guest_data="on")
        first_owner = get_user_model().objects.get(username="customer-one").customer_identity.owner_key
        self.assertEqual(self.client.get("/cuenta/salir/").status_code, 405)
        self.client.post("/cuenta/salir/")
        self.assertNotContains(self.client.get("/cuenta/"), profile.alias)
        other = get_user_model().objects.create_user(username="other-buyer", password=PASSWORD)
        self.client.post("/cuenta/ingresar/", {"username": "other-buyer", "password": PASSWORD, "keep_guest_data": "on"})
        services_identity.import_guest_data(first_owner, other)
        self.assertNotContains(self.client.get("/cuenta/"), profile.alias)
        profile.refresh_from_db()
        self.assertEqual(profile.session_key, first_owner)

    def test_existing_account_cart_merges_exact_quantities(self):
        user = get_user_model().objects.create_user(username="saved-buyer", password=PASSWORD)
        identity = CustomerIdentity.objects.create(user=user)
        existing = services_commerce.get_open_cart(self.store_a, identity.owner_key, create=True)
        variant = self.product.variants.get(option_label="Talla M")
        services_commerce.add_item(existing, variant, 2)
        self.client.get(f"/s/{self.store_a.slug}/")
        guest = services_commerce.get_open_cart(self.store_a, self.client.session.session_key, create=True)
        services_commerce.add_item(guest, variant, 1)
        self.client.post("/cuenta/ingresar/", {"username": user.username, "password": PASSWORD, "keep_guest_data": "on"})
        existing.refresh_from_db()
        guest.refresh_from_db()
        self.assertEqual(existing.items.get().quantity, 3)
        self.assertEqual(guest.status, Cart.Status.MERGED)
        self.assertEqual(Cart.objects.filter(session_key=identity.owner_key, status="open").count(), 1)

    def test_unsafe_merge_rolls_back_without_truncating_quantities(self):
        user = get_user_model().objects.create_user(username="large-cart", password=PASSWORD)
        identity = CustomerIdentity.objects.create(user=user)
        variant = self.product.variants.get(option_label="Talla M")
        saved = services_commerce.get_open_cart(self.store_a, identity.owner_key, create=True)
        services_commerce.add_item(saved, variant, 8)
        self.client.get(f"/s/{self.store_a.slug}/")
        guest = services_commerce.get_open_cart(self.store_a, self.client.session.session_key, create=True)
        services_commerce.add_item(guest, variant, 4)
        response = self.client.post("/cuenta/ingresar/", {"username": user.username, "password": PASSWORD, "keep_guest_data": "on"})
        self.assertContains(response, "no se pueden combinar")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(saved.items.get().quantity, 8)
        self.assertEqual(guest.items.get().quantity, 4)

    def test_password_change_retains_identity_and_revokes_old_password(self):
        self.guest_profile()
        self.register(keep_guest_data="on")
        user = get_user_model().objects.get(username="customer-one")
        owner = user.customer_identity.owner_key
        response = self.client.post("/cuenta/contrasena/", {"old_password": PASSWORD,
            "new_password1": "New-Royal-98!Strong", "new_password2": "New-Royal-98!Strong"})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get("/cuenta/"), "Mi Bruno")
        user.refresh_from_db()
        self.assertFalse(user.check_password(PASSWORD))
        self.assertTrue(user.check_password("New-Royal-98!Strong"))
        self.assertEqual(user.customer_identity.owner_key, owner)

    def test_external_redirects_are_rejected(self):
        self.assertEqual(self.register(next="https://evil.example/")["Location"], "/cuenta/")
        response = self.client.post("/cuenta/perfiles/nuevo/", {
            "store": self.store_a.slug, "alias": "Daisy", "next": "//evil.example/"})
        self.assertEqual(response["Location"], f"/s/{self.store_a.slug}/")

    def test_invalid_profile_does_not_grant_storewide_consent(self):
        self.client.post("/cuenta/consentimiento/", {
            "store": self.store_a.slug, "profile": "not-a-uuid", "purpose": "measurements", "decision": "grant"})
        self.assertFalse(Consent.objects.exists())

    def test_failed_login_does_not_claim_guest_data(self):
        profile = self.guest_profile()
        get_user_model().objects.create_user(username="saved-buyer", password=PASSWORD)
        response = self.client.post("/cuenta/ingresar/", {"username": "saved-buyer", "password": "wrong", "keep_guest_data": "on"})
        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.assertFalse(profile.session_key.startswith("customer:"))

    def test_preferences_require_explicit_permission_and_can_be_corrected(self):
        profile = self.guest_profile()
        url = f"/cuenta/perfiles/{profile.public_id}/preferencias/"
        fields = {"store": self.store_a.slug, "style": "azul", "budget": "70"}
        self.client.post(url, fields)
        self.assertFalse(profile.preferences.exists())
        self.client.post(url, {**fields, "remember": "1"})
        self.assertEqual(profile.preferences.get(key="style").value, "azul")
        self.client.post(url, {**fields, "style": "verde", "remember": "1"})
        self.assertEqual(profile.preferences.get(key="style").value, "verde")
        self.client.post(url, {**fields, "budget": "NaN", "remember": "1"})
        self.assertEqual(profile.preferences.get(key="budget_hint").value, "70.00")

    def test_order_history_is_only_available_to_owner_account(self):
        profile = self.guest_profile()
        cart = services_commerce.get_open_cart(self.store_a, profile.session_key, create=True)
        services_commerce.add_item(cart, self.product.variants.get(option_label="Talla M"), 1)
        checkout = services_commerce.prepare_checkout(cart, "manual", idempotency_key="auth-order")
        order = services_commerce.confirm_checkout(checkout, {"name": "Buyer", "email": "buyer@example.invalid"}, "auth-order")
        self.register(keep_guest_data="on")
        self.assertContains(self.client.get("/cuenta/"), order.reference)
        self.assertEqual(self.client.get(f"/s/{self.store_a.slug}/pedido/{order.public_id}/").status_code, 200)
        other = Client()
        self.assertEqual(other.get(f"/s/{self.store_a.slug}/pedido/{order.public_id}/").status_code, 404)

    def test_csrf_required_for_auth_and_logout(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post("/cuenta/registro/", {}).status_code, 403)
        self.assertEqual(client.post("/cuenta/ingresar/", {}).status_code, 403)
        self.assertEqual(client.post("/cuenta/salir/", {}).status_code, 403)
