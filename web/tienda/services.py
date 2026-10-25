"""Smart Quote: cotización calculada siempre en el servidor.

El cliente solo indica qué perro y qué producto; el precio se toma del
catálogo controlado (`tienda.catalog.PRODUCTOS`) y nunca de datos del navegador.

La regla de ajuste por talla/peso/materiales NO está definida por el negocio,
así que toda cotización es PROVISIONAL (precio base, sin ajuste).
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .models import Quote
from .catalog import PRODUCTOS


# Precio final máximo por producto indicado en la guía. Es solo un tope
# técnico: no existe aún una fórmula de ajuste por talla.
UNIT_PRICE_CAP = Decimal("850.00")


class UnknownProduct(Exception):
    pass


class InvalidCatalogPrice(Exception):
    pass


def get_product(slug):
    try:
        return PRODUCTOS[slug]
    except KeyError:
        raise UnknownProduct(slug) from None


def get_base_price(slug):
    """Precio base como Decimal, a partir del catálogo (p. ej. "$650")."""
    raw = get_product(slug)["precio"]
    try:
        price = Decimal(str(raw).strip().lstrip("$").replace(",", ""))
    except InvalidOperation:
        raise InvalidCatalogPrice(raw) from None
    if price <= 0 or price > UNIT_PRICE_CAP:
        raise InvalidCatalogPrice(raw)
    return price.quantize(Decimal("0.01"))


MAX_QUANTITY = 10  # supuesto técnico, pendiente de aprobación del negocio

PAYMENT_METHODS = ("unspecified", "bitcoin", "paypal_demo", "card_demo")
DEMO_METHODS = ("paypal_demo", "card_demo")  # sin pasarela: nunca pagan
SETTABLE_METHODS = ("unspecified", "bitcoin")  # el personal solo asigna métodos reales


def discount_eligible(slug):
    """Si el producto admite el descuento Bitcoin (por defecto sí)."""
    from .models import ProductPaymentRule

    rule = ProductPaymentRule.objects.filter(product_slug=slug).first()
    return True if rule is None else rule.bitcoin_discount_eligible


class QuantityError(Exception):
    pass


def normalize_quantity(raw):
    """Cantidad entera entre 1 y MAX_QUANTITY; lanza QuantityError si no."""
    try:
        qty = int(str(raw).strip())
    except (TypeError, ValueError):
        raise QuantityError("Enter a whole number of units.") from None
    if qty < 1 or qty > MAX_QUANTITY:
        raise QuantityError(f"Quantity must be between 1 and {MAX_QUANTITY}.")
    return qty


def create_quote(dog, slug, quantity=1, size_label=""):
    """Crea (o reutiliza) la cotización provisional borrador de un perro/producto.

    Solo se reutilizan borradores que no estén ya en un carrito.
    """
    base_price = get_base_price(slug)
    quantity = normalize_quantity(quantity)
    size_label = (size_label or "").strip()
    existing = (
        Quote.objects.filter(
            dog=dog,
            product_slug=slug,
            status=Quote.Status.DRAFT,
            pricing=Quote.Pricing.PROVISIONAL,
            cart__isnull=True,
        )
        .order_by("-pk")
        .first()
    )
    if existing:
        # Si el catálogo cambió, el precio del borrador se refresca.
        changed = []
        if existing.base_price != base_price:
            existing.base_price = base_price
            changed.append("base_price")
        if existing.quantity != quantity:
            existing.quantity = quantity
            changed.append("quantity")
        if existing.size_label != size_label:
            existing.size_label = size_label
            changed.append("size_label")
        if changed:
            existing.save(update_fields=changed)
        return existing
    return Quote.objects.create(
        dog=dog, product_slug=slug, base_price=base_price, quantity=quantity,
        size_label=size_label,
    )


def set_quote_quantity(quote, quantity):
    """Corrige la cantidad de una cotización borrador (solo sin pedido)."""
    quantity = normalize_quantity(quantity)
    if quote.status != Quote.Status.DRAFT or hasattr(quote, "order"):
        raise QuantityError("This quote can no longer be changed.")
    quote.quantity = quantity
    quote.save(update_fields=["quantity"])
    return quote


def compute_totals(quote, payment_method="unspecified"):
    """Importes de una cotización, siempre calculados en el servidor.

    - Precio unitario: catálogo (o total_price si una regla futura lo fija).
    - Subtotal de productos = unitario × cantidad.
    - Descuento Bitcoin: 15 % del subtotal de productos; el envío no entra.
    - Envío: sin tarifa definida, se muestra como pendiente.
    """
    unit_base = get_base_price(quote.product_slug)
    is_final = quote.pricing == Quote.Pricing.FINAL and quote.total_price is not None
    unit = quote.total_price if is_final else unit_base
    subtotal = _money(unit * quote.quantity)
    eligible = discount_eligible(quote.product_slug)
    rate, discount = compute_discount(subtotal, payment_method, eligible)
    return {
        "discount_eligible": eligible,
        "payment_method": payment_method,
        "unit_base_price": unit_base,
        "unit_price": unit,
        "quantity": quote.quantity,
        "subtotal": subtotal,
        "is_final": is_final,
        "discount_rate": rate,
        "discount_amount": discount,
        "shipping": None,  # por confirmar
        "amount_due": subtotal,  # el descuento aplica al verificar el pago
        "total_if_discount": _money(subtotal - discount),
    }


def build_breakdown(quote, payment_method="unspecified"):
    """Desglose legible; provisional mientras no haya regla de ajuste por talla."""
    t = compute_totals(quote, payment_method)
    name = get_product(quote.product_slug)["nombre"]
    lines = [
        {"label": f"{name} — unit base price", "amount": t["unit_price"], "note": ""},
        {"label": "Quantity", "amount": None, "note": str(t["quantity"]), "plain": True},
        {
            "label": "Size adjustment",
            "amount": None,
            "note": "Not calculated yet. The sizing rule is pending business approval.",
        },
        {"label": "Products subtotal", "amount": t["subtotal"], "note": ""},
    ]
    if t["discount_rate"]:
        lines.append(
            {
                "label": "Bitcoin discount (15%)",
                "amount": -t["discount_amount"],
                "note": "Applied once your payment is verified.",
            }
        )
    lines.append(
        {"label": "Shipping", "amount": None, "note": "To be confirmed."}
    )
    return {
        "lines": lines,
        "total": t["subtotal"],
        "is_final": t["is_final"],
        "totals": t,
    }


# --- Estados del pedido (panel) ---------------------------------------------
# Supuestos técnicos pendientes de aprobación del negocio: transiciones
# secuenciales, sin retrocesos, y no enviar antes de terminar la producción.

TARGET_MANUFACTURING_COST = Decimal("175.00")  # objetivo, NO costo comprobado
CENT = Decimal("0.01")
BITCOIN_DISCOUNT_RATE = Decimal("0.15")  # sobre el subtotal de productos, sin envío

TRANSITIONS = {
    "status": {"pending": ["confirmed", "cancelled"], "confirmed": ["cancelled"]},
    "payment_status": {"unpaid": ["paid"]},
    "production_status": {
        "not_started": ["in_production"],
        "in_production": ["completed"],
    },
    "shipping_status": {"not_shipped": ["shipped"], "shipped": ["delivered"]},
}


class TransitionError(Exception):
    pass


def _check_rules(order, field, new_value):
    """Devuelve un mensaje de error o None si la transición es válida."""
    if order.status == "cancelled" and field != "status":
        return "Cancelled orders cannot change state."
    if field == "payment_status" and new_value == "paid":
        if order.payment_method in DEMO_METHODS:
            return (
                "Demo payment methods cannot be recorded as paid. "
                "Change the order to a verified payment method first."
            )
    if field == "production_status" and new_value == "in_production":
        if order.payment_status != "paid":
            return "Payment must be verified before production can start."
        readiness = order_readiness(order)
        if not readiness["ready"]:
            return "Cannot start production: " + "; ".join(readiness["blockers"]) + "."
    if field == "shipping_status" and new_value == "shipped":
        if order.production_status != "completed":
            return "Production must be completed before shipping."
    if field == "status" and new_value == "cancelled":
        if order.shipping_status != "not_shipped":
            return "A shipped order cannot be cancelled."
    return None


def allowed_transitions(order):
    result = {}
    for field, table in TRANSITIONS.items():
        current = getattr(order, field)
        result[field] = [
            t for t in table.get(current, []) if _check_rules(order, field, t) is None
        ]
    return result


def apply_transition(order, field, new_value, user=None, note=""):
    from django.db import transaction

    from .models import Order, OrderEvent

    if field not in TRANSITIONS:
        raise TransitionError("Unknown state field.")
    note = (note or "").strip()
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        current = getattr(order, field)
        if new_value not in TRANSITIONS[field].get(current, []):
            raise TransitionError(f"Cannot change {field} from {current} to {new_value}.")
        error = _check_rules(order, field, new_value)
        if error:
            raise TransitionError(error)
        if field == "payment_status":
            # Pago manual: exige referencia como evidencia; no se simula ningún proveedor.
            if not note:
                raise TransitionError(
                    "A payment reference is required to mark an order as paid."
                )
            order.payment_reference = note[:120]
        setattr(order, field, new_value)
        if field == "production_status":
            # La producción de todo el pedido se refleja en cada línea.
            order.lines.update(production_status=new_value)
        discount_event = None
        if (
            field == "payment_status"
            and new_value == "paid"
            and order.discount_status == "pending_verification"
        ):
            # El pago (con su referencia) quedó verificado por el personal.
            order.discount_status = "applied"
            discount_event = ("pending_verification", "applied")
        order.save()
        if discount_event:
            OrderEvent.objects.create(
                order=order,
                field="discount_status",
                from_value=discount_event[0],
                to_value=discount_event[1],
                note=note[:200],
                by=user if getattr(user, "pk", None) else None,
            )
        OrderEvent.objects.create(
            order=order,
            field=field,
            from_value=current,
            to_value=new_value,
            note=note[:200],
            by=user if getattr(user, "pk", None) else None,
        )
    return order


def _estimated_cost_from_lines(order):
    """Costo estimado = suma del presupuesto de cada línea × su cantidad.

    Usa la copia del presupuesto guardada al confirmar; si falta, el
    presupuesto vigente; y como último recurso el objetivo provisional.
    """
    lines = list(order.lines.all())
    if not lines:
        snap = order.snapshot or {}
        frozen = snap.get("cost_estimate")
        live = None if frozen else product_cost_summary((snap.get("product") or {}).get("slug", ""))
        if frozen:
            return Decimal(frozen["total_cost"]) * order.quantity, "product_estimate"
        if live:
            return live["total_cost"] * order.quantity, "product_estimate"
        return TARGET_MANUFACTURING_COST, "target"
    total, known = Decimal("0"), 0
    for line in lines:
        unit = None
        if line.cost_estimate:
            unit = Decimal(line.cost_estimate["total_cost"])
        else:
            live = product_cost_summary(line.product_slug)
            if live:
                unit = live["total_cost"]
        if unit is None:
            unit = TARGET_MANUFACTURING_COST
        else:
            known += 1
        total += unit * line.quantity
    return total, ("product_estimate" if known else "target")


def cost_summary(order):
    """Costo y margen internos, indicando de dónde sale cada valor.

    Prioridad: costo real > costo estimado cargado > objetivo provisional.
    Los ingresos son el importe a pagar (el descuento Bitcoin solo cuenta
    cuando está aplicado).
    """
    if order.actual_cost is not None:
        cost, source = order.actual_cost, "actual"
    elif order.estimated_cost is not None:
        cost, source = order.estimated_cost, "estimated"
    else:
        cost, source = _estimated_cost_from_lines(order)
    revenue = order.amount_due
    margin = revenue - cost
    pct = (margin / revenue * 100).quantize(Decimal("0.1")) if revenue else None
    return {
        "total": order.total,
        "revenue": revenue,
        "discount_pending": order.discount_status == "pending_verification",
        "discount_amount": order.discount_amount,
        "total_is_provisional": order.price_is_provisional,
        "cost": cost,
        "cost_source": source,
        "is_actual": source == "actual",
        "margin": margin,
        "margin_pct": pct,
        "margin_negative": margin < 0,
        "target_cost": TARGET_MANUFACTURING_COST,
    }



class CostError(Exception):
    def __init__(self, messages):
        super().__init__("; ".join(messages))
        self.messages = messages


def _money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def product_cost_summary(slug):
    """Presupuesto interno de un producto: partidas, totales y margen bruto.

    El total de materiales se deriva de las partidas (consumo × precio
    unitario); nunca se guarda como constante. Devuelve None si no hay perfil.
    """
    from .models import ProductCost

    profile = ProductCost.objects.filter(product_slug=slug).first()
    if profile is None:
        return None
    lines = []
    for line in profile.lines.all():
        lines.append(
            {
                "id": line.pk,
                "name": line.name,
                "unit": line.unit,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "subtotal": line.subtotal,
                "is_reserve": line.is_provisional_reserve,
                "is_validated": line.is_validated,
            }
        )
    materials = _money(sum((l["subtotal"] for l in lines), Decimal("0")))
    total_cost = _money(materials + profile.labor_cost + profile.other_costs)
    try:
        sale_price = get_base_price(slug)
    except (UnknownProduct, InvalidCatalogPrice):
        sale_price = None
    margin = None if sale_price is None else _money(sale_price - total_cost)
    pct = None
    if margin is not None and sale_price:
        pct = (margin / sale_price * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    all_validated = profile.is_validated and all(l["is_validated"] for l in lines)
    return {
        "slug": slug,
        "name": PRODUCTOS.get(slug, {}).get("nombre", slug),
        "lines": lines,
        "materials_total": materials,
        "labor_cost": profile.labor_cost,
        "other_costs": profile.other_costs,
        "total_cost": total_cost,
        "sale_price": sale_price,
        "margin": margin,
        "margin_pct": pct,
        "margin_negative": margin is not None and margin < 0,
        "has_reserve": any(l["is_reserve"] for l in lines),
        # Sin mano de obra ni otros costos cargados, el margen está sobreestimado.
        "incomplete": profile.labor_cost == 0 and profile.other_costs == 0,
        "is_validated": all_validated,
        "notes": profile.notes,
        "updated_at": profile.updated_at,
    }


def all_product_costs():
    return [s for s in (product_cost_summary(slug) for slug in PRODUCTOS) if s]


def _dec_field(raw, label, errors, minimum=Decimal("0"), required=True):
    raw = (raw or "").strip()
    if raw == "":
        if required:
            errors.append(f"{label}: a value is required.")
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        errors.append(f"{label}: enter a valid number.")
        return None
    if not value.is_finite() or value < minimum:
        errors.append(f"{label}: must be {minimum} or more.")
        return None
    return value


def update_product_cost(slug, data, user=None):
    """Aplica ediciones del formulario interno (todo o nada).

    `data` es un dict tipo POST. Campos: labor_cost, other_costs, notes,
    is_validated, qty_<id>, price_<id>, validated_<id>, delete_<id> y una
    partida nueva (new_name, new_unit, new_qty, new_price).
    """
    from django.db import transaction

    from .models import MaterialLine, ProductCost

    errors = []
    with transaction.atomic():
        profile = ProductCost.objects.select_for_update().filter(product_slug=slug).first()
        if profile is None:
            raise CostError(["Unknown product cost profile."])
        labor = _dec_field(data.get("labor_cost"), "Labor cost", errors)
        other = _dec_field(data.get("other_costs"), "Other production costs", errors)
        edits = []
        for line in profile.lines.all():
            if data.get(f"delete_{line.pk}"):
                edits.append((line, None, None, None, True))
                continue
            qty = _dec_field(data.get(f"qty_{line.pk}"), f"{line.name} — consumption", errors)
            price = _dec_field(data.get(f"price_{line.pk}"), f"{line.name} — unit price", errors)
            edits.append((line, qty, price, bool(data.get(f"validated_{line.pk}")), False))

        new_line = None
        new_name = (data.get("new_name") or "").strip()
        if new_name or (data.get("new_qty") or "").strip() or (data.get("new_price") or "").strip():
            qty = _dec_field(data.get("new_qty"), "New line — consumption", errors)
            price = _dec_field(data.get("new_price"), "New line — unit price", errors)
            if not new_name:
                errors.append("New line: a name is required.")
            unit = (data.get("new_unit") or "").strip()[:20] or "unidad"
            new_line = (new_name[:120], unit, qty, price)

        if errors:
            raise CostError(errors)

        profile.labor_cost = labor
        profile.other_costs = other
        profile.is_validated = bool(data.get("is_validated"))
        profile.notes = (data.get("notes") or "").strip()[:300]
        profile.updated_by = user if getattr(user, "pk", None) else None
        profile.save()
        for line, qty, price, validated, delete in edits:
            if delete:
                line.delete()
                continue
            line.quantity = qty
            line.unit_price = price
            line.is_validated = validated
            line.save()
        if new_line:
            last = profile.lines.order_by("-position").first()
            MaterialLine.objects.create(
                product_cost=profile,
                position=(last.position + 1) if last else 1,
                name=new_line[0],
                unit=new_line[1],
                quantity=new_line[2],
                unit_price=new_line[3],
            )
    return product_cost_summary(slug)


def _sum_parts(*parts):
    present = [p for p in parts if p is not None]
    return sum(present, Decimal("0")) if present else None


def update_costs(
    order,
    user=None,
    estimated_materials=None,
    estimated_labor=None,
    actual_materials=None,
    actual_labor=None,
    notes="",
):
    """Guarda costos internos (materiales y mano de obra) y registra el cambio."""
    from django.db import transaction

    from .models import Order, OrderEvent

    values = (estimated_materials, estimated_labor, actual_materials, actual_labor)
    if any(v is not None and v < 0 for v in values):
        raise TransitionError("Costs cannot be negative.")
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        new = {
            "estimated_materials": estimated_materials,
            "estimated_labor": estimated_labor,
            "actual_materials": actual_materials,
            "actual_labor": actual_labor,
            "estimated_cost": _sum_parts(estimated_materials, estimated_labor),
            "actual_cost": _sum_parts(actual_materials, actual_labor),
        }
        for field, value in new.items():
            old = getattr(order, field)
            if old != value:
                setattr(order, field, value)
                OrderEvent.objects.create(
                    order=order,
                    field=field,
                    from_value="" if old is None else str(old),
                    to_value="" if value is None else str(value),
                    note="",
                    by=user if getattr(user, "pk", None) else None,
                )
        order.cost_notes = (notes or "").strip()[:300]
        order.save()
    return order


class QuoteNotOrderable(Exception):
    pass


def _dec(value):
    return None if value is None else str(value)


def compute_discount(subtotal, payment_method, eligible=True):
    """(tasa, importe) del descuento; solo Bitcoin tiene descuento aprobado."""
    if payment_method == "bitcoin" and eligible:
        amount = (subtotal * BITCOIN_DISCOUNT_RATE).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return BITCOIN_DISCOUNT_RATE, amount
    return Decimal("0"), Decimal("0.00")


class CartError(Exception):
    def __init__(self, messages):
        if isinstance(messages, str):
            messages = [messages]
        super().__init__("; ".join(messages))
        self.messages = list(messages)


def size_options():
    """Tallas que el cliente puede elegir (tabla de referencia, no validada)."""
    from .models import SizeRange

    seen, out = set(), []
    for row in SizeRange.objects.all():
        if row.display not in seen:
            seen.add(row.display)
            out.append(row.display)
    return out


def _dog_snapshot(dog):
    return {
        "name": dog.name,
        "breed": dog.breed,
        "weight_kg": _dec(dog.weight_kg),
        "back_length_cm": _dec(dog.back_length_cm),
        "chest_girth_cm": _dec(dog.chest_girth_cm),
        "neck_girth_cm": _dec(dog.neck_girth_cm),
    }


def _cost_snapshot(cost):
    if cost is None:
        return None
    return {
        "status": "estimate_not_verified",
        "materials_total": _dec(cost["materials_total"]),
        "labor_cost": _dec(cost["labor_cost"]),
        "other_costs": _dec(cost["other_costs"]),
        "total_cost": _dec(cost["total_cost"]),
        "lines": [
            {
                "name": l["name"],
                "unit": l["unit"],
                "quantity": _dec(l["quantity"]),
                "unit_price": _dec(l["unit_price"]),
                "subtotal": _dec(l["subtotal"]),
            }
            for l in cost["lines"]
        ],
    }


def _line_payload(quote, totals, position):
    """Datos de una línea de pedido: copia histórica de la cotización aceptada."""
    size = classify_size(quote.dog)
    product = get_product(quote.product_slug)
    return {
        "quote": quote,
        "position": position,
        "product_slug": quote.product_slug,
        "product_name": product["nombre"],
        "quantity": quote.quantity,
        "unit_price": totals["unit_price"],
        "subtotal": totals["subtotal"],
        "price_is_provisional": not totals["is_final"],
        "discount_eligible": totals["discount_eligible"],
        "discount_amount": totals["discount_amount"],
        "size_selected": quote.size_label,
        "dog_snapshot": _dog_snapshot(quote.dog),
        "size_reference": {
            "status": size["status"],
            "candidates": [c["text"] for c in size["candidates"]],
            "validated": size["validated"],
            "note": "Reference only; size table not validated with tailoring.",
        },
        "required_measurements": measurement_requirements(quote.product_slug),
        "cost_estimate": _cost_snapshot(product_cost_summary(quote.product_slug)),
    }


def _order_snapshot(payloads, totals_list, quotes, payment_method, rate, discount_total, subtotal):
    """Snapshot del pedido. Los campos de primer nivel reflejan la primera
    línea (compatibilidad); la fuente de verdad por producto es `lines`."""
    first = payloads[0]
    lines = []
    for p, t, q in zip(payloads, totals_list, quotes):
        lines.append(
            {
                "product": {"slug": p["product_slug"], "name": p["product_name"]},
                "quantity": p["quantity"],
                "unit_price": _dec(p["unit_price"]),
                "subtotal": _dec(p["subtotal"]),
                "base_price": _dec(t["unit_base_price"]),
                "pricing": "provisional" if p["price_is_provisional"] else "final",
                "size_selected": p["size_selected"],
                "dog": p["dog_snapshot"],
                "size_reference": p["size_reference"],
                "required_measurements": p["required_measurements"],
                "cost_estimate": p["cost_estimate"],
                "discount_eligible": p["discount_eligible"],
                "discount_amount": _dec(p["discount_amount"]),
                "quote_public_id": str(q.public_id),
            }
        )
    return {
        "currency": "USD",
        "product": {"slug": first["product_slug"], "name": first["product_name"]},
        "base_price": _dec(totals_list[0]["unit_base_price"]),
        "total": _dec(subtotal),
        "pricing": "provisional" if any(p["price_is_provisional"] for p in payloads) else "final",
        "quantity": first["quantity"],
        "unit_price": _dec(first["unit_price"]),
        "subtotal": _dec(subtotal),
        "shipping": {"status": "pending", "amount": None},
        "dog": first["dog_snapshot"],
        "quote_public_id": str(quotes[0].public_id),
        "size_reference": first["size_reference"],
        "required_measurements": first["required_measurements"],
        "cost_estimate": first["cost_estimate"],
        "payment_method": payment_method,
        "discount": {
            "rate": _dec(rate),
            "amount": _dec(discount_total),
            "status": "pending_verification" if discount_total > 0 else "none",
        },
        "lines": lines,
    }


def _create_order(quotes, customer, cart=None):
    """Crea un pedido con una línea por cotización; idempotente.

    Todos los importes se recalculan aquí desde el catálogo; nada del
    navegador influye. Devuelve (pedido, creado).
    """
    from django.db import IntegrityError, transaction

    from .models import Cart, Order, OrderLine

    customer = dict(customer)
    payment_method = customer.pop("payment_method", "unspecified")
    if payment_method not in PAYMENT_METHODS:
        payment_method = "unspecified"

    with transaction.atomic():
        ids = [q.pk for q in quotes]
        locked = list(
            Quote.objects.select_for_update(of=("self",)).select_related("dog").filter(pk__in=ids).order_by("pk")
        )
        if len(locked) != len(ids) or not locked:
            raise QuoteNotOrderable("missing")
        if cart is not None:
            cart = Cart.objects.select_for_update().get(pk=cart.pk)
            existing = Order.objects.filter(cart=cart).first()
        else:
            existing = Order.objects.filter(quote=locked[0]).first()
        if existing:
            return existing, False

        for q in locked:
            if q.status == Quote.Status.CANCELLED:
                raise QuoteNotOrderable("cancelled")
            if q.status == Quote.Status.ACCEPTED:
                raise QuoteNotOrderable("already ordered")
            if q.product_slug not in PRODUCTOS:
                raise QuoteNotOrderable("unavailable")
            missing = missing_measurements(q.dog, q.product_slug)
            if q.dog is None or missing:
                raise QuoteNotOrderable("missing measurements")

        totals_list = [compute_totals(q, payment_method) for q in locked]
        payloads = [_line_payload(q, t, i) for i, (q, t) in enumerate(zip(locked, totals_list), 1)]
        subtotal = sum((t["subtotal"] for t in totals_list), Decimal("0"))
        discount_total = sum((t["discount_amount"] for t in totals_list), Decimal("0"))
        rate = max((t["discount_rate"] for t in totals_list), default=Decimal("0"))
        if discount_total <= 0:
            rate = Decimal("0")
        snapshot = _order_snapshot(
            payloads, totals_list, locked, payment_method, rate, discount_total, subtotal
        )
        try:
            with transaction.atomic():
                order = Order.objects.create(
                    quote=locked[0] if len(locked) == 1 else None,
                    cart=cart,
                    total=subtotal,
                    quantity=sum(q.quantity for q in locked),
                    price_is_provisional=any(p["price_is_provisional"] for p in payloads),
                    snapshot=snapshot,
                    payment_method=payment_method,
                    discount_rate=rate,
                    discount_amount=discount_total,
                    discount_status="pending_verification" if discount_total > 0 else "none",
                    size_confirmed="",
                    **customer,
                )
        except IntegrityError:
            if cart is not None:
                return Order.objects.get(cart=cart), False
            return Order.objects.get(quote=locked[0]), False
        for payload in payloads:
            OrderLine.objects.create(order=order, **payload)
        for q, t in zip(locked, totals_list):
            q.base_price = t["unit_base_price"]
            q.status = Quote.Status.ACCEPTED
            q.save(update_fields=["base_price", "status"])
        if cart is not None:
            cart.status = Cart.Status.ORDERED
            cart.save(update_fields=["status"])
        return order, True


def create_order(quote, customer):
    """Pedido de una sola cotización (flujo directo)."""
    return _create_order([quote], customer)


def create_order_from_cart(cart, customer):
    """Un solo checkout para todas las líneas del carrito."""
    from .models import Order

    existing = Order.objects.filter(cart=cart).first()
    if existing:
        return existing, False
    quotes = list(cart.quotes.filter(status=Quote.Status.DRAFT).order_by("pk"))
    if not quotes:
        raise CartError("Your cart is empty.")
    return _create_order(quotes, customer, cart=cart)


# --- Carrito ------------------------------------------------------------------

def get_open_cart(public_id):
    from .models import Cart

    if not public_id:
        return None
    try:
        return Cart.objects.filter(public_id=public_id, status=Cart.Status.OPEN).first()
    except (ValueError, TypeError):
        return None


def add_to_cart(cart, dog, slug, quantity=1, size_label=""):
    """Añade (o suma a) una línea del carrito. El precio sale del catálogo."""
    get_base_price(slug)  # lanza UnknownProduct / InvalidCatalogPrice
    quantity = normalize_quantity(quantity)
    size_label = (size_label or "").strip()
    if size_label and size_label not in size_options():
        raise CartError("Choose a size from the list.")
    # Sin perfil la linea queda con medidas pendientes; se completa desde el carrito.
    existing = cart.quotes.filter(
        dog=dog, product_slug=slug, size_label=size_label, status=Quote.Status.DRAFT
    ).first()
    if existing:
        existing.quantity = normalize_quantity(existing.quantity + quantity)
        existing.base_price = get_base_price(slug)
        existing.save(update_fields=["quantity", "base_price"])
        return existing
    return Quote.objects.create(
        dog=dog, product_slug=slug, base_price=get_base_price(slug),
        quantity=quantity, cart=cart, size_label=size_label,
    )


def cart_lines(cart):
    return list(cart.quotes.filter(status=Quote.Status.DRAFT).select_related("dog").order_by("pk"))


def cart_summary(cart, payment_method="unspecified"):
    """Líneas y totales del carrito, calculados en el servidor."""
    lines, subtotal, discount, units = [], Decimal("0"), Decimal("0"), 0
    provisional = False
    for quote in cart_lines(cart):
        if quote.product_slug not in PRODUCTOS:
            continue
        t = compute_totals(quote, payment_method)
        product = get_product(quote.product_slug)
        size = classify_size(quote.dog) if quote.dog else None
        lines.append(
            {
                "quote": quote,
                "product": product,
                "totals": t,
                "size": size,
                "missing": missing_measurements(quote.dog, quote.product_slug),
            }
        )
        subtotal += t["subtotal"]
        discount += t["discount_amount"]
        units += quote.quantity
        provisional = provisional or not t["is_final"]
    return {
        "lines": lines,
        "units": units,
        "subtotal": _money(subtotal),
        "discount_amount": _money(discount),
        "total_if_discount": _money(subtotal - discount),
        "is_provisional": provisional,
        "shipping": None,
        "has_missing": any(l["missing"] for l in lines),
    }


# --- Medidas y talla de referencia (Smart Fit) --------------------------------

def measurement_requirements(slug):
    """Medidas extra que exige la prenda (configurable en el panel)."""
    from .models import ProductMeasurement

    pm = ProductMeasurement.objects.filter(product_slug=slug).first()
    return {
        "neck_girth": bool(pm and pm.requires_neck),
        "validated": bool(pm and pm.is_validated),
    }


def missing_measurements(dog, slug):
    """Campos que la prenda exige y el perfil aún no tiene."""
    if dog is None:
        return ["measurements"]
    missing = []
    if measurement_requirements(slug)["neck_girth"] and dog.neck_girth_cm is None:
        missing.append("neck_girth")
    return missing


def classify_size(dog):
    """Talla de referencia a partir de las MEDIDAS (nunca por raza).

    Resultado informativo y no validado: no cambia precios ni cotizaciones.
    Estados: matched (una fila), ambiguous (varias) u outside (ninguna).
    """
    from .models import SizeRange

    def inside(value, low, high):
        return low <= value <= high

    candidates = []
    for row in SizeRange.objects.all():
        if not inside(dog.chest_girth_cm, row.chest_min, row.chest_max):
            continue
        if not inside(dog.back_length_cm, row.back_min, row.back_max):
            continue
        if dog.neck_girth_cm is not None and not inside(
            dog.neck_girth_cm, row.neck_min, row.neck_max
        ):
            continue
        candidates.append(row)
    status = "matched" if len(candidates) == 1 else "ambiguous" if candidates else "outside"
    return {
        "status": status,
        "candidates": [
            {"label": r.label, "group": r.group, "text": r.display} for r in candidates
        ],
        "validated": bool(candidates) and all(r.is_validated for r in candidates),
        "used_neck": dog.neck_girth_cm is not None,
    }


def update_measurement_config(post, user=None):
    """Guarda requisitos por prenda y tabla de tallas (todo o nada)."""
    from django.db import transaction

    from .models import ProductMeasurement, SizeRange

    errors = []
    rows = list(SizeRange.objects.all())
    parsed = {}
    for row in rows:
        values = {}
        for field in ("neck_min", "neck_max", "chest_min", "chest_max", "back_min", "back_max"):
            raw = (post.get(f"{field}_{row.pk}") or "").strip()
            try:
                v = Decimal(raw)
            except InvalidOperation:
                errors.append(f"{row.display} — {field}: enter a number.")
                continue
            if not v.is_finite() or v <= 0 or v > Decimal("300"):
                errors.append(f"{row.display} — {field}: must be between 0 and 300.")
                continue
            values[field] = v
        for lo, hi in (("neck_min", "neck_max"), ("chest_min", "chest_max"), ("back_min", "back_max")):
            if lo in values and hi in values and values[lo] > values[hi]:
                errors.append(f"{row.display}: {lo} is greater than {hi}.")
        parsed[row.pk] = values
    if errors:
        raise CostError(errors)
    with transaction.atomic():
        for row in rows:
            for field, value in parsed[row.pk].items():
                setattr(row, field, value)
            row.is_validated = bool(post.get(f"svalid_{row.pk}"))
            row.save()
        for slug in PRODUCTOS:
            pm, _ = ProductMeasurement.objects.get_or_create(product_slug=slug)
            pm.requires_neck = bool(post.get(f"neck_{slug}"))
            pm.is_validated = bool(post.get(f"valid_{slug}"))
            pm.save()


# --- Métodos de pago (panel) ---------------------------------------------------

def set_payment_method(order, method, user=None):
    """Cambia el método de pago de un pedido SIN pagar y recalcula el descuento
    de cada línea."""
    from django.db import transaction

    from .models import Order, OrderEvent

    if method not in SETTABLE_METHODS:
        raise TransitionError("Choose a payment method that can be verified.")
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status == "cancelled":
            raise TransitionError("Cancelled orders cannot change state.")
        if order.payment_status != "unpaid":
            raise TransitionError("The payment method cannot change after payment is recorded.")
        old = order.payment_method
        if old == method:
            return order
        lines = list(order.lines.all())
        total_discount, rate = Decimal("0"), Decimal("0")
        if lines:
            for line in lines:
                eligible = discount_eligible(line.product_slug)
                r, amount = compute_discount(line.subtotal, method, eligible)
                line.discount_eligible = eligible
                line.discount_amount = amount
                line.save(update_fields=["discount_eligible", "discount_amount"])
                total_discount += amount
                rate = max(rate, r)
        else:
            slug = (order.snapshot or {}).get("product", {}).get("slug", "")
            rate, total_discount = compute_discount(order.total, method, discount_eligible(slug))
        if total_discount <= 0:
            rate = Decimal("0")
        order.payment_method = method
        order.discount_rate = rate
        order.discount_amount = total_discount
        order.discount_status = "pending_verification" if rate else "none"
        order.save()
        OrderEvent.objects.create(
            order=order,
            field="payment_method",
            from_value=old,
            to_value=method,
            note="",
            by=user if getattr(user, "pk", None) else None,
        )
    return order


def update_payment_rules(post):
    """Guarda la elegibilidad del descuento Bitcoin por producto."""
    from .models import ProductPaymentRule

    for slug in PRODUCTOS:
        rule, _ = ProductPaymentRule.objects.get_or_create(product_slug=slug)
        rule.bitcoin_discount_eligible = bool(post.get(f"btc_{slug}"))
        rule.save()


# --- Order Copilot: preparación para fabricar, etapas y progreso --------------

STAGES = ("review", "ready", "production", "finished", "shipped")
STAGE_LABELS = {
    "review": "To review (unpaid)",
    "ready": "Paid / ready to make",
    "production": "In production",
    "finished": "Finished",
    "shipped": "Shipped",
}


def _legacy_line(order):
    """Pedido sin líneas (datos antiguos): línea virtual desde el snapshot."""
    from types import SimpleNamespace

    snap = order.snapshot or {}
    return SimpleNamespace(
        pk=None,
        product_name=(snap.get("product") or {}).get("name", ""),
        quantity=order.quantity,
        dog_snapshot=snap.get("dog") or {},
        size_reference=snap.get("size_reference") or {},
        required_measurements=snap.get("required_measurements") or {},
        size_selected="",
        size_confirmed=order.size_confirmed,
        production_status=order.production_status,
    )


def _line_checks(line):
    """Medidas y talla de UNA línea. Devuelve (medidas_ok, detalle, talla_ok, detalle)."""
    dog = line.dog_snapshot or {}
    required = line.required_measurements or {}
    missing = [
        label
        for key, label in (
            ("weight_kg", "weight"),
            ("back_length_cm", "back length"),
            ("chest_girth_cm", "chest girth"),
        )
        if not dog.get(key)
    ]
    if required.get("neck_girth") and not dog.get("neck_girth_cm"):
        missing.append("neck girth")

    ref = line.size_reference or {}
    status = ref.get("status")
    candidates = ref.get("candidates") or []
    selected = (line.size_selected or "").strip()
    confirmed = (line.size_confirmed or "").strip()
    if confirmed:
        size_ok, size_detail = True, ""
    elif selected:
        size_ok = selected in candidates
        size_detail = "" if size_ok else (
            f"customer chose {selected}; measurements suggest "
            + (", ".join(candidates) if candidates else "a size outside the table")
            + " — staff must confirm the size"
        )
    else:
        size_ok = status == "matched"
        size_detail = "" if size_ok else (
            "reference size is " + ("ambiguous" if status == "ambiguous" else "outside the table")
            + " — staff must confirm the size"
        )
    return not missing, ", ".join(missing), size_ok, size_detail


def order_readiness(order):
    """Indicadores verificables de un pedido, separados entre sí.

    - saved: el pedido existe.
    - payment: pago registrado con un método verificable (no demo).
    - info: entrega completa y, en CADA línea, medidas completas y talla clara
      o confirmada.
    - ready: pago + información validada + pedido no cancelado.
    `lines` detalla la preparación de cada producto. Nada aquí inventa datos.
    """
    lines = list(order.lines.all()) or [_legacy_line(order)]
    multi = len(lines) > 1

    paid = order.payment_status == "paid" and order.payment_method not in DEMO_METHODS
    missing_delivery = [
        label
        for label, value in (
            ("name", order.customer_name),
            ("email", order.customer_email),
            ("phone", order.customer_phone),
            ("country", order.country),
            ("city", order.city),
            ("address", order.address),
        )
        if not (value or "").strip()
    ]
    cancelled = order.status == "cancelled"

    line_results, meas_details, size_details = [], [], []
    for line in lines:
        m_ok, m_detail, s_ok, s_detail = _line_checks(line)
        prefix = f"{line.product_name}: " if multi else ""
        if m_detail:
            meas_details.append(prefix + m_detail)
        if s_detail:
            size_details.append(prefix + s_detail)
        blockers = []
        if not m_ok:
            blockers.append(f"missing {m_detail}")
        if not s_ok:
            blockers.append(s_detail)
        line_results.append(
            {
                "line": line,
                "measurements_ok": m_ok,
                "size_ok": s_ok,
                "info_ok": m_ok and s_ok,
                "blockers": blockers,
                "ready": paid and not missing_delivery and m_ok and s_ok and not cancelled,
            }
        )
    meas_ok = all(r["measurements_ok"] for r in line_results)
    size_ok = all(r["size_ok"] for r in line_results)

    checks = [
        {"key": "saved", "ok": True, "label": "Order saved", "detail": ""},
        {
            "key": "payment",
            "ok": paid,
            "label": "Payment confirmed",
            "detail": "" if paid else (
                "Demo method cannot be paid"
                if order.payment_method in DEMO_METHODS
                else "No payment recorded"
            ),
        },
        {
            "key": "delivery",
            "ok": not missing_delivery,
            "label": "Delivery details complete",
            "detail": ", ".join(missing_delivery),
        },
        {
            "key": "measurements",
            "ok": meas_ok,
            "label": "Measurements complete",
            "detail": "; ".join(meas_details),
        },
        {
            "key": "size",
            "ok": size_ok,
            "label": "Size clear or confirmed by staff",
            "detail": "; ".join(size_details),
        },
    ]
    info_valid = not missing_delivery and meas_ok and size_ok
    ready = paid and info_valid and not cancelled
    blockers = []
    if cancelled:
        blockers.append("order is cancelled")
    for c in checks:
        if not c["ok"]:
            blockers.append(f"{c['label'].lower()}" + (f" ({c['detail']})" if c["detail"] else ""))
    return {
        "checks": checks,
        "saved": True,
        "payment_confirmed": paid,
        "info_validated": info_valid,
        "ready": ready,
        "blockers": blockers,
        "lines": line_results,
    }


def progress_steps(order):
    """Línea de progreso del pedido (saved → ... → delivered)."""
    r = order_readiness(order)
    steps = [
        ("Order saved", True),
        ("Payment verified", r["payment_confirmed"]),
        ("In production", order.production_status in ("in_production", "completed")),
        ("Production completed", order.production_status == "completed"),
        ("Shipped", order.shipping_status in ("shipped", "delivered")),
        ("Delivered", order.shipping_status == "delivered"),
    ]
    result, current_set = [], False
    for label, done in steps:
        current = (not done) and not current_set
        if current:
            current_set = True
        result.append({"label": label, "done": done, "current": current})
    return result


def stage_filter(stage):
    """Q para una etapa operativa; None si la etapa no existe."""
    from django.db.models import Q

    active = ~Q(status="cancelled")
    if stage == "review":
        return active & Q(payment_status="unpaid")
    if stage == "ready":
        return active & Q(payment_status="paid", production_status="not_started")
    if stage == "production":
        return active & Q(production_status="in_production")
    if stage == "finished":
        return active & Q(production_status="completed", shipping_status="not_shipped")
    if stage == "shipped":
        return active & Q(shipping_status__in=["shipped", "delivered"])
    if stage == "attention":
        return (
            stage_filter("review") | stage_filter("ready") | stage_filter("finished")
        )
    return None


def stage_counts():
    from .models import Order

    return [
        {"key": s, "label": STAGE_LABELS[s], "count": Order.objects.filter(stage_filter(s)).count()}
        for s in STAGES
    ]


def confirm_size(order, label, user=None, line=None):
    """El personal confirma la talla de una línea (cuando la de referencia o la
    elegida por el cliente no es concluyente)."""
    from django.db import transaction

    from .models import Order, OrderEvent, OrderLine

    label = (label or "").strip()
    if not label:
        raise TransitionError("Enter the confirmed size.")
    if len(label) > 40:
        raise TransitionError("The size label is too long.")
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status == "cancelled":
            raise TransitionError("Cancelled orders cannot change state.")
        lines = list(order.lines.select_for_update().all())
        if line is not None:
            target = next((l for l in lines if l.pk == getattr(line, "pk", line)), None)
            if target is None:
                raise TransitionError("That line does not belong to this order.")
        elif len(lines) == 1:
            target = lines[0]
        elif not lines:
            target = None
        else:
            raise TransitionError("Choose which product the size applies to.")
        if target is not None:
            if target.production_status != "not_started":
                raise TransitionError("The size cannot change once production has started.")
            old = target.size_confirmed
            target.size_confirmed = label
            target.save(update_fields=["size_confirmed"])
        elif order.production_status != "not_started":
            raise TransitionError("The size cannot change once production has started.")
        else:
            old = order.size_confirmed
        if len(lines) <= 1:
            order.size_confirmed = label  # espejo del pedido de una sola línea
            order.save(update_fields=["size_confirmed"])
        OrderEvent.objects.create(
            order=order, field="size_confirmed", from_value=(old or "")[:20], to_value=label[:20],
            note=(f"{target.product_name}: " if target is not None and len(lines) > 1 else "") + label,
            by=user if getattr(user, "pk", None) else None,
        )
    return order


def set_tracking(order, number, carrier="", user=None):
    """Registra el número de seguimiento (opcional) del envío."""
    from django.db import transaction

    from .models import Order, OrderEvent

    number = (number or "").strip()
    carrier = (carrier or "").strip()
    if len(number) > 60 or len(carrier) > 60:
        raise TransitionError("Tracking number and carrier must be at most 60 characters.")
    if any(c in number + carrier for c in "<>"):
        raise TransitionError("Tracking details contain invalid characters.")
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status == "cancelled":
            raise TransitionError("Cancelled orders cannot change state.")
        old = order.tracking_number
        order.tracking_number = number
        order.tracking_carrier = carrier
        order.save(update_fields=["tracking_number", "tracking_carrier"])
        if old != number:
            OrderEvent.objects.create(
                order=order, field="tracking_number", from_value=old[:20], to_value=number[:20],
                note=carrier, by=user if getattr(user, "pk", None) else None,
            )
    return order


# --- Producción por línea -------------------------------------------------------

LINE_PRODUCTION_FLOW = {
    "not_started": ["in_production"],
    "in_production": ["completed"],
}


def aggregate_production(statuses):
    statuses = list(statuses)
    if statuses and all(x == "completed" for x in statuses):
        return "completed"
    if not statuses or all(x == "not_started" for x in statuses):
        return "not_started"
    return "in_production"


def apply_line_transition(line, new_value, user=None, note=""):
    """Cambia la producción de UNA línea (mismas reglas que el pedido completo)."""
    from django.db import transaction

    from .models import Order, OrderEvent, OrderLine

    note = (note or "").strip()
    with transaction.atomic():
        line = OrderLine.objects.select_for_update().get(pk=line.pk)
        order = Order.objects.select_for_update().get(pk=line.order_id)
        current = line.production_status
        if new_value not in LINE_PRODUCTION_FLOW.get(current, []):
            raise TransitionError(f"Cannot change production from {current} to {new_value}.")
        if order.status == "cancelled":
            raise TransitionError("Cancelled orders cannot change state.")
        if new_value == "in_production":
            if order.payment_status != "paid":
                raise TransitionError("Payment must be verified before production can start.")
            readiness = order_readiness(order)
            result = next((r for r in readiness["lines"] if r["line"].pk == line.pk), None)
            problems = []
            delivery = next((c for c in readiness["checks"] if c["key"] == "delivery"), None)
            if delivery and not delivery["ok"]:
                problems.append(f"delivery details incomplete ({delivery['detail']})")
            if result is not None:
                problems.extend(result["blockers"])
            if problems:
                raise TransitionError("Cannot start production: " + "; ".join(problems) + ".")
        line.production_status = new_value
        line.save(update_fields=["production_status"])
        new_order_status = aggregate_production(order.lines.values_list("production_status", flat=True))
        previous_order_status = order.production_status
        if new_order_status != previous_order_status:
            order.production_status = new_order_status
            order.save(update_fields=["production_status"])
        OrderEvent.objects.create(
            order=order,
            field="line_production",
            from_value=current,
            to_value=new_value,
            note=(f"{line.product_name}" + (f" — {note}" if note else ""))[:200],
            by=user if getattr(user, "pk", None) else None,
        )
    return line
