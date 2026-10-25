"""Release regressions: hostile provider data, consent, quotes and real variants.

Provider responses here are explicit contract fixtures, never live verification.
"""
import io
import json
import urllib.error
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import override_settings

from reino import services_commerce, services_fit, services_memory, services_recommend
from reino.ai import adapter, fallback, intent, orchestrator
from reino.ai.tools import ToolContext, run_tool
from reino.models import ActionToken, AIConversation, AnalyticsEvent, Consent
from reino.tests import ReinoTestCase


AI = {"API_KEY": "test-contract-only", "BASE_URL": "https://api.example.invalid/v1",
      "MODEL": "contract-fixture", "TIMEOUT_SECONDS": 3, "MAX_TOOL_ROUNDS": 4,
      "MAX_COMPLETION_TOKENS": 321, "SESSION_HOURLY_LIMIT": 120, "STORE_DAILY_LIMIT": 2000}


@override_settings(REINO_AI=AI)
class AdvisorReleaseTests(ReinoTestCase):
    def setUp(self):
        cache.clear()
        self.ctx = ToolContext(self.store_a, "release-advisor")
        self.conversation = AIConversation.objects.create(store=self.store_a, session_key=self.ctx.session_key)

    def test_no_save_sends_current_request_without_persisting(self):
        self.conversation.memory_off = True
        self.conversation.save()
        long_request = "Quiero revisar opciones. " * 60 + "Máximo $64."
        with mock.patch.object(adapter, "chat", return_value={"role": "assistant", "content": "Revisemos."}) as call:
            orchestrator.respond(self.conversation, long_request, self.ctx)
        self.assertEqual(call.call_args.args[0][-1], {"role": "user", "content": long_request})
        self.assertEqual(self.conversation.messages.count(), 0)

    def test_http_message_preserves_last_constraint(self):
        text = "Consulta sobre colores y materiales. " * 35 + "Máximo $63."
        with mock.patch("reino.views_stylist.respond", return_value={"answer_text": "Recibido", "cards": []}) as respond:
            response = self.client.post(f"/s/{self.store_a.slug}/asesor/mensaje/", {"message": text})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(respond.call_args.args[1], text)

    def test_oversized_http_message_is_rejected_not_silently_cut(self):
        response = self.client.post(f"/s/{self.store_a.slug}/asesor/mensaje/", {"message": "x" * 8001})
        self.assertEqual(response.status_code, 400)

    def test_long_history_retains_current_request_and_bounds_payload(self):
        for n in range(20):
            self.conversation.messages.create(role="user", content=f"old-{n}" + "x" * 3000)
        with mock.patch.object(adapter, "chat", return_value={"role": "assistant", "content": "Revisemos."}) as call:
            orchestrator.respond(self.conversation, "Mi máximo ahora es $63", self.ctx)
        messages = call.call_args.args[0]
        self.assertEqual(messages[-1]["content"], "Mi máximo ahora es $63")
        self.assertLess(len(json.dumps(messages, ensure_ascii=False)), 27000)

    def test_cross_store_conversation_rejected(self):
        with self.assertRaises(ValueError):
            orchestrator.respond(self.conversation, "hola", ToolContext(self.store_b, self.ctx.session_key))

    def test_usage_limit_blocks_provider_and_uses_labelled_rules(self):
        with override_settings(REINO_AI={**AI, "SESSION_HOURLY_LIMIT": 0}), mock.patch.object(adapter, "chat") as call:
            reply = orchestrator.respond(self.conversation, "paseo", self.ctx)
        call.assert_not_called()
        self.assertEqual(reply["mode"], "rules")
        self.assertIn("selección guiada", reply["mode_note"])

    def test_provider_http_body_is_not_exposed(self):
        error = urllib.error.HTTPError("https://api.example.invalid", 401, "bad", {}, io.BytesIO(b"secret-account-and-key"))
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(adapter.ProviderError) as raised:
                adapter.chat([{"role": "user", "content": "hola"}])
        self.assertNotIn("secret", str(raised.exception))

    def test_provider_invalid_json_and_schema_fail_closed(self):
        for raw in (b"not-json", b"null", b'{"choices":[]}', b'{"choices":[{"message":{"role":"assistant","content":[]}}]}'):
            with self.subTest(raw=raw), mock.patch("urllib.request.urlopen") as urlopen:
                urlopen.return_value.__enter__.return_value.read.return_value = raw
                with self.assertRaises(adapter.ProviderError):
                    adapter.chat([{"role": "user", "content": "hola"}])

    def test_adapter_caps_output_and_does_not_request_provider_storage(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"role":"assistant","content":"OK"}}]}'
            adapter.chat([{"role": "user", "content": "hola"}])
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["max_completion_tokens"], 321)
        self.assertFalse(payload["store"])
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 3)

    def test_probe_requires_real_text_completion_contract(self):
        with mock.patch.object(adapter, "chat", return_value={"content": "OK"}) as call:
            ok, _ = adapter.probe()
        self.assertTrue(ok)
        self.assertEqual(call.call_args.args[0][0]["role"], "user")

    def test_tool_arguments_are_typed_and_disallow_tenant_override(self):
        for name, args in (("search_products", []), ("search_products", {"store": "other"}),
                           ("check_inventory", {"variant_id": "x", "quantity": -1}),
                           ("check_inventory", {"variant_id": "x", "quantity": 1.5}),
                           ("recommend_products", {"budget": float("nan")}),
                           ("get_product_details", {"product_ids": "not-an-array"})):
            with self.subTest(name=name, args=args):
                self.assertEqual(run_tool(name, args, self.ctx)["error"], "invalid_arguments")

    def test_draft_or_sold_out_variant_cannot_be_proposed(self):
        variant = self.product.variants.get(option_label="Talla M")
        self.product.status = "draft"
        self.product.save()
        self.assertIsNone(orchestrator._propose_action("add_item_to_cart", {"variant_id": str(variant.public_id)}, self.ctx))
        self.assertEqual(run_tool("check_inventory", {"variant_id": str(variant.public_id)}, self.ctx)["error"], "unknown_variant")

    def test_model_cannot_override_budget_in_tool_arguments(self):
        self.ctx.intent, _ = intent.intent_from_text("máximo $63")
        result = run_tool("search_products", {"max_price": 1000}, self.ctx)
        self.assertEqual([p["product_id"] for p in result["products"]], [str(self.product.public_id)])

    def test_multi_product_proposals_obey_aggregate_budget(self):
        self.ctx.intent, _ = intent.intent_from_text("hasta $100 en total")
        self.ctx.proposed_total = Decimal("0")
        variant = self.product.variants.get(option_label="Talla M")
        self.assertIsNotNone(orchestrator._propose_action("add_item_to_cart", {"variant_id": str(variant.public_id)}, self.ctx))
        self.assertIsNone(orchestrator._propose_action("add_item_to_cart", {"variant_id": str(variant.public_id)}, self.ctx))

    def test_adding_a_recipient_after_quote_requires_new_confirmation(self):
        variant = self.product.variants.get(option_label="Talla M")
        token = orchestrator._propose_action("add_item_to_cart", {"variant_id": str(variant.public_id)}, self.ctx)
        self.ctx.profile = self._profile(self.store_a, session=self.ctx.session_key)
        self.assertEqual(run_tool("add_item_to_cart", {"action_id": token.action_id}, self.ctx)["error"], "action_recipient_changed")

    def test_confirmed_action_event_is_exact_and_idempotent(self):
        variant = self.product.variants.get(option_label="Talla M")
        token = orchestrator._propose_action("add_item_to_cart", {"variant_id": str(variant.public_id)}, self.ctx)
        for _ in range(2):
            self.assertTrue(run_tool("add_item_to_cart", {"action_id": token.action_id}, self.ctx)["ok"])
        event = AnalyticsEvent.objects.get(name="advisor_action_confirmed")
        self.assertEqual(event.payload["variant"], str(variant.public_id))
        self.assertEqual(event.payload["cart"], str(services_commerce.get_open_cart(self.store_a, self.ctx.session_key).public_id))

    def test_unconfirmed_write_claim_is_replaced(self):
        with mock.patch.object(adapter, "chat", return_value={"role": "assistant", "content": "Ya he agregado el producto al carrito."}):
            reply = orchestrator.respond(self.conversation, "mostrame opciones", self.ctx)
        self.assertEqual(reply["answer_text"], orchestrator.ABSTENTION_TEXT)
        self.assertFalse(ActionToken.objects.exists())


