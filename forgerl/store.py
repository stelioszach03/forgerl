"""Durable queue and conservative, integer-USD inference reservations.

SQLite WAL is sufficient for one bounded VPS worker. Transactions, not process
memory, enforce the public budget and queue admission across restarts.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


class AdmissionError(RuntimeError):
    pass


class Store:
    CAPS = {"research": 12_000_000, "public": 8_000_000}
    TOTAL_CAP = 20_000_000  # $5 of the authorized $25 stays unspent as reserve.

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get("FORGERL_DB", "data/forgerl.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS charges (
                  id TEXT PRIMARY KEY,bucket TEXT NOT NULL,model TEXT NOT NULL,
                  reserved INTEGER NOT NULL,charged INTEGER NOT NULL,status TEXT NOT NULL,
                  created REAL NOT NULL,usage_json TEXT,run_id TEXT);
                CREATE INDEX IF NOT EXISTS charges_bucket ON charges(bucket,created);
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY,task_id TEXT NOT NULL,policy TEXT NOT NULL,
                  status TEXT NOT NULL,created REAL NOT NULL,session_hash TEXT,ip_hash TEXT,
                  result_json TEXT NOT NULL DEFAULT '{}',mode TEXT NOT NULL DEFAULT 'live');
                CREATE INDEX IF NOT EXISTS runs_created ON runs(created);
                CREATE TABLE IF NOT EXISTS events (
                  run_id TEXT NOT NULL,seq INTEGER NOT NULL,payload TEXT NOT NULL,
                  PRIMARY KEY(run_id,seq));
                CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY,value TEXT NOT NULL);
            """)

    def connect(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=10000")
        return c

    @contextlib.contextmanager
    def transaction(self):
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def budget(self, bucket: str) -> dict:
        if bucket not in self.CAPS:
            raise ValueError("Unknown budget bucket")
        with self.connect() as c:
            total = c.execute(
                "SELECT COALESCE(SUM(charged),0) FROM charges"
            ).fetchone()[0]
            amount = c.execute(
                "SELECT COALESCE(SUM(charged),0) FROM charges WHERE bucket=?", (bucket,)
            ).fetchone()[0]
            stopped = c.execute(
                "SELECT value FROM settings WHERE name='provider_disabled'"
            ).fetchone()
        remaining = max(0, min(self.CAPS[bucket] - amount, self.TOTAL_CAP - total))
        return {
            "bucket": bucket,
            "charged_usd": amount / 1e6,
            "remaining_usd": remaining / 1e6,
            "total_charged_usd": total / 1e6,
            "cap_usd": self.CAPS[bucket] / 1e6,
            "disabled": bool(stopped),
            "accounting": "Conservative token-rate estimates; uncertain calls retain their full reservation.",
        }

    def reserve(
        self, bucket: str, model: str, micro_usd: int, run_id: str | None = None
    ) -> str:
        if bucket not in self.CAPS or not 0 < micro_usd <= 500_000:
            raise ValueError("Invalid reservation")
        ident = uuid.uuid4().hex
        now = time.time()
        with self.transaction() as c:
            if c.execute(
                "SELECT 1 FROM settings WHERE name='provider_disabled'"
            ).fetchone():
                raise BudgetExceeded("Inference paused after an accounting discrepancy")
            total = c.execute(
                "SELECT COALESCE(SUM(charged),0) FROM charges"
            ).fetchone()[0]
            current = c.execute(
                "SELECT COALESCE(SUM(charged),0) FROM charges WHERE bucket=?", (bucket,)
            ).fetchone()[0]
            if (
                total + micro_usd > self.TOTAL_CAP
                or current + micro_usd > self.CAPS[bucket]
            ):
                raise BudgetExceeded("The project inference allowance is exhausted")
            if bucket == "public":
                daily = c.execute(
                    "SELECT COALESCE(SUM(charged),0) FROM charges WHERE bucket='public' AND created>?",
                    (now - 86400,),
                ).fetchone()[0]
                if daily + micro_usd > 1_000_000:
                    raise BudgetExceeded(
                        "Today's shared live allowance has been reached"
                    )
            c.execute(
                "INSERT INTO charges VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    ident,
                    bucket,
                    model,
                    micro_usd,
                    micro_usd,
                    "reserved",
                    now,
                    None,
                    run_id,
                ),
            )
        return ident

    def settle(self, ident: str, micro_usd: int | None, usage: dict | None = None):
        with self.transaction() as c:
            row = c.execute("SELECT * FROM charges WHERE id=?", (ident,)).fetchone()
            if row is None or row["status"] != "reserved":
                raise ValueError("Unknown or already settled reservation")
            amount = row["reserved"] if micro_usd is None else max(0, int(micro_usd))
            if amount > row["reserved"]:
                c.execute(
                    "INSERT OR REPLACE INTO settings VALUES ('provider_disabled','reservation_exceeded')"
                )
            c.execute(
                "UPDATE charges SET charged=?,status=?,usage_json=? WHERE id=?",
                (
                    amount,
                    "uncertain" if micro_usd is None else "estimated",
                    json.dumps(usage),
                    ident,
                ),
            )

    def import_calibration(self, micro_usd=770):
        with self.transaction() as c:
            c.execute(
                "INSERT OR IGNORE INTO charges VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "initial-provider-calibration",
                    "research",
                    "granite-4-0-h-small",
                    micro_usd,
                    micro_usd,
                    "estimated",
                    time.time(),
                    '{"total_tokens":77}',
                    None,
                ),
            )

    def admit(self, task_id, policy, session_hash, ip_hash) -> str:
        now, ident = time.time(), uuid.uuid4().hex
        with self.transaction() as c:
            active = c.execute(
                "SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            if active >= 3:
                raise AdmissionError(
                    "The live queue is full. Explore a recorded run while it clears."
                )
            for field, value, limit in [
                ("session_hash", session_hash, 2),
                ("ip_hash", ip_hash, 3),
            ]:
                count = c.execute(
                    f"SELECT COUNT(*) FROM runs WHERE {field}=? AND created>? AND mode='live'",
                    (value, now - 86400),
                ).fetchone()[0]
                if count >= limit:
                    raise AdmissionError(
                        "Your daily live-run allowance has been used. Recorded runs remain available."
                    )
            c.execute(
                "INSERT INTO runs(id,task_id,policy,status,created,session_hash,ip_hash) VALUES (?,?,?,'queued',?,?,?)",
                (ident, task_id, policy, now, session_hash, ip_hash),
            )
        return ident

    def claim(self):
        with self.transaction() as c:
            row = c.execute(
                "SELECT * FROM runs WHERE status='queued' ORDER BY created LIMIT 1"
            ).fetchone()
            if row:
                c.execute("UPDATE runs SET status='running' WHERE id=?", (row["id"],))
                return dict(row)
        return None

    def recover(self):
        with self.transaction() as c:
            for row in c.execute(
                "SELECT id,result_json FROM runs WHERE status='running'"
            ).fetchall():
                result = json.loads(row["result_json"])
                charges = c.execute(
                    "SELECT charged,status,usage_json FROM charges WHERE run_id=?",
                    (row["id"],),
                ).fetchall()
                if charges:
                    result["cost_usd"] = sum(r["charged"] for r in charges) / 1e6
                    result["tokens"] = None
                    result["tokens_complete"] = False
                result.update(
                    error="The worker restarted; outstanding reservations are retained and this run was not replayed.",
                    stop_reason="worker_restart",
                    solved=False,
                )
                c.execute(
                    "UPDATE runs SET status='interrupted',result_json=? WHERE id=?",
                    (json.dumps(result), row["id"]),
                )
            # Network/session identifiers are essential quota data, not analytics.
            c.execute(
                "UPDATE runs SET session_hash=NULL,ip_hash=NULL WHERE created<?",
                (time.time() - 172800,),
            )

    def expire_identifiers(self):
        with self.transaction() as c:
            c.execute(
                "UPDATE runs SET session_hash=NULL,ip_hash=NULL WHERE created<? AND (session_hash IS NOT NULL OR ip_hash IS NOT NULL)",
                (time.time() - 172800,),
            )

    def add_event(self, ident, event):
        with self.transaction() as c:
            seq = c.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (ident,)
            ).fetchone()[0]
            event = {**event, "seq": seq}
            c.execute(
                "INSERT INTO events VALUES (?,?,?)", (ident, seq, json.dumps(event))
            )
        return event

    def events(self, ident, after=0):
        with self.connect() as c:
            return [
                json.loads(r[0])
                for r in c.execute(
                    "SELECT payload FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 250",
                    (ident, after),
                )
            ]

    def finish_run(self, ident, result):
        with self.transaction() as c:
            c.execute(
                "UPDATE runs SET status=?,result_json=? WHERE id=?",
                (result["status"], json.dumps(result), ident),
            )

    def run(self, ident):
        with self.connect() as c:
            r = c.execute("SELECT * FROM runs WHERE id=?", (ident,)).fetchone()
        if not r:
            return None
        result = json.loads(r["result_json"])
        return {
            **result,
            "id": r["id"],
            "task_id": r["task_id"],
            "policy": r["policy"],
            "status": r["status"],
            "created_at": r["created"],
            "mode": r["mode"],
            "events": self.events(ident),
        }

    def runs(self, limit=20):
        with self.connect() as c:
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM runs ORDER BY created DESC LIMIT ?",
                    (min(100, max(1, limit)),),
                )
            ]
        return [self.run(i) for i in ids]

    def add_recorded(self, result):
        ident = result["id"]
        with self.transaction() as c:
            c.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,'recorded')",
                (
                    ident,
                    result["task_id"],
                    result["policy"],
                    result["status"],
                    result.get("created_at", time.time()),
                    None,
                    None,
                    json.dumps(result),
                ),
            )
            c.execute("DELETE FROM events WHERE run_id=?", (ident,))
            for n, event in enumerate(result.get("events", []), 1):
                c.execute(
                    "INSERT INTO events VALUES (?,?,?)",
                    (ident, n, json.dumps({**event, "seq": n})),
                )
