"""Reino Commerce — modelo de datos multi-tienda (P0).

Decisiones clave (ver docs/02_ARQUITECTURA_Y_DATOS.md):
- Merchant es el tenant; en P0 cada Merchant tiene una Store.
- Todo registro de negocio cuelga de store (tenant) y las consultas se hacen
  siempre con el store resuelto en servidor (fail-closed sin tenant).
- Dinero en Decimal con una única política de redondeo (ver reino.money).
- Los snapshots de pedido no cambian al editar el catálogo.
"""

import uuid

from django.db import models
from django.conf import settings
from django.utils import timezone


class CustomerIdentity(models.Model):
    """Opaque customer owner key, independent of browser session rotation."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="customer_identity")
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def owner_key(self):
        return "customer:" + self.public_id.hex


class AIUsageCounter(models.Model):
    """Atomic fixed-window quotas; keys contain only hashed owner identifiers."""

    key = models.CharField(max_length=160, unique=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)


class Merchant(models.Model):
    """Comercio (tenant). Propietario contractual de una o más tiendas."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PILOT = "pilot", "Piloto"
        ACTIVE = "active", "Activo"
        SUSPENDED = "suspended", "Suspendido"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=120)
    country = models.CharField(max_length=80, default="El Salvador")
    contact_email = models.EmailField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Permiso global EXPLÍCITO de operador de plataforma (N11, §8.4): se
        # concede solo al operador; is_staff o pertenecer a un comercio no lo
        # otorgan ni lo heredan.
        permissions = [("operate_platform", "Puede operar la administración global de la plataforma")]

    def __str__(self):
        return self.name


class Store(models.Model):
    """Tienda pública de un Merchant. slug único; estado demo nunca cobra."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        DEMO = "demo", "Demostración"
        ACTIVE = "active", "Activa"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.PROTECT, related_name="stores")
    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    tagline = models.CharField(max_length=160, blank=True)
    promise = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    currency = models.CharField(max_length=3, default="USD")
    locale = models.CharField(max_length=10, default="es-SV")
    category = models.CharField(max_length=60, default="general")
    is_demo = models.BooleanField(default=False)  # contenido de prueba, sin cobros reales
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    pickup_address = models.CharField(max_length=200, blank=True)
    theme = models.JSONField(default=dict)  # tokens de marca por tienda
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} (/s/{self.slug}/)"


class MerchantMember(models.Model):
    """Membresía usuario↔tenant con rol. Unicidad usuario+tenant."""

    class Role(models.TextChoices):
        OWNER = "owner", "Propietario"
        STAFF = "staff", "Equipo"
        LOGISTICS = "logistics", "Logística"

    user = models.ForeignKey("auth.User", on_delete=models.CASCADE, related_name="memberships")
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name="members")
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.STAFF)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "merchant")

    def __str__(self):
        return f"{self.user} @ {self.merchant} ({self.role})"


# ---------------------------------------------------------------- catálogo --

class Product(models.Model):
    """Producto publicado en una tienda (catálogo en base de datos)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PUBLISHED = "published", "Publicado"
        ARCHIVED = "archived", "Archivado"

    class OfferType(models.TextChoices):
        PHYSICAL = "physical", "Físico"
        DIGITAL = "digital", "Digital"
        SERVICE = "service", "Servicio con cita"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="products")
    slug = models.SlugField(max_length=80)
    offer_type = models.CharField(max_length=10, choices=OfferType.choices,
                                  default=OfferType.PHYSICAL)
    legacy_slug = models.CharField(max_length=50, blank=True)  # enlace con catálogo histórico
    title = models.CharField(max_length=160)
    short_title = models.CharField(max_length=80)
    subtitle = models.CharField(max_length=200, blank=True)  # beneficio verificable
    description = models.TextField(blank=True)
    category = models.CharField(max_length=40, default="general")
    occasions = models.JSONField(default=list)  # p. ej. ["celebracion", "paseo"]
    styles = models.JSONField(default=list)     # p. ej. ["royal-classic"]
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    # Elegibilidad del descuento Bitcoin migrada de la regla histórica
    # (tienda.ProductPaymentRule). Por defecto NO participa: solo las piezas
    # aprobadas explícitamente por el negocio (R05).
    bitcoin_discount_eligible = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    reason = models.CharField(max_length=160, blank=True)  # una razón verificable
    materials = models.JSONField(default=list)
    care = models.JSONField(default=list)
    shipping_note = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("store", "slug")
        ordering = ["-is_featured", "short_title"]

    @property
    def first_active_variant(self):
        """Primera variante activa (acciones de tarjeta: comparar)."""
        cache = getattr(self, "_prefetched_objects_cache", {})
        if "variants" in cache:
            return next((v for v in cache["variants"] if v.is_active), None)
        return self.variants.filter(is_active=True).first()

    def __str__(self):
        return f"{self.short_title} ({self.store.slug})"


