"""Read-only business reporting over tenant-scoped, persisted commerce records.

Dates are order-created cohorts, valued at their current payment/refund state;
this is deliberately not a cash ledger. No guessed tax/refund allocation.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from itertools import combinations

from django.db.models import Count, Q, Sum
from django.db.models.functions import Lower
from django.utils import timezone

from .models import AnalyticsEvent, Order, OrderItem, Product, Variant

ZERO = Decimal("0.00")
VERIFIED = (Order.PaymentStatus.PAID, Order.PaymentStatus.PARTIALLY_REFUNDED,
            Order.PaymentStatus.REFUNDED)


@dataclass(frozen=True)
class ReportFilters:
    start: object
    end: object
    product_id: int | None = None
    category: str = ""
    status: str = ""
    bucket: str = "day"

    @property
    def days(self):
        return (self.end - self.start).days + 1

    def previous(self):
        return ReportFilters(self.start - timedelta(days=self.days),
                             self.start - timedelta(days=1), self.product_id,
                             self.category, self.status, self.bucket)

    @property
    def bounds(self):
        zone = timezone.get_current_timezone()
        return (timezone.make_aware(datetime.combine(self.start, time.min), zone),
                timezone.make_aware(datetime.combine(self.end + timedelta(days=1), time.min), zone))


def order_scope(store, filters):
    """Product/category select whole orders containing a matching line."""
    start, end = filters.bounds
    orders = Order.objects.filter(store=store, currency=store.currency,
                                  created_at__gte=start, created_at__lt=end)
    # One EXISTS-like subquery avoids multiplying order totals by its lines.
    if filters.product_id or filters.category:
        lines = OrderItem.objects.filter(order__store=store)
        if filters.product_id:
            lines = lines.filter(variant__product_id=filters.product_id)
        if filters.category:
            lines = lines.filter(variant__product__category=filters.category)
        orders = orders.filter(pk__in=lines.values("order_id"))
    if filters.status:
        orders = orders.filter(status=filters.status)
    return orders


def financial_summary(orders):
    """Only verified payments. Cumulative refunds are never added twice."""
    sums = orders.filter(payment_status__in=VERIFIED).aggregate(
        paid_orders=Count("pk"), gross=Sum("subtotal"), discounts=Sum("discount_amount"),
        shipping=Sum("shipping_amount"), charged=Sum("total"), refunds=Sum("refund_amount"),
        refunded_orders=Count("pk", filter=Q(refund_amount__gt=0)),
        missing_refunds=Count("pk", filter=Q(payment_status__in=("refunded", "partially_refunded"), refund_amount__isnull=True)),
        missing_shipping=Count("pk", filter=Q(shipping_amount__isnull=True)),
    )
    for key in ("gross", "discounts", "shipping", "charged", "refunds"):
        sums[key] = sums[key] or ZERO
    sums["net_receipts"] = None if sums["missing_refunds"] else sums["charged"] - sums["refunds"]
    if sums["missing_shipping"]:
        sums["shipping"] = None
    sums["merchandise"] = sums["gross"] - sums["discounts"]
    sums["average_order"] = (sums["charged"] / sums["paid_orders"] if sums["paid_orders"] else None)
    # A refund has no line/tax/shipping allocation in the current schema.
    sums["net_sales"] = sums["merchandise"] if not sums["refunds"] and not sums["missing_refunds"] else None
    sums["tax"] = None
    counts = orders.aggregate(
        orders=Count("pk"),
        confirmed_orders=Count("pk", filter=Q(status__in=("confirmed", "closed"))),
        cancelled_orders=Count("pk", filter=Q(status="cancelled")),
        pending_orders=Count("pk", filter=Q(payment_status__in=("pending", "requires_action"))),
        returned_orders=Count("pk", filter=Q(delivery_status="returned")),
        disputed_orders=Count("pk", filter=Q(payment_status="disputed")),
    )
    return {**sums, **counts}


def percent_change(current, previous):
    if current is None or previous is None or previous == 0:
        return None
    return (Decimal(current) - Decimal(previous)) / abs(Decimal(previous)) * 100


def _bucket(day, mode):
    if mode == "week":
        return day - timedelta(days=day.weekday())
    if mode == "month":
        return day.replace(day=1)
    return day


def _series(orders, filters):
    points = {}
    for offset in range(filters.days):
        key = _bucket(filters.start + timedelta(days=offset), filters.bucket)
        points.setdefault(key, {"label": key.isoformat(), "gross": ZERO,
                                "net": ZERO, "orders": 0})
    for row in orders.values("created_at", "subtotal", "total", "refund_amount", "payment_status").iterator():
        key = _bucket(timezone.localtime(row["created_at"]).date(), filters.bucket)
        point = points[key]
        point["orders"] += 1
        if row["payment_status"] in VERIFIED:
            point["gross"] += row["subtotal"]
            if row["payment_status"] in ("refunded", "partially_refunded") and row["refund_amount"] is None:
                point["net"] = None
            elif point["net"] is not None:
                point["net"] += row["total"] - (row["refund_amount"] or ZERO)
    return [{**p, "gross": float(p["gross"]), "net": float(p["net"]) if p["net"] is not None else None} for p in points.values()]


def _customer_metrics(store, paid, start):
    emails = set(paid.exclude(customer_email="").annotate(identity=Lower("customer_email"))
                 .values_list("identity", flat=True))
    earlier = set(Order.objects.filter(store=store, payment_status__in=VERIFIED,
                                       created_at__lt=start).annotate(identity=Lower("customer_email"))
                  .filter(identity__in=emails).values_list("identity", flat=True))
    # Returning means a verified order BEFORE this period, not just two today.
    return {"customers": len(emails), "new_customers": len(emails - earlier),
            "returning_customers": len(earlier),
            "repeat_rate": len(earlier) / len(emails) * 100 if emails else None}


def _events_report(store, filters, orders):
    start, end = filters.bounds
    events = AnalyticsEvent.objects.filter(store=store, created_at__gte=start, created_at__lt=end)
    counts = dict(events.values_list("name").annotate(n=Count("pk")))
    # Events are only complete at store scope. Never fake product attribution.
    is_full_scope = not (filters.product_id or filters.category or filters.status)
    sessions = defaultdict(set)
    if is_full_scope:
        for name, key in events.exclude(session_key="").values_list("name", "session_key").distinct():
            sessions[name].add(key)
    views = sessions["product_view"]
    cart = views & sessions["cart_added"]
    checkout = cart & sessions["checkout_started"]
    placed = checkout & sessions["order_placed"]
    # Require real cohort orders, rather than trusting a payment event payload.
    paid_sessions = set(orders.filter(payment_status__in=VERIFIED, cart__isnull=False)
                        .values_list("cart__session_key", flat=True))
    converted = placed & paid_sessions
    rows = [{"label": label, "count": len(keys)} for label, keys in (
        ("Vieron un producto", views), ("Añadieron a la bolsa", cart),
        ("Iniciaron checkout", checkout), ("Crearon un pedido", placed),
        ("Tienen pago verificado", converted))]
    max_count = len(views)
    for row in rows:
        row["percent"] = row["count"] / max_count * 100 if max_count else 0
    # Cart inactivity inside the period is observable, definitive abandonment is not.
    all_cart = sessions["cart_added"]
    return {"events": counts, "funnel": rows, "funnel_available": bool(views) and is_full_scope,
            "conversion": len(converted) / len(views) * 100 if views and is_full_scope else None,
            "uncompleted_carts": len(all_cart - sessions["order_placed"]) if all_cart else None,
            "uncompleted_cart_rate": len(all_cart - sessions["order_placed"]) / len(all_cart) * 100 if all_cart else None,
            "advisor_queries": counts.get("advisor_query", 0),
            "advisor_no_match": counts.get("advisor_no_match", 0),
            "advisor_confirmations": counts.get("advisor_action_confirmed", 0)}


def _ai_attribution(store, paid):
    """A confirmed cart action must precede order and its SKU must be bought."""
    order_rows = list(paid.filter(cart__isnull=False).values("pk", "cart__public_id", "created_at", "total", "refund_amount", "payment_status"))
    if not order_rows:
        return {"ai_orders": 0, "ai_net_receipts": ZERO}
    by_cart = {str(o["cart__public_id"]): o for o in order_rows}
    variants = defaultdict(set)
    for oid, vid in OrderItem.objects.filter(order_id__in=[o["pk"] for o in order_rows]).values_list("order_id", "variant__public_id"):
        if vid:
            variants[oid].add(str(vid))
    matched = set()
    for event in AnalyticsEvent.objects.filter(store=store, name="advisor_action_confirmed",
                                               created_at__lte=max(o["created_at"] for o in order_rows)).only("payload", "created_at").iterator():
        payload = event.payload if isinstance(event.payload, dict) else {}
        order = by_cart.get(str(payload.get("cart", "")))
        if (order and payload.get("action") == "add_to_cart" and event.created_at <= order["created_at"]
                and str(payload.get("variant")) in variants[order["pk"]]):
            matched.add(order["pk"])
    missing = any(o["pk"] in matched and o["payment_status"] in ("refunded", "partially_refunded")
                  and o["refund_amount"] is None for o in order_rows)
    return {"ai_orders": len(matched), "ai_net_receipts": None if missing else sum(
        (o["total"] - (o["refund_amount"] or ZERO) for o in order_rows if o["pk"] in matched), ZERO)}


def build_report(store, filters):
    orders = order_scope(store, filters)
    paid = orders.filter(payment_status__in=VERIFIED)
    previous_orders = order_scope(store, filters.previous())
    current = financial_summary(orders)
    previous = financial_summary(previous_orders)
    changes = {key: percent_change(current[key], previous[key]) for key in
               ("net_receipts", "gross", "paid_orders", "average_order", "confirmed_orders")}
    lines = OrderItem.objects.filter(order__in=paid)
    # Breakdown is line gross value, never an invented allocation of refunds.
    top_products = list(lines.values("variant__product_id", "title").annotate(
        units=Sum("quantity"), revenue=Sum("subtotal")).order_by("-revenue", "title")[:8])
    categories = list(lines.values("variant__product__category").annotate(
        units=Sum("quantity"), revenue=Sum("subtotal")).order_by("-revenue"))
    maximum = max([c["revenue"] for c in categories], default=ZERO)
    for row in categories:
        row["label"] = row["variant__product__category"] or "Sin categoría disponible"
        row["percent"] = float(row["revenue"] / maximum * 100) if maximum else 0
    products = Product.objects.filter(store=store, status="published")
    if filters.product_id:
        products = products.filter(pk=filters.product_id)
    if filters.category:
        products = products.filter(category=filters.category)
    low_stock = Variant.objects.filter(product__in=products, is_active=True,
                                       product__offer_type="physical", stock__lte=2).select_related("product")
    slow_products = list(products.exclude(pk__in=lines.filter(variant__isnull=False).values("variant__product_id")).order_by("short_title")[:8])
    # Frequent pairs use distinct product IDs; variants are not separate products.
    basket_products = defaultdict(set)
    titles = {}
    for oid, pid, title in lines.values_list("order_id", "variant__product_id", "title"):
        if pid:
            basket_products[oid].add(pid)
            titles[pid] = title
    pairs = Counter()
    for product_ids in basket_products.values():
        # Cap pair enumeration for unusually large wholesale baskets.
        if len(product_ids) <= 50:
            pairs.update(combinations(sorted(product_ids), 2))
    pair_rows = [{"first": titles[a], "second": titles[b], "orders": count}
                 for (a, b), count in pairs.most_common(5) if count >= 2]
    promotions = list(paid.filter(discount_amount__gt=0).values("discount_note").annotate(
        orders=Count("pk"), discounts=Sum("discount_amount"), charged=Sum("total")).order_by("-orders"))
    events = _events_report(store, filters, orders)
    attribution = _ai_attribution(store, paid)
    customer_metrics = _customer_metrics(store, paid, filters.bounds[0])
    insights = []
    delta = changes["net_receipts"]
    if delta is not None:
        insights.append(f"El cobro neto {'subió' if delta >= 0 else 'bajó'} {abs(delta):.1f}% frente al período anterior de {filters.days} días.")
    critical_count = low_stock.count()
    if critical_count:
        insights.append(f"{critical_count} variantes físicas tienen 2 unidades o menos en inventario. Revisá existencias antes de promoverlas.")
    if events["advisor_no_match"]:
        insights.append(f"El asesor registró {events['advisor_no_match']} consultas sin coincidencias. Revisá cobertura del catálogo; estas consultas no prueban demanda de compra.")
    if current["refunds"]:
        insights.append("Hay reembolsos en esta cohorte. El cobro neto ya los descuenta; su reparto entre productos y envío no está disponible.")
    if current["missing_refunds"]:
        insights.append(f"{current['missing_refunds']} pedidos reembolsados no tienen importe registrado. El cobro neto queda sin calcular hasta completar esa evidencia.")
    return {"current": current, "previous": previous, "changes": changes,
            "series": _series(orders, filters), "previous_series": _series(previous_orders, filters.previous()),
            "top_products": top_products, "categories": categories, "low_stock": list(low_stock[:8]),
            "low_stock_count": critical_count, "slow_products": slow_products, "pairs": pair_rows,
            "promotions": promotions, "insights": insights, **customer_metrics, **events, **attribution,
            "other_currency_orders": Order.objects.filter(store=store, created_at__gte=filters.bounds[0],
                 created_at__lt=filters.bounds[1]).exclude(currency=store.currency).count()}
