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
