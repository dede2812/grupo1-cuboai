import uuid

from django.db import models


class DogProfile(models.Model):
    """Medidas de un perro, guardadas en unidades métricas (kg / cm)."""

    # Identificador público no secuencial para las URLs.
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # El nombre es opcional.
    name = models.CharField(max_length=80, blank=True)
    breed = models.CharField(max_length=80)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2)
    back_length_cm = models.DecimalField(max_digits=5, decimal_places=1)
    chest_girth_cm = models.DecimalField(max_digits=5, decimal_places=1)
    neck_girth_cm = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def display_name(self):
        return self.name or "Unnamed dog"

    def __str__(self):
        return f"{self.display_name} ({self.breed})"


class Cart(models.Model):
    """Carrito multiproducto. Cada línea es una cotización (Quote) con su
    propio perfil de perro, producto, cantidad y talla."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ORDERED = "ordered", "Ordered"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cart {self.pk}"


class Quote(models.Model):
    """Cotización de un producto del catálogo para un perro (línea de carrito)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACCEPTED = "accepted", "Accepted"
        CANCELLED = "cancelled", "Cancelled"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # Nulo = linea de carrito con medidas pendientes (aun sin perfil de perro).
    dog = models.ForeignKey(
        DogProfile, on_delete=models.PROTECT, related_name="quotes", null=True, blank=True
    )
    # El catálogo vive en tienda.views.PRODUCTOS; se referencia por su clave.
    product_slug = models.CharField(max_length=50)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)  # precio unitario
    quantity = models.PositiveSmallIntegerField(default=1)
    cart = models.ForeignKey(
        Cart, null=True, blank=True, on_delete=models.SET_NULL, related_name="quotes"
    )
    # Talla elegida por el cliente para esta línea (texto de la tabla de referencia).
    size_label = models.CharField(max_length=40, blank=True)
    # Nulo hasta que exista una regla comercial de precio por talla.
    total_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    class Pricing(models.TextChoices):
        PROVISIONAL = "provisional", "Provisional"
        FINAL = "final", "Final"

    # Provisional: solo precio base, sin ajuste por talla (regla comercial
    # pendiente). Final: total validado con una regla comercial aprobada.
    pricing = models.CharField(
        max_length=20, choices=Pricing.choices, default=Pricing.PROVISIONAL
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Quote #{self.pk} - {self.product_slug}"


class Order(models.Model):
    """Pedido generado a partir de una cotización.

    Pago, producción y envío son estados independientes. Crear el pedido
    NO implica que esté pagado.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"

    class ProductionStatus(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        IN_PRODUCTION = "in_production", "In production"
        COMPLETED = "completed", "Completed"

    class PaymentMethod(models.TextChoices):
        UNSPECIFIED = "unspecified", "To be arranged"
        BITCOIN = "bitcoin", "Bitcoin"
        PAYPAL_DEMO = "paypal_demo", "PayPal (demo - not available)"
        CARD_DEMO = "card_demo", "Card (demo - not available)"

    class DiscountStatus(models.TextChoices):
        NONE = "none", "None"
        PENDING = "pending_verification", "Pending payment verification"
        APPLIED = "applied", "Applied"

    class ShippingStatus(models.TextChoices):
        NOT_SHIPPED = "not_shipped", "Not shipped"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # Pedido de una sola cotización (flujo directo) o, si se creó desde un
    # carrito con varias líneas, nulo: ver `lines` y `cart`.
    quote = models.OneToOneField(
        Quote, null=True, blank=True, on_delete=models.PROTECT, related_name="order"
    )
    cart = models.OneToOneField(
        Cart, null=True, blank=True, on_delete=models.PROTECT, related_name="order"
    )
    # Subtotal de productos = suma de los subtotales de las líneas (sin envío).
    total = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveSmallIntegerField(default=1)
    # True mientras no exista regla de precio por talla aprobada.
    price_is_provisional = models.BooleanField(default=True)

    customer_name = models.CharField(max_length=120)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=30)
    country = models.CharField(max_length=80)
    city = models.CharField(max_length=80)
    address = models.TextField(max_length=300)

    # Copia de producto, precio y medidas al momento de crear el pedido.
    snapshot = models.JSONField(default=dict)

    # Seguimiento del envío: opcional, lo registra el personal cuando existe.
    tracking_number = models.CharField(max_length=60, blank=True)
    tracking_carrier = models.CharField(max_length=60, blank=True)
    # Talla confirmada por el personal (cuando la de referencia no es concluyente).
    size_confirmed = models.CharField(max_length=40, blank=True)

    # Evidencia aportada por el personal al marcar el pago (p. ej. referencia).
    payment_reference = models.CharField(max_length=120, blank=True)

    # Método de pago elegido y descuento Bitcoin (15 % sobre el subtotal de
    # productos, sin envío). El descuento queda PENDIENTE hasta que el pago
    # sea verificado; `total` es siempre el subtotal de productos.
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.UNSPECIFIED
    )
    discount_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_status = models.CharField(
        max_length=24, choices=DiscountStatus.choices, default=DiscountStatus.NONE
    )

    # Costos internos. Estimado y real son valores distintos; ambos opcionales.
    # Los totales se derivan de materiales + mano de obra cuando se cargan.
    estimated_materials = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    estimated_labor = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    actual_materials = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    actual_labor = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    estimated_cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    actual_cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    cost_notes = models.CharField(max_length=300, blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    production_status = models.CharField(
        max_length=20,
        choices=ProductionStatus.choices,
        default=ProductionStatus.NOT_STARTED,
    )
    shipping_status = models.CharField(
        max_length=20,
        choices=ShippingStatus.choices,
        default=ShippingStatus.NOT_SHIPPED,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def amount_due(self):
        """Importe a pagar: el descuento solo cuenta cuando está aplicado."""
        if self.discount_status == self.DiscountStatus.APPLIED:
            return self.total - self.discount_amount
        return self.total

    @property
    def amount_if_discount(self):
        return self.total - self.discount_amount

    @property
    def number(self):
        return f"WK-{self.pk:06d}"

    def __str__(self):
        return self.number


class OrderEvent(models.Model):
    """Registro de cada cambio de estado hecho desde el panel."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    field = models.CharField(max_length=30)
    from_value = models.CharField(max_length=20)
    to_value = models.CharField(max_length=120)
    note = models.CharField(max_length=200, blank=True)
    by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class ProductCost(models.Model):
    """Presupuesto interno de fabricación de un producto del catálogo.

    PRIVADO: nunca se muestra en páginas públicas. Todos los valores son
    supuestos editables hasta que `is_validated` sea verdadero.
    """

    product_slug = models.CharField(max_length=50, unique=True)
    labor_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    other_costs = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_validated = models.BooleanField(default=False)
    notes = models.CharField(max_length=300, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    def __str__(self):
        return f"Cost profile {self.product_slug}"


class MaterialLine(models.Model):
    """Partida de materiales: consumo × precio unitario = subtotal."""

    product_cost = models.ForeignKey(
        ProductCost, on_delete=models.CASCADE, related_name="lines"
    )
    position = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=120)
    unit = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=8, decimal_places=3)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    # Reservas sin desglose confirmado de insumos.
    is_provisional_reserve = models.BooleanField(default=False)
    is_validated = models.BooleanField(default=False)

    class Meta:
        ordering = ["position", "pk"]

    @property
    def subtotal(self):
        from decimal import ROUND_HALF_UP, Decimal

        return (self.quantity * self.unit_price).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def __str__(self):
        return f"{self.name} ({self.product_cost.product_slug})"


