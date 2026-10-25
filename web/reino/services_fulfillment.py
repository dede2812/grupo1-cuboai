"""Cumplimiento de ofertas no físicas: descarga digital y reserva de
servicio (G2, §12.2, §13).

Reglas:
- El derecho de descarga nace UNA sola vez y SOLO tras el estado de pago
  exigido (pagado); con token, expiración y límite de descargas (A33).
- La reserva de franja se confirma al crear el pedido con capacidad bajo
  bloqueo: dos compradores de la última franja = una reserva válida (A34).
- Cancelar/vencer el pedido libera la franja una sola vez (junto al stock).
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (Booking, DigitalAsset, DigitalGrant, Order, OrderEvent,
                     ServiceSlot)

GRANT_TTL_DAYS = 30


class FulfillmentError(Exception):
    """Conflicto de cumplimiento comprensible para el comprador."""


def reserve_service_slots(order):
    """Crea las reservas de las líneas con franja elegida (capacidad real)."""
    demand = order.items.filter(service_slot__isnull=False).values("service_slot_id").annotate(units=Sum("quantity"))
    for item in demand.order_by("service_slot_id"):
        with transaction.atomic():
            locked = ServiceSlot.objects.select_for_update().get(pk=item["service_slot_id"])
            if Booking.objects.filter(slot=locked, order=order).exists():
                continue
            if (locked.product.store_id != order.store_id or not locked.is_active or
                locked.starts_at <= timezone.now() or locked.booked + item["units"] > locked.capacity):
                raise FulfillmentError(
                    f"La franja de «{locked.product.short_title}» ya no tiene "
                    f"cupo. Elegí otra hora; no cobramos por algo que no podemos dar.")
            locked.booked += item["units"]
            locked.save(update_fields=["booked"])
            Booking.objects.create(
                slot=locked, order=order, quantity=item["units"], buyer_email=getattr(order, "customer_email", "") or "sin-correo@local")


def release_service_slots(order, user=None, reason="Cancelación"):
    """Libera las reservas del pedido, exactamente una vez por reserva."""
    for booking in order.bookings.select_related("slot"):
        with transaction.atomic():
            b = Booking.objects.select_for_update().get(pk=booking.pk)
            if b.status == Booking.Status.CANCELLED:
                continue  # repetición: no-op
            slot = ServiceSlot.objects.select_for_update().get(pk=b.slot_id)
            slot.booked = max(0, slot.booked - b.quantity)
            slot.save(update_fields=["booked"])
            b.status = Booking.Status.CANCELLED
            b.save(update_fields=["status"])
    OrderEvent.objects.create(
        order=order, field="booking", to_value="released",
        note=f"{reason}: franjas liberadas ({order.reference})", by=user)


def grant_digital_entitlements(order, user=None):
    """Crea los derechos de descarga del pedido PAGADO, exactamente una vez
    por par (archivo, pedido) — la restricción única respalda la propiedad."""
    created = []
    digital_products = [item.variant.product for item in
                        order.items.select_related("variant__product")
                        if item.variant and item.offer_type == "digital"]
    for product in digital_products:
        for asset in DigitalAsset.objects.filter(product=product, is_active=True):
            grant, was_created = DigitalGrant.objects.get_or_create(
                asset=asset, order=order,
                defaults={"expires_at": timezone.now() + timedelta(days=GRANT_TTL_DAYS)})
            if was_created:
                created.append(grant)
    if created:
        OrderEvent.objects.create(
            order=order, field="digital", to_value="granted",
            note=f"Descargas habilitadas: {len(created)} ({order.reference})", by=user)
    return created


def authorized_download(token):
    """Valida un token de descarga: existe, no venció y le quedan usos.

    Devuelve (grant, error). Nunca revela si el token «casi» existe.
    """
    grant = (DigitalGrant.objects.filter(token=token)
             .select_related("asset", "order").first())
    if grant is None:
        return None, "Ese enlace de descarga no es válido."
    if (not grant.asset.is_active or grant.order.status == "cancelled" or
        grant.order.payment_status not in ("paid", "partially_refunded")):
        return None, "El estado actual del pedido no permite esta descarga."
    if grant.expires_at < timezone.now():
        return None, "Ese enlace de descarga venció. Escribinos y lo renovamos."
    if grant.downloads >= grant.max_downloads:
        return None, "Llegaste al límite de descargas de este enlace."
    return grant, None


def register_download(grant):
    """Cuenta la descarga de forma atómica (límite bajo concurrencia)."""
    from django.db.models import F
    updated = (DigitalGrant.objects.filter(pk=grant.pk, downloads__lt=F("max_downloads"),
        expires_at__gt=timezone.now(), asset__is_active=True,
        order__payment_status__in=("paid", "partially_refunded"))
        .exclude(order__status="cancelled").update(downloads=F("downloads") + 1))
    if not updated:
        raise FulfillmentError("La descarga ya no está disponible o llegó a su límite.")
    grant.refresh_from_db()
    return grant.downloads
