"""Mock report fixtures, kept outside real evidence directories."""

import importlib.util
import json
from pathlib import Path

import pytest

from forgerl.bench import pilot

spec = importlib.util.spec_from_file_location(
    "pilot_analysis",
    Path(__file__).resolve().parents[1] / "scripts/analyze_pilot_forgebench.py",
)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def result(row, *, success):
    return {
        **row,
        "id": row["task_id"] + row["policy"],
        "version": pilot.VERSION,
        "protocol": pilot.PROTOCOL,
        "controllers_sha256": None,
        "status": "completed" if success else "failed",
        "solved": success,
        "heldout_passed": 2 if success else None,
        "heldout_total": 2,
        "cost_usd": 0.04,
        "tokens": 100 if success else None,
        "elapsed_s": 1,
        "tool_calls": 3,
        "attempts": 1,
        "decisions": 3,
        "provider_retries": 0,
        "escalations": 0,
        "regressions_introduced": 0,
        "unnecessary_edits": 0,
        "verification_calls": 1,
        "verification_elapsed_s": 0.1,
        "verification_grader_disagreement": False if success else None,
        "verification_grader_disagreement_direction": None,
        "events": [
            {
                "kind": "inference",
                "data": {"cost_usd": 0.01, "provider_reported_cost_usd": 0.01},
            },
            {
                "kind": "error",
                "data": {"cost_usd": 0.02, "provider_reported_cost_usd": 0.02},
            },
            {
                "kind": "error",
                "data": {"cost_usd": 0.01, "provider_reported_cost_usd": None},
            },
        ],
    }


def study(tmp_path):
    config = pilot.plan()
    frozen = {"configuration": config, "source_manifest": {"sha256": "fixture-source"}}
    frozen["sha256"] = pilot.digest(frozen)
    test = next(
        r
        for r in config["study_order"]
        if r["split"] == "test" and r["policy"] == "cheap_only"
    )
    external = next(
        r
        for r in config["study_order"]
        if r["split"] == "external" and r["policy"] == "cheap_only"
    )
    rows = [result(test, success=False), result(external, success=True)]
    observed = {(r["task_id"], r["policy"]) for r in rows}
    manifest = {
        "freeze_sha256": frozen["sha256"],
        "status": "incomplete",
        "completed": 2,
        "planned": 162,
        "missing": [
            r
            for r in config["study_order"]
            if (r["task_id"], r["policy"]) not in observed
        ],
    }
    (tmp_path / "runs").mkdir()
    (tmp_path / "freeze.json").write_text(json.dumps(frozen))
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    for index, row in enumerate(rows):
        (tmp_path / "runs" / f"{index}.json").write_text(json.dumps(row))
    return manifest


def test_primary_infrastructure_denominator_is_retained_and_external_never_pooled(
    tmp_path,
):
    study(tmp_path)
    report, rows = analysis.analyze(tmp_path)
    primary = next(
        r
        for r in report["summary"]
        if r["split"] == "test" and r["policy"] == "cheap_only"
    )
    external = next(
        r
        for r in report["summary"]
        if r["split"] == "external" and r["policy"] == "cheap_only"
    )
    assert primary["attempted"] == 1 and primary["planned"] == 18
    assert primary["family_weighted_success"] == 0
    assert primary["graded_only_success_rate"] is None
    assert primary["supplemental_grader_measured"] == 0
    assert primary["supplemental_grader_disagreements"] == 0
    assert external["family_weighted_success"] == 1
    assert external["supplemental_grader_measured"] == 1
    assert all(row["unconfirmed_reserve_usd"] == pytest.approx(0.01) for row in rows)
    assert report["confidence_intervals"] is None
    assert not primary["complete_coverage"]


def test_missing_matrix_must_reconcile_exactly(tmp_path):
    manifest = study(tmp_path)
    manifest["missing"].pop()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="missing-matrix"):
        analysis.read_runs(tmp_path)


def test_metric_disagreement_direction_and_measurement_are_preserved():
    row = result(
        next(r for r in pilot.plan()["study_order"] if r["split"] == "test"),
        success=True,
    )
    row["verification_grader_disagreement"] = True
    row["verification_grader_disagreement_direction"] = "false_rejection"
    metrics = analysis.metrics(row)
    assert metrics["supplemental_grader_disagreement"] is True
    assert metrics["supplemental_grader_disagreement_direction"] == "false_rejection"


def test_post_run_coverage_keeps_original_stop_labels_and_compares_nonterminal_actions():
    row = result(
        next(r for r in pilot.plan()["study_order"] if r["split"] == "test"),
        success=True,
    )

    def decisions(learned_source, stop_source):
        return [
            {"kind": "decision", "data": {"action": "escalate", "selection_source": learned_source}},
            {"kind": "decision", "data": {"action": "verify", "selection_source": "shared_verify_on_visible_green"}},
            {"kind": "decision", "data": {"action": "stop", "selection_source": stop_source}},
        ]

    original_events = list(row["events"])
    q = analysis.metrics({**row, "events": original_events + decisions("learned_q", "constraint")})
    supervised = analysis.metrics({**row, "events": original_events + decisions("learned_supervised_cost", "heuristic_fallback")})
    assert q["learned_decisions"] == supervised["learned_decisions"] == 1
    assert q["fallback_decisions"] == 0
    assert supervised["fallback_decisions"] == 1
    assert q["stop_constraint_decisions"] == supervised["stop_fallback_decisions"] == 1
    for metric in (q, supervised):
        assert metric["non_stop_non_verify_decisions"] == 1
        assert metric["non_stop_non_verify_learned_decisions"] == 1
        assert metric["non_stop_non_verify_fallback_decisions"] == 0
        assert metric["verify_decisions"] == metric["stop_decisions"] == 1
    assert row["events"] == original_events


def test_provider_retry_and_actual_repair_fallback_are_separate_diagnostic_sources():
    row = result(
        next(r for r in pilot.plan()["study_order"] if r["split"] == "test"),
        success=False,
    )
    row["events"].extend([
        {"kind": "decision", "data": {"action": "repair", "selection_source": "provider_retry"}},
        {"kind": "decision", "data": {"action": "repair", "selection_source": "heuristic_fallback"}},
        {"kind": "decision", "data": {"action": "retry", "selection_source": "baseline"}},
    ])
    metric = analysis.metrics(row)
    assert metric["non_stop_non_verify_decisions"] == 3
    assert metric["non_stop_non_verify_learned_decisions"] == 0
    assert metric["non_stop_non_verify_provider_retry_decisions"] == 1
    assert metric["non_stop_non_verify_fallback_decisions"] == 1
    assert metric["non_stop_non_verify_other_decisions"] == 1
    assert metric["fallback_decisions"] == 1


def test_coverage_diagnostic_is_labeled_post_run_without_changing_primary_scores(tmp_path):
    study(tmp_path)
    report, _ = analysis.analyze(tmp_path)
    diagnostic = report["post_run_diagnostics"]["selection_coverage"]
    assert diagnostic["added_after_execution"]
    assert diagnostic["original_learned_and_fallback_counts_preserved"]
    assert diagnostic["primary_scores_unchanged"]
    for summary in report["summary"]:
        assert summary["non_stop_non_verify_decisions"] == 0
        assert summary["non_stop_non_verify_learned_fraction"] is None
