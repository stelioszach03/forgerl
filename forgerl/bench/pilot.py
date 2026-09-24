"""Prospective v0.3 pilot, separate from the released v0.2 benchmark.

The two learned selectors transfer historical train-only action values. VERIFY
has no training support and is a shared explicit heuristic, never called learned.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import subprocess
from pathlib import Path

from . import router
from .engine import run_episode, utc_now
from .pilot_catalog import fresh_specs, manifest_hash, prior_development_tasks
from .study import CappedProvider, Writer, digest, source_manifest
from .support_audit import audit_rows, audit_studies
from .tasks import task_manifest_hash
from .v03 import VerificationEpisode
from ..provider import BudgetExceeded

VERSION = "0.3-pilot1"
PROTOCOL = "forgebench-v0.3-prospective-transfer-pilot1"
POLICIES = (
    "strong_only",
    "cheap_only",
    "escalate_on_failure",
    "static_router",
    "adaptive",
    "supervised_cost",
)
SOURCE_SEEDS = (17, 29, 43)


def fit_supervised(rows):
    """Observed discounted return regression, no bootstrapping/counterfactuals."""
    audit_rows(rows)
    buckets, episode = {}, []
    for row in rows:
        if episode and row["task_id"] != episode[0]["task_id"]:
            raise ValueError("Incomplete training episode boundary")
        episode.append(row)
        if not row["terminal"]:
            continue
        target = 0.0
        for observed in reversed(episode):
            target = observed["reward"] + 0.9 * target
            key = router.encode_state(observed["state"])
            buckets.setdefault(key, {}).setdefault(observed["action"], []).append(
                target
            )
        episode = []
    if episode:
        raise ValueError("Unterminated training episode")
    return {
        "algorithm": "observed_discounted_return_cell_means",
        "feature_version": router.FEATURE_VERSION,
        "trained": len(rows) >= 12,
        "values": {
            k: {a: sum(v) / len(v) for a, v in group.items()}
            for k, group in buckets.items()
        },
        "action_counts": {
            k: {a: len(v) for a, v in group.items()} for k, group in buckets.items()
        },
        "training_digest": digest(rows),
        "gamma": 0.9,
        "cost_weight": 5.0,
        "target": "discounted sum of logged rewards (terminal actual success minus 5 * actual accounted action cost)",
        "counterfactual_labels": False,
        "importance_weighting": False,
        "selection_bias": "Only completed historical training episodes; absent actions are unsupported, not negative labels.",
        "verify_support": 0,
        "verify_selection": "shared deterministic verify-on-visible-green",
    }


def fit_controllers(studies):
    """Read exactly training transitions/manifests; never evaluation trajectories."""
    audit = audit_studies(studies)
    rows = []
    for _, directory in studies:
        rows.extend(
            json.loads(line)
            for line in (Path(directory) / "transitions.jsonl").read_text().splitlines()
            if line.strip()
        )
    result = {
        "kind": "frozen_observational_transfer_controllers",
        "version": VERSION,
        "training_catalog_sha256": task_manifest_hash(),
        "training_inputs": audit["inputs"],
        "training_support": audit,
        "fitted_q": router.fit_q(rows, gamma=0.9, iterations=100, min_samples=12),
        "supervised_cost": fit_supervised(rows),
        "evaluation_used_for_fit": False,
        "verify_support": 0,
    }
    result["sha256"] = digest(result)
    return result


def choose_supervised(state, artifact):
    key = router.encode_state(state)
    values = artifact.get("values", {}).get(key, {})
    counts = artifact.get("action_counts", {}).get(key, {})
    supported = [
        action
        for action in router.allowed_actions(state)
        if counts.get(action, 0) > 0
        and type(values.get(action)) in (int, float)
        and math.isfinite(values[action])
    ]
    if (
        artifact.get("trained")
        and artifact.get("feature_version") == router.FEATURE_VERSION
        and supported
    ):
        return {
            "action": max(
                supported, key=lambda a: (values[a], -router.ACTIONS.index(a))
            ),
            "source": "learned_supervised_cost",
        }
    return {"action": router.static_action(state), "source": "heuristic_fallback"}


class PilotEpisode(VerificationEpisode):
    allowed_splits = ("validation", "test", "external")

    def __init__(self, spec, provider, policy, *, controllers=None, **kwargs):
        if policy not in POLICIES:
            raise ValueError("Unknown pilot policy")
        # The development harness rejects learned artifact reuse. This subclass
        # owns explicit historical-transfer selection, rather than presenting a
        # v0.2 artifact as a trained VERIFY policy.
        super().__init__(spec, provider, policy="static_router", **kwargs)
        self.policy = policy
        self.controllers = controllers or {}

    def observation(self):
        state = super().observation()
        state["feature_version"] = "forgebench-state-v3-pilot1"
        return state

    def select(self, state):
        legal = self.legal_actions(state)
        if "verify" in legal:
            return {"action": "verify", "source": "shared_verify_on_visible_green"}
        signal = self.routing_signal(state)
        if self.policy == "supervised_cost":
            selected = choose_supervised(
                signal, self.controllers.get("supervised_cost", {})
            )
        else:
            selected = router.choose_action(
                self.policy, signal, self.controllers.get("fitted_q")
            )
        if selected["action"] not in legal:
            raise ValueError("Pilot selector violated legal action mask")
        return selected

    async def step(self, action, selection_source="pilot"):
        if selection_source == "learned_supervised_cost":
            self.learned_decisions += 1
        return await super().step(action, selection_source)

    def result(self):
        result = super().result()
        result.update(
            version=VERSION,
            protocol=PROTOCOL,
            development_only=False,
            evidence_scope="prospective_pilot_not_full_v03",
            controllers_sha256=self.controllers.get("sha256"),
            verification_policy="shared deterministic rule; not learned",
        )
        return result


def all_specs(include_external=True):
    specs = list(fresh_specs())
    if include_external:
        from .pilot_external import external_specs

        specs.extend(external_specs())
    return tuple(specs)


def task_digest():
    from .pilot_external import external_manifest

    return digest(
        {
            "authored": manifest_hash(),
            "external": external_manifest(),
            "old_catalog": task_manifest_hash(),
            "old_split": "development_only",
        }
    )


def plan(controllers=None):
    specs = all_specs()
    order = []
    for spec in sorted(specs, key=lambda s: s.task.id):
        policies = list(POLICIES)
        random.Random(
            17 + int(hashlib.sha256(spec.task.id.encode()).hexdigest()[:8], 16)
        ).shuffle(policies)
        order.extend(
            {
                "task_id": spec.task.id,
                "family": spec.task.family,
                "split": spec.task.split,
                "policy": p,
                "seed": 17,
            }
            for p in policies
        )
    return {
        "version": VERSION,
        "protocol": PROTOCOL,
        "status": "draft_pending_review_and_freeze",
        "frozen": False,
        "inference_enabled": False,
        "prior_inspected_development_families": len(
            {t.family for t in prior_development_tasks()}
        ),
        "fresh_authored_families": 8,
        "fresh_validation_families": 2,
        "fresh_test_families": 6,
        "fresh_authored_tasks": 24,
        "external_source_derived_tasks": len(specs) - 24,
        "task_manifest_sha256": task_digest(),
        "controllers_sha256": controllers.get("sha256") if controllers else None,
        "seed": 17,
        "policies": list(POLICIES),
        "study_order": order,
        "planned_episodes": len(order),
        "maximum_model_calls": 6,
        "maximum_decisions": 10,
        "maximum_verifications": 2,
        "maximum_tokens_per_episode": 100000,
        "maximum_cost_per_episode_usd": 1.0,
        "study_cost_cap_usd": 1.0,
        "rate_limit_retries": 2,
        "models": {"cheap": "openai/gpt-oss-20b", "strong": "openai/gpt-oss-120b"},
        "provider": "coreweave/fp4",
        "fallbacks": False,
        "temperature": 0.2,
        "max_output_tokens": 4096,
        "training": "Existing v0.2 train split only, completed graded training episodes from seeds17/29/43; validation/test never read for fitting.",
        "verify": "All policies use the same deterministic verify-on-visible-green rule; not learned because historical action support is zero.",
        "primary_estimands": [
            "family-weighted task success on 6 fresh authored test families",
            "family-weighted accounted API cost per attempted test episode",
        ],
        "secondary": [
            "per-task and per-family paired differences",
            "graded-only sensitivity explicitly conditional on provider availability",
            "supplemental failures caught, verification calls/time, repaired after observed supplemental failure, final-grader disagreement",
            "learned/fallback decision coverage",
            "latency,tokens,tool calls,regressions,unnecessary-edit proxy",
        ],
        "analysis": "Descriptive pilot; report all six policies and all pairwise learned-baseline contrasts. No significance claims or population CI with six authored clusters. Validation and source-derived external track reported separately; no tuning or pooling.",
        "missingness": "Provider/infrastructure failure remains in attempted denominator; unattempted budget-stop episodes remain missing, never fabricated failures or selective replacements.",
        "limitations": [
            "Single seed, authored miniature programs, correlated variants, author-correlated verifier/grader, historical observational support without logged propensities, no learned VERIFY, no fresh model training, hosted checkpoint not pinned beyond provider/model/quantization.",
            "External track uses licensed source-derived artificial mutations and authored checks, not real upstream bug-fix issues or SWE-bench.",
        ],
    }


def runtime_manifest():
    result = source_manifest()
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "scripts/pilot_forgebench.py",
        "forgerl/bench/boltons_source.json",
    ):
        result["files"][relative] = hashlib.sha256(
            (root / relative).read_bytes()
        ).hexdigest()
    result["sha256"] = digest(result["files"])
    return result


def verify_source_commit(commit):
    """Every captured runtime byte must exist unchanged in the reviewed commit."""
    root = Path(__file__).resolve().parents[2]
    for relative, expected in runtime_manifest()["files"].items():
        result = subprocess.run(
            ["git", "show", f"{commit}:{relative}"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode or hashlib.sha256(result.stdout).hexdigest() != expected:
            raise ValueError(f"Runtime file is not frozen in source commit: {relative}")


def validate_fixture_receipt(receipt):
    specs = {s.task.id for s in all_specs()}
    rows = receipt.get("checks", [])
    if (
        receipt.get("status") != "passed"
        or receipt.get("task_manifest_sha256") != task_digest()
        or receipt.get("backend") != "rootless-docker-existing-isolated-executor"
        or receipt.get("candidate_host_execution") is not False
        or receipt.get("tasks") != len(specs)
        or len(rows) != len(specs)
        or {r.get("task_id") for r in rows} != specs
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", receipt.get("sandbox_image") or "")
    ):
        raise ValueError(
            "Real sandbox fixture verification must match catalog and image"
        )
    for row in rows:
        checks = row.get("checks", {})
        if set(checks) != {
            "starter_visible",
            "reference_visible",
            "reference_hidden",
            "reference_supplemental",
        } or not row.get("passed"):
            raise ValueError("Incomplete fixture suite receipt")
        for name, result in checks.items():
            if result.get("execution_error") or not result.get("total"):
                raise ValueError("Fixture execution must complete")
            if name == "starter_visible":
                if not 0 <= result["passed"] < result["total"]:
                    raise ValueError("Starter must fail visible checks")
            elif result["passed"] != result["total"]:
                raise ValueError("Reference must pass every fixture suite")


def freeze_document(controllers, *, commit, fixture_receipt, provider_snapshot):
    """Called explicitly only after human/root review; never on import/plan."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        raise ValueError("An immutable reviewed source commit is required")
    validate_fixture_receipt(fixture_receipt)
    if os.environ.get("FORGEBENCH_EVALUATED_IMAGE") != fixture_receipt["sandbox_image"]:
        raise ValueError("Runtime image must match verified fixture image")
    verify_source_commit(commit)
    endpoint_rows = provider_snapshot.get("endpoint_records", [])
    endpoints = [r.get("selected_endpoint", {}) for r in endpoint_rows]
    if (
        len(endpoints) != 2
        or {e.get("model_id") for e in endpoints}
        != {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}
        or any(
            e.get("tag") != "coreweave/fp4"
            or e.get("quantization") != "fp4"
            or e.get("status") != 0
            or not {"seed", "temperature", "max_tokens"}.issubset(
                e.get("supported_parameters", [])
            )
            for e in endpoints
        )
    ):
        raise ValueError(
            "Current public provider snapshot must support frozen settings"
        )
    config = plan(controllers)
    config.update(
        status="frozen_prospective_pilot", frozen=True, inference_enabled=True
    )
    document = {
        "frozen_at": utc_now(),
        "source_commit": commit,
        "configuration": config,
        "configuration_sha256": digest(config),
        "source_manifest": runtime_manifest(),
        "controllers": controllers,
        "fixture_receipt": fixture_receipt,
        "provider_snapshot": provider_snapshot,
    }
    document["sha256"] = digest(document)
    return document


