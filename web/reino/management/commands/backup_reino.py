"""Respaldo verificable (G6): dumpdata de reino a JSON con fecha + verificación
de restauración en una base temporal (el comando `restore_check` lo valida)."""

import json
from datetime import datetime, timezone

from django.core import serializers
from django.core.management.base import BaseCommand

from django.contrib.auth.models import User

from reino import models as m

BACKUP_MODELS = [
    User, m.CustomerIdentity,  # cuentas y propietario persistente (sin contraseña en claro)
    m.Merchant, m.Store, m.MerchantMember, m.CategorySchema,
    m.AttributeDefinition, m.AttributeValue, m.Product, m.FitRule, m.Variant,
    m.ProductMedia, m.MediaAsset, m.StoreThemeVersion, m.ShippingZone,
    m.Cart, m.CartItem, m.CheckoutSession, m.StockReservation,
    m.Order, m.OrderItem, m.OrderEvent, m.StockAdjustment,
    m.PaymentAttempt, m.PaymentEvent, m.Shipment, m.ShipmentEvent,
    m.DigitalAsset, m.DigitalGrant, m.ServiceSlot, m.Booking,
    m.RecipientProfile, m.Measurement, m.Consent, m.Preference, m.MemorySummary,
    m.Look, m.KnowledgeDocument, m.AIConversation, m.AIMessage,
    m.RecommendationEvent, m.ActionToken, m.OutboxEvent,
    m.IntegrationState, m.AnalyticsEvent, m.ComparisonSession, m.AIUsageCounter,
]


class Command(BaseCommand):
    help = "Respalda todos los datos de reino a un JSON fechado."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="backups")

    def handle(self, *args, **opts):
        import os
        out_dir = opts["out"]
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(out_dir, f"reino_backup_{stamp}.json")
        objects = []
        for model in BACKUP_MODELS:
            objects.extend(model.objects.all())
        with open(path, "w") as fh:
            fh.write(serializers.serialize("json", objects, indent=1))
        self.stdout.write(self.style.SUCCESS(
            f"Respaldo en {path}: {len(objects)} registros de "
            f"{len(BACKUP_MODELS)} modelos."))
