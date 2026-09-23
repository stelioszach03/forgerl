"""Behavioral checks for evidence integrity; no network or paid calls."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

from forgerl.research import aggregate_runs, collect_task_tree, evaluate_policy, run_research, validate_splits


class FakeBudgetExceeded(Exception):
    pass


class FakeEpisode:
    calls = []
    fail_after = None

    def __init__(self, task, provider, policy_id="fixed", max_steps=3, artifact=None):
        self.task, self.policy_id, self.max_steps = task, policy_id, max_steps
        self.attempts, self.source, self.events = 0, "original", []
        self.terminal, self.cost, self.status = False, 0.0, "running"
        self.hidden_seen = False

    async def start(self):
        return self.observation()

    def clone(self):
        return copy.deepcopy(self)

    def observation(self):
        # Single patch leaves tests failing, second fixes it. Both models use actual transitions.
        return {"attempts": self.attempts, "max_steps": self.max_steps, "public_passed": int(self.attempts >= 2),
                "public_total": 1, "cost_usd": self.cost, "last_action": self.events[-1] if self.events else None}

    async def step(self, action):
        if action == "stop":
            self.events.append("stop")
            self.terminal = True
            return self.observation()
        if self.fail_after is not None and len(type(self).calls) >= self.fail_after:
            self.status = "budget_exhausted"
            raise FakeBudgetExceeded("Research allowance exhausted")
        type(self).calls.append((self.task.id, self.policy_id, action))
        self.attempts += 1
        self.source += f"-{action}"
        self.events.append(action)
        self.cost += 0.01
        self.terminal = self.attempts >= self.max_steps
        return self.observation()

    async def finish(self):
        self.hidden_seen = True
        if self.status != "budget_exhausted":
            self.status = "completed"
        return self.result()

    def result(self):
        return {"id": f"{self.task.id}-{self.policy_id}-{self.source}", "status": self.status, "solved": self.hidden_seen and self.attempts >= 2,
                "steps": self.attempts, "cost_usd": self.cost, "tokens": 10 * self.attempts, "elapsed_s": 0.1,
                "events": list(self.events), "final_source": self.source}


def task(task_id="a", family="cache", split="train"):
    return SimpleNamespace(id=task_id, title=task_id, family=family, split=split)


class ResearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeEpisode.calls, FakeEpisode.fail_after = [], None
        self.old_provider = sys.modules.get("forgerl.provider")
        fake = types.ModuleType("forgerl.provider")
        fake.BudgetExceeded = FakeBudgetExceeded
        sys.modules["forgerl.provider"] = fake

    def tearDown(self):
        if self.old_provider is None:
            sys.modules.pop("forgerl.provider", None)
        else:
            sys.modules["forgerl.provider"] = self.old_provider

    def test_rejects_family_leakage_before_collection(self):
        with self.assertRaisesRegex(ValueError, "crosses splits"):
            validate_splits([task(), task("b", "cache", "validation"), task("c", "csv", "test")])

    async def test_branch_sources_independent_and_cost_not_double_counted(self):
        result = await collect_task_tree(task(), None, episode_factory=FakeEpisode, max_steps=3, cost_weight=5)
        # Two first actions and four second actions; every second action passes visible tests.
        self.assertEqual(len(FakeEpisode.calls), 6)
        self.assertAlmostEqual(result["collection_cost_usd"], 0.06)
        self.assertEqual(len(result["transitions"]), 9)  # three STOP probes plus six model calls
        self.assertEqual(result["transitions"][0]["reward"], 0.0)
        patch_transitions = [t for t in result["transitions"] if t["action"] != "stop"]
        self.assertAlmostEqual(sum(t["reward"] for t in patch_transitions), 4 - 0.3)
        self.assertTrue(all("hidden" not in json.dumps(t["state"]) for t in result["transitions"]))
        self.assertTrue(all(t["split"] == "train" for t in result["transitions"]))

    async def test_budget_denial_stops_remaining_branches(self):
        FakeEpisode.fail_after = 1
        result = await collect_task_tree(task(), None, episode_factory=FakeEpisode)
        self.assertTrue(result["partial"])
        self.assertEqual(result["reason"], "budget_exhausted")
        self.assertEqual(len(FakeEpisode.calls), 1)
        self.assertTrue(any(row["kind"] == "training-error" for row in result["traces"]))

    def test_aggregate_keeps_failure_and_marks_missing_coverage(self):
        runs = [{"task_id": "a", "family": "cache", "policy": "fixed", "status": "completed", "solved": True, "cost_usd": 0.01},
                {"task_id": "b", "family": "csv", "policy": "fixed", "status": "failed", "solved": False, "cost_usd": 0.02}]
        report = aggregate_runs(runs, ["a", "b", "c"], policies=("fixed",))
        row = report["summary"][0]
        self.assertEqual(report["status"], "partial")
        self.assertEqual(row["n"], 2)
        self.assertEqual(row["solve_rate"], 0.5)
        self.assertEqual(row["missing_task_ids"], ["c"])
        self.assertAlmostEqual(row["mean_cost_usd"], 0.015)

    async def test_test_episodes_are_fresh_and_frozen_after_fitting(self):
        tasks = [task(), task("b", "csv", "validation"), task("c", "datetime", "test")]
        fit_calls = []
        def fit(transitions, seed):
            fit_calls.append(copy.deepcopy(transitions))
            self.assertTrue(all(t["task_id"] == "a" for t in transitions))
            return {"version": 1, "seed": seed, "trained": True}
        def select(policy, observation, artifact):
            self.assertEqual(artifact["version"], 1)
            return "fast"
        with tempfile.TemporaryDirectory() as directory:
            report = await run_research(tasks, None, directory, episode_factory=FakeEpisode, fit_controller=fit,
                                        selector=select, task_manifest_hash="fixture", max_steps=3)
            self.assertEqual(report["status"], "complete")
            self.assertEqual(len(fit_calls), 1)
            self.assertEqual(len([r for r in FakeEpisode.calls if r[0] == "c"]), 8)
            self.assertTrue(all(r[1] != "research-tree" for r in FakeEpisode.calls if r[0] == "c"))
            manifest = json.loads((Path(directory) / "manifest.json").read_text())
            self.assertFalse(manifest["language_model_weights_updated"])
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(len(report["paired_runs"][0]["runs"]), 4)

    async def test_learned_stop_is_present_in_trace_without_model_call(self):
        result = await evaluate_policy(task("heldout", "time", "test"), None, "adaptive",
                                       episode_factory=FakeEpisode, selector=lambda *args: "stop", artifact={"trained": True})
        self.assertEqual(result["events"], ["stop"])
        self.assertEqual(result["steps"], 0)
        self.assertEqual(result["cost_usd"], 0.0)
        self.assertEqual(FakeEpisode.calls, [])
        self.assertEqual(result["status"], "completed")

    async def test_actual_task_catalog_and_controller_contract(self):
        from forgerl.controller import choose_action, fit_q
        from forgerl.tasks import list_tasks, task_manifest_hash
        with tempfile.TemporaryDirectory() as directory:
            report = await run_research(list_tasks(), None, directory, episode_factory=FakeEpisode,
                                        fit_controller=fit_q, selector=choose_action,
                                        task_manifest_hash=task_manifest_hash())
            self.assertEqual(report["status"], "complete")
            artifact = json.loads((Path(directory) / "controller.json").read_text())
            self.assertTrue(artifact["trained"])
            self.assertEqual(artifact["diagnostics"]["tasks"], 12)
            self.assertEqual([row["n"] for row in report["summary"]], [6, 6, 6, 6])
            self.assertTrue(all(action == "fast" for _, policy, action in FakeEpisode.calls if policy == "fixed"))
            self.assertTrue(all(action == "deliberate" for _, policy, action in FakeEpisode.calls if policy == "deliberate"))

    async def test_budget_exhausted_report_remains_partial_and_persists(self):
        FakeEpisode.fail_after = 0
        with tempfile.TemporaryDirectory() as directory:
            report = await run_research([task(), task("b", "csv", "validation"), task("c", "time", "test")], None, directory,
                                        episode_factory=FakeEpisode, fit_controller=lambda *a, **k: self.fail("Must not fit"),
                                        selector=lambda *a: "fast", task_manifest_hash="fixture")
            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["summary"][0]["n"], 0)
            self.assertTrue((Path(directory) / "raw-runs.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
