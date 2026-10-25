from functools import wraps

from django.contrib.auth.views import LoginView, redirect_to_login
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .forms import CostForm
from .models import Order

PAGE_SIZE = 25


class PanelLoginView(LoginView):
    """Use the same database-backed quota as the customer login endpoint."""

    def post(self, request, *args, **kwargs):
        from reino.views_auth import _allow_attempt
        if not _allow_attempt(request, "login", 20):
            # An unbound form avoids checking credentials after quota exhaustion.
            form = self.get_form_class()(request=request)
            return self.render_to_response(
                self.get_context_data(form=form, rate_limited=True), status=429)
        return super().post(request, *args, **kwargs)


def _int_or_none(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not (user.is_active and user.is_staff):
            return HttpResponseForbidden("Staff access only.")
        # Merchant onboarding must not grant access to the historical WK ledger.
        from reino.models import MerchantMember
        # Retain inactive memberships in this check: revoking a merchant role
        # must never turn that account into an unrestricted legacy staff user.
        memberships = MerchantMember.objects.filter(user=user)
        if not user.is_superuser and memberships.exists() and not memberships.filter(
            merchant__stores__slug="wiener-kingdom", role="owner", is_active=True
        ).exists():
            return HttpResponseForbidden("No tenés permiso para el panel histórico de Wiener Kingdom.")
        return view(request, *args, **kwargs)

    return wrapper


@staff_required
def orders(request):
    qs = Order.objects.order_by("-created_at", "-pk")
    q = request.GET.get("q", "").strip()
    if q:
        cond = (
            Q(customer_name__icontains=q)
            | Q(customer_email__icontains=q)
            | Q(snapshot__product__name__icontains=q)
            | Q(lines__product_name__icontains=q)
        )
        digits = q.upper().removeprefix("WK-").lstrip("0")
        if digits.isdigit():
            cond |= Q(pk=int(digits))
        qs = qs.filter(cond)
    stage = request.GET.get("stage", "")
    stage_q = services.stage_filter(stage) if stage else None
    if stage_q is not None:
        qs = qs.filter(stage_q)
    else:
        stage = ""
    filters = {}
    for field, choices in (
        ("status", Order.Status),
        ("payment_status", Order.PaymentStatus),
        ("production_status", Order.ProductionStatus),
        ("shipping_status", Order.ShippingStatus),
    ):
        value = request.GET.get(field, "")
        if value in choices.values:
            qs = qs.filter(**{field: value})
            filters[field] = value
    rows = list(qs.distinct()[:PAGE_SIZE])
    for row in rows:
        row.ready_flag = services.order_readiness(row)["ready"]
        names = [l.product_name for l in row.lines.all()]
        if not names:
            names = [(row.snapshot or {}).get("product", {}).get("name", "")]
        row.product_summary = names[0] + (f" + {len(names) - 1} more" if len(names) > 1 else "")
        if row.quantity > 1 and len(names) == 1:
            row.product_summary += f" × {row.quantity}"
    return render(
        request,
        "tienda/panel_orders.html",
        {
            "orders": rows,
            "total_count": qs.distinct().count(),
            "page_size": PAGE_SIZE,
            "stages": services.stage_counts(),
            "stage": stage,
            "q": q,
            "filters": filters,
            "status_choices": Order.Status.choices,
            "payment_choices": Order.PaymentStatus.choices,
            "production_choices": Order.ProductionStatus.choices,
            "shipping_choices": Order.ShippingStatus.choices,
        },
    )


@staff_required
def order_sheet(request, public_id):
    """Ficha de taller: datos confirmados del pedido (solo personal)."""
    order = get_object_or_404(Order, public_id=public_id)
    snap = order.snapshot or {}
    readiness = services.order_readiness(order)
    return render(
        request,
        "tienda/panel_order_sheet.html",
        {
            "order": order,
            "snap": snap,
            "cost": services.cost_summary(order),
            "readiness": readiness,
            "lines": readiness["lines"],
            "events": order.events.select_related("by"),
        },
    )


@staff_required
def payments(request):
    from .models import ProductPaymentRule

    if request.method == "POST":
        services.update_payment_rules(request.POST)
        return redirect("panel_payments")
    flags = {r.product_slug: r.bitcoin_discount_eligible for r in ProductPaymentRule.objects.all()}
    products = [
        {"slug": slug, "name": item["nombre"], "eligible": flags.get(slug, True)}
        for slug, item in services.PRODUCTOS.items()
    ]
    return render(request, "tienda/panel_payments.html", {"products": products})


@staff_required
def measurements(request):
    from .models import ProductMeasurement, SizeRange

    errors = []
    status = 200
    if request.method == "POST":
        try:
            services.update_measurement_config(request.POST, user=request.user)
        except services.CostError as exc:
            errors, status = exc.messages, 400
        else:
            return redirect("panel_measurements")
    flags = {m.product_slug: m for m in ProductMeasurement.objects.all()}
    products = [
        {
            "slug": slug,
            "name": item["nombre"],
            "requires_neck": getattr(flags.get(slug), "requires_neck", False),
            "is_validated": getattr(flags.get(slug), "is_validated", False),
        }
        for slug, item in services.PRODUCTOS.items()
    ]
    return render(
        request,
        "tienda/panel_measurements.html",
        {"products": products, "sizes": SizeRange.objects.all(), "errors": errors},
        status=status,
    )


@staff_required
def costs(request):
    return render(request, "tienda/panel_costs.html", {"products": services.all_product_costs()})


@staff_required
def product_cost(request, slug):
    summary = services.product_cost_summary(slug)
    if summary is None:
        raise Http404
    errors = []
    status = 200
    if request.method == "POST":
        try:
            services.update_product_cost(slug, request.POST, user=request.user)
        except services.CostError as exc:
            errors = exc.messages
            status = 400
        else:
            return redirect("panel_product_cost", slug=slug)
    return render(
        request,
        "tienda/panel_cost_product.html",
        {"cost": summary, "errors": errors, "posted": request.POST if errors else None},
        status=status,
    )


@staff_required
def order(request, public_id):
    order = get_object_or_404(Order, public_id=public_id)
    error = None
    cost_form = CostForm(initial={
        "estimated_materials": order.estimated_materials,
        "estimated_labor": order.estimated_labor,
        "actual_materials": order.actual_materials,
        "actual_labor": order.actual_labor,
        "cost_notes": order.cost_notes,
    })
    if request.method == "POST" and request.POST.get("form") == "costs":
        cost_form = CostForm(request.POST)
        if cost_form.is_valid():
            d = cost_form.cleaned_data
            services.update_costs(
                order,
                user=request.user,
                estimated_materials=d["estimated_materials"],
                estimated_labor=d["estimated_labor"],
                actual_materials=d["actual_materials"],
                actual_labor=d["actual_labor"],
                notes=d["cost_notes"],
            )
            return redirect("panel_order", public_id=order.public_id)
        order.refresh_from_db()
    elif request.method == "POST" and request.POST.get("form") == "line_production":
        from .models import OrderLine

        line = order.lines.filter(pk=_int_or_none(request.POST.get("line"))).first()
        try:
            if line is None:
                raise services.TransitionError("That line does not belong to this order.")
            services.apply_line_transition(
                line, request.POST.get("value", ""), user=request.user,
                note=request.POST.get("note", ""),
            )
        except services.TransitionError as exc:
            error = str(exc)
            order.refresh_from_db()
        else:
            return redirect("panel_order", public_id=order.public_id)
    elif request.method == "POST" and request.POST.get("form") in ("size", "tracking"):
        try:
            if request.POST["form"] == "size":
                line_id = _int_or_none(request.POST.get("line"))
                services.confirm_size(
                    order, request.POST.get("size_confirmed", ""), user=request.user,
                    line=line_id,
                )
            else:
                services.set_tracking(
                    order,
                    request.POST.get("tracking_number", ""),
                    request.POST.get("tracking_carrier", ""),
                    user=request.user,
                )
        except services.TransitionError as exc:
            error = str(exc)
            order.refresh_from_db()
        else:
            return redirect("panel_order", public_id=order.public_id)
    elif request.method == "POST" and request.POST.get("form") == "payment_method":
        try:
            services.set_payment_method(
                order, request.POST.get("payment_method", ""), user=request.user
            )
        except services.TransitionError as exc:
            error = str(exc)
            order.refresh_from_db()
        else:
            return redirect("panel_order", public_id=order.public_id)
    elif request.method == "POST":
        try:
            services.apply_transition(
                order,
                request.POST.get("field", ""),
                request.POST.get("value", ""),
                user=request.user,
                note=request.POST.get("note", ""),
            )
        except services.TransitionError as exc:
            error = str(exc)
            order.refresh_from_db()
        else:
            return redirect("panel_order", public_id=order.public_id)
    return render(
        request,
        "tienda/panel_order.html",
        {
            "order": order,
            "snap": order.snapshot,
            "events": order.events.select_related("by"),
            "allowed": services.allowed_transitions(order),
            "cost": services.cost_summary(order),
            "cost_form": cost_form,
            "readiness": services.order_readiness(order),
            "progress": services.progress_steps(order),
            "settable_methods": [
                ("unspecified", "To be arranged"),
                ("bitcoin", "Bitcoin"),
            ],
            "error": error,
        },
        status=400 if (error or cost_form.errors) else 200,
    )
