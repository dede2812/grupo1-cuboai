"""Storefront Reino Commerce (S01–S03, S05, S07–S09, S12).

Composición, copy, estados y comportamiento móvil según §6. Toda la lógica de
talla/precio/stock vive en servicios de servidor; las vistas traducen
solicitudes a servicios.
"""

import uuid

from django.db import DatabaseError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services_analytics, services_commerce as commerce, services_fulfillment
from . import services_fit, services_memory, services_theme, tenancy
from .models import (
    KnowledgeDocument, Order, Product, ShippingZone, Variant,
)
from .money import fmt


def _store_view(view_func):
    """Resuelve tienda y sesión; fail-closed sin tenant válido."""
    def wrapper(request, slug, *args, **kwargs):
        request.reino_store = tenancy.get_store(slug)
        tenancy.ensure_session(request)
        return view_func(request, request.reino_store, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


def _profile(request, store):
    pid = tenancy.active_profile_id(request, store)
    if not pid:
        return None
    return services_memory.get_profile(store, tenancy.owner_key(request), pid)


def _measurement(request, store, profile):
    """Medidas persistentes SOLO con consentimiento vigente (R07)."""
    if not profile:
        return None
    return services_memory.authorized_measurement(
        store, tenancy.owner_key(request), profile)


# ------------------------------------------------------------------- S01 ----

def _store_home_context(request, store, theme_config=None):
    """Contexto de la portada; con `theme_config` explícito sirve el preview
    privado del borrador (F08)."""
    config = theme_config if theme_config is not None else (
        services_theme.current_theme(store).config or {})
    modules = [m for m in (config.get("modules") or []) if m.get("visible")]

    featured = list(
        Product.objects.filter(store=store, status=Product.Status.PUBLISHED)
        .prefetch_related("media", "variants")
        .order_by("-is_featured", "short_title")[:4]
    )
    hero_product = None
    hero_cfg = config.get("hero") or {}
    if hero_cfg.get("product_id"):
        hero_product = Product.objects.filter(
            store=store, status=Product.Status.PUBLISHED,
            public_id=hero_cfg["product_id"]).prefetch_related("media").first()
    if hero_product is None and featured:
        hero_product = featured[0]
    products_exist = Product.objects.filter(store=store, status=Product.Status.PUBLISHED).exists()
    hero_asset = None
    if hero_cfg.get("media_asset_id"):
        hero_asset = store.media_assets.filter(pk=hero_cfg["media_asset_id"]).first()
    ctx = {
        "featured": featured, "hero_product": hero_product,
        "products_exist": products_exist, "theme_config": config,
        "modules": modules, "hero_cfg": hero_cfg, "hero_asset": hero_asset,
        "profile": _profile(request, store),
    }
    if theme_config is not None:
        # Preview del borrador: sus variables CSS tienen prioridad sobre las
        # del procesador de contexto (que trae la versión publicada).
        from .context import theme_css_vars
        ctx["reino_theme"] = config
        ctx["reino_theme_css"] = theme_css_vars(config)
    return ctx


@_store_view
def store_home(request, store):
    """S01 · Home de marca: hero con foto real, módulos del tema PUBLICADO.

    Una tienda nueva muestra el tema neutral y sus propias fotos; jamás
    hereda activos de otra marca (AC10). El hero evita el activo histórico
    con el error «WEINER» embebido (validación de marca pendiente).
    """
    return render(request, "reino/store_home.html",
                  _store_home_context(request, store))


# ------------------------------------------------------------------- S02 ----

@_store_view
def collection(request, store):
    """S02 · Colección: descubrir con una intención.

    Texto simple => búsqueda lexical; filtros curados; el resultado y la URL
    conservan el estado; los filtros incompatibles devuelven cero (honesto).
    """
    q = request.GET.get("q", "").strip()[:200]
    category = request.GET.get("categoria", "").strip()
    occasion = request.GET.get("ocasion", "").strip()
    max_price = request.GET.get("max", "").strip()
    available_only = request.GET.get("disponible") == "1"
    sort = request.GET.get("orden", "relevancia")

    products = list(
        Product.objects.filter(store=store, status=Product.Status.PUBLISHED)
        .prefetch_related("media", "variants")
    )

    interpretation = []
    if q:
        ql = q.lower()
        products = [p for p in products if ql in p.title.lower()
                    or ql in p.short_title.lower()
                    or ql in (p.description or "").lower()
                    or any(ql in str(m).lower() for m in (p.materials or []))]
        interpretation.append(f"“{q}”")
    if category:
        products = [p for p in products if p.category == category]
        interpretation.append(category)
    if occasion:
        products = [p for p in products if occasion in (p.occasions or [])]
        interpretation.append(occasion)
    if max_price:
        try:
            cap = float(max_price)
            products = [p for p in products if float(p.base_price) <= cap]
            interpretation.append(f"hasta ${cap:,.0f}")
        except ValueError:
            pass
    if available_only:
        products = [p for p in products if any(v.stock > 0 for v in p.variants.filter(is_active=True))]
        interpretation.append("disponible")

    if sort == "precio-asc":
        products.sort(key=lambda p: p.base_price)
    elif sort == "precio-desc":
        products.sort(key=lambda p: -p.base_price)

    categories = sorted({p.category for p in Product.objects.filter(
        store=store, status=Product.Status.PUBLISHED)})
    occasions = sorted({o for p in Product.objects.filter(
        store=store, status=Product.Status.PUBLISHED) for o in (p.occasions or [])})

    profile = _profile(request, store)
    measurement = _measurement(request, store, profile)
    cards = []
    for p in products:
        fit = services_fit.evaluate_for_profile(p, measurement) if measurement and store.category == "moda canina" else None
        cards.append({"product": p, "fit": fit})

    if q:
        services_analytics.track_daily("search", store=store,
            session_key=tenancy.owner_key(request), key=f"collection:{q}:{category}:{occasion}:{max_price}",
            result_count=len(cards), source="collection")
    return render(request, "reino/collection.html", {
        "cards": cards, "q": q, "interpretation": interpretation,
        "categories": categories, "occasions": occasions,
        "selected": {"categoria": category, "ocasion": occasion, "max": max_price,
                     "disponible": available_only, "orden": sort},
        "result_count": len(cards),
    })


# ------------------------------------------------------------------- S03 ----

@_store_view
def product_detail(request, store, product_slug):
    """S03 · Ficha: elegir con seguridad (galería, variantes, fit, acordeones)."""
    product = (
        Product.objects.filter(store=store, slug=product_slug, status=Product.Status.PUBLISHED)
        .prefetch_related("media", "variants", "fit_rules")
        .first()
    )
    if product is None:
        return render(request, "reino/product_detail.html", {"product": None}, status=404)

    profile = _profile(request, store)
    measurement = _measurement(request, store, profile)
    variants = list(product.variants.filter(is_active=True).order_by("pk"))
    fit = services_fit.evaluate_for_profile(product, measurement) if measurement else None

    variant_rows = []
    for v in variants:
        hint = None
        if fit and fit["candidates"] and any(
                services_fit.label_matches(c, v.option_label) for c in fit["candidates"]):
            hint = "sugerida"
        variant_rows.append({"variant": v, "fit_hint": hint, "available": v.stock > 0})

    # Complementos: máximo dos, solo con compatibilidad registrada.
    from .services_recommend import compose_bundle
    bundle, _ = compose_bundle(store, product, measurement=measurement)
    complements = [b["product"] for b in bundle if b["role"] == "complemento"][:2]

    # Datos estructurados Product/ofertas/variantes (descubrimiento, §8 [S02]).
    import json
    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.title,
        "description": product.description or product.subtitle,
        "brand": {"@type": "Brand", "name": store.name},
        "offers": [
            {"@type": "Offer", "sku": v.sku, "name": v.option_label,
             "price": str(v.price), "priceCurrency": store.currency,
             "availability": "https://schema.org/InStock" if v.stock > 0
             else "https://schema.org/OutOfStock"}
            for v in variants
        ],
    }, ensure_ascii=False)

    services_analytics.track_daily("product_view", store=store,
                             session_key=tenancy.owner_key(request) or "",
                             key=str(product.public_id),
                             product=str(product.public_id))
    return render(request, "reino/product_detail.html", {
        "product": product, "variant_rows": variant_rows, "fit": fit,
        "profile": profile, "complements": complements,
        "media": list(product.media.all()),
        "json_ld": json_ld,
        "has_quote_flow": bool(product.legacy_slug),  # pieza a medida: Smart Quote preservado
    })