class ConsentAndFitReleaseTests(ReinoTestCase):
    def test_profile_revocation_overrides_global_grant(self):
        profile = self._profile(self.store_a, session="specific-revoke")
        services_memory.grant_consent(self.store_a, profile.session_key, Consent.Purpose.MEASUREMENTS)
        services_memory.save_measurement(profile, chest_cm=36)
        services_memory.revoke_consent(self.store_a, profile.session_key, Consent.Purpose.MEASUREMENTS, profile)
        self.assertIsNone(services_memory.authorized_measurement(self.store_a, profile.session_key, profile))

    def test_new_conversation_requires_opt_in_for_saved_history(self):
        conversation = orchestrator.get_conversation(self.store_a, "new-private-visitor")
        self.assertTrue(conversation.memory_off)

    def test_invalid_units_nonfinite_and_post_conversion_limits(self):
        for value, unit in (("NaN", "cm"), ("Infinity", "cm"), ("40", "m"), ("100", "in"), ("0.0001", "cm")):
            with self.subTest(value=value, unit=unit), self.assertRaises(services_fit.InvalidMeasurement):
                services_fit.to_cm(value, unit)
        self.assertEqual(services_fit.to_cm("36,5", "cm"), Decimal("36.5"))

    def test_malformed_profile_is_not_a_server_error(self):
        self.assertIsNone(services_memory.get_profile(self.store_a, "session", "not-uuid"))

    def test_revoked_measurements_are_not_used_in_rules_fallback(self):
        profile = self._profile(self.store_a, session="consent")
        services_memory.grant_consent(self.store_a, "consent", Consent.Purpose.MEASUREMENTS, profile)
        services_memory.save_measurement(profile, chest_cm=36, neck_cm=24, back_cm=28)
        services_memory.revoke_consent(self.store_a, "consent", Consent.Purpose.MEASUREMENTS, profile)
        with mock.patch("reino.ai.fallback.recommend", return_value={"selection": []}) as recommend:
            fallback.respond("paseo", ToolContext(self.store_a, "consent", profile))
        self.assertIsNone(recommend.call_args.kwargs["measurement"])

    def test_storewide_consent_still_checks_profile_ownership(self):
        own = self._profile(self.store_a, session="owner")
        other = self._profile(self.store_b, session="owner")
        services_memory.grant_consent(self.store_a, "owner", Consent.Purpose.MEASUREMENTS)
        services_memory.save_measurement(own, chest_cm=36)
        services_memory.save_measurement(other, chest_cm=42)
        self.assertIsNotNone(services_memory.authorized_measurement(self.store_a, "owner", own))
        self.assertIsNone(services_memory.authorized_measurement(self.store_a, "owner", other))
        self.assertFalse(services_memory.delete_profile_memory(self.store_a, "owner", other))
        self.assertTrue(other.measurements.exists())

    def test_contradictory_and_nonfinite_budgets_request_clarification(self):
        _, errors = intent.intent_from_text("mínimo $50 y máximo $30")
        self.assertTrue(any("contradicen" in e for e in errors))
        for value in ("NaN", "Infinity", "1e999"):
            contract, errors = intent.validate({"budget": value, "must_have": 4})
            self.assertIsNone(contract.budget)
            self.assertTrue(errors)

    def test_only_compatible_variant_price_counts_for_budget(self):
        variant = self.product.variants.get(option_label="Talla S")
        variant.price_override = Decimal("99")
        variant.save()
        measurement = services_fit.SimpleMeasurement(Decimal("36"), Decimal("24"), Decimal("28"))
        result = services_recommend.recommend(self.store_a, services_recommend.normalize_intent(budget=63), measurement)
        self.assertNotIn(self.product.pk, [e["product"].pk for e in result["selection"]])

    def test_recommendation_card_quotes_the_compatible_variant(self):
        profile = self._profile(self.store_a, session="exact-price")
        services_memory.grant_consent(self.store_a, profile.session_key, Consent.Purpose.MEASUREMENTS, profile)
        services_memory.save_measurement(profile, chest_cm=36, neck_cm=24, back_cm=28)
        variant = self.product.variants.get(option_label="Talla S")
        variant.price_override = Decimal("99")
        variant.save()
        reply = run_tool("recommend_products", {"budget": 100}, ToolContext(self.store_a, profile.session_key, profile))
        card = reply["selection"][0]
        self.assertEqual(card["variant_id"], str(variant.public_id))
        self.assertIn("99", card["price"])

    def test_ranking_scores_follow_the_product_not_its_original_position(self):
        self.product.short_title = "Z económico"
        self.product.save()
        self.product2.short_title = "A costoso"
        self.product2.save()
        result = services_recommend.recommend(self.store_a, services_recommend.normalize_intent(budget=1000))
        self.assertEqual(result["selection"][0]["product"].pk, self.product.pk)


