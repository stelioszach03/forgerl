#!/usr/bin/env python3
"""Combine the predeclared 17/29/43 studies without inventing independent tasks."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Mapping

EXPECTED_SEEDS = (17, 29, 43)
PRODUCTION_SEED = 17
POLICIES = ("fixed", "deliberate", "heuristic", "adaptive")
PROTOCOL = "forgerl-three-seed-pilot-v1"
PREDECLARED_AT = "2026-09-23T03:46:42Z"
FROZEN_METHODOLOGY_SHA256 = "3e5e5b666de9f4fc037606b006704bfeb522b94eb770cf9f93bb324663dd7d8b"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path.name}")
    return value


def _solved(run: dict) -> bool:
    return run.get("status") == "completed" and run.get("solved") is True


def _mean(runs: list[dict], key: str) -> float | None:
    if not runs:
        return None
    values = []
    for run in runs:
        value = run.get(key)
        if value is None or (key == "tokens" and run.get("tokens_complete") is False):
            return None
        if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid measured metric {key} in run {run.get('id')}")
        values.append(value)
    return sum(values) / len(values)


def _summarize(runs: list[dict], task_ids: list[str], seeds: tuple[int, ...]) -> dict:
    expected_keys = {(task_id, seed) for task_id in task_ids for seed in seeds}
    summaries = []
    by_policy = {policy: [r for r in runs if r["policy"] == policy] for policy in POLICIES}
    for policy, items in by_policy.items():
        actual_keys = {(r["task_id"], r["study_seed"]) for r in items}
        missing = sorted(expected_keys - actual_keys, key=lambda key: (key[1], key[0]))
        families = {r["family"] for r in items}
        complete_replicates = sum(all((task_id, seed) in actual_keys for task_id in task_ids) for seed in seeds) if task_ids else 0
        successes = sum(_solved(r) for r in items)
        summaries.append({
            "policy": policy, "n": len(items), "n_unit": "evaluation episodes", "planned_n": len(expected_keys),
            "solved": successes, "solve_rate": successes / len(items) if items else None,
            "unique_task_count": len({r["task_id"] for r in items}), "planned_unique_task_count": len(task_ids),
            "family_count": len(families), "replicates_observed": len({r["study_seed"] for r in items}),
            "replicates_planned": len(seeds), "complete_replicates": complete_replicates,
            "mean_steps": _mean(items, "steps"), "mean_tokens": _mean(items, "tokens"),
            "mean_cost_usd": _mean(items, "cost_usd"), "mean_latency_s": _mean(items, "elapsed_s"),
            "provider_or_execution_failures": sum(r.get("status") != "completed" for r in items),
            "budget_exhausted_episodes": sum(r.get("status") == "budget_exhausted" for r in items),
            "tokens_incomplete_episodes": sum(r.get("tokens") is None or r.get("tokens_complete") is False for r in items),
            "solve_rate_wilson_95": None,
            "interval_note": "Not estimated: repeated task/seed episodes are dependent; only two held-out families were predeclared.",
            "missing_task_seed_pairs": [{"task_id": task_id, "seed": seed} for task_id, seed in missing],
        })
    paired = []
    for seed in seeds:
        for task_id in task_ids:
            items = [r for r in runs if r["task_id"] == task_id and r["study_seed"] == seed]
            original_title = next((r.get("task_title", task_id) for r in items), task_id)
            paired.append({"comparison_id": f"{task_id}@seed={seed}", "task_id": task_id,
                           "task_title": f"{original_title} · seed {seed}", "seed": seed, "runs": items})
    learned = {(r["task_id"], r["study_seed"]): r for r in by_policy["adaptive"]}
    differences = []
    for policy in POLICIES:
        if policy == "adaptive":
            continue
        baseline = {(r["task_id"], r["study_seed"]): r for r in by_policy[policy]}
        common = sorted(set(learned) & set(baseline))
        values = [int(_solved(learned[key])) - int(_solved(baseline[key])) for key in common]
        differences.append({"baseline": policy, "paired_n": len(common), "n_unit": "paired task/seed episodes",
                            "unique_task_count": len({key[0] for key in common}),
                            "family_n": len({learned[key]["family"] for key in common}),
                            "solve_rate_difference": sum(values) / len(values) if values else None,
                            "family_bootstrap_95": None,
                            "interval_note": "Not estimated: two held-out families are insufficient for a meaningful family-cluster interval."})
    complete = bool(task_ids) and all(not row["missing_task_seed_pairs"] for row in summaries)
    return {"status": "complete" if complete else "partial", "summary": summaries, "paired_runs": paired,
            "paired_differences": differences, "episode_count": len(runs),
            "unique_task_count": len({r["task_id"] for r in runs}), "planned_unique_task_count": len(task_ids),
            "family_count": len({r["family"] for r in runs}), "requested_replicates": list(seeds)}


def aggregate_studies(studies: Mapping[int, Path | str]) -> dict:
    """Read original evidence; reject conflicts, but preserve missing/partial seeds."""
    if set(studies) - set(EXPECTED_SEEDS):
        raise ValueError("Only predeclared seeds 17, 29 and 43 may enter this aggregate")
    manifests, provenance, runs, canonical = {}, [], [], None
    family_by_task: dict[str, str] = {}
    seen = set()
    production = {"seed": PRODUCTION_SEED, "selection": "fixed before evaluation; never best-of-three", "available": False}
    for seed in EXPECTED_SEEDS:
        directory = Path(studies[seed]) if seed in studies else None
        manifest_path = directory / "manifest.json" if directory else None
        entry = {"seed": seed, "source_directory": directory.name if directory else None,
                 "status": "missing", "manifest_sha256": None, "raw_evidence_sha256": None}
        if manifest_path is None or not manifest_path.is_file():
            provenance.append(entry)
            continue
        manifest = read_json(manifest_path)
        if manifest.get("controller_seed") != seed:
            raise ValueError(f"Manifest seed disagrees with study mapping for seed {seed}")
        if manifest.get("language_model_weights_updated") is not False:
            raise ValueError("Source study does not affirm frozen language-model weights")
        signature = {key: manifest.get(key) for key in ("protocol", "task_manifest_sha256", "splits", "max_steps", "cost_weight", "policies")}
        if not signature["task_manifest_sha256"] or set(signature["policies"] or []) != set(POLICIES):
            raise ValueError("Source study lacks a valid task hash or policy set")
        if canonical is None:
            canonical = signature
        elif signature != canonical:
            raise ValueError("Source studies have mismatched tasks, splits, policies or protocol parameters")
        splits = signature["splits"]
        if not isinstance(splits, dict) or set(splits) != {"train", "validation", "test"}:
            raise ValueError("Source study split manifest is incomplete")
        all_task_ids = [task_id for ids in splits.values() for task_id in ids]
        if len(all_task_ids) != len(set(all_task_ids)):
            raise ValueError("Source split manifest repeats a task ID")
        manifests[seed] = manifest
        entry.update(status=manifest.get("status", "unknown"), manifest_sha256=sha256(manifest_path),
                     controller_sha256=manifest.get("controller_sha256"), reason=manifest.get("reason"),
                     collection_cost_usd=manifest.get("collection_cost_usd"), evaluation_cost_usd=manifest.get("evaluation_cost_usd"),
                     training_partial=manifest.get("training_partial", False))
        controller_path = directory / "controller.json"
        if controller_path.is_file():
            controller = read_json(controller_path)
            digest = hashlib.sha256(json.dumps(controller, sort_keys=True).encode()).hexdigest()
            if manifest.get("controller_sha256") and manifest["controller_sha256"] != digest:
                raise ValueError(f"Controller fingerprint mismatch for seed {seed}")
            entry["controller_file_sha256"] = sha256(controller_path)
            if seed == PRODUCTION_SEED:
                production.update(available=controller.get("trained") is True, artifact_sha256=sha256(controller_path),
                                  training_digest=controller.get("training_digest"))
        raw_path = directory / "raw-runs.jsonl"
        if not raw_path.is_file():
            entry.update(status="partial", reason="raw_evidence_missing")
            provenance.append(entry)
            continue
        entry["raw_evidence_sha256"] = sha256(raw_path)
        for line_number, line in enumerate(raw_path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed raw evidence at seed {seed}, line {line_number}") from exc
            if not isinstance(record, dict):
                raise ValueError("Raw evidence must contain objects")
            if record.get("kind") != "prospective-evaluation":
                continue
            run = record.get("run")
            if not isinstance(run, dict) or run.get("evaluation_mode") != "prospective":
                raise ValueError("Evaluation record is not explicitly prospective")
            split, policy, task_id = run.get("split"), run.get("policy"), run.get("task_id")
            if split not in ("validation", "test") or task_id not in splits[split] or policy not in POLICIES:
                raise ValueError("Evaluation row falls outside its predeclared split or policy")
            if not isinstance(run.get("family"), str) or not run["family"]:
                raise ValueError("Evaluation row has no task family")
            if type(run.get("solved")) is not bool:
                raise ValueError("Evaluation row lacks a boolean solved outcome")
            family = run["family"]
            if task_id in family_by_task and family_by_task[task_id] != family:
                raise ValueError("Task family changed across source studies")
            family_by_task[task_id] = family
            identity = (seed, split, policy, task_id)
            if identity in seen:
                raise ValueError("Duplicate task/seed/policy evaluation; do not select a favorable duplicate")
            seen.add(identity)
            runs.append({**run, "study_seed": seed, "source_manifest_sha256": entry["manifest_sha256"]})
        provenance.append(entry)
    task_splits = canonical["splits"] if canonical else {"train": [], "validation": [], "test": []}
    test_runs = [run for run in runs if run["split"] == "test"]
    report = _summarize(test_runs, task_splits["test"], EXPECTED_SEEDS)
    report["validation"] = _summarize([run for run in runs if run["split"] == "validation"], task_splits["validation"], EXPECTED_SEEDS)
    source_complete = all(entry["status"] == "complete" and not entry.get("training_partial") for entry in provenance)
    if not source_complete or report["validation"]["status"] != "complete":
        report["status"] = "partial"
    report["methodology"] = {
        "protocol": PROTOCOL, "description": "Three predeclared seed replicates on six unique held-out tasks from two families. Full coverage is 18 episodes per policy, not 18 independent tasks. Failed and missing runs remain visible.",
        "max_steps": canonical["max_steps"] if canonical else 3, "controller_training": "finite-horizon fitted Q; separate training per seed",
        "language_model_weights_updated": False, "predeclared_seeds": list(EXPECTED_SEEDS),
        "unique_heldout_tasks_planned": len(task_splits["test"]) if canonical else 6,
        "heldout_families_planned": 2, "confidence_intervals": "Not estimated: only two held-out families; seed repeats are not independent tasks.",
        "production_policy_seed": PRODUCTION_SEED,
    }
    report["seed_summaries"] = [{"seed": seed, "status": next(item["status"] for item in provenance if item["seed"] == seed),
                                "summary": _summarize([r for r in test_runs if r["study_seed"] == seed], task_splits["test"], (seed,))["summary"]} for seed in EXPECTED_SEEDS]
    report["provenance"] = {
        "protocol": PROTOCOL, "predeclared_at": PREDECLARED_AT, "frozen_methodology_sha256": FROZEN_METHODOLOGY_SHA256,
        "sources": provenance, "task_manifest_sha256": canonical["task_manifest_sha256"] if canonical else None,
        "production_controller": production, "requested_seeds": list(EXPECTED_SEEDS),
        "missing_seeds": [entry["seed"] for entry in provenance if entry["status"] == "missing"],
        "partial_seeds": [entry["seed"] for entry in provenance if entry["status"] not in ("missing", "complete") or entry.get("training_partial")],
        "collection_cost_usd": sum(float(m.get("collection_cost_usd", 0) or 0) for m in manifests.values()),
        "evaluation_cost_usd": sum(float(m.get("evaluation_cost_usd", 0) or 0) for m in manifests.values()),
        "cost_basis": "Conservative token-rate estimates; failed requests with uncertain charges retain reservations.",
    }
    report["limitations"] = [
        "Six unique held-out tasks from two authored defect families; three requested seeds produce repeated episodes, not additional independent tasks.",
        "No ordinary binomial or family-cluster confidence interval is claimed for the repeated small suite.",
        "Three seed-specific controllers were evaluated; the production artifact was fixed to seed17 before evaluation, without selecting the highest score.",
        "The hosted language-model weights remain unchanged. This is a controller pilot, not LLM fine-tuning or a SWE-bench result.",
        "Provider seeds do not guarantee deterministic sampling. Token, cost and latency summaries retain failures and unknown accounting states.",
        "Budget exhaustion or incomplete source studies mark this aggregate partial; no missing run is silently dropped or counted as solved.",
    ]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", action="append", required=True, metavar="SEED=DIRECTORY")
    parser.add_argument("--output", type=Path, required=True, help="Combined benchmark.json output")
    args = parser.parse_args()
    mapping = {}
    for item in args.study:
        seed_text, separator, directory = item.partition("=")
        if not separator or not directory:
            parser.error("Use --study 17=PATH (and similarly for29/43)")
        try:
            seed = int(seed_text)
        except ValueError:
            parser.error("Study seed must be17,29 or43")
        if seed in mapping:
            parser.error("Each seed can be supplied once")
        mapping[seed] = Path(directory)
    result = aggregate_studies(mapping)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(args.output)
    print(json.dumps({"status": result["status"], "output": str(args.output), "summary": result["summary"]}, indent=2))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
