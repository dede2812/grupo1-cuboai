"""Cobros con intención durable, estados validados y efectos atómicos."""
import hashlib
from decimal import Decimal, InvalidOperation
from django.db import transaction
from . import services_commerce as commerce
from .models import Order, PaymentAttempt, PaymentEvent
from .payments.fake import FakeAdapter
from .payments.manual import ManualAdapter
from .payments.paypal import PayPalAdapter
from .payments.btcpay import BTCPayAdapter
from .payments.wompi import WompiAdapter

ADAPTERS = {a.key: a for a in (FakeAdapter(), ManualAdapter(), PayPalAdapter(), BTCPayAdapter(), WompiAdapter())}
TERMINAL = {'cancelled', 'expired', 'failed'}
FINANCIAL = {'captured', 'refund_pending', 'partially_refunded', 'refunded', 'disputed'}


def adapter_for(provider):
    if provider not in ADAPTERS:
        raise commerce.CartError('Método de pago no disponible.')
    return ADAPTERS[provider]


def _amount(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount != amount.quantize(Decimal('0.01')):
            raise InvalidOperation
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise commerce.CartError('Importe de pago inválido.')


def create_attempt(order, provider, idempotency_key, environment='test', account_ref=''):
    adapter = adapter_for(provider)
    if order.payment_method == 'bitcoin' and provider not in {'bitcoin', 'btcpay', 'manual', 'fake'}:
        raise commerce.CartError('El descuento Bitcoin requiere pagar con ese método; generá un nuevo pedido para cambiarlo.')
    if not idempotency_key or len(idempotency_key) > 64:
        raise commerce.CartError('Clave de idempotencia inválida.')
    if environment not in ('test', 'live') or (provider == 'fake' and environment != 'test'):
        raise commerce.CartError('Entorno de pago inválido.')
    if environment == 'live' and (order.store.is_demo or order.store.status != 'active'):
        raise commerce.CartError('Una tienda de demostración o inactiva no puede cobrar dinero real.')
    if order.total <= 0 or order.shipping_amount is None:
        raise commerce.CartError('El pedido necesita un total definitivo positivo antes de cobrar.')
    if hasattr(adapter, 'configuration'):
        config = adapter.configuration(order.store)
        if not config:
            raise commerce.CartError('Proveedor no configurado para esta tienda.')
        account_ref = account_ref or config.get('ACCOUNT_REF', '')
        if environment != config.get('ENVIRONMENT', 'test') or not account_ref or account_ref != config.get('ACCOUNT_REF'):
            raise commerce.CartError('Cuenta o entorno no coinciden con la tienda.')
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        existing = PaymentAttempt.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if (existing.order_id, existing.provider, existing.environment, existing.account_ref) != (order.pk, provider, environment, account_ref):
                raise commerce.CartError('La clave ya pertenece a otra operación.')
            return existing, None
        if order.status == 'cancelled' or order.stock_restored_at or order.payment_status != 'pending':
            raise commerce.CartError('El pedido no admite un nuevo cobro.')
        if order.payment_attempts.exclude(state__in=TERMINAL).exists():
            raise commerce.CartError('Ya existe un pago activo; consultá su estado antes de reintentar.')
        attempt = PaymentAttempt.objects.create(idempotency_key=idempotency_key, order=order,
            provider=provider, amount=order.total, currency=order.currency,
            environment=environment, account_ref=account_ref)
    # La intención se confirma ANTES del HTTP; no repetir automáticamente un POST ambiguo.
    response = adapter.create_payment(attempt)
    with transaction.atomic():
        Order.objects.select_for_update().get(pk=attempt.order_id)
        attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
        if not response.ok:
            attempt.state = 'pending' if response.safe.get('ambiguous') else 'failed'
            attempt.provider_state = 'creation_unconfirmed' if response.safe.get('ambiguous') else 'creation_failed'
            attempt.safe_payload = {'creation_error': response.error[:200]}
            attempt.save()
            return attempt, response.error
        attempt.external_ref, attempt.redirect_url = response.external_ref, response.redirect_url
        attempt.qr_payload, attempt.provider_state = response.qr_payload, response.provider_state
        attempt.safe_payload = response.safe
        error = _validate_response(attempt, response)
        if error:
            attempt.state = 'pending'
            attempt.provider_state = 'creation_unconfirmed'
            attempt.safe_payload = {'creation_error': error}
            attempt.save()
            return attempt, error
        attempt.save()
        attempt, _ = apply_provider_state(attempt, response.state or 'pending')
    return attempt, None


def apply_provider_state(attempt, new_state, provider_state='', event_id='', user=None, refunded_amount=None):
    if new_state not in PaymentAttempt.State.values:
        raise commerce.CartError('Estado de pago desconocido.')
    with transaction.atomic():
        Order.objects.select_for_update().get(pk=attempt.order_id)
        locked = PaymentAttempt.objects.select_for_update().select_related('order').get(pk=attempt.pk)
        if event_id:
            _, created = PaymentEvent.objects.get_or_create(attempt=locked,
                provider_event_id=event_id[:120], kind='provider', defaults={'payload': {'state': new_state}})
            if not created:
                return locked, False
        if locked.state in {'refunded', 'disputed'} and new_state != locked.state:
            return locked, False
        if locked.state in FINANCIAL and new_state not in FINANCIAL:
            return locked, False
        if locked.state in {'partially_refunded', 'refund_pending'} and new_state == 'captured':
            return locked, False
        if locked.state in TERMINAL and new_state not in {'captured', 'refunded', 'disputed'}:
            return locked, False
        if new_state == 'captured':
            if locked.order.status == 'cancelled' or locked.order.stock_restored_at:
                raise commerce.CartError('Pago tardío: requiere conciliación y devolución; la reserva fue liberada.')
            commerce.apply_transition(locked.order, 'payment_status', 'paid', user=user,
                note=f'Cobro confirmado ({locked.provider} {locked.external_ref})')
            locked.captured_amount = locked.amount
        if new_state in {'refunded', 'partially_refunded', 'disputed'}:
            if not locked.captured_amount:
                raise commerce.CartError('No se puede devolver o disputar un cobro sin confirmar.')
            if new_state != 'disputed':
                total = (_amount(refunded_amount) if refunded_amount is not None else
                    locked.captured_amount if new_state == 'refunded' else locked.refunded_amount)
                if total <= 0 or total > locked.captured_amount or total < locked.refunded_amount:
                    raise commerce.CartError('Importe acumulado de reembolso inválido.')
                if new_state == 'partially_refunded' and total >= locked.captured_amount:
                    raise commerce.CartError('El reembolso parcial debe ser inferior al cobro.')
                if new_state == 'refunded' and total != locked.captured_amount:
                    raise commerce.CartError('Un reembolso total debe cubrir todo el cobro.')
                locked.refunded_amount = total
            commerce.apply_transition(locked.order, 'payment_status', new_state, user=user,
                note=f'Reportado por {locked.provider} ({locked.external_ref})', refund_amount=locked.refunded_amount)
        changed = locked.state != new_state
        locked.state = new_state
        if provider_state:
            locked.provider_state = provider_state[:60]
        locked.save(update_fields=['state', 'provider_state', 'captured_amount', 'refunded_amount', 'updated_at'])
        return locked, changed


def _validate_response(attempt, response):
    if response.provider != attempt.provider or response.external_ref != attempt.external_ref:
        return 'referencia o proveedor no coinciden'
    if attempt.provider == 'manual':
        return None
    try:
        if _amount(response.amount) != attempt.amount or response.currency != attempt.currency:
            return 'monto o moneda no coinciden'
    except commerce.CartError:
        return 'monto o moneda no coinciden'
    if attempt.provider != 'fake':
        if response.safe.get('order_id') != str(attempt.order.public_id):
            return 'pedido no coincide'
        if response.safe.get('account_ref') != attempt.account_ref:
            return 'cuenta no coincide'
    return None


def verify_and_apply_notification(provider, headers, raw_body, parsed):
    adapter = adapter_for(provider)
    if not isinstance(parsed, dict):
        return None, 'cuerpo inválido'
    if hasattr(adapter, 'notification_reference'):
        try:
            reference = adapter.notification_reference(parsed)
        except (AttributeError, TypeError, ValueError):
            return None, 'cuerpo inválido'
        if not reference:
            return None, 'referencia desconocida'
        attempt = PaymentAttempt.objects.filter(external_ref=reference, provider=provider).first()
        if not attempt:
            return None, 'referencia desconocida'
        if not getattr(adapter, 'notification_requires_lookup', False) and not adapter.verify_notification(headers, raw_body, attempt=attempt):
            return None, 'firma inválida'
        return reconcile_attempt(attempt)
    if not adapter.verify_notification(headers, raw_body):
        return None, 'firma inválida'
    attempt = PaymentAttempt.objects.filter(external_ref=str(parsed.get('external_ref') or ''), provider=provider).first()
    if attempt is None:
        return None, 'referencia desconocida'
    try:
        if _amount(parsed.get('amount')) != attempt.amount or parsed.get('currency', attempt.currency) != attempt.currency:
            return None, 'monto o moneda no coinciden'
    except commerce.CartError:
        return None, 'monto o moneda no coinciden'
    return attempt, None


def reconcile_attempt(attempt, user=None):
    response = adapter_for(attempt.provider).get_payment(attempt)
    if not response.ok:
        return attempt, response.error
    error = _validate_response(attempt, response)
    if error:
        return attempt, error
    with transaction.atomic():
        Order.objects.select_for_update().get(pk=attempt.order_id)
        attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
        attempt.safe_payload = {**attempt.safe_payload, **response.safe}
        attempt.save(update_fields=['safe_payload', 'updated_at'])
        return apply_provider_state(attempt, response.state, response.provider_state,
            user=user, refunded_amount=response.safe.get('refunded_amount'))[0], None


def capture_attempt(attempt, user=None):
    """Captura con referencia idempotente del proveedor y validación del resultado."""
    attempt, error = reconcile_attempt(attempt, user=user)
    if error or attempt.state == 'captured':
        return attempt, error
    if attempt.state != 'authorized':
        raise commerce.CartError('El comprador todavía no autorizó este pago.')
    response = adapter_for(attempt.provider).capture(attempt)
    if not response.ok:
        return attempt, response.error
    error = _validate_response(attempt, response)
    if error:
        return attempt, error
    return reconcile_attempt(attempt, user=user)


def checkout_options(order):
    """Sólo cuentas configuradas para este negocio y entorno; nunca el fake."""
    if order.payment_status != 'pending' or order.status == 'cancelled' or order.stock_restored_at:
        return []
    return configured_checkout_options(order.store, order.payment_method, order.currency)


def configured_checkout_options(store, payment_method='manual', currency=None):
    """Mismos métodos y restricciones para checkout previo y pedido creado."""
    options = []
    for provider in ('wompi', 'paypal', 'btcpay'):
        if payment_method == 'bitcoin' and provider != 'btcpay':
            continue
        adapter = adapter_for(provider)
        config = adapter.configuration(store)
        if config and config.get('ENVIRONMENT') == 'live' and (store.is_demo or store.status != 'active'):
            continue
        if config and (provider != 'wompi' or (currency or store.currency) == 'USD'):
            options.append({'provider': provider, 'label': adapter.label,
                            'test': config.get('ENVIRONMENT', 'test') == 'test'})
    return options


def refund_attempt(attempt, amount=None, note='', user=None, member=None, idempotency_key=None):
    if member is not None and (member.merchant_id != attempt.order.store.merchant_id or not commerce.member_can(member, 'payments')):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('Tu rol no permite reembolsar este pedido.')
    key = idempotency_key or hashlib.sha256(f'{attempt.pk}:{amount}:{note}'.encode()).hexdigest()
    if len(key) > 120:
        raise commerce.CartError('Clave de reembolso inválida.')
    with transaction.atomic():
        Order.objects.select_for_update().get(pk=attempt.order_id)
        locked = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
        previous = locked.events.filter(kind='refund-request', provider_event_id=key).first()
        if previous:
            if amount is not None and _amount(amount) != _amount(previous.payload['amount']):
                raise commerce.CartError('La clave de reembolso pertenece a otro importe.')
            return locked
        if locked.state not in {'captured', 'partially_refunded'}:
            raise commerce.CartError('Sólo se reembolsa un cobro confirmado sin devolución pendiente.')
        remaining = locked.captured_amount - locked.refunded_amount
        amount = _amount(amount if amount is not None else remaining)
        if amount <= 0 or amount > remaining:
            raise commerce.CartError('El reembolso excede lo cobrado disponible.')
        prior_state = locked.state
        PaymentEvent.objects.create(attempt=locked, kind='refund-request', provider_event_id=key,
            payload={'amount': str(amount), 'target_total': str(locked.refunded_amount + amount),
                     'status': 'pending', 'note': note[:200]})
        locked.state = 'refund_pending'
        locked.safe_payload = {**locked.safe_payload, 'refund_request_key': key}
        locked.save(update_fields=['state', 'safe_payload', 'updated_at'])
    response = adapter_for(locked.provider).refund(locked, amount=amount, note=note)
    with transaction.atomic():
        Order.objects.select_for_update().get(pk=attempt.order_id)
        locked = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
        event = locked.events.get(kind='refund-request', provider_event_id=key)
        # Una consulta/webhook autenticado puede confirmar los fondos mientras
        # esperamos el HTTP. Esa evidencia prevalece incluso sobre un timeout
        # o error posterior: no volver a un estado anterior ni repetir el POST.
        confirmed = locked.refunded_amount >= _amount(event.payload['target_total'])
        if confirmed:
            event.payload = {**event.payload, 'status': 'completed'}
        elif not response.ok:
            event.payload = {**event.payload, 'status': 'unconfirmed' if response.safe.get('ambiguous') else 'failed'}
            if not response.safe.get('ambiguous') and locked.state == 'refund_pending':
                locked.state = prior_state
                locked.save(update_fields=['state', 'updated_at'])
        elif response.state == 'refund_pending':
            event.payload = {**event.payload, 'status': 'pending', 'external_ref': response.external_ref}
        elif response.state in {'refunded', 'partially_refunded'}:
            # El webhook puede haber confirmado este mismo reembolso mientras
            # esperamos el HTTP. El objetivo acumulado evita sumarlo dos veces.
            total = max(locked.refunded_amount, _amount(event.payload['target_total']))
            target = 'refunded' if total == locked.captured_amount else 'partially_refunded'
            locked, _ = apply_provider_state(locked, target, user=user, refunded_amount=total)
            event.payload = {**event.payload, 'status': 'completed', 'external_ref': response.external_ref}
        else:
            raise commerce.CartError('Respuesta de reembolso desconocida; requiere conciliación.')
        event.save(update_fields=['payload'])
    if not response.ok and not confirmed:
        raise commerce.CartError(response.error)
    return locked


def group_payment_status(orders):
    orders = list(orders)
    for order in orders:
        order.refresh_from_db()
    return {'parts': [{'order': o.reference, 'total': str(o.total), 'payment_status': o.payment_status} for o in orders],
        'all_paid': bool(orders) and all(o.payment_status == 'paid' for o in orders), 'count': len(orders)}