# ------------------------------------------------------------------- S05 ----

@_store_view
def smart_fit(request, store):
    """S05 · Smart Fit: tres medidas, cuatro estados honestos, cm/in equivalentes."""
    profile = _profile(request, store)
    products = Product.objects.filter(store=store, status=Product.Status.PUBLISHED).order_by("short_title")
    selected_product = request.POST.get("producto", request.GET.get("producto", "")).strip()
    product = None
    result, errors, values, results = None, {}, {"unit": "cm"}, []
    if selected_product:
        product = products.filter(slug=selected_product).first()
        if product is None:
            errors["producto"] = "Elegí una prenda publicada de esta tienda."
    measurement = None
    # GET con ?producto= y medidas guardadas (autorizadas): evaluación directa.
    if request.method == "GET" and product and profile:
        measurement = _measurement(request, store, profile)
    if request.method == "POST":
        unit = request.POST.get("unit", "cm")
        values = {k: request.POST.get(k, "").strip() for k in ("chest", "neck", "back")}
        values["unit"] = unit
        if unit not in ("cm", "in"):
            errors["unit"] = "Elegí centímetros o pulgadas."
        try:
            chest = services_fit.to_cm(values["chest"], unit) if values["chest"] else None
        except services_fit.InvalidMeasurement as exc:
            chest, errors["chest"] = None, str(exc)
        try:
            neck = services_fit.to_cm(values["neck"], unit) if values["neck"] else None
        except services_fit.InvalidMeasurement as exc:
            neck, errors["neck"] = None, str(exc)
        try:
            back = services_fit.to_cm(values["back"], unit) if values["back"] else None
        except services_fit.InvalidMeasurement as exc:
            back, errors["back"] = None, str(exc)

        if not errors and (chest or neck or back):
            remember = request.POST.get("remember") == "1"
            if remember and profile:
                # Guardar requiere consentimiento explícito y separado (R07).
                services_memory.grant_consent(
                    store, tenancy.owner_key(request),
                    services_memory.Consent.Purpose.MEASUREMENTS, profile)
                measurement = services_memory.save_measurement(
                    profile, chest_cm=chest, neck_cm=neck, back_cm=back,
                    original={**values}, source="smartfit",
                )
            else:
                # «Calcular sin guardar»: evaluación temporal, nada persiste.
                measurement = services_fit.SimpleMeasurement(chest, neck, back)
        elif not errors:
            errors["chest"] = "Ingresá al menos una medida para evaluar."

    if measurement is not None and not errors:
        from django.db.models import Sum
        from django.utils import timezone
        from .models import StockReservation
        evaluated_products = ([product] if product else
            list(products.filter(fit_rules__is_active=True).distinct().prefetch_related("variants")))
        variant_ids = [v.pk for p in evaluated_products for v in p.variants.all()]
        reserved = dict(StockReservation.objects.filter(
            variant_id__in=variant_ids, status=StockReservation.Status.ACTIVE,
            expires_at__gt=timezone.now()).values("variant_id").annotate(
                units=Sum("quantity")).values_list("variant_id", "units"))
        for candidate_product in evaluated_products:
            fit = services_fit.evaluate_for_profile(candidate_product, measurement)
            available = [v.option_label for v in candidate_product.variants.all()
                if v.is_active and v.stock - reserved.get(v.pk, 0) > 0
                and any(services_fit.label_matches(label, v.option_label) for label in fit["candidates"])]
            results.append({"product": candidate_product, "fit": fit, "available_sizes": available})
        if product:
            result = results[0]["fit"]
    return render(request, "reino/smartfit.html", {
        "profile": profile, "product": product, "result": result, "errors": errors,
        "values": values, "products": products, "selected_product": selected_product,
        "results": results, "evaluated": measurement is not None and not errors,
        "latest": _measurement(request, store, profile),
    }, status=400 if "producto" in errors else 200)


