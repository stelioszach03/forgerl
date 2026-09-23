"""Public evidence access must never arm paid inference or reveal trusted fixtures."""

from __future__ import annotations

import importlib
import json
import os
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from forgerl.bench.tasks import RepoTask


@pytest.fixture
def public_bench(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGERL_PUBLIC_INFERENCE", raising=False)
    # Even a configured worker and credentials must not override default read-only.
    monkeypatch.setenv("FORGERL_WORKER", "1")
    monkeypatch.setenv("FORGERL_DB", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("FORGERL_POLICY_FILE", str(tmp_path / "no-policy.json"))
    monkeypatch.setenv("FORGERL_BENCHMARK_FILE", str(tmp_path / "no-pilot.json"))
    monkeypatch.setenv("FORGERL_PUBLIC_ORIGIN", "http://testserver")
    monkeypatch.setenv("FORGERL_SESSION_KEY", "test-only-unused-secret")
    monkeypatch.setenv("RUNPOD_API_KEY", "test-only-unused-provider-key")
    monkeypatch.setenv("FORGERL_EXECUTOR_SOCKET", "/test-only-unused.sock")
    artifacts = tmp_path / "artifacts"
    (artifacts / "runs").mkdir(parents=True)
    monkeypatch.setenv("FORGEBENCH_ARTIFACT_DIR", str(artifacts))

    from forgerl.bench import api
    import forgerl.app

    module = importlib.reload(forgerl.app)
    task = RepoTask(
        id="catalog-fixture",
        title="Authored fixture",
        family="catalog-family",
        split="test",
        category="multi_file",
        difficulty="medium",
        summary="A fixture without host execution.",
        description="Preserve input values.",
        files={
            "service.py": "from rules import check\n",
            "rules.py": "def check(x): return False\n",
        },
        reference_files={"service.py": "reference-private-marker"},
        entrypoint="service:run",
        public_cases=({"name": "visible", "args": [1], "expected": 1},),
        hidden_cases=(
            {
                "name": "private-check-marker",
                "args": [42],
                "expected": "private-answer-marker",
            },
        ),
        allowed_edit_files=("service.py", "rules.py"),
        success_criterion="All visible and held-out cases pass.",
        tags=("authored",),
    )
    monkeypatch.setattr(api, "list_tasks", lambda: (task,))
    monkeypatch.setattr(api, "task_manifest_hash", lambda: "fixture-manifest-sha256")

    def get_task(ident):
        if ident == task.id:
            return task
        raise KeyError(ident)

    def forbidden(*args, **kwargs):
        pytest.fail("Read-only public browsing attempted to initialize paid execution")

    async def forbidden_worker(*args, **kwargs):
        forbidden()

    monkeypatch.setattr(api, "get_task", get_task)
    monkeypatch.setattr(module, "make_provider", forbidden)
    monkeypatch.setattr(module, "load_secret", forbidden)
    monkeypatch.setattr(module, "worker", forbidden_worker)
    monkeypatch.setattr(module, "Store", forbidden)
    api.read_json.cache_clear()
    with TestClient(module.app) as client:
        yield SimpleNamespace(
            client=client,
            module=module,
            artifacts=artifacts,
            task=task,
            api=api,
            archive_path=tmp_path / "api.sqlite3",
        )
    api.read_json.cache_clear()


def write_artifact(path, data):
    path.write_text(json.dumps(data))


def test_default_public_mode_has_no_worker_provider_session_or_queue_admission(
    public_bench,
):
    client = public_bench.client
    assert client.app.state.worker_task is None
    assert client.app.state.secret is None
    assert not public_bench.archive_path.exists()
    assert not hasattr(client.app.state.store, "budget")
    meta = client.get("/api/meta").json()
    assert meta["live"]["available"] is False
    assert meta["live"]["per_run_max_steps"] == 0
    for origin in ("http://testserver", "https://other.invalid"):
        session = client.post("/api/session", headers={"Origin": origin})
        assert session.status_code == 403
        assert session.json()["detail"]["code"] == "recorded_only"
        assert "set-cookie" not in session.headers
        run = client.post(
            "/api/runs",
            json={"task_id": "slug-spacing", "policy": "fixed"},
            headers={"Origin": origin},
        )
        assert run.status_code == 403
        assert run.json()["detail"]["code"] == "recorded_only"
    assert not client.cookies
    assert client.app.state.store.runs(20) == []
    assert client.get("/api/runs").json() == {"runs": []}
    assert client.get("/api/runs/absent").status_code == 404
    assert not public_bench.archive_path.exists()
    assert not list(public_bench.archive_path.parent.glob("api.sqlite3*"))
    assert client.get("/api/health").json()["status"] == "ok"


def test_catalog_and_detail_publish_visible_files_but_never_reference_or_hidden_cases(
    public_bench,
):
    client = public_bench.client
    catalog = client.get("/api/forgebench/tasks")
    detail = client.get("/api/forgebench/tasks/catalog-fixture")
    assert catalog.status_code == detail.status_code == 200
    public = catalog.json()["tasks"][0]
    assert public["files"] == public_bench.task.files
    assert public["allowed_edit_files"] == ["service.py", "rules.py"]
    assert "public_cases" not in public
    assert detail.json()["public_cases"][0]["name"] == "visible"
    for response in (catalog, detail):
        for private in (
            "reference_files",
            "hidden_cases",
            "private-check-marker",
            "private-answer-marker",
            "reference-private-marker",
        ):
            assert private not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/forgebench/tasks/absent").status_code == 404


def test_absent_benchmark_is_explicit_not_run_without_models_or_measured_rows(
    public_bench,
):
    result = public_bench.client.get("/api/forgebench")
    assert result.status_code == 200
    payload = result.json()
    assert payload["status"] == "not_run"
    assert payload["generated_at"] is None
    assert payload["models"] == payload["summary"] == payload["runs"] == []
    assert len(payload["policies"]) == 5
    assert payload["task_count"] == 1
    assert payload["catalog"] == {
        "task_count": 1,
        "family_count": 1,
        "task_manifest_hash": "fixture-manifest-sha256",
        "public_mode": "recorded_only",
    }
    assert payload["coverage"] == {"planned": 0, "completed": 0, "missing": 0}


def test_partial_benchmark_keeps_incomplete_coverage_null_measurements_and_actual_rows(
    public_bench,
):
    artifact = {
        "version": "0.2",
        "status": "partial",
        "models": ["actual-model"],
        "summary": [
            {"policy": "cheap_only", "n": 2, "solved": 0, "mean_cost_usd": None}
        ],
        "coverage": {
            "completed": 2,
            "planned": 10,
            "missing": [{"task_id": "missing"}],
        },
        "runs": [],
    }
    write_artifact(public_bench.artifacts / "benchmark.json", artifact)
    payload = public_bench.client.get("/api/forgebench").json()
    assert payload["summary"] == artifact["summary"]
    assert payload["coverage"] == artifact["coverage"]
    assert payload["status"] == "partial"
    assert payload["models"] == ["actual-model"]
    assert payload["catalog"]["public_mode"] == "recorded_only"


def test_stored_run_and_plain_text_patch_retain_evidence_and_scrub_nested_private_fields(
    public_bench,
):
    private = "do-not-publish-private"
    artifact = {
        "id": "actual-run",
        "status": "failed",
        "heldout_passed": None,
        "cost_usd": 0.04,
        "diff": "--- a/service.py\n+++ b/service.py\n@@ -1 +1 @@\n-old\n+new\n",
        "reference_files": {"service.py": private},
        "api_key": private,
        "events": [
            {
                "kind": "prompt",
                "data": {
                    "prompt_messages": [{"role": "user", "content": "visible request"}],
                    "Authorization": private,
                    "hidden_cases": [{"expected": private}],
                    "nested": [
                        {
                            "session_hash": private,
                            "ip_hash": private,
                            "hidden_inputs": private,
                            "hidden_expected": private,
                            "public_outcome": "kept",
                        }
                    ],
                },
            }
        ],
    }
    write_artifact(public_bench.artifacts / "runs/actual-run.json", artifact)
    response = public_bench.client.get("/api/forgebench/runs/actual-run")
    assert response.status_code == 200
    assert private not in response.text
    payload = response.json()
    assert (
        payload["status"] == "failed"
        and payload["heldout_passed"] is None
        and payload["cost_usd"] == 0.04
    )
    assert (
        payload["events"][0]["data"]["prompt_messages"][0]["content"]
        == "visible request"
    )
    assert payload["events"][0]["data"]["nested"] == [{"public_outcome": "kept"}]
    patch = public_bench.client.get("/api/forgebench/runs/actual-run/patch")
    assert patch.status_code == 200 and patch.text == artifact["diff"]
    assert patch.headers["content-type"].startswith("text/plain")
    assert patch.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "ident",
    [
        "..",
        "../outside",
        "foo/bar",
        "_invalid",
        "a" * 97,
        "bad.name",
        "bad%name",
        "bad\\name",
    ],
)
def test_invalid_identifiers_cannot_resolve_files(public_bench, ident):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as failure:
        public_bench.api.run_file(ident)
    assert failure.value.status_code == 404


def test_http_traversal_and_unpublished_run_ids_are_not_served(public_bench):
    write_artifact(
        public_bench.artifacts / "outside.json", {"private": "outside-marker"}
    )
    for url in (
        "/api/forgebench/runs/absent",
        "/api/forgebench/runs/%2e%2e%2foutside",
        "/api/forgebench/runs/foo%2fbar",
        "/api/forgebench/runs/_hidden",
        "/api/forgebench/runs/absent/patch",
    ):
        response = public_bench.client.get(url)
        assert response.status_code == 404
        assert "outside-marker" not in response.text


def test_symlink_artifacts_fail_closed(public_bench, tmp_path):
    target = tmp_path / "private.json"
    write_artifact(target, {"private": "symlink-private-marker"})
    (public_bench.artifacts / "runs/linked.json").symlink_to(target)
    (public_bench.artifacts / "benchmark.json").symlink_to(target)
    for url in (
        "/api/forgebench",
        "/api/forgebench/runs/linked",
        "/api/forgebench/runs/linked/patch",
    ):
        response = public_bench.client.get(url)
        assert response.status_code == 404
        assert "symlink-private-marker" not in response.text


def test_published_artifact_cache_invalidates_after_atomic_replacement(public_bench):
    path = public_bench.artifacts / "runs/revision.json"
    write_artifact(path, {"id": "revision", "status": "partial", "steps": 1})
    before = path.stat().st_mtime_ns
    assert public_bench.client.get("/api/forgebench/runs/revision").json()["steps"] == 1
    replacement = path.with_suffix(".next")
    write_artifact(replacement, {"id": "revision", "status": "completed", "steps": 2})
    os.utime(replacement, ns=(before + 2_000_000, before + 2_000_000))
    replacement.replace(path)
    changed = public_bench.client.get("/api/forgebench/runs/revision").json()
    assert changed["steps"] == 2 and changed["status"] == "completed"


@pytest.mark.parametrize("body", ["not json", "[]", '"scalar"', "null"])
def test_malformed_artifact_is_unavailable_without_internal_paths(public_bench, body):
    path = public_bench.artifacts / "runs/broken.json"
    path.write_text(body)
    response = public_bench.client.get("/api/forgebench/runs/broken")
    assert response.status_code == 503
    assert response.json()["detail"]["message"] == "Published artifact is unavailable."
    assert str(public_bench.artifacts) not in response.text


def test_oversized_artifact_is_rejected_before_json_parsing(public_bench):
    path = public_bench.artifacts / "runs/oversized.json"
    with path.open("wb") as output:
        output.truncate(12_000_001)
    assert public_bench.client.get("/api/forgebench/runs/oversized").status_code == 503


def test_public_home_is_current_benchmark_with_archive_access_and_no_post_endpoints(
    public_bench,
):
    client = public_bench.client
    home = client.get("/")
    assert home.status_code == 200 and "ForgeBench" in home.text
    script = re.search(r'src="(bench\.js(?:\?[^\"]*)?)"', home.text)
    assert script is not None
    assert client.get('/' + script.group(1)).status_code == 200
    assert "Run repair" not in home.text
    assert client.get("/index.html").status_code == 200
    assert "script-src 'self'" in home.headers["content-security-policy"]
    for path in (
        "/api/forgebench",
        "/api/forgebench/tasks",
        "/api/forgebench/runs/new",
    ):
        assert client.post(path, json={"task_id": "catalog-fixture"}).status_code == 405


def test_download_allowlist_missing_files_and_symlinks(public_bench):
    client = public_bench.client
    path = public_bench.artifacts / "results.csv"
    assert client.get("/api/forgebench/download/results.csv").status_code == 404
    path.write_text("policy,cost\ncheap_only,0.001\n")
    response = client.get("/api/forgebench/download/results.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert client.get("/api/forgebench/download/controller.json").status_code == 404
    pdf = public_bench.artifacts / "technical-report.pdf"
    pdf.symlink_to(path)
    assert (
        client.get("/api/forgebench/download/technical-report.pdf").status_code == 404
    )
    write_artifact(
        public_bench.artifacts / "benchmark.json",
        {"status": "partial", "summary": [], "runs": []},
    )
    assert client.get("/api/forgebench").json()["downloads"] == ["results.csv"]
