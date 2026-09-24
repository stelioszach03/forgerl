"""Pilot boundary and routing checks; mock results are not experiment evidence."""

import copy
import json
from types import SimpleNamespace

import pytest

from forgerl.bench import pilot, router, sandbox
from forgerl.bench.pilot_catalog import fresh_specs, prior_development_tasks
from forgerl.bench.pilot_external import external_manifest
from forgerl.bench.provider import prompt_messages
from forgerl.bench.tasks import list_tasks, task_manifest_hash
from forgerl.bench.v03 import validate_spec


def test_fresh_family_counts_and_no_prior_holdout_reuse():
    specs = fresh_specs()
    old = {t.family for t in list_tasks()}
    assert len(specs) == 24
    assert len({s.task.family for s in specs if s.task.split == "test"}) == 6
    assert len({s.task.family for s in specs if s.task.split == "validation"}) == 2
    assert not old & {s.task.family for s in specs}
    assert len(prior_development_tasks()) == 50
    assert all(t.split == "development" for t in prior_development_tasks())
    assert (
        task_manifest_hash()
        == "ccb6b8e3996e067e24ecfb4b2f14d6ffb543380b10acb7bcfbc4f19d6b6f116b"
    )


def test_catalog_scope_supplemental_disjoint_and_multi_file_faults():
    for spec in pilot.all_specs():
        validate_spec(spec, ("validation", "test", "external"))
        sandbox.validate_files(spec.task.reference_files, spec.task.entrypoint)
        assert (
            sum(
                spec.task.files[k] != spec.task.reference_files[k]
                for k in spec.task.files
            )
            >= 2
        )
        assert len(spec.task.hidden_cases) >= 4
        prompt = json.dumps(prompt_messages(spec.task, spec.task.files, {}))
        assert all(case["name"] not in prompt for case in spec.task.hidden_cases)
        assert all(case["name"] not in prompt for case in spec.verification_cases)


def test_plan_is_unfrozen_and_fully_prespecifies_balanced_matrix():
    plan = pilot.plan()
    assert not plan["frozen"] and not plan["inference_enabled"]
    assert plan["planned_episodes"] == 162
    assert plan["study_cost_cap_usd"] == 1
    assert plan["maximum_cost_per_episode_usd"] == 1
    assert plan["rate_limit_retries"] == 2
    assert len({(r["task_id"], r["policy"]) for r in plan["study_order"]}) == 162
    assert plan == pilot.plan()
    assert sum(r["split"] == "test" for r in plan["study_order"]) == 108
    assert sum(r["split"] == "validation" for r in plan["study_order"]) == 36
    assert sum(r["split"] == "external" for r in plan["study_order"]) == 18


def test_external_source_provenance_is_exact_and_not_claimed_real_issue():
    manifest = external_manifest()
    assert manifest["license"] == "BSD-3-Clause"
    assert manifest["revision"] == "4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d"
    assert manifest["track"] == "source_derived_mutations_descriptive_only"
    for row in manifest["tasks"]:
        assert "Mahmoud Hashemi" in row["reference_files"]["clipping.py"]
        assert "THIS SOFTWARE IS PROVIDED" in row["reference_files"]["rounding.py"]


def training_rows():
    # This test's one synthetic transition uses an actual catalog TRAIN identity;
    # it never reads evaluation artifacts or provides empirical policy evidence.
    state = {
        "public_passed": 0,
        "public_total": 2,
        "attempts": 0,
        "max_steps": 6,
        "decisions": 0,
        "max_decisions": 10,
        "budget_remaining_usd": 1.0,
        "current_model": "cheap",
        "improvement": 0,
        "can_rollback": False,
        "rollbacks": 0,
        "retries": 0,
    }
    next_state = {**state, "public_passed": 2, "attempts": 1, "decisions": 1}
    task = next(t for t in list_tasks() if t.split == "train")
    return [
        {
            "task_id": task.id,
            "split": "train",
            "state": state,
            "next_state": next_state,
            "action": "retry",
            "reward": 0.99,
            "cost_usd": 0.002,
            "terminal": True,
        }
    ]