def verify_freeze(document):
    copy = dict(document)
    claimed = copy.pop("sha256", None)
    if digest(copy) != claimed:
        raise ValueError("Frozen document hash mismatch")
    config = document["configuration"]
    current = plan(document["controllers"])
    current.update(
        status="frozen_prospective_pilot", frozen=True, inference_enabled=True
    )
    if current != config or digest(config) != document["configuration_sha256"]:
        raise ValueError("Pilot configuration/catalog changed after freeze")
    if runtime_manifest()["sha256"] != document["source_manifest"]["sha256"]:
        raise ValueError("Pilot runtime source changed after freeze")
    validate_fixture_receipt(document["fixture_receipt"])
    if (
        os.environ.get("FORGEBENCH_EVALUATED_IMAGE")
        != document["fixture_receipt"]["sandbox_image"]
    ):
        raise ValueError("Runtime image changed after freeze")
    controllers = dict(document["controllers"])
    controller_hash = controllers.pop("sha256", None)
    if digest(controllers) != controller_hash:
        raise ValueError("Frozen controller hash mismatch")


async def run_pilot(provider, output, frozen):
    verify_freeze(frozen)
    metadata = provider.metadata()
    if (
        metadata.get("provider") != "openrouter"
        or metadata.get("routing", {}).get("only") != ["coreweave/fp4"]
        or metadata.get("routing", {}).get("quantizations") != ["fp4"]
        or metadata.get("routing", {}).get("allow_fallbacks") is not False
        or metadata.get("temperature") != 0.2
        or {
            (m.get("role"), m.get("id"), m.get("max_output_tokens"))
            for m in metadata.get("models", [])
        }
        != {
            ("cheap", "openai/gpt-oss-20b", 4096),
            ("strong", "openai/gpt-oss-120b", 4096),
        }
    ):
        raise ValueError("Provider configuration differs from frozen pilot")
    bounded = CappedProvider(provider, 1.0)
    writer = Writer(output)
    config = frozen["configuration"]
    specs = {s.task.id: s for s in all_specs()}
    provenance = {
        "started_at": utc_now(),
        "freeze_sha256": frozen["sha256"],
        "configuration": config,
        "provider": provider.metadata(),
        "budget_before": bounded.start_budget,
        "status": "running",
    }
    writer.write("freeze.json", frozen)
    writer.write("manifest.json", provenance)
    results = []
    try:
        for row in config["study_order"]:
            if bounded.remaining() < 0.001:
                raise BudgetExceeded("Pilot allowance exhausted")
            episode = PilotEpisode(
                specs[row["task_id"]],
                bounded,
                row["policy"],
                controllers=frozen["controllers"],
                seed=17,
                max_steps=6,
                max_decisions=10,
                max_verifications=2,
                max_cost_usd=1.0,
                rate_limit_retries=2,
            )
            episode.event_callback = lambda event, ident=episode.id: writer.append(
                "events.jsonl", {"run_id": ident, "event": event}
            )
            result = await run_episode(episode, selector=episode.select)
            writer.run(result, "pilot_evaluation")
            results.append(result)
            provenance.update(
                completed=len(results), accounted_cost_delta_usd=bounded.spent()
            )
            writer.write("manifest.json", provenance)
            if result["status"] == "budget_exhausted":
                raise BudgetExceeded("Pilot episode or shared allowance exhausted")
    except Exception as exc:
        provenance["stop_reason"] = f"{type(exc).__name__}: {exc}"
    observed = {(r["task_id"], r["policy"]) for r in results}
    missing = [
        r for r in config["study_order"] if (r["task_id"], r["policy"]) not in observed
    ]
    provenance.update(
        status="complete" if not missing else "incomplete",
        finished_at=utc_now(),
        completed=len(results),
        planned=len(config["study_order"]),
        missing=missing,
        accounted_cost_delta_usd=bounded.spent(),
    )
    writer.write("manifest.json", provenance)
    return provenance
