"""Política inicial de ranking comercial (§6.4): MEDIBLE y versionada.

Primero elegibilidad (código), después ranking. Pesos iniciales — hipótesis
de producto, no resultado demostrado; se registran con la recomendación y se
comparan con evaluaciones antes de cambiarlos.

Componentes normalizados 0..1:
- ajuste a intención (0.35): coincidencia de ocasión/estilo/categoría pedida
- preferencias (0.25): estilos/materiales declarados por la persona
- adecuación del coste (0.20): cercanía al presupuesto SIN excederlo
- completitud de evidencia (0.10): atributos informados de la categoría
- condiciones de compra/entrega (0.10): stock visible y notas de envío

Si falta un componente se declara y se aplica una regla explícita; nunca se
inventa una «puntuación objetiva de calidad».
"""

from decimal import Decimal

RANKING_VERSION = "ranking-v1"
WEIGHTS_V1 = {"intent": Decimal("0.35"), "prefs": Decimal("0.25"),
              "cost": Decimal("0.20"), "evidence": Decimal("0.10"),
              "conditions": Decimal("0.10")}


def _score_intent(product, intent):
    """Coincidencia con lo pedido: ocasión/estilo/categoría (0..1)."""
    hits = total = 0
    occasions = set(intent.get("occasions") or ([intent["occasion"]] if intent.get("occasion") else []))
    styles = set(intent.get("styles") or ([intent["style"]] if intent.get("style") else []))
    category = (intent.get("category") or "").lower()
    if occasions:
        total += 1
        hits += 1 if occasions & set(product.occasions or []) else 0
    if styles:
        total += 1
        hits += 1 if styles & set(product.styles or []) else 0
    if category:
        total += 1
        hits += 1 if category in (product.category or "").lower() else 0
    return Decimal(hits) / Decimal(total) if total else Decimal("0.5")  # neutro declarado


def _score_prefs(product, prefs):
    if not prefs:
        return Decimal("0.5")  # sin preferencias declaradas: neutro
    hits = total = 0
    if prefs.get("styles"):
        total += 1
        hits += 1 if set(prefs["styles"]) & set(product.styles or []) else 0
    if prefs.get("materials"):
        total += 1
        hits += 1 if set(prefs["materials"]) & set(product.materials or []) else 0
    return Decimal(hits) / Decimal(total) if total else Decimal("0.5")


def _score_cost(price, budget):
    """Adecuación al presupuesto: 1.0 si está muy por debajo; jamás premia
    excederlo (los fuera de presupuesto ni llegan: los filtra elegibilidad)."""
    if not budget:
        return Decimal("0.5")  # sin presupuesto: neutro
    if price > budget:
        return Decimal("0")
    ratio = Decimal(price) / Decimal(budget)
    return Decimal("1") - (ratio * Decimal("0.5"))  # 0.5..1.0


def _score_evidence(product, informed_ratio=None):
    """Completitud de evidencia informada (0..1). Sin medición: neutro 0.5
    declarado (no castiga ni inventa)."""
    if informed_ratio is None:
        return Decimal("0.5")
    return Decimal(str(informed_ratio)).quantize(Decimal("0.01"))


def _score_conditions(variant):
    """Condiciones de compra: stock visible; nota de envío presente suma
    claridad. Determinista y verificable."""
    score = Decimal("0.5")
    if variant is not None and variant.stock > 0:
        score += Decimal("0.3")
    if variant is not None and variant.product.shipping_note:
        score += Decimal("0.2")
    return min(score, Decimal("1"))


def score_candidates(candidates, intent=None, weights=None):
    """Ordena candidatos ELEGIBLES con desglose trazable por componente.

    `candidates`: iterable de dicts con keys product, variant, price y
    opcionalmente evidence_ratio. Devuelve la lista ordenada desc con
    `score` y `score_parts` por candidato.
    """
    intent = intent or {}
    w = weights or WEIGHTS_V1
    scored = []
    for cand in candidates:
        product, variant = cand["product"], cand.get("variant")
        price = cand.get("price") or product.base_price
        parts = {
            "intent": _score_intent(product, intent),
            "prefs": _score_prefs(product, intent.get("preferences") or {}),
            "cost": _score_cost(Decimal(price), intent.get("budget")),
            "evidence": _score_evidence(product, cand.get("evidence_ratio")),
            "conditions": _score_conditions(variant),
        }
        total = sum(parts[k] * w[k] for k in parts).quantize(Decimal("0.001"))
        scored.append({**cand, "score": total, "score_parts":
                       {k: str(v) for k, v in parts.items()},
                       "ranking_version": RANKING_VERSION})
    scored.sort(key=lambda c: (-c["score"], str(c["product"].short_title)))
    return scored


def premium_uplift(base, premium):
    """«Qué ganás» con la opción premium (§6.4): mejora CONCRETA y verificable
    (material, capacidad, garantía documentada) + diferencia de precio.

    Devuelve dict con improvement/delta o None si no hay mejora sustentable:
    nunca se recomienda lo más caro por defecto.
    """
    improvements = []
    base_mats = set(base["product"].materials or [])
    prem_mats = set(premium["product"].materials or [])
    new_mats = prem_mats - base_mats
    if new_mats:
        improvements.append("materiales: " + ", ".join(sorted(new_mats)))
    if premium["product"].reason and premium["product"].reason != base["product"].reason:
        improvements.append(premium["product"].reason)
    if not improvements:
        return None
    delta = Decimal(premium["price"]) - Decimal(base["price"])
    return {"improvement": "; ".join(improvements)[:200], "price_delta": delta}
