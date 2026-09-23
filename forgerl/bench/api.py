"""Read-only published-artifact endpoints. No model or executor credentials."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from .tasks import get_task, list_tasks, public_task, task_manifest_hash

router = APIRouter(prefix="/api/forgebench")
ROOT = Path(__file__).resolve().parents[2]
POLICIES = [
    {"id": "strong_only", "label": "Strong model only"},
    {"id": "cheap_only", "label": "Cheap model only"},
    {"id": "escalate_on_failure", "label": "Escalate on failure"},
    {"id": "static_router", "label": "Hand-written router"},
    {"id": "adaptive", "label": "ForgeRL adaptive"},
]


def artifact_root():
    return Path(
        os.environ.get(
            "FORGEBENCH_ARTIFACT_DIR", str(ROOT / "artifacts/forgebench/v0.2")
        )
    )


def unavailable(
    code="artifact", message="Published artifact is unavailable.", status=404
):
    return HTTPException(status, detail={"code": code, "message": message})


@lru_cache(maxsize=32)
def read_json(filename: str, modified: int, size: int):
    if size > 12_000_000:
        raise unavailable(status=503)
    try:
        value = json.loads(Path(filename).read_text())
    except (OSError, ValueError):
        raise unavailable(status=503) from None
    if not isinstance(value, dict):
        raise unavailable(status=503)
    return scrub(value)


def scrub(value):
    # Defense in depth against accidentally publishing a task dataclass or an
    # internal provenance object; real hidden grading emits only case counts.
    denied = {
        "hidden_cases",
        "reference_files",
        "hidden_inputs",
        "hidden_expected",
        "api_key",
        "authorization",
        "session_hash",
        "ip_hash",
    }
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k.lower() not in denied}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def load(path):
    if not path.is_file() or path.is_symlink():
        raise unavailable()
    info = path.stat()
    return read_json(str(path), info.st_mtime_ns, info.st_size)


@router.get("")
def benchmark():
    path = artifact_root() / "benchmark.json"
    catalog = list_tasks()
    catalog_metadata = {
        "task_count": len(catalog),
        "family_count": len({t.family for t in catalog}),
        "task_manifest_hash": task_manifest_hash(),
        "public_mode": "recorded_only",
    }
    if path.is_file():
        result = dict(load(path))
        result["catalog"] = catalog_metadata
        result.setdefault("policies", POLICIES)
        return result
    return {
        "version": "0.2",
        "status": "not_run",
        "generated_at": None,
        "task_count": len(catalog),
        "catalog": catalog_metadata,
        "models": [],
        "policies": POLICIES,
        "summary": [],
        "coverage": {"planned": 0, "completed": 0, "missing": 0},
        "runs": [],
        "limitations": [
            "The catalog is implemented; this release has no published model evaluation yet.",
            "These are authored miniature repositories, not real-world long-horizon task evidence.",
        ],
        "provenance": {"task_manifest_hash": task_manifest_hash()},
        "links": {
            "source": "https://github.com/stelioszach03/forgerl",
            "methodology": "https://github.com/stelioszach03/forgerl/blob/main/docs/forgebench/PROTOCOL.md",
            "pilot": "index.html#experiments",
        },
    }


@router.get("/tasks")
def tasks():
    return {"tasks": [public_task(t) for t in list_tasks()]}


@router.get("/tasks/{ident}")
def task(ident: str):
    try:
        return public_task(get_task(ident), include_cases=True)
    except (KeyError, ValueError):
        raise unavailable("task", "Task not found.") from None


def run_file(ident):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", ident):
        raise unavailable("run", "Recorded run not found.")
    return artifact_root() / "runs" / (ident + ".json")


@router.get("/runs/{ident}")
def run(ident: str):
    return load(run_file(ident))


@router.get("/runs/{ident}/patch", response_class=PlainTextResponse)
def patch(ident: str):
    result = load(run_file(ident))
    return result.get("diff", "")