class ProductMeasurement(models.Model):
    """Medidas que exige cada prenda (configurable; a validar con confección)."""

    product_slug = models.CharField(max_length=50, unique=True)
    requires_neck = models.BooleanField(default=False)
    is_validated = models.BooleanField(default=False)
    notes = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"Measurements for {self.product_slug}"


class SizeRange(models.Model):
    """Fila de la tabla de tallas de referencia (cm).

    Configuración editable, NO validada con confección. Se usa solo para
    sugerir una talla de referencia desde las medidas; nunca por raza ni
    para cambiar precios.
    """

    class Group(models.TextChoices):
        SMALL = "small", "Small dogs"
        MEDIUM = "medium", "Medium dogs"
        LARGE = "large", "Large dogs"

    group = models.CharField(max_length=10, choices=Group.choices)
    label = models.CharField(max_length=10)
    position = models.PositiveSmallIntegerField(default=0)
    neck_min = models.DecimalField(max_digits=5, decimal_places=1)
    neck_max = models.DecimalField(max_digits=5, decimal_places=1)
    chest_min = models.DecimalField(max_digits=5, decimal_places=1)
    chest_max = models.DecimalField(max_digits=5, decimal_places=1)
    back_min = models.DecimalField(max_digits=5, decimal_places=1)
    back_max = models.DecimalField(max_digits=5, decimal_places=1)
    is_validated = models.BooleanField(default=False)

    class Meta:
        ordering = ["position", "pk"]

    @property
    def display(self):
        return f"{self.label} ({self.get_group_display().lower()})"

    def __str__(self):
        return self.display


class ProductPaymentRule(models.Model):
    """Reglas de pago por producto (configurables por el personal)."""

    product_slug = models.CharField(max_length=50, unique=True)
    # Si el producto admite el descuento por pago con Bitcoin.
    bitcoin_discount_eligible = models.BooleanField(default=True)

    def __str__(self):
        return f"Payment rules {self.product_slug}"


class OrderLine(models.Model):
    """Línea de un pedido: un producto con su cantidad, talla, medidas y
    estado de confección propios. Guarda copias históricas (snapshots)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    quote = models.OneToOneField(
        Quote, null=True, blank=True, on_delete=models.SET_NULL, related_name="order_line"
    )
    position = models.PositiveSmallIntegerField(default=0)
    product_slug = models.CharField(max_length=50)
    product_name = models.CharField(max_length=160)
    quantity = models.PositiveSmallIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    price_is_provisional = models.BooleanField(default=True)
    discount_eligible = models.BooleanField(default=False)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    size_selected = models.CharField(max_length=40, blank=True)  # elegida por el cliente
    size_confirmed = models.CharField(max_length=40, blank=True)  # confirmada por el personal

    dog_snapshot = models.JSONField(default=dict)
    size_reference = models.JSONField(default=dict)
    required_measurements = models.JSONField(default=dict)
    cost_estimate = models.JSONField(null=True, blank=True)

    production_status = models.CharField(
        max_length=20,
        choices=Order.ProductionStatus.choices,
        default=Order.ProductionStatus.NOT_STARTED,
    )

    class Meta:
        ordering = ["position", "pk"]

    @property
    def size_display(self):
        """Talla a mostrar: confirmada por el personal, elegida o de referencia."""
        if self.size_confirmed:
            return self.size_confirmed
        if self.size_selected:
            return self.size_selected
        ref = self.size_reference or {}
        candidates = ref.get("candidates") or []
        if ref.get("status") == "matched" and candidates:
            return f"{candidates[0]} (reference)"
        return "To be confirmed"

    def __str__(self):
        return f"{self.order.number} · {self.product_name} × {self.quantity}"
