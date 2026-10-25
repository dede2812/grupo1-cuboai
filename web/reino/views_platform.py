"""Plataforma: gateway, directorio (P01), para-negocios (M01), admin (P02)
y ALTA ASISTIDA de comercios (recorrido operativo, §6.15)."""

from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import (
    KnowledgeDocument, Merchant, MerchantMember, ShippingZone, Store,
)

ONBOARDING_CHECKLIST = [
    ("identidad", "Identidad: nombre, categoría y promesa de la tienda"),
    ("responsable", "Usuario responsable con rol de propietario"),
    ("catalogo", "Catálogo inicial: al menos un producto con variante"),
    ("envios", "Entrega: retiro y/o zonas con tarifa aprobada"),
    ("politicas", "Políticas de cambios y entrega publicadas"),
    ("pago", "Método de cobro definido (manual al inicio)"),
]


def robots_txt(request):
    """robots.txt: rutas privadas fuera del rastreo; sitemap enlazado."""
    from django.http import HttpResponse
    lines = [
        "User-agent: *",
        "Allow: /s/",
        "Disallow: /s/*/carrito/",
        "Disallow: /s/*/checkout/",
        "Disallow: /s/*/pedido/",
        "Disallow: /cuenta/",
        "Disallow: /negocio/",
        "Disallow: /plataforma/",
        "Disallow: /panel/",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml(request):
    """Sitemap público: tiendas visibles + productos publicados (§8)."""
    from django.http import HttpResponse
    from .models import Product
    base = f"{request.scheme}://{request.get_host()}"
    urls = [f"{base}/tiendas/"]
    from . import services_visibility as visibility
    for store in visibility.visible_stores():
        urls.append(f"{base}/s/{store.slug}/")
        urls.append(f"{base}/s/{store.slug}/coleccion/")
        for product in visibility.visible_products(store=store):
            urls.append(f"{base}/s/{store.slug}/producto/{product.slug}/")
    body = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f"{body}\n</urlset>")
    return HttpResponse(xml, content_type="application/xml")


def directory(request):
    """P02 · Directorio: elegir una marca por categoría y estilo.

    Filtros por categoría y búsqueda por nombre; la demo identificada antes
    de entrar; las tiendas en borrador no aparecen. Cada tarjeta muestra
    identidad propia y muestra real de productos (AC10).
    """
    from . import services_search
    q = request.GET.get("q", "").strip()
    category = request.GET.get("categoria", "").strip()
    stores = Store.objects.exclude(status=Store.Status.DRAFT).select_related("merchant")
    if q:
        stores = [s for s in stores if q.lower() in s.name.lower()]
    if category:
        stores = [s for s in stores if s.category == category]
    stores = services_search.annotate_stores(list(stores))
    categories = sorted({s.category for s in Store.objects.exclude(status=Store.Status.DRAFT)})
    return render(request, "reino/directory.html", {
        "stores": stores, "q": q, "category": category, "categories": categories,
    })


def for_business(request):
    """M01 · Presentación de Reino Commerce para comercios (piloto por invitación)."""
    return render(request, "reino/for_business.html")


def _is_operator(user):
    """Operador GLOBAL de plataforma (N11, §8.4): permiso explícito
    `reino.operate_platform`. Ser dueño/empleado/logística de un comercio —
    incluso con is_staff=True — NO concede administración global."""
    return user.is_authenticated and user.has_perm("reino.operate_platform")


@login_required(login_url="panel_login")
@user_passes_test(_is_operator, login_url="panel_login")
def platform_admin(request):
    """P02: comercios, estados y alta asistida (personal de la plataforma)."""
    merchants = Merchant.objects.prefetch_related("stores", "members__user").all()
    return render(request, "reino/platform_admin.html", {
        "merchants": merchants, "checklist": ONBOARDING_CHECKLIST,
    })


