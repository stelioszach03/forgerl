"""Bounded controller research, with separate collection and prospective evaluation.

This module never starts work on import. Paid calls only happen through an injected
provider; its durable ledger is the authority for available funds.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

PROTOCOL_VERSION = "forgerl-pilot-v1"
EVALUATION_POLICIES = ("fixed", "deliberate", "heuristic", "adaptive")
PATCH_ACTIONS = ("fast", "deliberate")
LIMITATIONS = [
    "Small curated Python-repair pilot; not SWE-bench or a general software-engineering benchmark.",
    "Task families, not individual variants, are separated across training, validation and test.",
    "The controller is learned; language-model weights are unchanged.",
    "A small number of held-out families cannot establish broad or statistically reliable superiority.",
    "Provider processing time is not a measurement of GPU-seconds.",
    "Budget, provider and execution failures remain in the report; incomplete coverage is marked partial.",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_value(task: Any, key: str) -> Any:
    return task[key] if isinstance(task, dict) else getattr(task, key)


def validate_splits(tasks: Iterable[Any]) -> dict[str, list[str]]:
    """Fail before spending when a family leaks or an ID occurs twice."""
    families: dict[str, str] = {}
    ids: set[str] = set()
    splits: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        task_id = str(_task_value(task, "id"))
        family = str(_task_value(task, "family"))
        split = str(_task_value(task, "split"))
        if split not in {"train", "validation", "test"}:
            raise ValueError(f"Unsupported split for {task_id}: {split}")
        if task_id in ids:
            raise ValueError(f"Duplicate task ID: {task_id}")
        if family in families and families[family] != split:
            raise ValueError(f"Task family crosses splits: {family}")
        ids.add(task_id)
        families[family] = split
        splits[split].append(task_id)
    if not all(splits.get(split) for split in ("train", "validation", "test")):
        raise ValueError("Training, validation and test tasks are all required")
    return dict(splits)


class EvidenceWriter:
    """Append raw records promptly; atomically publish JSON manifests/results."""

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.raw_path = self.directory / "raw-runs.jsonl"
        self.transitions_path = self.directory / "transitions.jsonl"
        # Reusing an evidence directory could mix policies or duplicate spending.
        if self.raw_path.exists() or self.transitions_path.exists():
            raise FileExistsError("Choose a new evidence directory for each research run")

    def append(self, record: dict, *, transition: bool = False) -> None:
        import os
        path = self.transitions_path if transition else self.raw_path
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def write_json(self, name: str, payload: dict) -> None:
        path = self.directory / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
        temporary.replace(path)


def _cost(result: dict) -> float:
    value = float(result.get("cost_usd", 0.0) or 0.0)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Episode cost must be finite and non-negative")
    return value


def _public_pass(state: dict) -> bool:
    total = int(state.get("public_total", state.get("total", 0)) or 0)
    passed = int(state.get("public_passed", state.get("passed", 0)) or 0)
    return total > 0 and passed == total


def _terminal_status(result: dict) -> bool:
    return result.get("status") in {"failed", "budget_exhausted", "cancelled"}


def _exception_is_budget(exc: Exception) -> bool:
    # Lazy import allows deterministic tests without loading the provider adapter.
    from .provider import BudgetExceeded
    return isinstance(exc, BudgetExceeded)


async def collect_task_tree(
    task: Any,
    provider: Any,
    *,
    episode_factory: Callable,
    writer: EvidenceWriter | None = None,
    max_steps: int = 3,
    cost_weight: float = 5.0,
) -> dict:
    """Collect a binary action tree on one *training* task, including STOP rewards.

    Hidden outcomes are reward labels only. They never enter stored state vectors.
    Each branch clone shares the provider ledger but has independent source/history.
    """
    if _task_value(task, "split") != "train":
        raise ValueError("Controller transition collection is training-only")
    if max_steps < 1 or max_steps > 3 or cost_weight < 0:
        raise ValueError("Invalid bounded research configuration")
    task_id = str(_task_value(task, "id"))
    root = episode_factory(task, provider, policy_id="research-tree", max_steps=max_steps)
    await root.start()
    transitions: list[dict] = []
    traces: list[dict] = []
    partial = False
    reason: str | None = None
    requests = 0
    billed_cost = 0.0

    def save_trace(route: list[str], result: dict, kind: str) -> None:
        record = {"kind": kind, "task_id": task_id, "split": "train", "route": route, "run": result}
        traces.append(record)
        if writer:
            writer.append(record)

    def save_transition(state: dict, action: str, reward: float, next_state: dict, terminal: bool, route: list[str]) -> None:
        transition = {"state": state, "action": action, "reward": reward, "next_state": next_state,
                      "terminal": terminal, "task_id": task_id, "split": "train", "route": route}
        transitions.append(transition)
        if writer:
            writer.append(transition, transition=True)

    async def visit(episode: Any, route: list[str]) -> None:
        nonlocal partial, reason, requests, billed_cost
        state = dict(episode.observation())
        stop_probe = episode.clone()
        stop_result = await stop_probe.finish()
        save_trace(route + ["stop"], stop_result, "training-stop-audit")
        if _terminal_status(stop_result):
            partial, reason = True, str(stop_result.get("error") or stop_result.get("status"))
            # Infrastructure failure is not a legitimate negative training reward.
            return
        save_transition(state, "stop", float(bool(stop_result.get("solved"))), state, True, route)
        if len(route) >= max_steps or _public_pass(state) or getattr(episode, "terminal", False):
            return
        for action in PATCH_ACTIONS:
            if partial and reason == "budget_exhausted":
                break
            branch = episode.clone()
            before = _cost(branch.result())
            requests += 1
            try:
                await branch.step(action)
            except Exception as exc:
                partial = True
                reason = "budget_exhausted" if _exception_is_budget(exc) else type(exc).__name__
                result = branch.result()
                result = {**result, "status": "budget_exhausted" if reason == "budget_exhausted" else "failed", "error": str(exc)}
                billed_cost += max(0.0, _cost(result) - before)
                save_trace(route + [action], result, "training-error")
                if reason == "budget_exhausted":
                    break
                continue
            next_state = dict(branch.observation())
            current = branch.result()
            incremental_cost = max(0.0, _cost(current) - before)
            billed_cost += incremental_cost
            if _terminal_status(current):
                partial = True
                reason = "budget_exhausted" if current.get("status") == "budget_exhausted" else str(current.get("error") or current.get("status"))
                save_trace(route + [action], current, "training-error")
                continue
            terminal = len(route) + 1 >= max_steps or _public_pass(next_state) or bool(getattr(branch, "terminal", False))
            reward = -cost_weight * incremental_cost
            if terminal:
                result = await branch.finish()
                save_trace(route + [action], result, "training-terminal")
                if _terminal_status(result):
                    partial, reason = True, str(result.get("error") or result.get("status"))
                    continue
                reward += float(bool(result.get("solved")))
            else:
                save_trace(route + [action], current, "training-transition")
            save_transition(state, action, reward, next_state, terminal, route)
            if not terminal:
                await visit(branch, route + [action])

    await visit(root, [])
    return {"task_id": task_id, "transitions": transitions, "traces": traces, "partial": partial,
            "reason": reason, "requests_attempted": requests, "collection_cost_usd": billed_cost}


async def evaluate_policy(
    task: Any, provider: Any, policy: str, *, episode_factory: Callable,
    selector: Callable, artifact: dict | None, max_steps: int = 3,
) -> dict:
    """Fresh episode; no counterfactual tree or training samples are reused."""
    episode = episode_factory(task, provider, policy_id=policy, max_steps=max_steps, artifact=artifact)
    try:
        await episode.start()
        for _ in range(max_steps):
            state = episode.observation()
            if _public_pass(state) or getattr(episode, "terminal", False):
                break
            action = "deliberate" if policy == "deliberate" else selector(policy, state, artifact)
            if action == "stop":
                await episode.step("stop")
                break
            if action not in {"fast", "deliberate", "replan"}:
                raise ValueError("Controller returned an unsupported action")
            await episode.step(action)
            if _terminal_status(episode.result()):
                break
        result = await episode.finish()
    except Exception as exc:
        result = episode.result()
        result = {**result, "status": "budget_exhausted" if _exception_is_budget(exc) else "failed", "error": str(exc)}
    return {**result, "task_id": str(_task_value(task, "id")), "task_title": str(_task_value(task, "title")),
            "family": str(_task_value(task, "family")), "split": str(_task_value(task, "split")),
            "policy": policy, "evaluation_mode": "prospective", "mode": "recorded"}


def wilson_interval(successes: int, count: int, z: float = 1.959963984540054) -> list[float] | None:
    if count == 0:
        return None
    p = successes / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def aggregate_runs(runs: list[dict], planned_task_ids: list[str], *, policies: tuple[str, ...] = EVALUATION_POLICIES, seed: int = 17) -> dict:
    """Failures stay in denominators. Missing runs are coverage gaps, not zeros."""
    summaries = []
    by_policy = {policy: [r for r in runs if r["policy"] == policy] for policy in policies}
    for policy, items in by_policy.items():
        count = len(items)
        solved = sum(bool(r.get("solved")) and r.get("status") == "completed" for r in items)
        def mean(key: str) -> float | None:
            if key == 'tokens' and any(r.get('tokens') is None or r.get('tokens_complete') is False for r in items):
                return None
            return sum(float(r.get(key, 0) or 0) for r in items) / count if count else None
        summaries.append({"policy": policy, "n": count, "planned_n": len(planned_task_ids), "solved": solved,
                          "solve_rate": solved / count if count else None, "solve_rate_wilson_95": wilson_interval(solved, count),
                          "mean_steps": mean("steps"), "mean_tokens": mean("tokens"), "mean_cost_usd": mean("cost_usd"),
                          "mean_latency_s": mean("elapsed_s"), "provider_or_execution_failures": sum(_terminal_status(r) for r in items),
                          "missing_task_ids": sorted(set(planned_task_ids) - {r["task_id"] for r in items})})
    paired_runs = [{"task_id": task_id, "task_title": next((r.get("task_title", task_id) for r in runs if r["task_id"] == task_id), task_id),
                    "runs": [r for r in runs if r["task_id"] == task_id]} for task_id in planned_task_ids]
    paired_differences = []
    learned = {r["task_id"]: r for r in by_policy.get("adaptive", [])}
    for policy in policies:
        if policy == "adaptive":
            continue
        baseline = {r["task_id"]: r for r in by_policy[policy]}
        common = sorted(set(learned) & set(baseline))
        families: dict[str, list[float]] = defaultdict(list)
        for task_id in common:
            a, b = learned[task_id], baseline[task_id]
            families[a.get("family", task_id)].append(float(bool(a.get("solved")) and a.get("status") == "completed") - float(bool(b.get("solved")) and b.get("status") == "completed"))
        values = [v for group in families.values() for v in group]
        interval = None
        # Fewer than three families makes a cluster bootstrap essentially meaningless.
        if len(families) >= 3:
            rng, names, samples = random.Random(seed), list(families), []
            for _ in range(2000):
                draw = [value for _ in names for value in families[rng.choice(names)]]
                samples.append(sum(draw) / len(draw))
            samples.sort()
            interval = [samples[49], samples[1949]]
        paired_differences.append({"baseline": policy, "paired_n": len(common), "family_n": len(families),
                                   "solve_rate_difference": sum(values) / len(values) if values else None,
                                   "family_bootstrap_95": interval,
                                   "interval_note": "Descriptive pilot interval only." if interval else "Not estimated: fewer than three paired task families."})
    complete = all(s["n"] == len(planned_task_ids) and not s["missing_task_ids"] for s in summaries)
    return {"status": "complete" if complete else "partial", "summary": summaries, "paired_runs": paired_runs,
            "paired_differences": paired_differences, "limitations": list(LIMITATIONS)}


async def run_research(
    tasks: list[Any], provider: Any, output_dir: Path | str, *, episode_factory: Callable,
    fit_controller: Callable, selector: Callable, task_manifest_hash: str,
    seed: int = 17, max_steps: int = 3, cost_weight: float = 5.0,
) -> dict:
    """One bounded pilot, retaining raw evidence and partial completion state."""
    splits = validate_splits(tasks)
    writer = EvidenceWriter(output_dir)
    manifest = {"protocol": PROTOCOL_VERSION, "started_at": utc_now(), "completed_at": None,
                "status": "running", "task_manifest_sha256": task_manifest_hash, "splits": splits,
                "controller_seed": seed, "model_sampling": "Provider/episode configuration; determinism is not guaranteed.",
                "max_steps": max_steps, "cost_weight": cost_weight, "policies": list(EVALUATION_POLICIES),
                "planned_exclusions": [], "training_collection": "binary-fast-deliberate-tree; stop at visible-test pass",
                "evaluation": "fresh prospective episodes after fitting", "language_model_weights_updated": False}
    writer.write_json("manifest.json", manifest)
    transitions, training_summary, runs = [], [], []
    artifact = None
    budget_exhausted = False
    try:
        for task in [t for t in tasks if _task_value(t, "split") == "train"]:
            collected = await collect_task_tree(task, provider, episode_factory=episode_factory, writer=writer, max_steps=max_steps, cost_weight=cost_weight)
            transitions.extend(collected["transitions"])
            training_summary.append({k: v for k, v in collected.items() if k not in {"transitions", "traces"}})
            if collected["reason"] == "budget_exhausted":
                budget_exhausted = True
                break
        if not transitions or budget_exhausted:
            manifest["status"] = "partial"
            manifest["reason"] = "budget_exhausted" if budget_exhausted else "no_valid_training_transitions"
        else:
            artifact = fit_controller(transitions, seed=seed)
            # Some controller implementations return (artifact, diagnostics).
            diagnostics = None
            if isinstance(artifact, tuple):
                artifact, diagnostics = artifact
            if not isinstance(artifact, dict):
                raise TypeError("Controller fit must return a JSON artifact")
            writer.write_json("controller.json", artifact)
            if artifact.get("trained") is not True:
                raise ValueError("Insufficient evidence to fit a trained controller; adaptive evaluation was not run")
            if diagnostics is not None:
                writer.write_json("training-diagnostics.json", diagnostics)
            manifest["controller_sha256"] = hashlib.sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest()
            # No post-validation parameter changes: the same frozen artifact is used on test.
            for split in ("validation", "test"):
                for task in [t for t in tasks if _task_value(t, "split") == split]:
                    order = list(EVALUATION_POLICIES)
                    stable_seed = int(hashlib.sha256(f"{seed}:{_task_value(task, 'id')}".encode()).hexdigest()[:8], 16)
                    random.Random(stable_seed).shuffle(order)
                    for policy in order:
                        result = await evaluate_policy(task, provider, policy, episode_factory=episode_factory, selector=selector,
                                                       artifact=artifact, max_steps=max_steps)
                        runs.append(result)
                        writer.append({"kind": "prospective-evaluation", "run": result})
                        if result.get("status") == "budget_exhausted":
                            budget_exhausted = True
                            break
                    if budget_exhausted:
                        break
                if budget_exhausted:
                    break
            manifest["status"] = "partial" if budget_exhausted else "complete"
    except Exception as exc:
        manifest["status"], manifest["reason"] = "partial", f"{type(exc).__name__}: {exc}"
    manifest["completed_at"] = utc_now()
    manifest["training_tasks_completed"] = len(training_summary)
    manifest["training_partial"] = any(item["partial"] for item in training_summary)
    if manifest["training_partial"]:
        manifest["status"] = "partial"
    manifest["transition_count"] = len(transitions)
    manifest["collection_cost_usd"] = sum(item["collection_cost_usd"] for item in training_summary)
    manifest["evaluation_cost_usd"] = sum(_cost(run) for run in runs)
    benchmark = aggregate_runs([r for r in runs if r["split"] == "test"], splits["test"], seed=seed)
    benchmark["validation"] = aggregate_runs([r for r in runs if r["split"] == "validation"], splits["validation"], seed=seed)
    benchmark["methodology"] = {"protocol": PROTOCOL_VERSION, "max_steps": max_steps, "controller_training": "finite-horizon fitted Q", "language_model_weights_updated": False}
    benchmark["provenance"] = manifest
    if manifest["status"] != "complete":
        benchmark["status"] = "partial"
    writer.write_json("training-summary.json", {"tasks": training_summary})
    writer.write_json("benchmark.json", benchmark)
    writer.write_json("manifest.json", manifest)
    return benchmark
