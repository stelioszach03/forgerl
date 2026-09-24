"""Opt-in v0.3 development harness, not a frozen or evaluated benchmark.

VERIFY uses authored, public supplemental checks. Their authors also wrote the
tasks: this is an additional signal, not independently authored unbiased evidence.
Hidden cases remain final-only and never supply a routing observation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, replace

from . import router, sandbox
from .engine import RepoEpisode, bounded_visible_cases, fingerprint, run_episode
from .tasks import RepoTask, case, public_task

VERSION = "0.3-dev"
PROTOCOL = "forgebench-v0.3-development-public-verify-v1"
FEATURE_VERSION = "forgebench-state-v3-development"


@dataclass(frozen=True)
class VerificationTask:
    task: RepoTask
    verification_cases: tuple[dict, ...]


def _inputs(cases):
    return {json.dumps([c["args"], c.get("kwargs", {})], sort_keys=True) for c in cases}


def validate_spec(spec, allowed_splits=("development",)):
    if spec.task.split not in allowed_splits:
        raise ValueError("This foundation accepts development tasks only")
    if not 1 <= len(spec.verification_cases) <= 24:
        raise ValueError("One to 24 supplemental checks required")
    if len(_inputs(spec.verification_cases)) != len(spec.verification_cases):
        raise ValueError("Supplemental inputs must be unique")
    if _inputs(spec.verification_cases) & _inputs(
        spec.task.public_cases + spec.task.hidden_cases
    ):
        raise ValueError(
            "Supplemental inputs overlap original visible or hidden inputs"
        )
    names = [c["name"] for c in spec.verification_cases]
    if len(set(names)) != len(names):
        raise ValueError("Supplemental names must be unique")
    sandbox.payload(
        spec.task.files, spec.task.entrypoint, list(spec.verification_cases)
    )
    json.dumps(spec.verification_cases, allow_nan=False)


class VerificationEpisode(RepoEpisode):
    allowed_splits = ("development",)

    def __init__(
        self, spec, provider, policy="static_router", *, max_verifications=2, **kwargs
    ):
        validate_spec(spec, self.allowed_splits)
        if type(max_verifications) is not int or max_verifications not in (1, 2):
            raise ValueError("Maximum verifications must be 1 or 2")
        if kwargs.get("artifact") is not None or policy == "adaptive":
            raise ValueError(
                "A v0.3 learned controller is not implemented; v0.2 controller reuse is forbidden"
            )
        self.spec = spec
        self.max_verifications = max_verifications
        self.verification_calls = 0
        self.verification_elapsed_s = 0.0
        self.verified_candidates = {}
        self.verification_attempted = set()
        super().__init__(spec.task, provider, policy=policy, **kwargs)

    def stop_after_visible_success(self):
        return False

    def current_verification(self):
        # Never transfer a verifier signal to a different candidate, including rollback.
        return self.verified_candidates.get(fingerprint(self.files))

    def observation(self):
        state = super().observation()
        verification = self.current_verification()
        state.update(
            feature_version=FEATURE_VERSION,
            verification_passed=verification["passed"] if verification else None,
            verification_total=verification["total"] if verification else None,
            verification_calls=self.verification_calls,
            max_verifications=self.max_verifications,
        )
        return state

    @staticmethod
    def routing_signal(state):
        """Project an observed supplemental failure into the existing heuristic."""
        signal = dict(state)
        if (
            state["verification_passed"] is not None
            and state["verification_passed"] < state["verification_total"]
        ):
            signal["public_total"] += state["verification_total"]
            signal["public_passed"] += state["verification_passed"]
        return signal

    def legal_actions(self, state):
        if state["decisions"] >= state["max_decisions"]:
            return ("stop",)
        actions = list(router.allowed_actions(self.routing_signal(state)))
        # VERIFY consumes a decision/tool budget but no model-call or API budget.
        # It is legal only once per immutable candidate and at most twice overall.
        if (
            state["public_total"]
            and state["public_passed"] == state["public_total"]
            and state["verification_passed"] is None
            and self.verification_calls < self.max_verifications
            and fingerprint(self.files) not in self.verification_attempted
        ):
            actions.insert(0, "verify")
        return tuple(actions)

    def feedback(self, action):
        feedback = super().feedback(action)
        verification = self.current_verification()
        if verification is not None:
            feedback["supplemental_verification"] = {
                "visibility": "public_supplemental",
                "files_sha256": fingerprint(self.files),
                "passed": verification["passed"],
                "total": verification["total"],
                "cases": bounded_visible_cases(verification.get("cases", [])),
                "specification_checks": list(self.spec.verification_cases),
                "note": "Authored public verification checks; not final hidden grading.",
            }
        return feedback

    async def step(self, action, selection_source="development_heuristic"):
        if action != "verify":
            return await super().step(action, selection_source)
        if not self.started_flag:
            await self.start()
        if self.terminal:
            return self.observation()
        state = self.observation()
        if action not in self.legal_actions(state):
            raise ValueError("Illegal bounded verification action")
        self.decisions += 1
        self.verification_calls += 1
        self.tool_calls += 1
        candidate_hash = fingerprint(self.files)
        self.verification_attempted.add(candidate_hash)
        await self.emit(
            "decision",
            "Routing decision",
            {
                "action": "verify",
                "selection_source": selection_source,
                "state": state,
                "policy": self.policy,
            },
        )
        await self.emit(
            "tool_call",
            "Run supplemental public verification",
            {
                "tool": "sandbox.evaluate",
                "visibility": "public_supplemental",
                "files_sha256": candidate_hash,
                "orchestrated": True,
                "cases": list(self.spec.verification_cases),
                "inference_cost_usd": 0.0,
                "note": "No provider request; local sandbox compute is not monetized in API cost.",
            },
        )
        verification_task = replace(
            self.task, public_cases=self.spec.verification_cases
        )
        started = time.monotonic()
        try:
            result = await asyncio.to_thread(
                self.evaluator, verification_task, dict(self.files), False
            )
        except Exception as exc:
            elapsed = time.monotonic() - started
            self.verification_elapsed_s += elapsed
            await self.emit(
                "error",
                "Supplemental verification unavailable",
                {
                    "visibility": "public_supplemental",
                    "files_sha256": candidate_hash,
                    "elapsed_s": elapsed,
                    "error": str(exc),
                },
            )
            raise
        # Check before accepting any delayed result. Execution never mutates the harness files.
        if fingerprint(self.files) != candidate_hash:
            raise RuntimeError("Candidate changed during verification")
        self.verified_candidates[candidate_hash] = result
        self.verification_elapsed_s += result.get("elapsed_s", 0.0)
        if result["passed"] < result["total"]:
            self.record_failure("verification:public_supplemental_fail")
        await self.emit(
            "tests",
            "Supplemental public verification completed",
            {
                **result,
                "visibility": "public_supplemental",
                "files_sha256": candidate_hash,
            },
        )
        if self.decisions >= self.max_decisions:
            self.terminal, self.stop_reason = True, "step_budget"
        self.transitions.append(
            {
                "task_id": self.task.id,
                "split": self.task.split,
                "action": "verify",
                "state": state,
                "next_state": self.observation(),
                "cost_usd": 0.0,
                "verification_elapsed_s": result.get("elapsed_s"),
                "terminal": self.terminal,
            }
        )
        return self.observation()

    def result(self):
        result = super().result()
        verification = self.current_verification()
        disagreement = None
        disagreement_direction = None
        if (
            result["status"] == "completed"
            and result["heldout_passed"] is not None
            and verification is not None
        ):
            verifier_accepted = verification["passed"] == verification["total"]
            disagreement = verifier_accepted != result["solved"]
            if disagreement:
                disagreement_direction = (
                    "missed_failure" if verifier_accepted else "false_rejection"
                )
        result.update(
            version=VERSION,
            protocol=PROTOCOL,
            development_only=True,
            verification_calls=self.verification_calls,
            verification_passed=verification["passed"] if verification else None,
            verification_total=verification["total"] if verification else None,
            verification_elapsed_s=round(self.verification_elapsed_s, 6),
            verification_inference_cost_usd=0.0,
            verification_grader_disagreement=disagreement,
            verification_grader_disagreement_direction=disagreement_direction,
        )
        result["evidence"]["maximum_verification_calls"] = self.max_verifications
        result["evidence"]["verification"] = (
            "Additional public author-written checks; no independent-author or unbiased-oracle claim. Hidden grading remains final-only."
        )
        return result


async def run_verification_episode(episode, selector=None):
    def choose(state):
        if selector:
            return selector(state)
        legal = episode.legal_actions(state)
        if "verify" in legal:
            return {"action": "verify", "source": "development_verify_on_green"}
        return router.choose_action(episode.policy, episode.routing_signal(state))

    return await run_episode(episode, selector=choose)


def development_tasks():
    """Two transparent integration fixtures, not a v0.3 evaluation split."""
    conversion = "def to_celsius(value):\n    return (value - 32) * 5 / 9\n"
    temperatures = {
        "conversion.py": conversion,
        "service.py": "from conversion import to_celsius\ndef run(request):\n    return to_celsius(request['fahrenheit'])\n",
    }
    temperature = RepoTask(
        id="dev-temperature-offset",
        title="Preserve signed temperature conversion",
        family="development_temperature",
        split="development",
        category="bug_fix",
        difficulty="development",
        summary="Convert signed Fahrenheit readings to Celsius using the stated affine conversion.",
        description="Return (fahrenheit - 32) * 5 / 9 for a numeric Fahrenheit reading. Negative values are valid signed measurements, not magnitudes. Do not mutate the input. This is an authored development fixture.",
        files={
            **temperatures,
            "conversion.py": conversion.replace("value - 32", "value + 32"),
        },
        reference_files=temperatures,
        entrypoint="service:run",
        public_cases=(
            case("freezing", {"fahrenheit": 32}, 0),
            case("boiling", {"fahrenheit": 212}, 100),
        ),
        hidden_cases=(
            case("heldout-cold", {"fahrenheit": -4}, -20),
            case("heldout-warm", {"fahrenheit": 77}, 25),
        ),
        allowed_edit_files=tuple(temperatures),
        success_criterion="All original visible and final held-out checks pass. Supplemental verifier outcomes are reported separately, with the same success criterion for every policy.",
        tags=("authored", "development-only", "public-verification"),
    )
    tokens = "def unique_tokens(values):\n    seen = set()\n    result = []\n    for value in values:\n        key = value.casefold()\n        if key not in seen:\n            seen.add(key)\n            result.append(value)\n    return result\n"
    identifiers = {
        "tokens.py": tokens,
        "service.py": "from tokens import unique_tokens\ndef run(request):\n    return unique_tokens(request['values'])\n",
    }
    identifier = RepoTask(
        id="dev-unicode-identifiers",
        title="Deduplicate Unicode identifiers while preserving order",
        family="development_identifiers",
        split="development",
        category="bug_fix",
        difficulty="development",
        summary="Use Unicode case folding while preserving each first original spelling.",
        description="Deduplicate string identifiers by Unicode str.casefold equality, preserving input order and first original spelling. Empty strings are valid. Do not mutate the input. Lowercasing is not a substitute for casefold. This is an authored development fixture.",
        files={
            **identifiers,
            "tokens.py": tokens.replace("key = value.casefold()", "key = value"),
        },
        reference_files=identifiers,
        entrypoint="service:run",
        public_cases=(
            case("ascii", {"values": ["A", "a", "B"]}, ["A", "B"]),
            case("empty", {"values": []}, []),
        ),
        hidden_cases=(
            case("heldout-ligature", {"values": ["ﬂ", "fl", "X"]}, ["ﬂ", "X"]),
            case("heldout-blank", {"values": ["", "", "z"]}, ["", "z"]),
        ),
        allowed_edit_files=tuple(identifiers),
        success_criterion=temperature.success_criterion,
        tags=temperature.tags,
    )
    return (
        VerificationTask(
            temperature,
            (
                case("verify-negative", {"fahrenheit": -40}, -40),
                case("verify-zero", {"fahrenheit": 0}, -160 / 9),
            ),
        ),
        VerificationTask(
            identifier,
            (
                case(
                    "verify-sharp-s",
                    {"values": ["Straße", "STRASSE", "q"]},
                    ["Straße", "q"],
                ),
                case("verify-sigma", {"values": ["Σ", "ς", "σ"]}, ["Σ"]),
            ),
        ),
    )


def draft_plan():
    specs = development_tasks()
    manifest = []
    for spec in specs:
        validate_spec(spec)
        manifest.append(
            {
                **public_task(spec.task, include_cases=True),
                "reference_files": spec.task.reference_files,
                "hidden_cases": spec.task.hidden_cases,
                "verification_cases": spec.verification_cases,
            }
        )
    return {
        "version": VERSION,
        "protocol": PROTOCOL,
        "status": "development_only_not_preregistered",
        "frozen": False,
        "inference_enabled": False,
        "task_count": len(specs),
        "completed_evaluation_episodes": 0,
        "task_manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "maximum_verification_calls": 2,
        "verification_access": "Same supplemental verifier and budgets for every future compared policy; policy-specific use is allowed.",
        "missing_before_freeze": [
            "Independent repository-family expansion",
            "External task provenance and license review",
            "Simpler learned baseline",
            "Final estimands, budgets and predeclared analysis",
        ],
    }
