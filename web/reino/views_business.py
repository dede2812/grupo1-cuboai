"""Private business reporting and CSV, using the same filters and permission."""
import csv
from datetime import timedelta

from django import forms
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import Order, Product
from .services_business import ReportFilters, build_report, order_scope, VERIFIED
from .views_merchant import merchant_view, require_capability


class ReportFilterForm(forms.Form):
    start = forms.DateField(label="Desde", widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Hasta", widget=forms.DateInput(attrs={"type": "date"}))
    product = forms.ModelChoiceField(label="Producto", queryset=Product.objects.none(), required=False,
                                    empty_label="Todos los productos")
    category = forms.ChoiceField(label="Categoría", required=False)
    status = forms.ChoiceField(label="Estado del pedido", required=False,
                              choices=[("", "Todos los estados"), *Order.Status.choices])
    bucket = forms.ChoiceField(label="Agrupar", choices=[("day", "Día"), ("week", "Semana"), ("month", "Mes")])

    def __init__(self, store, params):
        data = params.copy()
        today = timezone.localdate()
        data.setdefault("start", (today - timedelta(days=29)).isoformat())
        data.setdefault("end", today.isoformat())
        data.setdefault("bucket", "day")
        super().__init__(data)
        products = Product.objects.filter(store=store).order_by("short_title")
        self.fields["product"].queryset = products
        self.fields["product"].label_from_instance = lambda p: p.short_title
        self.fields["category"].choices = [("", "Todas las categorías"), *(
            (name, name) for name in products.order_by("category").values_list("category", flat=True).distinct())]

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end:
            if end < start:
                raise forms.ValidationError("La fecha final debe ser igual o posterior a la inicial.")
            if (end - start).days > 365:
                raise forms.ValidationError("Elegí un período de hasta 366 días.")
            if end > timezone.localdate():
                raise forms.ValidationError("La fecha final no puede estar en el futuro.")
            try:
                start - timedelta(days=(end - start).days + 1)
            except OverflowError:
                raise forms.ValidationError("La fecha inicial no permite calcular el período anterior.") from None
        return data

    def filters(self):
        d = self.cleaned_data
        return ReportFilters(d["start"], d["end"], d["product"].pk if d["product"] else None,
                             d["category"], d["status"], d["bucket"])


@merchant_view
@require_capability("payments")
@require_GET
def dashboard(request, store):
    form = ReportFilterForm(store, request.GET)
    context = {"store": store, "form": form, "member": request.reino_member}
    if not form.is_valid():
        return render(request, "reino/business_dashboard.html", context, status=400)
    filters = form.filters()
    report = build_report(store, filters)
    context.update({"report": report, "filters": filters, "previous_filters": filters.previous(),
                    "export_query": form.data.urlencode(),
                    "chart_data": {"current": report["series"], "previous": report["previous_series"],
                                   "currency": store.currency}})
    response = render(request, "reino/business_dashboard.html", context)
    response["Cache-Control"] = "private, no-store"
    return response


def csv_cell(value):
    """Neutralize spreadsheet formulas in untrusted snapshots and references."""
    text = str(value if value is not None else "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text


@merchant_view
@require_capability("payments")
@require_GET
def export_csv(request, store):
    form = ReportFilterForm(store, request.GET)
    if not form.is_valid():
        return HttpResponse("Filtros inválidos. Revisá el rango y los valores del informe.", status=400)
    filters = form.filters()
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{store.slug}-{filters.start}-{filters.end}.csv"'
    response["Cache-Control"] = "private, no-store"
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Pedido", "Fecha creación", "Moneda", "Estado pedido", "Estado pago", "Productos brutos",
                     "Descuentos", "Envío", "Impuestos", "Total pedido", "Reembolso acumulado",
                     "Cobro neto verificado", "Nota descuento"])
    for order in order_scope(store, filters).order_by("created_at").iterator():
        verified = order.payment_status in VERIFIED
        unknown_refund = order.payment_status in ("refunded", "partially_refunded") and order.refund_amount is None
        writer.writerow([csv_cell(v) for v in [order.reference, timezone.localtime(order.created_at).isoformat(),
            order.currency, order.get_status_display(), order.get_payment_status_display(), order.subtotal,
            order.discount_amount, order.shipping_amount, "No desglosados", order.total,
            "Sin importe registrado" if unknown_refund else order.refund_amount or 0,
            order.total - (order.refund_amount or 0) if verified and not unknown_refund else "",
            order.discount_note]])
    return response