# ------------------------------------------------------------------- S07 ----

@_store_view
def cart_view(request, store):
    """S07 · Carrito: confirmar la selección; envío por calcular."""
    cart = commerce.get_open_cart(store, tenancy.owner_key(request))
    summary = commerce.cart_summary(cart) if cart else None
    return render(request, "reino/cart.html", {
        "cart": cart, "summary": summary,
        "line_errors": request.session.pop("reino_cart_error", None),
    })


@_store_view
def digital_download(request, store, token):
    """Descarga autorizada de un producto digital (A33, §12.2).

    El enlace sale de la página de pedido del comprador; valida token,
    vencimiento y límite — nunca es una URL pública permanente.
    """
    grant, error = services_fulfillment.authorized_download(token)
    if error:
        return render(request, "reino/download_error.html", {
            "store": store, "error": error}, status=410)
    # Autorización: el pedido del grant debe pertenecer a esta sesión.
    session_orders = set(request.session.get(f"reino_orders_{store.slug}", []))
    owns_cart = grant.order.cart and grant.order.cart.session_key == tenancy.owner_key(request)
    if grant.order.store_id != store.pk or (not owns_cart and str(grant.order.public_id) not in session_orders):
        return render(request, "reino/download_error.html", {
            "store": store,
            "error": "Esta descarga pertenece a otra compra. Abrila desde tu pedido."},
            status=403)
    try:
        services_fulfillment.register_download(grant)
    except services_fulfillment.FulfillmentError:
        return render(request, "reino/download_error.html", {
            "store": store, "error": "Esta descarga ya no está disponible. Revisá el estado de tu pedido."}, status=410)
    from django.http import FileResponse
    return FileResponse(grant.asset.file.open("rb"),
                        as_attachment=True,
                        filename=f"{grant.asset.product.slug}-v{grant.asset.version}{_ext(grant.asset.file.name)}")


