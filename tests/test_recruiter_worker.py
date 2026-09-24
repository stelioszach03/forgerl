"""Synthetic broker-worker contract tests; no hosted requests or host execution."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from forgerl.recruiter.broker import curated_task, work
from forgerl.recruiter.state import BrokerState, PublicChargeAdapter, TASK_ID, POLICY
from forgerl.store import Store


@pytest.mark.asyncio
async def test_private_worker_one_candidate_fixed_task_and_final_only_hidden_checks(
    tmp_path,
):
    ledger = tmp_path / "ledger.sqlite3"
    Store(ledger)
    state = BrokerState(ledger, b"private-worker-unit-test-session-secret" * 2)
    session = state.start_session("198.51.100.1")
    job = state.admit(
        session["session"], "198.51.100.1", session["csrf"], TASK_ID, POLICY
    )
    task = curated_task()
    calls = []
    checks = []

    class Provider:
        async def generate(self, task, files, feedback, action, **kwargs):
            calls.append({"task": task.id, "action": action, "feedback": feedback})
            adapter = PublicChargeAdapter(state, job["id"])
            receipt = adapter.reserve(
                "research", "openai/gpt-oss-20b", 1000, kwargs["run_id"]
            )
            adapter.settle(receipt, 100, {"cost": 0.0001})
            return SimpleNamespace(
                files=task.reference_files,
                model="fixture",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                cost_usd=0.0001,
                elapsed_s=0.1,
                request_id="fixture",
                finish_reason="stop",
                prompt_messages=[],
                response_text="fixture",
                request_config={"authorization": "private-marker"},
            )

        async def close(self):
            pass

    def evaluator(task, files, hidden=False):
        checks.append(hidden)
        cases = task.hidden_cases if hidden else task.public_cases
        passed = files == task.reference_files
        return {
            "passed": len(cases) if passed else 0,
            "total": len(cases),
            "cases": [],
            "elapsed_s": 0.1,
            "execution_error": None,
        }

    app = SimpleNamespace(
        state=SimpleNamespace(
            broker=state,
            curated_task=task,
            provider_factory=lambda *args: Provider(),
            evaluator=evaluator,
        )
    )
    worker = asyncio.create_task(work(app))
    try:
        for _ in range(100):
            snapshot = state.view(job["id"], session["session"], "198.51.100.1")
            if snapshot["status"] == "completed":
                break
            await asyncio.sleep(0.01)
        assert snapshot["status"] == "completed" and snapshot["result"]["solved"]
        assert (
            len(calls) == 1
            and calls[0]["task"] == TASK_ID
            and calls[0]["action"] == "cheap"
        )
        assert checks == [False, False, True]
        assert snapshot["result"]["is_benchmark"] is False
        encoded = json.dumps(snapshot)
        assert (
            "private-marker" not in encoded
            and "hidden_cases" not in encoded
            and "reference_files" not in encoded
        )
        with state.store.connect() as c:
            assert (
                c.execute("SELECT bucket,charged FROM charges").fetchall()[0]["bucket"]
                == "public"
            )
            assert c.execute("SELECT COUNT(*) FROM charges").fetchone()[0] == 1
    finally:
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
