"""Motor de recomendaciones P0 (diseño §13).

Paso A: normalizar intención (obligatorio vs preferencias).
Paso B: recuperar candidatos (atributos curados + texto).
Paso C: filtrar ANTES de puntuar — lo desconocido nunca cuenta como cumplido.
Paso D: score = 100 × (0.35 I + 0.22 F + 0.16 Q + 0.10 D + 0.10 P + 0.07 V),
        con renormalización si una señal opcional no existe; jamás para saltar
        una restricción obligatoria desconocida.
Paso E: presentar hasta 3 opciones con códigos de razón auditables.
Paso F: componer conjuntos con compatibilidad registrada y presupuesto acumulado.

Versión del motor: ENGINE_VERSION (se guarda en cada RecommendationEvent).
"""

import uuid
from decimal import Decimal, InvalidOperation

from . import services_ranking, services_visibility as visibility
from .models import Product, RecommendationEvent, Variant
from .services_fit import COMPATIBLE, EDGE, evaluate_for_profile

ENGINE_VERSION = "v1"

# Códigos de razón autorizados (el LLM solo puede explicar estos).
MATCH_OCCASION = "MATCH_OCCASION"
MATCH_STYLE = "MATCH_STYLE"
FIT_RANGE_CONFIRMED = "FIT_RANGE_CONFIRMED"
FIT_NEEDS_REVIEW = "FIT_NEEDS_REVIEW"
FIT_UNKNOWN = "FIT_UNKNOWN"
BUDGET_TOTAL_OK = "BUDGET_TOTAL_OK"
DELIVERY_UNKNOWN = "DELIVERY_UNKNOWN"
QUALITY_COMPLETE = "QUALITY_COMPLETE"
EDITORIAL_FEATURED = "EDITORIAL_FEATURED"

WEIGHTS = {"I": 0.35, "F": 0.22, "Q": 0.16, "D": 0.10, "P": 0.10, "V": 0.07}


def normalize_intent(occasion="", style="", budget=None, budget_scope="products",
                     profile=None, needs_fit=True):
    """Paso A: separa necesidades obligatorias de preferencias."""
    if budget not in (None, ""):
        try:
            budget = Decimal(str(budget))
            if not budget.is_finite() or budget <= 0 or budget > Decimal("100000"):
                raise ValueError("Presupuesto fuera de rango.")
        except InvalidOperation:
            raise ValueError("Presupuesto inválido.") from None
    else:
        budget = None
    return {
        "occasion": occasion or "",
        "style": style or "",
        "budget": budget,
        "budget_scope": budget_scope,
        "profile_id": str(profile.public_id) if profile else None,
        "needs_fit": bool(needs_fit),
    }


def _candidates(store, intent):
    """Paso B: unión de atributos de ocasión/estilo y todo lo publicado."""
    qs = visibility.visible_products(store=store)
    if intent["occasion"]:
        preferred = [p for p in qs if intent["occasion"] in (p.occasions or [])]
        rest = [p for p in qs if p not in preferred]
        return preferred + rest
    return list(qs)


def _hard_filter(product, intent, measurement):
    """Paso C: restricciones obligatorias. Devuelve (elegible, razón_exclusión)."""
    variants = [v for v in product.variants.filter(is_active=True) if v.stock > 0]
    if not variants:
        return False, "OUT_OF_STOCK"
    if intent["needs_fit"] and measurement is not None:
        # La talla incompatible excluye; lo desconocido NO excluye pero se separa.
        fit = evaluate_for_profile(product, measurement)
        if fit["state"] not in (COMPATIBLE, EDGE) and fit["state"] != "sin_datos":
            return False, "FIT_INCOMPATIBLE"
        if fit["state"] in (COMPATIBLE, EDGE):
            from .services_fit import label_matches
            variants = [v for v in variants if any(label_matches(c, v.option_label) for c in fit["candidates"])]
            if not variants:
                return False, "FIT_OUT_OF_STOCK"
    if intent["budget"] is not None:
        cheapest = min(v.price for v in variants)
        if cheapest > intent["budget"]:
            return False, "OVER_BUDGET"
    return True, None


