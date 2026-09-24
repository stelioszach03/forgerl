#!/usr/bin/env python3
"""Plan (default), audit fixtures, fit historical policies, freeze or run a pilot."""

import argparse
import asyncio
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forgerl.bench import pilot, sandbox
from forgerl.bench.engine import utc_now


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--verify-fixtures", action="store_true")
    operation.add_argument("--fit-controllers", action="store_true")
    operation.add_argument("--freeze", action="store_true")
    operation.add_argument("--execute-research", action="store_true")
    parser.add_argument("--training-root", type=Path)
    parser.add_argument("--controllers", type=Path)
    parser.add_argument("--fixture-receipt", type=Path)
    parser.add_argument("--provider-snapshot", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--frozen-protocol", type=Path)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def write_once(path, value):
    if path is None:
        print(json.dumps(value, indent=2))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")


def verify_fixtures():
    checks = []
    for spec in pilot.all_specs():
        task = spec.task
        starter = sandbox.evaluate(task, task.files)
        rows = {"starter_visible": starter}
        for key, checked, hidden in (
            ("reference_visible", task, False),
            ("reference_hidden", task, True),
            (
                "reference_supplemental",
                replace(task, public_cases=spec.verification_cases),
                False,
            ),
        ):
            rows[key] = sandbox.evaluate(checked, task.reference_files, hidden)
        passed = (
            not starter["execution_error"]
            and starter["passed"] < starter["total"]
            and all(
                not result["execution_error"] and result["passed"] == result["total"]
                for key, result in rows.items()
                if key != "starter_visible"
            )
        )
        checks.append({"task_id": task.id, "passed": passed, "checks": rows})
        print(f"{task.id}: {'PASS' if passed else 'FAIL'}", file=sys.stderr)
    return {
        "status": "passed" if all(r["passed"] for r in checks) else "failed",
        "created_at": utc_now(),
        "task_manifest_sha256": pilot.task_digest(),
        "backend": "rootless-docker-existing-isolated-executor",
        "candidate_host_execution": False,
        "sandbox_image": os.environ.get("FORGEBENCH_EVALUATED_IMAGE"),
        "tasks": len(checks),
        "checks": checks,
    }


async def main(args):
    if args.verify_fixtures:
        receipt = verify_fixtures()
        write_once(args.output, receipt)
        return 0 if receipt["status"] == "passed" else 2
    if args.fit_controllers:
        if not args.training_root:
            raise ValueError("Historical training root required")
        controllers = pilot.fit_controllers(
            [(seed, args.training_root / f"seed{seed}") for seed in pilot.SOURCE_SEEDS]
        )
        write_once(args.output, controllers)
        return 0
    if args.freeze:
        if (
            not args.controllers
            or not args.fixture_receipt
            or not args.provider_snapshot
            or not args.output
        ):
            raise ValueError(
                "Reviewed controllers, fixture receipt, provider snapshot and new output are required"
            )
        document = pilot.freeze_document(
            json.loads(args.controllers.read_text()),
            commit=args.source_commit,
            fixture_receipt=json.loads(args.fixture_receipt.read_text()),
            provider_snapshot=json.loads(args.provider_snapshot.read_text()),
        )
        write_once(args.output, document)
        return 0
    if not args.execute_research:
        print(json.dumps(pilot.plan(), indent=2))
        print("Plan only: no key, ledger, network inference or model outcome accessed.")
        return 0
    if (
        not args.db
        or not args.db.is_file()
        or not args.output
        or not args.frozen_protocol
    ):
        raise ValueError(
            "Paid execution requires existing ledger, fresh evidence output and frozen protocol"
        )
    frozen = json.loads(args.frozen_protocol.read_text())
    pilot.verify_freeze(frozen)
    with args.db.with_suffix(".forgebench.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        from forgerl.bench.provider import make_provider

        provider = make_provider(db_path=args.db, profile="openrouter")
        try:
            result = await pilot.run_pilot(provider, args.output, frozen)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "complete" else 2
        finally:
            await provider.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(cli())))
