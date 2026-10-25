"""S06 · Royal Stylist: conversación con productos.

- El perfil activo y la tienda siempre visibles.
- Las tarjetas usan IDs del catálogo de la tienda (render servidor).
- Ante fallo: mensaje honesto, selecciones conservadas, Reintentar/Colección.
- La conversación nunca bloquea el checkout.
"""

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render  # redirect: confirmación HTTP (N01)
from django.views.decorators.http import require_POST

from . import services_memory, tenancy
from .ai import adapter
from .ai.orchestrator import get_conversation, respond
from .ai.tools import ToolContext
from .views_storefront import _store_view

EXAMPLES = [
    "Un look para una celebración",
    "Ayudame con la talla",
    "Algo para el día a día",
]


def _ctx(request, store):
    session_key = tenancy.owner_key(request)
    pid = tenancy.active_profile_id(request, store)
    profile = services_memory.get_profile(store, session_key, pid) if pid else None
    return ToolContext(store, session_key, profile)


@_store_view
def stylist(request, store):
    conversation = get_conversation(store, tenancy.owner_key(request))
    messages = list(conversation.messages.filter(role__in=("user", "assistant"))
                    .order_by("-created_at", "-pk")[:50])[::-1]
    # Saved messages are historical; visible product cards are always rebuilt
    # from the current tenant catalog, including updated prices/media.
    from uuid import UUID
    from . import services_visibility
    from .ai.tools import _card
    identifiers = set()
    for message in messages:
        for card in message.cards or []:
            try:
                identifiers.add(UUID(str(card.get("product_id"))))
            except (ValueError, TypeError, AttributeError):
                continue
    products = {str(p.public_id): p for p in services_visibility.visible_products(store=store)
                .filter(public_id__in=identifiers).select_related("store").prefetch_related("media", "variants")}
    for message in messages:
        message.cards = [_card(products[c["product_id"]]) for c in message.cards or []
                         if isinstance(c, dict) and c.get("product_id") in products]
    return render(request, "reino/stylist.html", {
        "conversation": conversation,
        "messages": messages,
        "examples": EXAMPLES,
        "ai_available": adapter.available(),
        "profile": _ctx(request, store).profile,
        "memory_off": conversation.memory_off,
    })


@_store_view
@require_POST
def stylist_memory_mode(request, store):
    """Activa/desactiva el modo «sin guardar» (§10): al activarlo, la
    conversación deja de persistirse y el proveedor sólo ve el turno actual;
    al desactivarlo vuelve el historial normal. La elección es visible."""
    conversation = get_conversation(store, tenancy.owner_key(request))
    conversation.memory_off = request.POST.get("memory_off") == "1"
    conversation.save(update_fields=["memory_off"])
    if conversation.memory_off:
        # Lo ya guardado queda fuera del alcance del proveedor a partir de ahora.
        from django.utils import timezone
        conversation.history_sealed_before = timezone.now()
        conversation.save(update_fields=["history_sealed_before"])
    return redirect("reino_stylist", slug=store.slug)


@_store_view
@require_POST
def stylist_message(request, store):
    """Recibe un mensaje y devuelve la respuesta (HTML parcial o JSON)."""
    text = (request.POST.get("message") or "").strip()
    if not text:
        return JsonResponse({"error": "empty_message"}, status=400)
    if len(text) > settings.REINO_AI.get("MAX_INPUT_CHARS", 8000):
        return JsonResponse({"error": "message_too_long", "detail": "El mensaje supera el límite de caracteres."}, status=400)
    conversation = get_conversation(store, tenancy.owner_key(request))
    ctx = _ctx(request, store)
    reply = respond(conversation, text, ctx)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render(request, "reino/_stylist_reply.html", {"reply": reply, "store": store})
    return render(request, "reino/stylist_reply_page.html", {"reply": reply, "store": store})


@_store_view
@require_POST
def stylist_confirm_action(request, store):
    """El comprador CONFIRMA una acción propuesta por el asesor (R11).

    El permiso (ActionToken) es de un solo uso, con alcance tienda+sesión y
    caducidad; reintentar el mismo action_id nunca duplica la escritura.
    """
    from .ai.tools import run_tool
    action_id = (request.POST.get("action_id") or "").strip()
    ctx = _ctx(request, store)
    result = run_tool("add_item_to_cart", {"action_id": action_id}, ctx)
    if result.get("error"):
        request.session["reino_cart_error"] = (
            "Esa propuesta venció o ya no es válida. Pedí una nueva al asesor."
        )
        return redirect("reino_stylist", slug=store.slug)
    request.session["reino_flash"] = "Agregado al carrito."
    return redirect("reino_cart", slug=store.slug)
