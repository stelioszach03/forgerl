"""Observable-state routing with explicit supported-action fitted Q and fallback."""

from __future__ import annotations
import hashlib
import json
import math

POLICIES = (
    "strong_only",
    "cheap_only",
    "escalate_on_failure",
    "static_router",
    "adaptive",
)
ACTIONS = ("retry", "repair", "escalate", "rollback", "stop")
FEATURE_VERSION = "forgebench-state-v2"


def allowed_actions(state):
    if state["public_total"] and state["public_passed"] == state["public_total"]:
        return ("stop",)
    if (
        state["decisions"] >= state["max_decisions"]
        or state["attempts"] >= state["max_steps"]
        or state.get("budget_remaining_usd", 1) <= 0
    ):
        return ("stop",)
    actions = ["retry"] if state.get("retries", 0) < 2 else []
    if state["attempts"]:
        actions.append("repair")
    if state.get("current_model", "cheap") != "strong":
        actions.append("escalate")
    if state.get("can_rollback") and state.get("rollbacks", 0) < 1:
        actions.append("rollback")
    return tuple(actions + ["stop"])


def encode_state(state):
    """No task ID, family, hidden score or reference implementation feature."""
    ratio = state["public_passed"] / max(1, state["public_total"])
    return "|".join(
        map(
            str,
            (
                FEATURE_VERSION,
                "all" if ratio == 1 else "some" if ratio > 0 else "none",
                min(state["attempts"], 3),
                min(max(0, state["max_steps"] - state["attempts"]), 3),
                state.get("current_model", "cheap"),
                "regressed"
                if state.get("improvement", 0) < 0
                else "improved"
                if state.get("improvement", 0) > 0
                else "unchanged",
                bool(state.get("can_rollback")),
                bool(state.get("rollbacks", 0)),
                "low" if state.get("budget_remaining_usd", 1) <= 0.25 else "normal",
            ),
        )
    )


def static_action(state):
    legal = allowed_actions(state)
    if legal == ("stop",):
        return "stop"
    if "rollback" in legal:
        return "rollback"
    if not state["attempts"]:
        return "retry"
    if "escalate" in legal and (
        state.get("improvement", 0) <= 0 or state["attempts"] >= 2
    ):
        return "escalate"
    return "repair"


def choose_action(policy, state, artifact=None):
    if policy not in POLICIES:
        raise ValueError("Unknown ForgeBench policy")
    legal = allowed_actions(state)
    if legal == ("stop",):
        return {"action": "stop", "source": "constraint"}
    if policy == "strong_only":
        return {
            "action": "escalate" if "escalate" in legal else "repair",
            "source": "baseline",
        }
    if policy == "cheap_only":
        return {
            "action": "retry" if not state["attempts"] else "repair",
            "source": "baseline",
        }
    if policy == "escalate_on_failure":
        return {
            "action": "retry"
            if not state["attempts"]
            else "escalate"
            if "escalate" in legal
            else "repair",
            "source": "baseline",
        }
    if (
        policy == "adaptive"
        and artifact
        and artifact.get("trained") is True
        and artifact.get("feature_version") == FEATURE_VERSION
    ):
        key = encode_state(state)
        values = artifact.get("q_values", {}).get(key, {})
        counts = artifact.get("action_counts", {}).get(key, {})
        supported = [
            a
            for a in legal
            if counts.get(a, 0) > 0
            and type(values.get(a)) in (int, float)
            and math.isfinite(values[a])
        ]
        if supported:
            return {
                "action": max(supported, key=lambda a: (values[a], -ACTIONS.index(a))),
                "source": "learned_q",
            }
    return {
        "action": static_action(state),
        "source": "heuristic_fallback" if policy == "adaptive" else "hand_written",
    }


def fit_q(transitions, gamma=0.9, iterations=100, min_samples=12):
    if not 0 <= gamma < 1 or iterations < 1 or min_samples < 1:
        raise ValueError("Invalid fitting configuration")
    buckets, normalized = {}, []
    for row in transitions:
        if row.get("split") != "train" or not row.get("task_id"):
            raise ValueError("Fitting requires train-only task provenance")
        if row["action"] not in allowed_actions(row["state"]):
            raise ValueError("Illegal observed action")
        if type(row["reward"]) not in (int, float) or not math.isfinite(row["reward"]):
            raise ValueError("Reward must be finite")
        entry = {
            "state": encode_state(row["state"]),
            "next_state": encode_state(row["next_state"]),
            "next_legal": allowed_actions(row["next_state"]),
            "action": row["action"],
            "reward": row["reward"],
            "terminal": bool(row["terminal"]),
            "task_id": row["task_id"],
        }
        normalized.append(entry)
        buckets.setdefault(entry["state"], {}).setdefault(entry["action"], []).append(
            entry
        )
    q = {key: {a: 0.0 for a in groups} for key, groups in buckets.items()}
    for _ in range(iterations):
        updated = {}
        for key, groups in buckets.items():
            updated[key] = {}
            for action, rows in groups.items():
                targets = [
                    r["reward"]
                    + (
                        gamma
                        * max(
                            [
                                v
                                for a, v in q.get(r["next_state"], {}).items()
                                if a in r["next_legal"]
                            ]
                            or [0]
                        )
                        if not r["terminal"]
                        else 0
                    )
                    for r in rows
                ]
                updated[key][action] = sum(targets) / len(targets)
        delta = max([abs(updated[k][a] - q[k][a]) for k in q for a in q[k]] or [0])
        q = updated
        if delta < 1e-9:
            break
    return {
        "feature_version": FEATURE_VERSION,
        "trained": len(normalized) >= min_samples,
        "algorithm": "offline_tabular_fitted_q",
        "q_values": q,
        "action_counts": {
            k: {a: len(rows) for a, rows in groups.items()}
            for k, groups in buckets.items()
        },
        "training_digest": hashlib.sha256(
            json.dumps(normalized, sort_keys=True).encode()
        ).hexdigest(),
        "diagnostics": {
            "transitions": len(normalized),
            "tasks": len({r["task_id"] for r in normalized}),
            "minimum_samples": min_samples,
            "evaluation_used_for_fit": False,
            "fallback": "hand-written router for untrained artifacts or unseen states/actions",
        },
        "gamma": gamma,
        "language_model_weights_updated": False,
    }