class FitRule(models.Model):
    """Regla de talla versionada por producto (rangos en cm).

    Medidas desconocidas nunca se interpretan como compatibles.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="fit_rules")
    version = models.PositiveSmallIntegerField(default=1)
    requires_neck = models.BooleanField(default=False)
    ease_note = models.CharField(max_length=200, blank=True)  # holgura propia del producto
    # Filas: [{"label":"S","chest_min":30,"chest_max":36,"neck_min":..,"back_min":..}, ...]
    ranges = models.JSONField(default=list)
    approved_by = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("product", "version")
        ordering = ["-version"]

    def __str__(self):
        return f"FitRule v{self.version} · {self.product.short_title}"


class Variant(models.Model):
    """Variante comprable (SKU). SKU único por tienda; stock nunca negativo."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=60)
    option_label = models.CharField(max_length=60)  # p. ej. "Talla M", "Único"
    price_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("product", "sku")
        ordering = ["pk"]

    @property
    def price(self):
        return self.price_override if self.price_override is not None else self.product.base_price

    def __str__(self):
        return f"{self.sku} · {self.product.short_title}"


class ProductMedia(models.Model):
    """Imagen pública de producto (ruta estática) con alt y origen/licencia.

    A37: también puede respaldarse en un MediaAsset subido por el comerciante
    (archivo real); `url` resuelve el origen correcto en ambos casos.
    """

    class Kind(models.TextChoices):
        PRODUCT = "product", "Producto"
        USE = "use", "En uso"
        DETAIL = "detail", "Detalle"
        FIT = "fit", "Ajuste"
        EDITORIAL = "editorial", "Ilustración editorial"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="media")
    asset = models.ForeignKey("MediaAsset", on_delete=models.SET_NULL,
                              null=True, blank=True, related_name="product_uses")
    path = models.CharField(max_length=200)  # ruta dentro de static/
    alt = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PRODUCT)
    position = models.PositiveSmallIntegerField(default=0)
    source = models.CharField(max_length=200, blank=True)  # origen/licencia de la imagen

    class Meta:
        ordering = ["position", "pk"]

    def __str__(self):
        return f"{self.path} · {self.product.short_title}"


# ------------------------------------------------------------- compra (P0) --

    @property
    def url(self):
        """URL pública de la imagen: archivo subido o recurso estático."""
        from django.templatetags.static import static
        if self.asset_id and self.asset.file:
            return self.asset.file.url
        return static(self.path)

