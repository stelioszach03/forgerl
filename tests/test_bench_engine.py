import copy
import json
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from forgerl.bench import engine, router, sandbox, study
from forgerl.provider import ProviderError, BudgetExceeded
from forgerl.sandbox import SandboxRejected, SandboxUnavailable
from forgerl.store import Store


@dataclass
class Task:
    id: str = "test-repo"
    title: str = "Preserve linked module behavior"
    family: str = "testing"
    split: str = "train"
    category: str = "multi_file"
    description: str = "Do not mutate input. Return twice the requested integer."
    success_criterion: str = "All visible and held-out checks pass."
    entrypoint: str = "service:run"

    @property
    def files(self):
        return {
            "service.py": "from helper import twice\ndef run(value):\n    return twice(value)\n",
            "helper.py": "def twice(value):\n    return value\n",
        }

    @property
    def reference_files(self):
        return {**self.files, "helper.py": "def twice(value):\n    return value * 2\n"}

    allowed_edit_files = ("service.py", "helper.py")
    public_cases = (
        {"name": "zero", "args": [0], "expected": 0},
        {"name": "positive", "args": [3], "expected": 6},
    )
    hidden_cases = ({"name": "SECRET_NEGATIVE", "args": [-9012], "expected": -18024},)


def grade(passed, hidden=False):
    total = 1 if hidden else 2
    return {
        "passed": passed,
        "total": total,
        "cases": [
            {
                "name": str(i),
                "passed": i < passed,
                "actual": None,
                "error": None if i < passed else "failed",
            }
            for i in range(total)
        ],
    }


class FakeProvider:
    def __init__(self, files=None, error=None):
        self.files, self.error = files, error
        self.calls = []

    def estimate_reservation_usd(self, *args):
        return 0.01

    def metadata(self):
        return {
            "models": [{"id": "fake-cheap"}, {"id": "fake-strong"}],
            "cost_basis": "Mock provider; never real evidence",
        }

    def build_messages(self, task, files, feedback, action):
        return [
            {
                "role": "user",
                "content": json.dumps({"files": files, "feedback": feedback}),
            }
        ]

    async def generate(self, task, files, feedback, action, **kwargs):
        self.calls.append(
            (task.id, copy.deepcopy(files), copy.deepcopy(feedback), action, kwargs)
        )
        if self.error:
            raise self.error
        result_files = self.files or task.reference_files
        return SimpleNamespace(
            files=result_files,
            model="fake-" + action,
            prompt_tokens=10,
            completion_tokens=20,
            cost_usd=0.001,
            elapsed_s=0.01,
            request_id="fixture",
            finish_reason="stop",
            prompt_messages=self.build_messages(task, files, feedback, action),
            response_text=json.dumps({"files": result_files}),
            total_tokens=35,
        )


def test_repository_payload_paths_imports_and_protected_edits():
    task = Task()
    sandbox.validate_files(task.files, task.entrypoint)
    payload, encoded = sandbox.payload(
        task.files, task.entrypoint, list(task.hidden_cases)
    )
    assert "expected" not in encoded.decode()
    assert payload["kind"] == "repository-v2"
    for files in (
        {"../escape.py": "def run(): return 1"},
        {"os.py": "import os\ndef run(): return 1"},
        {
            "service.py": "from helper import twice\ndef run(x): return twice(x)",
            "helper.py": "from service import run\ndef twice(x): return run(x)",
        },
        {"math.py": "def run(x): return x"},
    ):
        with pytest.raises(SandboxRejected):
            sandbox.validate_files(
                files,
                "service:run"
                if "service.py" in files
                else next(iter(files)).replace(".py", ":run"),
            )
    protected = Task()
    protected.allowed_edit_files = ("service.py",)
    with pytest.raises(SandboxRejected, match="protected"):
        sandbox.validate_edits(protected, protected.reference_files)


def test_repository_hidden_grading_never_exports_inputs_or_expected_outputs():
    task = Task()

    def execute(payload):
        assert all(set(c) == {"name", "args", "kwargs"} for c in payload["cases"])
        return {
            "cases": [
                {
                    "name": "SECRET_NEGATIVE",
                    "actual": -18024,
                    "error": None,
                    "input_mutated": False,
                }
            ]
        }

    with (
        patch.object(sandbox.base, "execute_docker", side_effect=execute),
        patch.dict("os.environ", {}, clear=True),
    ):
        result = sandbox.evaluate(task, task.reference_files, True)
    assert result["passed"] == 1
    exported = json.dumps(result)
    assert (
        "SECRET_NEGATIVE" not in exported
        and "18024" not in exported
        and "9012" not in exported
    )