def _ext(name):
    import os
    return os.path.splitext(name)[1][:10] or ".bin"


@_store_view
@require_POST
def cart_add(request, store):
    """Añade una variante válida; una inexistente nunca llega al carrito."""
    variant = Variant.objects.filter(
        public_id=request.POST.get("variant"), product__store=store, is_active=True
    ).select_related("product").first()
    if variant is None:
        request.session["reino_cart_error"] = "Esa variante ya no está disponible."
        return redirect("reino_cart", slug=store.slug)
    cart = commerce.get_open_cart(store, tenancy.owner_key(request), create=True)
    slot = None
    if variant.product.offer_type == "service":
        from .models import ServiceSlot
        slot = ServiceSlot.objects.filter(
            pk=request.POST.get("slot"), product=variant.product, is_active=True).first()
    try:
        commerce.add_item(cart, variant, request.POST.get("quantity", 1),
                          recipient=_profile(request, store), service_slot=slot)
    except (commerce.CartError, commerce.StockConflict) as exc:
        request.session["reino_cart_error"] = str(exc)
        return redirect("reino_cart", slug=store.slug)
    services_analytics.track_once("cart_added", store=store,
                             session_key=tenancy.owner_key(request) or "",
                             key=f"{cart.public_id}:{cart.version}", cart=str(cart.public_id),
                             product=str(variant.product.public_id),
                             variant=str(variant.public_id),
                             quantity=int(request.POST.get("quantity", 1)))
    return redirect("reino_cart", slug=store.slug)


@_store_view
@require_POST
def cart_update(request, store, item_id):
    cart = commerce.get_open_cart(store, tenancy.owner_key(request))
    if cart:
        try:
            commerce.update_item(cart, item_id, request.POST.get("quantity", 1))
        except (commerce.CartError, ValueError) as exc:
            request.session["reino_cart_error"] = str(exc)
    return redirect("reino_cart", slug=store.slug)


