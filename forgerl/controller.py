"""Finite, offline tabular Q controller for model-call routing.

This fits observed controller transitions. It does not fine-tune an LLM.
Unsupported states/actions fall back to the explicitly labeled heuristic.
"""
from __future__ import annotations
import hashlib
import json
import math
from typing import Any

ACTIONS = ("fast", "deliberate", "replan", "stop")
FEATURE_VERSION = 1


def _number(state, key, default):
    value = state.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Invalid state feature: {key}")
    return value


def _features(state: dict[str, Any]) -> dict[str, Any]:
    total = max(0, _number(state, "public_total", 0))
    passed = min(total, max(0, _number(state, "public_passed", 0)))
    attempts = max(0, int(_number(state, "attempts", state.get("steps", 0))))
    maximum = max(1, int(_number(state, "max_steps", 3)))
    max_cost = max(0.000001, _number(state, "max_cost_usd", 1.0))
    used_cost = max(0, _number(state, "cost_usd", 0))
    return {
        "ratio": passed / total if total else 0.0,
        "visible_pass": total > 0 and passed == total,
        "attempts": attempts,
        "remaining_steps": max(0, maximum - attempts),
        "remaining_cost": max(0.0, 1.0 - used_cost / max_cost),
        "improvement": _number(state, "improvement", 0),
        "last_action": state.get("last_action") if state.get("last_action") in ACTIONS else "none",
        "replan_count": max(0, int(_number(state, "replan_count", 0))),
    }


def encode_state(state: dict[str, Any]) -> str:
    """Whitelist observable features; ignore held-out labels and task identity."""
    f = _features(state)
    ratio_bin = "all" if f["visible_pass"] else "some" if f["ratio"] > 0 else "none"
    change = "+" if f["improvement"] > 0 else "-" if f["improvement"] < 0 else "0"
    budget = "low" if f["remaining_cost"] <= 0.3 else "mid" if f["remaining_cost"] <= 0.6 else "high"
    return "|".join(map(str, (FEATURE_VERSION, ratio_bin, min(f["attempts"], 3),
                                min(f["remaining_steps"], 3), budget, change,
                                f["last_action"], min(f["replan_count"], 1))))


def allowed_actions(state: dict[str, Any]) -> tuple[str, ...]:
    f = _features(state)
    if f["visible_pass"] or f["remaining_steps"] == 0 or f["remaining_cost"] <= 0:
        return ("stop",)
    actions = ["fast", "deliberate"]
    if f["attempts"] > 0 and f["replan_count"] == 0:
        actions.append("replan")
    actions.append("stop")
    return tuple(actions)


def heuristic_action(state: dict[str, Any]) -> str:
    f = _features(state)
    if allowed_actions(state) == ("stop",):
        return "stop"
    if f["attempts"] == 0 or f["remaining_cost"] <= 0.3:
        return "fast"
    if f["attempts"] >= 2 and f["improvement"] <= 0 and f["replan_count"] == 0:
        return "replan"
    return "deliberate"


def controller_status(artifact: dict | None) -> dict:
    loaded = bool(artifact and artifact.get("trained") is True
                  and artifact.get("feature_version") == FEATURE_VERSION
                  and isinstance(artifact.get("q_values"), dict))
    return {"trained": loaded, "label": "Fitted tabular Q policy" if loaded else "Untrained: heuristic fallback",
            "feature_version": FEATURE_VERSION,
            "training_transitions": artifact.get("diagnostics", {}).get("transitions", 0) if loaded else 0}


def choose_action(policy: str, state: dict[str, Any], artifact: dict | None = None) -> str:
    if policy not in ("fixed", "fixed-fast", "deliberate", "fixed-deliberate", "deliberate-only", "heuristic", "adaptive"):
        raise ValueError("Unknown controller policy")
    legal = allowed_actions(state)
    if legal == ("stop",):
        return "stop"
    if policy in ("fixed", "fixed-fast"):
        return "fast"
    if policy in ("deliberate", "fixed-deliberate", "deliberate-only"):
        return "deliberate"
    if policy == "heuristic" or not controller_status(artifact)["trained"]:
        return heuristic_action(state)
    key = encode_state(state)
    values = artifact.get("q_values", {}).get(key, {})
    counts = artifact.get("action_counts", {}).get(key, {})
    supported = [a for a in legal if counts.get(a, 0) > 0 and
                 isinstance(values.get(a), (int, float)) and math.isfinite(values[a])]
    if not supported:
        return heuristic_action(state)
    return max(supported, key=lambda a: (values[a], -ACTIONS.index(a)))