@pytest.mark.asyncio
async def test_complete_episode_records_actual_context_tools_patch_tokens_and_hidden_once():
    task, provider, calls = Task(), FakeProvider(), []

    def evaluator(t, files, hidden):
        calls.append(hidden)
        return grade(1 if hidden else 2 if files == t.reference_files else 1, hidden)

    episode = engine.RepoEpisode(task, provider, "cheap_only", evaluator=evaluator)
    result = await engine.run_episode(episode)
    assert result["solved"] and result["tokens"] == 35
    assert calls == [False, False, True]
    assert result["tool_calls"] == 3 and result["attempts"] == 1
    assert result["unnecessary_edits"] == 0 and not result["success_after_repair"]
    assert result["diff"].startswith("--- a/helper.py")
    kinds = [e["kind"] for e in result["events"]]
    assert all(
        k in kinds
        for k in (
            "prompt",
            "context",
            "tool_call",
            "inference",
            "patch",
            "tests",
            "complete",
        )
    )
    assert "SECRET_NEGATIVE" not in json.dumps(result) and "9012" not in json.dumps(
        provider.calls
    )


@pytest.mark.asyncio
async def test_rollback_uses_visible_checkpoint_and_adds_no_model_or_hidden_call():
    task, provider = (
        Task(),
        FakeProvider(files={"helper.py": "def twice(value):\n    return -999\n"}),
    )

    def evaluator(t, files, hidden):
        return grade(1 if files == t.files else 0, hidden)

    episode = engine.RepoEpisode(task, provider, "static_router", evaluator=evaluator)
    await episode.start()
    await episode.step("retry")
    assert episode.observation()["can_rollback"]
    assert episode.regressions == 1
    assert (
        router.choose_action("static_router", episode.observation())["action"]
        == "rollback"
    )
    await episode.step("rollback")
    assert episode.files == task.files and episode.public["passed"] == 1
    assert (
        len(provider.calls) == 1 and episode.tool_calls == 2 and episode.hidden is None
    )
    with pytest.raises(ValueError, match="Illegal"):
        await episode.step("rollback")


@pytest.mark.asyncio
async def test_hidden_failure_is_never_used_to_retry_and_failure_label_is_observed_proxy():
    task, provider = Task(), FakeProvider()
    count = 0

    def evaluator(t, files, hidden):
        nonlocal count
        count += 1
        return grade(0 if hidden else 2 if count > 1 else 1, hidden)

    result = await engine.run_episode(
        engine.RepoEpisode(task, provider, "adaptive", evaluator=evaluator)
    )
    assert not result["solved"] and result["attempts"] == 1
    assert "verification:visible_pass_hidden_fail" in result["failure_labels"]
    assert result["fallback_decisions"] == 1
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_failure_and_unknown_measurements_do_not_turn_into_zero_or_success():
    error = ProviderError("timeout", 0.02)
    result = await engine.run_episode(
        engine.RepoEpisode(
            Task(),
            FakeProvider(error=error),
            "cheap_only",
            evaluator=lambda *args: grade(1),
        )
    )
    assert result["status"] == "failed" and result["cost_usd"] == 0.02
    assert result["tokens"] is None and result["heldout_passed"] is None
    assert not result["solved"] and result["tool_calls"] == 1

    def unavailable(*args):
        raise SandboxUnavailable("offline")

    provider = FakeProvider()
    result = await engine.run_episode(
        engine.RepoEpisode(Task(), provider, "cheap_only", evaluator=unavailable)
    )
    assert result["public_passed"] is None and result["heldout_passed"] is None
    assert not provider.calls


@pytest.mark.asyncio
async def test_invalid_response_can_repair_with_charge_retained_and_no_hidden_feedback():
    error = ProviderError("invalid JSON", 0.02)
    error.failure_kind = "invalid_candidate"
    error.prompt_tokens, error.completion_tokens = 3, 4
    episode = engine.RepoEpisode(
        Task(),
        FakeProvider(error=error),
        "cheap_only",
        max_steps=2,
        evaluator=lambda t, files, hidden: grade(0 if hidden else 1, hidden),
    )
    result = await engine.run_episode(episode)
    assert result["status"] == "completed" and result["attempts"] == 2
    assert result["cost_usd"] == 0.04 and result["tokens"] == 14
    assert len(episode.transitions) == 2 and not result["solved"]
    assert "implementation:invalid_candidate" in result["failure_labels"]