class Cart(models.Model):
    """Carrito por tienda y sesión. Abrirlo no reserva inventario."""

    class Status(models.TextChoices):
        OPEN = "open", "Abierto"
        ORDERED = "ordered", "Convertido en pedido"
        MERGED = "merged", "Integrado en cuenta"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="carts")
    session_key = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    version = models.PositiveIntegerField(default=1)  # control optimista
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Cart {self.public_id} ({self.store.slug})"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="+")
    quantity = models.PositiveSmallIntegerField(default=1)
    # Servicio con cita: la franja elegida viaja con la línea (G2).
    service_slot = models.ForeignKey(
        "ServiceSlot", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    recipient = models.ForeignKey(
        "RecipientProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)  # snapshot al añadir
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("cart", "variant", "recipient")
        ordering = ["added_at", "pk"]


class CheckoutSession(models.Model):
    """Resumen aprobado de un intento de compra (idempotente).

    La clave idempotente queda ligada al carrito Y al contenido aprobado:
    mismo intento => misma sesión; contenido distinto bajo la misma clave
    => sesión nueva (la anterior queda invalidada y sus reservas liberadas).
    """

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    cart = models.ForeignKey(Cart, on_delete=models.PROTECT, related_name="checkouts")
    cart_version = models.PositiveIntegerField()
    # Identidad separada (§8.1, N02): intento estable + número de revisión +
    # digest del contenido. `idempotency_key` interna es única por revisión;
    # la identidad comercial del intento es `intent_key`.
    intent_key = models.CharField(max_length=80, db_index=True, default="")
    revision = models.PositiveIntegerField(default=0)
    idempotency_key = models.CharField(max_length=96, unique=True)
    summary = models.JSONField(default=dict)
    summary_hash = models.CharField(max_length=64, blank=True)  # contenido aprobado (R02)
    is_current = models.BooleanField(default=True)  # False => sustituida por una edición
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() >= self.expires_at


class StockReservation(models.Model):
    """Reserva corta de stock durante el checkout (P0: 10 minutos)."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Activa"
        CONSUMED = "consumed", "Consumida"
        EXPIRED = "expired", "Vencida"
        RELEASED = "released", "Liberada"

    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="reservations")
    checkout = models.ForeignKey(CheckoutSession, on_delete=models.CASCADE, related_name="reservations")
    quantity = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)


class Order(models.Model):
    """Pedido de la tienda nueva. Estados separados: pedido/pago/preparación/entrega."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PLACED = "placed", "Colocado"
        CONFIRMED = "confirmed", "Confirmado"
        CANCELLED = "cancelled", "Cancelado"
        CLOSED = "closed", "Cerrado"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "Pendiente"
        REQUIRES_ACTION = "requires_action", "Requiere acción"
        PAID = "paid", "Pagado"
        FAILED = "failed", "Fallido"
        EXPIRED = "expired", "Vencido"
        REFUNDED = "refunded", "Reembolsado"
        PARTIALLY_REFUNDED = "partially_refunded", "Parcialmente reembolsado"
        DISPUTED = "disputed", "En disputa"

    class PrepStatus(models.TextChoices):
        NOT_STARTED = "not_started", "No iniciada"
        PREPARING = "preparing", "Preparando"
        READY = "ready", "Lista"
        CANCELLED = "cancelled", "Cancelada"

    class DeliveryStatus(models.TextChoices):
        UNASSIGNED = "unassigned", "Sin asignar"
        SCHEDULED = "scheduled", "Programada"
        SHIPPED = "shipped", "Despachada"
        DELIVERED = "delivered", "Entregada"
        INCIDENT = "incident", "Incidencia"
        RETURNED = "returned", "Devuelta"

    class PaymentMethod(models.TextChoices):
        MANUAL = "manual", "Pago manual (verificación)"
        BITCOIN = "bitcoin", "Bitcoin (manual)"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reference = models.CharField(max_length=16, db_index=True)  # p. ej. WK-000123
    access_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)  # invitados
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="orders")
    cart = models.OneToOneField(Cart, null=True, blank=True, on_delete=models.PROTECT, related_name="order")
    idempotency_key = models.CharField(max_length=80, unique=True)
    currency = models.CharField(max_length=3, default="USD")
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_note = models.CharField(max_length=120, blank=True)
    shipping_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    customer_name = models.CharField(max_length=120)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=40, blank=True)
    delivery_mode = models.CharField(max_length=12, default="pickup")  # pickup | local
    address = models.TextField(max_length=300, blank=True)
    city = models.CharField(max_length=80, blank=True)
    zone = models.CharField(max_length=80, blank=True)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.MANUAL)
    stock_restored_at = models.DateTimeField(null=True, blank=True)  # reposición idempotente (R04)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    refund_note = models.CharField(max_length=200, blank=True)  # medio + motivo del reembolso
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLACED)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    prep_status = models.CharField(max_length=12, choices=PrepStatus.choices, default=PrepStatus.NOT_STARTED)
    delivery_status = models.CharField(max_length=12, choices=DeliveryStatus.choices, default=DeliveryStatus.UNASSIGNED)
    payment_reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("store", "reference"), name="uniq_order_reference_per_store"),
        ]

    def __str__(self):
        return self.reference


