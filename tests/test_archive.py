"""The public pilot viewer reads a sealed derivative, never the research ledger."""
from contextlib import closing
import hashlib
import sqlite3

import pytest

from forgerl.archive import ReadOnlyArchive
from forgerl.store import Store


@pytest.fixture
def sealed_archive(tmp_path):
    source = tmp_path / "private.sqlite3"
    store = Store(source)
    for number in (1, 2):
        store.add_recorded({
            "id": f"recorded-{number}", "task_id": "slug-spacing", "policy": "fixed",
            "status": "completed", "solved": number == 2, "created_at": 100 + number,
            "tokens": 20 * number, "cost_usd": .001 * number,
            "session_hash": "must-not-appear", "ip_hash": "must-not-appear",
            "events": [{"kind": "inspect", "title": "Recorded task"}, {"kind": "tests", "title": "Recorded checks"}],
        })
    destination = tmp_path / "published snapshot.sqlite3"
    with closing(sqlite3.connect(source)) as original:
        with closing(sqlite3.connect(destination)) as snapshot:
            original.backup(snapshot)
            assert snapshot.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    destination.chmod(0o444)
    return destination


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sealed_archive_preserves_runs_events_and_has_no_write_surface(sealed_archive, monkeypatch):
    archive = ReadOnlyArchive(sealed_archive)
    before_hash, before_mtime = digest(sealed_archive), sealed_archive.stat().st_mtime_ns
    before_files = sorted(path.name for path in sealed_archive.parent.iterdir())
    actual_connect = sqlite3.connect
    connections = []

    def checked_connect(database_uri, **kwargs):
        assert kwargs.get("uri") is True
        assert "mode=ro" in database_uri and "immutable=1" in database_uri
        # A space in the published filename must not break the URI.
        assert "%20" in database_uri
        connection = actual_connect(database_uri, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", checked_connect)
    runs = archive.runs(20)
    assert [run["id"] for run in runs] == ["recorded-2", "recorded-1"]
    assert runs[0]["solved"] is True and runs[1]["solved"] is False
    assert runs[0]["tokens"] == 40 and runs[0]["cost_usd"] == .002
    assert runs[0]["mode"] == "recorded"
    assert "session_hash" not in runs[0] and "ip_hash" not in runs[0]
    assert [event["seq"] for event in archive.events("recorded-2")] == [1, 2]
    assert [event["seq"] for event in archive.events("recorded-2", 1)] == [2]
    assert archive.run("absent") is None and archive.events("absent") == []
    assert len(archive.runs(1)) == 1
    assert archive.run("recorded-1")["events"][1]["kind"] == "tests"
    for method in ("budget", "reserve", "admit", "claim", "recover", "transaction", "finish_run", "add_event"):
        assert not hasattr(archive, method)
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    assert digest(sealed_archive) == before_hash
    assert sealed_archive.stat().st_mtime_ns == before_mtime
    assert sorted(path.name for path in sealed_archive.parent.iterdir()) == before_files
    assert not any(sealed_archive.parent.glob(sealed_archive.name + "-*"))


def test_archive_connection_cannot_mutate_even_when_file_mode_is_writable(sealed_archive):
    sealed_archive.chmod(0o644)
    archive = ReadOnlyArchive(sealed_archive)
    before = digest(sealed_archive)
    with closing(archive._connect()) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM runs")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE accidental_write (value TEXT)")
    assert digest(sealed_archive) == before
    assert len(archive.runs()) == 2


def test_missing_archive_creates_neither_database_nor_directory(tmp_path):
    missing = tmp_path / "absent-directory" / "archive.sqlite3"
    archive = ReadOnlyArchive(missing)
    assert archive.runs() == []
    assert archive.run("missing") is None
    assert archive.events("missing") == []
    assert not missing.exists() and not missing.parent.exists()


def test_unsealed_wal_snapshot_is_not_silently_read(sealed_archive):
    sidecar = sealed_archive.with_name(sealed_archive.name + "-wal")
    sidecar.write_bytes(b"uncheckpointed")
    with pytest.raises(sqlite3.OperationalError, match="sealed snapshot"):
        ReadOnlyArchive(sealed_archive).runs()


def test_queries_are_parameterized_and_never_interpret_identifiers_as_sql(sealed_archive):
    archive = ReadOnlyArchive(sealed_archive)
    assert archive.run("' OR 1=1 --") is None
    assert archive.events("' OR 1=1 --") == []
    assert len(archive.runs()) == 2
