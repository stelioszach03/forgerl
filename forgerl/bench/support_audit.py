"""Descriptive support audit of preserved v0.2 training transitions.

No model fitting, inference, evaluation labels, inverse-propensity estimates or
counterfactual outcomes. Missing action propensities are reported, never inferred.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

from . import router
from .study import digest
from .tasks import list_tasks, task_manifest_hash

STATE_KEYS = {
    "public_passed",
    "public_total",
    "attempts",
    "max_steps",
    "decisions",
    "max_decisions",
    "budget_remaining_usd",
    "current_model",
    "improvement",
    "can_rollback",
    "rollbacks",
    "retries",
}


def audit_rows(rows, *, require_propensity=False):
    training = {t.id: t for t in list_tasks() if t.split == "train"}
    support, legal_union = defaultdict(Counter), defaultdict(set)
    tasks, actions, family_counts = Counter(), Counter(), Counter()
    missing, observed, terminal = 0, 0, 0
    for row in rows:
        if row.get("split") != "train" or row.get("task_id") not in training:
            raise ValueError(
                "Audit accepts only catalog-verified training tasks, never validation/test rows"
            )
        for name in ("state", "next_state"):
            state = row.get(name)
            if not isinstance(state, dict) or set(state) != STATE_KEYS:
                raise ValueError(
                    "Expected only declared v0.2 observable state features"
                )
        action = row.get("action")
        legal = router.allowed_actions(row["state"])
        if action not in legal:
            raise ValueError("Observed action was not legal in its recorded state")
        if type(row.get("terminal")) is not bool:
            raise ValueError("Terminal marker must be boolean")
        for key in ("reward", "cost_usd"):
            if type(row.get(key)) not in (int, float) or not math.isfinite(row[key]):
                raise ValueError("Reward and cost must be finite recorded numbers")
        if row["cost_usd"] < 0:
            raise ValueError("Cost cannot be negative")
        probability = row.get("behavior_action_probability")
        if probability is None:
            missing += 1
        elif (
            type(probability) not in (int, float)
            or not math.isfinite(probability)
            or not 0 < probability <= 1
        ):
            raise ValueError(
                "Behavior propensity must be a finite probability in (0, 1]"
            )
        else:
            observed += 1
        state_key = router.encode_state(row["state"])
        support[state_key][action] += 1
        legal_union[state_key].update(legal)
        tasks[row["task_id"]] += 1
        family_counts[training[row["task_id"]].family] += 1
        actions[action] += 1
        terminal += row["terminal"]
    if not tasks:
        raise ValueError("No recorded training transitions")
    if require_propensity and missing:
        raise ValueError(
            "Missing logged behavior propensities; strict off-policy prerequisite check failed"
        )
    states = [
        {
            "encoded_state": state,
            "observed_action_counts": dict(sorted(support[state].items())),
            "legal_action_union": sorted(legal_union[state]),
            "unobserved_legal_actions": sorted(
                legal_union[state] - set(support[state])
            ),
        }
        for state in sorted(support)
    ]
    return {
        "kind": "descriptive_training_support_audit",
        "feature_version": router.FEATURE_VERSION,
        "training_transitions": sum(tasks.values()),
        "training_unique_tasks": len(tasks),
        "training_families": len(family_counts),
        "terminal_transitions": terminal,
        "encoded_states": len(states),
        "observed_state_action_pairs": sum(len(counts) for counts in support.values()),
        "legal_pairs_in_observed_state_bins": sum(
            len(actions) for actions in legal_union.values()
        ),
        "states_with_only_one_observed_action": sum(
            len(counts) == 1 for counts in support.values()
        ),
        "action_counts": dict(sorted(actions.items())),
        "family_transition_counts": dict(sorted(family_counts.items())),
        "task_transition_counts": dict(sorted(tasks.items())),
        "logged_propensities": observed,
        "missing_propensities": missing,
        "propensity_prerequisite_satisfied": missing == 0,
        "causal_or_off_policy_estimate": None,
        "evaluation_rows_used": 0,
        "models_fitted": 0,
        "states": states,
        "interpretation": [
            "This is observed training support, not an estimate of any new policy's performance.",
            "Missing logged propensities block supported importance-weighted off-policy claims from these logs; propensities were not reconstructed from rollout pseudocode.",
            "Missing propensities do not prevent ordinary supervised/observational policy fitting, but such a policy still needs declared training targets and fresh prospective evaluation.",
            "Even complete propensities would not by themselves establish causal identification or sufficient support.",
            "Unchosen actions have no observed counterfactual reward and are never labeled as failed actions.",
            "Counts use the current v0.2 state encoding; legal actions are unioned within each observed bin, not estimates of coverage of all possible states.",
            "Training terminal rewards may include final correctness; no validation/test labels or trajectories were loaded.",
        ],
    }


def audit_studies(studies, *, require_propensity=False):
    rows, inputs, seeds = [], [], set()
    for seed, directory in studies:
        if seed in seeds:
            raise ValueError("Duplicate source seed")
        seeds.add(seed)
        directory = Path(directory)
        manifest_bytes = (directory / "manifest.json").read_bytes()
        transition_bytes = (directory / "transitions.jsonl").read_bytes()
        manifest = json.loads(manifest_bytes)
        configuration = manifest.get("configuration", {})
        if (
            configuration.get("version") != "0.2"
            or configuration.get("seed") != seed
            or manifest.get("configuration_sha256") != digest(configuration)
            or manifest.get("task_manifest_sha256") != task_manifest_hash()
        ):
            raise ValueError(
                "Source study configuration/seed/catalog provenance mismatch"
            )
        source_rows = [
            json.loads(line) for line in transition_bytes.splitlines() if line.strip()
        ]
        declared_ids = set(configuration.get("training_ids", []))
        if any(row.get("task_id") not in declared_ids for row in source_rows):
            raise ValueError("Transition task was not in the declared training plan")
        if manifest.get("training_transitions") != len(source_rows):
            raise ValueError("Transition file does not reconcile with its manifest")
        rows.extend(source_rows)
        inputs.append(
            {
                "source_id": f"forgebench-v02-seed{seed}",
                "seed": seed,
                "protocol": configuration.get("protocol"),
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "transitions_sha256": hashlib.sha256(transition_bytes).hexdigest(),
                "runtime_source_sha256": manifest.get("source_manifest", {}).get(
                    "sha256"
                ),
                "task_manifest_sha256": manifest["task_manifest_sha256"],
                "training_transitions": len(source_rows),
                "source_training_episodes": manifest.get("training_completed"),
                "source_failed_training_episodes": manifest.get("training_failures"),
                "evaluation_artifacts_read": False,
            }
        )
    result = audit_rows(rows, require_propensity=require_propensity)
    result["inputs"] = inputs
    result["audit_source_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    result["transition_selection"] = (
        "Completed graded training episodes only, following the v0.2 fitter; "
        "infrastructure-failed episodes remain in the original archive but do not supply training transitions."
    )
    return result