class OrderItem(models.Model):
    """Línea de pedido con snapshot histórico (no cambia al editar catálogo)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveSmallIntegerField(default=0)
    variant = models.ForeignKey(Variant, null=True, on_delete=models.SET_NULL, related_name="+")
    sku = models.CharField(max_length=60)
    title = models.CharField(max_length=160)
    offer_type = models.CharField(max_length=12, choices=Product.OfferType.choices, default="physical")
    option_label = models.CharField(max_length=60, blank=True)
    recipient_alias = models.CharField(max_length=80, blank=True)
    quantity = models.PositiveSmallIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    service_slot = models.ForeignKey("ServiceSlot", null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["position", "pk"]


class OrderEvent(models.Model):
    """Línea temporal auditable del pedido (quién cambió qué)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    field = models.CharField(max_length=30)
    from_value = models.CharField(max_length=24, blank=True)
    to_value = models.CharField(max_length=24)
    note = models.CharField(max_length=200, blank=True)
    by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class ActionToken(models.Model):
    """Autorización de acción de escritura del asesor (R11).

    El modelo propone; el comprador confirma. Un permiso de un solo uso, con
    alcance (tienda+sesión), caducidad e idempotencia: repetir el mismo
    action_id devuelve el resultado ya ejecutado, nunca duplica la acción.
    """

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Propuesta"
        EXECUTED = "executed", "Ejecutada"
        EXPIRED = "expired", "Vencida"
        CANCELLED = "cancelled", "Cancelada"

    action_id = models.CharField(max_length=64, unique=True)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="action_tokens")
    session_key = models.CharField(max_length=64, db_index=True)
    tool = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)  # variante, cantidad, precio recuperados
    result = models.JSONField(default=dict)   # resultado de la ejecución (para reintentos)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROPOSED)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)


class StockAdjustment(models.Model):
    """Ajuste manual de inventario con motivo y actor (trazabilidad M04)."""

    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="adjustments")
    delta = models.IntegerField()  # +N entrada / -N salida
    reason = models.CharField(max_length=200)
    by = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class OutboxEvent(models.Model):
    """Trabajo diferido recuperable tras fallo (emails, métricas, webhooks).

    Claim con vencimiento (§18): el bloqueo de fila no se retiene durante la
    llamada externa; si el proceso cae tras enviar y antes de persistir, el
    evento se reclama de nuevo (al menos una vez, documentado). Un evento sin
    proveedor configurado queda BLOCKED con causa precisa, nunca «enviado».
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente"
        DONE = "done", "Procesado"
        FAILED = "failed", "Fallido"
        BLOCKED = "blocked", "Bloqueado por configuración"

    type = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    retries = models.PositiveSmallIntegerField(default=0)
    claim_token = models.CharField(max_length=40, blank=True)
    claimed_until = models.DateTimeField(null=True, blank=True)
    available_at = models.DateTimeField(null=True, blank=True)  # backoff de reintento
    last_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)


# ------------------------------------------------- perfiles, memoria y RAG --

class RecipientProfile(models.Model):
    """Perfil de destinatario (Royal Passport). Identidad por ID, nunca por nombre."""

    class Kind(models.TextChoices):
        DOG = "dog", "Perro"
        OTHER = "other", "Otro destinatario"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="profiles")
    session_key = models.CharField(max_length=64, db_index=True)  # propietario (P0: sesión)
    alias = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.DOG)
    breed = models.CharField(max_length=80, blank=True)
    photo_path = models.CharField(max_length=200, blank=True)  # opcional, nunca obligatoria
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.alias} ({self.store.slug})"


class Measurement(models.Model):
    """Medidas de un perfil: valor original + normalizadas a cm, con fecha y origen."""

    profile = models.ForeignKey(RecipientProfile, on_delete=models.CASCADE, related_name="measurements")
    chest_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    neck_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    back_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    original = models.JSONField(default=dict)  # {"chest": 15, "unit": "in", ...}
    source = models.CharField(max_length=20, default="owner")  # owner | looklab | smartfit
    measured_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-measured_at", "-pk"]


class Consent(models.Model):
    """Permiso de memoria por titular, tienda y finalidad. Revocable."""

    class Purpose(models.TextChoices):
        MEASUREMENTS = "measurements", "Guardar medidas"
        PREFERENCES = "preferences", "Guardar preferencias"
        PERSONALIZATION = "personalization", "Personalización"

    class Status(models.TextChoices):
        GRANTED = "granted", "Otorgado"
        REVOKED = "revoked", "Revocado"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="consents")
    session_key = models.CharField(max_length=64, db_index=True)
    profile = models.ForeignKey(RecipientProfile, null=True, blank=True, on_delete=models.CASCADE, related_name="consents")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    version = models.CharField(max_length=20, default="v1")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.GRANTED)
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-granted_at"]


class Preference(models.Model):
    """Preferencia persistente con consentimiento y origen."""

    profile = models.ForeignKey(RecipientProfile, on_delete=models.CASCADE, related_name="preferences")
    consent = models.ForeignKey(Consent, on_delete=models.CASCADE, related_name="preferences")
    key = models.CharField(max_length=40)   # p. ej. "color", "occasion", "budget_hint"
    value = models.CharField(max_length=120)
    source = models.CharField(max_length=20, default="explicit")  # explicit | assistant
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("profile", "key")


class MemorySummary(models.Model):
    """Resumen contextual derivado, corto, con referencias. Se invalida al revocar."""

    profile = models.ForeignKey(RecipientProfile, on_delete=models.CASCADE, related_name="memory_summaries")
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="memory_summaries")
    summary = models.CharField(max_length=280)
    refs = models.JSONField(default=list)
    consent_version = models.CharField(max_length=20, default="v1")
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Look(models.Model):
    """Look guardado de LookLab. Guardar un look no reserva precio ni stock."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="looks")
    session_key = models.CharField(max_length=64, db_index=True)
    profile = models.ForeignKey(RecipientProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="looks")
    occasion = models.CharField(max_length=40, blank=True)
    style = models.CharField(max_length=40, blank=True)
    budget = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    items = models.JSONField(default=list)  # [{"variant_id":..,"title":..,"price":..}]
    recommender_version = models.CharField(max_length=20, default="v1")
    created_at = models.DateTimeField(auto_now_add=True)


