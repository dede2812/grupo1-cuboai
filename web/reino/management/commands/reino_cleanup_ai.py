from django.core.management.base import BaseCommand
from django.utils import timezone

from reino.models import AIUsageCounter, ActionToken


class Command(BaseCommand):
    help = "Delete expired usage counters and expire outstanding AI/LookLab proposals."

    def handle(self, *args, **options):
        now = timezone.now()
        count, _ = AIUsageCounter.objects.filter(expires_at__lt=now).delete()
        expired = ActionToken.objects.filter(status="proposed", expires_at__lt=now).update(status="expired")
        self.stdout.write(f"Removed {count} expired counters; expired {expired} proposals.")
