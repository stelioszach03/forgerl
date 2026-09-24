"""Private UDS boundary with a synthetic ledger; no model/executor credentials."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from pathlib import Path
import tempfile

import httpx
import pytest
import uvicorn

from forgerl.recruiter import broker
from forgerl.recruiter.state import BrokerState
from forgerl.store import Store


@pytest.mark.asyncio
async def test_real_unix_socket_accepts_bounded_session_but_tcp_scope_is_rejected(
    tmp_path, monkeypatch
):
    ledger = tmp_path / "ledger.sqlite3"
    Store(ledger)
    state = BrokerState(ledger, b"test-private-session-secret" * 2)

    @asynccontextmanager
    async def fake_lifespan(app):
        app.state.broker = state
        app.state.worker = SimpleNamespace(done=lambda: False)
        yield

    monkeypatch.setattr(broker.app.router, "lifespan_context", fake_lifespan)
    # macOS limits sockaddr_un paths to 104 bytes; pytest's normal temp root is
    # longer. This isolated short socket directory is removed after the check.
    socket_directory = tempfile.TemporaryDirectory(prefix="fr-", dir="/tmp")
    socket = Path(socket_directory.name) / "broker.sock"
    server = uvicorn.Server(
        uvicorn.Config(
            broker.app,
            uds=str(socket),
            proxy_headers=False,
            log_level="error",
            access_log=False,
        )
    )
    running = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(socket)),
            base_url="http://private",
        ) as client:
            response = await client.get("/state")
            assert response.status_code == 200 and response.json()["available"] is True
            session = await client.post(
                "/session",
                json={
                    "origin": "https://forge.stelioszach.com",
                    "client": "198.51.100.1",
                },
            )
            assert session.status_code == 200 and session.json()["csrf"]
            rejected = await client.post(
                "/session",
                json={"origin": "https://evil.invalid", "client": "198.51.100.1"},
            )
            assert rejected.status_code == 403
            for reply in (response, session, rejected):
                assert reply.headers["cache-control"] == "private, no-store"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=broker.app, client=("127.0.0.1", 9999)),
            base_url="http://private",
        ) as client:
            response = await client.get("/state")
            assert (
                response.status_code == 403
                and response.json()["code"] == "private_transport"
            )
            assert response.headers["cache-control"] == "private, no-store"
    finally:
        server.should_exit = True
        await running
        socket_directory.cleanup()


def test_live_error_trace_does_not_expose_internal_paths_or_credentials():
    result = broker.safe_result(
        {
            "status": "failed",
            "error": "secret at /etc/forgerl/openrouter.key",
            "api_key": "fixture-secret",
            "events": [
                {
                    "kind": "error",
                    "data": {
                        "error": "fixture-secret at /var/lib/ledger",
                        "authorization": "fixture-secret",
                        "cost_usd": 0.001,
                    },
                }
            ],
        }
    )
    import json

    text = json.dumps(result)
    assert (
        "fixture-secret" not in text and "/etc/" not in text and "/var/lib/" not in text
    )
    assert result["events"][0]["data"]["cost_usd"] == 0.001
