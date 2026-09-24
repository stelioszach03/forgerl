#!/usr/bin/env python3
"""Export a public read-only view of the completed pilot; no inference."""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyze_pilot_forgebench import analyze, read_runs
from forgerl.bench.api import scrub
from forgerl.bench.pilot import all_specs, task_digest
from forgerl.bench.tasks import public_task

LABELS = {
    "strong_only": "Strong model only",
    "cheap_only": "Cheap model only",
    "escalate_on_failure": "Escalate on failure",
    "static_router": "Hand-written router",
    "adaptive": "Fitted-Q transfer",
    "supervised_cost": "Supervised return",
}
ROOT = Path(__file__).resolve().parents[1]


def export(pilot_root, output):
    pilot_root, output = Path(pilot_root).resolve(), Path(output).resolve()
    study = pilot_root / "study"
    if output == study or study in output.parents:
        raise ValueError("Do not write into the immutable study")
    frozen, manifest, runs, _ = read_runs(study)
    analysis, _ = analyze(study)
    published = json.loads((pilot_root / "analysis/analysis.json").read_text())
    if {k: v for k, v in analysis.items() if k != "analysis_source_sha256"} != {
        k: v for k, v in published.items() if k != "analysis_source_sha256"
    }:
        raise ValueError("Published analysis and actual run records differ")
    if task_digest() != frozen["configuration"]["task_manifest_sha256"]:
        raise ValueError("Current catalog differs from the evaluated frozen tasks")
    tasks = {
        spec.task.id: public_task(spec.task, include_cases=True) for spec in all_specs()
    }
    for run in runs:
        if (
            run["task_id"] not in tasks
            or run["initial_files"] != tasks[run["task_id"]]["files"]
        ):
            raise ValueError("Run starting source differs from its evaluated catalog")
    splits = {}
    for split in ("test", "validation", "external"):
        rows = []
        for row in published["summary"]:
            if row["split"] != split:
                continue
            selected = [
                r for r in runs if r["split"] == split and r["policy"] == row["policy"]
            ]
            repaired = [r for r in selected if r["attempts"] > 1]
            rows.append(
                {
                    **row,
                    "n": row["attempted"],
                    "solved": sum(
                        r["solved"] and r["status"] == "completed" for r in selected
                    ),
                    "solve_rate": row["family_weighted_success"],
                    "hidden_test_pass_rate": row["hidden_pass_fraction"],
                    "mean_cost_usd": row["family_weighted_cost_usd"],
                    "graded_runs": row["graded_episodes"],
                    "mean_steps": row["mean_attempts"],
                    "success_after_repair_rate": sum(
                        r["success_after_repair"] for r in repaired
                    )
                    / len(repaired)
                    if repaired
                    else None,
                    "escalation_frequency": sum(r["escalations"] > 0 for r in selected)
                    / len(selected)
                    if selected
                    else None,
                    "mean_verification_calls": row["verification_calls"] / len(selected)
                    if selected
                    else None,
                }
            )
        splits[split] = rows
    lightweight = [
        {
            k: v
            for k, v in run.items()
            if k not in ("events", "initial_files", "final_files", "diff")
        }
        for run in runs
    ]
    by_id = {r["id"]: r for r in runs}
    examples = {
        "repair": {
            "task_id": "tabular_join-repair-3",
            "run_id": "85191dbfa28b4137971ba2ab04971634",
            "description": "A recorded repair followed by supplemental verification and final grading.",
        },
        "verification_miss": {
            "task_id": "edit_distance-repair-2",
            "run_id": "bf3d0fe898ac434ebc3e988b3d88986d",
            "description": "Supplemental checks pass, but the final hidden grader rejects the candidate.",
        },
    }
    if any(by_id[e["run_id"]]["task_id"] != e["task_id"] for e in examples.values()):
        raise ValueError("Walkthrough references do not match recorded runs")
    if (
        not by_id[examples["repair"]["run_id"]]["solved"]
        or by_id[examples["verification_miss"]["run_id"]][
            "verification_grader_disagreement_direction"
        ]
        != "missed_failure"
    ):
        raise ValueError(
            "Walkthrough descriptions are not supported by actual outcomes"
        )
    benchmark = {
        "version": "0.3-pilot1",
        "status": manifest["status"],
        "generated_at": manifest["finished_at"],
        "task_count": len(tasks),
        "family_count": len({t["family"] for t in tasks.values()}),
        "catalog": {
            "task_count": len(tasks),
            "family_count": 9,
            "task_manifest_hash": task_digest(),
            "public_mode": "recorded_only",
        },
        "models": sorted({model for run in runs for model in run["model_ids"]}),
        "policies": [{"id": k, "label": v} for k, v in LABELS.items()],
        "coverage": {
            "completed": manifest["completed"],
            "planned": manifest["planned"],
            "missing": manifest["missing"],
            "training_completed": 0,
            "evaluated_unique_tasks": len(tasks),
            "summary_split": "test",
            "description": "24 new authored tasks plus 3 licensed source-derived mutation tasks. Primary test: 18 tasks in 6 families; validation and source-derived tracks stay separate. One requested seed.",
        },
        "summary": splits["test"],
        "summary_by_split": splits,
        "runs": lightweight,
        "walkthroughs": examples,
        "downloads": [
            "technical-report.pdf",
            "technical-report.md",
            "results.csv",
            "analysis.json",
            "trajectories.jsonl",
        ],
        "provenance": {
            "protocol": frozen["configuration"]["protocol"],
            "requested_seeds": [17],
            "provider": manifest["provider"],
            "task_manifest_sha256": task_digest(),
            "runtime_source_sha256": frozen["source_manifest"]["sha256"],
            "freeze_sha256": frozen["sha256"],
            "controller_selection": "Historical train-only fitted-Q and observed-return baseline; VERIFY is shared and not learned.",
            "cost_basis": manifest["provider"]["cost_basis"],
        },
        "limitations": [
            "One requested seed and six small authored test families do not establish general superiority.",
            "VERIFY is a shared fixed rule, not a learned action. Supplemental checks missed 12 failing final candidates in the primary sample.",
            "The three Boltons source-derived tasks use artificial mutations; they are not historical upstream issues or SWE-bench.",
            "Uncertain reservations remain accounted; unknown tokens remain missing. Credit fees and VPS expenses are excluded.",
            "All-action fallback totals include different terminal STOP labels; inspect nonterminal actions before comparing controller support.",
        ],
        "post_run_diagnostics": published.get("post_run_diagnostics"),
    }
    output.mkdir(parents=True, exist_ok=False)
    for name, data in (
        ("benchmark.json", benchmark),
        ("tasks.json", {"tasks": list(tasks.values())}),
    ):
        (output / name).write_text(
            json.dumps(scrub(data), indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
    (output / "trajectories.jsonl").write_text(
        "".join(
            json.dumps(scrub(r), sort_keys=True, allow_nan=False) + "\n" for r in runs
        )
    )
    receipt = {
        "source_freeze_sha256": frozen["sha256"],
        "source_manifest_sha256": hashlib.sha256(
            (study / "manifest.json").read_bytes()
        ).hexdigest(),
        "export_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "recorded_runs": len(runs),
        "tasks": len(tasks),
        "outputs": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.iterdir())
        },
    }
    (output / "export-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=ROOT / "artifacts/forgebench/v0.3-pilot1"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.input, args.output), indent=2))
