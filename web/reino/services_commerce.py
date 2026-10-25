"""Núcleo de compra P0: carrito, checkout, pedido, reservas e idempotencia.

Reglas (§15) tras la auditoría del PR #3:
- Agregar al carrito NO aparta inventario; preparar checkout crea una reserva
  corta (10 min) dentro de una transacción, con demanda AGREGADA por SKU (R03).
- La clave idempotente queda ligada a tienda+sesión+carrito+contenido (R01/R02):
  mismo intento => mismo resumen; contenido distinto bajo la misma clave =>
  resumen NUEVO (el anterior se invalida y sus reservas se liberan).
- Dinero en Decimal con money(); envío validado en servidor (R06): el
  navegador nunca es la autoridad sobre modalidad, zona o tarifa.
- Cancelar o vencer un pedido no expedido restituye el inventario exactamente
  una vez (R04); los movimientos quedan registrados con actor y motivo.
- Descuento Bitcoin 15 % SOLO sobre líneas elegibles migradas de la regla
  histórica (R05); sigue pendiente de verificación humana.
- Transiciones con capacidad por rol (R13): logística no confirma cobros.
"""

import hashlib
import json
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    Cart, CartItem, CheckoutSession, Order, OrderEvent, OrderItem, OutboxEvent,
    StockReservation, Store, Variant,
)
from . import services_fulfillment
from .money import BITCOIN_DISCOUNT_RATE, money

RESERVATION_MINUTES = 10
MAX_QUANTITY = 10

DELIVERY_MODES = ("pickup", "local")
PAYMENT_METHODS = ("manual", "bitcoin")


class CartError(Exception):
    pass


class StockConflict(Exception):
    """Stock insuficiente o carrito cambiado: conflicto recuperable (409)."""

    def __init__(self, message, lines=None):
        super().__init__(message)
        self.lines = lines or []


class PermissionDenied(CartError):
    """El rol del miembro no permite esta operación (R13)."""


def get_open_cart(store, session_key, create=False):
    cart = Cart.objects.filter(
        store=store, session_key=session_key, status=Cart.Status.OPEN
    ).first()
    if cart is None and create:
        cart = Cart.objects.create(store=store, session_key=session_key)
    return cart


def cart_summary(cart, payment_method="manual"):
    """Totales del carrito calculados en servidor. Envío: por calcular.

    El descuento Bitcoin aplica ÚNICAMENTE a líneas elegibles (R05): la
    elegibilidad migra de la regla histórica del negocio y cualquier cambio
    futuro debe aprobarse y versionarse.
    """
    lines, subtotal, eligible_subtotal = [], money(0), money(0)
    for item in cart.items.select_related("variant__product", "recipient"):
        # Revalidación de precio: el snapshot puede diferir del precio vigente.
        current = item.variant.price
        line_subtotal = money(current * item.quantity)
        subtotal += line_subtotal
        eligible = bool(item.variant.product.bitcoin_discount_eligible)
        if eligible:
            eligible_subtotal += line_subtotal
        lines.append({
            "item": item,
            "current_price": current,
            "price_changed": current != item.unit_price,
            "subtotal": line_subtotal,
            "discount_eligible": eligible,
            "available": item.variant.stock,
            "ok": item.variant.is_active and item.variant.stock >= item.quantity,
        })
    discount = money(0)
    if payment_method == "bitcoin":
        discount = money(eligible_subtotal * BITCOIN_DISCOUNT_RATE)
    return {
        "lines": lines,
        "subtotal": subtotal,
        "discount": discount,
        "discount_eligible_subtotal": eligible_subtotal,
        "discount_note": (
            "Descuento Bitcoin (15 %) sobre piezas participantes, pendiente de verificación"
            if discount else ""
        ),
        "shipping": None,  # por calcular: nunca un total incompleto como "final"
        "merchandise_total": subtotal,
        "amount_due": subtotal,  # el descuento aplica al verificar el pago
        "total_if_discount": money(subtotal - discount),
        "has_issues": any(not l["ok"] for l in lines),
        "is_empty": not lines,
    }


