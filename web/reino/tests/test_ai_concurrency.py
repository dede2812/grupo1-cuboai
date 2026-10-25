"""Real PostgreSQL contention tests for atomic external-provider budgets."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings

from reino.ai.orchestrator import _reserve_provider_call
from reino.ai.tools import ToolContext
from reino.models import AIUsageCounter, Merchant, Store


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row concurrency")
class ProviderBudgetConcurrencyTests(TransactionTestCase):
    def setUp(self):
        merchant = Merchant.objects.create(name="Quota test", status="active")
        self.store = Store.objects.create(merchant=merchant, slug="quota-store", name="Quota", status="active")

    def reserve_together(self, sessions):
        barrier = Barrier(len(sessions))

        def reserve(session):
            close_old_connections()
            try:
                store = Store.objects.get(pk=self.store.pk)
                barrier.wait(timeout=10)
                return _reserve_provider_call(ToolContext(store, session))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(sessions)) as pool:
            return list(pool.map(reserve, sessions))

    @override_settings(REINO_AI={"SESSION_HOURLY_LIMIT": 1, "STORE_DAILY_LIMIT": 20})
    def test_simultaneous_same_customer_reserves_one_call(self):
        self.assertEqual(sum(self.reserve_together(["same-owner", "same-owner"])), 1)
        self.assertTrue(all(c.count == 1 for c in AIUsageCounter.objects.all()))

    @override_settings(REINO_AI={"SESSION_HOURLY_LIMIT": 20, "STORE_DAILY_LIMIT": 1})
    def test_different_customers_cannot_exceed_store_budget(self):
        self.assertEqual(sum(self.reserve_together(["owner-a", "owner-b"])), 1)
        self.assertEqual(AIUsageCounter.objects.get(key__startswith="ai:store:").count, 1)