class KnowledgeDocument(models.Model):
    """Documento publicado de una tienda para el RAG (guías, políticas)."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="knowledge")
    audience = models.CharField(max_length=20, default="customer")  # customer | staff
    topic = models.CharField(max_length=40)   # tallas | envios | cambios | compra | cuidado
    title = models.CharField(max_length=160)
    body = models.TextField()
    version = models.CharField(max_length=20, default="v1")
    is_published = models.BooleanField(default=False)
    approved_by = models.CharField(max_length=120, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["topic", "title"]


# ------------------------------------------------------------------- IA -----

class AIConversation(models.Model):
    """Conversación del asesor. Propietario = sesión (P0).

    `history_sealed_before` separa el historial VISIBLE del historial
    elegible para el proveedor (N08, §8.3): al revocar un consentimiento se
    sella y los mensajes anteriores no vuelven a enviarse al modelo.
    """

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="conversations")
    session_key = models.CharField(max_length=64, db_index=True)
    mode = models.CharField(max_length=12, default="rules")  # ai | rules (etiqueta honesta)
    history_sealed_before = models.DateTimeField(null=True, blank=True)
    # «Sin guardar» (§10): modo efímero — nada de esta conversación se
    # persiste (mensajes, preferencias ni resúmenes) y el proveedor recibe
    # sólo el turno actual. La persona lo activa desde la pantalla del asesor.
    memory_off = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class AIMessage(models.Model):
    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10)  # user | assistant | system
    content = models.TextField()
    cards = models.JSONField(default=list)   # tarjetas renderizadas desde IDs validados
    request_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]


class RecommendationEvent(models.Model):
    """Trazabilidad de recomendaciones: candidatos, exclusiones, razones, versión."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="recommendation_events")
    request_id = models.CharField(max_length=64, db_index=True)
    kind = models.CharField(max_length=20, default="looklab")  # looklab | stylist | search
    intent = models.JSONField(default=dict)
    candidates = models.JSONField(default=list)
    excluded = models.JSONField(default=list)
    reasons = models.JSONField(default=list)
    engine_version = models.CharField(max_length=20, default="v1")
    created_at = models.DateTimeField(auto_now_add=True)