def add_item(cart, variant: Variant, quantity=1, recipient=None, service_slot=None):
    """Añade una variante válida. Revalida precio; no duplica (misma variante
    y destinatario actualizan cantidad). Una variante inexistente no entra.

    Servicio con cita: la franja es obligatoria, de ESTE producto y con cupo
    (la ocupación definitiva se toma al confirmar el pedido, bajo bloqueo).
    """
    if not variant.is_active or variant.product.status != "published":
        raise CartError("Esa variante ya no está disponible.")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise CartError("Ingresá una cantidad válida.") from None
    if quantity < 1 or quantity > MAX_QUANTITY:
        raise CartError(f"La cantidad debe ser entre 1 y {MAX_QUANTITY}.")
    if variant.product.offer_type == "service":
        if service_slot is None or service_slot.product_id != variant.product_id                 or not service_slot.is_active:
            raise CartError("Elegí una franja válida para reservar.")
        if service_slot.booked + quantity > service_slot.capacity:
            raise CartError("Esa franja ya no tiene cupo; elegí otra hora.")
    if variant.product.store_id != cart.store_id:
        raise CartError("La variante no pertenece a esta tienda.")
    if variant.stock < 1:
        raise StockConflict("Sin existencias por ahora.", [variant.sku])
    with transaction.atomic():
        item = (
            CartItem.objects.select_for_update()
            .filter(cart=cart, variant=variant, recipient=recipient)
            .first()
        )
        if item:
            if item.service_slot_id != getattr(service_slot, "pk", None):
                raise CartError("Esta opción ya está en el carrito con otra franja. "
                                "Quitá esa línea antes de elegir un horario diferente.")
            item.quantity = min(item.quantity + quantity, MAX_QUANTITY)
            item.unit_price = variant.price
            item.save(update_fields=["quantity", "unit_price"])
        else:
            CartItem.objects.create(
                cart=cart, variant=variant, quantity=quantity,
                recipient=recipient, unit_price=variant.price,
                service_slot=service_slot,
            )
        _bump(cart)
    return cart


def update_item(cart, item_id, quantity):
    item = CartItem.objects.filter(cart=cart, pk=item_id).first()
    if item is None:
        raise CartError("Esa línea ya no existe.")
    quantity = int(quantity)
    if quantity < 1 or quantity > MAX_QUANTITY:
        raise CartError(f"La cantidad debe ser entre 1 y {MAX_QUANTITY}.")
    item.quantity = quantity
    item.unit_price = item.variant.price
    item.save(update_fields=["quantity", "unit_price"])
    _bump(cart)


def remove_item(cart, item_id):
    CartItem.objects.filter(cart=cart, pk=item_id).delete()
    _bump(cart)


def _bump(cart):
    cart.version = (cart.version or 0) + 1
    cart.save(update_fields=["version", "updated_at"])


# ------------------------------------------------------------- checkout ----

def validate_shipping(store, delivery_mode, zone, cart=None):
    """Validación de envío en SERVIDOR (R06). El navegador nunca es la autoridad.

    Devuelve (modalidad_normalizada, zona_validada, tarifa Decimal).
    G2: un carrito SIN líneas físicas (digital/servicio) no cobra ni exige
    transporte — la modalidad queda «sin envío».
    """
    if cart is not None and not cart_requires_shipping(cart):
        return "none", None, money(0)
    if delivery_mode not in DELIVERY_MODES:
        raise CartError("Elegí una modalidad de entrega válida.")
    if delivery_mode == "pickup":
        return "pickup", None, money(0)
    # Entrega local: zona obligatoria, de ESTA tienda, activa y de modalidad local.
    if zone is None:
        raise CartError("Elegí una zona de entrega para cotizar el envío.")
    if zone.store_id != store.id or not zone.is_active or zone.mode != "local":
        raise CartError("Esa zona no corresponde a la modalidad elegida.")
    return "local", zone, money(zone.fee)


