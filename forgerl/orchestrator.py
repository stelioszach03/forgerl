"""Measured repair episodes. Model calls and test executions are never simulated."""

from __future__ import annotations

import asyncio
import copy
import difflib
import inspect
import time
import uuid
from datetime import datetime, timezone

from . import controller, sandbox
from .provider import BudgetExceeded, ProviderError


class Episode:
    def __init__(
        self,
        task,
        provider,
        policy_id="fixed",
        max_steps=3,
        event_callback=None,
        artifact=None,
        seed=0,
    ):
        self.task, self.provider, self.policy_id = task, provider, policy_id
        self.max_steps = min(3, max(1, max_steps))
        self.event_callback = event_callback
        self.artifact, self.seed = artifact, int(seed)
        self.id = uuid.uuid4().hex
        self.created_at = time.time()
        self.started = time.monotonic()
        self.source = task.source.rstrip() + "\n"
        self.attempts = 0
        self.events = []
        self.tokens = 0
        self.cost_usd = 0.0
        self.model_ids = []
        self.public = {"passed": 0, "total": len(task.public_cases), "cases": []}
        self.hidden = None
        self.terminal = False
        self.stop_reason = None
        self.error = None
        self.last_action = "start"
        self.improvement = 0
        self.replan_count = 0
        self.status = "running"
        self._finished = False
        self._started = False
        self.token_accounting_complete = True

    async def emit(self, kind, title, message="", data=None):
        event = {
            "seq": len(self.events) + 1,
            "kind": kind,
            "title": title,
            "message": message,
            "at": datetime.now(timezone.utc).isoformat(),
            "data": data or {},
        }
        self.events.append(event)
        if self.event_callback:
            value = self.event_callback(event)
            if inspect.isawaitable(value):
                await value

    async def start(self):
        if self._started:
            return self.observation()
        self._started = True
        await self.emit(
            "inspect",
            "Inspecting the regression task",
            self.task.title,
            {
                "filename": self.task.filename,
                "family": self.task.family,
                "task_id": self.task.id,
            },
        )
        self.public = await asyncio.to_thread(
            sandbox.evaluate, self.task, self.source, False
        )
        await self.emit(
            "tests",
            "Baseline tests completed",
            f"{self.public['passed']}/{self.public['total']} visible checks passed",
            self.public,
        )
        if self.public["total"] and self.public["passed"] == self.public["total"]:
            self.terminal = True
            self.stop_reason = "visible_tests_already_pass"
        return self.observation()

    def observation(self):
        return {
            "attempts": self.attempts,
            "max_steps": self.max_steps,
            "public_passed": self.public["passed"],
            "public_total": self.public["total"],
            "cost_usd": self.cost_usd,
            "max_cost_usd": 0.5,
            "last_action": self.last_action,
            "improvement": self.improvement,
            "replan_count": self.replan_count,
        }

    def clone(self):
        other = copy.copy(self)
        other.id = uuid.uuid4().hex
        other.events = copy.deepcopy(self.events)
        other.public = copy.deepcopy(self.public)
        other.hidden = copy.deepcopy(self.hidden)
        other.model_ids = list(self.model_ids)
        other.event_callback = None
        return other

    async def step(self, action):
        if not self._started:
            await self.start()
        if self.terminal:
            return self.observation()
        if action not in {"fast", "deliberate", "replan", "stop"}:
            raise ValueError("Unknown controller action")
        selection_source = "baseline"
        if self.policy_id == "adaptive":
            state_key = controller.encode_state(self.observation())
            supported = (
                (self.artifact or {}).get("action_counts", {}).get(state_key, {})
            )
            selection_source = (
                "learned_q" if supported.get(action, 0) > 0 else "heuristic_fallback"
            )
        await self.emit(
            "decision",
            "Controller decision",
            action,
            {
                "action": action,
                "state": self.observation(),
                "policy": self.policy_id,
                "selection_source": selection_source,
            },
        )
        self.last_action = action
        if action == "stop":
            self.terminal = True
            self.stop_reason = "controller_stop"
            return self.observation()
        if self.attempts >= self.max_steps or self.cost_usd >= 0.5:
            self.terminal = True
            self.stop_reason = "episode_budget"
            return self.observation()
        if action == "replan":
            self.replan_count += 1
        self.attempts += 1
        feedback = {
            "passed": self.public["passed"],
            "total": self.public["total"],
            "cases": self.public.get("cases", []),
            "attempt": self.attempts,
        }
        if action == "replan":
            feedback["instruction"] = (
                "Reconsider the approach using only the visible failures."
            )
        await self.emit(
            "model",
            "Requesting a repair",
            action,
            {"attempt": self.attempts, "action": action},
        )
        try:
            generated = await self.provider.generate(
                self.task,
                self.source,
                feedback,
                action,
                self.seed + self.attempts,
                run_id=self.id,
            )
        except asyncio.CancelledError as exc:
            self.cost_usd += getattr(exc, "cost_usd", 0)
            self._failed_tokens(exc)
            self.terminal = True
            self.stop_reason = "request_cancelled"
            self.status = "failed"
            self.error = (
                "The request was cancelled; any outstanding reservation is retained."
            )
            raise
        except BudgetExceeded:
            self.terminal = True
            self.stop_reason = "inference_budget"
            self.status = "budget_exhausted"
            self.error = "The shared inference allowance has been reached."
            await self.emit("error", "Inference paused", self.error)
            raise
        except ProviderError as exc:
            self.cost_usd += exc.cost_usd
            self._failed_tokens(exc)
            self.terminal = True
            self.stop_reason = "provider_error"
            self.status = "failed"
            self.error = str(exc)
            await self.emit(
                "error",
                "Provider request failed",
                self.error,
                {"reserved_cost_usd": exc.cost_usd},
            )
            raise
        self.tokens += generated.prompt_tokens + generated.completion_tokens
        self.cost_usd += generated.cost_usd
        if generated.model not in self.model_ids:
            self.model_ids.append(generated.model)
        previous = self.source
        self.source = generated.source
        delta = "".join(
            difflib.unified_diff(
                previous.splitlines(True),
                self.source.splitlines(True),
                fromfile="before/" + self.task.filename,
                tofile="after/" + self.task.filename,
            )
        )
        await self.emit(
            "patch",
            "Applied model-generated edit",
            generated.summary,
            {
                "diff": delta,
                "model": generated.model,
                "prompt_tokens": generated.prompt_tokens,
                "completion_tokens": generated.completion_tokens,
                "cost_usd": generated.cost_usd,
                "provider_elapsed_s": generated.elapsed_s,
                "request_id": generated.request_id,
                "finish_reason": generated.finish_reason,
                "seed_requested": generated.seed_requested,
            },
        )
        before = self.public["passed"]
        self.public = await asyncio.to_thread(
            sandbox.evaluate, self.task, self.source, False
        )
        self.improvement = self.public["passed"] - before
        await self.emit(
            "tests",
            "Visible tests completed",
            f"{self.public['passed']}/{self.public['total']} checks passed",
            self.public,
        )
        if self.public["total"] and self.public["passed"] == self.public["total"]:
            self.terminal = True
            self.stop_reason = "visible_tests_pass"
        elif self.attempts >= self.max_steps:
            self.terminal = True
            self.stop_reason = "step_budget"
        return self.observation()

    async def finish(self):
        if self._finished:
            return self.result()
        if not self._started:
            await self.start()
        self.terminal = True
        self.stop_reason = self.stop_reason or "controller_stop"
        # Held-out outcomes are final grading only, never returned as model feedback.
        self.hidden = await asyncio.to_thread(
            sandbox.evaluate, self.task, self.source, True
        )
        if self.status == "running":
            self.status = "completed"
        await self.emit(
            "grade",
            "Held-out checks completed",
            f"{self.hidden['passed']}/{self.hidden['total']} held-out checks passed",
            {
                "passed": self.hidden["passed"],
                "total": self.hidden["total"],
                "elapsed_s": self.hidden.get("elapsed_s"),
                "security": self.hidden.get("security"),
                "note": "Held-out cases were not supplied to the language model.",
            },
        )
        self._finished = True
        await self.emit(
            "complete",
            "Run finished",
            self.stop_reason,
            {
                "solved": self.result()["solved"],
                "steps": self.attempts,
                "tokens": self.tokens,
                "cost_usd": self.cost_usd,
            },
        )
        return self.result()

    def _failed_tokens(self, exc):
        incoming, outgoing = (
            getattr(exc, "prompt_tokens", None),
            getattr(exc, "completion_tokens", None),
        )
        if type(incoming) is int and type(outgoing) is int:
            self.tokens += incoming + outgoing
        else:
            self.token_accounting_complete = False

    def result(self):
        hidden = self.hidden or {"passed": None, "total": len(self.task.hidden_cases)}
        solved = bool(
            self._finished
            and self.public["total"]
            and self.hidden
            and hidden["total"]
            and self.public["passed"] == self.public["total"]
            and hidden["passed"] == hidden["total"]
        )
        return {
            "id": self.id,
            "task_id": self.task.id,
            "task_title": self.task.title,
            "family": self.task.family,
            "split": self.task.split,
            "policy": self.policy_id,
            "status": self.status,
            "mode": "recorded",
            "created_at": self.created_at,
            "steps": self.attempts,
            "tokens": self.tokens if self.token_accounting_complete else None,
            "known_tokens": self.tokens,
            "tokens_complete": self.token_accounting_complete,
            "cost_usd": round(self.cost_usd, 6),
            "elapsed_s": round(time.monotonic() - self.started, 3),
            "public_passed": self.public["passed"],
            "public_total": self.public["total"],
            "heldout_passed": hidden["passed"],
            "heldout_total": hidden["total"],
            "solved": solved,
            "stop_reason": self.stop_reason,
            "model_ids": self.model_ids,
            "events": self.events,
            "initial_source": self.task.source,
            "final_source": self.source,
            "diff": "".join(
                difflib.unified_diff(
                    (self.task.source.rstrip() + "\n").splitlines(True),
                    self.source.splitlines(True),
                    fromfile="a/" + self.task.filename,
                    tofile="b/" + self.task.filename,
                )
            ),
            "error": self.error,
            "evidence": {
                "task_origin": "authored regression task",
                "cost_basis": "conservative provider token-rate estimate, not an invoice",
                "model_weights": "frozen hosted models; controller training is separate",
                "grading": "visible and held-out checks; finite coverage, not proof of correctness",
                "seed_requested": self.seed,
                "provider_determinism_guaranteed": False,
                "public": {
                    "passed": self.public["passed"],
                    "total": self.public["total"],
                    "cases": [
                        {
                            "name": c["name"],
                            "passed": c["passed"],
                            "error": c.get("error"),
                        }
                        for c in self.public.get("cases", [])
                    ],
                },
                "heldout": {"passed": hidden["passed"], "total": hidden["total"]},
            },
        }


async def run_episode(episode):
    await episode.start()
    while not episode.terminal:
        policy = episode.policy_id
        if policy in ("deliberate-only", "fixed-deliberate"):
            action = "deliberate"
        else:
            action = controller.choose_action(
                policy, episode.observation(), episode.artifact
            )
        await episode.step(action)
    return await episode.finish()