class ShippingZone(models.Model):
    """Zona de entrega configurada por el comerciante (matriz P0)."""

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="shipping_zones")
    name = models.CharField(max_length=80)          # p. ej. "San Salvador"
    mode = models.CharField(max_length=12, default="local")  # pickup | local
    fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    eta_note = models.CharField(max_length=120, blank=True)  # rango estimado o "Por confirmar"
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]


# ============================================================ REVISIÓN 2 ====
# Contratos de categoría, medios reales, tema versionado, comparación y
# analítica (§13, §15, §21 del encargo de revisión 2).

class CategorySchema(models.Model):
    """Esquema de atributos tipados por categoría (§15): la categoría define
    qué se puede comparar y con qué unidad canónica."""

    slug = models.SlugField(max_length=60, unique=True)  # p. ej. "moda-canina"
    name = models.CharField(max_length=80)

    def __str__(self):
        return self.name


class AttributeDefinition(models.Model):
    """Definición de un atributo comparable dentro de una categoría."""

    class ValueType(models.TextChoices):
        TEXT = "text", "Texto"
        OPTION = "option", "Opción"
        DECIMAL = "decimal", "Número"
        MEASURE = "measure", "Medida con unidad"
        BOOLEAN = "boolean", "Sí/No"
        LIST = "list", "Lista controlada"

    schema = models.ForeignKey(CategorySchema, on_delete=models.CASCADE,
                               related_name="definitions")
    key = models.SlugField(max_length=60)        # p. ej. "chest_cm", "paper_size"
    label = models.CharField(max_length=80)
    value_type = models.CharField(max_length=10, choices=ValueType.choices)
    unit = models.CharField(max_length=12, blank=True)  # unidad canónica (cm, g, ml…)
    options = models.JSONField(default=list)     # para option/list
    is_variant_level = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ("schema", "key")
        ordering = ["position", "pk"]


class AttributeValue(models.Model):
    """Valor de atributo con estado y procedencia (§15).

    «No aplica», «no informado» y un valor real son cosas distintas. Se
    guarda el valor ORIGINAL con su unidad, el valor NORMALIZADO a la unidad
    canónica de la definición y la procedencia del dato.
    """

    class Status(models.TextChoices):
        INFORMED = "informed", "Informado"
        NOT_APPLICABLE = "not_applicable", "No aplica"
        UNKNOWN = "unknown", "No informado"

    definition = models.ForeignKey(AttributeDefinition, on_delete=models.CASCADE,
                                   related_name="values")
    product = models.ForeignKey(Product, on_delete=models.CASCADE,
                                related_name="attribute_values", null=True, blank=True)
    variant = models.ForeignKey(Variant, on_delete=models.CASCADE,
                                related_name="attribute_values", null=True, blank=True)
    status = models.CharField(max_length=14, choices=Status.choices,
                              default=Status.INFORMED)
    value = models.JSONField(default=dict)             # {"raw": ..., "unit": "in"}
    normalized_number = models.DecimalField(max_digits=12, decimal_places=3,
                                            null=True, blank=True)  # unidad canónica
    source = models.CharField(max_length=120, blank=True)  # procedencia verificable

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "product"], condition=models.Q(variant__isnull=True),
                name="uniq_attribute_product"),
            models.UniqueConstraint(
                fields=["definition", "variant"], condition=models.Q(product__isnull=True),
                name="uniq_attribute_variant"),
        ]


