"""Development-only verification contract; mocked checks are not benchmark evidence."""

import copy
import json
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from forgerl.bench.engine import RepoEpisode
from forgerl.bench.tasks import task_manifest_hash
from forgerl.bench import sandbox
from forgerl.sandbox import SandboxUnavailable
from forgerl.bench.v03 import (
    VerificationEpisode,
    development_tasks,
    draft_plan,
    run_verification_episode,
)

V02_HASH = "ccb6b8e3996e067e24ecfb4b2f14d6ffb543380b10acb7bcfbc4f19d6b6f116b"


class Provider:
    def __init__(self, candidates):
        self.candidates, self.calls = iter(candidates), []

    async def generate(self, task, files, feedback, action, **kwargs):
        self.calls.append(copy.deepcopy(feedback))
        candidate = next(self.candidates)
        return SimpleNamespace(
            files=candidate,
            model="mock",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            cost_usd=0.001,
            elapsed_s=0.01,
            request_id="mock",
            finish_reason="stop",
            prompt_messages=[],
            response_text="mock",
        )


def fixture():
    spec = development_tasks()[0]
    task = spec.task
    partial = dict(task.reference_files)
    partial["conversion.py"] = partial["conversion.py"].replace(
        "value - 32", "abs(value) - 32"
    )
    calls = []

    def evaluate(supplied, files, hidden=False):
        calls.append((hidden, tuple(c["name"] for c in supplied.public_cases)))
        cases = supplied.hidden_cases if hidden else supplied.public_cases
        verification = supplied.public_cases == spec.verification_cases
        passed = files == task.reference_files or (
            files == partial and not verification and not hidden
        )
        return {
            "passed": len(cases) if passed else 0,
            "total": len(cases),
            "cases": [
                {"name": c["name"], "passed": passed, "actual": None, "error": None}
                for c in cases
            ],
            "elapsed_s": 0.125,
            "execution_error": None,
        }

    return spec, partial, evaluate, calls


@pytest.mark.asyncio
async def test_verify_finds_new_public_failure_then_repair_before_final_hidden_grade():
    spec, partial, evaluate, calls = fixture()
    provider = Provider([partial, spec.task.reference_files])
    episode = VerificationEpisode(spec, provider, evaluator=evaluate)
    result = await run_verification_episode(episode)
    assert result["solved"] and result["version"] == "0.3-dev"
    assert result["verification_calls"] == 2
    assert result["verification_elapsed_s"] == 0.25
    assert (
        result["tool_calls"] == 6
    )  # baseline + 2 candidates + 2 VERIFY + final grader
    assert result["cost_usd"] == 0.002  # no provider request for VERIFY
    assert result["verification_inference_cost_usd"] == 0
    assert calls[-1][0] is True and sum(hidden for hidden, _ in calls) == 1
    assert [
        e["data"]["action"] for e in result["events"] if e["kind"] == "decision"
    ] == ["retry", "verify", "repair", "verify", "stop"]
    assert "supplemental_verification" not in provider.calls[0]
    assert provider.calls[1]["supplemental_verification"]["passed"] == 0
    prompts = json.dumps(provider.calls)
    assert all(c["name"] not in prompts for c in spec.task.hidden_cases)


@pytest.mark.asyncio
async def test_same_candidate_cannot_verify_twice_and_candidate_change_invalidates_signal():
    spec, partial, evaluate, _ = fixture()
    episode = VerificationEpisode(
        spec, Provider([partial, spec.task.reference_files]), evaluator=evaluate
    )
    await episode.step("retry")
    assert not episode.terminal
    await episode.step("verify")
    assert episode.observation()["verification_passed"] == 0
    with pytest.raises(ValueError, match="Illegal"):
        await episode.step("verify")
    await episode.step("repair")
    assert episode.observation()["verification_passed"] is None
    await episode.step("verify")
    assert "verify" not in episode.legal_actions(episode.observation())


