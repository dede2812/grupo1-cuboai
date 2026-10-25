"""Envíos por líneas históricas; reservas e idempotencia bajo bloqueo del pedido."""
from django.db import transaction
from django.utils import timezone
from . import services_commerce as commerce
from .models import Order, OrderEvent, Shipment, ShipmentEvent
from .shipping.manual import ManualShipping
from .shipping.mydhl import MyDHLAdapter

ADAPTERS = {a.key: a for a in (ManualShipping(), MyDHLAdapter())}
STATUS_ORDER = ['preparing', 'ready', 'label_created', 'picked_up', 'in_transit', 'delivered']
DISPATCHED_STATES = ('picked_up', 'in_transit', 'delivered', 'returned')


def was_dispatched(shipment):
    """Una incidencia posterior nunca borra la salida física del historial."""
    return shipment.status in DISPATCHED_STATES or any(event.code in DISPATCHED_STATES for event in shipment.events.all())


def adapter_for(provider):
    if provider not in ADAPTERS:
        raise commerce.CartError('Proveedor de envío no disponible.')
    return ADAPTERS[provider]


def _physical(item):
    historical = getattr(item, 'offer_type', None)
    return historical == 'physical' if historical else bool(item.variant and item.variant.product.offer_type == 'physical')


def shipped_quantities(order):
    totals = {}
    for shipment in order.shipments.exclude(status='cancelled'):
        for line in shipment.lines:
            totals[line['order_item_id']] = totals.get(line['order_item_id'], 0) + line['quantity']
    return totals


def shippable_lines(order):
    shipped = shipped_quantities(order)
    return [{'item': item, 'pending': item.quantity - shipped.get(item.pk, 0)}
            for item in order.items.select_related('variant__product')
            if _physical(item) and item.quantity > shipped.get(item.pk, 0)]


def _normalise_lines(lines):
    if not isinstance(lines, list) or not lines:
        raise commerce.CartError('No quedan unidades físicas por despachar.')
    normalised, seen = [], set()
    for line in lines:
        if not isinstance(line, dict) or type(line.get('order_item_id')) is not int or type(line.get('quantity')) is not int:
            raise commerce.CartError('Línea o cantidad de envío inválida.')
        item_id, quantity = line['order_item_id'], line['quantity']
        if item_id in seen or quantity < 1:
            raise commerce.CartError('Cada línea debe aparecer una vez y con cantidad positiva.')
        seen.add(item_id)
        normalised.append({'order_item_id': item_id, 'quantity': quantity})
    return sorted(normalised, key=lambda line: line['order_item_id'])