def _score(product, intent, measurement, fit_cache):
    """Paso D: señales 0..1, pesos renormalizados si falta evidencia opcional."""
    signals, reasons = {}, []

    # I · Intención: coincidencia con ocasión/estilo confirmados.
    if intent["occasion"]:
        i = 1.0 if intent["occasion"] in (product.occasions or []) else 0.35
        if i == 1.0:
            reasons.append(MATCH_OCCASION)
    else:
        i = None
    signals["I"] = i

    # F · Compatibilidad de talla (validación del servicio de fit).
    if intent["needs_fit"]:
        fit = fit_cache.get(product.pk)
        if fit is None:
            fit = evaluate_for_profile(product, measurement)
            fit_cache[product.pk] = fit
        f = {COMPATIBLE: 1.0, EDGE: 0.6}.get(fit["state"])
        if fit["state"] == COMPATIBLE:
            reasons.append(FIT_RANGE_CONFIRMED)
        elif fit["state"] == EDGE:
            reasons.append(FIT_NEEDS_REVIEW)
        elif fit["state"] == "sin_datos":
            reasons.append(FIT_UNKNOWN)
        signals["F"] = f
    else:
        signals["F"] = None

    # Q · Evidencia de calidad: ficha revisada, fotos, materiales cargados.
    has_media = product.media.exists()
    has_materials = bool(product.materials)
    has_fit_rule = product.fit_rules.filter(is_active=True).exists()
    signals["Q"] = round(0.4 * has_media + 0.3 * has_materials + 0.3 * has_fit_rule, 3)
    if signals["Q"] >= 0.99:
        reasons.append(QUALITY_COMPLETE)

    # D · Entrega: P0 no confirma fechas — señal honesta.
    signals["D"] = None
    reasons.append(DELIVERY_UNKNOWN)

    # P · Preferencias: estilo expresado en la sesión/perfil autorizado.
    if intent["style"]:
        p = 1.0 if intent["style"] in (product.styles or []) else 0.4
        if p == 1.0:
            reasons.append(MATCH_STYLE)
    else:
        p = None
    signals["P"] = p

    # V · Valor premium verificable: pieza editorial destacada con razón cargada.
    v = 1.0 if (product.is_featured and product.reason) else None
    if v:
        reasons.append(EDITORIAL_FEATURED)
    signals["V"] = v

    used = {k: w for k, w in WEIGHTS.items() if signals.get(k) is not None}
    total_w = sum(used.values()) or 1
    score = sum(signals[k] * w for k, w in used.items()) / total_w
    return round(100 * score, 1), reasons


