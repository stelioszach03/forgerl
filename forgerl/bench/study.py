"""Prospective bounded studies; no inference or file writes happen on import."""

from __future__ import annotations
import hashlib
import json
import math
import os
import random
from collections import defaultdict
from pathlib import Path
from . import router
from .engine import RepoEpisode, run_episode, utc_now
from ..provider import BudgetExceeded
from ..research import validate_splits

VERSION = "0.2"
PROTOCOL = "forgebench-v0.2-prespecified"
LIMITATIONS = [
    "Authored miniature Python repositories, not real-world SWE-bench issues or evidence of production long-horizon capability.",
    "Hidden means withheld from agent context during evaluation; source publication makes this a transparent benchmark, not a private contamination-resistant test set.",
    "Five related variants per family share interfaces; families are split-disjoint, but task observations are not fully independent.",
    "The learned controller is fitted offline; hosted language-model weights are unchanged.",
    "Observed failure labels are testable proxies, not causal claims about localization, planning or private model reasoning.",
    "Latency includes hosted inference, network and isolated testing; it is not GPU-seconds.",
    "Failed requests, missing measurements and incomplete coverage are retained. Success rates describe attempted runs, not unrun tasks.",
    "Sparse state/action coverage triggers an explicit hand-written fallback; learned-action coverage is reported.",
    "Unnecessary edits count changed files outside the reference patch scope, assessed only after decisions. Alternative valid edits may count; this is not a minimality oracle.",
]


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def source_manifest():
    """Hash actual evaluated source, independent of a possibly dirty checkout."""
    root = Path(__file__).resolve().parents[2]
    paths = (
        list((root / "forgerl").rglob("*.py"))
        + list((root / "sandbox").glob("*"))
        + [root / "scripts/forgebench.py", root / "requirements.lock"]
    )
    hashes = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
        if p.is_file()
    }
    return {
        "files": hashes,
        "sha256": digest(hashes),
        "sandbox_image": os.environ.get("FORGEBENCH_EVALUATED_IMAGE"),
        "checkpoint_revision": "Hosted provider does not expose a fixed checkpoint revision.",
    }


def select_tasks(tasks, per_family):
    groups = defaultdict(list)
    for task in tasks:
        groups[task.family].append(task)
    return [
        task
        for name in sorted(groups)
        for task in sorted(groups[name], key=lambda t: t.id)[:per_family]
    ]


def plan(
    tasks,
    *,
    seed=17,
    train_per_family=5,
    eval_per_family=5,
    train_rollouts=2,
    max_steps=6,
    max_decisions=10,
    max_cost_usd=5.0,
    rate_limit_retries=0,
):
    validate_splits(tasks)
    if (
        not 1 <= train_per_family <= 5
        or not 1 <= eval_per_family <= 5
        or not 1 <= train_rollouts <= 4
        or not 1 <= max_steps <= 6
        or not 1 <= max_decisions <= 10
        or not 0 < max_cost_usd <= 10
        or type(rate_limit_retries) is not int
        or not 0 <= rate_limit_retries <= 2
    ):
        raise ValueError("Invalid bounded study configuration")
    training = select_tasks([t for t in tasks if t.split == "train"], train_per_family)
    evaluation = select_tasks([t for t in tasks if t.split != "train"], eval_per_family)
    return {
        "protocol": PROTOCOL
        if not rate_limit_retries
        else PROTOCOL + "-rate-limit-retry-v1",
        "rate_limit_retries": rate_limit_retries,
        "version": VERSION,
        "seed": seed,
        "task_count": len(tasks),
        "training_ids": [t.id for t in training],
        "evaluation_ids": [t.id for t in evaluation],
        "train_rollouts_per_task": train_rollouts,
        "policies": list(router.POLICIES),
        "maximum_model_calls": max_steps,
        "maximum_decisions": max_decisions,
        "study_cost_cap_usd": max_cost_usd,
        "planned_training_episodes": len(training) * train_rollouts,
        "planned_evaluation_episodes": len(evaluation) * len(router.POLICIES),
        "selection": "Lexicographic task IDs within every selected family, declared before inference",
        "cost_weight": 5.0,
        "language_model_weights_updated": False,
    }


