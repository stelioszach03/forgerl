"""Separate, opt-in proprietary reference treatment; never a primary-study profile.

The fixed URL/model/provider and rates below are checked against the public
catalog again before execution. This module does not read credentials on import.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from pathlib import Path

import httpx

from .provider import (
    RepoProvider,
    RepoResult,
    InvalidCandidate,
    MAX_RESPONSE_BYTES,
    extract_files,
)
from .engine import RepoEpisode, run_episode, utc_now
from .study import CappedProvider, Writer, digest, summarize, public_summary
from .tasks import task_manifest_hash
from ..provider import ProviderError, BudgetExceeded

MODEL = "openai/gpt-4.1"
PROVIDER_TAG = "openai"
PROVIDER_NAME = "OpenAI"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
CATALOG_URL = "https://openrouter.ai/api/v1/models/openai/gpt-4.1/endpoints"
SOURCE_URLS = [
    CATALOG_URL,
    "https://openrouter.ai/openai/gpt-4.1",
    "https://openrouter.ai/docs/guides/routing/provider-selection",
    "https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion",
]
INPUT_RATE = 2.0
OUTPUT_RATE = 8.0
PROTOCOL = "forgebench-v0.2-post-primary-reference-gpt41-seed17"
VERSION = "0.2-reference"
TASK_HASH = "ccb6b8e3996e067e24ecfb4b2f14d6ffb543380b10acb7bcfbc4f19d6b6f116b"
ROUTING = {
    "only": [PROVIDER_TAG],
    "order": [PROVIDER_TAG],
    "allow_fallbacks": False,
    "require_parameters": True,
    "max_price": {"prompt": INPUT_RATE, "completion": OUTPUT_RATE},
}
COST_BASIS = "OpenRouter reported usage.cost, rounded upward to durable microUSD; uncertain requests retain their price-ceiling reservation. Purchase fees excluded."


def validate_catalog(data):
    """Reject unavailable/mispriced/unsupported fixed treatment before paid work."""
    model = data.get("data") if isinstance(data, dict) else None
    if not isinstance(model, dict) or model.get("id") != MODEL:
        raise ProviderError("Reference catalog model identity mismatch")
    matches = [
        row
        for row in model.get("endpoints", [])
        if isinstance(row, dict)
        and row.get("tag") == PROVIDER_TAG
        and row.get("provider_name") == PROVIDER_NAME
        and row.get("model_id") == MODEL
    ]
    if len(matches) != 1:
        raise ProviderError(
            "The exact reference provider endpoint is unavailable or ambiguous"
        )
    selected = matches[0]
    if selected.get("status") != 0:
        raise ProviderError("The fixed reference endpoint is not currently available")
    try:
        prompt = float(selected["pricing"]["prompt"])
        completion = float(selected["pricing"]["completion"])
        supported = set(selected["supported_parameters"])
        if not all(math.isfinite(rate) and rate >= 0 for rate in (prompt, completion)):
            raise ValueError("invalid pricing")
        if prompt > INPUT_RATE / 1e6 or completion > OUTPUT_RATE / 1e6:
            raise ValueError("price ceiling exceeded")
        if not {"seed", "max_tokens", "response_format", "temperature"} <= supported:
            raise ValueError("required parameters missing")
        if selected.get("max_completion_tokens", 0) < 4096:
            raise ValueError("completion limit unavailable")
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderError(
            "Reference catalog does not satisfy the frozen pricing/parameter contract"
        ) from exc
    return {
        "verified_at": utc_now(),
        "source_url": CATALOG_URL,
        "catalog_sha256": digest(data),
        "model_id": MODEL,
        "endpoint": selected,
    }


async def verify_catalog():
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        async with client.stream("GET", CATALOG_URL) as response:
            if response.status_code != 200:
                raise ProviderError("Reference catalog cannot be verified")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 100000:
                    raise ProviderError(
                        "Reference catalog exceeded its bounded response limit"
                    )
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ProviderError("Reference catalog returned invalid JSON") from exc
    return validate_catalog(data)


class ReferenceProvider(RepoProvider):
    """Fixed GPT-4.1/OpenAI reference with the original durable ledger contract."""

    def __init__(self, store, api_key):
        super().__init__(store, api_key, bucket="research", profile="openrouter")
        self.profile = "openrouter-reference-gpt41"
        self.config = {
            "cheap": {"model": MODEL, "endpoint": ENDPOINT},
            "strong": {"model": MODEL, "endpoint": ENDPOINT},
            "input_rate": INPUT_RATE,
            "output_rate": OUTPUT_RATE,
            "routing": ROUTING,
            "cost_basis": COST_BASIS,
        }

    def metadata(self):
        return {
            "provider": self.profile,
            "models": [
                {"role": "reference", "id": MODEL, "max_output_tokens": self.max_tokens}
            ],
            "fixed_provider_tag": PROVIDER_TAG,
            "expected_response_provider": PROVIDER_NAME,
            "cost_basis": COST_BASIS,
            "routing": ROUTING,
            "temperature": 0.2,
            "seed_support": "requested; no determinism guarantee",
            "weights_updated": False,
            "source_urls": SOURCE_URLS,
            "reasoning": "No reasoning requested or retained; only visible message.content is captured",
            "price_ceiling_per_million": {"input": INPUT_RATE, "output": OUTPUT_RATE},
        }

    def build_messages(self, task, files, feedback, action):
        if action != "strong":
            raise ProviderError(
                "The reference treatment supports only its fixed strong role"
            )
        return super().build_messages(task, files, feedback, action)

    async def generate(self, task, files, feedback, action, seed=0, run_id=None):
        messages = self.build_messages(task, files, feedback, action)
        reserved = self._reservation(messages)
        # Reserve in the existing SQLite ledger before constructing any client.
        charge = self.store.reserve("research", MODEL, reserved, run_id=run_id)
        accounted, incoming, outgoing, total = reserved, None, None, None
        response_text, request_id, finish_reason = None, None, None
        provider_id, reported_cost = None, None
        body = {
            "model": MODEL,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 0.2,
            "seed": int(seed),
            "provider": ROUTING,
            "response_format": {"type": "json_object"},
        }
        request_config = {
            key: value for key, value in body.items() if key != "messages"
        }
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(160, connect=12), follow_redirects=False
            ) as client:
                async with client.stream(
                    "POST",
                    ENDPOINT,
                    headers={"Authorization": "Bearer " + self.api_key},
                    json=body,
                ) as response:
                    if response.status_code != 200:
                        if response.status_code in (401, 402, 403):
                            with self.store.transaction() as connection:
                                connection.execute(
                                    "INSERT INTO settings(name,value) VALUES('provider_disabled','provider_access') ON CONFLICT(name) DO NOTHING"
                                )
                        raise ProviderError(
                            f"Reference model provider returned HTTP {response.status_code}"
                        )
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE_BYTES:
                            raise ProviderError(
                                "Reference response exceeds the bounded output limit"
                            )
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get("usage"), dict):
                raise ProviderError("Reference provider returned malformed usage")
            usage = data["usage"]
            incoming, outgoing = (
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
            )
            if (
                type(incoming) is not int
                or type(outgoing) is not int
                or min(incoming, outgoing) < 0
            ):
                incoming = outgoing = None
                raise ProviderError(
                    "Reference provider omitted usable token accounting"
                )
            total = usage.get("total_tokens", incoming + outgoing)
            if type(total) is not int or total < incoming + outgoing:
                total = incoming + outgoing
            reported_cost = usage.get("cost")
            if (
                type(reported_cost) not in (int, float)
                or not math.isfinite(reported_cost)
                or reported_cost < 0
            ):
                reported_cost = None
                raise ProviderError("Reference provider omitted usable cost accounting")
            charged = math.ceil(reported_cost * 1e6)
            self.store.settle(
                charge,
                charged,
                {
                    "prompt_tokens": incoming,
                    "completion_tokens": outgoing,
                    "total_tokens": total,
                },
            )
            charge, accounted = None, charged
            provider_id = (
                data.get("provider") if isinstance(data.get("provider"), str) else None
            )
            request_id = data.get("id") if isinstance(data.get("id"), str) else None
            choices = data.get("choices")
            if (
                not isinstance(choices, list)
                or not choices
                or not isinstance(choices[0], dict)
            ):
                raise ProviderError("Reference provider returned no usable choices")
            choice = choices[0]
            message = choice.get("message")
            response_text = (
                message.get("content") if isinstance(message, dict) else None
            )
            finish_reason = choice.get("finish_reason")
            if provider_id != PROVIDER_NAME:
                raise ProviderError(
                    "Reference provider identity mismatch; candidate excluded"
                )
            if data.get("model") != MODEL:
                raise ProviderError(
                    "Reference model identity mismatch; candidate excluded"
                )
            if not isinstance(response_text, str):
                raise InvalidCandidate(
                    "Reference model returned no visible repository edit"
                )
            candidate = extract_files(response_text, task, files)
            return RepoResult(
                candidate,
                MODEL,
                incoming,
                outgoing,
                charged / 1e6,
                time.monotonic() - started,
                request_id,
                finish_reason,
                messages,
                response_text,
                total,
                provider_id,
                reported_cost,
                request_config,
            )
        except (Exception, asyncio.CancelledError) as exc:
            if charge is not None:
                self.store.settle(charge, None)
            error = (
                exc
                if isinstance(exc, (ProviderError, asyncio.CancelledError))
                else ProviderError(
                    "Reference request failed; its accounted cost is retained"
                )
            )
            error.cost_usd = accounted / 1e6
            error.prompt_tokens, error.completion_tokens, error.total_tokens = (
                incoming,
                outgoing,
                total,
            )
            error.prompt_messages, error.response_text = messages, response_text
            error.model, error.request_id, error.finish_reason = (
                MODEL,
                request_id,
                finish_reason,
            )
            error.provider_id, error.provider_reported_cost_usd = (
                provider_id,
                reported_cost,
            )
            error.request_config, error.elapsed_s = (
                request_config,
                time.monotonic() - started,
            )
            raise error from None


def reference_plan(tasks, max_cost_usd=1.0):
    if (
        type(max_cost_usd) not in (int, float)
        or not math.isfinite(max_cost_usd)
        or not 0 < max_cost_usd <= 1
    ):
        raise ValueError("Reference study cap must be positive and at most $1")
    selected = sorted(
        (task for task in tasks if task.split == "test"), key=lambda task: task.id
    )
    if (
        len(selected) != 10
        or len({task.id for task in selected}) != 10
        or task_manifest_hash() != TASK_HASH
    ):
        raise ValueError(
            "Reference treatment requires the unchanged ten-task v0.2 test split"
        )
    return {
        "protocol": PROTOCOL,
        "version": VERSION,
        "treatment": "post-primary-proprietary-reference",
        "task_ids": [task.id for task in selected],
        "task_manifest_sha256": TASK_HASH,
        "seed": 17,
        "policy": "strong_only",
        "model": MODEL,
        "provider": PROVIDER_NAME,
        "routing": ROUTING,
        "maximum_model_calls": 6,
        "maximum_decisions": 10,
        "maximum_tokens_per_episode": 100000,
        "max_output_tokens": 4096,
        "temperature": 0.2,
        "planned_episodes": 10,
        "study_cost_cap_usd": max_cost_usd,
        "primary_results_pooled": False,
        "selection": "All existing test tasks in lexical order, no outcome-based selection",
        "source_urls": SOURCE_URLS,
        "cost_note": "All ten tasks are planned, not guaranteed within $1. Stop before an unaffordable reservation and retain missing coverage.",
    }


def source_manifest():
    root = Path(__file__).resolve().parents[2]
    paths = list((root / "forgerl" / "bench").rglob("*.py")) + [
        root / "forgerl" / "store.py",
        root / "forgerl" / "sandbox.py",
        root / "sandbox" / "runner.py",
        root / "scripts" / "reference_forgebench.py",
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


async def run_reference(
    tasks,
    provider,
    output,
    *,
    catalog_receipt,
    max_cost_usd=1.0,
    episode_factory=RepoEpisode,
):
    configuration = reference_plan(tasks, max_cost_usd)
    bounded = CappedProvider(provider, max_cost_usd)
    writer = Writer(output)
    sources = source_manifest()
    manifest = {
        "protocol": PROTOCOL,
        "started_at": utc_now(),
        "configuration": configuration,
        "configuration_sha256": digest(configuration),
        "provider": provider.metadata(),
        "catalog_verification": catalog_receipt,
        "source_manifest_sha256": digest(sources),
        "budget_before": bounded.start_budget,
        "status": "running",
    }
    writer.write("plan.json", configuration)
    writer.write("source-manifest.json", sources)
    writer.write("manifest.json", manifest)
    by_id, runs, stop_reason = {task.id: task for task in tasks}, [], None
    for task_id in configuration["task_ids"]:
        episode = episode_factory(
            by_id[task_id],
            bounded,
            "strong_only",
            seed=17,
            max_steps=6,
            max_decisions=10,
        )
        episode.event_callback = lambda event, ident=episode.id: writer.append(
            "events.jsonl", {"run_id": ident, "event": event}
        )
        cancelled = False
        try:
            result = await run_episode(episode)
        except (Exception, asyncio.CancelledError) as exc:
            cancelled = isinstance(exc, asyncio.CancelledError)
            episode.status = "interrupted" if cancelled else "failed"
            episode.terminal, episode.error, episode.stop_reason = (
                True,
                type(exc).__name__,
                "reference_harness_interrupted"
                if cancelled
                else "reference_harness_error",
            )
            result = await episode.finish()
            stop_reason = episode.stop_reason
        result.update(
            {
                "version": VERSION,
                "protocol": PROTOCOL,
                "treatment": "post-primary-proprietary-reference",
            }
        )
        writer.run(result, "reference")
        runs.append(result)
        if result["status"] == "budget_exhausted":
            stop_reason = "reference_budget_cap"
            break
        if stop_reason or cancelled:
            break
    observed = {row["task_id"] for row in runs}
    missing = [
        identifier
        for identifier in configuration["task_ids"]
        if identifier not in observed
    ]
    status = "partial" if missing or stop_reason else "complete"
    manifest.update(
        {
            "finished_at": utc_now(),
            "status": status,
            "stop_reason": stop_reason,
            "budget_after": bounded.store.budget("research"),
            "study_ledger_delta_usd": bounded.spent(),
        }
    )
    summary = next(row for row in summarize(runs, 10) if row["policy"] == "strong_only")
    report = {
        "version": VERSION,
        "protocol": PROTOCOL,
        "treatment": "post-primary-proprietary-reference",
        "status": status,
        "generated_at": utc_now(),
        "model": MODEL,
        "coverage": {"planned": 10, "attempted": len(runs), "missing": missing},
        "summary": summary,
        "runs": [public_summary(row) for row in runs],
        "provenance": manifest,
        "limitations": [
            "Post-primary reference comparator; not part of the frozen primary five-policy study and never pooled into its aggregate.",
            "The test tasks are already part of a known authored benchmark; this is not new held-out discovery or independent router-superiority evidence.",
            "Ten related tasks in two families and one requested seed; no broad ranking or population-level significance claim.",
            "GPT-4.1 is a configured proprietary reference, not asserted newest, frontier or universally stronger.",
            "Price-cap reservations may stop the run before every planned task; unrun tasks stay missing.",
            "Only visible response content is captured; reasoning is neither requested nor stored.",
        ],
    }
    writer.write("reference.json", report)
    writer.write("manifest.json", manifest)
    return report
