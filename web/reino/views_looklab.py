"""S04 · LookLab: flujo de cuatro etapas editables y una revelación.

- Borrador en sesión; volver atrás conserva información (A07).
- La foto jamás es obligatoria ni se usa para deducir medidas.
- «No tengo las medidas» continúa con talla pendiente.
- La revelación no simula una espera de análisis ni premarca extras.
- Memoria solo con consentimiento explícito separado.
"""

from decimal import Decimal, InvalidOperation
from datetime import timedelta
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services_analytics
from . import services_fit, services_memory, tenancy
from .models import ActionToken, Consent, Product, Variant
from .services_recommend import compose_bundle, normalize_intent, recommend, variants_with_fit
from .views_storefront import _store_view

STEPS = ["perfil", "medidas", "personalidad", "ocasion", "revelacion"]

STYLES = [
    ("royal-classic", "Royal Classic", "Sobrio y pulido."),
    ("urban-king", "Urban King", "Cotidiano y moderno."),
    ("little-adventurer", "Little Adventurer", "Práctico para explorar."),
    ("party-royalty", "Party Royalty", "Ocasión especial."),
]

OCCASIONS = [
    ("paseo", "Paseo"), ("celebracion", "Celebración"),
    ("fotos", "Fotos"), ("diario", "Día a día"), ("regalo", "Es un regalo"),
]


def _step(request, store):
    step = request.GET.get("paso", "perfil")
    return step if step in STEPS else "perfil"


@_store_view
def looklab(request, store):
    """Pantalla principal del flujo (una URL, pasos por ?paso=)."""
    session_key = tenancy.owner_key(request)
    draft = tenancy.looklab_draft(request, store)
    step = _step(request, store)
    errors = {}
    if not draft.get("flow_id"):
        draft["flow_id"] = uuid.uuid4().hex
        tenancy.set_looklab_draft(request, store, draft)
    if step == "perfil" and request.method == "GET":
        services_analytics.track("looklab_started", store=store,
                                 request_id="look-start:" + draft["flow_id"],
                                 session_key=session_key or "")

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "perfil":
            profile_id = request.POST.get("profile_id", "")
            old_profile_id = draft.get("profile_id")
            if profile_id == "new":
                alias = request.POST.get("alias", "").strip()
                if not alias:
                    errors["alias"] = "Poné un nombre o alias a tu pequeño rey."
                else:
                    profile = services_memory.create_profile(
                        store, session_key, alias, kind="dog",
                        breed=request.POST.get("breed", "").strip(),
                    )
                    tenancy.set_active_profile(request, store, profile.public_id)
                    draft["profile_id"] = str(profile.public_id)
            elif profile_id == "explore":
                draft["profile_id"] = None
                tenancy.set_active_profile(request, store, None)
            else:
                profile = services_memory.get_profile(store, session_key, profile_id)
                if profile is None:
                    errors["profile"] = "Ese perfil ya no existe."
                else:
                    tenancy.set_active_profile(request, store, profile.public_id)
                    draft["profile_id"] = str(profile.public_id)
            if not errors:
                if draft.get("profile_id") != old_profile_id:
                    for key in ("converted", "measurement_saved", "chest", "neck", "back"):
                        draft.pop(key, None)
                draft["step"] = "medidas"
                tenancy.set_looklab_draft(request, store, draft)
                return redirect(f"{request.path}?paso=medidas")

        elif action == "medidas":
            unit = request.POST.get("unit", "cm")
            if unit not in ("cm", "in"):
                errors["chest"] = "Elegí centímetros o pulgadas."
            draft["unit"] = unit
            converted = {}
            for field in ("chest", "neck", "back"):
                raw = request.POST.get(field, "").strip()
                draft[field] = raw
                if raw:
                    try:
                        converted[field] = services_fit.to_cm(raw, unit)
                    except services_fit.InvalidMeasurement as exc:
                        errors[field] = str(exc)
            if not errors:
                profile = _draft_profile(request, store, draft)
                # Reiniciar SIEMPRE la medida del intento: «no tengo las
                # medidas» nunca arrastra silenciosamente un borrador viejo.
                draft["converted"] = {}
                draft["measurement_saved"] = False
                if any(converted.values()):
                    if profile and request.POST.get("remember") == "1":
                        # Guardar medidas requiere consentimiento explícito.
                        services_memory.grant_consent(
                            store, session_key, Consent.Purpose.MEASUREMENTS, profile)
                        services_memory.save_measurement(
                            profile, chest_cm=converted.get("chest"),
                            neck_cm=converted.get("neck"), back_cm=converted.get("back"),
                            original={"chest": draft.get("chest"), "neck": draft.get("neck"),
                                      "back": draft.get("back"), "unit": unit},
                            source="looklab",
                        )
                        draft["measurement_saved"] = True
                    # Medidas de esta visita (con o sin perfil): precedencia
                    # sobre cualquier dato guardado (R09).
                    draft["converted"] = {k: str(v) for k, v in converted.items()}
                draft["step"] = "personalidad"
                tenancy.set_looklab_draft(request, store, draft)
                return redirect(f"{request.path}?paso=personalidad")

        elif action == "personalidad":
            style = request.POST.get("style", "")
            if style not in {s[0] for s in STYLES}:
                errors["style"] = "Elegí una de las cuatro opciones."
            else:
                draft["style"] = style
                draft["step"] = "ocasion"
                tenancy.set_looklab_draft(request, store, draft)
                return redirect(f"{request.path}?paso=ocasion")

        elif action == "ocasion":
            occasion = request.POST.get("occasion", "")
            if occasion not in dict(OCCASIONS):
                errors["occasion"] = "Elegí una ocasión."
            budget_raw = request.POST.get("budget", "").strip()
            budget = None
            if budget_raw:
                try:
                    budget = Decimal(budget_raw)
                    if not budget.is_finite() or budget <= 0 or budget > Decimal("100000"):
                        raise InvalidOperation
                except InvalidOperation:
                    errors["budget"] = "Ingresá un presupuesto válido (opcional)."
            if not errors:
                draft["occasion"] = occasion
                draft["budget"] = str(budget) if budget else None
                scope = request.POST.get("budget_scope", "products")
                draft["budget_scope"] = scope if scope in ("products", "total") else "products"
                draft["step"] = "revelacion"
                tenancy.set_looklab_draft(request, store, draft)
                return redirect(f"{request.path}?paso=revelacion")

    # ---- render por paso ------------------------------------------------
    profile = _draft_profile(request, store, draft)
    context = {
        "step": step, "step_index": STEPS.index(step) + 1, "total_steps": 4,
        "draft": draft, "profile": profile, "errors": errors,
        "profiles": services_memory.list_profiles(store, session_key),
        "styles": STYLES, "occasions": OCCASIONS,
        "measurement": services_memory.latest_measurement(profile) if profile else None,
    }

    if step == "revelacion":
        context.update(_reveal(request, store, draft, profile))
    return render(request, "reino/looklab.html", context)


