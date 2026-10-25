"""Smart Fit: evaluación de talla por regla versionada de producto.

Estados (sección S05/A05): compatible | al_limite | incompatible | sin_datos.
- cm y pulgadas equivalentes producen el mismo resultado (A04).
- Medida desconocida nunca es compatible (A05); no se inventa confianza.
- La holgura pertenece a la regla del producto, no a una suma universal.
"""

from decimal import Decimal, InvalidOperation

from .models import FitRule

IN_TO_CM = Decimal("2.54")
TOLERANCE_EDGE = Decimal("1.0")  # cm desde el borde del rango => "al límite"

COMPATIBLE = "compatible"
EDGE = "al_limite"
INCOMPATIBLE = "incompatible"
UNKNOWN = "sin_datos"

STATE_LABELS = {
    COMPATIBLE: "Compatible según tus medidas",
    EDGE: "Revisar medidas",
    INCOMPATIBLE: "No compatible",
    UNKNOWN: "Datos insuficientes",
}


class InvalidMeasurement(Exception):
    pass


class SimpleMeasurement:
    """Medida temporal de esta visita (sin persistencia ni consentimiento).

    Sirve para «Calcular sin guardar» y para el borrador de LookLab: evalúa
    la talla sin escribir nada en la memoria del perfil (R09/R07).
    """

    def __init__(self, chest_cm=None, neck_cm=None, back_cm=None):
        self.chest_cm = chest_cm
        self.neck_cm = neck_cm
        self.back_cm = back_cm


def to_cm(value, unit):
    """Convierte un valor a cm; lanza InvalidMeasurement si no es un número válido."""
    if unit not in ("cm", "in"):
        raise InvalidMeasurement("Elegí centímetros o pulgadas.")
    try:
        v = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        raise InvalidMeasurement("Ingresá un número válido.") from None
    if not v.is_finite():
        raise InvalidMeasurement("Ingresá un número válido.")
    if unit == "in":
        v = v * IN_TO_CM
    if v <= 0 or v > Decimal("200") or v < Decimal("0.05"):
        raise InvalidMeasurement("La medida debe ser mayor que 0 y no superar 200 cm.")
    return v.quantize(Decimal("0.1"))


def active_rule(product):
    """Regla de talla vigente del producto, o None (=> incertidumbre honesta)."""
    return (
        FitRule.objects.filter(product=product, is_active=True)
        .order_by("-version")
        .first()
    )


def evaluate(product, chest_cm=None, neck_cm=None, back_cm=None):
    """Evalúa medidas contra la regla del producto.

    Devuelve dict con estado, candidatas, explicación y datos faltantes.
    """
    # API, formulario y herramienta comparten el mismo límite físico.
    chest_cm, neck_cm, back_cm = (
        to_cm(v, "cm") if v is not None else None
        for v in (chest_cm, neck_cm, back_cm)
    )
    rule = active_rule(product)
    if rule is None or not rule.ranges:
        return {
            "state": UNKNOWN,
            "label": STATE_LABELS[UNKNOWN],
            "candidates": [],
            "missing": ["rule"],
            "explanation": "Este producto todavía no tiene una guía de tallas publicada.",
            "rule_version": None,
            "measured_at": None,
        }

    missing = []
    if chest_cm is None:
        missing.append("chest")
    if rule.requires_neck and neck_cm is None:
        missing.append("neck")
    if back_cm is None:
        missing.append("back")
    if missing:
        return {
            "state": UNKNOWN,
            "label": STATE_LABELS[UNKNOWN],
            "candidates": [],
            "missing": missing,
            "explanation": "Faltan medidas para evaluar la talla de esta prenda.",
            "rule_version": rule.version,
            "measured_at": None,
        }

    matched, edge = [], []
    for row in rule.ranges:
        chest_ok = Decimal(str(row["chest_min"])) <= chest_cm <= Decimal(str(row["chest_max"]))
        neck_ok = True
        if rule.requires_neck and row.get("neck_min") is not None and neck_cm is not None:
            neck_ok = Decimal(str(row["neck_min"])) <= neck_cm <= Decimal(str(row["neck_max"]))
        back_ok = True
        if row.get("back_min") is not None and back_cm is not None:
            back_ok = Decimal(str(row["back_min"])) <= back_cm <= Decimal(str(row["back_max"]))
        if chest_ok and neck_ok and back_ok:
            near_edge = (
                chest_cm - Decimal(str(row["chest_min"])) < TOLERANCE_EDGE
                or Decimal(str(row["chest_max"])) - chest_cm < TOLERANCE_EDGE
            )
            (edge if near_edge else matched).append(row["label"])

    if matched:
        state, candidates = COMPATIBLE, matched
    elif edge:
        state, candidates = EDGE, edge
    else:
        state, candidates = INCOMPATIBLE, []

    if state == COMPATIBLE:
        explanation = (
            f"La medida de pecho registrada ({chest_cm} cm) está dentro del rango "
            f"de la talla {candidates[0]} de esta prenda (regla v{rule.version})."
        )
    elif state == EDGE:
        explanation = (
            f"Las medidas están al límite de la talla {candidates[0]}. "
            "Revisá la guía antes de elegir."
        )
    else:
        explanation = (
            "Las medidas registradas no entran en los rangos publicados de esta prenda."
        )

    return {
        "state": state,
        "label": STATE_LABELS[state],
        "candidates": candidates,
        "missing": [],
        "explanation": explanation,
        "rule_version": rule.version,
        "measured_at": None,
    }


def evaluate_for_profile(product, measurement):
    """Atajo: evalúa la medida más reciente de un perfil."""
    if measurement is None:
        return evaluate(product)
    return evaluate(
        product,
        chest_cm=measurement.chest_cm,
        neck_cm=measurement.neck_cm,
        back_cm=measurement.back_cm,
    )


def normalize_size_label(option_label):
    """Normaliza la etiqueta de una variante para comparación EXACTA (R08).

    «Talla S» → «S»; «s» → «S». Nunca se usan subcadenas parciales: una S
    agotada no puede presentarse como M «compatible».
    """
    label = (option_label or "").strip().upper()
    for prefix in ("TALLA ", "SIZE "):
        if label.startswith(prefix):
            label = label[len(prefix):]
    return label.strip()


def label_matches(candidate, option_label):
    """Coincidencia exacta entre candidata de la regla y variante."""
    return normalize_size_label(candidate) == normalize_size_label(option_label)
