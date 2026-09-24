"""Private-broker state tests; all charges are isolated synthetic ledger rows."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import uuid

import pytest

from forgerl.store import Store, BudgetExceeded
from forgerl.recruiter.state import (
    BrokerState,
    Rejected,
    PublicChargeAdapter,
    TASK_ID,
    POLICY,
    RUN_PREFIX,
    RETENTION_SECONDS,
)


@pytest.fixture
def state(tmp_path):
    ledger = tmp_path / "existing.sqlite3"
    Store(ledger)
    now = [datetime(2026, 9, 24, tzinfo=timezone.utc).timestamp()]
    state = BrokerState(
        ledger, b"test-session-secret-never-a-provider-key" * 2, clock=lambda: now[0]
    )
    state.test_clock = now
    return state


def admitted(state, client="198.51.100.1"):
    session = state.start_session(client)
    job = state.admit(session["session"], client, session["csrf"], TASK_ID, POLICY)
    return session, job


def financial_fixture(state, amount, *, bucket="public", created=None):
    now = state.clock() if created is None else created
    with state.store.transaction() as c:
        c.execute(
            "INSERT INTO charges VALUES(?,?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                bucket,
                "fixture",
                amount,
                amount,
                "uncertain",
                now,
                None,
                "historical-fixture",
            ),
        )


def running_fixture(state):
    ident = uuid.uuid4().hex
    with state.store.transaction() as c:
        c.execute(
            "INSERT INTO recruiter_jobs(id,session_id,client_hash,created,expires,status) VALUES(?,?,?,?,?,'running')",
            (
                ident,
                "quota-fixture",
                "quota-fixture",
                state.clock(),
                state.clock() + 900,
            ),
        )
    return ident


def test_retention_never_removes_financial_rows_or_pending_work(state):
    _, done = admitted(state)
    state.claim()
    charge = state.reserve("openai/gpt-oss-20b", 1000, RUN_PREFIX + done["id"])
    state.store.settle(charge, 200, {"cost": 0.0002})
    state.finish(done["id"], {"status": "completed", "events": ["payload"]})
    _, running = admitted(state, "198.51.100.2")
    state.claim()
    pending = state.reserve("openai/gpt-oss-20b", 1000, RUN_PREFIX + running["id"])
    _, queued = admitted(state, "198.51.100.3")
    state.test_clock[0] += RETENTION_SECONDS + 1
    state.prune()
    with state.store.connect() as c:
        jobs = {row["id"]: row["status"] for row in c.execute("SELECT * FROM recruiter_jobs")}
        assert jobs == {running["id"]: "running", queued["id"]: "queued"}
        assert c.execute("SELECT COUNT(*) FROM recruiter_sessions").fetchone()[0] == 2
        assert c.execute("SELECT SUM(charged) FROM charges").fetchone()[0] == 1200
    state.recover()
    state.prune()
    with state.store.connect() as c:
        assert c.execute("SELECT status,charged FROM charges WHERE id=?", (pending,)).fetchone()[:] == ("uncertain", 1000)
        assert c.execute("SELECT COUNT(*) FROM charges").fetchone()[0] == 2
        assert state.limits(c, state.clock())["global_micro"] == 1200
        assert c.execute("SELECT id FROM recruiter_jobs").fetchone()[0] == queued["id"]


def test_existing_ledger_required_no_replacement_created(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(ValueError, match="existing ledger"):
        BrokerState(path, b"x" * 32)
    assert not path.exists()


def test_fixed_input_session_csrf_ip_binding_and_one_use(state):
    session = state.start_session("198.51.100.1")
    for client, csrf in (("198.51.100.2", session["csrf"]), ("198.51.100.1", "wrong")):
        with pytest.raises(Rejected):
            state.admit(session["session"], client, csrf, TASK_ID, POLICY)
    with pytest.raises(Rejected, match="fixed"):
        state.admit(
            session["session"],
            "198.51.100.1",
            session["csrf"],
            "arbitrary-code",
            POLICY,
        )
    job = state.admit(
        session["session"], "198.51.100.1", session["csrf"], TASK_ID, POLICY
    )
    with pytest.raises(Rejected, match="already"):
        state.admit(
            session["session"], "198.51.100.1", session["csrf"], TASK_ID, POLICY
        )
    assert (
        state.view(job["id"], session["session"], "198.51.100.1")["status"] == "queued"
    )
    other = state.start_session("198.51.100.2")
    with pytest.raises(Rejected, match="not found"):
        state.view(job["id"], other["session"], "198.51.100.2")


def test_one_active_and_two_queued_with_expiry(state):
    admitted(state)
    first = state.claim()
    assert first
    assert state.claim() is None
    admitted(state, "198.51.100.2")
    admitted(state, "198.51.100.3")
    with pytest.raises(Rejected, match="full"):
        admitted(state, "198.51.100.4")
    state.test_clock[0] += 181
    state.finish(first["id"], {"status": "completed"})
    assert state.claim() is None


def test_session_expiry_and_network_daily_admission_limit(state):
    admitted(state)
    with pytest.raises(Rejected, match="UTC day"):
        admitted(state)
    session = state.start_session("198.51.100.10")
    state.test_clock[0] += 901
    with pytest.raises(Rejected, match="expired"):
        state.admit(
            session["session"], "198.51.100.10", session["csrf"], TASK_ID, POLICY
        )


def test_atomic_daily_limit_counts_all_existing_public_reservations(state):
    financial_fixture(state, 40_000)
    ids = [running_fixture(state) for _ in range(8)]

    def reserve(ident):
        try:
            return state.reserve("openai/gpt-oss-20b", 5_000, RUN_PREFIX + ident)
        except BudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(reserve, ids))
    assert sum(r is not None for r in receipts) == 2
    with state.store.connect() as c:
        assert state.limits(c, state.clock())["day_micro"] == 50_000


def test_month_cap_survives_new_utc_day_and_restart(state):
    financial_fixture(state, 995_000, created=state.clock() - 86400)
    ident = running_fixture(state)
    state.reserve("openai/gpt-oss-20b", 5_000, RUN_PREFIX + ident)
    restarted = BrokerState(state.store.path, state.secret, clock=state.clock)
    state.test_clock[0] += 86400
    with pytest.raises(BudgetExceeded, match="allowance"):
        restarted.reserve("openai/gpt-oss-20b", 1, RUN_PREFIX + running_fixture(state))
    with state.store.connect() as c:
        assert state.limits(c, state.clock())["month_micro"] == 1_000_000


@pytest.mark.parametrize(
    "bucket,amount", [("public", 8_000_000), ("research", 20_000_000)]
)
def test_original_public_and_global_lifetime_caps_never_reset(state, bucket, amount):
    financial_fixture(state, amount, bucket=bucket, created=state.clock() - 90 * 86400)
    with pytest.raises(BudgetExceeded):
        state.reserve("openai/gpt-oss-20b", 1, RUN_PREFIX + running_fixture(state))


def test_single_request_even_after_zero_cost_settlement_and_recovery_is_scoped(state):
    _, job = admitted(state)
    state.claim()
    adapter = PublicChargeAdapter(state, job["id"])
    receipt = adapter.reserve("research", "openai/gpt-oss-20b", 1000, job["id"])
    adapter.settle(receipt, 0, {"cost": 0})
    with pytest.raises(BudgetExceeded, match="one provider"):
        adapter.reserve("research", "openai/gpt-oss-20b", 1000, job["id"])
    research = state.store.reserve("research", "unrelated-research", 1000)
    state.recover()
    with state.store.connect() as c:
        assert (
            c.execute("SELECT status FROM charges WHERE id=?", (research,)).fetchone()[
                0
            ]
            == "reserved"
        )
        assert (
            c.execute(
                "SELECT status FROM recruiter_jobs WHERE id=?", (job["id"],)
            ).fetchone()[0]
            == "interrupted"
        )


def test_unknown_live_charge_stays_reserved_after_private_restart(state):
    _, job = admitted(state)
    state.claim()
    receipt = state.reserve("openai/gpt-oss-20b", 1200, RUN_PREFIX + job["id"])
    state.recover()
    with state.store.connect() as c:
        row = c.execute(
            "SELECT charged,status,bucket FROM charges WHERE id=?", (receipt,)
        ).fetchone()
        assert tuple(row) == (1200, "uncertain", "public")
    assert state.claim() is None


def test_unsupported_model_and_unadmitted_job_cannot_reserve(state):
    with pytest.raises(BudgetExceeded):
        state.reserve("expensive-model", 1000, RUN_PREFIX + running_fixture(state))
    with pytest.raises(BudgetExceeded):
        state.reserve("openai/gpt-oss-20b", 1000, RUN_PREFIX + uuid.uuid4().hex)
