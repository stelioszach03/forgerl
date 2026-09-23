import pytest
from forgerl.controller import (
    choose_action,
    encode_state,
    fit_q,
    allowed_actions,
    controller_status,
)


def state(**updates):
    value = {
        "public_passed": 0,
        "public_total": 2,
        "attempts": 0,
        "max_steps": 3,
        "cost_usd": 0.0,
        "max_cost_usd": 0.5,
        "last_action": "none",
        "improvement": 0,
    }
    return dict(value, **updates)


def transition(
    action, reward, *, source=None, next_state=None, terminal=True, split="train"
):
    return {
        "state": source or state(),
        "action": action,
        "reward": reward,
        "next_state": next_state or state(attempts=1),
        "terminal": terminal,
        "task_id": "recorded-example",
        "split": split,
    }


def test_public_stop_applies_to_every_baseline():
    for policy in ("fixed", "deliberate", "heuristic", "adaptive"):
        assert choose_action(policy, state(public_passed=2)) == "stop"
        assert choose_action(policy, state(attempts=3)) == "stop"
        assert choose_action(policy, state(cost_usd=0.5)) == "stop"
    assert choose_action("fixed", state()) == "fast"
    assert choose_action("deliberate", state()) == "deliberate"


def test_heuristic_uses_visible_feedback_and_one_replan():
    assert choose_action("heuristic", state()) == "fast"
    assert choose_action("heuristic", state(attempts=1)) == "deliberate"
    assert choose_action("heuristic", state(attempts=2)) == "replan"
    assert choose_action("heuristic", state(attempts=2, replan_count=1)) == "deliberate"
    assert "replan" not in allowed_actions(state())


def test_hidden_labels_and_task_identity_do_not_enter_features():
    original = state()
    leaked = dict(
        original,
        hidden_passed=100,
        heldout_passed=100,
        task_id="test-graph",
        solved=True,
    )
    assert encode_state(original) == encode_state(leaked)
    assert original == state()


def test_untrained_artifact_is_an_explicit_heuristic_fallback():
    artifact = fit_q([transition("stop", 1)], seed=4)
    assert artifact["trained"] is False
    assert controller_status(artifact)["label"] == "Untrained: heuristic fallback"
    assert choose_action("adaptive", state(), artifact) == "fast"


def test_q_fit_learns_observed_reward_preference():
    rows = [
        transition("fast", -0.1),
        transition("deliberate", 0.8),
        transition("stop", 0),
    ] * 4
    artifact = fit_q(rows, seed=42)
    assert artifact["trained"]
    assert artifact["diagnostics"]["transitions"] == 12
    assert choose_action("adaptive", state(), artifact) == "deliberate"
    assert artifact == fit_q(rows, seed=42)
    assert (
        choose_action("adaptive", state(attempts=1), artifact) == "deliberate"
    )  # unseen state fallback


def test_fitted_bellman_backup_propagates_delayed_rewards():
    middle = state(attempts=1, last_action="fast")
    rows = [
        transition("fast", -0.1, next_state=middle, terminal=False),
        transition("stop", 0),
        transition("deliberate", 1, source=middle),
    ] * 4
    result = fit_q(rows, gamma=0.9)
    assert result["q_values"][encode_state(state())]["fast"] == pytest.approx(0.8)
    assert choose_action("adaptive", state(), result) == "fast"


def test_negative_observed_values_do_not_select_unseen_zero_actions():
    rows = [transition("deliberate", -0.2)] * 12
    result = fit_q(rows)
    assert choose_action("adaptive", state(), result) == "deliberate"


def test_fitting_rejects_test_and_validation_labels_and_illegal_actions():
    for split in ("validation", "test", None):
        with pytest.raises(ValueError):
            fit_q([transition("fast", 1, split=split)])
    with pytest.raises(ValueError):
        fit_q([transition("replan", 1)])
    with pytest.raises(ValueError):
        fit_q([transition("fast", float("nan"))])
    with pytest.raises(ValueError):
        encode_state(state(cost_usd=float("nan")))
