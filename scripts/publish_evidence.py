"""Import completed, independently captured evaluation runs; no model requests."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forgerl.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    benchmark = json.loads((args.artifacts / "benchmark.json").read_text())
    assert benchmark["status"] == "complete"
    policy = args.artifacts / "studies/seed17/controller.json"
    expected = benchmark["provenance"]["production_controller"]["artifact_sha256"]
    assert hashlib.sha256(policy.read_bytes()).hexdigest() == expected
    assert (
        hashlib.sha256((args.artifacts / "policy.json").read_bytes()).hexdigest()
        == expected
    )
    store = Store(args.db)
    count = 0
    for seed in (17, 29, 43):
        root = args.artifacts / "studies" / f"seed{seed}"
        manifest = json.loads((root / "manifest.json").read_text())
        assert manifest["status"] == "complete"
        for line in (root / "raw-runs.jsonl").read_text().splitlines():
            row = json.loads(line)
            if row.get("kind") != "prospective-evaluation":
                continue
            result = row["run"]
            result.setdefault("evidence", {})["study_seed"] = seed
            result["evidence"]["evaluation_source"] = (
                "prospective held-out or validation episode"
            )
            store.add_recorded(result)
            count += 1
    assert count == 144
    print(
        json.dumps(
            {
                "recorded_evaluations_imported": count,
                "test_episodes": 72,
                "validation_episodes": 72,
                "production_seed": 17,
                "policy_sha256": expected,
            }
        )
    )


if __name__ == "__main__":
    main()
