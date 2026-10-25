"""Herramientas autorizadas del asesor (implementación servidor, §11).

El servidor inyecta tienda, sesión y perfil permitido. Las herramientas de
lectura no reservan nada; la única escritura (add_item_to_cart) revalida y es
idempotente vía servicios de comercio. No existe herramienta para fijar
precios, confirmar cobros, reembolsar, enviar marketing ni SQL libre.
"""

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .. import services_commerce as commerce
from .. import services_fit, services_memory
from .. import services_visibility as visibility
from ..models import (
    ActionToken, KnowledgeDocument, Order, Product, ShippingZone, Variant,
)
from ..money import fmt
from ..services_recommend import normalize_intent, recommend
from .schemas import TOOL_SPECS

logger = logging.getLogger(__name__)


def valid_arguments(name, args, *, proposing=False):
    """Enforce the tool contract before touching any model/queryset."""
    if not isinstance(args, dict):
        return False
    if name == "add_item_to_cart" and not proposing:
        return (set(args) <= {"action_id", "variant_id", "quantity"}
                and isinstance(args.get("action_id", ""), str)
                and len(args.get("action_id", "")) <= 64)
    spec = next((t["function"]["parameters"] for t in TOOL_SPECS if t["function"]["name"] == name), None)
    if spec is None or set(args) - set(spec["properties"]) or any(k not in args for k in spec.get("required", [])):
        return False
    for key, value in args.items():
        field = spec["properties"][key]
        kind = field["type"]
        if kind == "string" and (not isinstance(value, str) or len(value) > field.get("maxLength", 200)):
            return False
        if kind == "array" and (not isinstance(value, list) or len(value) > field.get("maxItems", 6)
                                or any(not isinstance(item, str) or len(item) > 80 for item in value)):
            return False
        if kind in ("number", "integer"):
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                return False
            try:
                number = Decimal(str(value))
                if not number.is_finite() or number <= 0 or number > field.get("maximum", 100000):
                    return False
                if kind == "integer" and number != number.to_integral_value():
                    return False
            except InvalidOperation:
                return False
        if "enum" in field and value not in field["enum"]:
            return False
    return True


class ToolContext:
    """Contexto firmado/controlado por servidor para una conversación."""

    def __init__(self, store, session_key, profile=None, cart=None):
        self.store = store
        self.session_key = session_key
        self.profile = profile
        self.cart = cart


def _card(product, reasons=(), fit=None, variant=None):
    image = product.media.first()
    prices = [v.price for v in product.variants.filter(is_active=True, stock__gt=0)]
    return {
        "product_id": str(product.public_id),
        "slug": product.slug,
        "title": product.short_title,
        "price": fmt(variant.price if variant else min(prices) if prices else product.base_price, product.store.currency),
        "price_kind": "exact" if variant else "from", "available": bool(prices),
        "variant_id": str(variant.public_id) if variant else None,
        "option": variant.option_label if variant else "",
        "image": image.path if image else "",
        "image_url": image.url if image else "",
        "alt": image.alt if image else product.short_title,
        "reason_codes": list(reasons),
        "fit_state": fit["state"] if fit else None,
        "fit_label": fit["label"] if fit else None,
    }


