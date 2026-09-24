#!/usr/bin/env python3
"""Read-only audit. Writes JSON to stdout; never fits a model or reads keys."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forgerl.bench.support_audit import audit_studies


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--study", action="append", required=True, metavar="SEED=DIRECTORY"
    )
    parser.add_argument("--require-propensity", action="store_true")
    args = parser.parse_args()
    try:
        studies = [
            (int(seed), path)
            for seed, path in (item.split("=", 1) for item in args.study)
        ]
        report = audit_studies(studies, require_propensity=args.require_propensity)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