def create_shipment(order, lines=None, provider='manual', service='', user=None, address=None, idempotency_key=None):
    adapter = adapter_for(provider)
    if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 120):
        raise commerce.CartError('Clave de despacho inválida.')
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if idempotency_key is not None:
            operation = ShipmentEvent.objects.select_related('shipment').filter(
                shipment__order=locked, code='create-request', provider_event_id=idempotency_key).first()
            if operation:
                existing = operation.shipment
                if (existing.provider != provider or existing.service != service or
                        (lines is not None and existing.lines != _normalise_lines(lines)) or
                        (address is not None and existing.address_snapshot != address)):
                    raise commerce.CartError('La clave de despacho pertenece a otra operación.')
                return existing
        if locked.status == 'cancelled' or locked.stock_restored_at:
            raise commerce.CartError('Un pedido cancelado o sin reserva no admite envíos.')
        if lines is None:
            lines = [{'order_item_id': row['item'].pk, 'quantity': row['pending']} for row in shippable_lines(locked)]
            if not lines:
                existing = locked.shipments.exclude(status='cancelled').filter(provider=provider, service=service).order_by('-pk').first()
                if existing and idempotency_key is None:
                    return existing
                raise commerce.CartError('No quedan unidades físicas por despachar.')
        lines = _normalise_lines(lines)
        # Los llamadores históricos deduplican por líneas. Con clave explícita,
        # cada operación nueva puede despachar un segundo parcial idéntico.
        legacy_matches = (locked.shipments.exclude(status='cancelled').filter(provider=provider, service=service)
            if idempotency_key is None else ())
        for existing in legacy_matches:
            if sorted(existing.lines, key=lambda line: line['order_item_id']) == lines:
                if address is not None and existing.address_snapshot != address:
                    raise commerce.CartError('El envío existente tiene otra dirección; revisalo antes de reintentar.')
                return existing
        shipped = shipped_quantities(locked)
        items = {item.pk: item for item in locked.items.select_related('variant__product')}
        for line in lines:
            item = items.get(line['order_item_id'])
            if not item or not _physical(item):
                raise commerce.CartError('Sólo pueden enviarse líneas físicas de este pedido.')
            left = item.quantity - shipped.get(item.pk, 0)
            if line['quantity'] > left:
                raise commerce.CartError(f'No podés despachar esa cantidad de «{item.title}»: quedan {left}.')
        shipment = Shipment.objects.create(order=locked, provider=provider, service=service,
            amount=locked.shipping_amount or 0, currency=locked.currency, lines=lines, address_snapshot=address or {})
        if idempotency_key is not None:
            ShipmentEvent.objects.create(shipment=shipment, code='create-request',
                provider_event_id=idempotency_key, occurred_at=timezone.now())
    response = adapter.create_shipment(shipment)
    with transaction.atomic():
        Order.objects.select_for_update().get(pk=order.pk)
        shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
        if not response.ok:
            shipment.status = 'issue' if response.safe.get('ambiguous') else 'cancelled'
            shipment.save(update_fields=['status', 'updated_at'])
            record_tracking(shipment, 'creation_unconfirmed' if response.safe.get('ambiguous') else 'creation_failed',
                detail=response.error, event_id=f'create-result-{shipment.public_id}')
        else:
            shipment.external_ref, shipment.tracking = response.external_ref, response.tracking
            shipment.label_ref = response.label_url
            shipment.status = response.state if response.state in Shipment.Status.values else 'preparing'
            shipment.save(update_fields=['external_ref', 'tracking', 'label_ref', 'status', 'updated_at'])
            OrderEvent.objects.create(order=order, field='shipment', to_value=f'envío-{shipment.pk}',
                note=f'Envío {shipment.public_id} creado ({provider}, {len(lines)} línea/s)', by=user)
    if not response.ok:
        raise commerce.CartError(response.error)
    return shipment


def mark_status(shipment, status, user=None, note='', event_id='', occurred_at=None):
    if status not in Shipment.Status.values:
        raise commerce.CartError('Estado de envío desconocido.')
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=shipment.order_id)
        locked = Shipment.objects.select_for_update().get(pk=shipment.pk)
        current = locked.status
        if status == 'cancelled' and was_dispatched(locked):
            raise commerce.CartError('El envío ya salió: registrá devolución o incidencia; no puede cancelarse como no despachado.')
        if event_id:
            _, created = ShipmentEvent.objects.get_or_create(shipment=locked, provider_event_id=event_id,
                code=status, defaults={'occurred_at': occurred_at or timezone.now(), 'detail': note[:200]})
            if not created:
                return locked, False
        if current in ('returned', 'cancelled') or (current == 'delivered' and status != 'returned') or current == status:
            return locked, False
        if current in STATUS_ORDER and status in STATUS_ORDER and STATUS_ORDER.index(status) < STATUS_ORDER.index(current):
            return locked, False
        if status in ('picked_up', 'in_transit', 'delivered') and (order.status == 'cancelled' or order.stock_restored_at):
            raise commerce.CartError('No se puede despachar un pedido cancelado o sin reserva.')
        locked.status = status
        locked.save(update_fields=['status', 'updated_at'])
        if not event_id:
            record_tracking(locked, status, detail=note, event_id=f'local-{locked.pk}-{status}')
        OrderEvent.objects.create(order=order, field='shipment', from_value=f'{locked.pk}:{current}',
            to_value=f'{locked.pk}:{status}', note=note[:200], by=user)
    return locked, True


def record_tracking(shipment, code, detail='', event_id='', occurred_at=None):
    return ShipmentEvent.objects.get_or_create(shipment=shipment,
        provider_event_id=event_id or f'local-{code}-{detail[:20]}', code=code,
        defaults={'occurred_at': occurred_at or timezone.now(), 'detail': detail[:200]})


def reconcile_before_retry(shipment, user=None):
    response = adapter_for(shipment.provider).track(shipment)
    if not response.ok:
        return shipment, None
    if response.state and response.state != shipment.status:
        shipment, _ = mark_status(shipment, response.state, user=user, note='Reconciliación tras timeout')
    return shipment, response.state