class MediaAsset(models.Model):
    """Archivo de imagen REAL subido por el comerciante (§13).

    Validado por tipo/tamaño en la vista; guarda dimensiones, punto focal y
    texto alternativo. El origen/derechos es un dato editorial declarado.
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="media_assets")
    file = models.ImageField(upload_to="reino/uploads/%Y/%m")
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    alt = models.CharField(max_length=160)
    focal_x = models.FloatField(default=0.5)  # 0..1 punto focal horizontal
    focal_y = models.FloatField(default=0.5)

    @property
    def focal_css(self):
        return f"{self.focal_x * 100:.1f}% {self.focal_y * 100:.1f}%"
    origin = models.CharField(max_length=160, blank=True)  # derechos/origen (dato editorial)
    uploaded_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL,
                                    null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.store.slug}:{self.pk} {self.alt[:30]}"


class StoreThemeVersion(models.Model):
    """Versión de apariencia y contenido de una tienda (§13).

    Borrador y publicación separados; publicar es una acción explícita con
    validación; restaurar crea una NUEVA versión copiando una anterior (el
    historial nunca se pisa). Solo una versión publicada por tienda, garantía
    reforzada en el servicio dentro de una transacción.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Borrador"
        PUBLISHED = "published", "Publicada"

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="theme_versions")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    # F09: una versión PUBLICADA es inmutable y queda en el historial; la
    # vigente se marca con is_current (publicar NO convierte la anterior en
    # borrador editable).
    is_current = models.BooleanField(default=False)
    config = models.JSONField(default=dict)
    created_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL,
                                   null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("store", "version")
        ordering = ["-version"]


class ComparisonSession(models.Model):
    """Bandeja persistente de comparación (P06): 2–4 variantes por sesión,
    compartible por ID público sin datos sensibles."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    session_key = models.CharField(max_length=64, db_index=True)
    items = models.JSONField(default=list)  # [{"variant_id": "..."}]
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AnalyticsEvent(models.Model):
    """Evento de analítica con definición y deduplicación (§21).

    `request_id` único: un reintento del cliente nunca cuenta dos veces.
    Los pedidos creados, pagados y cobrados son eventos DISTINTOS.
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE,
                              related_name="analytics", null=True, blank=True)
    session_key = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=40, db_index=True)  # ver services_analytics.EVENTS
    request_id = models.CharField(max_length=64, unique=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class IntegrationState(models.Model):
    """Estado OBSERVABLE de una integración (AC25).

    Nunca «producción» por la sola presencia de una clave: los estados
    posibles son no_configurada / configurada / conexion_comprobada /
    evaluacion_aprobada / degradada / error, con fecha de última comprobación
    real y detalle accionable. Un botón «Probar conexión» ejecuta la prueba.
    """

    class State(models.TextChoices):
        NOT_CONFIGURED = "no_configurada", "No configurada"
        CONFIGURED = "configurada", "Configurada"
        CONNECTION_OK = "conexion_comprobada", "Conexión comprobada"
        EVAL_APPROVED = "evaluacion_aprobada", "Evaluación aprobada"
        DEGRADED = "degradada", "Degradada"
        ERROR = "error", "Error"

    key = models.SlugField(max_length=40, unique=True)  # ai | email | payments | postgres
    state = models.CharField(max_length=22, choices=State.choices,
                             default=State.NOT_CONFIGURED)
    detail = models.CharField(max_length=200, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class DigitalAsset(models.Model):
    """Archivo descargable de un producto digital (§5, §12.2).

    El acceso nace UNA sola vez tras el estado de pago exigido y se sirve
    con token autorizado + expiración; jamás un enlace público permanente.
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE,
                                related_name="digital_assets")
    file = models.FileField(upload_to="reino/digital/%Y/%m")
    version = models.CharField(max_length=40, default="1.0")
    license_note = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)


class DigitalGrant(models.Model):
    """Derecho de descarga creado exactamente una vez por línea pagada."""
    asset = models.ForeignKey(DigitalAsset, on_delete=models.CASCADE, related_name="grants")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="digital_grants")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    downloads = models.PositiveIntegerField(default=0)
    max_downloads = models.PositiveIntegerField(default=5)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("asset", "order")


class ServiceSlot(models.Model):
    """Franja reservable de un producto-servicio (capacidad acotada)."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE,
                                related_name="slots")
    starts_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=60)
    capacity = models.PositiveIntegerField(default=1)
    booked = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)


class Booking(models.Model):
    """Reserva confirmada de una franja; única por pedido+franja (§13)."""

    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmada"
        CANCELLED = "cancelled", "Cancelada"

    slot = models.ForeignKey(ServiceSlot, on_delete=models.PROTECT, related_name="bookings")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="bookings")
    buyer_email = models.EmailField()
    quantity = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.CONFIRMED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("slot", "order")