def cart_requires_shipping(cart):
    """¿El carrito contiene al menos una línea física? (G2, §12.2)"""
    return any(item.variant.product.offer_type == "physical"
               for item in cart.items.select_related("variant__product"))


def _summary_hash(summary):
    """Huella del contenido aprobado: mismo intento => misma huella (R02)."""
    canonical = json.dumps(summary, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def prepare_checkout(cart, payment_method, delivery_mode="pickup", zone=None,
                     idempotency_key=None):
    """Crea la sesión de checkout con reserva atómica de stock (10 min).

    - Clave ligada a carrito y contenido (R01/R02): misma clave + mismo
      contenido => misma sesión; misma clave + contenido distinto => sesión
      nueva vigente (la anterior se invalida y sus reservas se liberan).
    - Demanda agregada por SKU: dos destinatarios no reservan por encima del
      stock disponible (R03).
    - Modalidad/zona/tarifa validadas en servidor (R06).
    """
    if payment_method not in PAYMENT_METHODS:
        raise CartError("Elegí un método de pago habilitado.")
    key = idempotency_key or uuid.uuid4().hex

    summary = cart_summary(cart, payment_method)
    if summary["is_empty"]:
        raise CartError("Tu carrito está vacío.")
    if summary["has_issues"]:
        raise StockConflict(
            "Alguna línea ya no tiene existencias suficientes.",
            [l["item"].variant.sku for l in summary["lines"] if not l["ok"]],
        )

    delivery_mode, zone, shipping_amount = validate_shipping(
        cart.store, delivery_mode, zone, cart=cart)

    content = {
        "subtotal": str(summary["subtotal"]),
        "discount": str(summary["discount"]),
        "shipping": str(shipping_amount),
        "payment_method": payment_method,
        "delivery_mode": delivery_mode,
        "zone": zone.name if zone else "",
        "lines": [
            {"variant_id": l["item"].variant_id, "quantity": l["item"].quantity,
             "service_slot_id": l["item"].service_slot_id,
             "unit_price": str(l["current_price"]),
             "discount_eligible": l["discount_eligible"],
             # Destinatario por ID (§8.1): el alias es solo presentación.
             "recipient_id": l["item"].recipient_id or 0,
             "recipient_alias": l["item"].recipient.alias if l["item"].recipient else ""}
            for l in summary["lines"]
        ],
    }
    digest = _summary_hash(content)

    # Identidad estable del intento (§8.1, N02): se reutiliza la revisión
    # vigente si el contenido es idéntico, sin importar su número interno;
    # una revisión vencida se RENUEVA con stock revalidado (N03) y el
    # comprador vuelve a ver el nuevo resumen antes de confirmar.
    existing = CheckoutSession.objects.filter(
        intent_key=key, cart=cart, is_current=True
    ).order_by("-revision").first()
    if existing and existing.summary_hash == digest and not existing.is_expired():
        return existing  # reintento idéntico: misma revisión aprobada

    with transaction.atomic():
        if existing:
            # Contenido distinto o revisión vencida bajo el mismo intento:
            # invalidar la anterior y liberar sus reservas atómicamente (R02).
            existing.is_current = False
            existing.save(update_fields=["is_current"])
            StockReservation.objects.filter(
                checkout=existing, status=StockReservation.Status.ACTIVE
            ).update(status=StockReservation.Status.RELEASED)

        # Demanda AGREGADA por variante (R03): dos destinatarios del mismo SKU
        # comparten el mismo stock.
        demand = {}
        for line in summary["lines"]:
            demand[line["item"].variant_id] = demand.get(line["item"].variant_id, 0) + line["item"].quantity

        variants = list(
            Variant.objects.select_for_update()
            .filter(pk__in=demand)
            .order_by("pk")  # orden estable: sin interbloqueos
        )
        now = timezone.now()
        for v in variants:
            reserved = sum(
                r.quantity
                for r in v.reservations.filter(
                    status=StockReservation.Status.ACTIVE, expires_at__gt=now
                )
            )
            if v.stock - reserved < demand[v.pk]:
                raise StockConflict(
                    f"Quedan {max(v.stock - reserved, 0)} unidades de {v.option_label}.",
                    [v.sku],
                )

        revision = CheckoutSession.objects.filter(intent_key=key).count()
        internal_key = key if revision == 0 else f"{key}#{revision}"
        expires = now + timedelta(minutes=RESERVATION_MINUTES)
        checkout = CheckoutSession.objects.create(
            cart=cart, cart_version=cart.version, intent_key=key, revision=revision,
            idempotency_key=internal_key, summary=content, summary_hash=digest,
            expires_at=expires,
        )
        for line in summary["lines"]:
            StockReservation.objects.create(
                variant_id=line["item"].variant_id, checkout=checkout,
                quantity=line["item"].quantity, expires_at=expires,
            )
    return checkout


def confirm_checkout(checkout, customer, idempotency_key):
    """Convierte la sesión de checkout en pedido (idempotente).

    Mismo intento => mismo pedido; pago manual/bitcoin => pendiente de
    verificación; la reserva se consume y el stock se descuenta una sola vez.
    """
    existing = Order.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing
    if not checkout.is_current:
        raise CartError("Ese resumen fue sustituido; revisá el vigente antes de confirmar.")
    if checkout.is_expired():
        raise CartError("La revisión venció. Tu carrito sigue guardado: prepará una nueva revisión.")
    if checkout.cart.status != Cart.Status.OPEN or checkout.cart.version != checkout.cart_version:
        raise CartError("El carrito cambió; revisá el nuevo resumen antes de confirmar.")

    s = checkout.summary
    subtotal = money(s["subtotal"])
    discount = money(s.get("discount", "0"))
    shipping = money(s["shipping"]) if s.get("shipping") is not None else None
    payment_method = s.get("payment_method", "manual")
    total = money(subtotal - discount + (shipping or 0))

    try:
        return _create_order(checkout, idempotency_key, s, subtotal, discount,
                             shipping, payment_method, total, customer)
    except IntegrityError:
        # Doble confirmación del MISMO intento en concurrencia (Postgres): la
        # restricción única de idempotency_key lo resguarda; el segundo hilo
        # devuelve el pedido del primero — jamás un duplicado (R02/A49).
        existing = Order.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
        raise


def _create_order(checkout, idempotency_key, s, subtotal, discount, shipping,
                  payment_method, total, customer):
    with transaction.atomic():
        # Referencia única por tienda sin count()+1 al aire: la fila de la
        # tienda se bloquea dentro de la transacción (serializa por comercio) y
        # la restricción única (store, reference) respalda la propiedad (R03).
        store = Store.objects.select_for_update().get(pk=checkout.cart.store_id)
        variants = list(
            Variant.objects.select_for_update()
            .filter(pk__in=[l["variant_id"] for l in s["lines"]]).order_by("pk")
        )
        by_pk = {v.pk: v for v in variants}
        demand = {}
        for line in s["lines"]:
            demand[line["variant_id"]] = demand.get(line["variant_id"], 0) + line["quantity"]
        for v in variants:
            if v.stock < demand[v.pk]:
                raise StockConflict("Sin existencias suficientes.", [v.sku])
        order = Order.objects.create(
            store=store,
            cart=checkout.cart,
            idempotency_key=idempotency_key,
            reference=_next_reference(store),
            currency=store.currency,
            subtotal=subtotal,
            discount_amount=discount,
            discount_note=(
                "Descuento Bitcoin (15 %) sobre piezas participantes, pendiente de verificación"
                if discount else ""
            ),
            shipping_amount=shipping,
            total=total,
            customer_name=customer["name"],
            customer_email=customer["email"],
            customer_phone=customer.get("phone", ""),
            delivery_mode=s.get("delivery_mode", "pickup"),
            zone=s.get("zone", ""),
            address=customer.get("address", ""),
            city=customer.get("city", ""),
            payment_method=payment_method,
        )
        for i, line in enumerate(s["lines"]):
            v = by_pk[line["variant_id"]]
            v.stock -= line["quantity"]
            v.save(update_fields=["stock"])
            OrderItem.objects.create(
                order=order, position=i, variant=v, sku=v.sku,
                offer_type=v.product.offer_type,
                service_slot_id=line.get("service_slot_id"),
                title=v.product.short_title, option_label=v.option_label,
                recipient_alias=line.get("recipient_alias", ""),
                quantity=line["quantity"],
                unit_price=money(line["unit_price"]),
                subtotal=money(money(line["unit_price"]) * line["quantity"]),
            )
        StockReservation.objects.filter(checkout=checkout, status=StockReservation.Status.ACTIVE)\
            .update(status=StockReservation.Status.CONSUMED)
        checkout.is_current = False  # consumida: no reutilizable para otro pedido
        checkout.save(update_fields=["is_current"])
        cart = checkout.cart
        cart.status = Cart.Status.ORDERED
        cart.save(update_fields=["status", "updated_at"])
        OrderEvent.objects.create(order=order, field="status", to_value=Order.Status.PLACED,
                                  note="Pedido registrado")
        # A34: las franjas de servicio se reservan al crear el pedido, con
        # capacidad verificada bajo bloqueo (última franja = una reserva).
        services_fulfillment.reserve_service_slots(order)
        # Trabajo diferido recuperable: correo de confirmación (si hay sistema
        # transaccional configurado) y métricas. Se dispara una sola vez.
        OutboxEvent.objects.create(type="order_confirmation_email",
                                   payload={"order_id": str(order.public_id)})
        OutboxEvent.objects.create(type="metric",
                                   payload={"event": "order_placed", "order": order.reference})
    return order


def _next_reference(store):
    """Siguiente referencia legible; la tienda ya viene bloqueada (R03)."""
    prefix = "".join(w[0] for w in store.name.split()[:2]).upper() or "RC"
    last = Order.objects.filter(store=store).count()
    return f"{prefix}-{last + 1:06d}"


# Transiciones de panel (máquina de estados, actor y capacidad registrados) ---

TRANSITIONS = {
    "status": {
        Order.Status.PLACED: [Order.Status.CONFIRMED, Order.Status.CANCELLED],
        Order.Status.CONFIRMED: [Order.Status.CANCELLED, Order.Status.CLOSED],
    },
    "payment_status": {
        Order.PaymentStatus.PENDING: [Order.PaymentStatus.PAID, Order.PaymentStatus.FAILED,
                                      Order.PaymentStatus.EXPIRED],
        Order.PaymentStatus.PAID: [Order.PaymentStatus.REFUNDED,
                                   Order.PaymentStatus.PARTIALLY_REFUNDED,
                                   Order.PaymentStatus.DISPUTED],
        Order.PaymentStatus.PARTIALLY_REFUNDED: [Order.PaymentStatus.REFUNDED,
                                                 Order.PaymentStatus.DISPUTED],
    },
    "prep_status": {
        Order.PrepStatus.NOT_STARTED: [Order.PrepStatus.PREPARING, Order.PrepStatus.CANCELLED],
        Order.PrepStatus.PREPARING: [Order.PrepStatus.READY, Order.PrepStatus.CANCELLED],
    },
    "delivery_status": {
        Order.DeliveryStatus.UNASSIGNED: [Order.DeliveryStatus.SCHEDULED],
        Order.DeliveryStatus.SCHEDULED: [Order.DeliveryStatus.SHIPPED, Order.DeliveryStatus.INCIDENT],
        Order.DeliveryStatus.SHIPPED: [Order.DeliveryStatus.DELIVERED, Order.DeliveryStatus.INCIDENT,
                                       Order.DeliveryStatus.RETURNED],
        Order.DeliveryStatus.INCIDENT: [Order.DeliveryStatus.SCHEDULED, Order.DeliveryStatus.RETURNED],
    },
}

# Capacidad requerida por campo de transición (R13). Un botón oculto nunca
# sustituye la autorización del servidor.
FIELD_CAPABILITY = {
    "status": "orders",
    "payment_status": "payments",
    "prep_status": "fulfilment",
    "delivery_status": "fulfilment",
}

ROLE_CAPABILITIES = {
    "owner": {"orders", "payments", "fulfilment", "catalog", "inventory", "settings", "team"},
    "staff": {"orders", "fulfilment", "catalog", "inventory"},
    "logistics": {"fulfilment"},
}

# Campos que requieren evidencia obligatoria (motivo/referencia) al transicionar.
NEEDS_EVIDENCE = {("payment_status", Order.PaymentStatus.PAID),
                  ("payment_status", Order.PaymentStatus.REFUNDED),
                  ("payment_status", Order.PaymentStatus.PARTIALLY_REFUNDED)}


def member_can(member, capability):
    return member is not None and capability in ROLE_CAPABILITIES.get(member.role, set())


def apply_transition(order, field, to_value, user=None, note="", member=None,
                     refund_amount=None):
    """Cambio de estado validado con capacidad por rol (R13) y evidencia.

    El pedido se BLOQUEA y se RELEE dentro de la transacción (N04): una
    instancia vieja nunca decide sobre un estado que ya cambió. Si el pedido
    ya está en el estado destino, la operación es un no-op idempotente.

    - Pedido cancelado: solo admite registrar el reembolso de un pago recibido;
      nunca preparación ni despacho (coherencia de estados comerciales).
    - Cancelar/vencer un pedido no expedido restituye inventario UNA vez (R04).
    - Confirmar cobro o reembolsar exige nota (evidencia); el reembolso
      registra importe, medio y motivo: la etiqueta no es dinero devuelto.
    """
    capability = FIELD_CAPABILITY.get(field)
    if member is not None and (member.merchant_id != order.store.merchant_id or
                               not member_can(member, capability)):
        raise PermissionDenied("Tu rol no permite esta operación.")
    if (field, to_value) in NEEDS_EVIDENCE and not note.strip():
        raise CartError("Esta operación requiere una referencia o motivo (evidencia).")

    with transaction.atomic():
        # Bloquear y releer: la autoridad es el estado actual en base de datos.
        order = Order.objects.select_for_update().get(pk=order.pk)
        from_value = getattr(order, field)
        refund_update = (field == "payment_status" and to_value in (
            Order.PaymentStatus.REFUNDED, Order.PaymentStatus.PARTIALLY_REFUNDED))
        cumulative_refund = money(refund_amount) if refund_amount is not None else order.total
        if from_value == to_value and not (refund_update and cumulative_refund > (order.refund_amount or 0)):
            return order  # repetición de una transición ya aplicada: no-op

        if order.status == Order.Status.CANCELLED and field != "payment_status":
            raise CartError("Un pedido cancelado no puede prepararse ni despacharse.")
        if order.status == Order.Status.CANCELLED and field == "payment_status" and \
                to_value not in (Order.PaymentStatus.REFUNDED, Order.PaymentStatus.PARTIALLY_REFUNDED):
            raise CartError("A un pedido cancelado solo puede registrarse el reembolso.")

        allowed = TRANSITIONS.get(field, {}).get(from_value, [])
        if to_value not in [str(v) for v in allowed] and not (from_value == to_value and refund_update):
            raise CartError(f"Transición no permitida: {field} → {to_value}.")

        setattr(order, field, to_value)
        update = [field]
        if field == "payment_status" and to_value in (
                Order.PaymentStatus.REFUNDED, Order.PaymentStatus.PARTIALLY_REFUNDED):
            amount = cumulative_refund
            if amount <= 0 or amount > order.total or amount < (order.refund_amount or 0):
                raise CartError("El reembolso debe ser mayor que cero y no superar lo cobrado.")
            if to_value == Order.PaymentStatus.REFUNDED and amount != order.total:
                raise CartError("Un reembolso total debe cubrir el total cobrado.")
            if to_value == Order.PaymentStatus.PARTIALLY_REFUNDED and amount >= order.total:
                raise CartError("Un reembolso parcial debe ser inferior al total cobrado.")
            order.refund_amount = amount
            order.refund_note = note.strip()[:200]
            update += ["refund_amount", "refund_note"]
        order.save(update_fields=update)
        OrderEvent.objects.create(order=order, field=field, from_value=from_value,
                                  to_value=to_value, note=note, by=user)
        # R04: cancelar o vencer un pedido NO expedido restituye el inventario
        # exactamente una vez. Un pedido despachado requiere proceso de devolución.
        should_restock = (
            (field == "status" and to_value == Order.Status.CANCELLED)
            or (field == "payment_status" and to_value in (Order.PaymentStatus.EXPIRED,
                                                           Order.PaymentStatus.FAILED))
        )
        if should_restock:
            _restock_once(order, user=user,
                          reason="Cancelación" if field == "status" else "Pago vencido/fallido")
            services_fulfillment.release_service_slots(
                order, user=user,
                reason="Cancelación" if field == "status" else "Pago vencido/fallido")
        # A33: el acceso digital nace sólo con el cobro confirmado.
        if field == "payment_status" and to_value == Order.PaymentStatus.PAID:
            services_fulfillment.grant_digital_entitlements(order, user=user)
        event_name = None
        if field == "payment_status" and to_value == Order.PaymentStatus.PAID:
            event_name = "payment_verified"
        elif refund_update:
            event_name = "refund_recorded"
        elif field == "status" and to_value == Order.Status.CANCELLED:
            event_name = "order_cancelled"
        if event_name:
            from . import services_analytics
            services_analytics.track_once(event_name, store=order.store,
                key=f"{order.public_id}:{to_value}:{order.refund_amount or 0}",
                order=str(order.public_id), amount=str(order.refund_amount if refund_update else order.total),
                currency=order.currency)
    return order


def _restock_once(order, user=None, reason=""):
    """Devuelve el stock descontado al confirmar, UNA sola vez por pedido (N04).

    La comprobación se hace sobre la fila BLOQUEADA y releída dentro de la
    transacción: dos instancias cargadas antes de la primera cancelación
    jamás suman dos veces.
    """
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.stock_restored_at is not None:
            return False  # ya restituido por otra solicitud
        if not locked.shipments.exists():
            departed_states = (Order.DeliveryStatus.SHIPPED, Order.DeliveryStatus.DELIVERED, Order.DeliveryStatus.RETURNED)
            if (locked.delivery_status in departed_states or
                    locked.events.filter(field='delivery_status', to_value__in=departed_states).exists()):
                return False  # una incidencia posterior no borra la salida histórica
        dispatched = {}
        from .services_shipping import was_dispatched
        for shipment in locked.shipments.prefetch_related("events"):
            if not was_dispatched(shipment):
                continue
            for line in shipment.lines:
                item_id = line["order_item_id"]
                dispatched[item_id] = dispatched.get(item_id, 0) + line["quantity"]
        for item in locked.items.select_related("variant"):
            if item.variant_id is None:
                continue
            restore_quantity = max(0, item.quantity - dispatched.get(item.pk, 0))
            if not restore_quantity:
                continue
            v = Variant.objects.select_for_update().get(pk=item.variant_id)
            v.stock += restore_quantity
            v.save(update_fields=["stock"])
        locked.stock_restored_at = timezone.now()
        locked.save(update_fields=["stock_restored_at"])
        OrderEvent.objects.create(
            order=locked, field="stock", to_value="restored",
            note=f"{reason}: inventario restituido ({locked.reference})", by=user,
        )
    return True