class LookLabReleaseTests(ReinoTestCase):
    def reveal(self, **draft):
        from reino import tenancy
        self.client.get(f"/s/{self.store_a.slug}/looklab/")
        session = self.client.session
        current = session[tenancy.SESSION_LOOKLAB]
        current[self.store_a.slug].update(draft)
        session[tenancy.SESSION_LOOKLAB] = current
        session.save()
        return self.client.get(f"/s/{self.store_a.slug}/looklab/?paso=revelacion")

    def test_invalid_measurement_budget_and_profile_are_handled(self):
        url = f"/s/{self.store_a.slug}/looklab/"
        for data, step in (({"action": "perfil", "profile_id": "invalid"}, "perfil"),
                           ({"action": "medidas", "chest": "NaN"}, "medidas"),
                           ({"action": "ocasion", "occasion": "paseo", "budget": "NaN"}, "ocasion")):
            response = self.client.post(url + "?paso=" + step, data)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["errors"])

    def test_batch_selection_is_quoted_and_idempotent(self):
        response = self.reveal(occasion="paseo")
        token = ActionToken.objects.get(action_id=response.context["action_id"])
        vid = next(iter(token.payload["options"]))
        url = f"/s/{self.store_a.slug}/looklab/agregar/"
        for _ in range(2):
            self.assertEqual(self.client.post(url, {"action_id": token.action_id, "variant": [vid, vid]}).status_code, 302)
        cart = services_commerce.get_open_cart(self.store_a, self.client.session.session_key)
        self.assertEqual(cart.items.get().quantity, 1)

    def test_changed_quote_rejects_entire_selection(self):
        response = self.reveal(occasion="paseo")
        token = ActionToken.objects.get(action_id=response.context["action_id"])
        vid = next(iter(token.payload["options"]))
        variant = self.product.variants.get(public_id=vid)
        variant.price_override = Decimal("89")
        variant.save()
        self.client.post(f"/s/{self.store_a.slug}/looklab/agregar/", {"action_id": token.action_id, "variant": vid})
        self.assertIsNone(services_commerce.get_open_cart(self.store_a, self.client.session.session_key))
        token.refresh_from_db()
        self.assertEqual(token.status, "proposed")

    def test_invalid_saved_ids_are_ignored(self):
        response = self.client.post(f"/s/{self.store_a.slug}/looklab/guardar/", {"variant": ["", "not-uuid"]})
        self.assertEqual(response.status_code, 302)

    def test_reveal_events_are_not_double_counted_on_refresh(self):
        self.reveal(occasion="paseo")
        self.client.get(f"/s/{self.store_a.slug}/looklab/?paso=revelacion")
        self.assertEqual(AnalyticsEvent.objects.filter(name="looklab_started").count(), 1)
        self.assertEqual(AnalyticsEvent.objects.filter(name="looklab_completed").count(), 1)