def run_tool(name, args, ctx: ToolContext):
    """Despacha una llamada del modelo a la herramienta permitida."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": "tool_not_allowed"}
    if not valid_arguments(name, args):
        return {"error": "invalid_arguments"}
    args = dict(args)
    contract = getattr(ctx, "intent", None)
    if contract and contract.budget is not None:
        if name in ("search_products", "recommend_products"):
            field = "max_price" if name == "search_products" else "budget"
            args[field] = min(Decimal(str(args.get(field, contract.budget))), contract.budget)
            if name == "recommend_products":
                args["budget_scope"] = contract.budget_scope
    if ctx.profile is not None and (ctx.profile.store_id != ctx.store.pk or ctx.profile.session_key != ctx.session_key):
        return {"error": "invalid_context"}
    if ctx.cart is not None and (ctx.cart.store_id != ctx.store.pk or ctx.cart.session_key != ctx.session_key):
        return {"error": "invalid_context"}
    try:
        return handler(args, ctx)
    except Exception as exc:  # la herramienta falla en cerrado y con mensaje útil
        logger.warning("ai_tool_failed tool=%s error_type=%s", name, type(exc).__name__)
        return {"error": "tool_error"}


def _search_products(args, ctx):
    from ..services_search import normalize
    qs = visibility.visible_products(store=ctx.store).filter(variants__is_active=True, variants__stock__gt=0).distinct()
    query = normalize(args.get("query") or "").strip()
    if query:
        qs = [p for p in qs if query in normalize(p.title)
              or query in normalize(p.short_title)
              or query in normalize(p.description or "")]
    if args.get("category"):
        qs = [p for p in qs if p.category == args["category"]]
    if args.get("occasion"):
        qs = [p for p in qs if args["occasion"] in (p.occasions or [])]
    if args.get("max_price"):
        qs = [p for p in qs if any(v.price <= Decimal(str(args["max_price"]))
                                  for v in p.variants.filter(is_active=True, stock__gt=0))]
    return {"products": [_card(p) for p in list(qs)[:6]]}


def _get_product_details(args, ctx):
    out = []
    for pid in (args.get("product_ids") or [])[:6]:
        p = visibility.visible_products(store=ctx.store).filter(public_id=pid).first()
        if p is None:
            continue  # IDs desconocidos no se hidratan (fail-closed)
        contract = getattr(ctx, "intent", None)
        if contract and contract.budget is not None and not any(
            v.price <= contract.budget for v in p.variants.filter(is_active=True, stock__gt=0)
        ):
            continue
        out.append({
            **_card(p),
            "description": p.description,
            "materials": p.materials or [],
            "variants": [
                {"variant_id": str(v.public_id), "sku": v.sku,
                 "option": v.option_label, "price": fmt(v.price, ctx.store.currency),
                 "available": v.stock > 0}
                for v in p.variants.filter(is_active=True)
            ],
        })
    return {"products": out}


def _check_inventory(args, ctx):
    v = Variant.objects.filter(public_id=args.get("variant_id"), is_active=True,
                               product__in=visibility.visible_products(store=ctx.store)).first()
    if v is None:
        return {"error": "unknown_variant"}
    qty = int(args.get("quantity") or 1)
    return {"variant_id": str(v.public_id), "sku": v.sku, "requested": qty,
            "available": v.stock >= qty, "stock": v.stock}


def _calculate_smart_fit(args, ctx):
    from decimal import Decimal as D

    p = visibility.visible_products(store=ctx.store).filter(public_id=args.get("product_id")).first()
    if p is None:
        return {"error": "unknown_product"}
    chest = D(str(args["chest_cm"])) if args.get("chest_cm") else None
    neck = D(str(args["neck_cm"])) if args.get("neck_cm") else None
    back = D(str(args["back_cm"])) if args.get("back_cm") else None
    if all(args.get(k) is None for k in ("chest_cm", "neck_cm", "back_cm")) and ctx.profile is not None:
        # Solo memoria con consentimiento vigente (R07).
        m = services_memory.authorized_measurement(ctx.store, ctx.session_key, ctx.profile)
        if m:
            chest, neck, back = m.chest_cm, m.neck_cm, m.back_cm
    return services_fit.evaluate(p, chest_cm=chest, neck_cm=neck, back_cm=back)


def _recommend_products(args, ctx):
    # Solo memoria con consentimiento vigente (R07).
    measurement = (
        services_memory.authorized_measurement(ctx.store, ctx.session_key, ctx.profile)
        if ctx.profile else None
    )
    intent = normalize_intent(
        occasion=args.get("occasion", ""), style=args.get("style", ""),
        budget=args.get("budget"), budget_scope=args.get("budget_scope", "products"),
        profile=ctx.profile, needs_fit=ctx.store.category == "moda canina",
    )
    result = recommend(ctx.store, intent, measurement=measurement, kind="stylist")
    selected, total = [], Decimal("0")
    for entry in result["selection"]:
        price = entry["price"]
        if intent["budget_scope"] == "total" and intent["budget"] is not None and total + price > intent["budget"]:
            continue
        selected.append(entry)
        total += price
    return {
        "selection": [
            {**_card(e["product"], e["reasons"], fit=e["fit"], variant=e["variant"]), "score": e["score"]}
            for e in selected
        ],
        "excluded": result["excluded"],
        "engine_version": result["engine_version"],
    }


def _get_store_policies(args, ctx):
    docs = KnowledgeDocument.objects.filter(
        store=ctx.store, topic=args.get("topic", ""), is_published=True,
        audience="customer",
    )
    return {"fragments": [
        {"title": d.title, "body": d.body, "version": d.version,
         "published_at": d.published_at.isoformat() if d.published_at else None}
        for d in docs[:5]
    ]}


def _get_shipping_options(args, ctx):
    zones = ShippingZone.objects.filter(store=ctx.store, is_active=True)
    return {"zones": [
        {"name": z.name, "mode": z.mode, "fee": fmt(z.fee, ctx.store.currency),
         "eta": z.eta_note or "Por confirmar"}
        for z in zones
    ]}


def _get_customer_preferences(args, ctx):
    if ctx.profile is None:
        return {"preferences": {}, "note": "sin perfil activo"}
    return {"preferences": services_memory.authorized_preferences(
        ctx.profile, ctx.store, ctx.session_key)}


def _add_item_to_cart(args, ctx):
    """Única escritura del asesor, por AUTORIZACIÓN verificable (R11, §8.2).

    El permiso (ActionToken) solo lo EMITE el servidor al proponer; la
    ejecución NUNCA crea su propio permiso (N05): un action_id desconocido,
    ajeno, vencido, de otra herramienta o malformado se rechaza sin escribir.

    Vinculación (N09/N10): la propuesta lleva destinatario y cotización
    aprobados (variante, precio, moneda, cantidad). Si el destinatario activo
    o el precio cambiaron, se exige una nueva propuesta: no se aplica
    silenciosamente el contexto nuevo.

    Consumir permiso y escribir el carrito ocurren en UNA transacción con la
    fila del permiso bloqueada: dos confirmaciones simultáneas agregan una
    sola vez y los reintentos devuelven el resultado guardado.
    """
    action_id = (args.get("action_id") or "").strip()
    if not action_id:
        return {"error": "action_authorization_required"}

    with transaction.atomic():
        token = ActionToken.objects.select_for_update().filter(
            action_id=action_id, store=ctx.store, session_key=ctx.session_key
        ).first()
        if token is None or token.tool != "add_item_to_cart":
            return {"error": "action_unknown"}
        if token.status == ActionToken.Status.EXECUTED:
            return dict(token.result)  # idempotente: misma acción, mismo resultado
        if token.status != ActionToken.Status.PROPOSED or token.expires_at <= timezone.now():
            if token.status == ActionToken.Status.PROPOSED:
                token.status = ActionToken.Status.EXPIRED
                token.save(update_fields=["status"])
            return {"error": "action_expired"}

        payload = token.payload
        # Destinatario vinculado a la propuesta (N09).
        bound_profile = payload.get("profile_id")
        current_profile = ctx.profile.id if ctx.profile is not None else None
        if current_profile != bound_profile:
            return {"error": "action_recipient_changed",
                    "detail": "El destinatario cambió; pedí una nueva propuesta."}

        v = Variant.objects.select_for_update().filter(
            public_id=payload.get("variant_id"), product__store=ctx.store,
            is_active=True, product__in=visibility.visible_products(store=ctx.store)).first()
        if v is None:
            return {"error": "unknown_variant"}
        # Cotización vinculada (N10): precio/moneda/variante/cantidad aprobados.
        approved_price = payload.get("unit_price")
        if approved_price is not None and str(v.price) != str(approved_price):
            return {"error": "action_quote_changed",
                    "detail": f"El precio cambió de ${approved_price} a ${v.price}; "
                              "pedí una nueva propuesta para revisarlo."}
        if payload.get("currency") and payload["currency"] != ctx.store.currency:
            return {"error": "action_quote_changed"}

        cart = ctx.cart or commerce.get_open_cart(ctx.store, ctx.session_key, create=True)
        try:
            commerce.add_item(cart, v, int(payload.get("quantity") or 1),
                              recipient=ctx.profile)
        except (commerce.CartError, commerce.StockConflict) as exc:
            return {"error": "cart_rejected", "detail": str(exc)}
        summary = commerce.cart_summary(cart)
        result = {"ok": True,
                  "cart_units": sum(l["item"].quantity for l in summary["lines"]),
                  "subtotal": fmt(summary["subtotal"], ctx.store.currency)}
        token.status = ActionToken.Status.EXECUTED
        token.result = result
        token.executed_at = timezone.now()
        token.save(update_fields=["status", "result", "executed_at"])
        from .. import services_analytics
        services_analytics.track(
            "advisor_action_confirmed", store=ctx.store, session_key=ctx.session_key,
            request_id="advisor:" + token.action_id,
            cart=str(cart.public_id), variant=str(v.public_id), action="add_to_cart",
        )
        return result


def _get_cart(args, ctx):
    cart = ctx.cart or commerce.get_open_cart(ctx.store, ctx.session_key)
    if cart is None:
        return {"lines": [], "subtotal": fmt(0, ctx.store.currency)}
    summary = commerce.cart_summary(cart)
    return {
        "lines": [
            {"title": l["item"].variant.product.short_title,
             "option": l["item"].variant.option_label,
             "quantity": l["item"].quantity,
             "subtotal": fmt(l["subtotal"], ctx.store.currency)}
            for l in summary["lines"]
        ],
        "subtotal": fmt(summary["subtotal"], ctx.store.currency),
        "shipping": "por calcular",
    }


def _get_order_status(args, ctx):
    """Solo pedidos del comprador autenticado (su sesión), nunca por adivinar."""
    ref = (args.get("reference") or "").strip().upper()
    order = Order.objects.filter(store=ctx.store, reference=ref).first()
    if order is None or not order.cart or order.cart.session_key != ctx.session_key:
        return {"error": "not_found"}  # sin filtrar existencia de pedidos ajenos
    return {
        "reference": order.reference,
        "status": order.get_status_display(),
        "payment": order.get_payment_status_display(),
        "preparation": order.get_prep_status_display(),
        "delivery": order.get_delivery_status_display(),
        "total": fmt(order.total, order.currency),
    }


_HANDLERS = {
    "search_products": _search_products,
    "get_product_details": _get_product_details,
    "check_inventory": _check_inventory,
    "calculate_smart_fit": _calculate_smart_fit,
    "recommend_products": _recommend_products,
    "get_store_policies": _get_store_policies,
    "get_shipping_options": _get_shipping_options,
    "get_customer_preferences": _get_customer_preferences,
    "add_item_to_cart": _add_item_to_cart,
    "get_cart": _get_cart,
    "get_order_status": _get_order_status,
}