def fit_q(transitions: list[dict], seed: int = 0, gamma: float = 0.9,
          iterations: int = 100, min_samples: int = 12) -> dict:
    """Batch fitted Q iteration over observed (state, action, reward, next-state).

    Rewards may include terminal held-out correctness, but state encoders use
    public observations only. Evaluation/validation rows are rejected, rather
    than silently influencing the learned policy. No claims of convergence to
    an optimal general repair policy are made.
    """
    if not 0 <= gamma < 1 or iterations < 1 or min_samples < 1:
        raise ValueError("Invalid fitting configuration")
    normalized = []
    buckets: dict[str, dict[str, list[dict]]] = {}
    for row in transitions:
        if row.get("split") != "train":
            raise ValueError("Q fitting accepts explicitly labeled train transitions only")
        if not isinstance(row.get("task_id"), str) or not row["task_id"]:
            raise ValueError("Each observed transition needs task_id provenance")
        action = row.get("action")
        if action not in ACTIONS:
            raise ValueError("Invalid observed action")
        reward = row.get("reward")
        if isinstance(reward, bool) or not isinstance(reward, (int, float)) or not math.isfinite(reward):
            raise ValueError("Reward must be finite")
        state, next_state = row["state"], row["next_state"]
        if action not in allowed_actions(state):
            raise ValueError("Observed action violates controller budget or stopping constraints")
        entry = {"state": encode_state(state), "action": action, "reward": float(reward),
                 "next_state": encode_state(next_state), "next_legal": allowed_actions(next_state),
                 "terminal": bool(row.get("terminal", row.get("done", False))), "task_id": row["task_id"]}
        normalized.append(entry)
        buckets.setdefault(entry["state"], {}).setdefault(action, []).append(entry)
    q = {key: {action: 0.0 for action in groups} for key, groups in buckets.items()}
    delta = 0.0
    completed = 0
    for iteration in range(iterations):
        updated = {}
        delta = 0.0
        for key, groups in buckets.items():
            updated[key] = {}
            for action, rows in groups.items():
                targets = []
                for row in rows:
                    next_values = [v for a, v in q.get(row["next_state"], {}).items() if a in row["next_legal"]]
                    continuation = max(next_values) if next_values and not row["terminal"] else 0.0
                    targets.append(row["reward"] + gamma * continuation)
                value = sum(targets) / len(targets)
                updated[key][action] = round(value, 12)
                delta = max(delta, abs(value - q[key][action]))
        q = updated
        completed = iteration + 1
        if delta < 1e-9:
            break
    fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1, "feature_version": FEATURE_VERSION,
        "algorithm": "batch_tabular_fitted_q_iteration", "trained": len(normalized) >= min_samples,
        "seed": seed, "gamma": gamma, "q_values": q,
        "action_counts": {key: {action: len(rows) for action, rows in groups.items()} for key, groups in buckets.items()},
        "training_digest": fingerprint,
        "diagnostics": {"transitions": len(normalized), "tasks": len({r["task_id"] for r in normalized}),
                        "states": len(buckets), "state_action_pairs": sum(len(x) for x in buckets.values()),
                        "iterations": completed, "last_max_update": delta, "minimum_samples": min_samples,
                        "fallback": "heuristic for unseen states or untrained artifact", "evaluation_used_for_fit": False},
        "limitations": ["Fits routing actions, not language-model weights.",
                        "Finite authored tasks and sparse state coverage limit generalization.",
                        "Offline actions without observed support are not selected.",
                        "Public-test success is not a guarantee of held-out correctness."],
    }