def _draft_profile(request, store, draft):
    pid = draft.get("profile_id")
    if not pid:
        return None
    return services_memory.get_profile(store, tenancy.owner_key(request), pid)


class _DraftMeasurement:
    """Medidas temporales del borrador (sin consentimiento de guardado)."""

    def __init__(self, converted):
        from decimal import Decimal as D
        self.chest_cm = D(converted["chest"]) if converted.get("chest") else None
        self.neck_cm = D(converted["neck"]) if converted.get("neck") else None
        self.back_cm = D(converted["back"]) if converted.get("back") else None


def _resolve_measurement(request, store, draft, profile):
    """Precedencia explícita de medidas (R09):

    1. Las introducidas para ESTE intento (borrador convertido), siempre.
    2. Después, las persistentes vigentes y AUTORIZADAS (consentimiento).
    3. Finalmente, datos insuficientes (talla honestamente pendiente).
    """
    if draft.get("converted") and any(draft["converted"].values()):
        return _DraftMeasurement(draft["converted"]), "esta_visita"
    if profile is not None:
        saved = services_memory.authorized_measurement(store, profile.session_key, profile)
        if saved is not None:
            return saved, "guardadas"
    return None, "sin_datos"


def _pick_variant(product, measurement, needs_fit):
    """Unidad comprable real: producto + variante + regla de talla + precio (R08).

    Devuelve (variante|None, fit, variantes_para_elegir, agotada_tu_talla).
    NUNCA sustituye la talla compatible por otra: si la talla de la persona
    está agotada, la pieza no se ofrece como compatible.
    """
    rows, fit = variants_with_fit(product, measurement)
    in_stock = [r for r in rows if r["variant"].stock > 0]
    if not needs_fit:
        chosen = min((r["variant"] for r in in_stock), key=lambda v: (v.price, v.pk)) if in_stock else None
        return chosen, fit, rows, False
    if fit is None or fit["state"] == "sin_datos":
        # Sin medidas: la talla queda pendiente; la elección es explícita.
        fit = fit or {"state": "sin_datos", "label": "Talla por confirmar",
                      "candidates": [], "explanation": ""}
        return None, fit, rows, False
    suggested = [r for r in rows if r["fit_hint"] == "sugerida"]
    available_suggested = [r for r in suggested if r["variant"].stock > 0]
    if available_suggested:
        return min((r["variant"] for r in available_suggested), key=lambda v: (v.price, v.pk)), fit, rows, False
    if suggested:
        # La talla compatible existe pero está agotada: NO ofrecer otra (R08).
        return None, fit, rows, True
    # Sin candidatas (incompatible): la pieza no aplica para estas medidas.
    return None, fit, rows, False