@pytest.mark.asyncio
async def test_verification_cap_and_decision_budget_cannot_be_bypassed():
    spec, partial, evaluate, _ = fixture()
    episode = VerificationEpisode(
        spec, Provider([partial]), evaluator=evaluate, max_verifications=1
    )
    await episode.step("retry")
    await episode.step("verify")
    assert "verify" not in episode.legal_actions(episode.observation())
    bounded = VerificationEpisode(
        spec, Provider([partial]), evaluator=evaluate, max_decisions=1
    )
    await bounded.step("retry")
    assert bounded.terminal and bounded.verification_calls == 0


@pytest.mark.asyncio
async def test_original_v02_still_stops_on_visible_green_without_verify():
    spec, partial, evaluate, calls = fixture()
    episode = RepoEpisode(spec.task, Provider([partial]), evaluator=evaluate)
    await episode.step("retry")
    assert episode.terminal and episode.stop_reason == "visible_tests_pass"
    assert episode.result()["version"] == "0.2"
    assert task_manifest_hash() == V02_HASH


def test_draft_is_not_preregistered_or_an_evaluation_and_has_new_manifest():
    plan = draft_plan()
    assert plan["status"] == "development_only_not_preregistered"
    assert plan["task_count"] == 2 and plan["inference_enabled"] is False
    assert plan["task_manifest_sha256"] != V02_HASH
    assert plan["completed_evaluation_episodes"] == 0
    assert plan["frozen"] is False


def test_supplemental_cases_are_distinct_and_old_controller_rejected():
    for spec in development_tasks():
        inputs = lambda cases: {
            json.dumps([c["args"], c.get("kwargs", {})], sort_keys=True) for c in cases
        }
        assert not inputs(spec.verification_cases) & inputs(spec.task.hidden_cases)
        assert not inputs(spec.verification_cases) & inputs(spec.task.public_cases)
        assert spec.task.split == "development"
    spec, _, evaluate, _ = fixture()
    with pytest.raises(ValueError, match="controller"):
        VerificationEpisode(
            spec,
            Provider([]),
            artifact={"feature_version": "forgebench-state-v2"},
            evaluator=evaluate,
        )
    with pytest.raises(ValueError, match="1 or 2"):
        VerificationEpisode(spec, Provider([]), max_verifications=3, evaluator=evaluate)


@pytest.mark.asyncio
async def test_stopping_after_observed_verification_failure_is_not_solved():
    spec, partial, evaluate, _ = fixture()
    episode = VerificationEpisode(spec, Provider([partial]), evaluator=evaluate)
    await episode.step("retry")
    await episode.step("verify")
    await episode.step("stop")
    result = await episode.finish()
    assert result["verification_passed"] == 0 and not result["solved"]


@pytest.mark.asyncio
async def test_success_definition_does_not_depend_on_whether_verifier_was_invoked():
    spec, partial, evaluate, _ = fixture()

    def imperfect_signal(task, files, hidden=False):
        result = evaluate(task, files, hidden)
        if hidden:
            result["passed"] = result["total"]
        return result

    episode = VerificationEpisode(spec, Provider([partial]), evaluator=imperfect_signal)
    await episode.step("retry")
    await episode.step("verify")
    await episode.step("stop")
    result = await episode.finish()
    assert result["solved"] and result["verification_passed"] == 0
    assert result["verification_grader_disagreement"] is True
    assert result["verification_grader_disagreement_direction"] == "false_rejection"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "supplemental_pass,hidden_pass,disagreement,direction",
    [
        (True, False, True, "missed_failure"),
        (False, True, True, "false_rejection"),
        (True, True, False, None),
        (False, False, False, None),
    ],
)
async def test_disagreement_is_bidirectional(
    supplemental_pass, hidden_pass, disagreement, direction
):
    spec, _, evaluate, _ = fixture()

    def grading(task, files, hidden=False):
        result = evaluate(task, files, hidden)
        if hidden:
            result["passed"] = result["total"] if hidden_pass else 0
        elif task.public_cases == spec.verification_cases:
            result["passed"] = result["total"] if supplemental_pass else 0
        return result

    episode = VerificationEpisode(
        spec, Provider([spec.task.reference_files]), evaluator=grading
    )
    await episode.step("retry")
    await episode.step("verify")
    await episode.step("stop")
    result = await episode.finish()
    assert result["verification_grader_disagreement"] is disagreement
    assert result["verification_grader_disagreement_direction"] == direction


