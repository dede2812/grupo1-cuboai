"""HTTP de cobros (§11.4): webhook autenticado + consulta de estado.

El retorno del navegador NUNCA confirma un pago: sólo la notificación
verificada o la consulta autenticada lo hacen (A45/A46/A47).
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import services_payments as pay
from .services_commerce import CartError


@csrf_exempt  # la autenticidad la da la FIRMA del proveedor, no el CSRF
@require_POST
def payment_webhook(request, provider):
    """Recibe notificaciones: verifica firma, pedido, referencia, importe y
    moneda ANTES de tocar estados; duplicadas son no-op (200 siempre que se
    procesan, para que el proveedor no reintente en loop)."""
    if provider in {"fake", "manual"}:
        return JsonResponse({"ok": False, "error": "proveedor no disponible"}, status=404)
    if len(request.body) > 262144:
        return JsonResponse({"ok": False, "error": "cuerpo demasiado grande"}, status=413)
    try:
        parsed = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "cuerpo inválido"}, status=400)
    try:
        attempt, err = pay.verify_and_apply_notification(
            provider, dict(request.headers), request.body, parsed)
    except CartError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=422)
    if err:
        # Firma/monto inválidos: NO cambian el estado financiero (A45).
        return JsonResponse({"ok": False, "error": err}, status=422)
    # Los adaptadores reales consultan la API autenticada; jamás confiar en
    # un campo arbitrario `state` del cuerpo HTTP.
    return JsonResponse({"ok": True, "state": attempt.state})

# Inicio y consulta del pago: acceso privado por pedido, POST con CSRF.
import hmac
from urllib.parse import urlsplit

from django.core import signing
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from . import tenancy
from .models import Order, PaymentAttempt


def _flash(request, text):
    request.session['reino_flash'] = text


def _private_order(request, slug, public_id):
    store = tenancy.get_store(slug)
    request.reino_store = store
    order = get_object_or_404(Order.objects.select_related('store', 'cart'), store=store, public_id=public_id)
    owns = bool(order.cart and order.cart.session_key == tenancy.owner_key(request))
    token = request.POST.get('order_token', '')
    if not owns and not hmac.compare_digest(str(order.access_token).encode(), token.encode()):
        raise Http404
    return order


def _order_redirect(order):
    return redirect('reino_order_guest', slug=order.store.slug, public_id=order.public_id, token=order.access_token)


@require_POST
def payment_start(request, slug, public_id, provider):
    order = _private_order(request, slug, public_id)
    options = {row['provider'] for row in pay.checkout_options(order)}
    if provider not in options:
        raise Http404
    adapter = pay.adapter_for(provider)
    config = adapter.configuration(order.store)
    try:
        # A failed definitive request may be retried with a new server key. A
        # pending/ambiguous request must be reconciled, even across providers.
        import uuid
        active = order.payment_attempts.exclude(state__in=pay.TERMINAL).first()
        if active:
            attempt, error = active, None
        else:
            attempt, error = pay.create_attempt(order, provider, str(uuid.uuid4()),
                environment=config.get('ENVIRONMENT', 'test'), account_ref=config['ACCOUNT_REF'])
        if error:
            _flash(request, error)
            return _order_redirect(order)
        allowed = request.session.get('reino_payment_attempts', [])
        if str(attempt.public_id) not in allowed:
            request.session['reino_payment_attempts'] = (allowed + [str(attempt.public_id)])[-20:]
        if attempt.provider != provider:
            _flash(request, 'Ya existe un pago activo. Comprobá su estado antes de cambiar de método.')
            return _order_redirect(order)
        target = urlsplit(attempt.redirect_url)
        if attempt.state == 'requires_action' and target.scheme == 'https' and target.hostname and not target.username:
            response = redirect(attempt.redirect_url)
            response['Referrer-Policy'] = 'no-referrer'
            return response
        _flash(request, 'El pago está pendiente de confirmación. Consultá su estado antes de volver a pagar.')
    except CartError as exc:
        _flash(request, str(exc))
    return _order_redirect(order)


@require_POST
def payment_refresh(request, slug, public_id, attempt_id):
    order = _private_order(request, slug, public_id)
    attempt = get_object_or_404(PaymentAttempt, order=order, public_id=attempt_id)
    if attempt.provider in {'fake', 'manual'}:
        raise Http404
    try:
        if request.POST.get('action') == 'capture':
            attempt, error = pay.capture_attempt(attempt, user=request.user if request.user.is_authenticated else None)
        else:
            attempt, error = pay.reconcile_attempt(attempt)
        if error:
            _flash(request, error)
        else:
            _flash(request, 'Estado consultado con el proveedor: ' + attempt.get_state_display())
    except CartError as exc:
        _flash(request, str(exc))
    return _order_redirect(order)


def payment_return(request, provider):
    try:
        attempt_id = signing.loads(request.GET.get('state', ''), salt='reino-payment-return', max_age=7200)
    except signing.BadSignature:
        raise Http404
    if attempt_id not in request.session.get('reino_payment_attempts', []):
        raise Http404
    attempt = get_object_or_404(PaymentAttempt.objects.select_related('order__store'),
        public_id=attempt_id, provider=provider)
    if provider == 'paypal' and request.GET.get('token') != attempt.external_ref:
        raise Http404
    # Ningún parámetro success/paid del navegador confirma el pago. El botón
    # de consulta/captura del pedido usa POST y llama al proveedor autenticado.
    _flash(request, 'Regresaste del proveedor. Comprobá el pago para confirmar su estado.')
    response = _order_redirect(attempt.order)
    response['Referrer-Policy'] = 'no-referrer'
    return response