@login_required(login_url="panel_login")
@user_passes_test(_is_operator, login_url="panel_login")
@require_POST
def merchant_onboard(request):
    """Alta asistida (§6.15): crea comercio en BORRADOR + usuario responsable
    + permisos + zonas y políticas iniciales. Activar requiere completar el
    checklist operativo; nada queda vendible por accidente."""
    name = request.POST.get("name", "").strip()[:120]
    slug = request.POST.get("slug", "").strip().lower()[:60]
    category = request.POST.get("category", "general").strip()[:60]
    username = request.POST.get("username", "").strip()
    is_demo = request.POST.get("is_demo") == "1"
    errors = []
    if not name or not slug:
        errors.append("Nombre y slug son obligatorios.")
    elif Store.objects.filter(slug=slug).exists():
        errors.append("Ese slug ya está en uso.")
    if not username:
        errors.append("Indicá el usuario responsable.")
    if errors:
        request.session["reino_flash"] = " ".join(errors)
        return redirect("reino_platform")

    merchant = Merchant.objects.create(name=name, status=Merchant.Status.DRAFT)
    store = Store.objects.create(
        merchant=merchant, slug=slug, name=name, category=category,
        is_demo=is_demo, status=Store.Status.DEMO if is_demo else Store.Status.DRAFT,
    )
    user, created = User.objects.get_or_create(username=username)
    temp_password = None
    if created:
        # Alta operable (§14): contraseña temporal usable mostrada UNA vez al
        # operador; sin ella la tienda nacería sin acceso real del responsable.
        import secrets
        temp_password = secrets.token_urlsafe(9)
        user.set_password(temp_password)
        user.is_staff = True  # acceso al panel de SU tienda; NO a plataforma (N11)
        user.save()
    MerchantMember.objects.create(user=user, merchant=merchant, role="owner")
    ShippingZone.objects.create(store=store, name="Retiro en taller", mode="pickup", fee=0)
    KnowledgeDocument.objects.create(
        store=store, topic="cambios", title="Cambios (borrador por aprobar)",
        body="Política de cambios pendiente de aprobación del negocio.",
        audience="customer", is_published=False,
    )
    flash = (
        f"«{name}» creado en borrador con {username} como propietario. "
        "Completá el checklist antes de activar."
    )
    if temp_password:
        flash += (f" Contraseña temporal (mostrada solo esta vez): {temp_password} — "
                  "pedile que la cambie al entrar.")
    request.session["reino_flash"] = flash
    return redirect("reino_platform")


@login_required(login_url="panel_login")
@user_passes_test(_is_operator, login_url="panel_login")
@require_POST
def store_activate(request, slug):
    """Activar una tienda exige checklist operativo completo (verificado)."""
    store = Store.objects.filter(slug=slug).first()
    if store is None:
        return redirect("reino_platform")
    missing = []
    if not store.products.filter(status="published").exists():
        missing.append("catálogo (un producto publicado)")
    if not ShippingZone.objects.filter(store=store, is_active=True).exists():
        missing.append("entrega (una zona activa)")
    if not KnowledgeDocument.objects.filter(store=store, is_published=True).exists():
        missing.append("políticas publicadas")
    if not store.merchant.members.filter(is_active=True, role="owner").exists():
        missing.append("propietario activo")
    if missing and not store.is_demo:
        request.session["reino_flash"] = "Falta antes de activar: " + ", ".join(missing) + "."
    else:
        store.status = Store.Status.ACTIVE if not store.is_demo else Store.Status.DEMO
        store.save(update_fields=["status"])
        # F06: la visibilidad exige negocio piloto/activo; activar la tienda
        # activa también su negocio (si no, nacería invisible).
        if store.merchant.status == Merchant.Status.DRAFT:
            store.merchant.status = Merchant.Status.PILOT
            store.merchant.save(update_fields=["status"])
        request.session["reino_flash"] = f"«{store.name}» está {store.get_status_display()}."
    return redirect("reino_platform")


def components_showcase(request):
    """Galería viva del sistema visual Reino (G5): todos los componentes con
    datos reales de demostración — referencia de implementación y revisión."""
    from .models import Product, Store
    from .services_visibility import visible_products, visible_stores
    store = visible_stores().first()
    products = visible_products().select_related(
        "store").prefetch_related("media", "variants")[:3]
    return render(request, "reino/plataforma_componentes.html", {
        "store": store, "products": products,
    })
