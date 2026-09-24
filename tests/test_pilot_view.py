"""Public pilot views use real recorded artifacts without model/executor access."""

import hashlib
import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

PREFIX = "/api/forgebench/versions/v0.3-pilot1"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGERL_PUBLIC_INFERENCE", "0")
    monkeypatch.setenv("FORGERL_DB", str(tmp_path / "never-created.sqlite3"))
    from forgerl import app as module

    module = importlib.reload(module)

    def forbidden(*a, **kw):
        pytest.fail("Public artifact browsing accessed paid/private execution")

    monkeypatch.setattr(module, "Store", forbidden)
    monkeypatch.setattr(module, "make_provider", forbidden)
    monkeypatch.setattr(module, "load_secret", forbidden)
    with TestClient(module.app) as session:
        yield session
    assert not (tmp_path / "never-created.sqlite3").exists()


def test_actual_162_episode_pilot_is_native_and_splits_never_pool(client):
    data = client.get(PREFIX).json()
    assert data["version"] == "0.3-pilot1"
    assert data["coverage"]["completed"] == data["coverage"]["planned"] == 162
    assert len(data["runs"]) == 162 and len(data["policies"]) == 6
    assert {p["id"] for p in data["policies"]} >= {"adaptive", "supervised_cost"}
    assert all(row["n"] == 18 for row in data["summary_by_split"]["test"])
    assert all(row["n"] == 6 for row in data["summary_by_split"]["validation"])
    assert all(row["n"] == 3 for row in data["summary_by_split"]["external"])
    assert [row["solved"] for row in data["summary"]] == [16, 15, 16, 15, 16, 17]
    assert (
        client.post(
            "/api/runs", json={"task_id": "anything", "policy": "cheap_only"}
        ).status_code
        == 403
    )


def test_catalog_only_publishes_visible_source_and_checks(client):
    catalog = client.get(PREFIX + "/tasks")
    assert catalog.status_code == 200 and len(catalog.json()["tasks"]) == 27
    assert all("public_cases" not in task for task in catalog.json()["tasks"])
    task = client.get(PREFIX + "/tasks/tabular_join-repair-3")
    assert task.status_code == 200 and task.json()["public_cases"]
    assert "reference_files" not in task.text and "hidden_cases" not in task.text
    assert "hidden_cases" not in catalog.text and "reference_files" not in catalog.text
    assert client.get(PREFIX + "/tasks/not-a-task").status_code == 404


def test_walkthroughs_are_actual_runs_and_verify_links_final_source(client):
    benchmark = client.get(PREFIX).json()
    for key, example in benchmark["walkthroughs"].items():
        run = client.get(PREFIX + "/runs/" + example["run_id"]).json()
        assert run["task_id"] == example["task_id"]
        assert run["explorer"]["new_inference"] is False
        if key == "repair":
            assert run["solved"] and run["attempts"] > 1
        else:
            assert (
                not run["solved"]
                and run["verification_grader_disagreement_direction"]
                == "missed_failure"
            )
        expected = hashlib.sha256(
            json.dumps(run["final_files"], sort_keys=True).encode()
        ).hexdigest()
        assert run["explorer"]["final_source_sha256"] == expected
        seq = run["explorer"]["final_verification_event_seq"]
        event = next(e for e in run["events"] if e["seq"] == seq)
        assert event["data"]["files_sha256"] == expected
        assert event["data"]["visibility"] == "public_supplemental"
        assert "hidden_cases" not in json.dumps(run)


@pytest.mark.parametrize(
    "path",
    [
        "/runs/nothex",
        "/runs/" + "0" * 32,
        "/download/freeze.json",
        "/download/openrouter.key",
        "/tasks/..%2Fprivate",
    ],
)
def test_unknown_or_private_paths_rejected(client, path):
    assert client.get(PREFIX + path).status_code == 404


def test_private_nested_fields_scrubbed_and_symlinks_refused(
    client, monkeypatch, tmp_path
):
    from forgerl.bench import pilot_view

    monkeypatch.setenv("FORGEBENCH_PILOT_ARTIFACT_DIR", str(tmp_path))
    (tmp_path / "explorer").mkdir()
    path = tmp_path / "explorer/benchmark.json"
    path.write_text(
        json.dumps(
            {
                "runs": [],
                "hidden_cases": [{"expected": "secret"}],
                "nested": {"authorization": "secret"},
            }
        )
    )
    assert "secret" not in client.get(PREFIX).text
    path.unlink()
    actual = tmp_path / "private.json"
    actual.write_text('{"secret":"never"}')
    path.symlink_to(actual)
    assert client.get(PREFIX).status_code == 404


def test_actual_downloads_are_bounded_public_artifacts(client):
    assert (
        client.get(PREFIX + "/download/technical-report.pdf").headers["content-type"]
        == "application/pdf"
    )
    assert client.get(PREFIX + "/download/results.csv").status_code == 200
    assert client.get(PREFIX + "/download/analysis.json").json()["completed"] == 162