class Writer:
    def __init__(self, directory):
        self.directory = Path(directory)
        if self.directory.exists() and any(self.directory.iterdir()):
            raise FileExistsError(
                "Use a new evidence directory; existing studies are immutable"
            )
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "runs").mkdir()

    def write(self, name, value):
        target = self.directory / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        with temporary.open("w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)

    def append(self, name, value):
        with (self.directory / name).open("a") as stream:
            stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def run(self, result, phase):
        self.write("runs/" + result["id"] + ".json", result)
        self.append(
            "raw-runs.jsonl",
            {
                "phase": phase,
                "run_id": result["id"],
                "task_id": result["task_id"],
                "policy": result["policy"],
                "status": result["status"],
            },
        )


class CappedProvider:
    """Per-study preflight on top of the existing durable reservation ledger.

    The CLI exclusively locks studies on that ledger. Any unrelated spending is
    included conservatively in the measured delta; it can only stop this earlier.
    """

    def __init__(self, provider, cap_usd):
        self.provider, self.cap_usd = provider, cap_usd
        self.store = provider.store
        self.start_budget = self.store.budget("research")
        if self.start_budget["disabled"] or self.start_budget["remaining_usd"] < 0.001:
            raise BudgetExceeded("Research ledger has no usable allowance")
        self.cap_usd = min(self.cap_usd, self.start_budget["remaining_usd"])

    def spent(self):
        return max(
            0.0,
            self.store.budget("research")["total_charged_usd"]
            - self.start_budget["total_charged_usd"],
        )

    def remaining(self):
        return max(
            0.0,
            min(
                self.cap_usd - self.spent(),
                self.store.budget("research")["remaining_usd"],
            ),
        )

    def metadata(self):
        return self.provider.metadata()

    def build_messages(self, *args, **kwargs):
        return self.provider.build_messages(*args, **kwargs)

    def estimate_reservation_usd(self, *args, **kwargs):
        return self.provider.estimate_reservation_usd(*args, **kwargs)

    def estimate_token_bound(self, *args, **kwargs):
        estimator = getattr(self.provider, "estimate_token_bound", None)
        return estimator(*args, **kwargs) if estimator else 0

    async def generate(self, task, files, feedback, action, **kwargs):
        expected = self.estimate_reservation_usd(task, files, feedback, action)
        if expected > self.remaining() + 1e-9:
            raise BudgetExceeded(
                "Per-study cap reached before reserving another model request"
            )
        return await self.provider.generate(task, files, feedback, action, **kwargs)


def summarize(runs, planned):
    summary = []
    for policy in router.POLICIES:
        rows = [r for r in runs if r["policy"] == policy]

        def mean(key):
            values = [r[key] for r in rows if r.get(key) is not None]
            return sum(values) / len(values) if values else None

        n = len(rows)
        graded = [r for r in rows if r.get("heldout_passed") is not None]
        repaired = [r for r in rows if r["attempts"] > 1]
        solved = sum(r["status"] == "completed" and r["solved"] for r in rows)
        summary.append(
            {
                "policy": policy,
                "n": n,
                "planned": planned,
                "solved": solved,
                "solve_rate": solved / n if n else None,
                "hidden_test_pass_rate": sum(r["heldout_passed"] for r in graded)
                / sum(r["heldout_total"] for r in graded)
                if graded
                else None,
                "graded_runs": len(graded),
                "mean_cost_usd": mean("cost_usd"),
                "mean_tokens": mean("tokens"),
                "token_measured_runs": sum(r.get("tokens") is not None for r in rows),
                "mean_latency_s": mean("elapsed_s"),
                "mean_tool_calls": mean("tool_calls"),
                "mean_steps": mean("steps"),
                "mean_regressions": mean("regressions_introduced"),
                "success_after_repair_rate": sum(
                    r["success_after_repair"] for r in repaired
                )
                / len(repaired)
                if repaired
                else None,
                "repair_eligible_runs": len(repaired),
                "escalation_frequency": sum(r["escalations"] > 0 for r in rows) / n
                if n
                else None,
                "unnecessary_edits": mean("unnecessary_edits"),
                "failed_runs": sum(r["status"] != "completed" for r in rows),
                "learned_decisions": sum(r["learned_decisions"] for r in rows),
                "fallback_decisions": sum(r["fallback_decisions"] for r in rows),
            }
        )
    return summary


def paired_intervals(runs, seed):
    """Pair by task, average seeds before resampling (never independent seeds)."""
    grouped = defaultdict(lambda: defaultdict(list))
    for r in runs:
        grouped[r["task_id"]][r["policy"]].append(
            float(r["status"] == "completed" and r["solved"])
        )
    results = []
    for policy in router.POLICIES:
        if policy == "adaptive":
            continue
        values = [
            sum(v["adaptive"]) / len(v["adaptive"]) - sum(v[policy]) / len(v[policy])
            for v in grouped.values()
            if v.get("adaptive") and v.get(policy)
        ]
        ci = None
        if len(values) >= 3:
            rng = random.Random(seed)
            draws = sorted(
                sum(rng.choice(values) for _ in values) / len(values)
                for _ in range(2000)
            )
            ci = [draws[49], draws[1949]]
        results.append(
            {
                "baseline": policy,
                "paired_tasks": len(values),
                "solve_rate_difference": sum(values) / len(values) if values else None,
                "task_bootstrap_95": ci,
                "note": "Descriptive task bootstrap; related variants within families limit independence. Seeds are averaged within task.",
            }
        )
    return results


def public_summary(run):
    return {
        k: v
        for k, v in run.items()
        if k not in {"events", "initial_files", "final_files", "diff"}
    }


async def run_study(
    tasks,
    provider,
    output,
    *,
    task_manifest_hash,
    seed=17,
    train_per_family=5,
    eval_per_family=5,
    train_rollouts=2,
    max_steps=6,
    max_decisions=10,
    max_cost_usd=5.0,
    episode_factory=RepoEpisode,
    rate_limit_retries=0,
):
    configuration = plan(
        tasks,
        seed=seed,
        train_per_family=train_per_family,
        eval_per_family=eval_per_family,
        train_rollouts=train_rollouts,
        max_steps=max_steps,
        max_decisions=max_decisions,
        max_cost_usd=max_cost_usd,
        rate_limit_retries=rate_limit_retries,
    )
    bounded = CappedProvider(provider, max_cost_usd)
    writer = Writer(output)
    by_id = {t.id: t for t in tasks}
    provenance = {
        "started_at": utc_now(),
        "task_manifest_sha256": task_manifest_hash,
        "configuration": configuration,
        "configuration_sha256": digest(configuration),
        "source_manifest": source_manifest(),
        "provider": provider.metadata(),
        "budget_before": bounded.start_budget,
        "study_cap_usd": bounded.cap_usd,
        "status": "running",
        "training_completed": 0,
        "training_failures": 0,
    }
    writer.write("manifest.json", provenance)
    writer.write("plan.json", configuration)
    training, runs, artifact = [], [], None
    stop_reason = None
    try:
        for task_id in configuration["training_ids"]:
            for rollout in range(train_rollouts):
                stable_seed = (
                    seed
                    + rollout * 10000
                    + int(hashlib.sha256(task_id.encode()).hexdigest()[:6], 16)
                )
                rng = random.Random(stable_seed)

                def explore(state):
                    legal = router.allowed_actions(state)
                    if legal == ("stop",):
                        return {"action": "stop", "source": "training_constraint"}
                    if not state["attempts"]:
                        return {
                            "action": "retry" if rollout % 2 == 0 else "escalate",
                            "source": "prespecified_train_exploration",
                        }
                    choices = [
                        a for a in legal if a != "stop" or state["attempts"] >= 2
                    ]
                    return {
                        "action": rng.choice(choices),
                        "source": "prespecified_train_exploration",
                    }

                episode = episode_factory(
                    by_id[task_id],
                    bounded,
                    "exploration",
                    seed=stable_seed,
                    max_steps=max_steps,
                    max_decisions=max_decisions,
                    rate_limit_retries=rate_limit_retries,
                )
                episode.event_callback = lambda event, ident=episode.id: writer.append(
                    "events.jsonl", {"run_id": ident, "event": event}
                )
                result = await run_episode(episode, selector=explore)
                writer.run(result, "train")
                provenance["training_completed"] += 1
                if result["status"] == "completed":
                    for index, transition in enumerate(episode.transitions):
                        row = dict(transition)
                        row["terminal"] = index == len(episode.transitions) - 1
                        row["reward"] = (
                            float(result["solved"]) if row["terminal"] else 0.0
                        ) - configuration["cost_weight"] * row["cost_usd"]
                        training.append(row)
                        writer.append("transitions.jsonl", row)
                else:
                    provenance["training_failures"] += 1
                if result["status"] == "budget_exhausted":
                    raise BudgetExceeded("Training reached the bounded allowance")
        artifact = router.fit_q(training)
        artifact["task_manifest_sha256"] = task_manifest_hash
        writer.write("controller.json", artifact)
        provenance["controller_sha256"] = digest(artifact)
        provenance["controller_trained"] = artifact["trained"]
        provenance["controller_frozen_at"] = utc_now()
        writer.write("manifest.json", provenance)
        # Validation is a report, not a hyperparameter selection step. Freeze once.
        for task_id in configuration["evaluation_ids"]:
            task = by_id[task_id]
            order = list(router.POLICIES)
            random.Random(
                seed + int(hashlib.sha256(task_id.encode()).hexdigest()[:8], 16)
            ).shuffle(order)
            for policy in order:
                episode = episode_factory(
                    task,
                    bounded,
                    policy,
                    artifact=artifact,
                    seed=seed,
                    max_steps=max_steps,
                    max_decisions=max_decisions,
                    rate_limit_retries=rate_limit_retries,
                )
                episode.event_callback = lambda event, ident=episode.id: writer.append(
                    "events.jsonl", {"run_id": ident, "event": event}
                )
                result = await run_episode(episode)
                writer.run(result, "evaluation")
                runs.append(result)
                if result["status"] == "budget_exhausted":
                    raise BudgetExceeded("Evaluation reached the bounded allowance")
    except Exception as exc:
        stop_reason = f"{type(exc).__name__}: {exc}"
    expected = [
        {"task_id": task_id, "policy": policy, "seed": seed}
        for task_id in configuration["evaluation_ids"]
        for policy in router.POLICIES
    ]
    observed = {(r["task_id"], r["policy"], r["seed"]) for r in runs}
    missing = [
        r for r in expected if (r["task_id"], r["policy"], r["seed"]) not in observed
    ]
    tests = [r for r in runs if r["split"] == "test"]
    validations = [r for r in runs if r["split"] == "validation"]
    test_n = sum(
        by_id[ident].split == "test" for ident in configuration["evaluation_ids"]
    )
    val_n = sum(
        by_id[ident].split == "validation" for ident in configuration["evaluation_ids"]
    )
    provenance.update(
        {
            "finished_at": utc_now(),
            "status": "partial" if missing or stop_reason else "complete",
            "stop_reason": stop_reason,
            "budget_after": bounded.store.budget("research"),
            "study_ledger_delta_usd": bounded.spent(),
            "training_transitions": len(training),
            "controller_sha256": digest(artifact) if artifact else None,
        }
    )
    benchmark = {
        "version": VERSION,
        "status": provenance["status"],
        "generated_at": utc_now(),
        "task_count": len(tasks),
        "models": [
            m
            for m in provider.metadata()["models"]
            if m["id"] in {model for run in runs for model in run.get("model_ids", [])}
        ],
        "policies": list(router.POLICIES),
        "summary": summarize(tests, test_n),
        "validation_summary": summarize(validations, val_n),
        "coverage": {
            "planned": len(expected),
            "completed": len(runs),
            "missing": missing,
            "training_planned": configuration["planned_training_episodes"],
            "training_completed": provenance["training_completed"],
            "evaluated_unique_tasks": len({r["task_id"] for r in runs}),
            "catalog_tasks": len(tasks),
            "summary_split": "test",
        },
        "runs": [public_summary(r) for r in runs],
        "paired_differences": paired_intervals(tests, seed),
        "limitations": LIMITATIONS,
        "provenance": provenance,
    }
    writer.write("benchmark.json", benchmark)
    writer.write("manifest.json", provenance)
    return benchmark