def recommend(store, intent, measurement=None, limit=3, kind="looklab"):
    """Pipeline completo A→E. Devuelve selección con razones auditables."""
    fit_cache = {}
    chosen, excluded = [], []
    measurement = measurement if intent["needs_fit"] else None

    for product in _candidates(store, intent):
        ok, why = _hard_filter(product, intent, measurement)
        if not ok:
            excluded.append({"product": product.short_title, "reason": why})
            continue
        score, reasons = _score(product, intent, measurement, fit_cache)
        available = list(product.variants.filter(is_active=True, stock__gt=0))
        fit = fit_cache.get(product.pk)
        if fit and fit["state"] in (COMPATIBLE, EDGE):
            from .services_fit import label_matches
            available = [v for v in available if any(label_matches(c, v.option_label) for c in fit["candidates"])]
        variant = min(available, key=lambda v: (v.price, v.pk))
        if intent["budget"] is not None and score >= 0:
            cheapest = variant.price
            if intent["budget_scope"] == "products" and cheapest <= intent["budget"]:
                reasons.append(BUDGET_TOTAL_OK)
        chosen.append({"product": product, "variant": variant, "price": variant.price,
                       "fit": fit, "score": score, "reasons": reasons})

    # Orden final: política de ranking VERSIONADA (§6.4, ranking-v1). Los
    # candidatos ya son elegibles; aquí sólo se ordenan con desglose.
    ranked = services_ranking.score_candidates(
        [{"product": c["product"],
          "variant": c["variant"],
          "price": c["price"],
          "reasons": c["reasons"], "legacy_score": c["score"]} for c in chosen],
        intent={**intent, "preferences": intent.get("preferences") or {}})
    by_id = {c["product"].pk: c for c in chosen}
    for r in ranked:
        c = by_id[r["product"].pk]
        c["rank_score"] = str(r["score"])
        c["score_parts"] = r["score_parts"]
    selection = [by_id[r["product"].pk] for r in ranked[:limit]]

    RecommendationEvent.objects.create(
        store=store,
        request_id=uuid.uuid4().hex[:12],
        kind=kind,
        intent={k: (str(v) if isinstance(v, Decimal) else v) for k, v in intent.items()},
        candidates=[
            {"product_id": str(c["product"].public_id), "score": c["score"], "reasons": c["reasons"]}
            for c in selection
        ],
        excluded=excluded,
        reasons=sorted({r for c in selection for r in c["reasons"]}),
        engine_version=ENGINE_VERSION + "+" + services_ranking.RANKING_VERSION,
    )
    return {"selection": selection, "excluded": excluded, "engine_version": ENGINE_VERSION}


def compose_bundle(store, main_product, measurement=None, budget=None, max_extras=2):
    """Paso F: pieza principal + hasta 2 complementos compatibles registrados.

    Un complemento solo entra si hay relación de ocasión/estilo catalogada;
    nunca se inventa compatibilidad ni se duplica función. El presupuesto es
    acumulado: un extra que supera el total queda fuera.
    """
    if main_product.store_id != store.pk:
        return [], Decimal("0")
    budget = Decimal(str(budget)) if budget is not None else None
    if budget is not None and not budget.is_finite():
        raise ValueError("Presupuesto inválido.")
    bundle, total = [], main_product.base_price
    main = {
        "product": main_product,
        "role": "principal",
        "price": main_product.base_price,
    }
    bundle.append(main)
    main_occasions = set(main_product.occasions or [])
    main_styles = set(main_product.styles or [])
    categories = {main_product.category}

    candidates = (
        visibility.visible_products(store=main_product.store)
        .exclude(pk=main_product.pk)
        .exclude(category=main_product.category)  # sin duplicar función
    )
    for product in candidates:
        if len(bundle) > max_extras:
            break
        if product.category in categories:
            continue
        shared = (set(product.occasions or []) & main_occasions) or (
            set(product.styles or []) & main_styles
        )
        if not shared:
            continue  # sin compatibilidad registrada, no se sugiere
        if not product.variants.filter(is_active=True, stock__gt=0).exists():
            continue  # pieza no disponible invalida el complemento
        if budget is not None and total + product.base_price > budget:
            continue  # presupuesto acumulado estricto
        bundle.append({"product": product, "role": "complemento", "price": product.base_price})
        categories.add(product.category)
        total += product.base_price
    return bundle, total


def variants_with_fit(product, measurement):
    """Variantes activas anotadas con su estado de talla (coincidencia EXACTA).

    R08: una variante solo puede decir «sugerida» si la regla de talla la
    respalda a ELLA; jamás por subcadena ni por hermano de producto.
    """
    from .services_fit import label_matches
    fit = evaluate_for_profile(product, measurement) if measurement else None
    rows = []
    for v in product.variants.filter(is_active=True):
        state = None
        if fit and fit["candidates"]:
            state = "sugerida" if any(label_matches(c, v.option_label)
                                      for c in fit["candidates"]) else "otra"
        rows.append({"variant": v, "fit_hint": state})
    return rows, fit
