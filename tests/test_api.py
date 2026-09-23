import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGERL_DB", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("FORGERL_WORKER", "0")
    monkeypatch.setenv("FORGERL_POLICY_FILE", str(tmp_path / "no-policy.json"))
    monkeypatch.setenv("FORGERL_BENCHMARK_FILE", str(tmp_path / "no-benchmark.json"))
    monkeypatch.setenv(
        "FORGERL_SESSION_KEY", "test-only-signing-key-not-a-production-credential"
    )
    monkeypatch.setenv("FORGERL_PUBLIC_ORIGIN", "http://testserver")
    monkeypatch.setenv("FORGERL_EXECUTOR_SOCKET", "/test-only-executor.sock")
    monkeypatch.setenv("RUNPOD_API_KEY", "test-only-never-sent")
    monkeypatch.delenv("RUNPOD_API_KEY_FILE", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    import forgerl.app

    module = importlib.reload(forgerl.app)
    with TestClient(module.app) as test:
        yield test


def credentials(client):
    r = client.post("/api/session", headers={"Origin": "http://testserver"})
    assert r.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": r.json()["csrf_token"]}


def test_public_tasks_never_serialize_hidden_expected_outputs(client):
    rows = client.get("/api/tasks").json()["tasks"]
    assert len(rows) == 24
    detail = client.get("/api/tasks/" + rows[0]["id"]).json()
    assert "hidden_cases" not in detail and "public_tests" in detail
    meta = client.get("/api/meta").json()
    assert meta["evidence_status"] == "not_trained"
    assert meta["policies"][0]["id"] == "deliberate"
    assert (
        "not trained"
        in next(p for p in meta["policies"] if p["id"] == "adaptive")["label"]
    )
    assert (
        next(p for p in meta["policies"] if p["id"] == "heuristic")["label"]
        == "Rule-based routing"
    )


def test_cross_origin_and_missing_csrf_cannot_start_paid_work(client):
    assert (
        client.post(
            "/api/session", headers={"Origin": "https://untrusted.invalid"}
        ).status_code
        == 403
    )
    headers = credentials(client)
    task = client.get("/api/tasks").json()["tasks"][0]["id"]
    assert (
        client.post(
            "/api/runs",
            json={"task_id": task, "policy": "fixed"},
            headers={"Origin": "http://testserver"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/runs",
            json={"task_id": task, "policy": "fixed", "source": "arbitrary code"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/runs",
            json={"task_id": "../../etc/passwd", "policy": "fixed"},
            headers=headers,
        ).status_code
        == 404
    )


def test_public_limits_and_untrained_policy_fail_closed(client):
    headers = credentials(client)
    task = client.get("/api/tasks").json()["tasks"][0]["id"]
    assert (
        client.post(
            "/api/runs", json={"task_id": task, "policy": "adaptive"}, headers=headers
        ).status_code
        == 503
    )
    for _ in range(2):
        r = client.post(
            "/api/runs", json={"task_id": task, "policy": "fixed"}, headers=headers
        )
        assert r.status_code == 202
        detail = client.get("/api/runs/" + r.json()["id"]).json()
        assert "session_hash" not in detail and "ip_hash" not in detail
    assert (
        client.post(
            "/api/runs", json={"task_id": task, "policy": "fixed"}, headers=headers
        ).status_code
        == 429
    )


def test_no_fake_benchmark_and_headers(client):
    response = client.get("/api/benchmark")
    assert response.json()["status"] == "not_run" and response.json()["summary"] == []
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert client.get("/api/runs/not-a-real-run").status_code == 404
    assert client.get("/../provider.py").status_code == 404
