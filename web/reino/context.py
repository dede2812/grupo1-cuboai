"""Contexto global de templates reino: tienda activa, perfil activo y carrito."""

from . import services_compare, services_memory, services_theme, tenancy
from .models import RecipientProfile


def reino_context(request):
    """Contexto global: tienda, tema PUBLICADO (variables CSS), perfil,
    carrito y bandeja de comparación."""
    ctx = {"reino_store": None, "reino_profile": None, "reino_cart_units": 0,
           "reino_profiles": [], "reino_theme": None, "reino_theme_css": "",
           "reino_compare_count": 0,
           "reino_flash": request.session.pop("reino_flash", None)}
    key = tenancy.owner_key(request)
    if key:
        ctx["reino_compare_count"] = len(
            services_compare.get_tray(key).items) if key else 0
    store = getattr(request, "reino_store", None)
    if store is None:
        # Tema de plataforma (Reino) para /explorar/, /buscar/, /comparar/.
        if request.path.startswith(("/explorar", "/buscar", "/comparar", "/tiendas",
                                    "/para-negocios", "/cuenta")):
            config = services_theme.default_config("reino")
            ctx["reino_theme"] = config
            ctx["reino_theme_css"] = theme_css_vars(config)
        return ctx
    session_key = tenancy.ensure_session(request)
    ctx["reino_store"] = store
    theme = services_theme.current_theme(store)
    ctx["reino_theme"] = theme.config
    ctx["reino_theme_css"] = theme_css_vars(theme.config)
    ctx["reino_profiles"] = services_memory.list_profiles(store, session_key)
    profile_id = tenancy.active_profile_id(request, store)
    if profile_id:
        ctx["reino_profile"] = RecipientProfile.objects.filter(
            store=store, session_key=session_key, public_id=profile_id
        ).first()
    from .services_commerce import get_open_cart
    cart = get_open_cart(store, session_key)
    if cart:
        ctx["reino_cart_units"] = sum(i.quantity for i in cart.items.all())
    return ctx


def theme_css_vars(config):
    """Variables CSS del tema publicado (consumidas por reino.css)."""
    colors = (config or {}).get("colors") or {}
    pairs = services_theme.FONT_PAIRS.get((config or {}).get("font_pair", "manrope"))
    shapes = {"rounded": "22px", "soft": "14px", "sharp": "6px"}
    radius = shapes.get((config or {}).get("shape", "rounded"), "22px")
    parts = [f"--rk-{k}:{v}" for k, v in colors.items() if isinstance(v, str)]
    parts.append(f"--rk-radius:{radius}")
    # Forma de botones elegida en el estudio: cambia la interfaz REAL (A40).
    btn_radii = {"pill": "999px", "rounded": "14px", "square": "4px"}
    parts.append(f"--rk-btn-radius:{btn_radii.get((config or {}).get('buttons', 'pill'), '999px')}")
    parts.append(f"--rk-font-display:'{pairs['display']}',sans-serif")
    parts.append(f"--rk-font-body:'{pairs['body']}',sans-serif")
    return ";".join(parts)
