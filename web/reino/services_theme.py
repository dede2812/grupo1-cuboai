"""Tema de tienda versionado: valores, validación y publicación (§13).

- Toda tienda nace con un tema NEUTRAL utilizable: nunca hereda fotos,
  mascotas ni textos de otra marca (AC10).
- Publicar es explícito y validado (contraste AA de pares de texto, parejas
  tipográficas probadas, módulos conocidos). Un error al publicar no destruye
  la versión visible: la promoción ocurre en una transacción.
- Restaurar crea una NUEVA versión copiando una anterior; el historial no se
  pisa (AC11).
"""

import copy
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from .models import Store, StoreThemeVersion

# Parejas tipográficas probadas (licencias OFL vendoradas en static/reino/fonts).
FONT_PAIRS = {
    "manrope": {"display": "Manrope", "body": "Manrope"},
    "manrope-fraunces": {"display": "Fraunces", "body": "Manrope"},
}
SHAPES = {"rounded", "soft", "sharp"}
BUTTON_STYLES = {"pill", "rounded"}
MODULE_KEYS = {
    "hero", "featured", "occasions", "looklab_entry", "fit_explainer",
    "premium_bar", "policies", "contact",
}

# Identidades iniciales (§9.3). El neutral NO usa activos de ninguna marca.
def default_config(identity="neutral"):
    base = {
        "identity": identity,
        "colors": {
            "ink": "#15172E", "bg": "#FFF8ED", "surface": "#FFFFFF",
            "primary": "#2C3FFF", "on_primary": "#FFFFFF", "accent": "#D6F85A", "soft": "#F1EDE3",
        },
        "font_pair": "manrope",
        "shape": "rounded",
        "buttons": "pill",
        "hero": {"product_id": None, "headline": "", "sub": ""},
        "modules": [
            {"key": "hero", "visible": True},
            {"key": "featured", "visible": True},
            {"key": "occasions", "visible": True},
            {"key": "looklab_entry", "visible": True},
            {"key": "fit_explainer", "visible": True},
            {"key": "premium_bar", "visible": True},
            {"key": "policies", "visible": True},
            {"key": "contact", "visible": True},
        ],
    }
    if identity == "wiener-kingdom":
        base["colors"].update({"primary": "#AF3635", "on_primary": "#FFFFFF", "accent": "#C5CBD5",
                               "bg": "#FAF8F6", "ink": "#101E36", "soft": "#F0EBE8"})
        base["font_pair"] = "manrope-fraunces"
    elif identity == "estudio-nube":
        base["colors"].update({"primary": "#B9A5FF", "on_primary": "#23234A", "accent": "#FBE58A",
                               "bg": "#F7F8FF", "ink": "#23234A", "soft": "#EAE6FF"})
    return base


