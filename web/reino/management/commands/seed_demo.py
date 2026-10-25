"""Seed controlado de datos de demostración (P0).

Crea las dos tiendas de la demo: Wiener Kingdom (catálogo real histórico,
fotos reales del repo) y Estudio Nube Demo (papelería ficticia, identificada
como datos de prueba, sin cobros reales).

Uso normal (no destructivo):  python manage.py seed_demo
Recrear desde cero:           python manage.py seed_demo --reset

Seguridad (auditoría §9.5): el borrado total exige --reset y jamás corre en
producción (DEBUG=False) sin la variable REINO_ALLOW_SEED=1. La elegibilidad
Bitcoin se MIGRA de la regla histórica (tienda.ProductPaymentRule), no se
inventa. El stock del seed es de DEMOSTRACIÓN, nunca inventario confirmado.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from reino.models import (
    AttributeDefinition, AttributeValue, CategorySchema, DigitalAsset, FitRule,
    KnowledgeDocument, Merchant, MerchantMember, Product, ProductMedia, ServiceSlot,
    ShippingZone, Store, StoreThemeVersion, Variant,
)

# Tabla de tallas histórica del negocio (tienda/migrations/0011): subset dachshund.
SIZES_DOG = [
    {"label": "XS", "neck_min": 18, "neck_max": 23, "chest_min": 28, "chest_max": 34, "back_min": 20, "back_max": 26},
    {"label": "S", "neck_min": 22, "neck_max": 27, "chest_min": 33, "chest_max": 40, "back_min": 25, "back_max": 32},
    {"label": "M", "neck_min": 26, "neck_max": 31, "chest_min": 39, "chest_max": 46, "back_min": 31, "back_max": 38},
    {"label": "L", "neck_min": 35, "neck_max": 41, "chest_min": 52, "chest_max": 61, "back_min": 41, "back_max": 49},
]

# Catálogo histórico de Wiener Kingdom (fuente: tienda/catalog.py).
WK_PRODUCTS = [
    {
        "slug": "wedding-dog", "legacy_slug": "wedding-dog",
        "title": "Waterproof Linen Dachshund Wedding Dog Suit Pair for Two",
        "short_title": "Wedding Dog", "base_price": "650.00",
        "subtitle": "Un traje pequeño para tus momentos más grandes.",
        "description": "Vestuario formal elegante para dachshunds, diseñado para bodas, celebraciones especiales y momentos inolvidables con tu mejor amigo.",
        "category": "formal", "occasions": ["celebracion", "fotos"], "styles": ["party-royalty", "royal-classic"],
        "is_featured": True, "reason": "Pieza de ocasión especial con materiales de acabado formal.",
        "images": [("tienda/img/wedding-dog.jpg", "Traje formal Wedding Dog para dachshund", "product")],
        "materials": ["Satén Duchess de poliéster premium", "Forro de satén Bemberg", "Encaje Chantilly bordado", "Cierre invisible YKK"],
        "care": ["Limpieza en seco recomendada", "Guardar colgado lejos de humedad"],
    },
    {
        "slug": "tactical-dog", "legacy_slug": "tactical-dog",
        "title": "Tactical Dog", "short_title": "Tactical Dog", "base_price": "300.00",
        "subtitle": "Hecho para la aventura. Estilo de realeza.",
        "description": "Un look audaz y funcional para dachshunds con personalidad intrépida, pensado para darle estilo distintivo a las aventuras de cada día.",
        "category": "aventura", "occasions": ["paseo", "diario"], "styles": ["little-adventurer"],
        "is_featured": True, "reason": "Textil técnico de alta resistencia al desgaste (Cordura 1000D).",
        "images": [("tienda/img/tactical-dog.jpg", "Conjunto Tactical Dog para dachshund", "product")],
        "materials": ["Nylon Cordura 1000D", "Forro de malla 3D transpirable", "Hebillas Duraflex", "Panel acolchado de espuma EVA"],
        "care": ["Lavar a mano con jabón suave", "Secar a la sombra"],
    },
    {
        "slug": "christmas-dog", "legacy_slug": "christmas-dog",
        "title": "Christmas Dog", "short_title": "Christmas Dog", "base_price": "250.00",
        "subtitle": "Que cada celebración sea mágica.",
        "description": "Un look festivo para reuniones de temporada, fotos familiares y celebraciones memorables con tu pequeño compañero.",
        "category": "formal", "occasions": ["celebracion", "fotos"], "styles": ["party-royalty"],
        "images": [("tienda/img/christmas-dog.jpg", "Conjunto festivo Christmas Dog", "product")],
        "materials": ["Terciopelo de poliéster premium", "Tela tartán escocés premium", "Cierre YKK"],
        "care": ["Lavar a mano en frío", "No planchar el ribete"],
    },
    {
        "slug": "alnut-whip-harness", "legacy_slug": "alnut-whip-harness",
        "title": "Walnut Whip Dachshund Harness Fleece", "short_title": "Walnut Whip Harness",
        "base_price": "250.00", "subtitle": "Fleece suave por fuera, forro cálido por dentro.",
        "description": "Arnés estilo fleece con capa exterior suave, forro cálido y detalles duraderos.",
        "category": "arnes", "occasions": ["paseo", "diario"], "styles": ["little-adventurer", "urban-king"],
        "images": [
            ("tienda/img/alnut-whip-1.jpg", "Arnés Walnut Whip color fleece, vista frontal", "product"),
            ("tienda/img/alnut-whip-2.jpg", "Arnés Walnut Whip, segundo ángulo", "detail"),
        ],
        "materials": ["Polar fleece premium antipilling", "Forro térmico transpirable", "Hebillas de liberación rápida"],
        "care": ["Lavar a máquina ciclo suave", "No usar secadora"],
    },
    {
        "slug": "beige-anti-rub-harness", "legacy_slug": "beige-anti-rub-harness",
        "title": "Beige Sophisticated Sausage Dachshund Anti-Rub Dog Harness",
        "short_title": "Beige Anti-Rub Harness", "base_price": "63.00",
        "subtitle": "Comodidad acolchada con bordes suaves.",
        "description": "Arnés beige acolchado con bordes suaves y herrajes duraderos.",
        "category": "arnes", "occasions": ["paseo", "diario"], "styles": ["urban-king", "royal-classic"],
        "is_featured": True, "reason": "Ribete suave pensado para no pellizcar en paseos largos.",
        "images": [
            ("tienda/img/beige-harness-2.jpg", "Arnés beige anti-rozaduras, fotografía principal", "product"),
            ("tienda/img/beige-harness-1.jpg", "Arnés beige, miniatura de referencia", "detail"),
        ],
        "materials": ["Tejido beige premium resistente", "Espuma de acolchado", "Ribete suave antipellizcos"],
        "care": ["Lavar a mano", "Secar al aire"],
    },
    {
        "slug": "tutti-frutti-harness", "legacy_slug": "tutti-frutti-harness",
        "title": "Tutti Frutti Houndstooth Anti-Rub Harness – Ribbon",
        "short_title": "Tutti Frutti Harness", "base_price": "63.00",
        "subtitle": "Estampado pata de gallo con acabado de cinta.",
        "description": "Arnés estampado con cinta decorativa multicolor y acabado anti-rozaduras.",
        "category": "arnes", "occasions": ["paseo", "fotos"], "styles": ["urban-king", "party-royalty"],
        "images": [("tienda/img/tutti-frutti-1.jpg", "Arnés Tutti Frutti pata de gallo", "product")],
        "materials": ["Tejido premium pata de gallo", "Cinta decorativa multicolor", "Ribete suave de acabado"],
        "care": ["Lavar a mano", "Secar al aire"],
    },
    {
        "slug": "cable-knit-jumper", "legacy_slug": "cable-knit-jumper",
        "title": "Luxury Cable Knit Dachshund Jumper", "short_title": "Cable Knit Jumper",
        "base_price": "150.00", "subtitle": "Abrigo tejido con acabados de punto.",
        "description": "Suéter tejido cable-knit hecho con una mezcla de fibras premium y acabados de punto.",
        "category": "abrigo", "occasions": ["diario", "fotos"], "styles": ["royal-classic", "urban-king"],
        "is_featured": True, "reason": "Mezcla de lana merino y alpaca: abrigo con fibras naturales.",
        "images": [("tienda/img/cable-knit-jumper-1.jpg", "Suéter Cable Knit para dachshund", "product")],
        "materials": ["Hilo premium de lana merino", "Hilo de mezcla de alpaca", "Botones decorativos premium"],
        "care": ["Lavar a mano en frío", "Secar horizontalmente"],
    },
    {
        "slug": "bamboo-drying-robe", "legacy_slug": "bamboo-drying-robe",
        "title": "Showercover Bamboo Dachshund Drying Robe", "short_title": "Bamboo Drying Robe",
        "base_price": "88.00", "subtitle": "Tela de bambú absorbente, acabados suaves.",
        "description": "Bata absorbente hecha con tela de fibra de bambú, cierre ajustable y acabados suaves.",
        "category": "cuidado", "occasions": ["diario"], "styles": ["little-adventurer"],
        "images": [
            ("tienda/img/drying-robe-1.jpg", "Bata de secado de bambú, vista frontal", "product"),
            ("tienda/img/drying-robe-2.jpg", "Bata de bambú, segundo ángulo", "detail"),
            ("tienda/img/drying-robe-3.jpg", "Bata de bambú, detalle de tela", "detail"),
        ],
        "materials": ["Tela de rizo con fibra de bambú", "Velcro suave de contacto", "Ribete de algodón premium"],
        "care": ["Lavar a máquina ciclo suave", "No usar cloro"],
    },
]

# Estudio Nube Demo — papelería y regalos FICTICIOS (datos de prueba).
NUBE_PRODUCTS = [
    {
        "slug": "cuaderno-puntos", "title": "Cuaderno de puntos A5 «Niebla»",
        "short_title": "Cuaderno Niebla", "base_price": "12.00",
        "subtitle": "Papel de 100 g, 160 páginas de puntos.",
        "description": "Cuaderno A5 de tapa suave con cuadrícula de puntos para journaling y bocetos. Producto de demostración.",
        "category": "papeleria", "occasions": ["diario", "regalo"], "styles": [],
        "reason": "Papel de 100 g que resiste plumas de gel sin traspasar.",
        "images": [("reino/img/nube/cuaderno.jpg", "Cuaderno A5 de puntos color niebla", "product")],
    },
    {
        "slug": "set-stickers", "title": "Set de stickers «Nubes y soles»",
        "short_title": "Set de stickers", "base_price": "6.00",
        "subtitle": "24 stickers troquelados resistentes al agua.",
        "description": "Set de 24 stickers troquelados con acabado mate. Producto de demostración.",
        "category": "papeleria", "occasions": ["regalo", "diario"], "styles": [],
        "reason": "Vinilo resistente al agua, apto para botellas y laptops.",
        "images": [("reino/img/nube/stickers.jpg", "Set de stickers de nubes y soles", "product")],
    },
    {
        "slug": "tarjeta-regalo", "title": "Tarjeta de regalo «Gracias»",
        "short_title": "Tarjeta Gracias", "base_price": "4.50",
        "subtitle": "Tarjeta doblada con sobre kraft.",
        "description": "Tarjeta doblada impresa en papel texturizado con sobre kraft. Producto de demostración.",
        "category": "regalos", "occasions": ["regalo", "celebracion"], "styles": [],
        "reason": "Papel texturizado de 300 g con sobre incluido.",
        "images": [("reino/img/nube/tarjeta.jpg", "Tarjeta de regalo con sobre kraft", "product")],
    },
    {
        "slug": "planner-semanal", "title": "Planner semanal «Horizonte»",
        "short_title": "Planner Horizonte", "base_price": "18.00",
        "subtitle": "52 semanas sin fecha, con separadores.",
        "description": "Planner semanal sin fecha con separadores de mes y bolsillo interior. Producto de demostración.",
        "category": "papeleria", "occasions": ["diario"], "styles": [],
        "reason": "Formato sin fecha: empezá cualquier semana del año.",
        "images": [("reino/img/nube/planner.jpg", "Planner semanal abierto", "product")],
    },
    {
        "slug": "set-plumas", "title": "Set de 3 plumas gel «Tinta firme»",
        "short_title": "Set de plumas", "base_price": "14.00",
        "subtitle": "Tinta negra de 0.5 mm, trazo seco rápido.",
        "description": "Set de tres plumas de gel de trazo fino y secado rápido. Producto de demostración.",
        "category": "escritura", "occasions": ["diario", "regalo"], "styles": [],
        "reason": "Secado rápido para zurdos y notas ágiles.",
        "images": [("reino/img/nube/plumas.jpg", "Tres plumas de gel", "product")],
    },
    {
        "slug": "caja-regalo", "title": "Caja de regalo «Nube grande»",
        "short_title": "Caja Nube grande", "base_price": "25.00",
        "subtitle": "Caja rígida con papel de seda y tarjeta.",
        "description": "Caja rígida de regalo con papel de seda, moño y tarjeta en blanco. Producto de demostración.",
        "category": "regalos", "occasions": ["regalo", "celebracion"], "styles": [],
        "reason": "Caja rígida reutilizable con cierre magnético.",
        "images": [("reino/img/nube/caja.jpg", "Caja de regalo con moño", "product")],
    },
]

WK_KNOWLEDGE = [
    ("tallas", "Guía de tallas para dachshund",
     "Medí a tu perro de pie y relajado. Pecho: la parte más ancha del torso, detrás de las patas delanteras. "
     "Largo de espalda: desde la base del cuello hasta la base de la cola. Cuello: donde asienta el collar. "
     "La cinta debe quedar ajustada pero sin apretar (dos dedos de holgura). Si tu perro está entre dos tallas, "
     "revisá la tabla del producto: cada prenda tiene sus propios rangos. Esta guía es la versión v1 aprobada para la demo."),
    ("envios", "Política de entrega",
     "Ofrecemos retiro coordinado en La Madriguera Café, San Benito (San Salvador) sin costo. "
     "La entrega a domicilio en San Salvador tiene una tarifa por zona que se muestra antes de confirmar el pedido. "
     "Los tiempos de preparación se confirman por pedido; ninguna fecha es garantía hasta la confirmación del equipo."),
    ("cambios", "Cambios y devoluciones",
     "Si la talla no funciona, escribinos dentro de los 7 días posteriores a la entrega con tu número de pedido. "
     "Las prendas deben estar sin uso y con sus etiquetas. Las piezas hechas a medida (cotización) se revisan caso por caso. "
     "Versión v1 de demostración; el negocio confirma la política definitiva."),
    ("compra", "Cómo comprar y pagar",
     "Podés pagar con pago manual coordinado (transferencia o efectivo contra entrega) o Bitcoin con un 15 % de descuento "
     "sobre la mercancía, que se aplica cuando el equipo verifica el pago. Todo pedido queda registrado como pendiente de "
     "verificación hasta que el equipo confirma el pago. Ningún cobro electrónico está habilitado en esta demostración."),
    ("cuidado", "Cuidado de las prendas",
     "Cada ficha indica el cuidado específico de sus materiales. Como regla general: lavar a mano o ciclo suave con "
     "jabón neutro, secar a la sombra y evitar secadora. Las piezas formales (satén, encaje) se recomiendan en limpieza en seco."),
]

NUBE_KNOWLEDGE = [
    ("envios", "Entregas (demo)",
     "Tienda de demostración: las entregas se coordinan por retiro sin costo. Contenido de prueba, sin cobros reales."),
    ("cambios", "Cambios (demo)",
     "Tienda de demostración: política de cambios de ejemplo. Contenido de prueba."),
]


class Command(BaseCommand):
    help = "Crea las tiendas de demostración de Reino Commerce (Wiener Kingdom y Estudio Nube Demo)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="BORRA todos los datos de reino antes de sembrar (destructivo).")

    def handle(self, *args, **options):
        import os
        from django.conf import settings
        from reino import models as m

        if options["reset"]:
            if not settings.DEBUG and os.environ.get("REINO_ALLOW_SEED") != "1":
                raise SystemExit(
                    "Bloqueado: --reset con DEBUG=False requiere REINO_ALLOW_SEED=1 "
                    "(protección contra borrado accidental en producción).")
            # Limpieza controlada de datos reino (orden por dependencias).
            for model in (m.OrderEvent, m.OrderItem, m.Order, m.StockReservation,
                          m.CheckoutSession, m.CartItem, m.Cart, m.RecommendationEvent,
                          m.AIMessage, m.AIConversation, m.ActionToken, m.Look,
                          m.MemorySummary, m.Preference, m.Consent, m.Measurement,
                          m.RecipientProfile, m.KnowledgeDocument, m.OutboxEvent,
                          m.ProductMedia, m.StockAdjustment, m.Variant,
                          m.FitRule, m.Product, m.ShippingZone, m.MerchantMember,
                          m.AnalyticsEvent, m.ComparisonSession, m.MediaAsset,
                          m.AttributeValue, m.AttributeDefinition, m.CategorySchema,
                          m.StoreThemeVersion, m.IntegrationState,
                          m.Booking, m.ServiceSlot, m.DigitalGrant, m.DigitalAsset,
                          m.Store, m.Merchant):
                model.objects.all().delete()
        elif Store.objects.filter(slug__in=("wiener-kingdom", "estudio-nube")).exists():
            self.stdout.write(self.style.WARNING(
                "Las tiendas demo ya existen; no se borra nada. "
                "Usá --reset para recrear desde cero (destructivo)."))
            return

        wk_merchant = Merchant.objects.create(
            name="Wiener Kingdom", country="El Salvador",
            contact_email="fiorellalarios17@gmail.com", status=Merchant.Status.PILOT,
        )
        wk = Store.objects.create(
            merchant=wk_merchant, slug="wiener-kingdom", name="Wiener Kingdom",
            tagline="Estilo propio. Medidas que importan.",
            promise="Cada pequeño rey merece su reino.",
            description="Boutique de moda y accesorios para dachshunds con orientación de talla.",
            currency="USD", locale="es-SV", category="moda canina",
            status=Store.Status.ACTIVE, is_demo=False,
            contact_email="fiorellalarios17@gmail.com", contact_phone="+503 7546-7119",
            pickup_address="La Madriguera Café, San Benito, San Salvador",
        )
        self._seed_wk(wk)

        nube_merchant = Merchant.objects.create(
            name="Estudio Nube Demo", country="El Salvador", status=Merchant.Status.PILOT,
        )
        nube = Store.objects.create(
            merchant=nube_merchant, slug="estudio-nube", name="Estudio Nube",
            tagline="Papelería y regalos de demostración.",
            description="Tienda ficticia para demostrar Reino Commerce fuera de la moda canina. "
                        "Todo su contenido es de prueba y no está habilitada para cobros reales.",
            currency="USD", locale="es-SV", category="papeleria",
            status=Store.Status.DEMO, is_demo=True,
            pickup_address="Retiro coordinado (demo)",
        )
        self._seed_nube(nube)

        staff, created = User.objects.get_or_create(username="demo_staff")
        staff.is_staff = True
        staff.set_password("demo1234")  # credencial de DEMOSTRACIÓN, documentada en README
        staff.save()
        MerchantMember.objects.get_or_create(user=staff, merchant=wk_merchant,
                                             defaults={"role": MerchantMember.Role.OWNER})
        MerchantMember.objects.get_or_create(user=staff, merchant=nube_merchant,
                                             defaults={"role": MerchantMember.Role.OWNER})

        # Temas PUBLICADOS con identidad propia por tienda (§9.3, AC10) y
        # esquemas de categoría con atributos tipados para el comparador (§15).
        self._seed_themes(wk, nube)
        self._seed_schemas(wk, nube)
        self._seed_demo_market()

        self.stdout.write(self.style.SUCCESS(
            f"Seed OK: {wk.products.count()} productos WK, {nube.products.count()} Nube. "
            "Panel: usuario demo_staff / demo1234 (solo demo)."
        ))

    def _seed_themes(self, wk, nube):
        from reino import services_theme
        for store, identity in ((wk, "wiener-kingdom"), (nube, "estudio-nube")):
            config = services_theme.default_config(identity)
            if identity == "wiener-kingdom":
                config["hero"]["headline"] = "Pequeño perro. Mucha actitud."
                config["hero"]["sub"] = ("Moda y accesorios para dachshunds con "
                                         "orientación de talla por medidas.")
            draft = StoreThemeVersion.objects.create(
                store=store, version=1, config=config)
            services_theme.publish(store, draft)

    def _seed_schemas(self, wk, nube):
        moda = CategorySchema.objects.create(slug="moda-canina", name="Moda canina")
        materiales = AttributeDefinition.objects.create(
            schema=moda, key="material_principal", label="Material principal",
            value_type="option", options=["algodón", "bambú", "lana", "poliéster", "mezclilla"],
            position=1)
        AttributeDefinition.objects.create(
            schema=moda, key="peso_prenda", label="Peso de la prenda",
            value_type="measure", unit="g", position=2)
        AttributeDefinition.objects.create(
            schema=moda, key="lavable_maquina", label="Lavable a máquina",
            value_type="boolean", position=3)
        pape = CategorySchema.objects.create(slug="papeleria", name="Papelería")
        tamano = AttributeDefinition.objects.create(
            schema=pape, key="tamano_papel", label="Tamaño",
            value_type="option", options=["A5", "A6", "carta", "sticker"], position=1)
        AttributeDefinition.objects.create(
            schema=pape, key="hojas", label="Cantidad de hojas/piezas",
            value_type="decimal", position=2)
        # Fixture de una TERCERA categoría: demuestra extensión sin cascadas
        # condicionales (AC10/§15); no se publica como tienda ficticia.
        CategorySchema.objects.create(slug="hogar-fixture", name="Hogar (fixture)")

        def attr(product, definition, raw, unit="", normalized=None, source="seed demo"):
            AttributeValue.objects.create(
                product=product, definition=definition,
                value={"raw": raw, "unit": unit}, normalized_number=normalized,
                source=source)
        for p in wk.products.all():
            material = (p.materials or ["algodón"])[0] if p.materials else "algodón"
            attr(p, materiales, material)
        for p in nube.products.all():
            attr(p, tamano, "A5")

    def _seed_demo_market(self):
        """Entorno DEMO separado (§5): seis categorías físicas, un digital
        descargable y un servicio reservable — todo identificado como prueba,
        sin cobros reales y sin mezclarse con el catálogo histórico de WK."""
        from datetime import timedelta

        from django.core.files.base import ContentFile
        from django.utils import timezone as tz

        merchant = Merchant.objects.create(
            name="Reino Demo Market", country="El Salvador", status=Merchant.Status.PILOT)
        store = Store.objects.create(
            merchant=merchant, slug="mercado-demo", name="Mercado Demo",
            tagline="Vitrina de categorías de demostración.",
            description="Productos FICTICIOS para demostrar las capacidades de "
                        "Reino Commerce por categoría. Sin cobros reales.",
            currency="USD", locale="es-SV", category="varios",
            status=Store.Status.DEMO, is_demo=True,
            pickup_address="Retiro coordinado (demo)",
        )
        ShippingZone.objects.create(store=store, name="Retiro", mode="pickup", fee=0)

        def prod(slug, title, price, category, offer="physical", **kw):
            p = Product.objects.create(
                store=store, slug=slug, title=title, short_title=title,
                base_price=price, status="published", category=category,
                offer_type=offer, reason="Producto ficticio de demostración",
                description=f"Producto de demostración de la categoría {category}. "
                            "Contenido ficticio, sin venta real.",
                **kw)
            Variant.objects.create(product=p, sku=f"{slug[:10].upper()}-STD",
                                   option_label=kw.get("option", "Estándar"), stock=8)
            return p

        # Seis categorías FÍSICAS (§5)
        prod("lampara-mesa-demo", "Lámpara de mesa Demo", "32.00", "hogar",
             materials=["metal"], shipping_note="Caja 30×18×18 cm (demo)")
        prod("cable-usbc-demo", "Cable USB-C trenzado Demo", "12.50", "tecnologia")
        prod("jabon-avena-demo", "Jabón de avena Demo", "6.00", "cuidado personal")
        prod("cuaderno-puntos-demo", "Cuaderno de puntos Demo", "14.00", "papeleria")
        prod("camiseta-crema-demo", "Camiseta crema Demo", "18.00", "moda humana")
        prod("rompecabezas-mapa-demo", "Rompecabezas mapa Demo", "21.00", "juguetes")

        # Un producto DIGITAL descargable (tras pago exigido; token+expira)
        guia = prod("guia-cartas-demo", "Guía de caligrafía (PDF) Demo", "9.00",
                    "digital", offer="digital")
        DigitalAsset.objects.create(
            product=guia, version="1.0-demo",
            file=ContentFile(b"%PDF-1.4\n% Guia de caligrafia DEMO (ficticia)\n",
                             name="guia-caligrafia-demo.pdf"),
            license_note="Contenido ficticio de demostración; sin licencia real.")

        # Un SERVICIO reservable con franjas de capacidad 2
        taller = prod("taller-lettering-demo", "Taller de lettering (cupo) Demo", "25.00",
                      "servicio", offer="service")
        v = taller.variants.get()
        v.sku = "TALLER-DEMO"
        v.save(update_fields=["sku"])
        for days, hour in ((3, 15), (10, 15)):
            ServiceSlot.objects.create(
                product=taller, starts_at=tz.now() + timedelta(days=days),
                duration_minutes=90, capacity=2)

        # Tema neutral publicado (sin herencia de WK/Nube, AC10)
        from reino import services_theme
        draft = StoreThemeVersion.objects.create(
            store=store, version=1, status=StoreThemeVersion.Status.DRAFT,
            config=services_theme.default_config("neutral"))
        services_theme.publish(store, draft)
        self.stdout.write(self.style.SUCCESS(
            f"Demo market: {store.products.count()} ofertas de prueba (6 físicas + digital + servicio)."))

    def _seed_wk(self, store):
        from tienda.models import ProductPaymentRule
        for data in WK_PRODUCTS:
            images = data.pop("images")
            materials = data.pop("materials")
            care = data.pop("care")
            # Elegibilidad Bitcoin MIGRADA de la regla histórica vigente (R05):
            # solo las piezas que el negocio habilitó (cable-knit-jumper y
            # bamboo-drying-robe); sin regla histórica => no participa.
            legacy = data.get("legacy_slug", "")
            rule = ProductPaymentRule.objects.filter(product_slug=legacy).first()
            data["bitcoin_discount_eligible"] = bool(
                rule and rule.bitcoin_discount_eligible)
            product = Product.objects.create(
                store=store, status=Product.Status.PUBLISHED,
                materials=materials, care=care, **data,
            )
            FitRule.objects.create(
                product=product, version=1, ranges=SIZES_DOG,
                ease_note="La cinta debe quedar ajustada pero sin apretar (dos dedos de holgura).",
                approved_by="seed demo (tabla histórica del negocio)",
            )
            for size in SIZES_DOG:
                Variant.objects.create(
                    product=product, sku=f"{data['slug'].upper()[:12]}-{size['label']}",
                    option_label=f"Talla {size['label']}", stock=5,
                )
            for pos, (path, alt, kind) in enumerate(images):
                ProductMedia.objects.create(product=product, path=path, alt=alt,
                                            kind=kind, position=pos,
                                            source="fotografía real del repositorio")
        for topic, title, body in WK_KNOWLEDGE:
            KnowledgeDocument.objects.create(
                store=store, topic=topic, title=title, body=body,
                version="v1", is_published=True, approved_by="seed demo",
                published_at=timezone.now(),
            )
        ShippingZone.objects.create(store=store, name="Retiro · La Madriguera Café, San Benito",
                                    mode="pickup", fee=Decimal("0"),
                                    eta_note="Se coordina al confirmar el pedido")
        # Tarifa hipotética de demostración (pendiente de aprobación del negocio).
        ShippingZone.objects.create(store=store, name="San Salvador (demo)",
                                    mode="local", fee=Decimal("3.50"),
                                    eta_note="1–3 días hábiles (por confirmar)")

    def _seed_nube(self, store):
        for data in NUBE_PRODUCTS:
            images = data.pop("images")
            product = Product.objects.create(store=store, status=Product.Status.PUBLISHED,
                                             materials=[], care=[], **data)
            Variant.objects.create(product=product, sku=f"NUBE-{data['slug'].upper()[:16]}",
                                   option_label="Único", stock=12)
            for pos, (path, alt, kind) in enumerate(images):
                ProductMedia.objects.create(
                    product=product, path=path, alt=alt, kind=kind, position=pos,
                    source="imagen generada — contenido de demostración",
                )
        for topic, title, body in NUBE_KNOWLEDGE:
            KnowledgeDocument.objects.create(
                store=store, topic=topic, title=title, body=body,
                version="v1", is_published=True, approved_by="seed demo",
                published_at=timezone.now(),
            )
        ShippingZone.objects.create(store=store, name="Retiro (demo)", mode="pickup",
                                    fee=Decimal("0"), eta_note="Contenido de prueba")
