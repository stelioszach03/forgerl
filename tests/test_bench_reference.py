"""No paid calls: fixed-reference transport, budget and evidence tests use mocks."""

import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from forgerl.bench import reference, engine
from forgerl.bench.tasks import list_tasks
from forgerl.provider import ProviderError, BudgetExceeded
from forgerl.store import Store


TASK = next(task for task in list_tasks() if task.split == "test")
SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "docs/forgebench/reference-provider-snapshot.json"
)


def data_reply(**changes):
    data = {
        "id": "mock-reference-request",
        "provider": "OpenAI",
        "model": "openai/gpt-4.1",
        "usage": {
            "prompt_tokens": 300,
            "completion_tokens": 200,
            "total_tokens": 500,
            "cost": 0.0022,
        },
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({"files": {}}),
                    "reasoning": "MUST_NOT_BE_RECORDED",
                },
            }
        ],
    }
    data.update(changes)
    return data


def mock_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_fixed_reference_plan_uses_all_existing_test_tasks_and_caps():
    plan = reference.reference_plan(list_tasks())
    assert plan["task_ids"] == sorted(
        task.id for task in list_tasks() if task.split == "test"
    )
    assert len(plan["task_ids"]) == 10 and plan["seed"] == 17
    assert plan["maximum_model_calls"] == 6 and plan["maximum_decisions"] == 10
    assert plan["model"] == "openai/gpt-4.1"
    assert (
        plan["routing"]["only"] == ["openai"]
        and plan["routing"]["allow_fallbacks"] is False
    )
    assert not plan["primary_results_pooled"] and plan["version"] != "0.2"
    for amount in (0, -1, 1.01, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            reference.reference_plan(list_tasks(), amount)


def test_official_snapshot_satisfies_exact_frozen_contract():
    data = json.loads(SNAPSHOT.read_text())["response"]
    result = reference.validate_catalog(data)
    assert result["model_id"] == "openai/gpt-4.1"
    assert result["endpoint"]["provider_name"] == "OpenAI"
    assert result["source_url"] == reference.CATALOG_URL
    for modification in ("price", "provider", "parameter"):
        changed = copy.deepcopy(data)
        endpoint = next(
            row for row in changed["data"]["endpoints"] if row["tag"] == "openai"
        )
        if modification == "price":
            endpoint["pricing"]["completion"] = "0.000009"
        elif modification == "provider":
            endpoint["provider_name"] = "Another provider"
        else:
            endpoint["supported_parameters"].remove("seed")
        with pytest.raises(ProviderError):
            reference.validate_catalog(changed)


@pytest.mark.asyncio
async def test_reference_reserves_existing_ledger_before_network_and_captures_visible_content(
    tmp_path, monkeypatch
):
    store = Store(tmp_path / "existing.sqlite")
    old = store.reserve("research", "previous-study", 100000)
    store.settle(old, 100000)
    calls = []

    def handler(request):
        assert store.budget("research")["charged_usd"] > 0.1
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=data_reply())

    mock_transport(monkeypatch, handler)
    provider = reference.ReferenceProvider(store, "test-value-not-a-real-key")
    result = await provider.generate(
        TASK, TASK.files, {}, "strong", seed=18, run_id="mock"
    )
    assert str(calls[0]["model"]) == reference.MODEL
    assert calls[0]["provider"] == reference.ROUTING
    assert calls[0]["max_tokens"] == 4096 and calls[0]["seed"] == 18
    assert "reasoning" not in calls[0] and "reasoning_effort" not in calls[0]
    assert result.model == reference.MODEL and result.provider_id == "OpenAI"
    assert (
        result.cost_usd == 0.0022 and store.budget("research")["charged_usd"] == 0.1022
    )
    assert "MUST_NOT_BE_RECORDED" not in result.response_text
    assert "test-value-not-a-real-key" not in json.dumps(result.prompt_messages)
    with pytest.raises(ProviderError):
        await provider.generate(TASK, TASK.files, {}, "cheap")
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes", [{"provider": "Azure"}, {"model": "openai/gpt-4.1-mini"}]
)
async def test_reference_excludes_wrong_model_or_provider_and_retains_charge(
    tmp_path, monkeypatch, changes
):
    mock_transport(
        monkeypatch, lambda request: httpx.Response(200, json=data_reply(**changes))
    )
    store = Store(tmp_path / "existing.sqlite")
    with pytest.raises(ProviderError, match="identity mismatch") as caught:
        await reference.ReferenceProvider(store, "test").generate(
            TASK, TASK.files, {}, "strong"
        )
    assert (
        caught.value.cost_usd == 0.0022
        and store.budget("research")["charged_usd"] == 0.0022
    )