def state(**changes):
    return {
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
        **changes,
    }


def test_five_policies_are_bounded_and_learning_rejects_test_leakage():
    start = state()
    assert router.choose_action("strong_only", start)["action"] == "escalate"
    assert router.choose_action("cheap_only", start)["action"] == "retry"
    after = state(attempts=1)
    assert router.choose_action("escalate_on_failure", after)["action"] == "escalate"
    assert router.choose_action("adaptive", after)["source"] == "heuristic_fallback"
    for policy in router.POLICIES:
        assert router.choose_action(policy, state(attempts=6))["action"] == "stop"
    row = {
        "task_id": "a",
        "split": "train",
        "state": start,
        "action": "retry",
        "next_state": after,
        "reward": 1,
        "terminal": True,
    }
    artifact = router.fit_q([row] * 12)
    assert artifact["trained"] and router.choose_action(
        "adaptive", start, artifact
    ) == {"action": "retry", "source": "learned_q"}
    assert router.encode_state(
        {**start, "hidden_passed": 99, "task_id": "injected"}
    ) == router.encode_state(start)
    with pytest.raises(ValueError, match="train-only"):
        router.fit_q([{**row, "split": "test"}])


@pytest.mark.asyncio
async def test_study_cap_uses_existing_ledger_and_uncertain_costs(tmp_path):
    provider = FakeProvider()
    provider.store = Store(tmp_path / "ledger.sqlite3")
    old = provider.store.reserve("research", "older", 200_000)
    provider.store.settle(old, 100_000)
    bounded = study.CappedProvider(provider, 0.015)
    first = provider.store.reserve("research", "uncertain", 10000)
    provider.store.settle(first, None)
    assert bounded.spent() == pytest.approx(0.01)
    with pytest.raises(BudgetExceeded, match="Per-study"):
        await bounded.generate(Task(), Task().files, {}, "cheap")
    assert not provider.calls
    assert provider.store.budget("research")["charged_usd"] == 0.11


def test_summary_retains_missing_failure_and_null_measurements():
    run = {
        "policy": "cheap_only",
        "status": "failed",
        "solved": False,
        "cost_usd": 0.02,
        "tokens": None,
        "attempts": 1,
        "steps": 1,
        "heldout_passed": None,
        "heldout_total": 3,
        "elapsed_s": 10,
        "tool_calls": 1,
        "regressions_introduced": 0,
        "unnecessary_edits": None,
        "success_after_repair": False,
        "escalations": 0,
        "learned_decisions": 0,
        "fallback_decisions": 0,
    }
    rows = study.summarize([run], 10)
    cheap = next(r for r in rows if r["policy"] == "cheap_only")
    assert cheap["n"] == 1 and cheap["planned"] == 10 and cheap["solve_rate"] == 0
    assert cheap["hidden_test_pass_rate"] is None and cheap["mean_tokens"] is None
    assert all(r["solve_rate"] is None for r in rows if r["n"] == 0)


@pytest.mark.asyncio
async def test_full_study_freezes_train_only_controller_and_retains_actual_coverage(
    tmp_path,
):
    provider = FakeProvider()
    provider.store = Store(tmp_path / "existing.sqlite3")
    tasks = [
        Task(id="train-a", family="alpha", split="train"),
        Task(id="val-b", family="beta", split="validation"),
        Task(id="test-c", family="gamma", split="test"),
    ]

    def episode_factory(task, provider, policy, **kwargs):
        def evaluator(t, files, hidden):
            return grade(
                1 if hidden else 2 if files == t.reference_files else 1, hidden
            )

        return engine.RepoEpisode(task, provider, policy, evaluator=evaluator, **kwargs)

    result = await study.run_study(
        tasks,
        provider,
        tmp_path / "study",
        task_manifest_hash="fixture",
        episode_factory=episode_factory,
        train_rollouts=2,
    )
    assert result["status"] == "complete"
    assert result["coverage"]["completed"] == result["coverage"]["planned"] == 10
    assert not result["coverage"]["missing"]
    assert len(result["summary"]) == 5 and all(
        r["n"] == 1 and r["solved"] == 1 for r in result["summary"]
    )
    artifact = json.loads((tmp_path / "study/controller.json").read_text())
    assert not artifact["trained"]  # Two transitions cannot be called trained.
    assert artifact["diagnostics"]["tasks"] == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "study/transitions.jsonl").read_text().splitlines()
    ]
    assert all(r["split"] == "train" and r["task_id"] == "train-a" for r in rows)
    assert (tmp_path / "study/events.jsonl").stat().st_size > 0
    assert len(list((tmp_path / "study/runs").glob("*.json"))) == 12
    with pytest.raises(FileExistsError):
        study.Writer(tmp_path / "study")


