"""Single-worker public research application with a durable bounded job queue."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
from functools import lru_cache
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from . import __version__
from .orchestrator import Episode
from .provider import MODELS, BudgetExceeded, ProviderError, make_provider
from .store import AdmissionError, Store
from .tasks import get_task, list_tasks, public_task

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = os.environ.get("FORGERL_PUBLIC_ORIGIN", "https://stelioszach.com")
POLICIES = [
    {
        "id": "deliberate",
        "label": "Extended model · default",
        "description": "Use the extended-budget model with visible-test feedback. This is the product default, separate from the experimental learned policy.",
    },
    {
        "id": "fixed",
        "label": "Fixed · short budget",
        "description": "Use the short-budget model until visible tests pass or the shared step cap is reached.",
    },
    {
        "id": "heuristic",
        "label": "Rule-based routing",
        "description": "Escalate after visible failures using an explicit rule.",
    },
    {
        "id": "adaptive",
        "label": "Learned controller",
        "description": "A frozen controller trained on separate task families; language-model weights remain unchanged.",
    },
]
log = logging.getLogger("forgerl")


def artifact():
    path = Path(
        os.environ.get("FORGERL_POLICY_FILE", str(ROOT / "artifacts/policy.json"))
    )
    if path.is_file():
        try:
            result = json.loads(path.read_text())
            from .controller import controller_status

            return result if controller_status(result)["trained"] else None
        except (OSError, json.JSONDecodeError):
            return None
    return None


def load_secret():
    path = os.environ.get("FORGERL_SESSION_KEY_FILE")
    if not path and os.environ.get("CREDENTIALS_DIRECTORY"):
        path = str(Path(os.environ["CREDENTIALS_DIRECTORY"]) / "session-key")
    if path:
        return Path(path).read_bytes().strip()
    value = os.environ.get("FORGERL_SESSION_KEY")
    if value:
        return value.encode()
    # Not deployment-ready without a stable private signing key.
    return None


def problem(status, code, message):
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def worker(app):
    store = app.state.store
    last_expiry = 0
    retry_delay = 1
    while True:
        try:
            if time.monotonic() - last_expiry > 3600:
                await asyncio.to_thread(store.expire_identifiers)
                last_expiry = time.monotonic()
            row = await asyncio.to_thread(store.claim)
            retry_delay = 1
        except sqlite3.Error as exc:
            log.warning("Queue storage temporarily unavailable: %s", type(exc).__name__)
            await asyncio.sleep(retry_delay)
            retry_delay = min(30, retry_delay * 2)
            continue
        if not row:
            await asyncio.sleep(0.7)
            continue
        episode = None
        try:
            task = get_task(row["task_id"])
            provider = make_provider("public", store.path)

            async def event_callback(event):
                await asyncio.to_thread(store.add_event, row["id"], event)

            episode = Episode(
                task,
                provider,
                row["policy"],
                event_callback=event_callback,
                artifact=artifact(),
            )
            episode.id = row["id"]
            episode.created_at = row["created"]
            async with asyncio.timeout(510):
                await episode.start()
                from .controller import choose_action

                while not episode.terminal:
                    action = choose_action(
                        row["policy"], episode.observation(), episode.artifact
                    )
                    await episode.step(action)
                    interim = episode.result()
                    interim["mode"] = "live"
                    await asyncio.to_thread(store.finish_run, row["id"], interim)
                result = await episode.finish()
        except BudgetExceeded:
            result = episode.result() if episode else {}
            result.update(
                status="budget_exhausted",
                error="The shared live inference allowance has been reached.",
                stop_reason="inference_budget",
            )
        except (ProviderError, TimeoutError) as exc:
            result = episode.result() if episode else {}
            result.update(
                status="failed",
                error=str(exc)
                if isinstance(exc, ProviderError)
                else "The run reached its wall-clock limit.",
                stop_reason="provider_error"
                if isinstance(exc, ProviderError)
                else "wall_clock_limit",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Run failed internally; run_id=%s", row["id"])
            result = episode.result() if episode else {}
            result.update(
                status="failed",
                error="This run could not be completed. No result is claimed.",
                stop_reason="execution_error",
            )
        result.update(
            id=row["id"],
            task_id=row["task_id"],
            policy=row["policy"],
            mode="live",
            created_at=row["created"],
        )
        await asyncio.to_thread(store.finish_run, row["id"], result)


@asynccontextmanager
async def lifespan(app):
    app.state.store = Store()
    app.state.secret = load_secret()
    app.state.store.recover()
    work = (
        asyncio.create_task(worker(app))
        if os.environ.get("FORGERL_WORKER", "1") == "1"
        else None
    )
    app.state.worker_task = work
    yield
    if work:
        work.cancel()
        try:
            await work
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="ForgeRL",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method == "POST":
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            size = 99999
        if size > 2048 or request.headers.get("transfer-encoding"):
            return JSONResponse(
                {
                    "detail": {
                        "code": "request_too_large",
                        "message": "Request exceeds the public limit.",
                    }
                },
                status_code=413,
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def origin_check(request):
    if request.headers.get("origin") != ORIGIN:
        raise problem(
            403,
            "origin",
            "Open the demo on its configured public website to start a run.",
        )


def signed(secret, value):
    return hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()


def session(request):
    secret = request.app.state.secret
    if not secret:
        raise problem(503, "not_configured", "Live sessions are not configured.")
    value = request.cookies.get("forgerl_session", "")
    try:
        ident, issued, mac = value.split(".")
        valid = len(ident) == 32 and 0 <= time.time() - int(issued) < 86400
    except (ValueError, TypeError):
        valid = False
    if not valid or not hmac.compare_digest(mac, signed(secret, ident + "." + issued)):
        raise problem(403, "session", "Start a new demo session and try again.")
    return ident


def live_state(request):
    budget = request.app.state.store.budget("public")
    reason = None
    queue_worker = getattr(request.app.state, "worker_task", None)
    if queue_worker is None or queue_worker.done():
        reason = "The live queue is temporarily paused. Recorded runs remain available."
    elif not request.app.state.secret:
        reason = "Live sessions are not configured."
    elif budget["disabled"]:
        reason = "Live inference is temporarily paused. Recorded runs remain available."
    elif budget["remaining_usd"] < 0.35:
        reason = (
            "The shared live allowance is exhausted. Recorded runs remain available."
        )
    elif not os.environ.get("FORGERL_EXECUTOR_SOCKET"):
        reason = "The isolated execution worker is unavailable."
    else:
        try:
            make_provider("public", request.app.state.store.path)
        except (ProviderError, OSError):
            reason = "The model provider is not configured."
    return {
        "available": reason is None,
        "reason": reason,
        "remaining_usd": budget["remaining_usd"],
        "per_run_max_steps": 3,
        "accounting": budget["accounting"],
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/meta")
def meta(request: Request):
    trained = artifact() is not None
    policies = [dict(p) for p in POLICIES]
    if not trained:
        next(p for p in policies if p["id"] == "adaptive").update(
            label="Adaptive · not trained",
            description="No frozen trained artifact is available; live adaptive selection is disabled.",
        )
    return {
        "name": "ForgeRL",
        "version": __version__,
        "live": live_state(request),
        "policies": policies,
        "models": [{"id": v["model"], "label": v["label"]} for v in MODELS.values()],
        "limits": {"max_steps": 3, "daily_session_runs": 2},
        "evidence_status": "trained_controller" if trained else "not_trained",
        "links": {
            "source": "https://github.com/stelioszach03/forgerl",
            "methodology": "api/benchmark",
        },
    }


@app.get("/api/tasks")
def tasks():
    return {"tasks": [public_task(t) for t in list_tasks()]}


@app.get("/api/tasks/{ident}")
def task(ident: str):
    try:
        return public_task(get_task(ident), include_cases=True)
    except (KeyError, ValueError):
        raise problem(404, "task", "Task not found.")


@app.post("/api/session")
def create_session(request: Request, response: Response):
    origin_check(request)
    secret = request.app.state.secret
    if not secret:
        raise problem(503, "session", "Live sessions are not configured.")
    try:
        ident = session(request)
    except HTTPException:
        ident = secrets.token_hex(16)
    value = ident + "." + str(int(time.time()))
    response.set_cookie(
        "forgerl_session",
        value + "." + signed(secret, value),
        secure=ORIGIN.startswith("https://"),
        httponly=True,
        samesite="strict",
        max_age=86400,
        path="/demos/forgerl/" if ORIGIN.startswith("https://") else "/",
    )
    return {"csrf_token": signed(secret, "csrf:" + ident)}


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    policy: str = "deliberate"


@app.post("/api/runs", status_code=202)
def create_run(body: RunRequest, request: Request):
    origin_check(request)
    ident = session(request)
    secret = request.app.state.secret
    token = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(token, signed(secret, "csrf:" + ident)):
        raise problem(
            403,
            "csrf",
            "The session token has expired. Refresh the demo and try again.",
        )
    try:
        current = get_task(body.task_id)
    except (ValueError, KeyError):
        raise problem(404, "task", "Task not found.")
    if body.policy not in {p["id"] for p in POLICIES}:
        raise problem(400, "policy", "Unknown policy.")
    if body.policy == "adaptive" and artifact() is None:
        raise problem(
            503,
            "policy_not_trained",
            "The controller has not been trained yet. Choose a baseline.",
        )
    live = live_state(request)
    if not live["available"]:
        raise problem(503, "live_unavailable", live["reason"])
    # X-Forwarded-For is deliberately ignored here. Uvicorn trusts only local
    # Nginx, which overwrites its forwarded IP header before proxying requests.
    ip = request.client.host if request.client else "unknown"
    try:
        run_id = request.app.state.store.admit(
            current.id,
            body.policy,
            signed(secret, "sid:" + ident),
            signed(secret, "ip:" + ip),
        )
    except AdmissionError as exc:
        raise problem(429, "run_limit", str(exc))
    return {"id": run_id, "status": "queued", "mode": "live"}


@app.get("/api/runs")
def runs(request: Request, limit: int = 20):
    result = []
    for item in request.app.state.store.runs(limit):
        item = {
            k: v
            for k, v in item.items()
            if k not in {"events", "initial_source", "final_source", "diff"}
        }
        if not item.get("task_title"):
            try:
                item["task_title"] = get_task(item["task_id"]).title
            except KeyError:
                item["task_title"] = item["task_id"]
        result.append(item)
    return {"runs": result}


def get_run(request, ident):
    if len(ident) > 64 or not ident.replace("-", "").isalnum():
        raise problem(404, "run", "Run not found.")
    result = request.app.state.store.run(ident)
    if result is None:
        raise problem(404, "run", "Run not found.")
    return result


@app.get("/api/runs/{ident}")
def run(ident: str, request: Request):
    return get_run(request, ident)


@app.get("/api/runs/{ident}/events")
def events(ident: str, request: Request, after: int = 0):
    result = get_run(request, ident)
    values = request.app.state.store.events(ident, max(0, after))
    return {
        "events": values,
        "status": result["status"],
        "next_seq": values[-1]["seq"] if values else max(0, after),
    }


@app.get("/api/runs/{ident}/patch", response_class=PlainTextResponse)
def patch(ident: str, request: Request):
    result = get_run(request, ident)
    return PlainTextResponse(
        result.get("diff", ""),
        headers={
            "Content-Disposition": f'attachment; filename="forgerl-{ident}.patch"'
        },
    )


@app.get("/api/runs/{ident}/export")
def export(ident: str, request: Request):
    result = get_run(request, ident)
    return JSONResponse(
        result,
        headers={"Content-Disposition": f'attachment; filename="forgerl-{ident}.json"'},
    )


@lru_cache(maxsize=2)
def benchmark_view(path_string, modified_ns):
    result = json.loads(Path(path_string).read_text())
    # Comparison needs summaries; detailed sources/events have their own
    # addressable run/export routes. Avoid repeatedly shipping every trace.
    summary_fields = {
        "id",
        "task_id",
        "task_title",
        "policy",
        "status",
        "mode",
        "created_at",
        "steps",
        "tokens",
        "cost_usd",
        "elapsed_s",
        "public_passed",
        "public_total",
        "heldout_passed",
        "heldout_total",
        "solved",
        "stop_reason",
        "model_ids",
    }
    for pair in result.get("paired_runs", []):
        pair["runs"] = [
            {k: v for k, v in row.items() if k in summary_fields}
            for row in pair.get("runs", [])
        ]
    return result


@app.get("/api/benchmark")
def benchmark():
    path = Path(
        os.environ.get("FORGERL_BENCHMARK_FILE", str(ROOT / "artifacts/benchmark.json"))
    )
    if path.is_file():
        return benchmark_view(str(path), path.stat().st_mtime_ns)
    return {
        "status": "not_run",
        "summary": [],
        "paired_runs": [],
        "methodology": {
            "scope": "Authored regression tasks. Frozen language models; a separately trained finite controller.",
            "protocol": "Disjoint training, validation and held-out task families; equal three-call caps.",
        },
        "limitations": [
            "No measured benchmark has been published yet.",
            "Sandbox checks are finite tests, not a proof of correctness.",
        ],
        "provenance": {},
    }


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
