"""Contrato de intención (§6.2): la conversación se convierte en un objeto
VALIDADO — la persona puede verlo y editarlo; una inferencia jamás se vuelve
requisito silencioso.

El contrato distingue presupuesto por producto vs total puesto en destino
(`budget_scope`); si el total incluye envío y falta ubicación, el sistema lo
declara: nunca excluye el envío para aparentar cumplimiento.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re

CONTRACT_VERSION = "intent-v1"
CURRENCIES = {"USD"}
BUDGET_SCOPES = {"products", "total"}


@dataclass
class IntentContract:
    query: str = ""
    category_ids: list = field(default_factory=list)
    store_scope: str = ""              # slug de tienda o "" (todo el mercado)
    budget: Decimal | None = None
    budget_scope: str = "products"     # products | total (puesto en destino)
    currency: str = "USD"
    must_have: list = field(default_factory=list)
    preferences: dict = field(default_factory=dict)
    excluded: list = field(default_factory=list)
    recipient_ref: str = ""            # public_id del perfil autorizado o ""
    destination_scope: str = ""        # zona/ciudad para cotizar total
    requested_date: str = ""
    consent_version: str = ""
    version: str = CONTRACT_VERSION


def _dec(value):
    try:
        d = Decimal(str(value))
        return d if d.is_finite() and 0 < d <= 100000 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def validate(payload: dict) -> tuple[IntentContract, list[str]]:
    """Valida un dict arbitrario y devuelve (contrato, errores accionables).

    Los campos desconocidos se ignoran; los conocidos inválidos se reportan.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return IntentContract(), ["la intención debe ser un objeto"]

    c = IntentContract()
    c.query = str(payload.get("query") or "")[:8000]
    ids = payload.get("category_ids") or []
    if isinstance(ids, list):
        c.category_ids = [str(i)[:60] for i in ids][:8]
    else:
        errors.append("category_ids debe ser una lista")
    c.store_scope = str(payload.get("store_scope") or "")[:60]

    c.budget = _dec(payload.get("budget"))
    if payload.get("budget") not in (None, "") and c.budget is None:
        errors.append("budget debe ser un monto positivo")
    scope = str(payload.get("budget_scope") or "products")
    if scope not in BUDGET_SCOPES:
        errors.append("budget_scope debe ser products o total")
    else:
        c.budget_scope = scope
    currency = str(payload.get("currency") or "USD").upper()
    if currency not in CURRENCIES:
        errors.append(f"moneda no soportada: {currency}")
    else:
        c.currency = currency

    for name in ("must_have", "excluded"):
        value = payload.get(name) or []
        if not isinstance(value, list):
            errors.append(f"{name} debe ser una lista")
        else:
            setattr(c, name, [str(x)[:60] for x in value][:8])
    if isinstance(payload.get("preferences"), dict):
        c.preferences = {str(k)[:40]: v for k, v in list(payload["preferences"].items())[:12]}
    c.recipient_ref = str(payload.get("recipient_ref") or "")[:40]
    c.destination_scope = str(payload.get("destination_scope") or "")[:80]
    c.requested_date = str(payload.get("requested_date") or "")[:20]
    c.consent_version = str(payload.get("consent_version") or "")[:20]

    # Coherencia: total puesto en destino SIN ubicación no es verificable.
    if c.budget is not None and c.budget_scope == "total" and not c.destination_scope:
        errors.append("para garantizar un total con envío necesito la ubicación "
                      "(destination_scope); sin ella lo marco como «envío por confirmar»")
    return c, errors


def intent_from_text(text, store_slug=""):
    """Convierte lenguaje natural en un contrato VALIDADO (§6.2).

    Reutiliza el parseo de búsqueda (presupuesto, categoría, cues) y lo pasa
    por `validate`: la conversación entera queda gobernada por el contrato —
    visible y editable por la persona, nunca una inferencia silenciosa.
    """
    from .. import services_search as search
    parsed = search.parse_query(text or "")
    normalized = search.normalize(text or "")
    payload = {"query": text, "store_scope": store_slug}
    if parsed.get("max_price") is not None:
        payload["budget"] = str(parsed["max_price"])
        payload["budget_scope"] = "products"
    # A bare amount is meaningful only with a budget cue; measurements and
    # product quantities must never become monetary constraints.
    amounts = re.findall(r"(?:menos de|hasta|maximo|max|presupuesto(?: de)?|no mas de)\s*\$?\s*(\d+(?:[.,]\d{1,2})?)", normalized)
    if amounts:
        payload["budget"] = str(min(Decimal(a.replace(",", ".")) for a in amounts))
    if re.search(r"en total|presupuesto total|conjunto|inclu\w* (?:el )?envio", normalized):
        payload["budget_scope"] = "total"
    if parsed.get("category"):
        payload["category_ids"] = [parsed["category"]]
    if parsed.get("must_have"):
        payload["must_have"] = parsed["must_have"]
    contract, errors = validate(payload)
    minimum = re.search(r"(?:minimo|al menos)\s*\$\s*(\d+(?:[.,]\d{1,2})?)", normalized)
    if minimum and contract.budget is not None and Decimal(minimum.group(1).replace(",", ".")) > contract.budget:
        errors.append("Los límites de presupuesto se contradicen; confirmá el máximo que querés gastar.")
    if len({Decimal(a.replace(",", ".")) for a in amounts}) > 1:
        errors.append("Mencionaste varios máximos; confirmá cuál es tu presupuesto.")
    return contract, errors