def test_cli_plan_has_no_provider_or_ledger_side_effects(monkeypatch, tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("bench_cli", "scripts/forgebench.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = module.parser().parse_args(["--output", str(tmp_path / "unused")])
    assert not args.execute_research and args.provider == "openrouter"
    assert args.max_steps == 6 and args.max_decisions == 10
    assert args.db is None and not (tmp_path / "unused").exists()


def test_visible_feedback_marks_large_actual_values_without_mutating_recorded_output():
    original = [
        {"name": "large output", "passed": False, "actual": "α" * 4000, "error": None},
        {"name": "legitimate null", "passed": True, "actual": None, "error": None},
    ]
    feedback = engine.bounded_visible_cases(original)
    assert original[0]["actual"] == "α" * 4000
    assert feedback[0]["actual"] is None and feedback[0]["actual_omitted"] is True
    assert len(feedback[0]["actual_preview"].encode()) <= 2048
    assert feedback[0]["actual_size_bytes"] > 8000
    assert "truncated JSON" in feedback[0]["actual_note"]
    assert feedback[1] == original[1] and "actual_omitted" not in feedback[1]


@pytest.mark.asyncio
async def test_oversized_context_after_paid_attempt_finishes_and_saves_trace(tmp_path):
    from forgerl.bench.provider import RepoProvider

    task = Task()
    # Valid Python below the source cap; repeated newlines make the serialized
    # outbound prompt exceed its independent JSON/context limit. Never execute.
    candidate = {
        "helper.py": "def twice(value):\n    return value\n" + "# filler\n" * 4300
    }
    sandbox.validate_edits(task, {**task.files, **candidate})
    gate = RepoProvider(None, "unused-test-value")

    class SizedProvider(FakeProvider):
        def estimate_reservation_usd(self, *args):
            return gate.estimate_reservation_usd(*args)

        def build_messages(self, *args):
            return gate.build_messages(*args)

    provider = SizedProvider(files=candidate)

    def evaluator(t, files, hidden):
        assert not hidden, "A prompt-preflight failure must remain ungraded"
        result = grade(1)
        if files != t.files:
            result["cases"][1]["actual"] = "x" * 50000
        return result

    result = await engine.run_episode(
        engine.RepoEpisode(task, provider, "cheap_only", evaluator=evaluator)
    )
    assert (
        result["status"] == "failed"
        and result["stop_reason"] == "prompt_preflight_error"
    )
    assert "context exceeds" in result["error"]
    assert len(provider.calls) == result["attempts"] == 1
    assert result["cost_usd"] == 0.001 and result["heldout_passed"] is None
    assert result["events"][-1]["kind"] == "complete"
    writer = study.Writer(tmp_path / "recorded")
    writer.run(result, "evaluation")
    saved = json.loads(
        (tmp_path / "recorded" / "runs" / (result["id"] + ".json")).read_text()
    )
    assert saved["status"] == "failed" and saved["cost_usd"] == 0.001
    assert any(
        event["title"] == "Provider prompt preflight failed"
        for event in saved["events"]
    )


@pytest.mark.asyncio
async def test_large_visible_output_can_be_repaired_using_explicit_bounded_preview():
    task = Task()
    broken = {"helper.py": "def twice(value):\n    return 3\n"}

    class TwoAttemptProvider(FakeProvider):
        async def generate(self, *args, **kwargs):
            self.files = broken if not self.calls else task.reference_files
            return await super().generate(*args, **kwargs)

    provider = TwoAttemptProvider()

    def evaluator(t, files, hidden):
        if hidden:
            return grade(1, True)
        if files == t.reference_files:
            return grade(2)
        result = grade(1)
        if files != t.files:
            result["cases"][1]["actual"] = "x" * 50000
        return result

    result = await engine.run_episode(
        engine.RepoEpisode(task, provider, "cheap_only", evaluator=evaluator)
    )
    assert result["solved"] and result["attempts"] == 2
    retry_feedback = provider.calls[1][2]["cases"][1]
    assert retry_feedback["actual"] is None and retry_feedback["actual_omitted"] is True
    assert len(retry_feedback["actual_preview"].encode()) <= 2048
    full_results = [
        event["data"]
        for event in result["events"]
        if event["kind"] == "tests" and event["data"].get("cases")
    ]
    assert any(row["cases"][1]["actual"] == "x" * 50000 for row in full_results)


@pytest.mark.asyncio
@pytest.mark.parametrize("rejection", ["ast", "protected"])
async def test_invalid_candidate_cap_includes_ast_and_protected_file_rejections(
    rejection,
):
    task = Task()
    if rejection == "protected":
        task.allowed_edit_files = ("service.py",)
        files = task.reference_files
    else:
        files = {"helper.py": "import os\ndef twice(value):\n    return value * 2\n"}
    provider = FakeProvider(files=files)
    result = await engine.run_episode(
        engine.RepoEpisode(
            task,
            provider,
            "cheap_only",
            evaluator=lambda t, files, hidden: grade(0 if hidden else 1, hidden),
        )
    )
    assert result["invalid_responses"] == result["attempts"] == len(provider.calls) == 3
    assert result["stop_reason"] == "invalid_response_retry_cap"
    assert result["cost_usd"] == pytest.approx(0.003)
    assert result["final_files"] == task.files and not result["solved"]
    assert (
        sum(
            event["title"] == "Candidate rejected before execution"
            for event in result["events"]
        )
        == 3
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["reservation_preflight", "prompt_preflight", "ledger_budget"]
)
async def test_unmade_escalation_does_not_change_role_or_increment_metric(failure):
    task, provider = Task(), FakeProvider(files=Task().files)
    episode = engine.RepoEpisode(
        task, provider, "escalate_on_failure", evaluator=lambda *args: grade(1)
    )
    await episode.start()
    await episode.step("retry")
    assert episode.attempts == 1 and episode.current_model == "cheap"
    if failure == "reservation_preflight":
        provider.estimate_reservation_usd = lambda *args: 2.0
    elif failure == "prompt_preflight":

        def invalid_prompt(*args):
            raise ProviderError("Context limit exceeded")

        provider.build_messages = invalid_prompt
    else:
        provider.error = BudgetExceeded("No reservation; no hosted request")
    await episode.step("escalate")
    assert episode.terminal and episode.escalations == 0
    assert episode.current_model == "cheap" and episode.attempts == 1
    assert episode.cost_usd == 0.001
    if failure != "ledger_budget":
        assert len(provider.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("charged_failure", [False, True])
async def test_observed_strong_request_counts_exactly_one_escalation(charged_failure):
    task, provider = Task(), FakeProvider(files=Task().files)
    episode = engine.RepoEpisode(
        task, provider, "escalate_on_failure", evaluator=lambda *args: grade(1)
    )
    await episode.start()
    await episode.step("retry")
    if charged_failure:
        provider.error = ProviderError("Charged request failed", 0.02)
    await episode.step("escalate")
    assert episode.escalations == 1 and episode.current_model == "strong"
    assert episode.attempts == 2 and len(provider.calls) == 2
    assert provider.calls[-1][3] == "strong"
    assert episode.cost_usd == pytest.approx(0.021 if charged_failure else 0.002)


@pytest.mark.asyncio
async def test_initial_strong_request_is_not_an_escalation():
    task, provider = Task(), FakeProvider()
    result = await engine.run_episode(
        engine.RepoEpisode(
            task,
            provider,
            "strong_only",
            evaluator=lambda t, files, hidden: grade(
                1 if hidden else 2 if files == t.reference_files else 1, hidden
            ),
        )
    )
    assert result["solved"] and result["escalations"] == 0
    assert provider.calls[0][3] == "strong"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "recover,limit,after,expected_calls,expected_delays",
    [
        (True, 6, 45, 2, [45]),
        (False, 6, None, 3, [30, 60]),
        (False, 1, None, 1, []),
        (False, 6, 120, 1, []),
    ],
)
async def test_rate_limit_retry_is_bounded_counted_and_recorded(
    monkeypatch, recover, limit, after, expected_calls, expected_delays
):
    error = ProviderError("Model provider returned HTTP 429", 0.02)
    error.http_status = 429
    error.retry_after_s = after
    error.accounting_kind = "retained_reservation"

    class RateProvider(FakeProvider):
        async def generate(self, *args, **kwargs):
            self.error = error if not recover or not self.calls else None
            return await super().generate(*args, **kwargs)

    provider = RateProvider()
    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(engine.asyncio, "sleep", sleep)
    calls = []

    def evaluate(task, files, hidden):
        calls.append(hidden)
        return grade(1 if hidden else 2 if files == task.reference_files else 1, hidden)

    episode = engine.RepoEpisode(
        Task(),
        provider,
        "strong_only",
        max_steps=limit,
        evaluator=evaluate,
        rate_limit_retries=2,
    )
    result = await engine.run_episode(episode)
    assert len(provider.calls) == expected_calls == result["attempts"]
    assert delays == expected_delays
    assert all(call[3] == "strong" for call in provider.calls)
    assert result["provider_retries"] == len(delays)
    assert result["cost_usd"] == pytest.approx(
        0.021 if recover else 0.02 * expected_calls
    )
    assert len([e for e in result["events"] if e["kind"] == "provider_backoff"]) == len(
        delays
    )
    assert result["tokens"] is None
    if recover:
        assert result["solved"] and result["status"] == "completed"
        assert calls == [False, False, True]
    else:
        assert result["status"] == "failed" and result["heldout_passed"] is None
        assert calls == [False]


@pytest.mark.asyncio
async def test_rate_limit_retry_does_not_bypass_episode_reservation_cap(monkeypatch):
    error = ProviderError("Model provider returned HTTP 429", 0.009)
    error.http_status = 429
    error.retry_after_s = 1
    provider = FakeProvider(error=error)

    async def sleep(delay):
        pass

    monkeypatch.setattr(engine.asyncio, "sleep", sleep)
    episode = engine.RepoEpisode(
        Task(),
        provider,
        "cheap_only",
        max_cost_usd=0.015,
        rate_limit_retries=2,
        evaluator=lambda *args: grade(1),
    )
    result = await engine.run_episode(episode)
    assert len(provider.calls) == 1 and result["cost_usd"] == 0.009
    assert result["status"] == "budget_exhausted"
    assert result["provider_retries"] == 0


@pytest.mark.asyncio
async def test_cancelling_backoff_never_issues_another_request(monkeypatch):
    error = ProviderError("Model provider returned HTTP 429", 0.02)
    error.http_status = 429
    provider = FakeProvider(error=error)

    async def cancel(delay):
        raise engine.asyncio.CancelledError()

    monkeypatch.setattr(engine.asyncio, "sleep", cancel)
    episode = engine.RepoEpisode(
        Task(),
        provider,
        "cheap_only",
        rate_limit_retries=2,
        evaluator=lambda *args: grade(1),
    )
    with pytest.raises(engine.asyncio.CancelledError):
        await engine.run_episode(episode)
    assert len(provider.calls) == 1 and episode.result()["status"] == "interrupted"
    assert episode.result()["heldout_passed"] is None


def test_retry_protocol_is_explicit_in_the_study_plan():
    from forgerl.bench.tasks import list_tasks

    original = study.plan(list_tasks())
    retrying = study.plan(list_tasks(), rate_limit_retries=2)
    assert original["protocol"] != retrying["protocol"]
    assert retrying["rate_limit_retries"] == 2
    assert original["evaluation_ids"] == retrying["evaluation_ids"]


@pytest.mark.asyncio
async def test_unmeasured_request_tokens_remain_reserved_against_the_episode_cap(
    monkeypatch,
):
    error = ProviderError("Model provider returned HTTP 429", 0.02)
    error.http_status = 429
    provider = FakeProvider(error=error)
    provider.estimate_token_bound = lambda *args: 60000

    async def sleep(delay):
        pass

    monkeypatch.setattr(engine.asyncio, "sleep", sleep)
    result = await engine.run_episode(
        engine.RepoEpisode(
            Task(),
            provider,
            "cheap_only",
            rate_limit_retries=2,
            evaluator=lambda *args: grade(1),
        )
    )
    assert len(provider.calls) == 1
    assert result["stop_reason"] == "episode_token_cap"
    assert result["provider_retries"] == 0
    assert result["unknown_token_upper_bound"] == 60000 and result["tokens"] is None
