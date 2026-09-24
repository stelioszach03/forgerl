#!/usr/bin/env python3
"""Descriptive frozen-pilot analysis, never combined with published v0.2."""

from __future__ import annotations
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forgerl.bench.pilot import POLICIES, PROTOCOL, VERSION
from forgerl.bench.study import digest


def read_runs(directory):
    frozen = json.loads((directory / "freeze.json").read_text())
    manifest = json.loads((directory / "manifest.json").read_text())
    claimed = dict(frozen)
    sha = claimed.pop("sha256")
    if digest(claimed) != sha or manifest["freeze_sha256"] != sha:
        raise ValueError("Freeze provenance mismatch")
    plan = frozen["configuration"]
    if plan["version"] != VERSION or plan["protocol"] != PROTOCOL:
        raise ValueError("Wrong protocol")
    expected = {(r["task_id"], r["policy"], r["seed"]): r for r in plan["study_order"]}
    runs = []
    seen = set()
    for path in sorted((directory / "runs").glob("*.json")):
        run = json.loads(path.read_text())
        key = (run["task_id"], run["policy"], run["seed"])
        if (
            key not in expected
            or key in seen
            or run["version"] != VERSION
            or run["protocol"] != PROTOCOL
            or run["controllers_sha256"] != plan["controllers_sha256"]
            or run["family"] != expected[key]["family"]
            or run["split"] != expected[key]["split"]
        ):
            raise ValueError("Unexpected, duplicate or mixed pilot run")
        seen.add(key)
        runs.append(run)
    if len(runs) != manifest["completed"]:
        raise ValueError("Manifest/run count mismatch")
    missing = [row for key, row in expected.items() if key not in seen]
    if manifest.get("missing") != missing or manifest.get("planned") != len(expected):
        raise ValueError("Manifest missing-matrix entries do not reconcile")
    if manifest.get("status") != ("incomplete" if missing else "complete"):
        raise ValueError("Manifest coverage status does not reconcile")
    return frozen, manifest, runs, expected


def metrics(run):
    supplemental = [
        e["data"]
        for e in run["events"]
        if e["kind"] == "tests"
        and e.get("data", {}).get("visibility") == "public_supplemental"
    ]
    caught = sum(e["passed"] < e["total"] for e in supplemental)
    success = bool(run["status"] == "completed" and run["solved"])
    decisions = [e["data"] for e in run["events"] if e["kind"] == "decision"]
    # Post-run diagnostic only: STOP provenance is not logged symmetrically by
    # the two frozen selectors. Keep the original counts intact below.
    selections = [d for d in decisions if d["action"] not in ("stop", "verify")]
    learned_sources = ("learned_q", "learned_supervised_cost")
    selection_learned = sum(d["selection_source"] in learned_sources for d in selections)
    selection_fallback = sum(d["selection_source"] == "heuristic_fallback" for d in selections)
    selection_provider_retry = sum(d["selection_source"] == "provider_retry" for d in selections)
    measured_cost = sum(
        e["data"].get("cost_usd", 0.0)
        for e in run["events"]
        if e["kind"] in ("inference", "error")
        and type(e.get("data", {}).get("provider_reported_cost_usd")) in (int, float)
    )
    return {
        "run_id": run["id"],
        "task_id": run["task_id"],
        "family": run["family"],
        "split": run["split"],
        "policy": run["policy"],
        "seed": run["seed"],
        "status": run["status"],
        "success": int(success),
        "hidden_passed": run.get("heldout_passed"),
        "hidden_total": run.get("heldout_total"),
        "accounted_cost_usd": run["cost_usd"],
        "measured_inference_cost_usd": measured_cost,
        "unconfirmed_reserve_usd": max(0.0, run["cost_usd"] - measured_cost),
        "tokens": run.get("tokens"),
        "latency_s": run["elapsed_s"],
        "tool_calls": run["tool_calls"],
        "attempts": run["attempts"],
        "decisions": run["decisions"],
        "provider_retries": run["provider_retries"],
        "escalations": run["escalations"],
        "regressions": run["regressions_introduced"],
        "unnecessary_edits_proxy": run["unnecessary_edits"],
        "verification_calls": run["verification_calls"],
        "verification_elapsed_s": run["verification_elapsed_s"],
        "caught_supplemental_failures": caught,
        "success_after_supplemental_failure": bool(success and caught),
        "supplemental_grader_disagreement": run["verification_grader_disagreement"],
        "supplemental_grader_disagreement_direction": run[
            "verification_grader_disagreement_direction"
        ],
        "learned_decisions": sum(
            d["selection_source"] in ("learned_q", "learned_supervised_cost")
            for d in decisions
        ),
        "fallback_decisions": sum(
            d["selection_source"] == "heuristic_fallback" for d in decisions
        ),
        "stop_decisions": sum(d["action"] == "stop" for d in decisions),
        "stop_fallback_decisions": sum(
            d["action"] == "stop" and d["selection_source"] == "heuristic_fallback"
            for d in decisions
        ),
        "stop_constraint_decisions": sum(
            d["action"] == "stop" and d["selection_source"] == "constraint"
            for d in decisions
        ),
        "verify_decisions": sum(d["action"] == "verify" for d in decisions),
        "non_stop_non_verify_decisions": len(selections),
        "non_stop_non_verify_learned_decisions": selection_learned,
        "non_stop_non_verify_fallback_decisions": selection_fallback,
        "non_stop_non_verify_provider_retry_decisions": selection_provider_retry,
        "non_stop_non_verify_other_decisions": len(selections)
        - selection_learned - selection_fallback - selection_provider_retry,
    }


