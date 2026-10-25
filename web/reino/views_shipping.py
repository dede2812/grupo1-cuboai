"""Despachos manuales por cantidades históricas y capacidad de logística."""
import uuid

from django.core import signing
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import services_commerce as commerce, services_shipping as shipping
from .models import Order, OrderEvent, Shipment
from .views_merchant import merchant_view, require_capability

SALT = 'reino-manual-shipment'
MANUAL_STATES = ('preparing', 'ready', 'picked_up', 'in_transit', 'delivered', 'issue', 'returned', 'cancelled')


def _order(store, public_id):
    return get_object_or_404(Order.objects.prefetch_related('items'), store=store, public_id=public_id)


def _back(store, order):
    return redirect('reino_merchant_shipments', slug=store.slug, public_id=order.public_id)


@merchant_view
@require_capability('fulfilment')
@require_GET
def shipments(request, store, public_id):
    order = _order(store, public_id)
    rows = shipping.shippable_lines(order)
    token = signing.dumps({'order': str(order.public_id), 'user': request.user.pk, 'key': uuid.uuid4().hex}, salt=SALT)
    states = [(value, label) for value, label in Shipment.Status.choices if value in MANUAL_STATES]
    response = render(request, 'reino/merchant_shipments.html', {
        'store': store, 'order': order, 'lines': rows, 'shipments': order.shipments.prefetch_related('events'),
        'action_token': token, 'states': states,
        'can_create': bool(rows) and order.status != 'cancelled' and not order.stock_restored_at,
    })
    response['Cache-Control'] = 'private, no-store'
    return response


@merchant_view
@require_capability('fulfilment')
@require_POST
def shipment_create(request, store, public_id):
    order = _order(store, public_id)
    try:
        payload = signing.loads(request.POST.get('action_token', ''), salt=SALT, max_age=86400)
        if not isinstance(payload, dict) or payload.get('order') != str(order.public_id) or payload.get('user') != request.user.pk:
            raise commerce.CartError('La autorización de despacho no corresponde a este pedido.')
        lines = []
        for name in request.POST:
            if not name.startswith('quantity_'):
                continue
            if len(request.POST.getlist(name)) != 1:
                raise commerce.CartError('La cantidad de cada línea debe enviarse una sola vez.')
            item_id, quantity = int(name[9:]), int(request.POST[name] or '0')
            if quantity < 0:
                raise commerce.CartError('La cantidad no puede ser negativa.')
            if quantity:
                lines.append({'order_item_id': item_id, 'quantity': quantity})
        if order.delivery_mode not in ('local', 'pickup'):
            raise commerce.CartError('Este pedido no tiene una modalidad de despacho físico disponible.')
        shipment = shipping.create_shipment(order, lines=lines, provider='manual',
            service=order.delivery_mode, user=request.user, idempotency_key=payload['key'],
            address={'address': order.address, 'city': order.city, 'zone': order.zone})
        request.session['reino_flash'] = f'Despacho registrado: {shipment.public_id}. Estado: {shipment.get_status_display()}.'
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        request.session['reino_flash'] = 'Formulario vencido o inválido. Revisá las cantidades y volvé a intentar.'
    except commerce.CartError as exc:
        request.session['reino_flash'] = str(exc)
    return _back(store, order)


@merchant_view
@require_capability('fulfilment')
@require_POST
def shipment_update(request, store, public_id, shipment_id):
    order = _order(store, public_id)
    shipment = get_object_or_404(Shipment, order=order, public_id=shipment_id, provider='manual')
    status, note = request.POST.get('status', ''), request.POST.get('note', '').strip()
    tracking = request.POST.get('tracking', '').strip()
    try:
        if status not in MANUAL_STATES or len(tracking) > 120 or len(note) > 200:
            raise commerce.CartError('Estado, referencia o evidencia inválidos.')
        if not note:
            raise commerce.CartError('Indicá la evidencia o el motivo del cambio.')
        with transaction.atomic():
            Order.objects.select_for_update().get(pk=order.pk)
            shipment = Shipment.objects.select_for_update().get(pk=shipment.pk)
            shipment, changed = shipping.mark_status(shipment, status, user=request.user, note=note)
            tracking_changed = shipment.tracking != tracking and (changed or status == shipment.status)
            if tracking_changed:
                shipment.tracking = tracking
                shipment.save(update_fields=['tracking', 'updated_at'])
                OrderEvent.objects.create(order=order, field='shipment_tracking',
                    to_value=str(shipment.pk), note=note, by=request.user)
        request.session['reino_flash'] = 'Seguimiento actualizado.' if changed or tracking_changed else 'El despacho ya tiene ese estado o no admite ese cambio.'
    except commerce.CartError as exc:
        request.session['reino_flash'] = str(exc)
    return _back(store, order)
