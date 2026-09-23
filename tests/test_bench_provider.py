import json
from types import SimpleNamespace

import httpx
import pytest

from forgerl.bench.provider import RepoProvider, extract_files, prompt_messages
from forgerl.provider import ProviderError
from forgerl.store import Store


@pytest.fixture
def task():
    return SimpleNamespace(
        title="A repair",
        description="Return an integer.",
        success_criterion="All checks pass.",
        entrypoint="service:run",
        files={
            "service.py": "def run(x):\n    return 0\n",
            "rules.py": "def rule(x):\n    return x\n",
        },
        allowed_edit_files=("service.py",),
        public_cases=({"name": "visible", "args": [1], "kwargs": {}, "expected": 1},),
        hidden_cases=({"expected": "PRIVATE_HELDOUT_SENTINEL"},),
        reference_files={"service.py": "REFERENCE_PATCH_SENTINEL"},
    )


def reply(**overrides):
    data = {
        "id": "fake-response",
        "provider": "CoreWeave",
        "model": "openai/gpt-oss-20b",
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150,
            "cost": 0.0000101,
        },
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {"files": {"service.py": "def run(x):\n    return x\n"}}
                    ),
                    "reasoning": "NOT_A_PUBLIC_TRAJECTORY",
                },
            }
        ],
    }
    data.update(overrides)
    return data


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_prompt_has_only_visible_task_information(task):
    messages = json.dumps(prompt_messages(task, task.files, {}))
    assert "PRIVATE_HELDOUT_SENTINEL" not in messages
    assert "REFERENCE_PATCH_SENTINEL" not in messages
    assert "visible" in messages and "rules.py" in messages


def test_protected_file_and_invalid_json_are_rejected(task):
    for content in [
        '{"files":{"../escape.py":"x"}}',
        '{"files":{"rules.py":"x"}}',
        '{"files":[]}',
        "not JSON",
    ]:
        with pytest.raises(ProviderError):
            extract_files(content, task, task.files)
    fixed = extract_files(
        '```json\n{"files":{"service.py":"def run(x): return x"}}\n```',
        task,
        task.files,
    )
    assert fixed["rules.py"] == task.files["rules.py"]


@pytest.mark.asyncio
async def test_openrouter_pins_provider_and_accounts_reported_cost(
    tmp_path, monkeypatch, task
):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=reply())

    transport(monkeypatch, handler)
    store = Store(tmp_path / "ledger.sqlite")
    provider = RepoProvider(store, "test-only-not-a-real-key")
    estimate = provider.estimate_reservation_usd(task, task.files, {}, "cheap")
    result = await provider.generate(task, task.files, {}, "cheap", run_id="fixture")
    assert calls[0]["provider"]["only"] == ["coreweave/fp4"]
    assert calls[0]["provider"]["allow_fallbacks"] is False
    assert result.cost_usd == 0.000011  # Rounded up to a durable microUSD.
    assert store.budget("research")["charged_usd"] == result.cost_usd
    assert result.cost_usd < estimate
    assert result.provider_reported_cost_usd == 0.0000101
    assert result.provider_id == "CoreWeave"
    assert "NOT_A_PUBLIC_TRAJECTORY" not in result.response_text
    assert "test-only-not-a-real-key" not in json.dumps(result.prompt_messages)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": 2},
        {"prompt_tokens": True, "completion_tokens": 2, "cost": 0},
        {"prompt_tokens": 2, "completion_tokens": 3, "cost": -1},
        "malformed",
    ],
)
async def test_uncertain_usage_retains_exact_reservation(
    tmp_path, monkeypatch, task, usage
):
    transport(monkeypatch, lambda _: httpx.Response(200, json=reply(usage=usage)))
    store = Store(tmp_path / "ledger.sqlite")
    provider = RepoProvider(store, "test-only")
    reservation = provider.estimate_reservation_usd(task, task.files, {}, "cheap")
    with pytest.raises(ProviderError) as caught:
        await provider.generate(task, task.files, {}, "cheap")
    assert store.budget("research")["charged_usd"] == reservation
    assert caught.value.cost_usd == reservation
    assert caught.value.prompt_messages


@pytest.mark.asyncio
async def test_wrong_provider_keeps_actual_cost_but_rejects_candidate(
    tmp_path, monkeypatch, task
):
    transport(
        monkeypatch,
        lambda _: httpx.Response(200, json=reply(provider="Unexpected provider")),
    )
    store = Store(tmp_path / "ledger.sqlite")
    with pytest.raises(ProviderError, match="Pinned provider") as caught:
        await RepoProvider(store, "test-only").generate(task, task.files, {}, "cheap")
    assert caught.value.cost_usd == 0.000011
    assert caught.value.response_text
    assert caught.value.provider_id == "Unexpected provider"


@pytest.mark.asyncio
async def test_bad_json_keeps_actual_cost_and_raw_visible_response(
    tmp_path, monkeypatch, task
):
    transport(
        monkeypatch,
        lambda _: httpx.Response(
            200, json=reply(choices=[{"message": {"content": "invalid JSON"}}])
        ),
    )
    store = Store(tmp_path / "ledger.sqlite")
    with pytest.raises(ProviderError) as caught:
        await RepoProvider(store, "test-only").generate(task, task.files, {}, "cheap")
    assert caught.value.response_text == "invalid JSON"
    assert caught.value.cost_usd == 0.000011


@pytest.mark.asyncio
async def test_auth_failure_stops_future_spending(tmp_path, monkeypatch, task):
    transport(
        monkeypatch,
        lambda _: httpx.Response(401, json={"error": "DO_NOT_EXPOSE_UPSTREAM"}),
    )
    store = Store(tmp_path / "ledger.sqlite")
    with pytest.raises(ProviderError) as caught:
        await RepoProvider(store, "test-only").generate(task, task.files, {}, "cheap")
    assert store.budget("research")["disabled"] is True
    assert "DO_NOT_EXPOSE_UPSTREAM" not in str(caught.value)


@pytest.mark.asyncio
async def test_429_carries_retry_hint_and_retains_its_reservation(
    tmp_path, monkeypatch, task
):
    transport(
        monkeypatch,
        lambda _: httpx.Response(
            429, headers={"Retry-After": "45"}, json={"error": "private upstream body"}
        ),
    )
    store = Store(tmp_path / "ledger.sqlite")
    provider = RepoProvider(store, "test-only")
    reserved = provider.estimate_reservation_usd(task, task.files, {}, "cheap")
    with pytest.raises(ProviderError) as caught:
        await provider.generate(task, task.files, {}, "cheap")
    assert caught.value.http_status == 429 and caught.value.retry_after_s == 45
    assert caught.value.accounting_kind == "retained_reservation"
    assert store.budget("research")["charged_usd"] == reserved
    assert "private upstream body" not in str(caught.value)


@pytest.mark.parametrize(
    "header,expected",
    [
        ("120", 120),
        ("NaN", None),
        ("inf", None),
        ("-2", None),
        ("invalid", None),
        (None, None),
    ],
)
def test_retry_after_rejects_invalid_values_without_shortening_long_waits(
    header, expected
):
    from forgerl.bench.provider import http_error

    assert http_error(429, header).retry_after_s == expected
    assert http_error(401, header).retry_after_s is None