@pytest.mark.asyncio
async def test_missing_hidden_grade_has_unknown_verifier_disagreement():
    spec, _, evaluate, _ = fixture()
    episode = VerificationEpisode(
        spec, Provider([spec.task.reference_files]), evaluator=evaluate
    )
    await episode.step("retry")
    await episode.step("verify")
    episode.status = "failed"
    result = await episode.finish()
    assert result["heldout_passed"] is None
    assert result["verification_grader_disagreement"] is None
    assert result["verification_grader_disagreement_direction"] is None


def test_rejects_verification_cases_reusing_hidden_or_public_input():
    spec = development_tasks()[0]
    for cases in (spec.task.public_cases, spec.task.hidden_cases):
        with pytest.raises(ValueError, match="overlap"):
            VerificationEpisode(replace(spec, verification_cases=cases), Provider([]))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy", ["strong_only", "cheap_only", "escalate_on_failure", "static_router"]
)
async def test_nonlearned_policies_have_identical_verifier_access_and_caps(policy):
    spec, partial, evaluate, _ = fixture()
    episode = VerificationEpisode(
        spec, Provider([partial]), policy=policy, evaluator=evaluate
    )
    await episode.step("retry")
    assert "verify" in episode.legal_actions(episode.observation())
    assert episode.max_verifications == 2
    assert episode.max_steps == 6 and episode.max_decisions == 10


@pytest.mark.asyncio
async def test_changed_candidate_hash_rejects_delayed_verifier_result():
    spec, partial, evaluate, _ = fixture()
    episode = None

    def delayed_result(task, files, hidden=False):
        result = evaluate(task, files, hidden)
        if task.public_cases == spec.verification_cases:
            episode.files = dict(spec.task.reference_files)
        return result

    episode = VerificationEpisode(spec, Provider([partial]), evaluator=delayed_result)
    await episode.step("retry")
    with pytest.raises(RuntimeError, match="changed during verification"):
        await episode.step("verify")
    assert episode.current_verification() is None
    assert not episode.verified_candidates


@pytest.mark.asyncio
async def test_unavailable_verifier_is_failure_with_time_and_no_hidden_grade():
    spec, partial, evaluate, calls = fixture()

    def unavailable(task, files, hidden=False):
        if task.public_cases == spec.verification_cases:
            raise SandboxUnavailable("fixture executor unavailable")
        return evaluate(task, files, hidden)

    episode = VerificationEpisode(spec, Provider([partial]), evaluator=unavailable)
    result = await run_verification_episode(episode)
    assert result["status"] == "failed" and not result["solved"]
    assert result["verification_calls"] == 1
    assert result["verification_passed"] is None
    assert result["verification_elapsed_s"] >= 0
    assert all(not hidden for hidden, _ in calls)
    assert any(
        e["title"] == "Supplemental verification unavailable" for e in result["events"]
    )


@pytest.mark.skipif(
    os.environ.get("FORGERL_DOCKER_TESTS") != "1",
    reason="real rootless Docker sandbox opt-in",
)
@pytest.mark.parametrize("spec", development_tasks(), ids=lambda spec: spec.task.id)
def test_development_fixtures_inside_real_isolated_sandbox(spec):
    task = spec.task
    starter = sandbox.evaluate(task, task.files)
    assert starter["execution_error"] is None
    assert starter["passed"] < starter["total"]
    for checked, hidden in (
        (task, False),
        (task, True),
        (replace(task, public_cases=spec.verification_cases), False),
    ):
        result = sandbox.evaluate(checked, task.reference_files, hidden)
        assert result["execution_error"] is None
        assert result["passed"] == result["total"]
    partial = dict(task.reference_files)
    if task.id == "dev-temperature-offset":
        partial["conversion.py"] = partial["conversion.py"].replace(
            "value - 32", "abs(value) - 32"
        )
    else:
        partial["tokens.py"] = partial["tokens.py"].replace(
            "value.casefold()", "value.lower()"
        )
    original = sandbox.evaluate(task, partial)
    additional = sandbox.evaluate(
        replace(task, public_cases=spec.verification_cases), partial
    )
    assert original["passed"] == original["total"]
    assert additional["passed"] < additional["total"]
