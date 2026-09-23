"""Offline regression checks: failed requests stay visible in ledger and trace.

All HTTP clients and sandbox execution are replaced by deterministic fixtures.
No key, network request, Docker invocation or paid inference is used.
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from forgerl.orchestrator import Episode
from forgerl.provider import ProviderError, RunpodProvider
from forgerl.store import Store
from forgerl.tasks import list_tasks


class Response:
    status_code = 200
    content = b"offline response fixture"

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class OfflineClient:
    behavior = None
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, *args, **kwargs):
        type(self).calls += 1
        if self.behavior == "timeout":
            raise httpx.ReadTimeout("offline timeout")
        if self.behavior == "cancel":
            raise asyncio.CancelledError()
        return Response(self.behavior)


def sandbox_fixture(*args, **kwargs):
    return {"passed": 0, "total": 1, "cases": []}


class ProviderAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, response_or_error, exception):
        OfflineClient.behavior, OfflineClient.calls = response_or_error, 0
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "ledger.sqlite3")
            provider = RunpodProvider(store, "offline-fixture-no-credential")
            episode = Episode(list_tasks()[0], provider)
            with patch("forgerl.provider.httpx.AsyncClient", OfflineClient), patch("forgerl.orchestrator.sandbox.evaluate", sandbox_fixture):
                await episode.start()
                with self.assertRaises(exception):
                    await episode.step("fast")
            budget = store.budget("research")
            result = episode.result()
            self.assertEqual(OfflineClient.calls, 1)
            self.assertGreater(budget["charged_usd"], 0)
            self.assertAlmostEqual(result["cost_usd"], budget["charged_usd"], places=6)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(episode.terminal)
            with store.connect() as connection:
                charge = dict(connection.execute("SELECT * FROM charges").fetchone())
            return charge, result

    async def test_non_object_response_retains_reservation_and_episode_cost(self):
        for malformed in ([], None, "unexpected payload"):
            with self.subTest(shape=type(malformed).__name__):
                charge, result = await self.exercise(malformed, ProviderError)
                self.assertEqual(charge["status"], "uncertain")
                self.assertEqual(charge["charged"], charge["reserved"])
                self.assertFalse(result["solved"])

    async def test_bad_choice_after_usage_retains_settled_cost_not_zero_or_reservation(self):
        for malformed in ({"choices": []}, {"choices": [{"message": []}]}):
            with self.subTest(payload=malformed):
                payload = {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}, **malformed}
                charge, result = await self.exercise(payload, ProviderError)
                self.assertEqual(charge["status"], "estimated")
                self.assertEqual(charge["charged"], 1500)
                self.assertAlmostEqual(result["cost_usd"], 0.0015)

    async def test_timeout_preserves_unknown_charge_without_retry(self):
        charge, result = await self.exercise("timeout", ProviderError)
        self.assertEqual(charge["status"], "uncertain")
        self.assertEqual(charge["charged"], charge["reserved"])
        self.assertEqual(result["stop_reason"], "provider_error")

    async def test_cancellation_preserves_charge_and_propagates_cancellation(self):
        charge, result = await self.exercise("cancel", asyncio.CancelledError)
        self.assertEqual(charge["status"], "uncertain")
        self.assertEqual(charge["charged"], charge["reserved"])
        self.assertEqual(result["stop_reason"], "request_cancelled")


if __name__ == "__main__":
    unittest.main()
