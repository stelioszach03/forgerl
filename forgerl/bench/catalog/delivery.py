from ..tasks import build_family, case as c

REFERENCE = {
    "retry.py": """
def delay(attempt, base, cap):
    if type(attempt) is not int or attempt < 1 or type(base) is not int or base < 0 or type(cap) is not int or cap < 0:
        raise ValueError("invalid retry configuration")
    return min(cap, base * (2 ** min(attempt - 1, 30)))

def retryable(status):
    return status == 429 or 500 <= status <= 599

def outcome(job, response, now, config):
    attempt = job.get("attempt", 0) + 1
    status = response["status"]
    if 200 <= status <= 299:
        return {"id": job["id"], "state": "delivered", "attempt": attempt, "next_at": None}
    if retryable(status) and attempt < config.get("max_attempts", 3):
        wait = max(delay(attempt, config.get("base", 2), config.get("cap", 60)), response.get("retry_after", 0))
        return {"id": job["id"], "state": "pending", "attempt": attempt, "next_at": now + wait}
    return {"id": job["id"], "state": "dead", "attempt": attempt, "next_at": None}
""",
    "queueing.py": """
def eligible(jobs, now, limit):
    if type(limit) is not int or limit < 0:
        raise ValueError("invalid limit")
    candidates = [job for job in jobs if job.get("state", "pending") == "pending" and job["next_at"] <= now]
    candidates.sort(key=lambda job: (job["next_at"], job["id"]))
    return candidates[:limit]

def deduplicate(jobs):
    seen, result = set(), []
    for job in jobs:
        if job["id"] not in seen:
            result.append(job)
            seen.add(job["id"])
    return result
""",
    "service.py": """
from retry import outcome, delay
from queueing import eligible, deduplicate

def run(request):
    if request.get("op") == "delay":
        return delay(request["attempt"], request.get("base", 2), request.get("cap", 60))
    jobs = eligible(deduplicate(request.get("jobs", [])), request["now"], request.get("limit", 10))
    if request.get("op", "select") == "select":
        return [job["id"] for job in jobs]
    responses = request.get("responses", {})
    return [outcome(job, responses[job["id"]], request["now"], request.get("config", {})) for job in jobs if job["id"] in responses]
""",
}
SPEC = "A network-free webhook-delivery model selects pending jobs with next_at<=now, deduplicating ids by first input occurrence BEFORE filtering. Sort by (next_at,id) and apply a nonnegative integer limit. op=deliver handles selected jobs that have a supplied response; others are omitted. Each handled response increments attempt. HTTP200..299 delivers;429/500..599 retry until attempt reaches max_attempts(default3); all other statuses die. Retry wait=max(capped exponential base*2^(attempt-1), retry_after seconds), with exponent capped30. Defaults base2/cap60; delay args strict nonnegative integers, attempt>=1. retry_after is a supplied nonnegative integer. next_at for terminal outcomes is null. This simulator makes no network requests."
J = lambda id, t=0, **kw: {"id": id, "next_at": t, **kw}
R = lambda id, state, attempt, next_at=None: {
    "id": id,
    "state": state,
    "attempt": attempt,
    "next_at": next_at,
}
BACKOFF = ("retry.py", "2 ** min(attempt - 1, 30)", "2 ** min(attempt, 30)")
CLASSIFY = ("retry.py", "status == 429 or 500 <= status <= 599", "500 <= status <= 599")
DUE = ("queueing.py", 'job["next_at"] <= now', 'job["next_at"] < now')
SORT = ("queueing.py", '(job["next_at"], job["id"])', '(job["id"], job["next_at"])')
AFTER = (
    "retry.py",
    'wait = max(delay(attempt, config.get("base", 2), config.get("cap", 60)), response.get("retry_after", 0))',
    'wait = delay(attempt, config.get("base", 2), config.get("cap", 60))',
)
DEDUPE = ("queueing.py", 'if job["id"] not in seen:', "if True:")


