"""Read an operator-published, sealed v0.1 SQLite evidence snapshot.

This reader has no schema, queue, budget, recovery or credential operations.
The operator must create a standalone backup in DELETE journal mode and publish
it read-only; an active WAL database is not a valid immutable archive. Opening a
missing snapshot never creates a database or its parent directory.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3


class ReadOnlyArchive:
    def __init__(self, path: str | Path):
        self._path = Path(path).absolute()

    def _connect(self):
        if not self._path.exists():
            return None
        if any(Path(str(self._path) + suffix).exists() for suffix in ("-wal", "-shm")):
            raise sqlite3.OperationalError("The published archive is not a sealed snapshot")
        # as_uri escapes filenames before adding SQLite connection parameters.
        # immutable disables journal/lock side effects; mode=ro forbids writes.
        connection = sqlite3.connect(
            self._path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=5
        )
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _events(connection, ident, after=0):
        return [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT payload FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 250",
                (ident, max(0, after)),
            )
        ]

    @classmethod
    def _run(cls, connection, ident):
        row = connection.execute(
            "SELECT id,task_id,policy,status,created,mode,result_json FROM runs WHERE id=?",
            (ident,),
        ).fetchone()
        if row is None:
            return None
        result = json.loads(row["result_json"])
        if not isinstance(result, dict):
            raise sqlite3.DatabaseError("The published run artifact is not an object")
        # Network quota identifiers do not belong in the public result, even if
        # an old result_json accidentally included its source queue metadata.
        result = {
            key: value
            for key, value in result.items()
            if key not in {"session_hash", "ip_hash"}
        }
        return {
            **result,
            "id": row["id"],
            "task_id": row["task_id"],
            "policy": row["policy"],
            "status": row["status"],
            "created_at": row["created"],
            "mode": row["mode"],
            "events": cls._events(connection, ident),
        }

    def runs(self, limit=20):
        connection = self._connect()
        if connection is None:
            return []
        with closing(connection):
            ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM runs ORDER BY created DESC LIMIT ?",
                    (min(100, max(1, limit)),),
                )
            ]
            return [self._run(connection, ident) for ident in ids]

    def run(self, ident):
        connection = self._connect()
        if connection is None:
            return None
        with closing(connection):
            return self._run(connection, ident)

    def events(self, ident, after=0):
        connection = self._connect()
        if connection is None:
            return []
        with closing(connection):
            return self._events(connection, ident, after)