def test_supervised_fit_observed_return_only_and_explicit_unsupported_fallback():
    rows = training_rows() * 12
    fitted = pilot.fit_supervised(rows)
    key = router.encode_state(rows[0]["state"])
    assert fitted["values"][key]["retry"] == pytest.approx(0.99)
    assert set(fitted["values"][key]) == {"retry"}
    assert fitted["verify_support"] == 0 and fitted["counterfactual_labels"] is False
    assert (
        pilot.choose_supervised(rows[0]["state"], fitted)["source"]
        == "learned_supervised_cost"
    )
    unseen = {**rows[0]["state"], "attempts": 3}
    assert pilot.choose_supervised(unseen, fitted)["source"] == "heuristic_fallback"
    assert fitted == pilot.fit_supervised(rows)


def test_supervised_rejects_evaluation_and_incomplete_episode():
    row = training_rows()[0]
    with pytest.raises(ValueError, match="training"):
        pilot.fit_supervised([{**row, "split": "test"}])
    with pytest.raises(ValueError, match="Unterminated"):
        pilot.fit_supervised([{**row, "terminal": False}])


class Provider:
    async def generate(self, task, files, feedback, action, **kwargs):
        return SimpleNamespace(
            files=task.reference_files,
            model="mock",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            cost_usd=0.001,
            elapsed_s=0.001,
            request_id="mock",
            finish_reason="stop",
            prompt_messages=[],
            response_text="mock",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", pilot.POLICIES)
async def test_all_six_policies_use_same_real_action_masks_and_shared_verification(
    policy,
):
    spec = fresh_specs()[0]
    calls = []

    def evaluator(task, files, hidden=False):
        calls.append((hidden, task.public_cases == spec.verification_cases))
        cases = task.hidden_cases if hidden else task.public_cases
        good = files == task.reference_files
        return {
            "passed": len(cases) if good else 0,
            "total": len(cases),
            "cases": [],
            "elapsed_s": 0.001,
            "execution_error": None,
        }

    episode = pilot.PilotEpisode(spec, Provider(), policy, evaluator=evaluator)
    result = await pilot.run_episode(episode, selector=episode.select)
    assert result["solved"] and result["version"] == pilot.VERSION
    assert result["verification_calls"] == 1
    assert result["evidence_scope"] == "prospective_pilot_not_full_v03"
    assert result["attempts"] == 1 and result["decisions"] == 3
    assert calls == [(False, False), (False, False), (False, True), (True, False)]
    decision = [e["data"] for e in result["events"] if e["kind"] == "decision"]
    assert decision[1]["action"] == "verify"
    assert decision[1]["selection_source"] == "shared_verify_on_visible_green"


def test_freeze_rejects_bad_receipt_and_mutated_configuration(monkeypatch):
    with pytest.raises(ValueError, match="fixture"):
        pilot.freeze_document(
            {}, commit="a" * 40, fixture_receipt={}, provider_snapshot={}
        )
    controllers = {"sha256": pilot.digest({})}
    image = "sha256:" + "b" * 64
    monkeypatch.setenv("FORGEBENCH_EVALUATED_IMAGE", image)
    receipt = {
        "status": "passed",
        "task_manifest_sha256": pilot.task_digest(),
        "backend": "rootless-docker-existing-isolated-executor",
        "candidate_host_execution": False,
        "sandbox_image": image,
        "tasks": 27,
        "checks": [
            {
                "task_id": s.task.id,
                "passed": True,
                "checks": {
                    key: {
                        "passed": 0 if key == "starter_visible" else 2,
                        "total": 2,
                        "execution_error": None,
                    }
                    for key in (
                        "starter_visible",
                        "reference_visible",
                        "reference_hidden",
                        "reference_supplemental",
                    )
                },
            }
            for s in pilot.all_specs()
        ],
    }
    snapshot = {
        "endpoint_records": [
            {
                "selected_endpoint": {
                    "model_id": model,
                    "tag": "coreweave/fp4",
                    "quantization": "fp4",
                    "status": 0,
                    "supported_parameters": ["seed", "temperature", "max_tokens"],
                }
            }
            for model in ("openai/gpt-oss-20b", "openai/gpt-oss-120b")
        ]
    }
    monkeypatch.setattr(pilot, "verify_source_commit", lambda commit: None)
    frozen = pilot.freeze_document(
        controllers,
        commit="a" * 40,
        fixture_receipt=receipt,
        provider_snapshot=snapshot,
    )
    pilot.verify_freeze(frozen)
    changed = copy.deepcopy(frozen)
    changed["configuration"]["study_cost_cap_usd"] = 2
    with pytest.raises(ValueError, match="hash"):
        pilot.verify_freeze(changed)
