"""Modo por reglas del asesor: contingencia honesta, etiquetada como tal.

Reutiliza la intención de keywords del asistente histórico pero sobre el
catálogo en base de datos y con el motor de recomendación real. NO cuenta
como cumplimiento del requisito de IA real (puerta de aceptación §2).
"""

from ..services_recommend import normalize_intent, recommend
from decimal import Decimal

OCCASION_WORDS = {
    "celebracion": ("boda", "wedding", "celebra", "fiesta", "evento", "elegante", "formal"),
    "fotos": ("foto", "fotos", "sesión", "sesion", "retrato"),
    "paseo": ("paseo", "caminar", "calle", "parque", "walk"),
    "diario": ("diario", "casa", "día a día", "cotidiano", "everyday", "abrigo", "frío", "frio"),
    "regalo": ("regalo", "regalar", "cumpleaños", "gift"),
}


def _guess_occasion(text):
    for occasion, words in OCCASION_WORDS.items():
        if any(w in text for w in words):
            return occasion
    return ""


def respond(user_text, ctx):
    text = (user_text or "").lower()
    occasion = _guess_occasion(text)
    budget = _guess_budget(text)
    contract = getattr(ctx, "intent", None)
    if contract:
        budget = contract.budget
    intent = normalize_intent(
        occasion=occasion, budget=budget, profile=ctx.profile,
        budget_scope=contract.budget_scope if contract else "products",
        needs_fit=ctx.store.category == "moda canina",
    )
    measurement = None
    if ctx.profile is not None:
        from .. import services_memory
        measurement = services_memory.authorized_measurement(ctx.store, ctx.session_key, ctx.profile)
    result = recommend(ctx.store, intent, measurement=measurement, kind="stylist")

    if not result["selection"]:
        return {
            "answer_text": ("No encontré coincidencias con esos filtros. "
                            "Podés quitar alguno o ver toda la colección."),
            "cards": [],
            "clarifying_question": None,
            "suggested_actions": [{"label": "Ver colección", "action": "collection"}],
            "warnings": [],
            "request_id": "",
        }

    cards, total = [], Decimal("0")
    for entry in result["selection"]:
        p = entry["product"]
        price = entry["price"]
        if budget is not None and intent["budget_scope"] == "total" and total + price > Decimal(str(budget)):
            continue
        total += price
        image = p.media.first()
        cards.append({
            "product_id": str(p.public_id), "slug": p.slug, "title": p.short_title,
            "price": f"${price:,.2f}",
            "image": image.path if image else "",
            "image_url": image.url if image else "",
            "alt": image.alt if image else p.short_title,
            "reason_codes": entry["reasons"],
            "fit_state": None, "fit_label": None,
        })
    return {
        "answer_text": "Mirá lo que encontré para esa necesidad:",
        "cards": cards,
        "clarifying_question": None,
        "suggested_actions": [],
        "warnings": [],
        "request_id": "",
    }


def _guess_budget(text):
    import re
    m = re.search(r"(?:hasta|máximo|maximo|menos de|under)\s*\$?\s*(\d+(?:[.,]\d+)?)", text)
    if not m:
        return None
    try:
        return m.group(1).replace(",", ".")
    except ValueError:
        return None
