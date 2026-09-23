#!/usr/bin/env python3
"""Plan-only by default; execute one separate $1-capped GPT-4.1 reference study."""

from __future__ import annotations
import argparse
import asyncio
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REFERENCE_ROOT = ROOT / "artifacts" / "forgebench" / "reference"


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--execute-reference", action="store_true")
    cli.add_argument(
        "--db", type=Path, help="Existing service spend ledger; never a new database"
    )
    cli.add_argument(
        "--key-file",
        type=Path,
        help="Private credential file; defaults to systemd credentials when available",
    )
    cli.add_argument("--output", type=Path)
    cli.add_argument("--max-cost-usd", type=float, default=1.0)
    return cli


async def main(args):
    from forgerl.bench.reference import (
        ReferenceProvider,
        reference_plan,
        run_reference,
        verify_catalog,
    )
    from forgerl.bench.tasks import list_tasks

    tasks = list_tasks()
    planned = reference_plan(tasks, args.max_cost_usd)
    output = args.output or REFERENCE_ROOT / (
        "gpt41-seed17-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    if not output.resolve().is_relative_to(REFERENCE_ROOT.resolve()):
        raise ValueError(
            "Reference output must remain under artifacts/forgebench/reference"
        )
    print(
        json.dumps(
            {**planned, "execute": args.execute_reference, "output": str(output)},
            indent=2,
        )
    )
    if not args.execute_reference:
        print(
            "Plan only: no credential read, catalog request, ledger access or inference."
        )
        return 0
    if not args.db or not args.db.is_file():
        raise ValueError("Reference execution requires the EXISTING service ledger")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Use a new reference evidence directory")
    with args.db.with_suffix(".forgebench.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                "Another primary/reference study is using the existing ledger"
            ) from None
        catalog = await verify_catalog()
        from forgerl.store import Store

        key_path = args.key_file or (
            Path(os.environ["CREDENTIALS_DIRECTORY"]) / "openrouter-key"
            if os.environ.get("CREDENTIALS_DIRECTORY")
            else Path("/etc/forgerl/openrouter.key")
        )
        key = key_path.read_text().strip()
        if not key:
            raise ValueError("Private reference credential is empty")
        provider = ReferenceProvider(Store(args.db), key)
        try:
            report = await run_reference(
                tasks,
                provider,
                output,
                catalog_receipt=catalog,
                max_cost_usd=args.max_cost_usd,
            )
            print(
                json.dumps(
                    {
                        "status": report["status"],
                        "coverage": report["coverage"],
                        "summary": report["summary"],
                        "output": str(output),
                    },
                    indent=2,
                )
            )
            return 0 if report["status"] == "complete" else 2
        finally:
            await provider.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(parser().parse_args())))