class PaymentAttempt(models.Model):
    """Intento de cobro de UN pedido de UNA tienda (§11.5).

    Pedido ≠ pago ≠ cumplimiento: un pedido puede tener varios intentos
    (fallidos y luego uno exitoso); los estados del proveedor se mapean a
    este contrato sin perder el original. Efectos de dominio exactamente una
    vez: (attempt, efecto) deduplicado por diseño del servicio.
    """

    class State(models.TextChoices):
        CREATED = "created", "Creado"
        REQUIRES_ACTION = "requires_action", "Requiere acción del comprador"
        PENDING = "pending", "Pendiente"
        AUTHORIZED = "authorized", "Autorizado"
        CAPTURED = "captured", "Capturado/confirmado"
        FAILED = "failed", "Fallido"
        CANCELLED = "cancelled", "Cancelado"
        EXPIRED = "expired", "Expirado"
        REFUND_PENDING = "refund_pending", "Reembolso pendiente"
        PARTIALLY_REFUNDED = "partially_refunded", "Parcialmente reembolsado"
        REFUNDED = "refunded", "Reembolsado"
        DISPUTED = "disputed", "Disputado"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payment_attempts")
    provider = models.CharField(max_length=20)       # manual | paypal | btcpay | wompi | fake
    account_ref = models.CharField(max_length=80, blank=True)  # cuenta/tienda/entorno
    environment = models.CharField(max_length=10, default="test")  # test | live
    state = models.CharField(max_length=20, choices=State.choices, default=State.CREATED)
    provider_state = models.CharField(max_length=60, blank=True)  # estado original
    external_ref = models.CharField(max_length=120, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=6, default="USD")
    idempotency_key = models.CharField(max_length=64, unique=True)
    captured_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    redirect_url = models.CharField(max_length=300, blank=True)
    qr_payload = models.CharField(max_length=300, blank=True)
    safe_payload = models.JSONField(default=dict)    # minimizado y redactado
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class PaymentEvent(models.Model):
    """Evento de pago (webhook/consulta/acción): deduplicado por referencia."""

    attempt = models.ForeignKey(PaymentAttempt, on_delete=models.CASCADE,
                                related_name="events")
    provider_event_id = models.CharField(max_length=120, db_index=True)
    kind = models.CharField(max_length=30)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("attempt", "provider_event_id", "kind")


class Shipment(models.Model):
    """Envío de (parte de) un pedido (§12.1): paquete, referencia, etiqueta,
    tracking y estado por líneas/cantidades. Manual y automático separados."""

    class Status(models.TextChoices):
        PREPARING = "preparing", "En preparación"
        READY = "ready", "Listo para despacho"
        LABEL_CREATED = "label_created", "Etiqueta creada"
        PICKED_UP = "picked_up", "Recogido"
        IN_TRANSIT = "in_transit", "En tránsito"
        ISSUE = "issue", "Incidencia"
        DELIVERED = "delivered", "Entregado"
        RETURNED = "returned", "Devuelto"
        CANCELLED = "cancelled", "Cancelado"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="shipments")
    provider = models.CharField(max_length=20, default="manual")
    service = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices,
                              default=Status.PREPARING)
    external_ref = models.CharField(max_length=120, blank=True, db_index=True)
    tracking = models.CharField(max_length=120, blank=True)
    label_ref = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=6, default="USD")
    lines = models.JSONField(default=list)  # [{order_item_id, quantity}] parciales
    address_snapshot = models.JSONField(default=dict)  # privado (§12.4)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ShipmentEvent(models.Model):
    """Evento de tracking deduplicado; fuera de orden no rompe la línea de
    tiempo (§12.4.8)."""

    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE,
                                 related_name="events")
    code = models.CharField(max_length=40)
    detail = models.CharField(max_length=200, blank=True)
    occurred_at = models.DateTimeField()
    provider_event_id = models.CharField(max_length=120, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("shipment", "provider_event_id", "code")
        ordering = ["occurred_at", "pk"]
