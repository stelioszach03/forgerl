#!/usr/bin/env python3
"""Aggregate the predeclared ForgeBench seeds without dropping failed/missing runs."""

from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import random
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forgerl.bench.study import LIMITATIONS, digest, public_summary, summarize
from forgerl.bench.router import POLICIES
from forgerl.bench.engine import utc_now

EXPECTED_SEEDS = (17, 29, 43)
ID = re.compile(r"[a-f0-9]{32}\Z")
METRICS = (
    "cost_usd",
    "tokens",
    "elapsed_s",
    "tool_calls",
    "steps",
    "attempts",
    "regressions_introduced",
    "unnecessary_edits",
    "escalations",
    "learned_decisions",
    "fallback_decisions",
)


def read_json(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def family_bootstrap(runs, seed=17, samples=2000):
    """Pair same task/seed; average within task before grouping by family."""
    policies = {
        p: {(r["task_id"], r["seed"]): r for r in runs if r["policy"] == p}
        for p in POLICIES
    }
    adaptive, results = policies["adaptive"], []
    for policy in POLICIES:
        if policy == "adaptive":
            continue
        common = sorted(set(adaptive) & set(policies[policy]))
        tasks = defaultdict(list)
        for identity in common:
            left, right = adaptive[identity], policies[policy][identity]
            tasks[(left["family"], identity[0])].append(
                int(left["status"] == "completed" and left["solved"])
                - int(right["status"] == "completed" and right["solved"])
            )
        families = defaultdict(list)
        for (family, task_id), values in tasks.items():
            families[family].append(sum(values) / len(values))
        values = [value for group in families.values() for value in group]
        interval = None
        if len(families) >= 3:
            rng, names = random.Random(seed), sorted(families)
            distribution = []
            for _ in range(samples):
                draw = [value for _ in names for value in families[rng.choice(names)]]
                distribution.append(sum(draw) / len(draw))
            distribution.sort()
            interval = [
                distribution[int(samples * 0.025)],
                distribution[min(samples - 1, int(samples * 0.975))],
            ]
        results.append(
            {
                "baseline": policy,
                "paired_episodes": len(common),
                "paired_tasks": len(tasks),
                "paired_families": len(families),
                "solve_rate_difference": sum(values) / len(values) if values else None,
                "family_bootstrap_95": interval,
                "bootstrap_samples": samples if interval is not None else 0,
                "status": "descriptive_interval"
                if interval is not None
                else "insufficient_clusters",
                "note": "Seeds averaged within task; families resampled together. Fewer than three families: no interval estimated. Even three clusters warrant cautious descriptive interpretation.",
            }
        )
    return {
        "unit": "family clusters after within-task seed averaging",
        "comparisons": results,
        "seed": seed,
        "no_binomial_interval": True,
    }


def _configuration_signature(manifest):
    config = manifest.get("configuration")
    if not isinstance(config, dict) or not manifest.get("task_manifest_sha256"):
        raise ValueError("Study has no configuration or task manifest")
    if manifest.get("configuration_sha256") != digest(config):
        raise ValueError("Study configuration hash mismatch")
    if (
        config.get("version") != "0.2"
        or config.get("protocol")
        not in (
            "forgebench-v0.2-prespecified",
            "forgebench-v0.2-prespecified-rate-limit-retry-v1",
        )
        or config.get("policies") != list(POLICIES)
    ):
        raise ValueError("Unsupported study version, protocol or policy set")
    train, evaluation = config.get("training_ids"), config.get("evaluation_ids")
    if (
        not isinstance(train, list)
        or not isinstance(evaluation, list)
        or len(set(train + evaluation)) != len(train + evaluation)
    ):
        raise ValueError("Task selection repeats or overlaps IDs")
    if config.get("language_model_weights_updated") is not False:
        raise ValueError("Frozen hosted weights must be explicit")
    source = manifest.get("source_manifest")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("files"), dict)
        or not source["files"]
        or source.get("sha256") != digest(source["files"])
    ):
        raise ValueError(
            "Evaluated source manifest is missing or its digest is invalid"
        )
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
        for value in source["files"].values()
    ):
        raise ValueError("Invalid evaluated source file digest")
    if not isinstance(source.get("sandbox_image"), str) or not re.fullmatch(
        r"sha256:[a-f0-9]{64}", source["sandbox_image"]
    ):
        raise ValueError("Evaluated sandbox image must be pinned by immutable digest")
    parameters = {k: v for k, v in config.items() if k != "seed"}
    return {
        "configuration": parameters,
        "task_manifest_sha256": manifest["task_manifest_sha256"],
        "provider": manifest.get("provider"),
        "source_manifest": source,
        "runtime_source_sha256": source["sha256"],
    }


