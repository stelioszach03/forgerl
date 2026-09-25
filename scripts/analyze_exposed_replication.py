"""Verify the exposed ForgeBench replication and publish aggregate-only evidence.

The input archive and ledger receipt remain private. Derived outputs contain no
prompts, patches, model responses, or credentials. This script makes no API calls.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import tarfile
from collections import Counter, defaultdict
from pathlib import Path


def canonical_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def put_csv(path: Path, rows: list[dict]) -> None:
    assert rows
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--ledger-receipt", type=Path, required=True)
    parser.add_argument("--public-freeze", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    runs = []
    raw_index = []
    events = Counter()
    event_run_ids = set()
    manifest = None
    freeze = None
    with tarfile.open(args.archive, "r|gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = member.name.removeprefix("./")
            file = tar.extractfile(member)
            assert file is not None
            if name == "manifest.json":
                manifest = json.load(file)
            elif name == "freeze.json":
                freeze = json.load(file)
            elif name == "raw-runs.jsonl":
                raw_index = [json.loads(line) for line in file]
            elif name == "events.jsonl":
                for line in file:
                    row = json.loads(line)
                    events[row["event"]["kind"]] += 1
                    event_run_ids.add(row["run_id"])
            elif name.startswith("runs/") and name.endswith(".json"):
                run = json.load(file)
                assert Path(name).stem == run["id"]
                runs.append(run)

    assert manifest and freeze and manifest["status"] == "complete" and manifest["missing"] == []
    assert freeze == json.loads(args.public_freeze.read_text())
    assert freeze["sha256"] == canonical_digest({k: v for k, v in freeze.items() if k != "sha256"})
    design = freeze["configuration"]["study_order"]
    expected = {row["design_id"]: row for row in design}
    assert len(expected) == manifest["planned"] == manifest["completed"] == len(runs) == 1296
    assert len(raw_index) == 1296
    assert len({row["id"] for row in runs}) == 1296
    assert event_run_ids == {row["id"] for row in runs}
    assert Counter(row["run_id"] for row in raw_index) == Counter({row["id"]: 1 for row in runs})
    assert {row["phase"] for row in raw_index} == {"exposed_replication"}
    run_by_id = {row["id"]: row for row in runs}
    assert all(row["status"] == run_by_id[row["run_id"]]["status"] for row in raw_index)
    seen_design = set()
    for run in runs:
        row = run["design"]
        assert row["design_id"] in expected and row == expected[row["design_id"]]
        assert row["design_id"] not in seen_design
        assert run["seed"] == row["seed"] and run["task_id"] == row["task_id"] and run["policy"] == row["policy"]
        assert run["verification_enabled"] == row["verify_enabled"] and run["split"] == row["original_split"]
        assert run["evidence_scope"] == "replication_on_previously_exposed_catalog"
        seen_design.add(row["design_id"])
    assert seen_design == set(expected)
    assert {x["status"] for x in runs} <= {"completed", "failed"}
    cost = sum(x["cost_usd"] for x in runs)
    assert abs(cost - manifest["accounted_cost_delta_usd"]) < 1e-8
    receipt = json.loads(args.ledger_receipt.read_text())["snapshots"]
    before, after = receipt["before"], receipt["after"]
    ledger_delta_micro = after["research"]["charged_micro_usd"] - before["research"]["charged_micro_usd"]
    assert ledger_delta_micro == round(cost * 1_000_000)
    assert before["public"]["charged_micro_usd"] == after["public"]["charged_micro_usd"]

    cells = []
    for run in sorted(runs, key=lambda x: (x["split"], x["policy"], x["seed"], x["task_id"], x["verification_enabled"])):
        model_events = sum(event["kind"] == "model" for event in run["events"])
        caught = sum(
            event["kind"] == "tests"
            and event.get("data", {}).get("visibility") == "public_supplemental"
            and event["data"].get("passed", 0) < event["data"].get("total", 0)
            for event in run["events"]
        )
        provider_reported = sum(
            event["data"].get("cost_usd", 0)
            for event in run["events"]
            if event["kind"] in ("inference", "error")
            and type(event.get("data", {}).get("provider_reported_cost_usd")) in (int, float)
        )
        cells.append({
            "design_id": run["design"]["design_id"],
            "split": run["split"],
            "family": run["family"],
            "task_id": run["task_id"],
            "seed": run["seed"],
            "policy": run["policy"],
            "verify_enabled": int(run["verification_enabled"]),
            "status": run["status"],
            "solved": int(run["solved"]),
            "accounted_cost_usd": run["cost_usd"],
            "provider_reported_cost_usd": provider_reported,
            "conservative_reserve_usd": max(0, run["cost_usd"] - provider_reported),
            "elapsed_s": run["elapsed_s"],
            "tool_calls": run["tool_calls"],
            "attempts": run["attempts"],
            "model_events": model_events,
            "provider_retries": run["provider_retries"],
            "tokens_complete": int(run["tokens_complete"]),
            "known_tokens": run.get("known_tokens") or 0,
            "unknown_token_upper_bound": run.get("unknown_token_upper_bound") or 0,
            "hidden_passed": run.get("heldout_passed") or 0,
            "hidden_total": run.get("heldout_total") or 0,
            "public_passed": run.get("public_passed") or 0,
            "public_total": run.get("public_total") or 0,
            "verification_calls": run.get("verification_calls") or 0,
            "verification_elapsed_s": run.get("verification_elapsed_s") or 0,
            "caught_supplemental_failures": caught,
            "supplemental_grader_disagreement": "unknown" if run["verification_grader_disagreement"] is None else int(run["verification_grader_disagreement"]),
            "supplemental_grader_disagreement_direction": run.get("verification_grader_disagreement_direction") or "",
            "success_after_repair": int(run["success_after_repair"]),
            "regressions_introduced": run["regressions_introduced"] or 0,
            "unnecessary_edits": run["unnecessary_edits"] or 0,
        })

    policy_summary = []
    verify_effect = []
    for split in ("test", "validation", "external"):
        for policy in sorted({run["policy"] for run in runs}):
            group = [run for run in runs if run["split"] == split and run["policy"] == policy]
            assert len(group) == {"test": 144, "validation": 48, "external": 24}[split]
            total_cost = sum(run["cost_usd"] for run in group)
            policy_summary.append({
                "split": split,
                "policy": policy,
                "attempted": len(group),
                "solved": sum(run["solved"] for run in group),
                "provider_failed": sum(run["status"] == "failed" for run in group),
                "accounted_cost_usd": round(total_cost, 6),
                "mean_cost_usd_per_episode": total_cost / len(group),
                "median_elapsed_s": statistics.median(run["elapsed_s"] for run in group),
                "mean_tool_calls": statistics.mean(run["tool_calls"] for run in group),
                "tokens_complete": sum(run["tokens_complete"] for run in group),
                "hidden_passed": sum(run.get("heldout_passed") or 0 for run in group),
                "hidden_total": sum(run.get("heldout_total") or 0 for run in group),
                "verification_calls": sum(run.get("verification_calls") or 0 for run in group),
                "verification_elapsed_s": sum(run.get("verification_elapsed_s") or 0 for run in group),
            })
            pairs = defaultdict(dict)
            for run in group:
                key = (run["seed"], run["task_id"])
                assert run["verification_enabled"] not in pairs[key]
                pairs[key][run["verification_enabled"]] = run
            assert len(pairs) * 2 == len(group)
            assert all(set(pair) == {False, True} for pair in pairs.values())
            verify_effect.append({
                "split": split,
                "policy": policy,
                "paired_tasks_seeds": len(pairs),
                "off_solved": sum(pair[False]["solved"] for pair in pairs.values()),
                "on_solved": sum(pair[True]["solved"] for pair in pairs.values()),
                "on_gain": sum(not pair[False]["solved"] and pair[True]["solved"] for pair in pairs.values()),
                "on_loss": sum(pair[False]["solved"] and not pair[True]["solved"] for pair in pairs.values()),
                "off_cost_usd": round(sum(pair[False]["cost_usd"] for pair in pairs.values()), 6),
                "on_cost_usd": round(sum(pair[True]["cost_usd"] for pair in pairs.values()), 6),
            })

    # The primary estimand gives each related task family equal weight. Preserve
    # every family/seed/policy pair rather than treating variants as independent.
    family_paired = []
    primary = [run for run in runs if run["split"] == "test"]
    for family in sorted({run["family"] for run in primary}):
        for seed in (31, 47, 73, 101):
            for policy in sorted({run["policy"] for run in primary}):
                pair = {
                    enabled: [run for run in primary if run["family"] == family and run["seed"] == seed and run["policy"] == policy and run["verification_enabled"] == enabled]
                    for enabled in (False, True)
                }
                assert len(pair[False]) == len(pair[True]) == 3
                off, on = pair[False], pair[True]
                family_paired.append({
                    "family": family,
                    "seed": seed,
                    "policy": policy,
                    "related_tasks": 3,
                    "off_solved": sum(run["solved"] for run in off),
                    "on_solved": sum(run["solved"] for run in on),
                    "verify_minus_off_success_fraction": (sum(run["solved"] for run in on) - sum(run["solved"] for run in off)) / 3,
                    "off_mean_cost_usd": statistics.mean(run["cost_usd"] for run in off),
                    "on_mean_cost_usd": statistics.mean(run["cost_usd"] for run in on),
                    "verify_minus_off_mean_cost_usd": statistics.mean(run["cost_usd"] for run in on) - statistics.mean(run["cost_usd"] for run in off),
                })
    assert len(family_paired) == 144
    seed_summary = []
    for seed in (31, 47, 73, 101):
        for policy in sorted({run["policy"] for run in primary}):
            group = [run for run in primary if run["seed"] == seed and run["policy"] == policy]
            assert len(group) == 36
            seed_summary.append({
                "seed": seed,
                "policy": policy,
                "attempted": 36,
                "solved": sum(run["solved"] for run in group),
                "provider_failed": sum(run["status"] == "failed" for run in group),
                "accounted_cost_usd": sum(run["cost_usd"] for run in group),
            })

    provider_codes = Counter()
    for run in runs:
        if run["status"] != "failed":
            continue
        match = re.search(r"HTTP\s+([45]\d\d)", run["error"] or "")
        provider_codes[match.group(1) if match else "unclassified"] += 1
    failure_labels = Counter(label for run in runs for label in run["failure_labels"])
    slice_metrics = {}
    for split in ("test", "validation", "external"):
        group = [row for row in cells if row["split"] == split]
        slice_metrics[split] = {
            "attempted": len(group),
            "solved": sum(row["solved"] for row in group),
            "hidden_passed": sum(row["hidden_passed"] for row in group),
            "hidden_total": sum(row["hidden_total"] for row in group),
            "public_passed": sum(row["public_passed"] for row in group),
            "public_total": sum(row["public_total"] for row in group),
            "model_events": sum(row["model_events"] for row in group),
            "tool_calls": sum(row["tool_calls"] for row in group),
            "verification_calls": sum(row["verification_calls"] for row in group),
            "verification_elapsed_s": sum(row["verification_elapsed_s"] for row in group),
            "caught_supplemental_failure_events": sum(row["caught_supplemental_failures"] for row in group),
            "episodes_with_caught_supplemental_failure": sum(row["caught_supplemental_failures"] > 0 for row in group),
            "solved_after_caught_supplemental_failure": sum(row["caught_supplemental_failures"] > 0 and row["solved"] for row in group),
            "supplemental_missed_hidden_failure": sum(row["supplemental_grader_disagreement_direction"] == "missed_failure" for row in group),
            "success_after_repair": sum(row["success_after_repair"] for row in group),
            "regressions_introduced": sum(row["regressions_introduced"] for row in group),
            "unnecessary_edits_proxy": sum(row["unnecessary_edits"] for row in group),
        }
    summary = {
        "schema": "exposed-replication-reviewed-v1",
        "freeze_sha256": freeze["sha256"],
        "source_commit": freeze["source_commit"],
        "archive_sha256": hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        "scope": "Previously exposed v0.3 catalog; no fresh held-out generalization claim.",
        "attempted": len(runs),
        "recorded_completed": sum(run["status"] == "completed" for run in runs),
        "provider_failed": sum(run["status"] == "failed" for run in runs),
        "solved": sum(run["solved"] for run in runs),
        "cost_accounting": "Provider reported usage.cost with conservative reservation for uncertain calls; fees excluded.",
        "accounted_cost_delta_usd": round(cost, 6),
        "provider_reported_cost_usd": round(sum(row["provider_reported_cost_usd"] for row in cells), 6),
        "conservative_reserve_usd": round(sum(row["conservative_reserve_usd"] for row in cells), 6),
        "research_ledger_charged_before_usd": before["research"]["charged_micro_usd"] / 1_000_000,
        "research_ledger_charged_after_usd": after["research"]["charged_micro_usd"] / 1_000_000,
        "public_ledger_unchanged": True,
        "tokens_complete_runs": sum(run["tokens_complete"] for run in runs),
        "known_tokens": sum(row["known_tokens"] for row in cells),
        "unknown_token_upper_bound": sum(row["unknown_token_upper_bound"] for row in cells),
        "events": sum(events.values()),
        "event_types": dict(sorted(events.items())),
        "provider_failure_http_codes": dict(sorted(provider_codes.items())),
        "failure_labels": dict(sorted(failure_labels.items())),
        "slice_metrics": slice_metrics,
        "policy_summary": policy_summary,
        "verify_effect": verify_effect,
        "family_paired": family_paired,
        "seed_summary": seed_summary,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    put_csv(args.output / "cells.csv", cells)
    put_csv(args.output / "policy-summary.csv", policy_summary)
    put_csv(args.output / "verify-effect.csv", verify_effect)
    put_csv(args.output / "family-paired.csv", family_paired)
    put_csv(args.output / "seed-summary.csv", seed_summary)
    (args.output / "summary.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"attempted": len(runs), "solved": summary["solved"], "provider_failed": summary["provider_failed"], "cost_usd": summary["accounted_cost_delta_usd"], "events": summary["events"]}, sort_keys=True))


if __name__ == "__main__":
    main()