@_store_view
@require_POST
def cart_remove(request, store, item_id):
    cart = commerce.get_open_cart(store, tenancy.owner_key(request))
    if cart:
        commerce.remove_item(cart, item_id)
    return redirect("reino_cart", slug=store.slug)


# ------------------------------------------------------------------- S08 ----

@_store_view
def checkout(request, store):
    """S08 · Checkout: datos y opciones → revisión vigente → confirmar.

    Microcopy final honesto: «Crear pedido pendiente de pago» (flujo manual).
    La clave de intento es POR TIENDA (R01); el resumen aprobado queda ligado
    a su contenido (R02); modalidad/zona/tarifa se validan en servidor (R06).
    """
    session_key = tenancy.owner_key(request)
    cart = commerce.get_open_cart(store, session_key)
    if cart is None:
        return redirect("reino_cart", slug=store.slug)

    services_analytics.track_once("checkout_started", store=store, session_key=session_key,
                                 key=str(cart.public_id), cart=str(cart.public_id))
    idem_key = f"reino_idem_{store.slug}"  # un intento por tienda, jamás compartido (R01)
    zones = ShippingZone.objects.filter(store=store, is_active=True)
    errors = {}
    data = {}
    payment_method = "manual"

    if request.method == "POST":
        step = request.POST.get("step", "review")
        data = {k: request.POST.get(k, "").strip() for k in
                ("name", "email", "phone", "delivery_mode", "zone", "address", "city",
                 "payment_method")}
        payment_method = data["payment_method"] or "manual"
        idem = request.POST.get("idempotency_key") or uuid.uuid4().hex
        request.session.setdefault(idem_key, idem)

        if not data["name"]:
            errors["name"] = "Ingresá tu nombre."
        if "@" not in data["email"]:
            errors["email"] = "Ingresá un correo válido."
        # Carrito sin líneas físicas: no hay transporte que validar (G2).
        if not commerce.cart_requires_shipping(cart):
            data["delivery_mode"] = "none"
            data["zone"] = ""
            data["address"] = data["address"] or ""
        # Zona validada en servidor: tienda + activa + modalidad coherente (R06).
        zone = None
        if data["delivery_mode"] == "none":
            pass  # digital/servicio: sin envío (A33)
        elif data["delivery_mode"] == "local":
            zone = zones.filter(name=data["zone"], mode="local").first()
            if zone is None:
                errors["zone"] = "Elegí una zona de entrega válida."
            if not data["address"]:
                errors["address"] = "Ingresá la dirección de entrega."
        elif data["delivery_mode"] == "pickup":
            zone = None
        else:
            errors["delivery_mode"] = "Elegí una modalidad de entrega válida."
        if payment_method not in ("manual", "bitcoin"):
            errors["payment_method"] = "Elegí un método de pago habilitado."

        if not errors:
            try:
                session = commerce.prepare_checkout(
                    cart, payment_method,
                    delivery_mode=data["delivery_mode"] or "pickup",
                    zone=zone, idempotency_key=request.session[idem_key],
                )
            except commerce.StockConflict as exc:
                request.session["reino_cart_error"] = str(exc)
                return redirect("reino_cart", slug=store.slug)
            except commerce.CartError as exc:
                errors["zone"] = str(exc)
            else:
                reviewed_id = request.POST.get("session_id", "")
                if step == "confirm" and reviewed_id and str(session.public_id) != reviewed_id:
                    # El resumen cambió desde la última revisión: exigir una
                    # revisión nueva del contenido vigente (R02), nunca
                    # confirmar un resumen obsoleto.
                    step = "review"
                if step == "review":
                    services_analytics.track_once("checkout_reviewed", store=store,
                                             session_key=tenancy.owner_key(request) or "",
                                             key=f"{session.public_id}:{session.revision}",
                                             revision=session.revision)
                    return render(request, "reino/checkout_review.html", {
                        "cart": cart, "summary": commerce.cart_summary(cart, payment_method),
                        "data": data, "session": session, "store": store,
                        "total": _review_total(session),
                        "idem": request.session[idem_key],
                    })
                try:
                    order = commerce.confirm_checkout(
                        session,
                        {"name": data["name"], "email": data["email"],
                         "phone": data["phone"], "address": data["address"],
                         "city": data["city"]},
                        idempotency_key=session.idempotency_key,
                    )
                except (commerce.CartError, commerce.StockConflict) as exc:
                    errors["confirm"] = str(exc)
                else:
                    services_analytics.track("order_placed", store=store,
                                             session_key=tenancy.owner_key(request) or "",
                                             request_id=f"order-{order.public_id}",
                                             order=order.reference, total=str(order.total))
                    if order.discount_amount:
                        services_analytics.track_once("promotion_applied", store=store,
                            session_key=tenancy.owner_key(request), key=str(order.public_id),
                            order=order.reference, discount=str(order.discount_amount))
                    request.session.pop(idem_key, None)
                    # La compra queda ligada a esta sesión: autoriza las
                    # descargas digitales de ESTE pedido (A33).
                    owned = request.session.get(f"reino_orders_{store.slug}", [])
                    owned.append(str(order.public_id))
                    request.session[f"reino_orders_{store.slug}"] = owned[-20:]
                    return redirect("reino_order_guest", slug=store.slug,
                                    public_id=order.public_id, token=order.access_token)

    summary = commerce.cart_summary(cart, payment_method)
    if summary["is_empty"]:
        return redirect("reino_cart", slug=store.slug)
    from .services_payments import configured_checkout_options
    return render(request, "reino/checkout.html", {
        "cart": cart, "summary": summary, "zones": zones, "errors": errors,
        "data": data, "idem": request.session.get(idem_key, uuid.uuid4().hex),
        "payment_options": configured_checkout_options(store, payment_method),
    })