def reconcile_training_counters(source, observed, failed):
    """Indexed complete episode artifacts are authoritative for snapshots."""
    source["training_completed_manifest"] = source.get("training_completed", 0)
    source["training_failures_manifest"] = source.get("training_failures", 0)
    mismatches = []
    for field, value in (
        ("training_completed", observed),
        ("training_failures", failed),
    ):
        if source[field + "_manifest"] != value:
            mismatches.append(
                {
                    "field": field,
                    "manifest": source[field + "_manifest"],
                    "observed": value,
                }
            )
        source[field] = value
    source["source_counter_mismatches"] = mismatches
    if mismatches and source["status"] == "running":
        source["counter_consistency"] = "in_progress_manifest_may_be_stale"
    elif mismatches:
        source["counter_consistency"] = "finished_manifest_mismatch"
        source["reported_status"] = source["status"]
        source["status"] = "partial"
    else:
        source["counter_consistency"] = "consistent"


def aggregate_studies(studies):
    if set(studies) - set(EXPECTED_SEEDS):
        raise ValueError("Only predeclared seeds 17, 29 and 43 may be aggregated")
    canonical, sources, full_runs, evaluation, identities, ids = (
        None,
        [],
        [],
        [],
        set(),
        set(),
    )
    family_splits, task_families = {}, {}
    for seed in EXPECTED_SEEDS:
        directory = Path(studies[seed]) if seed in studies else None
        if directory is None or not (directory / "manifest.json").is_file():
            sources.append({"seed": seed, "status": "missing"})
            continue
        manifest = read_json(directory / "manifest.json")
        signature = _configuration_signature(manifest)
        configuration = manifest["configuration"]
        if configuration.get("seed") != seed:
            raise ValueError("Source seed disagrees with declared mapping")
        if canonical is None:
            canonical = signature
        elif signature != canonical:
            raise ValueError(
                "Incompatible tasks, protocol, runtime source, provider or configuration across seeds"
            )
        controller_path = directory / "controller.json"
        if manifest.get("controller_sha256"):
            if (
                not controller_path.is_file()
                or digest(read_json(controller_path)) != manifest["controller_sha256"]
            ):
                raise ValueError("Frozen controller hash mismatch")
        source = {
            "seed": seed,
            "status": manifest.get("status", "partial"),
            "manifest_sha256": sha(directory / "manifest.json"),
            "controller_sha256": manifest.get("controller_sha256"),
            "controller_trained": manifest.get("controller_trained"),
            "finished_at": manifest.get("finished_at"),
            "training_completed": manifest.get("training_completed", 0),
            "training_failures": manifest.get("training_failures", 0),
            "study_ledger_delta_usd": manifest.get("study_ledger_delta_usd"),
            "stop_reason": manifest.get("stop_reason"),
        }
        observed_training = observed_training_failures = 0
        index = directory / "raw-runs.jsonl"
        if not index.is_file():
            source["status"] = "partial"
            source["raw_index_missing"] = True
            reconcile_training_counters(source, 0, 0)
            sources.append(source)
            continue
        index_bytes = index.read_bytes()
        source["raw_index_sha256"] = hashlib.sha256(index_bytes).hexdigest()
        for line in index_bytes.decode("utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            ident, phase = row.get("run_id", ""), row.get("phase")
            if not ID.fullmatch(ident) or phase not in ("train", "evaluation"):
                raise ValueError("Invalid run index entry")
            if ident in ids:
                raise ValueError("Duplicate run ID; do not select favorable duplicates")
            ids.add(ident)
            run_path = directory / "runs" / (ident + ".json")
            run = read_json(run_path)
            if run.get("id") != ident or any(
                run.get(k) != row.get(k) for k in ("task_id", "policy", "status")
            ):
                raise ValueError("Run/index identity mismatch")
            if (
                not isinstance(run.get("events"), list)
                or not isinstance(run.get("initial_files"), dict)
                or not isinstance(run.get("final_files"), dict)
            ):
                raise ValueError(
                    "A published run must include its actual trajectory and files"
                )
            if type(run.get("solved")) is not bool:
                raise ValueError("A run must have a boolean success outcome")
            for metric in METRICS:
                value = run.get(metric)
                if value is not None and (
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError("Invalid nonnegative metric: " + metric)
            if phase == "train":
                if (
                    run.get("split") != "train"
                    or run["task_id"] not in configuration["training_ids"]
                    or run.get("policy") != "exploration"
                ):
                    raise ValueError("Training row outside the declared split")
            else:
                if (
                    run.get("split") not in ("validation", "test")
                    or run["task_id"] not in configuration["evaluation_ids"]
                    or run.get("policy") not in POLICIES
                    or run.get("seed") != seed
                ):
                    raise ValueError(
                        "Evaluation row outside declared split, policy or seed"
                    )
                identity = (seed, run["task_id"], run["policy"])
                if identity in identities:
                    raise ValueError("Duplicate task/policy/seed evaluation")
                identities.add(identity)
            family, split = run.get("family"), run.get("split")
            if not isinstance(family, str) or not family:
                raise ValueError("Run has no family")
            if family in family_splits and family_splits[family] != split:
                raise ValueError("Family crosses train/validation/test splits")
            if (
                run["task_id"] in task_families
                and task_families[run["task_id"]] != family
            ):
                raise ValueError("Task changed family across studies")
            family_splits[family], task_families[run["task_id"]] = split, family
            # Preserve original run bytes in publication; aggregation metadata is
            # outside the trajectory, so its source hash stays reproducible.
            full_runs.append(
                {
                    "phase": phase,
                    "study_seed": seed,
                    "source_sha256": sha(run_path),
                    "run": run,
                }
            )
            if phase == "evaluation":
                evaluation.append(run)
            else:
                observed_training += 1
                observed_training_failures += run.get("status") != "completed"
        reconcile_training_counters(
            source, observed_training, observed_training_failures
        )
        sources.append(source)
    if canonical is None:
        raise ValueError("No study manifest available; publish a not_run view instead")
    configuration = canonical["configuration"]
    expected = [
        {"task_id": task, "policy": policy, "seed": seed}
        for seed in EXPECTED_SEEDS
        for task in configuration["evaluation_ids"]
        for policy in POLICIES
    ]
    missing = [
        row
        for row in expected
        if (row["seed"], row["task_id"], row["policy"]) not in identities
    ]
    # Catalog is a versioned authority for unobserved planned split assignment.
    from forgerl.bench.tasks import get_task

    test_ids = [
        ident
        for ident in configuration["evaluation_ids"]
        if (family_splits.get(task_families.get(ident)) or get_task(ident).split)
        == "test"
    ]
    validation_ids = [
        ident for ident in configuration["evaluation_ids"] if ident not in test_ids
    ]
    tests = [r for r in evaluation if r["split"] == "test"]
    validation = [r for r in evaluation if r["split"] == "validation"]
    observed_models = {
        model for run in evaluation for model in run.get("model_ids", [])
    }
    models = [
        model
        for model in canonical["provider"]["models"]
        if model["id"] in observed_models
    ]
    status = (
        "complete"
        if not missing and all(s["status"] == "complete" for s in sources)
        else "partial"
    )
    bootstraps = family_bootstrap(tests)
    coverage = {
        "planned": len(expected),
        "completed": len(evaluation),
        "missing": missing,
        "training_planned": configuration["planned_training_episodes"]
        * len(EXPECTED_SEEDS),
        "training_completed": sum(s.get("training_completed", 0) for s in sources),
        "training_unique_tasks": len(
            {
                record["run"]["task_id"]
                for record in full_runs
                if record["phase"] == "train"
            }
        ),
        "training_count_basis": "Validated indexed training episode artifacts, including failed episodes; not stale manifest counters",
        "evaluated_unique_tasks": len({r["task_id"] for r in evaluation}),
        "catalog_tasks": configuration["task_count"],
        "summary_split": "test",
        "test_unique_tasks": len(test_ids),
        "test_families": len({r["family"] for r in tests}),
        "seeds_planned": list(EXPECTED_SEEDS),
        "seeds_observed": sorted({r["seed"] for r in evaluation}),
    }
    report = {
        "version": "0.2",
        "status": status,
        "generated_at": utc_now(),
        "task_count": configuration["task_count"],
        "models": models,
        "policies": list(POLICIES),
        "summary": summarize(tests, len(test_ids) * len(EXPECTED_SEEDS)),
        "validation_summary": summarize(
            validation, len(validation_ids) * len(EXPECTED_SEEDS)
        ),
        "coverage": coverage,
        "runs": [public_summary(r) for r in evaluation],
        "training_runs": [
            {
                **public_summary(record["run"]),
                "phase": "train",
                "study_seed": record["study_seed"],
            }
            for record in full_runs
            if record["phase"] == "train"
        ],
        "paired_differences": bootstraps["comparisons"],
        "limitations": list(LIMITATIONS)
        + [
            "No family confidence interval is estimated with fewer than three independent held-out families. Repeated seeds do not increase the family count."
        ],
        "provenance": {
            "protocol": "forgebench-v0.2-three-seed",
            "requested_seeds": list(EXPECTED_SEEDS),
            "sources": sources,
            "task_manifest_sha256": canonical["task_manifest_sha256"],
            "configuration": configuration,
            "provider": canonical["provider"],
            "runtime_source_sha256": canonical["runtime_source_sha256"],
            "source_manifest": canonical["source_manifest"],
            "cost_basis": canonical["provider"].get("cost_basis"),
            "controller_selection": "Separate train-only controller per seed; no selection by validation or test outcome",
            "study_ledger_delta_usd": sum(
                s.get("study_ledger_delta_usd") or 0 for s in sources
            ),
        },
    }
    return report, full_runs, bootstraps


def write_exports(output, report, full_runs, bootstraps):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "runs").mkdir(exist_ok=True)

    def write(name, payload):
        temporary = output / (name + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        temporary.replace(output / name)

    write("benchmark.json", report)
    write("bootstrap_results.json", bootstraps)
    with (output / "trajectories.jsonl").open("w") as stream:
        for record in full_runs:
            stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
            write("runs/" + record["run"]["id"] + ".json", record["run"])
    fields = [
        "id",
        "task_id",
        "family",
        "split",
        "category",
        "policy",
        "seed",
        "status",
        "solved",
        "public_passed",
        "public_total",
        "heldout_passed",
        "heldout_total",
        *METRICS,
        "success_after_repair",
        "stop_reason",
        "failure_labels",
    ]
    with (output / "results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for run in report["runs"]:
            writer.writerow(
                {**run, "failure_labels": ";".join(run.get("failure_labels", []))}
            )
    fields = [
        "split",
        "policy",
        "label",
        "observed_runs",
        "denominator_runs",
        "frequency",
        "interpretation",
    ]
    with (output / "failure_analysis.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for split in ("validation", "test"):
            for policy in POLICIES:
                rows = [
                    r
                    for r in report["runs"]
                    if r["split"] == split and r["policy"] == policy
                ]
                for label in sorted(
                    {label for r in rows for label in r.get("failure_labels", [])}
                ):
                    count = sum(label in r.get("failure_labels", []) for r in rows)
                    writer.writerow(
                        {
                            "split": split,
                            "policy": policy,
                            "label": label,
                            "observed_runs": count,
                            "denominator_runs": len(rows),
                            "frequency": count / len(rows),
                            "interpretation": "Observed proxy, not a causal model reasoning attribution",
                        }
                    )
    exports = [
        "benchmark.json",
        "bootstrap_results.json",
        "trajectories.jsonl",
        "results.csv",
        "failure_analysis.csv",
    ]
    write(
        "export-manifest.json",
        {
            "generated_at": utc_now(),
            "files": {name: sha(output / name) for name in exports},
            "run_sources": {
                record["run"]["id"]: record["source_sha256"] for record in full_runs
            },
            "published_runs": {
                record["run"]["id"]: sha(
                    output / "runs" / (record["run"]["id"] + ".json")
                )
                for record in full_runs
            },
            "run_count": len(full_runs),
        },
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--study", action="append", required=True, metavar="SEED=DIRECTORY"
    )
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    studies = {}
    for item in args.study:
        seed, separator, directory = item.partition("=")
        if not separator or not directory or not seed.isdigit() or int(seed) in studies:
            cli.error("Specify each --study SEED=DIRECTORY once")
        studies[int(seed)] = Path(directory)
    report, runs, bootstraps = aggregate_studies(studies)
    write_exports(args.output, report, runs, bootstraps)
    print(
        json.dumps(
            {
                "status": report["status"],
                "coverage": report["coverage"],
                "output": str(args.output),
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
