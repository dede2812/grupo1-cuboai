"""Búsqueda y exploración por REGLAS (P01/P04): funciona sin clave de IA.

- Cubre todo el catálogo PUBLICADO de Reino (varias tiendas), con la demo
  separada del catálogo comercial (P01, AC26).
- Tolerante a tildes (normalización Unicode) y consultas comunes.
- Filtros visibles y compartibles por URL (GET), sin datos privados.
- «regalo por menos de $30» se interpreta por reglas cuando es posible
  (precio máximo detectado) y siempre como filtros visibles y editables.
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from .models import CategorySchema, Product, Store
from . import services_visibility as visibility
from .money import fmt


def normalize(text):
    """Minúsculas sin tildes: «arnes» encuentra «Arnés»."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", (text or "").lower())
        if not unicodedata.combining(ch)
    )


_PRICE_RE = re.compile(r"(?:menos de|hasta|max(?:imo)?|menor a|por debajo de)?\s*\$?\s*(\d+(?:[.,]\d{1,2})?)\s*(?:dolares|usd)?$", re.IGNORECASE)


def parse_query(text):
    """Extrae intención estructurada de una consulta libre (reglas)."""
    raw = (text or "").strip()
    out = {"text": raw, "max_price": None, "occasion": None}
    m = re.search(r"(?:menos de|hasta|máximo|maximo|max) \$?\s*(\d+(?:[.,]\d{1,2})?)", normalize(raw))
    if m:
        try:
            out["max_price"] = Decimal(m.group(1).replace(",", "."))
            raw = re.sub(r"(?i)(por )?(menos de|hasta|máximo|maximo|max) \$?\s*\d+(?:[.,]\d{1,2})?", "", raw).strip()
            out["text"] = raw
        except InvalidOperation:
            pass
    for occasion in ("paseo", "celebracion", "fotos", "diario", "casa", "lluvia"):
        if occasion in normalize(raw):
            out["occasion"] = occasion
            break
    return out


def search_catalog(query="", store=None, occasion="", max_price=None,
                   category="", include_demo=False, limit=48):
    """Catálogo publicado; cada resultado declara su tienda y su estado."""
    parsed = parse_query(query) if query else {"text": "", "max_price": None, "occasion": None}
    max_price = max_price if max_price is not None else parsed["max_price"]
    occasion = occasion or parsed["occasion"] or ""
    # F06: la visibilidad es la política CENTRALIZADA (negocio + tienda +
    # publicación), no un filtro local de esta vista.
    qs = (visibility.visible_products(store=store, include_demo=include_demo)
          .select_related("store").prefetch_related("media", "variants"))
    if category:
        qs = qs.filter(store__category__icontains=category)
    if occasion:
        qs = [p for p in qs if occasion in (p.occasions or [])]
    if max_price is not None:
        qs = [p for p in qs if p.base_price <= max_price]
    needle = normalize(parsed["text"])
    if needle:
        # Palabras de relleno frecuentes en consultas sugeridas («algo para
        # paseo»): NO son criterio AND o eliminarían resultados válidos.
        stop = {"algo", "para", "una", "unos", "unas", "con", "que", "del",
                "los", "las", "por", "mis", "muy", "mas", "esto", "esta",
                "este", "estos", "quiero", "busco", "necesito", "regalo"}
        terms = [t for t in needle.split() if len(t) > 2 and t not in stop]
        if terms:
            qs = [p for p in qs if all(
                t in normalize(" ".join([p.title, p.short_title, p.description or "",
                                         " ".join(p.materials or []), p.store.name]))
                for t in terms)]
    results = []
    for p in list(qs)[:limit]:
        active = [v for v in p.variants.all() if v.is_active]
        prices = [v.price for v in active] or [p.base_price]
        media = p.media.first()
        results.append({
            "product": p,
            "store": p.store,
            "price_from": fmt(min(prices), p.store.currency),
            "varies": len(set(prices)) > 1,
            "image": media.path if media else "",
            "alt": media.alt if media else p.short_title,
            "available": any(v.stock > 0 for v in active),
        })
    return results


def annotate_stores(stores):
    """Anota portada propia y muestra de productos REALES por tienda (P02).

    La portada sale del catálogo de ESA tienda; una tienda sin fotos muestra
    la escena neutra de su tema, nunca el activo de otra marca (AC10).
    """
    for store in stores:
        sample = list(visibility.visible_products(store=store)
                      .prefetch_related("media").order_by("-is_featured", "short_title")[:2])
        store.sample_products = sample
        store.cover_product = sample[0] if sample else None
    return stores


def explore_home():
    """Datos del descubrimiento (P01): todo desde la base, nunca listas
    escondidas en plantillas. Demo separada; si hay una sola tienda activa se
    presenta con orgullo, sin fabricar escala."""
    stores = annotate_stores(list(visibility.visible_stores(include_demo=False)))
    demo = annotate_stores(list(Store.objects.filter(status=Store.Status.DEMO, is_demo=True,
                                                     merchant__status__in=("pilot", "active"))))
    featured = []
    for store in stores:
        product = (visibility.visible_products(store=store).filter(is_featured=True)
                   .prefetch_related("media", "variants").first()
                   or visibility.visible_products(store=store)
                   .prefetch_related("media", "variants").first())
        if product:
            featured.append({"store": store, "product": product})
    categories = CategorySchema.objects.prefetch_related("definitions").all()
    return {"stores": stores, "demo_stores": demo, "featured": featured,
            "categories": categories}
