"""Private Unix-socket broker for one curated live trial. Never mount publicly."""

from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .state import BrokerState, POLICY, TASK_ID, PublicChargeAdapter, Rejected
from .gateway import RecruiterNoStoreMiddleware
from ..bench.api import scrub
from ..bench.engine import RepoEpisode, run_episode
from ..bench.pilot_catalog import fresh_specs
from ..bench.provider import RepoProvider

PILOT_FREEZE = (
    Path(__file__).resolve().parents[2]
    / "artifacts/forgebench/v0.3-pilot1/study/freeze.json"
)


def curated_task():
    from ..bench.pilot import task_digest

    frozen = json.loads(PILOT_FREEZE.read_text())
    if task_digest() != frozen["configuration"]["task_manifest_sha256"]:
        raise ValueError("Curated task catalog differs from its evaluated source")
    return next(spec.task for spec in fresh_specs() if spec.task.id == TASK_ID)


def safe_result(result):
    public = scrub(result)
    if public.get("error"):
        public["error"] = safe_error(public["error"])
    public["events"] = [public_event(event) for event in public.get("events", [])]
    public["mode"], public["is_benchmark"] = "live_curated", False
    public["evidence_scope"] = (
        "One newly generated candidate for a published fixed task; not an unseen evaluation or leaderboard result."
    )
    return public


def safe_error(value):
    status = re.search(r"\bHTTP (\d{3})\b", str(value))
    return (
        "Model provider returned HTTP " + status.group(1)
        if status
        else "The bounded live trial could not complete. Recorded replay remains available."
    )


def public_event(event):
    result = scrub(event)
    if result.get("kind") == "error":
        data = result.get("data", {})
        result["data"] = {
            key: data[key]
            for key in (
                "http_status",
                "cost_usd",
                "accounting_kind",
                "provider_reported_cost_usd",
                "model",
            )
            if key in data
        }
        result["data"]["error"] = safe_error(data.get("error"))
    return result


