"""Public gateway: bounded IPC only; no model keys, ledger or executor imports."""

import ipaddress
import json
import os
import re
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/recruiter-live")
COOKIE = "forgerl_recruiter_session"


class RecruiterNoStoreMiddleware:
    """Apply privacy headers even to rejected bodies and unexpected failures."""

    def __init__(self, app, all_paths=False):
        self.app, self.all_paths = app, all_paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (
            self.all_paths or scope.get("path", "").startswith("/api/recruiter-live")
        ):
            return await self.app(scope, receive, send)
        started = False

        async def private_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] = [
                    (k, v) for k, v in message.get("headers", [])
                    if k.lower() not in (b"cache-control", b"pragma")
                ] + [(b"cache-control", b"private, no-store"), (b"pragma", b"no-cache")]
            await send(message)

        try:
            await self.app(scope, receive, private_send)
        except Exception:
            if started:
                raise
            response = JSONResponse(
                {"detail": {"code": "live_unavailable", "message": "Live trial unavailable; recorded replay remains available."}},
                status_code=503,
            )
            await response(scope, receive, private_send)


def disabled():
    return {
        "available": False,
        "reason": "recorded_only",
        "message": "Live trials are not enabled. Recorded replay is available without model calls.",
        "mode": "recorded_fallback",
    }


def reject(code, message, status):
    return JSONResponse(
        {"detail": {"code": code, "message": message}}, status_code=status
    )


def identity(request, *, mutation=False):
    allowed = {
        v.strip()
        for v in os.environ.get(
            "FORGERL_RECRUITER_ORIGINS",
            "https://forge.stelioszach.com,https://stelioszach.com",
        ).split(",")
        if v.strip()
    }
    origin = request.headers.get("origin")
    if not mutation and not origin:
        parts = urlsplit(str(request.url))
        origin = parts.scheme + "://" + parts.netloc
    if origin not in allowed or request.headers.get("sec-fetch-site") == "cross-site":
        return None
    client = request.client.host if request.client else ""
    try:
        ipaddress.ip_address(client)
    except ValueError:
        return None
    return {"origin": origin, "client": client}


async def broker(route, payload=None):
    socket = os.environ.get("FORGERL_RECRUITER_BROKER_SOCKET")
    if not socket:
        return 503, disabled()
    transport = httpx.AsyncHTTPTransport(uds=socket)
    try:
        async with httpx.AsyncClient(
            transport=transport, timeout=3, follow_redirects=False, trust_env=False
        ) as client:
            response = await (
                client.post("http://recruiter-broker" + route, json=payload)
                if payload is not None
                else client.get("http://recruiter-broker" + route)
            )
        if len(response.content) > 2_000_000:
            return 503, {
                "code": "broker_unavailable",
                "message": "Live trial temporarily unavailable; recorded replay still works.",
            }
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid broker reply")
        return response.status_code, data
    except (httpx.HTTPError, OSError, ValueError):
        return 503, {
            "code": "broker_unavailable",
            "message": "Live trial temporarily unavailable; recorded replay still works.",
        }


@router.get("/state")
async def state():
    if not os.environ.get("FORGERL_RECRUITER_BROKER_SOCKET"):
        return disabled()
    status, data = await broker("/state")
    if status != 200:
        return {
            "available": False,
            "reason": "broker_unavailable",
            "message": "The live worker is offline. Recorded replay remains available.",
            "mode": "recorded_fallback",
        }
    return data


@router.post("/session")
async def session(request: Request):
    if not os.environ.get("FORGERL_RECRUITER_BROKER_SOCKET"):
        return reject("recorded_only", disabled()["message"], 403)
    context = identity(request, mutation=True)
    if context is None:
        return reject("origin", "The live-trial request could not be verified.", 403)
    status, data = await broker("/session", context)
    if status != 200:
        return reject(
            data.get("code", "unavailable"),
            data.get("message", "Live trial unavailable."),
            status,
        )
    response = JSONResponse({"csrf": data["csrf"], "expires_in": data["expires_in"]})
    response.set_cookie(
        COOKIE,
        data["session"],
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=data["expires_in"],
        path="/",
    )
    return response


@router.post("/runs", status_code=202)
async def submit(request: Request):
    if not os.environ.get("FORGERL_RECRUITER_BROKER_SOCKET"):
        return reject("recorded_only", disabled()["message"], 403)
    context = identity(request, mutation=True)
    if context is None:
        return reject("origin", "The live-trial request could not be verified.", 403)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 512:
            return reject(
                "input_limit", "Only a fixed demonstration request is accepted.", 413
            )
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        return reject("input", "Invalid live-trial request.", 400)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"task_id", "policy"}
        or payload != {"task_id": "binary_protocol-repair-1", "policy": "cheap_only"}
    ):
        return reject("curated_only", "No custom code or prompts are accepted.", 422)
    context.update(
        session=request.cookies.get(COOKIE, ""),
        csrf=request.headers.get("x-csrf-token", ""),
        **payload,
    )
    status, data = await broker("/runs", context)
    return JSONResponse(
        data if status == 200 else {"detail": data},
        status_code=202 if status == 200 else status,
    )


@router.get("/runs/{ident}")
async def view(ident: str, request: Request):
    if not re.fullmatch(r"[a-f0-9]{32}", ident):
        return reject("run_missing", "Live trial not found.", 404)
    context = identity(request)
    if context is None:
        return reject("origin", "The live-trial request could not be verified.", 403)
    context.update(session=request.cookies.get(COOKIE, ""), id=ident)
    status, data = await broker("/view", context)
    return JSONResponse(data if status == 200 else {"detail": data}, status_code=status)
