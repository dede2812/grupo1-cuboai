"""Resolución de tienda y sesión: el tenant siempre se deriva en servidor.

Regla: sin tenant válido, fallo cerrado (404). Nunca confiar en un tenant
suministrado por el modelo de IA ni por el cliente sin validar.
"""

from django.http import Http404

from .models import CustomerIdentity, Merchant, Store

SESSION_PROFILE = "reino_profile"      # {store_slug: profile_public_id}
SESSION_CART = "reino_cart"            # {store_slug: cart_public_id}
SESSION_LOOKLAB = "reino_looklab"      # {store_slug: draft}


def get_store(slug, *, allow_demo=True):
    """Resuelve la tienda por slug o 404 (F06: política centralizada).

    No es pública si la tienda está en borrador O su negocio no está en
    piloto/activo: el acceso directo tampoco la descubre.
    """
    store = Store.objects.filter(slug=slug).select_related("merchant").first()
    if store is None or store.status == Store.Status.DRAFT:
        raise Http404("Tienda no encontrada")
    if store.merchant.status not in (Merchant.Status.PILOT, Merchant.Status.ACTIVE):
        raise Http404("Tienda no encontrada")
    if store.is_demo and not allow_demo:
        raise Http404("Tienda no disponible")
    return store


def ensure_session(request):
    """Garantiza una session_key estable (propietario de carritos y perfiles)."""
    if not request.session.session_key:
        request.session.create()
    return owner_key(request)


def owner_key(request):
    """Keep guest ownership unchanged; signed-in buyers use a durable UUID."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        identity = getattr(request, "_customer_identity", None)
        if identity is None or identity.user_id != user.pk:
            identity, _ = CustomerIdentity.objects.get_or_create(user=user)
            request._customer_identity = identity
        return identity.owner_key
    return request.session.session_key


def _scoped_get(request, key, store_slug):
    bag = request.session.get(key, {})
    return bag.get(store_slug)


def _scoped_set(request, key, store_slug, value):
    bag = dict(request.session.get(key, {}))
    bag[store_slug] = value
    request.session[key] = bag
    request.session.modified = True


def active_profile_id(request, store):
    return _scoped_get(request, SESSION_PROFILE, store.slug)


def set_active_profile(request, store, profile_public_id):
    _scoped_set(request, SESSION_PROFILE, store.slug, str(profile_public_id) if profile_public_id else None)


def cart_id(request, store):
    return _scoped_get(request, SESSION_CART, store.slug)


def set_cart_id(request, store, cart_public_id):
    _scoped_set(request, SESSION_CART, store.slug, str(cart_public_id))


def looklab_draft(request, store):
    return _scoped_get(request, SESSION_LOOKLAB, store.slug) or {}


def set_looklab_draft(request, store, draft):
    _scoped_set(request, SESSION_LOOKLAB, store.slug, draft)


def clear_looklab_draft(request, store):
    bag = dict(request.session.get(SESSION_LOOKLAB, {}))
    bag.pop(store.slug, None)
    request.session[SESSION_LOOKLAB] = bag
    request.session.modified = True
