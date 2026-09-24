"""Private broker state and atomic limits on the original durable ledger."""

from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
import re
import time
import uuid

from ..store import Store, BudgetExceeded

TASK_ID = "binary_protocol-repair-1"
POLICY = "cheap_only"
DAY_MICRO = 50_000
MONTH_MICRO = 1_000_000
REQUEST_MICRO = 5_000
SESSION_TTL = 900
QUEUE_TTL = 180
RETENTION_SECONDS = 7 * 86400
RUN_PREFIX = "recruiter-live:"


class Rejected(ValueError):
    def __init__(self, code, message, status=429):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def boundaries(now):
    current = datetime.fromtimestamp(now, timezone.utc)
    day = current.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    month = current.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    return day, month


class BrokerState:
    def __init__(self, ledger, secret, *, clock=time.time):
        if not ledger.is_file():
            raise ValueError(
                "Use the existing ledger; a new financial allowance is forbidden"
            )
        if len(secret) < 32:
            raise ValueError("Broker session secret must contain at least 32 bytes")
        if (
            Store.CAPS != {"research": 12_000_000, "public": 8_000_000}
            or Store.TOTAL_CAP != 20_000_000
        ):
            raise ValueError(
                "The original lifetime ledger limits must remain unchanged"
            )
        self.store, self.secret, self.clock = Store(ledger), secret, clock
        with self.store.connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS recruiter_sessions (
                    id TEXT PRIMARY KEY, client_hash TEXT NOT NULL, csrf_hash TEXT NOT NULL,
                    created REAL NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS recruiter_jobs (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, client_hash TEXT NOT NULL,
                    created REAL NOT NULL, expires REAL NOT NULL, status TEXT NOT NULL,
                    result_json TEXT, events_json TEXT NOT NULL DEFAULT '[]');
                CREATE INDEX IF NOT EXISTS recruiter_jobs_client ON recruiter_jobs(client_hash,created);
            """)

    def private_hash(self, value):
        return hmac.new(self.secret, str(value).encode(), hashlib.sha256).hexdigest()

    def limits(self, c, now):
        day, month = boundaries(now)
        rows = c.execute("SELECT bucket,charged,created FROM charges").fetchall()
        public = [r for r in rows if r["bucket"] == "public"]
        return {
            "day_micro": sum(r["charged"] for r in public if r["created"] >= day),
            "month_micro": sum(r["charged"] for r in public if r["created"] >= month),
            "public_micro": sum(r["charged"] for r in public),
            "global_micro": sum(r["charged"] for r in rows),
            "rolling_public_micro": sum(
                r["charged"] for r in public if r["created"] > now - 86400
            ),
            "disabled": bool(
                c.execute(
                    "SELECT 1 FROM settings WHERE name='provider_disabled'"
                ).fetchone()
            ),
        }

    def available(self, *, minimum=REQUEST_MICRO):
        with self.store.connect() as c:
            limits = self.limits(c, self.clock())
            queued = c.execute(
                "SELECT COUNT(*) FROM recruiter_jobs WHERE status='queued' AND expires>?",
                (self.clock(),),
            ).fetchone()[0]
        if limits["disabled"]:
            return (
                False,
                "provider_paused",
                "The live trial is paused. Recorded replay remains available.",
            )
        if (
            limits["day_micro"] + minimum > DAY_MICRO
            or limits["month_micro"] + minimum > MONTH_MICRO
            or limits["public_micro"] + minimum > self.store.CAPS["public"]
            or limits["global_micro"] + minimum > self.store.TOTAL_CAP
        ):
            return (
                False,
                "budget_limit",
                "The shared live allowance is used up. Recorded replay remains available.",
            )
        if queued >= 2:
            return (
                False,
                "queue_full",
                "The live queue is full. Explore a recorded run while it clears.",
            )
        return (
            True,
            None,
            "One fixed task, one new model request; separate from benchmark results.",
        )

    def start_session(self, client):
        self.prune()
        now = self.clock()
        hashed = self.private_hash(client)
        sid, csrf = secrets.token_hex(24), secrets.token_urlsafe(32)
        with self.store.transaction() as c:
            recent = c.execute(
                "SELECT COUNT(*) FROM recruiter_sessions WHERE client_hash=? AND created>?",
                (hashed, now - 600),
            ).fetchone()[0]
            total = c.execute(
                "SELECT COUNT(*) FROM recruiter_sessions WHERE created>?", (now - 600,)
            ).fetchone()[0]
            if recent >= 3 or total >= 100:
                raise Rejected(
                    "session_limit",
                    "Please use recorded replay and try the live trial later.",
                )
            c.execute(
                "INSERT INTO recruiter_sessions VALUES(?,?,?,?,?,0)",
                (sid, hashed, self.private_hash(csrf), now, now + SESSION_TTL),
            )
        token = sid + "." + self.private_hash(sid)
        return {"session": token, "csrf": csrf, "expires_in": SESSION_TTL}

    def prune(self):
        """Expire terminal trial payloads only; financial evidence is permanent."""
        now = self.clock()
        with self.store.transaction() as c:
            c.execute(
                "DELETE FROM recruiter_jobs WHERE created<? AND status NOT IN ('queued','running')",
                (now - RETENTION_SECONDS,),
            )
            c.execute(
                "DELETE FROM recruiter_sessions WHERE expires<? AND id NOT IN (SELECT session_id FROM recruiter_jobs)",
                (now,),
            )

    def session(self, c, token, client, csrf=None):
        try:
            sid, signature = token.split(".")
        except (AttributeError, ValueError):
            raise Rejected("session", "Start a new live-trial session.", 403) from None
        if (
            not re.fullmatch(r"[a-f0-9]{48}", sid)
            or not re.fullmatch(r"[a-f0-9]{64}", signature)
            or not hmac.compare_digest(signature, self.private_hash(sid))
        ):
            raise Rejected("session", "Start a new live-trial session.", 403)
        row = c.execute(
            "SELECT * FROM recruiter_sessions WHERE id=?", (sid,)
        ).fetchone()
        if (
            not row
            or row["expires"] < self.clock()
            or row["client_hash"] != self.private_hash(client)
        ):
            raise Rejected("session", "This live-trial session expired.", 403)
        if csrf is not None and not hmac.compare_digest(
            row["csrf_hash"], self.private_hash(csrf)
        ):
            raise Rejected("csrf", "The live-trial request could not be verified.", 403)
        return row

    def admit(self, token, client, csrf, task_id, policy):
        if task_id != TASK_ID or policy != POLICY:
            raise Rejected(
                "curated_only", "Only the fixed demonstration is available.", 422
            )
        now = self.clock()
        ident = uuid.uuid4().hex
        with self.store.transaction() as c:
            session = self.session(c, token, client, csrf)
            if session["used"]:
                raise Rejected(
                    "replayed_request", "This session already started its trial.", 409
                )
            day, _ = boundaries(now)
            prior = c.execute(
                "SELECT 1 FROM recruiter_jobs WHERE client_hash=? AND created>=?",
                (session["client_hash"], day),
            ).fetchone()
            if prior:
                raise Rejected(
                    "client_limit",
                    "One live trial per client each UTC day. Recorded runs remain available.",
                )
            limits = self.limits(c, now)
            if (
                limits["disabled"]
                or limits["day_micro"] + REQUEST_MICRO > DAY_MICRO
                or limits["month_micro"] + REQUEST_MICRO > MONTH_MICRO
                or limits["public_micro"] + REQUEST_MICRO > self.store.CAPS["public"]
                or limits["global_micro"] + REQUEST_MICRO > self.store.TOTAL_CAP
            ):
                raise Rejected(
                    "budget_limit",
                    "The shared live allowance is used up. Try recorded replay.",
                )
            c.execute(
                "UPDATE recruiter_jobs SET status='expired' WHERE status='queued' AND expires<?",
                (now,),
            )
            active = c.execute(
                "SELECT COUNT(*) FROM recruiter_jobs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            queued = c.execute(
                "SELECT COUNT(*) FROM recruiter_jobs WHERE status='queued'"
            ).fetchone()[0]
            if active >= 3 or queued >= 2:
                raise Rejected(
                    "queue_full", "The live queue is full. Try recorded replay."
                )
            c.execute(
                "UPDATE recruiter_sessions SET used=1 WHERE id=?", (session["id"],)
            )
            c.execute(
                "INSERT INTO recruiter_jobs(id,session_id,client_hash,created,expires,status) VALUES(?,?,?,?,?,'queued')",
                (ident, session["id"], session["client_hash"], now, now + QUEUE_TTL),
            )
        return {
            "id": ident,
            "status": "queued",
            "mode": "live_curated",
            "is_benchmark": False,
        }

    def claim(self):
        now = self.clock()
        with self.store.transaction() as c:
            c.execute(
                "UPDATE recruiter_jobs SET status='expired' WHERE status='queued' AND expires<?",
                (now,),
            )
            if c.execute(
                "SELECT 1 FROM recruiter_jobs WHERE status='running'"
            ).fetchone():
                return None
            row = c.execute(
                "SELECT * FROM recruiter_jobs WHERE status='queued' ORDER BY created,id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            c.execute(
                "UPDATE recruiter_jobs SET status='running' WHERE id=? AND status='queued'",
                (row["id"],),
            )
        return dict(row)

    def append_event(self, ident, event):
        with self.store.transaction() as c:
            row = c.execute(
                "SELECT events_json FROM recruiter_jobs WHERE id=?", (ident,)
            ).fetchone()
            events = json.loads(row[0])
            events.append(event)
            c.execute(
                "UPDATE recruiter_jobs SET events_json=? WHERE id=?",
                (json.dumps(events, allow_nan=False), ident),
            )

    def finish(self, ident, result):
        with self.store.transaction() as c:
            c.execute(
                "UPDATE recruiter_jobs SET status=?,result_json=? WHERE id=? AND status='running'",
                (result["status"], json.dumps(result, allow_nan=False), ident),
            )

    def view(self, ident, token, client):
        with self.store.connect() as c:
            session = self.session(c, token, client)
            row = c.execute(
                "SELECT * FROM recruiter_jobs WHERE id=? AND session_id=?",
                (ident, session["id"]),
            ).fetchone()
        if not row:
            raise Rejected("run_missing", "Live trial not found for this session.", 404)
        return {
            "id": ident,
            "status": row["status"],
            "mode": "live_curated",
            "is_benchmark": False,
            "task_id": TASK_ID,
            "policy": POLICY,
            "created_at": row["created"],
            "events": json.loads(row["events_json"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
        }

    def recover(self):
        # Never recover unrelated research reservations or rerun an interrupted job.
        with self.store.transaction() as c:
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM recruiter_jobs WHERE status='running'"
                )
            ]
            for ident in ids:
                c.execute(
                    "UPDATE charges SET status='uncertain' WHERE status='reserved' AND run_id=?",
                    (RUN_PREFIX + ident,),
                )
                c.execute(
                    "UPDATE recruiter_jobs SET status='interrupted' WHERE id=?",
                    (ident,),
                )

    def reserve(self, model, micro_usd, run_id):
        if (
            type(micro_usd) is not int
            or not 0 < micro_usd <= REQUEST_MICRO
            or model != "openai/gpt-oss-20b"
            or not re.fullmatch(r"recruiter-live:[a-f0-9]{32}", run_id)
        ):
            raise BudgetExceeded("Live-trial request exceeds its fixed allowance")
        now = self.clock()
        ident = uuid.uuid4().hex
        with self.store.transaction() as c:
            limits = self.limits(c, now)
            if limits["disabled"]:
                raise BudgetExceeded("Live trial is paused")
            if (
                limits["day_micro"] + micro_usd > DAY_MICRO
                or limits["month_micro"] + micro_usd > MONTH_MICRO
                or limits["public_micro"] + micro_usd > self.store.CAPS["public"]
                or limits["global_micro"] + micro_usd > self.store.TOTAL_CAP
                or limits["rolling_public_micro"] + micro_usd > 1_000_000
            ):
                raise BudgetExceeded("Live-trial day/month/lifetime allowance reached")
            if c.execute("SELECT 1 FROM charges WHERE run_id=?", (run_id,)).fetchone():
                raise BudgetExceeded(
                    "The live trial already made its one provider request"
                )
            if not c.execute(
                "SELECT 1 FROM recruiter_jobs WHERE id=? AND status='running'",
                (run_id.removeprefix(RUN_PREFIX),),
            ).fetchone():
                raise BudgetExceeded(
                    "Only an admitted running live trial may reserve a request"
                )
            c.execute(
                "INSERT INTO charges VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    ident,
                    "public",
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


class PublicChargeAdapter:
    """Private-only adapter: repository provider calls charge public, never research."""

    def __init__(self, state, job_id):
        self.state, self.job_id = state, job_id

    def reserve(self, bucket, model, amount, run_id=None):
        if bucket != "research" or run_id != self.job_id:
            raise BudgetExceeded("Unexpected live-trial provider reservation")
        return self.state.reserve(model, amount, RUN_PREFIX + self.job_id)

    def settle(self, ident, amount, usage=None):
        return self.state.store.settle(ident, amount, usage)

    def transaction(self):
        return self.state.store.transaction()