def _channel(hex_color, i):
    v = int(hex_color[i:i + 2], 16) / 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def luminance(hex_color):
    """Luminancia relativa WCAG de un color #RRGGBB."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError("color inválido")
    r, g, b = _channel(h, 0), _channel(h, 2), _channel(h, 4)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg, bg):
    l1, l2 = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


class ThemeError(Exception):
    """Configuración de tema inválida (mensaje accionable para el editor)."""


def validate_config(config):
    """Valida el borrador antes de publicar (§13). Devuelve lista de errores."""
    errors = []
    colors = config.get("colors") or {}
    for key in ("ink", "bg", "surface", "primary", "accent", "on_primary"):
        value = colors.get(key, "")
        import re
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            errors.append(f"Color «{key}» inválido: usá formato #RRGGBB.")
    if errors:
        return errors
    # Contraste AA de los pares de texto críticos (§13: ofrecer corrección
    # automática antes de publicar; acá se RECHAZA lo ilegible).
    if contrast_ratio(colors["ink"], colors["bg"]) < 4.5:
        errors.append(f"Texto/fondo con contraste insuficiente "
                      f"({contrast_ratio(colors['ink'], colors['bg']):.2f}:1; mínimo 4.5:1).")
    if contrast_ratio(colors["ink"], colors["surface"]) < 4.5:
        errors.append("Texto/tarjeta con contraste insuficiente (mínimo 4.5:1).")
    # F07: el navegador pinta SIEMPRE on_primary sobre primary (botones,
    # chips). Ese par concreto debe pasar AA; no basta con que "algún texto
    # sería posible" si luego el CSS usa blanco fijo.
    on_primary = colors.get("on_primary") or ""
    if on_primary:
        ratio = contrast_ratio(on_primary, colors["primary"])
        if ratio < 4.5:
            errors.append(f"Texto de acción sobre el color de acción con contraste "
                          f"insuficiente ({ratio:.2f}:1; mínimo 4.5:1). Corregí "
                          f"«texto sobre acción» o el color de acción.")
    else:
        # Derivar el mejor par posible si el editor no lo fijó.
        best = max((("#FFFFFF", contrast_ratio("#FFFFFF", colors["primary"])),
                    (colors["ink"], contrast_ratio(colors["ink"], colors["primary"]))),
                   key=lambda t: t[1])
        if best[1] < 4.5:
            errors.append("El color de acción no tiene un texto legible posible (AA).")
    if config.get("font_pair") not in FONT_PAIRS:
        errors.append("Pareja tipográfica no probada.")
    if config.get("shape") not in SHAPES:
        errors.append("Intensidad de formas desconocida.")
    if config.get("buttons") not in BUTTON_STYLES:
        errors.append("Estilo de botones desconocido.")
    known = {m.get("key") for m in config.get("modules") or []}
    if not known or not known <= MODULE_KEYS:
        errors.append("Hay módulos desconocidos en la página.")
    return errors


def current_theme(store):
    """Tema PUBLICADO vigente (o el neutral por defecto si nunca se publicó)."""
    published = store.theme_versions.filter(
        status=StoreThemeVersion.Status.PUBLISHED, is_current=True).first()
    if published:
        return published
    identity = (store.slug if store.slug in ("wiener-kingdom", "estudio-nube")
                else "neutral")
    config = default_config(identity)
    return StoreThemeVersion(store=store, version=0,
                             status=StoreThemeVersion.Status.DRAFT, config=config)


def _next_version(store):
    """Numeración bajo bloqueo de la tienda (nunca count()+1 a ciegas)."""
    Store.objects.select_for_update().get(pk=store.pk)
    last = store.theme_versions.aggregate(m=models.Max("version"))["m"] or 0
    return last + 1


def get_or_create_draft(store, user=None):
    """Borrador de trabajo: copia del publicado vigente o del tema actual.

    F09: un borrador es una versión NUNCA publicada; las publicadas son
    inmutables y no se reutilizan como borrador.
    """
    draft = store.theme_versions.filter(status=StoreThemeVersion.Status.DRAFT).first()
    if draft:
        return draft
    current = current_theme(store)
    with transaction.atomic():
        return StoreThemeVersion.objects.create(
            store=store, version=_next_version(store),
            status=StoreThemeVersion.Status.DRAFT,
            config=copy.deepcopy(current.config), created_by=user,
        )


def publish(store, draft, user=None):
    """Publica un borrador validado; la versión visible anterior queda
    archivada en el historial. Todo en una transacción (§13)."""
    errors = validate_config(draft.config)
    if errors:
        raise ThemeError(" ".join(errors))
    if draft.status != StoreThemeVersion.Status.DRAFT:
        raise ThemeError("Sólo se puede publicar un borrador; las versiones "
                         "publicadas son inmutables.")
    with transaction.atomic():
        # F09: la versión anterior NO se convierte en borrador: queda
        # publicada e inmutable en el historial; sólo deja de ser la vigente.
        store.theme_versions.select_for_update().filter(is_current=True).update(
            is_current=False)
        draft.status = StoreThemeVersion.Status.PUBLISHED
        draft.is_current = True
        draft.published_at = timezone.now()
        draft.save(update_fields=["status", "is_current", "published_at"])
    return draft


def restore(store, version_number, user=None):
    """Restaurar = NUEVA versión publicada copiando una anterior (historial
    intacto). Devuelve la nueva versión."""
    source = store.theme_versions.filter(version=version_number).first()
    if source is None:
        raise ThemeError("Esa versión no existe.")
    with transaction.atomic():
        draft = StoreThemeVersion.objects.create(
            store=store, version=_next_version(store),
            status=StoreThemeVersion.Status.DRAFT,
            config=copy.deepcopy(source.config), created_by=user,
        )
        return publish(store, draft, user=user)


def save_draft_config(draft, config):
    """Guarda un borrador validando que NO sea una versión publicada (F09)."""
    draft.refresh_from_db()
    if draft.status != StoreThemeVersion.Status.DRAFT:
        raise ThemeError("Esa versión ya fue publicada y es inmutable; "
                         "se creó un borrador nuevo para tus cambios.")
    draft.config = config
    draft.save(update_fields=["config"])
    return draft
