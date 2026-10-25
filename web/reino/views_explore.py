"""Descubrimiento, búsqueda y comparación de Reino (P01, P04, P06).

Rutas de plataforma nuevas; las históricas quedan intactas. Todo funciona
sin clave de IA: reglas, filtros visibles y estado compartible por URL.
"""

from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import services_analytics, services_compare, services_search, tenancy
from .models import Variant


def _session_key(request):
    return tenancy.ensure_session(request)


def explore(request):
    """P01 · Explorar Reino: descubrimiento del catálogo disponible."""
    data = services_search.explore_home()
    return render(request, "reino/explorar.html", {
        **data,
        "examples": ["algo para paseo", "regalo por menos de $30", "para celebración"],
    })


def search(request):
    """P04 · Búsqueda universal del catálogo disponible (reglas, sin IA)."""
    q = request.GET.get("q", "").strip()
    occasion = request.GET.get("ocasion", "")
    raw_max_price = request.GET.get("max", "").strip()
    category = request.GET.get("categoria", "")
    from decimal import Decimal, InvalidOperation
    price_error = ""
    try:
        max_price = Decimal(raw_max_price) if raw_max_price else None
        if max_price is not None and (not max_price.is_finite() or max_price < 0):
            raise InvalidOperation
    except InvalidOperation:
        max_price = None
        price_error = "Ingresá un precio máximo válido, mayor o igual a cero."
    searched = bool(q or occasion or category or raw_max_price)
    results = services_search.search_catalog(
        q, occasion=occasion, max_price=max_price, category=category) if searched and not price_error else []
    if searched and not price_error:
        # A platform search is not arbitrarily attributed to each merchant.
        services_analytics.track_daily("search", session_key=_session_key(request),
            key=f"platform:{q}:{occasion}:{max_price}:{category}",
            result_count=len(results), source="platform")
    return render(request, "reino/buscar.html", {
        "q": q, "occasion": occasion,
        "max_price": max_price if max_price is not None else "",
        "price_error": price_error,
        "category": category, "results": results,
        "searched": searched,
        "examples": ["algo para paseo", "regalo por menos de $30", "para celebración"],
    })


def compare(request):
    """P06 · Comparador: 2–4 variantes, solo diferencias, compartir."""
    key = _session_key(request)
    public_id = request.GET.get("c")  # comparación compartida (IDs no sensibles)
    data = services_compare.build_comparison(
        session_key=None if public_id else key, public_id=public_id)
    rows = data["rows"]
    if request.GET.get("vista") == "diferencias":
        rows = services_compare.diff_rows(rows, data["columns"])
    if data["columns"]:
        services_analytics.track("compare_opened", session_key=key,
                                 items=len(data["columns"]))
    # URL de compartir construida con parámetros reales (nunca concatenando
    # «?c=» a una URL que puede traer query): A17.
    share_url = request.build_absolute_uri(
        f"/comparar/?c={data['tray'].public_id}") if data["tray"] else ""
    return render(request, "reino/comparar.html", {
        **data, "rows": rows, "vista": request.GET.get("vista", "todos"),
        "shared": bool(public_id), "share_url": share_url,
    })


@require_POST
def compare_add(request):
    key = _session_key(request)
    variant_id = request.POST.get("variant_id", "")
    try:
        tray, message = services_compare.add_item(key, variant_id)
        request.session["reino_flash"] = message
        services_analytics.track("compare_selected", session_key=key,
                                 variant_id=variant_id)
    except services_compare.CompareError as exc:
        request.session["reino_flash"] = str(exc)
    return redirect(request.POST.get("next") or "reino_compare")


@require_POST
def compare_remove(request):
    key = _session_key(request)
    services_compare.remove_item(key, request.POST.get("variant_id", ""))
    return redirect(request.POST.get("next") or "reino_compare")