@pytest.mark.asyncio
async def test_unknown_reference_bill_retains_reservation_and_rejected_reservation_makes_no_network_call(
    tmp_path, monkeypatch
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=data_reply(usage={"prompt_tokens": 10}))

    mock_transport(monkeypatch, handler)
    store = Store(tmp_path / "existing.sqlite")
    provider = reference.ReferenceProvider(store, "test")
    reserved = provider.estimate_reservation_usd(TASK, TASK.files, {}, "strong")
    with pytest.raises(ProviderError):
        await provider.generate(TASK, TASK.files, {}, "strong")
    assert store.budget("research")["charged_usd"] == reserved
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO settings(name,value) VALUES('provider_disabled','test-block')"
        )
    with pytest.raises(BudgetExceeded):
        await provider.generate(TASK, TASK.files, {}, "strong")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_reference_study_is_separate_preserves_all_ten_tasks_and_actual_coverage(
    tmp_path,
):
    class FakeProvider:
        def __init__(self):
            self.store = Store(tmp_path / "existing.sqlite")

        def metadata(self):
            return {
                "models": [{"id": reference.MODEL}],
                "cost_basis": "Mock evidence only",
            }

        def estimate_reservation_usd(self, *args):
            return 0.01

        def build_messages(self, *args):
            return [{"role": "user", "content": "mock"}]

        async def generate(self, task, files, feedback, action, **kwargs):
            charge = self.store.reserve(
                "research", reference.MODEL, 10000, run_id=kwargs["run_id"]
            )
            self.store.settle(charge, 10000)
            return SimpleNamespace(
                files=task.reference_files,
                model=reference.MODEL,
                prompt_tokens=10,
                completion_tokens=10,
                cost_usd=0.01,
                elapsed_s=0.01,
                request_id="mock",
                finish_reason="stop",
                prompt_messages=[],
                response_text="{}",
                total_tokens=20,
            )

    def episode_factory(task, provider, policy, **kwargs):
        def evaluator(t, files, hidden):
            total = len(t.hidden_cases if hidden else t.public_cases)
            passed = total if files == t.reference_files else 0
            return {
                "passed": passed,
                "total": total,
                "cases": [
                    {"name": str(i), "passed": i < passed, "actual": None}
                    for i in range(total)
                ],
            }

        return engine.RepoEpisode(task, provider, policy, evaluator=evaluator, **kwargs)

    provider = FakeProvider()
    output = tmp_path / "reference"
    report = await reference.run_reference(
        list_tasks(),
        provider,
        output,
        catalog_receipt={"mock": True},
        max_cost_usd=0.035,
        episode_factory=episode_factory,
    )
    assert report["version"] == "0.2-reference"
    assert report["status"] == "partial" and report["coverage"]["planned"] == 10
    assert (
        report["coverage"]["attempted"] == 4 and len(report["coverage"]["missing"]) == 6
    )
    assert (
        report["summary"]["solved"] == 3
        and provider.store.budget("research")["charged_usd"] == 0.03
    )
    assert (output / "reference.json").is_file() and not (
        output / "benchmark.json"
    ).exists()
    assert len(list((output / "runs").glob("*.json"))) == 4
    assert report["provenance"]["configuration"]["primary_results_pooled"] is False


@pytest.mark.asyncio
async def test_reference_cli_default_plan_reads_no_key_ledger_or_network(
    tmp_path, monkeypatch, capsys
):
    path = Path(__file__).resolve().parents[1] / "scripts/reference_forgebench.py"
    spec = importlib.util.spec_from_file_location("reference_cli_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(*args, **kwargs):
        raise AssertionError("Plan must not read credentials or network")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    args = module.parser().parse_args(
        [
            "--db",
            str(tmp_path / "missing.sqlite"),
            "--key-file",
            str(tmp_path / "missing.key"),
        ]
    )
    assert await module.main(args) == 0
    assert "Plan only" in capsys.readouterr().out
    assert not (tmp_path / "missing.sqlite").exists()
