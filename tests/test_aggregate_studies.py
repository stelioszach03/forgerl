"""Independent aggregation checks; fixtures are labeled and contain no inference."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.aggregate_studies import EXPECTED_SEEDS, POLICIES, aggregate_studies


def fixture_study(
    directory: Path, seed: int, *, status="complete", failure=False, omit=0
):
    directory.mkdir()
    controller = {
        "trained": True,
        "seed": seed,
        "training_digest": f"fixture-seed-{seed}",
    }
    controller_hash = hashlib.sha256(
        json.dumps(controller, sort_keys=True).encode()
    ).hexdigest()
    manifest = {
        "protocol": "forgerl-pilot-v1",
        "controller_seed": seed,
        "status": status,
        "language_model_weights_updated": False,
        "task_manifest_sha256": "fixture-not-real-results",
        "splits": {
            "train": [f"train-{n}" for n in range(12)],
            "validation": [f"val-{n}" for n in range(6)],
            "test": [f"test-{n}" for n in range(6)],
        },
        "max_steps": 3,
        "cost_weight": 5.0,
        "policies": list(POLICIES),
        "controller_sha256": controller_hash,
        "collection_cost_usd": 0.5,
        "evaluation_cost_usd": 0.1,
        "training_partial": status != "complete",
    }
    (directory / "controller.json").write_text(json.dumps(controller))
    (directory / "manifest.json").write_text(json.dumps(manifest))
    records = []
    for split in ("validation", "test"):
        for number, task_id in enumerate(manifest["splits"][split]):
            for policy in POLICIES:
                failed = (
                    failure and split == "test" and number == 0 and policy == "adaptive"
                )
                run = {
                    "id": f"fixture-{seed}-{task_id}-{policy}",
                    "task_id": task_id,
                    "task_title": f"Fixture {task_id}",
                    "family": f"{split}-family-{number // 3}",
                    "split": split,
                    "policy": policy,
                    "evaluation_mode": "prospective",
                    "status": "failed" if failed else "completed",
                    "solved": not failed,
                    "steps": 1,
                    "tokens": None if failed else 100,
                    "tokens_complete": not failed,
                    "cost_usd": 0.02 if failed else 0.01,
                    "elapsed_s": 0.2,
                    "error": "fixture failure" if failed else None,
                }
                records.append({"kind": "prospective-evaluation", "run": run})
    if omit:
        records = records[:-omit]
    (directory / "raw-runs.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )
    return directory


class AggregationTests(unittest.TestCase):
    def test_three_replicates_are_18_episodes_not_18_unique_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = {
                seed: fixture_study(Path(folder) / str(seed), seed)
                for seed in EXPECTED_SEEDS
            }
            result = aggregate_studies(paths)
            self.assertEqual(result["status"], "complete")
            for summary in result["summary"]:
                self.assertEqual(summary["n"], 18)
                self.assertEqual(summary["unique_task_count"], 6)
                self.assertEqual(summary["family_count"], 2)
                self.assertEqual(summary["complete_replicates"], 3)
                self.assertIsNone(summary["solve_rate_wilson_95"])
            self.assertEqual(len(result["paired_runs"]), 18)
            self.assertEqual(
                len({row["comparison_id"] for row in result["paired_runs"]}), 18
            )
            self.assertEqual(len({row["task_id"] for row in result["paired_runs"]}), 6)
            self.assertTrue(
                all(
                    run["task_id"] == row["task_id"]
                    for row in result["paired_runs"]
                    for run in row["runs"]
                )
            )
            self.assertTrue(
                all(
                    row["family_bootstrap_95"] is None
                    for row in result["paired_differences"]
                )
            )
            for source in result["provenance"]["sources"]:
                self.assertEqual(len(source["manifest_sha256"]), 64)
                self.assertEqual(len(source["raw_evidence_sha256"]), 64)
            self.assertEqual(result["provenance"]["production_controller"]["seed"], 17)
            self.assertEqual(
                result["provenance"]["production_controller"]["training_digest"],
                "fixture-seed-17",
            )

    def test_failure_is_kept_in_denominator_and_token_uncertainty(self):
        with tempfile.TemporaryDirectory() as folder:
            result = aggregate_studies(
                {
                    seed: fixture_study(
                        Path(folder) / str(seed), seed, failure=seed == 29
                    )
                    for seed in EXPECTED_SEEDS
                }
            )
            row = next(row for row in result["summary"] if row["policy"] == "adaptive")
            self.assertEqual(row["n"], 18)
            self.assertEqual(row["solved"], 17)
            self.assertEqual(row["provider_or_execution_failures"], 1)
            self.assertIsNone(row["mean_tokens"])
            self.assertGreater(row["mean_cost_usd"], 0.01)
            pair = next(
                row
                for row in result["paired_runs"]
                if row["task_id"] == "test-0" and row["seed"] == 29
            )
            self.assertTrue(
                any(run["error"] == "fixture failure" for run in pair["runs"])
            )

    def test_missing_and_partial_seeds_never_claim_complete_or_replace_seed17(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = {
                29: fixture_study(Path(folder) / "29", 29, status="partial", omit=5),
                43: fixture_study(Path(folder) / "43", 43),
            }
            result = aggregate_studies(paths)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["provenance"]["missing_seeds"], [17])
            self.assertEqual(result["provenance"]["partial_seeds"], [29])
            self.assertFalse(result["provenance"]["production_controller"]["available"])
            self.assertEqual(result["provenance"]["production_controller"]["seed"], 17)
            self.assertTrue(all(row["planned_n"] == 18 for row in result["summary"]))
            self.assertTrue(all(row["n"] < 18 for row in result["summary"]))

    def test_budget_exhaustion_row_and_missing_coverage_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = {
                seed: fixture_study(
                    Path(folder) / str(seed),
                    seed,
                    status="partial" if seed == 43 else "complete",
                    omit=1 if seed == 43 else 0,
                )
                for seed in EXPECTED_SEEDS
            }
            path = paths[43] / "raw-runs.jsonl"
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            rows[-1]["run"].update(
                status="budget_exhausted",
                solved=False,
                error="fixture budget exhausted",
            )
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            result = aggregate_studies(paths)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(
                sum(row["budget_exhausted_episodes"] for row in result["summary"]), 1
            )
            self.assertEqual(
                sum(len(row["missing_task_seed_pairs"]) for row in result["summary"]), 1
            )
            self.assertTrue(
                any(
                    run.get("status") == "budget_exhausted"
                    for pair in result["paired_runs"]
                    for run in pair["runs"]
                )
            )

    def test_mismatched_tasks_or_controller_fingerprint_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = {
                seed: fixture_study(Path(folder) / str(seed), seed)
                for seed in EXPECTED_SEEDS
            }
            path = paths[29] / "manifest.json"
            manifest = json.loads(path.read_text())
            manifest["task_manifest_sha256"] = "different-task-suite"
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "mismatched"):
                aggregate_studies(paths)
            manifest["task_manifest_sha256"] = "fixture-not-real-results"
            manifest["controller_sha256"] = "wrong-policy-fingerprint"
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
                aggregate_studies(paths)

    def test_duplicate_attempt_is_rejected_instead_of_selecting_best(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = fixture_study(Path(folder) / "17", 17)
            path = directory / "raw-runs.jsonl"
            original = path.read_text()
            path.write_text(original + original.splitlines()[0] + "\n")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                aggregate_studies({17: directory})


if __name__ == "__main__":
    unittest.main()
