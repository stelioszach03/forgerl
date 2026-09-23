"""Bounded multi-file repair episodes, with exported observable trajectories.

Only authored repository files enter prompts. Hidden grading runs after the last
policy decision. Tool calls here are orchestrated sandbox checks, not autonomous
model function calls; no private reasoning is requested or stored.
"""

from __future__ import annotations
import asyncio
import copy
import difflib
import hashlib
import inspect
import json
import time
import uuid
from datetime import datetime, timezone
from . import router, sandbox
from ..provider import ProviderError, BudgetExceeded
from ..sandbox import SandboxUnavailable, SandboxRejected


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def diff_files(before, after):
    return "".join(
        "".join(
            difflib.unified_diff(
                before[name].splitlines(True),
                after[name].splitlines(True),
                fromfile="a/" + name,
                tofile="b/" + name,
            )
        )
        for name in sorted(before)
        if before[name] != after[name]
    )


def fingerprint(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def bounded_visible_cases(cases, limit_bytes=2048):
    """Keep large actual outputs out of subsequent provider context.

    Full bounded sandbox results remain in the recorded tests event. The model
    gets an explicitly labelled UTF-8 preview rather than an invented value.
    """
    result = []
    for case in cases:
        row = dict(case)
        if "actual" in row:
            encoded = json.dumps(
                row["actual"], ensure_ascii=False, allow_nan=False
            ).encode()
            if len(encoded) > limit_bytes:
                row["actual"] = None
                row["actual_preview"] = encoded[:limit_bytes].decode(
                    "utf-8", errors="ignore"
                )
                row["actual_omitted"] = True
                row["actual_size_bytes"] = len(encoded)
                row["actual_note"] = (
                    "Actual output omitted from model feedback; preview is truncated JSON text, not the complete value."
                )
        result.append(row)
    return result


class RepoEpisode:
    def __init__(
        self,
        task,
        provider,
        policy="adaptive",
        *,
        artifact=None,
        max_steps=6,
        max_decisions=10,
        max_cost_usd=1.0,
        seed=17,
        evaluator=None,
        event_callback=None,
    ):
        if policy not in router.POLICIES and policy != "exploration":
            raise ValueError("Unknown policy")
        if (
            not 1 <= max_steps <= 6
            or not 1 <= max_decisions <= 10
            or not 0 < max_cost_usd <= 5
        ):
            raise ValueError("Episode bounds exceeded")
        self.task, self.provider, self.policy = task, provider, policy
        self.artifact, self.max_steps, self.max_decisions = (
            artifact,
            max_steps,
            max_decisions,
        )
        self.max_cost_usd, self.seed = max_cost_usd, seed
        self.evaluator, self.event_callback = (
            evaluator or sandbox.evaluate,
            event_callback,
        )
        self.id, self.created_at = uuid.uuid4().hex, utc_now()
        self.started = time.monotonic()
        self.files = dict(task.files)
        self.best_files = dict(self.files)
        self.public = {"passed": 0, "total": len(task.public_cases), "cases": []}
        self.best_public = copy.deepcopy(self.public)
        self.hidden = None
        self.public_measured = False
        self.unnecessary_edits = None
        self.attempts = self.decisions = self.rollbacks = self.escalations = 0
        self.retries = self.invalid_responses = 0
        self.max_tokens = 100000
        self.tool_calls = self.regressions = self.tokens = 0
        self.cost_usd, self.improvement = 0.0, 0
        self.current_model, self.last_model_id = "cheap", None
        self.events, self.transitions, self.models, self.failure_labels = [], [], [], []
        self.snapshots = {fingerprint(self.files)}
        self.status, self.stop_reason, self.error = "running", None, None
        self.started_flag = self.terminal = self.finished = False
        self.tokens_complete = True
        self.elapsed_s = None
        self.learned_decisions = self.fallback_decisions = 0
        self.had_visible_failure = False

    async def emit(self, kind, title, data=None):
        event = {
            "seq": len(self.events) + 1,
            "kind": kind,
            "title": title,
            "at": utc_now(),
            "data": data or {},
        }
        self.events.append(event)
        if self.event_callback:
            returned = self.event_callback(event)
            if inspect.isawaitable(returned):
                await returned

    def observation(self):
        return {
            "public_passed": self.public["passed"],
            "public_total": self.public["total"],
            "attempts": self.attempts,
            "max_steps": self.max_steps,
            "decisions": self.decisions,
            "max_decisions": self.max_decisions,
            "budget_remaining_usd": max(0, self.max_cost_usd - self.cost_usd),
            "current_model": self.current_model,
            "improvement": self.improvement,
            "can_rollback": self.public["passed"] < self.best_public["passed"]
            and self.files != self.best_files,
            "rollbacks": self.rollbacks,
            "retries": self.retries,
        }

    async def check(self, hidden=False):
        self.tool_calls += 1
        await self.emit(
            "tool_call",
            "Run isolated held-out checks" if hidden else "Run isolated visible checks",
            {
                "tool": "sandbox.evaluate",
                "visibility": "hidden" if hidden else "public",
                "files_sha256": fingerprint(self.files),
                "orchestrated": True,
            },
        )
        result = await asyncio.to_thread(self.evaluator, self.task, self.files, hidden)
        await self.emit(
            "tests",
            "Held-out grading completed" if hidden else "Visible checks completed",
            result
            if not hidden
            else {
                "passed": result["passed"],
                "total": result["total"],
                "elapsed_s": result.get("elapsed_s"),
                "security": result.get("security"),
                "visibility": "hidden",
                "note": "Final-only grading: no hidden inputs, expected values or case names exported.",
            },
        )
        return result

    async def start(self):
        if self.started_flag:
            return self.observation()
        self.started_flag = True
        await self.emit(
            "prompt",
            "Authored task specification",
            {
                "task_id": self.task.id,
                "description": self.task.description,
                "success_criterion": self.task.success_criterion,
            },
        )
        await self.emit(
            "context",
            "Repository supplied to the repair harness",
            {
                "files": self.files,
                "entrypoint": self.task.entrypoint,
                "note": "Files supplied as context; not a claim of autonomous file inspection.",
            },
        )
        self.public = await self.check()
        self.public_measured = True
        self.best_public = copy.deepcopy(self.public)
        self.had_visible_failure = self.public["passed"] < self.public["total"]
        if not self.had_visible_failure:
            self.terminal, self.stop_reason = True, "visible_tests_already_pass"
        return self.observation()

    def record_failure(self, label):
        if label not in self.failure_labels:
            self.failure_labels.append(label)

    async def step(self, action, selection_source="exploration"):
        if not self.started_flag:
            await self.start()
        if self.terminal:
            return self.observation()
        state = self.observation()
        if action not in router.allowed_actions(state):
            raise ValueError("Illegal bounded routing action")
        self.decisions += 1
        self.learned_decisions += selection_source == "learned_q"
        self.fallback_decisions += selection_source == "heuristic_fallback"
        await self.emit(
            "decision",
            "Routing decision",
            {
                "action": action,
                "selection_source": selection_source,
                "state": state,
                "policy": self.policy,
            },
        )
        prior_cost, prior_passed = self.cost_usd, self.public["passed"]
        if action == "stop":
            self.terminal, self.stop_reason = (
                True,
                "visible_tests_pass"
                if self.public["passed"] == self.public["total"]
                else "controller_stop",
            )
        elif action == "rollback":
            previous = self.files
            self.files, self.public = (
                dict(self.best_files),
                copy.deepcopy(self.best_public),
            )
            self.rollbacks += 1
            self.improvement = self.public["passed"] - prior_passed
            await self.emit(
                "rollback",
                "Restored last best visible checkpoint",
                {
                    "diff": diff_files(previous, self.files),
                    "files_sha256": fingerprint(self.files),
                    "public_passed": self.public["passed"],
                    "note": "Checkpoint selected using visible checks only; no model call.",
                },
            )
        else:
            requested_model = "strong" if action == "escalate" else self.current_model
            # Commit the role switch only when a hosted request actually occurs.
            # Starting the strong baseline is not a cheap-to-strong escalation.
            pending_escalation = (
                action == "escalate"
                and self.attempts > 0
                and self.current_model != "strong"
            )
            feedback = {
                "passed": self.public["passed"],
                "total": self.public["total"],
                "cases": bounded_visible_cases(self.public.get("cases", [])),
                "attempt": self.attempts + 1,
                "action": action,
                "instruction": "Repair the visible failures while preserving currently passing behavior."
                if action == "repair"
                else "Produce a complete candidate using the task specification and visible feedback.",
            }
            try:
                estimator = getattr(self.provider, "estimate_reservation_usd", None)
                if (
                    estimator
                    and estimator(self.task, self.files, feedback, requested_model)
                    > self.max_cost_usd - self.cost_usd + 1e-9
                ):
                    self.status, self.terminal, self.stop_reason = (
                        "budget_exhausted",
                        True,
                        "episode_cost_cap",
                    )
                    await self.emit(
                        "error",
                        "Episode reservation cap reached",
                        {"note": "No provider request was made."},
                    )
                    return self.observation()
                token_bound = getattr(self.provider, "estimate_token_bound", None)
                if (
                    token_bound
                    and self.tokens
                    + token_bound(self.task, self.files, feedback, requested_model)
                    > self.max_tokens
                ):
                    self.status, self.terminal, self.stop_reason = (
                        "budget_exhausted",
                        True,
                        "episode_token_cap",
                    )
                    await self.emit(
                        "error",
                        "Episode token cap reached",
                        {
                            "max_tokens": self.max_tokens,
                            "note": "Conservative input/output bound; no provider request was made.",
                        },
                    )
                    return self.observation()
                builder = getattr(self.provider, "build_messages", None)
                if builder:
                    await self.emit(
                        "prompt",
                        "Outbound provider prompt",
                        {
                            "prompt_messages": builder(
                                self.task, self.files, feedback, requested_model
                            ),
                            "model_role": requested_model,
                        },
                    )
            except ProviderError as exc:
                # A candidate may fit the source limit but exceed the serialized
                # prompt limit. Keep this episode and earlier charges recorded;
                # do not abort the study or make another hosted request.
                self.status, self.terminal, self.stop_reason = (
                    "failed",
                    True,
                    "prompt_preflight_error",
                )
                self.error = str(exc)
                await self.emit(
                    "error",
                    "Provider prompt preflight failed",
                    {
                        "error": self.error,
                        "note": "No additional provider request was made; earlier accounted costs are retained.",
                    },
                )
                return self.observation()
            self.attempts += 1
            if action == "retry" and self.attempts > 1:
                self.retries += 1
                await self.emit(
                    "retry",
                    "Retry using the current model",
                    {"attempt": self.attempts, "model_role": requested_model},
                )
            await self.emit(
                "model",
                "Request bounded repository candidate",
                {
                    "attempt": self.attempts,
                    "model_role": requested_model,
                    "action": action,
                    "files_supplied": list(self.files),
                    "seed_requested": self.seed + self.attempts,
                },
            )
            try:
                generated = await self.provider.generate(
                    self.task,
                    self.files,
                    feedback,
                    requested_model,
                    seed=self.seed + self.attempts,
                    run_id=self.id,
                )
            except (ProviderError, BudgetExceeded, asyncio.CancelledError) as exc:
                self.cost_usd += getattr(exc, "cost_usd", 0)
                request_observed = not isinstance(exc, BudgetExceeded) and (
                    getattr(exc, "cost_usd", 0) > 0
                    or getattr(exc, "request_id", None) is not None
                    or getattr(exc, "response_text", None) is not None
                )
                if request_observed:
                    self.escalations += pending_escalation
                    self.current_model = requested_model
                if getattr(exc, "model", None) and exc.model not in self.models:
                    self.models.append(exc.model)
                if getattr(exc, "model", None):
                    if self.last_model_id and self.last_model_id != exc.model:
                        await self.emit(
                            "model_switch",
                            "Changed hosted model",
                            {"from": self.last_model_id, "to": exc.model},
                        )
                    self.last_model_id = exc.model
                incoming, outgoing = (
                    getattr(exc, "prompt_tokens", None),
                    getattr(exc, "completion_tokens", None),
                )
                if type(incoming) is int and type(outgoing) is int:
                    self.tokens += (
                        getattr(exc, "total_tokens", 0) or incoming + outgoing
                    )
                elif not isinstance(exc, BudgetExceeded):
                    self.tokens_complete = False
                self.status = (
                    "budget_exhausted"
                    if isinstance(exc, BudgetExceeded)
                    else "interrupted"
                    if isinstance(exc, asyncio.CancelledError)
                    else "failed"
                )
                self.stop_reason = (
                    "inference_budget"
                    if isinstance(exc, BudgetExceeded)
                    else "provider_error"
                )
                self.error, self.terminal = str(exc) or "Request cancelled", True
                await self.emit(
                    "error",
                    "Provider request did not produce a candidate",
                    {
                        "error": self.error,
                        "cost_usd": getattr(exc, "cost_usd", 0),
                        "prompt_messages": getattr(exc, "prompt_messages", []),
                        "response_text": getattr(exc, "response_text", None),
                        "model": getattr(exc, "model", None),
                        "request_id": getattr(exc, "request_id", None),
                        "finish_reason": getattr(exc, "finish_reason", None),
                        "provider_id": getattr(exc, "provider_id", None),
                        "provider_reported_cost_usd": getattr(
                            exc, "provider_reported_cost_usd", None
                        ),
                        "request_config": getattr(exc, "request_config", None),
                    },
                )
                if isinstance(exc, asyncio.CancelledError):
                    raise
                if isinstance(exc, BudgetExceeded):
                    self.attempts -= 1  # Reservation rejection made no hosted request.
                elif getattr(exc, "failure_kind", None) == "invalid_candidate":
                    self.invalid_responses += 1
                    self.status, self.terminal, self.error, self.stop_reason = (
                        "running",
                        False,
                        None,
                        None,
                    )
                    self.record_failure("implementation:invalid_candidate")
                    self.improvement = 0
                    if (
                        self.attempts >= self.max_steps
                        or self.decisions >= self.max_decisions
                    ):
                        self.terminal, self.stop_reason = True, "step_budget"
                    if self.invalid_responses >= 3:
                        self.terminal, self.stop_reason = (
                            True,
                            "invalid_response_retry_cap",
                        )
                    self.transitions.append(
                        {
                            "task_id": self.task.id,
                            "split": self.task.split,
                            "action": action,
                            "state": state,
                            "next_state": self.observation(),
                            "cost_usd": self.cost_usd - prior_cost,
                            "terminal": self.terminal,
                        }
                    )
                return self.observation()
            self.escalations += pending_escalation
            self.current_model = requested_model
            self.tokens += (
                getattr(generated, "total_tokens", 0)
                or generated.prompt_tokens + generated.completion_tokens
            )
            self.cost_usd += generated.cost_usd
            if generated.model not in self.models:
                self.models.append(generated.model)
            if self.last_model_id and self.last_model_id != generated.model:
                await self.emit(
                    "model_switch",
                    "Changed hosted model",
                    {"from": self.last_model_id, "to": generated.model},
                )
            self.last_model_id = generated.model
            await self.emit(
                "inference",
                "Actual provider prompt and visible response",
                {
                    "prompt_messages": generated.prompt_messages,
                    "response_text": generated.response_text,
                    "model": generated.model,
                    "prompt_tokens": generated.prompt_tokens,
                    "completion_tokens": generated.completion_tokens,
                    "cost_usd": generated.cost_usd,
                    "provider_elapsed_s": generated.elapsed_s,
                    "request_id": generated.request_id,
                    "finish_reason": generated.finish_reason,
                    "provider_id": getattr(generated, "provider_id", None),
                    "provider_reported_cost_usd": getattr(
                        generated, "provider_reported_cost_usd", None
                    ),
                    "request_config": getattr(generated, "request_config", None),
                    "note": "Provider content only; no private reasoning. Prompt captured with returned response.",
                },
            )
            candidate = dict(self.files)
            candidate.update(generated.files)
            previous = dict(self.files)
            try:
                sandbox.validate_edits(self.task, candidate)
            except SandboxRejected as exc:
                self.improvement = 0
                self.invalid_responses += 1
                self.record_failure("implementation:invalid_candidate")
                await self.emit(
                    "error",
                    "Candidate rejected before execution",
                    {"error": str(exc), "candidate_files": generated.files},
                )
                if self.invalid_responses >= 3:
                    self.terminal, self.stop_reason = True, "invalid_response_retry_cap"
            else:
                self.files = candidate
                patch = diff_files(previous, candidate)
                await self.emit(
                    "patch",
                    "Applied candidate repository edits",
                    {
                        "diff": patch,
                        "files": candidate,
                        "changed_files": [
                            name
                            for name in candidate
                            if candidate[name] != previous[name]
                        ],
                    },
                )
                if fingerprint(candidate) in self.snapshots:
                    self.record_failure("looping:repeated_candidate")
                self.snapshots.add(fingerprint(candidate))
                before_rows = {
                    r["name"]: r["passed"] for r in self.public.get("cases", [])
                }
                self.public = await self.check()
                self.regressions += sum(
                    before_rows.get(r["name"]) is True and not r["passed"]
                    for r in self.public.get("cases", [])
                )
                self.improvement = self.public["passed"] - prior_passed
                if self.improvement < 0:
                    self.record_failure("implementation:visible_regression")
                if self.public.get("execution_error"):
                    self.record_failure("implementation:execution_rejected")
                if self.public["passed"] > self.best_public["passed"]:
                    self.best_files, self.best_public = (
                        dict(self.files),
                        copy.deepcopy(self.public),
                    )
                if (
                    self.public["total"]
                    and self.public["passed"] == self.public["total"]
                ):
                    self.terminal, self.stop_reason = True, "visible_tests_pass"
        if not self.terminal and (
            self.attempts >= self.max_steps or self.decisions >= self.max_decisions
        ):
            self.terminal, self.stop_reason = True, "step_budget"
        self.transitions.append(
            {
                "task_id": self.task.id,
                "split": self.task.split,
                "action": action,
                "state": state,
                "next_state": self.observation(),
                "cost_usd": self.cost_usd - prior_cost,
                "terminal": self.terminal,
            }
        )
        return self.observation()

    async def finish(self):
        if self.finished:
            return self.result()
        self.terminal = True
        self.stop_reason = self.stop_reason or "controller_stop"
        # Infrastructure/provider failure is retained; it is not a model failure label.
        if self.started_flag and self.status == "running":
            try:
                self.hidden = await self.check(hidden=True)
            except SandboxUnavailable as exc:
                self.status, self.error, self.stop_reason = (
                    "failed",
                    str(exc),
                    "sandbox_unavailable",
                )
                await self.emit(
                    "error", "Final grading unavailable", {"error": self.error}
                )
            else:
                self.status = "completed"
                if (
                    self.public["passed"] == self.public["total"]
                    and self.hidden["passed"] < self.hidden["total"]
                ):
                    self.record_failure("verification:visible_pass_hidden_fail")
        if self.status == "completed":
            # Post-decision descriptive proxy only; never exposed to the policy.
            reference_scope = {
                name
                for name in self.task.files
                if self.task.reference_files.get(name) != self.task.files[name]
            }
            edited_scope = {
                name for name in self.files if self.files[name] != self.task.files[name]
            }
            self.unnecessary_edits = len(edited_scope - reference_scope)
        self.finished = True
        self.elapsed_s = round(time.monotonic() - self.started, 6)
        await self.emit(
            "complete",
            "Episode finished",
            {
                "status": self.status,
                "solved": self.result()["solved"],
                "stop_reason": self.stop_reason,
            },
        )
        return self.result()

    def result(self):
        solved = bool(
            self.finished
            and self.status == "completed"
            and self.hidden
            and self.hidden["total"]
            and self.hidden["passed"] == self.hidden["total"]
            and self.public["total"]
            and self.public["passed"] == self.public["total"]
        )
        return {
            "id": self.id,
            "version": "0.2",
            "task_id": self.task.id,
            "task_title": self.task.title,
            "family": self.task.family,
            "split": self.task.split,
            "category": self.task.category,
            "policy": self.policy,
            "seed": self.seed,
            "created_at": self.created_at,
            "status": self.status,
            "solved": solved,
            "public_passed": self.public["passed"] if self.public_measured else None,
            "public_total": self.public["total"],
            "heldout_passed": self.hidden["passed"] if self.hidden else None,
            "heldout_total": len(self.task.hidden_cases),
            "cost_usd": round(self.cost_usd, 8),
            "tokens": self.tokens if self.tokens_complete else None,
            "known_tokens": self.tokens,
            "tokens_complete": self.tokens_complete,
            "elapsed_s": self.elapsed_s
            if self.elapsed_s is not None
            else round(time.monotonic() - self.started, 6),
            "tool_calls": self.tool_calls,
            "steps": self.attempts,
            "attempts": self.attempts,
            "retries": self.retries,
            "invalid_responses": self.invalid_responses,
            "decisions": self.decisions,
            "regressions_introduced": self.regressions,
            "unnecessary_edits": self.unnecessary_edits,
            "success_after_repair": solved and self.attempts > 1,
            "escalations": self.escalations,
            "rollbacks": self.rollbacks,
            "failure_labels": self.failure_labels,
            "learned_decisions": self.learned_decisions,
            "fallback_decisions": self.fallback_decisions,
            "model_ids": self.models,
            "initial_files": dict(self.task.files),
            "final_files": dict(self.files),
            "diff": diff_files(self.task.files, self.files),
            "events": self.events,
            "error": self.error,
            "stop_reason": self.stop_reason,
            "evidence": {
                "cost_basis": self.provider.metadata().get("cost_basis")
                if hasattr(self.provider, "metadata")
                else "Test provider; not real economic evidence",
                "tool_calls": "Orchestrated sandbox evaluations, including baseline and final grading",
                "unnecessary_edits": "Post-decision reference-scope proxy: changed files outside the supplied reference patch scope. Alternative valid edits can be counted; not a minimality oracle.",
                "failure_labels": "Observed proxies, not causal model reasoning claims",
                "model_weights_updated": False,
                "hidden_grading": "After all policy decisions; never feedback",
                "maximum_model_calls": self.max_steps,
                "maximum_decisions": self.max_decisions,
                "maximum_tokens": self.max_tokens,
                "maximum_retry_actions": 2,
                "maximum_invalid_responses": 3,
            },
        }


async def run_episode(episode, selector=None):
    try:
        await episode.start()
        while not episode.terminal:
            selection = (
                selector(episode.observation())
                if selector
                else router.choose_action(
                    episode.policy, episode.observation(), episode.artifact
                )
            )
            await episode.step(
                selection["action"], selection.get("source", "exploration")
            )
    except SandboxUnavailable as exc:
        episode.status, episode.terminal, episode.stop_reason, episode.error = (
            "failed",
            True,
            "sandbox_unavailable",
            str(exc),
        )
        await episode.emit(
            "error", "Isolated execution unavailable", {"error": str(exc)}
        )
    return await episode.finish()
