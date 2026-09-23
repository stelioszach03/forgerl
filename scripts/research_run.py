#!/usr/bin/env python3
"""Run the bounded ForgeRL pilot only when execution is explicitly requested."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--execute-research", action="store_true", help="Allow paid model calls through the durable research ledger")
    command.add_argument("--output", type=Path, default=None, help="New evidence directory; existing raw evidence is never overwritten")
    command.add_argument("--db", type=Path, help="Provider budget database (same durable database as the service)")
    command.add_argument("--seed", type=int, default=17)
    command.add_argument("--max-steps", type=int, choices=(1, 2, 3), default=3)
    command.add_argument("--cost-weight", type=float, default=5.0)
    return command


async def main(args: argparse.Namespace) -> int:
    from forgerl.tasks import list_tasks, task_manifest_hash
    from forgerl.research import EVALUATION_POLICIES, run_research, validate_splits
    tasks = list_tasks()
    splits = validate_splits(tasks)
    output = args.output or Path("evidence") / ("pilot-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    plan = {"execute": args.execute_research, "task_splits": {key: len(value) for key, value in splits.items()},
            "policies": EVALUATION_POLICIES, "max_steps": args.max_steps, "cost_weight": args.cost_weight,
            "output": str(output), "budget_bucket": "research", "model_weights_updated": False}
    print(json.dumps(plan, indent=2))
    if not args.execute_research:
        print("Plan only. No provider was constructed and no inference was requested.")
        return 0
    if args.cost_weight < 0:
        raise ValueError("Cost weight cannot be negative")
    if args.db:
        os.environ["FORGERL_DB"] = str(args.db.resolve())
    from forgerl.controller import choose_action, fit_q
    from forgerl.orchestrator import Episode
    from forgerl.provider import make_provider
    provider = make_provider(bucket="research", db_path=str(args.db.resolve()) if args.db else None)
    try:
        def episode_factory(task, provider, **kwargs):
            return Episode(task, provider, seed=args.seed, **kwargs)
        report = await run_research(tasks, provider, output, episode_factory=episode_factory, fit_controller=fit_q,
                                    selector=choose_action, task_manifest_hash=task_manifest_hash(),
                                    seed=args.seed, max_steps=args.max_steps, cost_weight=args.cost_weight)
        print(json.dumps({"status": report["status"], "output": str(output), "summary": report["summary"]}, indent=2))
        return 0 if report["status"] == "complete" else 2
    finally:
        closer = getattr(provider, "close", None)
        if closer:
            outcome = closer()
            if hasattr(outcome, "__await__"):
                await outcome


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(parser().parse_args())))