async def work(app):
    last_cleanup = 0.0
    while True:
        now = asyncio.get_running_loop().time()
        if now - last_cleanup >= 3600:
            await asyncio.to_thread(app.state.broker.prune)
            last_cleanup = now
        job = await asyncio.to_thread(app.state.broker.claim)
        if not job:
            await asyncio.sleep(0.25)
            continue
        provider = episode = None
        try:
            provider = app.state.provider_factory(app.state.broker, job["id"])
            episode = RepoEpisode(
                app.state.curated_task,
                provider,
                POLICY,
                max_steps=1,
                max_decisions=2,
                max_cost_usd=0.005,
                rate_limit_retries=0,
                seed=int(job["id"][:8], 16),
                evaluator=getattr(app.state, "evaluator", None),
            )
            episode.id = job["id"]
            episode.max_tokens = 48000

            async def event_callback(event):
                await asyncio.to_thread(
                    app.state.broker.append_event, job["id"], public_event(event)
                )

            episode.event_callback = event_callback
            result = await asyncio.wait_for(run_episode(episode), timeout=120)
        except asyncio.TimeoutError:
            result = (
                episode.result()
                if episode
                else {"id": job["id"], "events": [], "tokens": None, "cost_usd": None}
            )
            result.update(
                status="interrupted",
                solved=False,
                error="The live-trial time limit was reached.",
                stop_reason="live_time_limit",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            result = (
                episode.result()
                if episode
                else {"id": job["id"], "events": [], "tokens": None, "cost_usd": None}
            )
            result.update(
                status="failed",
                solved=False,
                error="The live trial is unavailable. Recorded runs remain available.",
                stop_reason="live_worker_error",
            )
        finally:
            if provider:
                await provider.close()
        await asyncio.to_thread(app.state.broker.finish, job["id"], safe_result(result))


def credentials(name, explicit=None):
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    path = Path(explicit) if explicit else Path(directory) / name if directory else None
    if not path or not path.is_file():
        raise ValueError("Private broker credentials are not configured")
    return path.read_bytes().strip()


@asynccontextmanager
async def lifespan(app):
    if os.environ.get("FORGERL_RECRUITER_WORKER_ENABLED", "0") != "1":
        raise ValueError("Private live broker is disabled by default")
    ledger = Path(os.environ["FORGERL_RECRUITER_LEDGER"]).resolve()
    if not ledger.is_file() or not os.environ.get("FORGERL_EXECUTOR_SOCKET"):
        raise ValueError("Existing ledger and isolated executor socket required")
    # An OS-held lock prevents duplicate workers and unsafe restart recovery.
    lock = ledger.with_suffix(".recruiter-worker.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    app.state.broker = BrokerState(ledger, credentials("recruiter-session-secret"))
    app.state.broker.recover()
    app.state.curated_task = curated_task()
    key = credentials("openrouter-key").decode()

    def factory(state, ident):
        provider = RepoProvider(
            PublicChargeAdapter(state, ident), key, profile="openrouter"
        )
        provider.max_tokens = 2048
        return provider

    app.state.provider_factory = factory
    app.state.worker = asyncio.create_task(work(app))
    try:
        yield
    finally:
        app.state.worker.cancel()
        try:
            await app.state.worker
        except asyncio.CancelledError:
            pass
        app.state.broker.recover()
        lock.close()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def unix_only(request, call_next):
    # Uvicorn's Unix listener has no TCP client address. Refuse accidental TCP
    # exposure even if the private ASGI app is started with the wrong bind.
    if request.scope.get("client") is not None:
        return JSONResponse(
            {
                "code": "private_transport",
                "message": "Private Unix transport required.",
            },
            status_code=403,
        )
    return await call_next(request)


app.add_middleware(RecruiterNoStoreMiddleware, all_paths=True)


@app.exception_handler(Rejected)
async def rejected(request, exc):
    return JSONResponse(
        {"code": exc.code, "message": exc.message}, status_code=exc.status
    )


def origins():
    return {
        value.strip()
        for value in os.environ.get(
            "FORGERL_RECRUITER_ORIGINS",
            "https://forge.stelioszach.com,https://stelioszach.com",
        ).split(",")
        if value.strip()
    }


async def command(request, fields):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 2048:
            raise Rejected(
                "input_limit", "The live trial accepts only a small fixed request.", 413
            )
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeError):
        raise Rejected("input", "Invalid live-trial request.", 400) from None
    if (
        not isinstance(payload, dict)
        or set(payload) != set(fields)
        or any(not isinstance(v, str) or len(v) > 512 for v in payload.values())
    ):
        raise Rejected(
            "input", "Only the declared live-trial fields are accepted.", 422
        )
    if payload["origin"] not in origins():
        raise Rejected("origin", "This request origin is not allowed.", 403)
    try:
        ipaddress.ip_address(payload["client"])
    except ValueError:
        raise Rejected("client", "Client identity is unavailable.", 403) from None
    return payload


@app.get("/state")
def state(request: Request):
    alive = not request.app.state.worker.done()
    available, reason, message = request.app.state.broker.available()
    return {
        "available": available and alive,
        "reason": reason if alive else "worker_unavailable",
        "message": message
        if alive
        else "The live worker is unavailable; recorded replay remains available.",
        "task_id": TASK_ID,
        "policy": POLICY,
        "max_model_requests": 1,
        "limits": {"utc_day_usd": 0.05, "utc_month_usd": 1.0},
        "mode": "live_curated",
        "is_benchmark": False,
    }


@app.post("/session")
async def session(request: Request):
    payload = await command(request, ("origin", "client"))
    return request.app.state.broker.start_session(payload["client"])


@app.post("/runs")
async def submit(request: Request):
    payload = await command(
        request, ("origin", "client", "session", "csrf", "task_id", "policy")
    )
    if request.app.state.worker.done():
        raise Rejected("worker_unavailable", "The live worker is unavailable.", 503)
    return request.app.state.broker.admit(
        payload["session"],
        payload["client"],
        payload["csrf"],
        payload["task_id"],
        payload["policy"],
    )


@app.post("/view")
async def view(request: Request):
    payload = await command(request, ("origin", "client", "session", "id"))
    if not re.fullmatch(r"[a-f0-9]{32}", payload["id"]):
        raise Rejected("run_missing", "Live trial not found.", 404)
    return scrub(
        request.app.state.broker.view(
            payload["id"], payload["session"], payload["client"]
        )
    )
