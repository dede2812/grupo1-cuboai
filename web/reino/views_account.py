"""S10 · Cuenta, Royal Passport y preferencias (P0 por sesión).

- «Mis perfiles», «Mis looks», «Mi privacidad» por tienda.
- Privacidad muestra cada permiso por tienda, finalidad, fecha y datos.
- «Borrar memoria» retira preferencias y derivados; no toca pedidos.
- Memoria desactivada no impide comprar.
"""

from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from decimal import Decimal, InvalidOperation

from . import services_fit, services_memory, tenancy
from .models import Cart, Consent, Look, Order, Store
from .views_storefront import _store_view  # noqa: F401 (patrón de resolución)


def _stores_with_data(session_key):
    """Tiendas donde la sesión tiene perfiles o consentimientos."""
    from .models import RecipientProfile
    slugs = set(RecipientProfile.objects.filter(session_key=session_key)
                .values_list("store__slug", flat=True))
    slugs |= set(Consent.objects.filter(session_key=session_key)
               .values_list("store__slug", flat=True))
    slugs |= set(Cart.objects.filter(session_key=session_key).values_list("store__slug", flat=True))
    slugs |= set(Look.objects.filter(session_key=session_key).values_list("store__slug", flat=True))
    return Store.objects.filter(slug__in=slugs)


def account_home(request):
    tenancy.ensure_session(request)
    session_key = tenancy.owner_key(request)
    stores = _stores_with_data(session_key)
    active_store = None
    if request.GET.get("tienda"):
        active_store = stores.filter(slug=request.GET["tienda"]).first()
    if active_store is None:
        active_store = stores.first()

    profiles, consents, looks = [], {}, []
    if active_store:
        profiles = services_memory.list_profiles(active_store, session_key)
        consents = services_memory.consent_state(active_store, session_key)
        looks = list(Look.objects.filter(store=active_store, session_key=session_key))
    return render(request, "reino/account.html", {
        "stores": stores, "active_store": active_store,
        "profiles": profiles, "consents": consents, "looks": looks,
        "latest_measurements": {p.public_id: services_memory.latest_measurement(p) for p in profiles},
        "saved_preferences": {p.public_id: services_memory.authorized_preferences(p, active_store, session_key) for p in profiles},
        "orders": Order.objects.filter(cart__session_key=session_key).select_related("store").order_by("-created_at")[:20],
    })


@require_POST
def profile_create(request):
    tenancy.ensure_session(request)
    store = tenancy.get_store(request.POST.get("store", ""))
    profile = services_memory.create_profile(
        store, tenancy.owner_key(request),
        request.POST.get("alias", ""), kind=request.POST.get("kind", "dog"),
        breed=request.POST.get("breed", ""),
    )
    tenancy.set_active_profile(request, store, profile.public_id)
    return _safe_store_redirect(request, store)


@require_POST
def profile_activate(request, public_id):
    tenancy.ensure_session(request)
    store = tenancy.get_store(request.POST.get("store", ""))
    profile = services_memory.get_profile(store, tenancy.owner_key(request), public_id)
    if profile:
        tenancy.set_active_profile(request, store, profile.public_id)
    return _safe_store_redirect(request, store)


def _safe_store_redirect(request, store):
    target = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(target, {request.get_host()}, require_https=request.is_secure()):
        target = f"/s/{store.slug}/"
    return redirect(target)


@require_POST
def profile_measurements(request, public_id):
    """Actualiza medidas de un perfil propio; cm/in equivalentes (A04)."""
    tenancy.ensure_session(request)
    store = tenancy.get_store(request.POST.get("store", ""))
    profile = services_memory.get_profile(store, tenancy.owner_key(request), public_id)
    if profile is None:
        return redirect("reino_account")
    unit = request.POST.get("unit", "cm")
    try:
        chest = services_fit.to_cm(request.POST["chest"], unit) if request.POST.get("chest") else None
        neck = services_fit.to_cm(request.POST["neck"], unit) if request.POST.get("neck") else None
        back = services_fit.to_cm(request.POST["back"], unit) if request.POST.get("back") else None
    except services_fit.InvalidMeasurement:
        request.session["reino_flash"] = "Revisá las medidas: algún valor no es válido."
        return redirect("reino_account")
    services_memory.save_measurement(profile, chest_cm=chest, neck_cm=neck, back_cm=back,
                                     original={"unit": unit}, source="account")
    request.session["reino_flash"] = "Medidas actualizadas."
    return redirect("reino_account")


@require_POST
def profile_preferences(request, public_id):
    owner = tenancy.ensure_session(request)
    store = tenancy.get_store(request.POST.get("store", ""))
    profile = services_memory.get_profile(store, owner, public_id)
    if profile is None:
        return redirect("reino_account")
    if request.POST.get("remember") != "1":
        request.session["reino_flash"] = "Elegí si querés autorizar el guardado de estas preferencias."
        return redirect("reino_account")
    style = request.POST.get("style", "").strip()[:120]
    budget = request.POST.get("budget", "").strip()
    if budget:
        try:
            amount = Decimal(budget.replace(",", "."))
            if not amount.is_finite() or not 0 < amount <= 100000:
                raise InvalidOperation
            budget = str(amount.quantize(Decimal("0.01")))
        except InvalidOperation:
            request.session["reino_flash"] = "Ingresá un presupuesto válido."
            return redirect("reino_account")
    consent = services_memory.grant_consent(store, owner, Consent.Purpose.PREFERENCES, profile)
    for key, value in (("style", style), ("budget_hint", budget)):
        if value:
            services_memory.save_preference(profile, consent, key, value)
        else:
            profile.preferences.filter(key=key).delete()
    request.session["reino_flash"] = "Preferencias actualizadas con tu permiso."
    return redirect("reino_account")


@require_POST
def consent_update(request):
    """Otorga o revoca un permiso (clic del usuario; nunca del modelo, §14)."""
    tenancy.ensure_session(request)
    store = tenancy.get_store(request.POST.get("store", ""))
    purpose = request.POST.get("purpose", "")
    if purpose not in dict(Consent.Purpose.choices):
        return redirect("reino_account")
    profile = None
    if request.POST.get("profile"):
        profile = services_memory.get_profile(store, tenancy.owner_key(request),
                                              request.POST["profile"])
        if profile is None:
            return redirect("reino_account")
    if request.POST.get("decision") == "grant":
        services_memory.grant_consent(store, tenancy.owner_key(request), purpose, profile)
        request.session["reino_flash"] = "Permiso guardado."
    else:
        services_memory.revoke_consent(store, tenancy.owner_key(request), purpose, profile)
        request.session["reino_flash"] = "Permiso retirado. La próxima recomendación ya no usará esos datos."
    return redirect("reino_account")


@require_POST
def profile_memory_delete(request, public_id):
    """«Borrar memoria»: preferencias, resúmenes y foto; explica qué se conserva."""
    tenancy.ensure_session(request)
    store = tenancy.get_store(request.POST.get("store", ""))
    profile = services_memory.get_profile(store, tenancy.owner_key(request), public_id)
    if profile:
        services_memory.delete_profile_memory(store, tenancy.owner_key(request), profile)
        request.session["reino_flash"] = (
            "Memoria borrada: preferencias, foto y resúmenes eliminados. "
            "Los pedidos registrados se conservan según la política de la tienda."
        )
    return redirect("reino_account")


def looks(request):
    tenancy.ensure_session(request)
    session_key = tenancy.owner_key(request)
    all_looks = Look.objects.filter(session_key=session_key).select_related("store", "profile")
    return render(request, "reino/looks.html", {"looks": all_looks})
