import json

import pytest

from forgerl.bench.study import digest, plan
from forgerl.bench.tasks import list_tasks, task_manifest_hash
from forgerl.bench.support_audit import audit_rows, audit_studies


def row():
    state = dict(
        public_passed=0,
        public_total=2,
        attempts=0,
        max_steps=6,
        decisions=0,
        max_decisions=10,
        budget_remaining_usd=1,
        current_model="cheap",
        improvement=0,
        can_rollback=False,
        rollbacks=0,
        retries=0,
    )
    return {
        "task_id": list_tasks()[0].id,
        "split": "train",
        "state": state,
        "next_state": dict(state),
        "action": "retry",
        "terminal": True,
        "reward": 0.9,
        "cost_usd": 0.02,
    }


def test_missing_propensity_is_reported_without_inventing_counterfactuals():
    report = audit_rows([row()])
    assert report["missing_propensities"] == 1
    assert not report["propensity_prerequisite_satisfied"]
    assert report["causal_or_off_policy_estimate"] is None
    assert report["models_fitted"] == report["evaluation_rows_used"] == 0
    assert report["states"][0]["observed_action_counts"] == {"retry": 1}
    assert "escalate" in report["states"][0]["unobserved_legal_actions"]
    with pytest.raises(ValueError, match="Missing logged"):
        audit_rows([row()], require_propensity=True)


@pytest.mark.parametrize("split", ["validation", "test"])
def test_rejects_evaluation_rows_even_if_training_task_id_is_claimed(split):
    value = row()
    value["split"] = split
    with pytest.raises(ValueError, match="training tasks"):
        audit_rows([value])


def test_rejects_test_task_mislabeled_as_train():
    value = row()
    value["task_id"] = next(t.id for t in list_tasks() if t.split == "test")
    with pytest.raises(ValueError, match="training tasks"):
        audit_rows([value])


def test_rejects_extra_hidden_state_feature():
    value = row()
    value["state"]["hidden_passed"] = 1
    with pytest.raises(ValueError, match="observable"):
        audit_rows([value])


@pytest.mark.parametrize("probability", [0, -0.1, 1.1, float("nan"), True])
def test_rejects_invalid_propensity(probability):
    value = row()
    value["behavior_action_probability"] = probability
    with pytest.raises(ValueError, match="probability"):
        audit_rows([value])


def test_complete_propensity_is_only_a_prerequisite_not_a_causal_result():
    value = row()
    value["behavior_action_probability"] = 0.5
    report = audit_rows([value], require_propensity=True)
    assert report["propensity_prerequisite_satisfied"]
    assert report["causal_or_off_policy_estimate"] is None


def test_source_hashes_and_reconciliation(tmp_path):
    configuration = plan(list_tasks(), seed=17)
    manifest = {
        "configuration": configuration,
        "configuration_sha256": digest(configuration),
        "task_manifest_sha256": task_manifest_hash(),
        "training_transitions": 1,
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "transitions.jsonl").write_text(json.dumps(row()) + "\n")
    result = audit_studies([(17, tmp_path)])
    assert len(result["inputs"][0]["transitions_sha256"]) == 64
    assert result["inputs"][0]["evaluation_artifacts_read"] is False
    with pytest.raises(ValueError, match="Duplicate"):
        audit_studies([(17, tmp_path), (17, tmp_path)])
    manifest["training_transitions"] = 2
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="reconcile"):
        audit_studies([(17, tmp_path)])
