"""The public API never needs model credentials, the ledger or executor access."""

import importlib
from fastapi.testclient import TestClient
import pytest

from forgerl.recruiter import gateway
from forgerl.recruiter.state import BrokerState, POLICY, TASK_ID, Rejected
from forgerl.store import Store


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGERL_PUBLIC_INFERENCE", "0")
    monkeypatch.setenv("FORGERL_RECRUITER_ORIGINS", "https://testserver")
    monkeypatch.setenv("FORGERL_DB", str(tmp_path / "public-must-not-create.sqlite3"))
    monkeypatch.delenv("FORGERL_RECRUITER_BROKER_SOCKET", raising=False)
    from forgerl import app as module

    module = importlib.reload(module)

    def forbidden(*a, **k):
        pytest.fail("Public process accessed model/ledger credentials")

    monkeypatch.setattr(module, "make_provider", forbidden)
    monkeypatch.setattr(module, "load_secret", forbidden)
    monkeypatch.setattr(module, "Store", forbidden)
    with TestClient(
        module.app, base_url="https://testserver", client=("198.51.100.1", 50000)
    ) as client:
        yield client, monkeypatch, tmp_path
    assert not (tmp_path / "public-must-not-create.sqlite3").exists()


def test_default_disabled_never_creates_session_or_paid_admission(setup):
    client, _, _ = setup
    assert client.get("/api/recruiter-live/state").json()["available"] is False
    for route in ("session", "runs"):
        response = client.post(
            "/api/recruiter-live/" + route, headers={"Origin": "https://testserver"}
        )
        assert response.status_code == 403
        assert "set-cookie" not in response.headers


def test_all_recruiter_responses_are_private_no_store_including_errors(setup):
    client, monkeypatch, tmp_path = setup
    state, _ = install_broker(monkeypatch, tmp_path)
    responses = [
        client.get("/api/recruiter-live/state"),
        client.post("/api/recruiter-live/session"),
        client.post("/api/recruiter-live/runs", content="x" * 3000),
        client.get("/api/recruiter-live/runs/invalid"),
        client.get("/api/recruiter-live/unknown"),
    ]
    session = client.post("/api/recruiter-live/session", headers={"Origin": "https://testserver"})
    responses.append(session)
    job = client.post("/api/recruiter-live/runs", headers={"Origin": "https://testserver", "X-CSRF-Token": session.json()["csrf"]}, json={"task_id": TASK_ID, "policy": POLICY})
    responses.extend([job, client.get("/api/recruiter-live/runs/" + job.json()["id"])])

    async def unexpected(*args, **kwargs):
        raise RuntimeError("private internal error")

    monkeypatch.setattr(gateway, "broker", unexpected)
    failed = client.get("/api/recruiter-live/state")
    assert failed.status_code == 503 and "private internal error" not in failed.text
    responses.append(failed)
    for response in responses:
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["pragma"] == "no-cache"


def install_broker(monkeypatch, tmp_path):
    ledger = tmp_path / "private.sqlite3"
    Store(ledger)
    state = BrokerState(ledger, b"private-broker-session-fixture" * 2)
    calls = []

    async def ipc(route, payload=None):
        calls.append((route, payload))
        try:
            if route == "/session":
                return 200, state.start_session(payload["client"])
            if route == "/runs":
                return 200, state.admit(
                    payload["session"],
                    payload["client"],
                    payload["csrf"],
                    payload["task_id"],
                    payload["policy"],
                )
            if route == "/view":
                return 200, state.view(
                    payload["id"], payload["session"], payload["client"]
                )
            return 200, {"available": True, "task_id": TASK_ID, "policy": POLICY}
        except Rejected as error:
            return error.status, {"code": error.code, "message": error.message}

    monkeypatch.setenv("FORGERL_RECRUITER_BROKER_SOCKET", "/private/test-broker.sock")
    monkeypatch.setattr(gateway, "broker", ipc)
    return state, calls


def test_gateway_origin_csrf_fixed_request_and_http_only_cookie(setup):
    client, monkeypatch, tmp_path = setup
    state, calls = install_broker(monkeypatch, tmp_path)
    for headers in (
        {},
        {"Origin": "https://evil.invalid"},
        {"Origin": "https://testserver", "Sec-Fetch-Site": "cross-site"},
    ):
        assert (
            client.post("/api/recruiter-live/session", headers=headers).status_code
            == 403
        )
    assert not calls
    response = client.post(
        "/api/recruiter-live/session", headers={"Origin": "https://testserver"}
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    csrf = response.json()["csrf"]
    payload = {"task_id": TASK_ID, "policy": POLICY}
    assert (
        client.post(
            "/api/recruiter-live/runs",
            json=payload,
            headers={"Origin": "https://testserver"},
        ).status_code
        == 403
    )
    headers = {"Origin": "https://testserver", "X-CSRF-Token": csrf}
    assert (
        client.post(
            "/api/recruiter-live/runs",
            json={**payload, "code": "untrusted"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/recruiter-live/runs",
            json={"task_id": "custom", "policy": POLICY},
            headers=headers,
        ).status_code
        == 422
    )
    response = client.post("/api/recruiter-live/runs", json=payload, headers=headers)
    assert response.status_code == 202
    ident = response.json()["id"]
    assert (
        client.post(
            "/api/recruiter-live/runs", json=payload, headers=headers
        ).status_code
        == 409
    )
    result = client.get("/api/recruiter-live/runs/" + ident)
    assert result.status_code == 200 and result.json()["mode"] == "live_curated"
    assert "client_hash" not in result.text and "csrf" not in result.text
    with state.store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM charges").fetchone()[0] == 0


def test_broker_failure_has_recorded_fallback_not_fabricated_output(setup):
    client, monkeypatch, _ = setup
    monkeypatch.setenv("FORGERL_RECRUITER_BROKER_SOCKET", "/private/unavailable.sock")

    async def unavailable(*a, **k):
        return 503, {
            "code": "broker_unavailable",
            "message": "Recorded replay remains available.",
        }

    monkeypatch.setattr(gateway, "broker", unavailable)
    result = client.get("/api/recruiter-live/state").json()
    assert result["available"] is False and result["mode"] == "recorded_fallback"
    assert "result" not in result
