"""Upgrade only the original Wiener palette, preserving published history."""
from copy import deepcopy
from django.core.management.base import BaseCommand
from django.db import transaction
from reino.models import Store, ProductMedia
from reino import services_theme


class Command(BaseCommand):
    help = "Actualiza la paleta original de Wiener Kingdom; conserva temas personalizados e historial."

    @transaction.atomic
    def handle(self, **options):
        store = Store.objects.select_for_update().filter(slug="wiener-kingdom").first()
        if not store:
            self.stdout.write("No existe Wiener Kingdom; no se modificó ninguna tienda.")
            return
        current = services_theme.current_theme(store)
        # The original seed used a 168px thumbnail as hero; the 1254px original
        # already exists. Update only this known catalogue entry, no uploads.
        media = ProductMedia.objects.filter(product__store=store,
            product__slug="beige-anti-rub-harness", asset__isnull=True)
        media.filter(path="tienda/img/beige-harness-2.jpg").update(position=0)
        media.filter(path="tienda/img/beige-harness-1.jpg").update(position=1)
        colors = current.config.get("colors", {})
        if colors.get("primary") != "#FF4D9D" or colors.get("ink") != "#15172E":
            self.stdout.write("Tema actualizado o personalizado; se conserva sin cambios.")
            return
        draft = services_theme.get_or_create_draft(store)
        config = deepcopy(current.config)
        config["colors"] = services_theme.default_config("wiener-kingdom")["colors"]
        services_theme.save_draft_config(draft, config)
        services_theme.publish(store, draft)
        self.stdout.write(self.style.SUCCESS(f"Paleta publicada como versión {draft.version}; historial conservado."))
