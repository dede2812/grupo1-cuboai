"""Analítica con definición y deduplicación (§21).

Eventos con nombre registrado; `request_id` único evita doble conteo por
reintentos. Pedido creado ≠ pedido pagado ≠ dinero cobrado: son eventos
distintos. Los datos de demo quedan aislados por tienda (is_demo).
"""

import logging
import hashlib
import uuid

from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

log = logging.getLogger("reino.analytics")

from .models import AnalyticsEvent

EVENTS = {
    "search", "advisor_query", "advisor_no_match", "promotion_applied",
    "product_view", "variant_selected", "fit_opened",
    "looklab_started", "looklab_completed",
    "compare_selected", "compare_opened",
    "saved_item", "advisor_action_proposed", "advisor_action_confirmed",
    "cart_added", "checkout_started", "checkout_reviewed",
    "order_placed", "payment_verified", "order_cancelled", "refund_recorded",
}


def track_once(name, *, store=None, session_key="", key="", **payload):
    """Server-scoped deduplication; browser keys cannot suppress another tenant."""
    scope = f"{getattr(store, 'pk', '')}:{session_key}:{name}:{key}"
    request_id = hashlib.sha256(scope.encode()).hexdigest()
    return track(name, store=store, session_key=session_key, request_id=request_id, **payload)


def track_daily(name, *, key="", **kwargs):
    """Deduplicate refreshes without suppressing future visits of an account."""
    return track_once(name, key=f"{timezone.localdate()}:{key}", **kwargs)


def track(name, store=None, session_key="", request_id=None, **payload):
    """Registra un evento; duplicado por request_id => no-op (dedupe)."""
    if name not in EVENTS:
        raise ValueError(f"Evento no definido: {name}")
    request_id = request_id or uuid.uuid4().hex[:24]
    try:
        # Savepoint propio: si la restricción única salta dentro de una
        # transacción envolvente (tests, checkout), solo se revierte este
        # punto y la transacción externa sigue sana.
        with transaction.atomic():
            AnalyticsEvent.objects.create(
                store=store, session_key=session_key or "", name=name,
                request_id=request_id, payload=payload,
            )
        return True
    except IntegrityError:
        return False  # reintento: ya contado
    except DatabaseError as exc:
        # La telemetría NUNCA convierte una compra confirmada en un 500 (F02):
        # se registra el fallo para revisión y el flujo de negocio continúa.
        # No es un `except Exception: pass`: el error queda en el log con
        # nombre de evento y la excepción concreta.
        log.warning("analytics track falló (evento=%s): %s", name, exc)
        return False


def funnel(store, since=None):
    """Conteos simples con denominador explícito (sesiones con actividad)."""
    qs = AnalyticsEvent.objects.filter(store=store)
    if since:
        qs = qs.filter(created_at__gte=since)
    counts = {}
    for (name,) in qs.values_list("name").distinct():
        counts[name] = qs.filter(name=name).count()
    counts["sessions"] = qs.values("session_key").distinct().count()
    return counts
