"""Native read-only pilot views. No provider, ledger or executor imports."""

import hashlib
import json
import os
from pathlib import Path
import re

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse

from .api import load, unavailable

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter(prefix="/api/forgebench/versions/v0.3-pilot1")
DOWNLOADS = {
    "technical-report.pdf": ("report/pilot-report.pdf", "application/pdf"),
    "technical-report.md": ("report/pilot-report.md", "text/markdown"),
    "results.csv": ("analysis/results.csv", "text/csv"),
    "analysis.json": ("analysis/analysis.json", "application/json"),
    "trajectories.jsonl": ("explorer/trajectories.jsonl", "application/x-ndjson"),
}


def root():
    return Path(
        os.environ.get(
            "FORGEBENCH_PILOT_ARTIFACT_DIR",
            str(ROOT / "artifacts/forgebench/v0.3-pilot1"),
        )
    )


def artifact(relative):
    configured = root()
    base = configured.resolve()
    path = base / relative
    checked = path
    if configured.is_symlink():
        raise unavailable()
    while checked != base:
        if checked.is_symlink() or checked == checked.parent:
            raise unavailable()
        checked = checked.parent
    if base not in path.resolve().parents or not path.is_file():
        raise unavailable()
    return path


@router.get("")
def benchmark():
    return load(artifact("explorer/benchmark.json"))


@router.get("/tasks")
def tasks():
    result = load(artifact("explorer/tasks.json"))
    return {
        "tasks": [
            {k: v for k, v in task.items() if k != "public_cases"}
            for task in result["tasks"]
        ]
    }


@router.get("/tasks/{ident}")
def task(ident: str):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,95}", ident):
        raise unavailable("task", "Task not found.")
    for item in load(artifact("explorer/tasks.json"))["tasks"]:
        if item["id"] == ident:
            return item
    raise unavailable("task", "Task not found.")


def recorded_run(ident):
    if not re.fullmatch(r"[a-f0-9]{32}", ident) or not any(
        row["id"] == ident for row in benchmark()["runs"]
    ):
        raise unavailable("run", "Recorded run not found.")
    result = dict(load(artifact("study/runs/" + ident + ".json")))
    fingerprint = hashlib.sha256(
        json.dumps(result.get("final_files", {}), sort_keys=True).encode()
    ).hexdigest()
    verified = next(
        (
            e
            for e in reversed(result.get("events", []))
            if e.get("kind") == "tests"
            and e.get("data", {}).get("visibility") == "public_supplemental"
            and e["data"].get("files_sha256") == fingerprint
        ),
        None,
    )
    result["explorer"] = {
        "mode": "recorded",
        "final_source_sha256": fingerprint,
        "final_verification_event_seq": verified.get("seq") if verified else None,
        "new_inference": False,
    }
    return result


@router.get("/runs/{ident}")
def run(ident: str):
    return recorded_run(ident)


@router.get("/runs/{ident}/patch", response_class=PlainTextResponse)
def patch(ident: str):
    return recorded_run(ident).get("diff", "")


@router.get("/download/{name}")
def download(name: str):
    if name not in DOWNLOADS:
        raise unavailable("download", "Published download not found.")
    relative, mime = DOWNLOADS[name]
    path = artifact(relative)
    headers = (
        {"Content-Disposition": 'inline; filename="forgebench-v0.3-pilot-report.pdf"'}
        if mime == "application/pdf"
        else None
    )
    return FileResponse(
        path, media_type=mime, headers=headers, filename=None if headers else name
    )