def tasks():
    return build_family(
        "delivery",
        "train",
        REFERENCE,
        SPEC,
        [
            dict(
                slug="backoff-index",
                title="Correct the first retry backoff",
                category="bug_fix",
                summary="The first failed delivery waits twice the configured base.",
                instructions="Correct retry exponent indexing while preserving the cap and integer validation.",
                mutations=[BACKOFF],
                public=[
                    c("first", {"op": "delay", "attempt": 1}, 2),
                    c(
                        "third",
                        {"op": "delay", "attempt": 3, "base": 3, "cap": 100},
                        12,
                    ),
                ],
                hidden=[
                    c("capped", {"op": "delay", "attempt": 10, "base": 2, "cap": 9}, 9),
                    c("zero base", {"op": "delay", "attempt": 5, "base": 0}, 0),
                    c("bad attempt", {"op": "delay", "attempt": 0}, error="ValueError"),
                    c(
                        "huge",
                        {"op": "delay", "attempt": 1000000, "base": 1, "cap": 60},
                        60,
                    ),
                ],
            ),
            dict(
                slug="rate-limit-retries",
                title="Implement rate-limit response scheduling",
                category="feature",
                summary="Rate-limited jobs die instead of respecting retry-after.",
                instructions="Retry429 and enforce retry_after as a minimum delay without exceeding max_attempts.",
                mutations=[CLASSIFY, AFTER],
                public=[
                    c(
                        "429",
                        {
                            "op": "deliver",
                            "now": 5,
                            "jobs": [J("a")],
                            "responses": {"a": {"status": 429, "retry_after": 20}},
                        },
                        [R("a", "pending", 1, 25)],
                    ),
                    c(
                        "503 hint",
                        {
                            "op": "deliver",
                            "now": 0,
                            "jobs": [J("a")],
                            "responses": {"a": {"status": 503, "retry_after": 100}},
                        },
                        [R("a", "pending", 1, 100)],
                    ),
                ],
                hidden=[
                    c(
                        "last attempt",
                        {
                            "op": "deliver",
                            "now": 0,
                            "jobs": [J("a", attempt=2)],
                            "responses": {"a": {"status": 429}},
                        },
                        [R("a", "dead", 3)],
                    ),
                    c(
                        "400",
                        {
                            "op": "deliver",
                            "now": 0,
                            "jobs": [J("a")],
                            "responses": {"a": {"status": 400}},
                        },
                        [R("a", "dead", 1)],
                    ),
                    c(
                        "204",
                        {
                            "op": "deliver",
                            "now": 0,
                            "jobs": [J("a")],
                            "responses": {"a": {"status": 204}},
                        },
                        [R("a", "delivered", 1)],
                    ),
                    c(
                        "small hint",
                        {
                            "op": "deliver",
                            "now": 0,
                            "jobs": [J("a")],
                            "responses": {"a": {"status": 500, "retry_after": 1}},
                        },
                        [R("a", "pending", 1, 2)],
                    ),
                ],
            ),
            dict(
                slug="queue-ordering",
                title="Preserve due-time priority at the scheduling boundary",
                category="failing_tests",
                summary="A queue skips exactly-due work and sorts by identifier.",
                instructions="Include boundary-due jobs and sort first by next_at, then identifier.",
                mutations=[DUE, SORT],
                public=[
                    c("due now", {"now": 5, "jobs": [J("a", 5)]}, ["a"]),
                    c(
                        "earliest first",
                        {"now": 10, "jobs": [J("a", 9), J("z", 1)], "limit": 1},
                        ["z"],
                    ),
                ],
                hidden=[
                    c("ties", {"now": 10, "jobs": [J("b", 2), J("a", 2)]}, ["a", "b"]),
                    c("future", {"now": 5, "jobs": [J("a", 6)]}, []),
                    c("terminal", {"now": 5, "jobs": [J("a", 0, state="dead")]}, []),
                    c("zero limit", {"now": 5, "jobs": [J("a")], "limit": 0}, []),
                ],
            ),
            dict(
                slug="idempotent-selection",
                title="Centralize idempotent delivery selection",
                category="refactor",
                summary="Duplicate imported jobs are processed twice by both queue facades.",
                instructions="Restore shared first-write deduplication for select/deliver before eligibility checks. Preserve input records. Behavioral tests verify facade compatibility, not a mandated helper shape.",
                mutations=[DEDUPE],
                public=[
                    c("select duplicate", {"now": 2, "jobs": [J("a"), J("a")]}, ["a"]),
                    c(
                        "deliver duplicate",
                        {
                            "op": "deliver",
                            "now": 2,
                            "jobs": [J("a"), J("a")],
                            "responses": {"a": {"status": 200}},
                        },
                        [R("a", "delivered", 1)],
                    ),
                ],
                hidden=[
                    c(
                        "first future wins",
                        {"now": 2, "jobs": [J("a", 5), J("a", 0)]},
                        [],
                    ),
                    c(
                        "first terminal",
                        {"now": 2, "jobs": [J("a", 0, state="delivered"), J("a", 0)]},
                        [],
                    ),
                    c("distinct", {"now": 2, "jobs": [J("a"), J("b")]}, ["a", "b"]),
                    c(
                        "missing response",
                        {"op": "deliver", "now": 2, "jobs": [J("a")], "responses": {}},
                        [],
                    ),
                ],
            ),
            dict(
                slug="delivery-recovery",
                title="Recover webhook scheduling after a queue migration",
                category="long_horizon",
                difficulty="hard",
                summary="Queue ordering, duplicates and retry policy no longer agree.",
                instructions="Restore first-write deduplication, inclusive due boundary, priority ordering,429/retry-after handling and backoff indexing across the queue and retry modules. Miniature integrated stress task.",
                mutations=[BACKOFF, CLASSIFY, DUE, SORT, AFTER, DEDUPE],
                public=[
                    c(
                        "combined",
                        {
                            "op": "deliver",
                            "now": 5,
                            "jobs": [J("b", 5), J("a", 0), J("a", 0)],
                            "responses": {
                                "a": {"status": 429, "retry_after": 10},
                                "b": {"status": 500},
                            },
                        },
                        [R("a", "pending", 1, 15), R("b", "pending", 1, 7)],
                    ),
                    c(
                        "due limit",
                        {"now": 5, "jobs": [J("a", 5), J("z", 1)], "limit": 1},
                        ["z"],
                    ),
                ],
                hidden=[
                    c(
                        "stop retries",
                        {
                            "op": "deliver",
                            "now": 0,
                            "jobs": [J("a", attempt=2)],
                            "responses": {"a": {"status": 500}},
                        },
                        [R("a", "dead", 3)],
                    ),
                    c(
                        "success",
                        {
                            "op": "deliver",
                            "now": 0,
                            "jobs": [J("a")],
                            "responses": {"a": {"status": 201}},
                        },
                        [R("a", "delivered", 1)],
                    ),
                    c("cap", {"op": "delay", "attempt": 9, "base": 3, "cap": 10}, 10),
                    c("first wins", {"now": 3, "jobs": [J("a", 5), J("a", 0)]}, []),
                    c("invalid limit", {"now": 0, "limit": -1}, error="ValueError"),
                ],
            ),
        ],
    )