def _reveal(request, store, draft, profile):
    if request is not None:  # las pruebas de unidad llaman con request=None
        services_analytics.track("looklab_completed", store=store,
                                 request_id="look-complete:" + draft["flow_id"],
                                 session_key=tenancy.owner_key(request) or "")
    """Calcula la revelación: UNA pieza principal + complementos coherentes.

    - Precedencia de medidas de esta visita sobre las guardadas (R09).
    - Talla por variante exacta; nunca sustitución silenciosa (R08).
    - Presupuesto del conjunto acumulado y estricto (R10).
    """
    measurement, measurement_origin = _resolve_measurement(request, store, draft, profile)
    if measurement and not any([measurement.chest_cm, measurement.neck_cm, measurement.back_cm]):
        measurement, measurement_origin = None, "sin_datos"

    needs_fit = store.category == "moda canina"
    budget = Decimal(draft["budget"]) if draft.get("budget") else None
    budget_scope = draft.get("budget_scope", "products")
    intent = normalize_intent(
        occasion=draft.get("occasion", ""), style=draft.get("style", ""),
        budget=draft.get("budget"), budget_scope=budget_scope,
        profile=profile, needs_fit=needs_fit,
    )
    result = recommend(store, intent, measurement=measurement, kind="looklab")

    selection, unavailable, excluded = [], [], list(result["excluded"])
    total = Decimal("0")
    total_budget = budget if (budget is not None and budget_scope in
                              ("total", "conjunto", "pedido")) else None

    for entry in result["selection"]:
        product = entry["product"]
        chosen, fit, rows, size_sold_out = _pick_variant(product, measurement, needs_fit)
        if size_sold_out:
            unavailable.append({
                "product": product, "fit": fit,
                "note": "Tu talla está agotada en esta pieza.",
            })
            continue
        if chosen is None and not (needs_fit and fit["state"] == "sin_datos"):
            continue  # sin unidad comprable y con talla conocida: no entra
        # Precio de la unidad REALMENTE seleccionada (variante); si la talla
        # está pendiente, el precio de referencia honesto es el base.
        unit_price = chosen.price if chosen else min(r["variant"].price for r in rows if r["variant"].stock > 0)
        if budget is not None and unit_price > budget:
            continue
        if total_budget is not None and total + unit_price > total_budget:
            excluded.append({"product": product.short_title, "reason": "OVER_BUDGET_TOTAL"})
            continue  # menos piezas, jamás inventar que el presupuesto alcanzó (R10)
        selection.append({
            "product": product, "variant": chosen, "score": entry["score"],
            "reasons": entry["reasons"], "fit": fit,
            "size_pending": chosen is None,
            "selectable_variants": [r["variant"] for r in rows if r["variant"].stock > 0],
            "unit_price": unit_price,
        })
        total += unit_price

    # Conjunto coherente (§6.6 / §7.3): UNA pieza principal; las demás
    # candidatas son ALTERNATIVAS (opciones de look), nunca se suman. Los
    # complementos son de función distinta, opcionales y dentro del
    # presupuesto restante.
    main = selection[0] if selection else None
    alternatives = selection[1:] if len(selection) > 1 else []
    complements = []
    if main is not None:
        bundle, _ = compose_bundle(store, main["product"], measurement=measurement,
                                   budget=total_budget, max_extras=2)
        selected_ids = {e["product"].pk for e in selection}
        comp_total = main["unit_price"]
        for item in bundle:
            if item["role"] != "complemento" or item["product"].pk in selected_ids:
                continue
            c_variant, c_fit, c_rows, c_sold_out = _pick_variant(
                item["product"], measurement, needs_fit)
            if c_sold_out:
                continue
            if c_variant is None and c_fit and c_fit["state"] not in ("sin_datos",):
                continue
            available = [r["variant"] for r in c_rows if r["variant"].stock > 0]
            if not available:
                continue
            c_price = c_variant.price if c_variant else min(v.price for v in available)
            if total_budget is not None and comp_total + c_price > total_budget:
                continue  # presupuesto acumulado también en complementos (R10)
            complements.append({
                "product": item["product"], "variant": c_variant, "fit": c_fit,
                "size_pending": c_variant is None,
                "selectable_variants": [r["variant"] for r in c_rows if r["variant"].stock > 0],
                "unit_price": c_price,
            })
            comp_total += c_price

    action_id = ""
    if request is not None and main is not None:
        # Quote the visible selectable units. A stale form cannot silently
        # add another price, pet, or arbitrary catalog ID.
        options = {}
        for item in [main] + complements:
            variants = [item["variant"]] if item["variant"] else item["selectable_variants"]
            options.update({str(v.public_id): str(v.price) for v in variants})
        token = ActionToken.objects.create(
            action_id=uuid.uuid4().hex[:24], tool="looklab_add", store=store,
            session_key=tenancy.owner_key(request),
            payload={"options": options, "profile_id": profile.pk if profile else None,
                     "budget": str(budget) if budget else None, "budget_scope": budget_scope},
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        action_id = token.action_id
    return {
        "selection": selection,          # compatibilidad con pruebas (matriz A)
        "main": main, "alternatives": alternatives, "complements": complements,
        "unavailable": unavailable, "excluded": excluded,
        "engine_version": result["engine_version"], "selection_total": total,
        "budget": budget, "budget_scope": budget_scope,
        "measurement_origin": measurement_origin,
        "alias": profile.alias if profile else "",
        "action_id": action_id,
    }


@_store_view
@require_POST
def looklab_add(request, store):
    """Agrega la selección elegida al carrito (una operación, clave idempotente).

    El cliente elige qué piezas incorporar; nunca se premarcan extras.
    """
    from . import services_commerce as commerce

    variant_ids = list(dict.fromkeys(v for v in request.POST.getlist("variant") if v))
    if not variant_ids:
        return redirect("reino_looklab", slug=store.slug)
    from . import services_visibility as visibility
    try:
        with transaction.atomic():
            token = ActionToken.objects.select_for_update().filter(
                action_id=request.POST.get("action_id", ""), store=store,
                session_key=tenancy.owner_key(request), tool="looklab_add",
            ).first()
            if token and token.status == ActionToken.Status.EXECUTED:
                return redirect("reino_cart", slug=store.slug)
            if not token or token.status != ActionToken.Status.PROPOSED or token.expires_at <= timezone.now():
                raise commerce.CartError("La selección venció. Volvé a LookLab para revisarla.")
            if len(variant_ids) > 3 or set(variant_ids) - set(token.payload["options"]):
                raise commerce.CartError("La selección no coincide con el look mostrado.")
            profile_id = tenancy.active_profile_id(request, store)
            recipient = services_memory.get_profile(store, tenancy.owner_key(request), profile_id) if profile_id else None
            if (recipient.pk if recipient else None) != token.payload.get("profile_id"):
                raise commerce.CartError("El destinatario cambió. Revisá el look nuevamente.")
            variants = list(Variant.objects.select_for_update().filter(
                public_id__in=variant_ids, product__in=visibility.visible_products(store=store),
                is_active=True, stock__gt=0,
            ))
            if len(variants) != len(variant_ids):
                raise commerce.CartError("Una pieza ya no está disponible.")
            if any(str(v.price) != token.payload["options"][str(v.public_id)] for v in variants):
                raise commerce.CartError("El precio cambió. Revisá el look antes de confirmar.")
            budget = Decimal(token.payload["budget"]) if token.payload.get("budget") else None
            if budget is not None and ((token.payload.get("budget_scope") == "total" and sum(v.price for v in variants) > budget)
                                       or any(v.price > budget for v in variants)):
                raise commerce.CartError("La selección supera tu presupuesto.")
            cart = commerce.get_open_cart(store, tenancy.owner_key(request), create=True)
            for variant in variants:
                commerce.add_item(cart, variant, 1, recipient=recipient)
            token.status = ActionToken.Status.EXECUTED
            token.executed_at = timezone.now()
            token.save(update_fields=["status", "executed_at"])
    except (commerce.CartError, commerce.StockConflict, ValidationError, ValueError) as exc:
        request.session["reino_cart_error"] = str(exc) if isinstance(exc, commerce.CartError) else "La selección ya no es válida. Revisá el look."
    return redirect("reino_cart", slug=store.slug)


@_store_view
@require_POST
def looklab_save(request, store):
    """Guarda el look (no reserva precio ni stock) con consentimiento separado."""
    from .models import Look

    draft = tenancy.looklab_draft(request, store)
    profile = _draft_profile(request, store, draft)
    items = []
    from . import services_visibility as visibility
    for vid in list(dict.fromkeys(request.POST.getlist("variant")))[:3]:
        try:
            v = Variant.objects.filter(public_id=vid, is_active=True,
                                       product__in=visibility.visible_products(store=store)).first()
        except (ValidationError, ValueError):
            continue
        if v:
            items.append({"variant_id": str(v.public_id), "title": v.product.short_title,
                          "option": v.option_label, "price": str(v.price)})
    if items:
        Look.objects.create(
            store=store, session_key=tenancy.owner_key(request), profile=profile,
            occasion=draft.get("occasion", ""), style=draft.get("style", ""),
            budget=Decimal(draft["budget"]) if draft.get("budget") else None,
            items=items,
        )
        request.session["reino_flash"] = "Look guardado en tu cuenta."
    return redirect("reino_looklab", slug=store.slug)