def _review_total(session):
    from decimal import Decimal
    s = session.summary
    subtotal = Decimal(s["subtotal"])
    discount = Decimal(s.get("discount", "0"))
    shipping = Decimal(s["shipping"]) if s.get("shipping") is not None else None
    return {"subtotal": subtotal, "discount": discount, "shipping": shipping,
            "total": subtotal - discount + (shipping or 0)}


# ------------------------------------------------------------------- S09 ----

@_store_view
def order_detail(request, store, public_id, token=None):
    """S09 · Confirmación y seguimiento. Acceso protegido por token de alta
    entropía (invitados) o por sesión propietaria."""
    order = Order.objects.filter(store=store, public_id=public_id).prefetch_related(
        "items", "events").first()
    if order is None:
        return render(request, "reino/order.html", {"order": None}, status=404)
    owner_session = order.cart and order.cart.session_key == tenancy.owner_key(request)
    if not owner_session and str(order.access_token) != str(token):
        # Un número adivinado no autentica: sin datos privados (A25).
        return render(request, "reino/order.html", {"order": None}, status=404)
    grants = []
    if order.payment_status == Order.PaymentStatus.PAID:
        grants = order.digital_grants.select_related("asset__product")
    from . import services_payments
    active_payment = order.payment_attempts.filter(provider__in=("paypal", "wompi", "btcpay")).exclude(
        state__in=services_payments.TERMINAL).first()
    return render(request, "reino/order.html", {
        "order": order,
        "payment_label": dict(Order.PaymentStatus.choices).get(order.payment_status),
        "digital_grants": grants,
        "bookings": order.bookings.select_related("slot"),
        "payment_options": services_payments.checkout_options(order),
        "active_payment": active_payment if order.payment_status == "pending" else None,
    })


# ------------------------------------------------------------------- S12 ----

@_store_view
def help_center(request, store):
    """S12 · Ayuda: respuestas publicadas y vigentes por la tienda (RAG P0)."""
    topic = request.GET.get("tema", "")
    docs = KnowledgeDocument.objects.filter(store=store, is_published=True,
                                            audience="customer")
    if topic:
        docs = docs.filter(topic=topic)
    topics = sorted(set(KnowledgeDocument.objects.filter(
        store=store, is_published=True, audience="customer"
    ).values_list("topic", flat=True)))
    return render(request, "reino/help.html", {
        "docs": docs, "topics": topics, "selected_topic": topic,
    })
