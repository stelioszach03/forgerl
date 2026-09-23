#!/usr/bin/env python3
"""Plan or explicitly execute an immutable ForgeBench research study."""
from __future__ import annotations
import argparse
import asyncio
import fcntl
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--execute-research", action="store_true")
    cli.add_argument("--db", type=Path, help="EXISTING durable service ledger, required for paid work")
    cli.add_argument("--output", type=Path)
    cli.add_argument("--provider", choices=("openrouter", "openrouter-dev", "runpod", "together"), default="openrouter")
    cli.add_argument("--seed", type=int, default=17)
    cli.add_argument("--train-per-family", type=int, choices=range(1, 6), default=5)
    cli.add_argument("--eval-per-family", type=int, choices=range(1, 6), default=5)
    cli.add_argument("--train-rollouts", type=int, choices=range(1, 5), default=2)
    cli.add_argument("--max-steps", type=int, choices=range(1, 7), default=6)
    cli.add_argument("--max-decisions", type=int, choices=range(1, 11), default=10)
    cli.add_argument("--max-cost-usd", type=float, default=5.)
    return cli


async def main(args):
    from forgerl.bench.tasks import list_tasks, task_manifest_hash
    from forgerl.bench.study import plan, run_study
    tasks = list_tasks()
    configuration = dict(seed=args.seed, train_per_family=args.train_per_family, eval_per_family=args.eval_per_family, train_rollouts=args.train_rollouts, max_steps=args.max_steps, max_decisions=args.max_decisions, max_cost_usd=args.max_cost_usd)
    output = args.output or Path("artifacts/forgebench") / ("v0.2-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    planned = plan(tasks, **configuration)
    print(json.dumps({**planned, "execute": args.execute_research, "output": str(output), "provider": args.provider}, indent=2))
    if not args.execute_research:
        print("Plan only: no credential read, ledger opened or inference requested.")
        return 0
    if not args.db or not args.db.is_file():
        raise ValueError("Paid research requires --db pointing to the existing service ledger")
    # Independent studies cannot overlap their per-study preflight/settlement.
    with args.db.with_suffix(".forgebench.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another ForgeBench study is already using this ledger") from None
        from forgerl.bench.provider import make_provider
        provider = make_provider(db_path=args.db, profile=args.provider)
        try:
            result = await run_study(tasks, provider, output, task_manifest_hash=task_manifest_hash(), **configuration)
            print(json.dumps({"status": result["status"], "coverage": result["coverage"], "summary": result["summary"], "output": str(output)}, indent=2))
            return 0 if result["status"] == "complete" else 2
        finally:
            await provider.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(parser().parse_args())))