def analyze(directory):
    frozen, manifest, runs, expected = read_runs(directory)
    rows = [metrics(r) for r in runs]
    summary = []
    families = []
    for split in ("test", "validation", "external"):
        for policy in POLICIES:
            selected = [
                r for r in rows if r["split"] == split and r["policy"] == policy
            ]
            planned = [
                r
                for r in expected.values()
                if r["split"] == split and r["policy"] == policy
            ]
            by_family = defaultdict(list)
            for row in selected:
                by_family[row["family"]].append(row)
            family_rows = []
            for family, group in sorted(by_family.items()):
                item = {
                    "split": split,
                    "policy": policy,
                    "family": family,
                    "attempted": len(group),
                    "planned": sum(r["family"] == family for r in planned),
                    "success_rate": sum(r["success"] for r in group) / len(group),
                    "mean_accounted_cost_usd": sum(
                        r["accounted_cost_usd"] for r in group
                    )
                    / len(group),
                }
                family_rows.append(item)
                families.append(item)
            graded = [r for r in selected if r["hidden_passed"] is not None]

            def mean(key):
                values = [r[key] for r in selected if r[key] is not None]
                return sum(values) / len(values) if values else None

            summary.append(
                {
                    "split": split,
                    "policy": policy,
                    "attempted": len(selected),
                    "planned": len(planned),
                    "complete_coverage": len(selected) == len(planned),
                    "families_observed": len(family_rows),
                    "family_weighted_success": sum(
                        r["success_rate"] for r in family_rows
                    )
                    / len(family_rows)
                    if family_rows
                    else None,
                    "family_weighted_cost_usd": sum(
                        r["mean_accounted_cost_usd"] for r in family_rows
                    )
                    / len(family_rows)
                    if family_rows
                    else None,
                    "graded_episodes": len(graded),
                    "graded_only_success_rate": sum(r["success"] for r in graded)
                    / len(graded)
                    if graded
                    else None,
                    "hidden_pass_fraction": sum(r["hidden_passed"] for r in graded)
                    / sum(r["hidden_total"] for r in graded)
                    if graded
                    else None,
                    "mean_tokens": mean("tokens"),
                    "token_measured_episodes": sum(
                        r["tokens"] is not None for r in selected
                    ),
                    "mean_latency_s": mean("latency_s"),
                    "mean_tool_calls": mean("tool_calls"),
                    "mean_attempts": mean("attempts"),
                    "mean_regressions": mean("regressions"),
                    "mean_unnecessary_edits_proxy": mean("unnecessary_edits_proxy"),
                    "verification_calls": sum(
                        r["verification_calls"] for r in selected
                    ),
                    "verification_elapsed_s": sum(
                        r["verification_elapsed_s"] for r in selected
                    ),
                    "caught_supplemental_failures": sum(
                        r["caught_supplemental_failures"] for r in selected
                    ),
                    "success_after_supplemental_failure": sum(
                        r["success_after_supplemental_failure"] for r in selected
                    ),
                    "supplemental_grader_disagreements": sum(
                        r["supplemental_grader_disagreement"] is True for r in selected
                    ),
                    "supplemental_grader_measured": sum(
                        r["supplemental_grader_disagreement"] is not None
                        for r in selected
                    ),
                    "supplemental_false_rejections": sum(
                        r["supplemental_grader_disagreement_direction"]
                        == "false_rejection"
                        for r in selected
                    ),
                    "supplemental_missed_failures": sum(
                        r["supplemental_grader_disagreement_direction"]
                        == "missed_failure"
                        for r in selected
                    ),
                    "learned_decisions": sum(r["learned_decisions"] for r in selected),
                    "fallback_decisions": sum(
                        r["fallback_decisions"] for r in selected
                    ),
                    **{
                        key: sum(r[key] for r in selected)
                        for key in (
                            "stop_decisions", "stop_fallback_decisions",
                            "stop_constraint_decisions", "verify_decisions",
                            "non_stop_non_verify_decisions",
                            "non_stop_non_verify_learned_decisions",
                            "non_stop_non_verify_fallback_decisions",
                            "non_stop_non_verify_provider_retry_decisions",
                            "non_stop_non_verify_other_decisions",
                        )
                    },
                    "non_stop_non_verify_learned_fraction": (
                        sum(r["non_stop_non_verify_learned_decisions"] for r in selected)
                        / sum(r["non_stop_non_verify_decisions"] for r in selected)
                        if sum(r["non_stop_non_verify_decisions"] for r in selected)
                        else None
                    ),
                    "unconfirmed_reserve_usd": sum(
                        r["unconfirmed_reserve_usd"] for r in selected
                    ),
                }
            )
    pairs = []
    for learned in ("adaptive", "supervised_cost"):
        for baseline in POLICIES:
            if baseline == learned:
                continue
            for family in sorted(
                {r["family"] for r in families if r["split"] == "test"}
            ):
                left = next(
                    (
                        r
                        for r in families
                        if r["split"] == "test"
                        and r["family"] == family
                        and r["policy"] == learned
                    ),
                    None,
                )
                right = next(
                    (
                        r
                        for r in families
                        if r["split"] == "test"
                        and r["family"] == family
                        and r["policy"] == baseline
                    ),
                    None,
                )
                if (
                    left
                    and right
                    and left["attempted"] == left["planned"]
                    and right["attempted"] == right["planned"]
                ):
                    pairs.append(
                        {
                            "family": family,
                            "learned": learned,
                            "baseline": baseline,
                            "success_rate_difference": left["success_rate"]
                            - right["success_rate"],
                            "mean_cost_difference_usd": left["mean_accounted_cost_usd"]
                            - right["mean_accounted_cost_usd"],
                        }
                    )
    report = {
        "version": VERSION,
        "protocol": PROTOCOL,
        "freeze_sha256": frozen["sha256"],
        "status": manifest["status"],
        "completed": len(rows),
        "planned": len(expected),
        "missing": manifest["missing"],
        "primary_track": "test (six new authored families)",
        "summary": summary,
        "family_metrics": families,
        "paired_family_differences": pairs,
        "confidence_intervals": None,
        "significance_claim": False,
        "post_run_diagnostics": {
            "selection_coverage": {
                "added_after_execution": True,
                "original_learned_and_fallback_counts_preserved": True,
                "primary_scores_unchanged": True,
                "definition": "Count recorded decision actions excluding stop and verify. Separately retain learned, heuristic_fallback, provider_retry and other source counts. The fraction denominator includes provider-retry actions; it is not a claim that retries are learned selector opportunities.",
                "reason": "Frozen fitted-Q logs forced STOP as constraint, while the supervised selector can log the same terminal action as heuristic_fallback. Raw all-action fallback counts alone are not comparable measures of unsupported model-selection states.",
                "stop_handling": "All STOP counts are reported separately with constraint and heuristic_fallback source counts; no event is relabeled or removed.",
            }
        },
        "interpretation": "Single-seed descriptive pilot. Family-weighted means use observed families; incomplete coverage prevents a full-matrix claim. All infrastructure failures retained, graded-only conditional sensitivity separate. External source-derived track never pooled.",
        "source_manifest_sha256": frozen["source_manifest"]["sha256"],
        "analysis_source_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
    }
    return report, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report, rows = analyze(args.study)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "analysis.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    if rows:
        with (args.output / "results.csv").open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    lines = [
        "# ForgeBench v0.3 prospective transfer pilot results",
        "",
        f"Coverage: **{len(rows)} / {report['planned']}** prespecified episodes. Study status: **{report['status']}**.",
        "",
        "Descriptive one-seed pilot. No broad superiority, statistical significance or learned-verification claim.",
        "",
    ]
    for split in ("test", "validation", "external"):
        lines.extend(
            [
                f"## {split}",
                "",
                "| Policy | Attempted/planned | Family-weighted success | Accounted cost/task | Graded episodes |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for r in report["summary"]:
            if r["split"] != split:
                continue
            success = (
                f"{r['family_weighted_success']:.1%}"
                if r["family_weighted_success"] is not None
                else "unmeasured"
            )
            cost = (
                f"${r['family_weighted_cost_usd']:.6f}"
                if r["family_weighted_cost_usd"] is not None
                else "unmeasured"
            )
            lines.append(
                f"| {r['policy']} | {r['attempted']}/{r['planned']} | {success} | {cost} | {r['graded_episodes']} |"
            )
        lines.append("")
    lines.extend(
        [
            report["interpretation"],
            "",
            "Full per-run metrics, reserved-cost accounting, verification outcomes and learned/fallback counts are in results.csv and analysis.json.",
            "The original all-action learned/fallback counts are preserved. A separately labeled post-run diagnostic excludes STOP/VERIFY, reports STOP source counts and separates provider-retry actions; it does not change primary scores or the frozen protocol.",
            "",
            f"Frozen source digest: `{report['source_manifest_sha256']}`.",
            f"Frozen protocol digest: `{report['freeze_sha256']}`.",
            "",
        ]
    )
    (args.output / "results.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "status": report["status"],
                "completed": len(rows),
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
