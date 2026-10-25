"""Explicit guest-to-account import, atomic and scoped to the presented cookie."""
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from . import services_commerce
from .models import (
    ActionToken, AIConversation, AnalyticsEvent, Cart, CheckoutSession,
    ComparisonSession, Consent, CustomerIdentity, Look, Preference,
    RecipientProfile, StockReservation,
)


class IdentityImportError(Exception):
    pass


@transaction.atomic
def import_guest_data(guest_key, user):
    """Caller must authenticate first and obtain explicit import consent.

    No account owner key is accepted as a guest; switching accounts cannot
    import another signed-in customer's data. Existing orders stay unchanged.
    """
    if not guest_key or guest_key.startswith("customer:"):
        return
    identity, _ = CustomerIdentity.objects.get_or_create(user=user)
    # Serialise merges into this account across simultaneous browser logins.
    identity = CustomerIdentity.objects.select_for_update().get(pk=identity.pk)
    owner = identity.owner_key
    guest_carts = list(Cart.objects.select_for_update().filter(session_key=guest_key))
    for cart in guest_carts:
        if cart.status != Cart.Status.OPEN:
            cart.session_key = owner
            cart.save(update_fields=["session_key"])
            continue
        target = Cart.objects.select_for_update().filter(
            store=cart.store, session_key=owner, status=Cart.Status.OPEN).first()
        # Login changes the owner/selection context, invalidating old quotes.
        checkouts = CheckoutSession.objects.filter(cart__in=[cart] + ([target] if target else []), is_current=True)
        StockReservation.objects.filter(checkout__in=checkouts, status="active").update(status="released")
        checkouts.update(is_current=False)
        if target:
            for item in cart.items.select_for_update():
                existing = target.items.filter(variant=item.variant, recipient=item.recipient).first()
                if existing:
                    if existing.service_slot_id != item.service_slot_id or existing.quantity + item.quantity > services_commerce.MAX_QUANTITY:
                        raise IdentityImportError("Los carritos no se pueden combinar sin cambiar cantidades u horarios. Ajustá el carrito de esta visita o ingresá sin importarlo.")
                    existing.quantity += item.quantity
                    existing.save(update_fields=["quantity"])
                    item.delete()
                else:
                    item.cart = target
                    item.save(update_fields=["cart"])
            Cart.objects.filter(pk=target.pk).update(version=F("version") + 1)
            cart.status = Cart.Status.MERGED
            # Preserve evidence-based attribution when the exact selected line
            # is transferred to the account's open cart.
            for event in AnalyticsEvent.objects.filter(session_key=guest_key, store=cart.store,
                                                        name="advisor_action_confirmed"):
                if event.payload.get("cart") == str(cart.public_id):
                    event.payload = {**event.payload, "cart": str(target.public_id)}
                    event.save(update_fields=["payload"])
        cart.session_key = owner
        cart.version += 1
        cart.save(update_fields=["session_key", "version", "status"])

    # Never allow an old global grant to override this account's revocation.
    for consent in Consent.objects.filter(session_key=guest_key, profile__isnull=True):
        existing = Consent.objects.filter(session_key=owner, store=consent.store,
                                           profile__isnull=True, purpose=consent.purpose).first()
        if existing:
            if consent.status == "revoked" or existing.status == "revoked":
                existing.status, existing.revoked_at = "revoked", timezone.now()
                existing.save(update_fields=["status", "revoked_at"])
            Preference.objects.filter(consent=consent).update(consent=existing)
            consent.delete()
    for model in (RecipientProfile, Consent, Look, AnalyticsEvent):
        model.objects.filter(session_key=guest_key).update(session_key=owner)

    for conversation in AIConversation.objects.filter(session_key=guest_key):
        existing = AIConversation.objects.filter(session_key=owner, store=conversation.store).first()
        if existing:
            conversation.messages.update(conversation=existing)
            existing.memory_off = existing.memory_off or conversation.memory_off
            existing.history_sealed_before = timezone.now()
            existing.save(update_fields=["memory_off", "history_sealed_before"])
            conversation.delete()
        else:
            conversation.session_key = owner
            conversation.history_sealed_before = timezone.now()
            conversation.save(update_fields=["session_key", "history_sealed_before"])
    guest_tray = ComparisonSession.objects.filter(session_key=guest_key).first()
    if guest_tray:
        target_tray = ComparisonSession.objects.filter(session_key=owner).first()
        if target_tray:
            combined = list(target_tray.items)
            ids = {i.get("variant_id") for i in combined}
            for item in guest_tray.items:
                if item.get("variant_id") not in ids and len(combined) < 4:
                    combined.append(item)
                    ids.add(item.get("variant_id"))
            target_tray.items = combined
            target_tray.save(update_fields=["items", "updated_at"])
            guest_tray.delete()
        else:
            guest_tray.session_key = owner
            guest_tray.save(update_fields=["session_key"])
    ActionToken.objects.filter(session_key=guest_key, status="proposed").update(status="cancelled")
