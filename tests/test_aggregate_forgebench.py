import importlib.util
import json
from pathlib import Path
import pytest
from forgerl.bench.study import digest
from forgerl.bench.router import POLICIES
from forgerl.bench.tasks import list_tasks


def script(name):
    spec = importlib.util.spec_from_file_location(name, Path("scripts")/(name+".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


aggregate = script("aggregate_forgebench")
reporting = script("report_forgebench")


def make_study(directory, seed=17, provider="fixture"):
    directory.mkdir()
    (directory/"runs").mkdir()
    tasks = list_tasks()
    train = next(t for t in tasks if t.split == "train")
    val = next(t for t in tasks if t.split == "validation")
    test = next(t for t in tasks if t.split == "test")
    configuration = {"version": "0.2", "protocol": "forgebench-v0.2-prespecified", "seed": seed, "policies": list(POLICIES), "training_ids": [train.id], "evaluation_ids": [val.id, test.id], "language_model_weights_updated": False, "task_count": len(tasks), "planned_training_episodes": 2, "maximum_model_calls": 6}
    manifest = {"configuration": configuration, "configuration_sha256": digest(configuration), "task_manifest_sha256": "fixture-hash", "provider": {"provider": provider, "models": [{"id": "measured"}, {"id": "not_called"}], "cost_basis": "Mock evidence only"}, "status": "complete", "training_completed": 0, "source_manifest": {"files": {"forgerl/bench/engine.py": "a"*64}, "sha256": digest({"forgerl/bench/engine.py": "a"*64}), "sandbox_image": "sha256:"+"b"*64}}
    (directory/"manifest.json").write_text(json.dumps(manifest))
    index, runs = [], []
    for task in (val, test):
        for policy in POLICIES:
            ident = f"{seed:08x}{len(index):024x}"
            run = {"id": ident, "version": "0.2", "task_id": task.id, "task_title": task.title, "family": task.family, "split": task.split, "category": task.category, "seed": seed, "policy": policy, "status": "completed", "solved": policy != "cheap_only", "public_passed": 2, "public_total": 2, "heldout_passed": 1 if policy != "cheap_only" else 0, "heldout_total": 1, "cost_usd": .001, "tokens": 100, "elapsed_s": 2, "tool_calls": 3, "steps": 1, "attempts": 1, "regressions_introduced": 0, "unnecessary_edits": 0, "escalations": 0, "learned_decisions": 0, "fallback_decisions": 1 if policy == "adaptive" else 0, "success_after_repair": False, "failure_labels": ["verification:visible_pass_hidden_fail"] if policy == "cheap_only" else [], "initial_files": {"service.py": "def run(): return 0\n"}, "final_files": {"service.py": "def run(): return 1\n"}, "diff": "fixture patch", "events": [{"kind": "decision", "data": {"action": "retry"}}], "model_ids": ["measured"]}
            (directory/"runs"/(ident+".json")).write_text(json.dumps(run))
            index.append({"run_id": ident, "phase": "evaluation", "task_id": task.id, "policy": policy, "status": "completed"})
            runs.append(run)
    (directory/"raw-runs.jsonl").write_text("".join(json.dumps(r)+"\n" for r in index))
    return runs


def test_missing_seeds_preserve_planned_coverage_and_actual_models(tmp_path):
    make_study(tmp_path/"seed17")
    report, full, bootstrap = aggregate.aggregate_studies({17: tmp_path/"seed17"})
    assert report["status"] == "partial"
    assert report["coverage"]["planned"] == 30 and report["coverage"]["completed"] == 10
    assert len(report["coverage"]["missing"]) == 20
    assert report["models"] == [{"id": "measured"}]
    assert all(r["family_bootstrap_95"] is None and r["status"] == "insufficient_clusters" for r in bootstrap["comparisons"])
    assert len(full) == 10
    output = tmp_path/"published"
    aggregate.write_exports(output, report, full, bootstrap)
    assert (output/"results.csv").read_text().count("cheap_only") == 2
    assert len((output/"trajectories.jsonl").read_text().splitlines()) == 10
    assert (output/"failure_analysis.csv").read_text().count("visible_pass_hidden_fail") == 2


def test_three_seeds_keep_seed_repeats_out_of_independent_family_count(tmp_path):
    mapping = {}
    for seed in (17, 29, 43):
        mapping[seed] = tmp_path/f"seed{seed}"
        make_study(mapping[seed], seed)
    report, full, bootstrap = aggregate.aggregate_studies(mapping)
    assert report["status"] == "complete"
    assert all(r["n"] == 3 and r["planned"] == 3 for r in report["summary"])
    assert report["coverage"]["test_unique_tasks"] == 1
    assert all(r["paired_episodes"] == 3 and r["paired_tasks"] == 1 and r["paired_families"] == 1 for r in bootstrap["comparisons"])
    assert len(full) == 30


def test_incompatible_provider_or_configuration_fails_closed(tmp_path):
    make_study(tmp_path/"first")
    make_study(tmp_path/"second", 29, "other-provider")
    with pytest.raises(ValueError, match="Incompatible"):
        aggregate.aggregate_studies({17: tmp_path/"first", 29: tmp_path/"second"})
    manifest_path = tmp_path/"first/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["configuration"]["maximum_model_calls"] = 5
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="hash mismatch"):
        aggregate.aggregate_studies({17: tmp_path/"first"})


def test_duplicate_or_altered_run_identity_cannot_be_cherry_picked(tmp_path):
    make_study(tmp_path/"seed17")
    index = tmp_path/"seed17/raw-runs.jsonl"
    rows = index.read_text().splitlines()
    index.write_text("\n".join(rows+[rows[0]])+"\n")
    with pytest.raises(ValueError, match="Duplicate"):
        aggregate.aggregate_studies({17: tmp_path/"seed17"})


def test_report_is_coverage_grounded_and_does_not_claim_unrun_ablations(tmp_path):
    make_study(tmp_path/"seed17")
    report, _, _ = aggregate.aggregate_studies({17: tmp_path/"seed17"})
    sections = reporting.report_sections(report)
    text = "\n".join(paragraph for heading, paragraph in sections)
    assert "10/30 planned evaluation episodes" in text
    assert "have not been run and are not claimed" in text
    assert "not a SWE-bench result" in text
    assert "not_called" not in text
    assert "no family-bootstrap interval" in text


@pytest.mark.skipif(importlib.util.find_spec("matplotlib") is None, reason="optional report plotting dependencies")
def test_standard_figures_render_from_actual_record_counts(tmp_path):
    make_study(tmp_path/"seed17")
    report, full, _ = aggregate.aggregate_studies({17: tmp_path/"seed17"})
    captions = reporting.create_figures(report, full, tmp_path/"figures")
    assert len(captions) == 4
    for name in captions:
        assert (tmp_path/"figures"/(name+".svg")).stat().st_size > 1000
        assert (tmp_path/"figures"/(name+".png")).stat().st_size > 1000


def test_source_manifest_and_sandbox_identity_are_required(tmp_path):
    make_study(tmp_path/"seed17")
    path = tmp_path/"seed17/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["source_manifest"]["files"]["forgerl/bench/engine.py"] = "c"*64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="source manifest"):
        aggregate.aggregate_studies({17: tmp_path/"seed17"})
    manifest["source_manifest"]["sha256"] = digest(manifest["source_manifest"]["files"])
    manifest["source_manifest"]["sandbox_image"] = "latest"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="immutable"):
        aggregate.aggregate_studies({17: tmp_path/"seed17"})
