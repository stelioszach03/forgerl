"""Paid end-to-end acceptance, explicitly excluded from research metrics."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forgerl.orchestrator import Episode
from forgerl.provider import make_provider
from forgerl.tasks import list_tasks


async def main():
    if "--execute" not in sys.argv:
        print("Add --execute to permit two budgeted model requests.")
        return
    provider = make_provider("research")
    provider.store.import_calibration()
    task = list_tasks()[0]
    for action in ("fast", "deliberate"):
        episode = Episode(
            task,
            provider,
            policy_id="fixed" if action == "fast" else "deliberate",
            seed=17,
        )
        await episode.start()
        await episode.step(action)
        result = await episode.finish()
        result["evidence"]["purpose"] = (
            "Integration smoke; excluded from the benchmark."
        )
        provider.store.add_recorded(result)
        path = Path(os.environ.get("FORGERL_EVIDENCE_DIR", "data"))
        path.mkdir(parents=True, exist_ok=True)
        (path / f"smoke-{action}.json").write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in (
                        "id",
                        "policy",
                        "status",
                        "steps",
                        "tokens",
                        "cost_usd",
                        "public_passed",
                        "public_total",
                        "heldout_passed",
                        "heldout_total",
                        "solved",
                    )
                }
            ),
            flush=True,
        )
    await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
