from ..tasks import build_family, case as c

REFERENCE = {
    "clocks.py": """
def validate(clock):
    if not isinstance(clock, dict) or any(type(value) is not int or value < 0 for value in clock.values()):
        raise ValueError("invalid vector clock")
    return dict(clock)

def compare(left, right):
    left, right = validate(left), validate(right)
    keys = set(left) | set(right)
    greater = any(left.get(key, 0) > right.get(key, 0) for key in keys)
    smaller = any(left.get(key, 0) < right.get(key, 0) for key in keys)
    if greater and not smaller:
        return 1
    if smaller and not greater:
        return -1
    return 0

def joined(clocks):
    result = {}
    for clock in clocks:
        for key, value in validate(clock).items():
            result[key] = max(result.get(key, 0), value)
    return dict(sorted(result.items()))
""",
    "resolution.py": """
import json
from clocks import compare, validate, joined

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))

def normalize(record):
    return {"key": record["key"], "node": record["node"], "clock": validate(record["clock"]),
            "value": record.get("value"), "deleted": bool(record.get("deleted", False))}

def resolve(records):
    unique = {}
    for row in records:
        record = normalize(row)
        unique[canonical(record)] = record
    versions = list(unique.values())
    frontier = [candidate for candidate in versions if not any(compare(other["clock"], candidate["clock"]) > 0 for other in versions)]
    winner = max(frontier, key=lambda row: (row["deleted"], row["node"], canonical(row["value"])))
    return {"key": winner["key"], "value": None if winner["deleted"] else winner["value"],
            "deleted": winner["deleted"], "clock": joined([row["clock"] for row in versions]),
            "winner": winner["node"], "conflict": len(frontier) > 1}
""",
    "service.py": """
from clocks import compare
from resolution import resolve

def run(request):
    if request.get("op") == "compare":
        return compare(request["left"], request["right"])
    groups = {}
    for record in request.get("records", []):
        groups.setdefault(record["key"], []).append(record)
    return [resolve(groups[key]) for key in sorted(groups)]
""",
}
SPEC = "An offline replica reconciliation exercise uses vector clocks of nonnegative strict integer counters. Missing components count as zero. compare returns1 if left strictly dominates, -1 if right strictly dominates,0 for equal or concurrent. Merge groups by key, normalizes absent deleted=false/value=null, removes exact normalized duplicates, and keeps causally maximal versions (strict dominance only). For concurrent/equal-clock versions, prefer tombstones, then lexicographically greatest node, then lexicographically greatest canonical JSON value(sort keys,compact separators). Result conflict=true iff more than one distinct maximal version remains. Result clock is component-wise max over all versions; retain explicit zero components. Tombstones output value=null. Output keys sorted. This is a deterministic exercise with a stated conflict policy, not a complete CRDT or distributed database."
V = lambda node, clock, value="v", key="k", deleted=False: {
    "key": key,
    "node": node,
    "clock": clock,
    "value": value,
    "deleted": deleted,
}
R = lambda node, clock, value="v", key="k", deleted=False, conflict=False: {
    "key": key,
    "value": None if deleted else value,
    "deleted": deleted,
    "clock": clock,
    "winner": node,
    "conflict": conflict,
}
KEYS = ("clocks.py", "keys = set(left) | set(right)", "keys = set(left) & set(right)")
JOIN = (
    "clocks.py",
    "result[key] = max(result.get(key, 0), value)",
    "result[key] = result.get(key, 0) + value",
)
STRICT = (
    "resolution.py",
    'compare(other["clock"], candidate["clock"]) > 0',
    'compare(other["clock"], candidate["clock"]) >= 0',
)
DELETE = (
    "resolution.py",
    '(row["deleted"], row["node"], canonical(row["value"]))',
    '(False, row["node"], canonical(row["value"]))',
)
VALID = (
    "clocks.py",
    "type(value) is not int or value < 0",
    "not isinstance(value, int) or value < 0",
)


def tasks():
    return build_family(
        "federation",
        "test",
        REFERENCE,
        SPEC,
        [
            dict(
                slug="clock-components",
                title="Compare the union of replica clock components",
                category="bug_fix",
                summary="A new replica component is ignored during causality comparison.",
                instructions="Compare all clock keys with absent values treated as zero, distinguishing strict dominance from concurrency.",
                mutations=[KEYS],
                public=[
                    c(
                        "new component",
                        {"op": "compare", "left": {"A": 1}, "right": {}},
                        1,
                    ),
                    c(
                        "concurrent",
                        {
                            "op": "compare",
                            "left": {"A": 2, "B": 0},
                            "right": {"A": 1, "B": 1},
                        },
                        0,
                    ),
                ],
                hidden=[
                    c("reverse", {"op": "compare", "left": {}, "right": {"B": 1}}, -1),
                    c(
                        "explicit zero",
                        {"op": "compare", "left": {"A": 0}, "right": {}},
                        0,
                    ),
                    c(
                        "equal",
                        {"op": "compare", "left": {"A": 2}, "right": {"A": 2}},
                        0,
                    ),
                    c(
                        "merge dominance",
                        {"records": [V("z", {}, "old"), V("a", {"A": 1}, "new")]},
                        [R("a", {"A": 1}, "new")],
                    ),
                ],
            ),
            dict(
                slug="tombstone-policy",
                title="Resolve concurrent tombstones deterministically",
                category="feature",
                summary="A concurrent live value can resurrect a deleted record.",
                instructions="Apply delete-wins only among maximal concurrent/equal versions; a causally newer live version still supersedes an old tombstone.",
                mutations=[DELETE],
                public=[
                    c(
                        "concurrent deletion",
                        {
                            "records": [
                                V("a", {"A": 1}, deleted=True),
                                V("z", {"B": 1}, "live"),
                            ]
                        },
                        [R("a", {"A": 1, "B": 1}, deleted=True, conflict=True)],
                    ),
                    c(
                        "equal clocks",
                        {
                            "records": [
                                V("a", {"A": 1}, deleted=True),
                                V("z", {"A": 1}, "live"),
                            ]
                        },
                        [R("a", {"A": 1}, deleted=True, conflict=True)],
                    ),
                ],
                hidden=[
                    c(
                        "newer live",
                        {
                            "records": [
                                V("a", {"A": 1}, deleted=True),
                                V("z", {"A": 2}, "new"),
                            ]
                        },
                        [R("z", {"A": 2}, "new")],
                    ),
                    c(
                        "newer deleted",
                        {
                            "records": [
                                V("a", {"A": 2}, deleted=True),
                                V("z", {"A": 1}, "old"),
                            ]
                        },
                        [R("a", {"A": 2}, deleted=True)],
                    ),
                    c(
                        "both tombstones",
                        {
                            "records": [
                                V("a", {"A": 1}, deleted=True),
                                V("z", {"B": 1}, deleted=True),
                            ]
                        },
                        [R("z", {"A": 1, "B": 1}, deleted=True, conflict=True)],
                    ),
                    c("plain", {"records": [V("a", {"A": 1})]}, [R("a", {"A": 1})]),
                ],
            ),
            dict(
                slug="clock-join",
                title="Make replica clock joins idempotent",
                category="refactor",
                summary="Aggregating clocks sums counters instead of preserving causal maxima.",
                instructions="Use a component-wise max join consistently across identical, obsolete and concurrent records. Preserve the deterministic reconciliation facade.",
                mutations=[JOIN],
                public=[
                    c(
                        "same component",
                        {"records": [V("a", {"A": 1}), V("b", {"A": 2})]},
                        [R("b", {"A": 2})],
                    ),
                    c(
                        "concurrent",
                        {
                            "records": [
                                V("a", {"A": 2, "B": 1}),
                                V("b", {"A": 1, "B": 2}),
                            ]
                        },
                        [R("b", {"A": 2, "B": 2}, conflict=True)],
                    ),
                ],
                hidden=[
                    c(
                        "exact duplicate",
                        {"records": [V("a", {"A": 2}), V("a", {"A": 2})]},
                        [R("a", {"A": 2})],
                    ),
                    c(
                        "explicit zero",
                        {"records": [V("a", {"A": 0})]},
                        [R("a", {"A": 0})],
                    ),
                    c(
                        "separate keys",
                        {
                            "records": [
                                V("a", {"A": 2}, key="z"),
                                V("b", {"A": 1}, key="a"),
                            ]
                        },
                        [R("b", {"A": 1}, key="a"), R("a", {"A": 2}, key="z")],
                    ),
                    c("no records", {}, []),
                ],
            ),
            dict(
                slug="strict-frontier",
                title="Keep equal-clock versions on the causal frontier",
                category="failing_tests",
                summary="A version dominates itself and reconciliation loses every candidate.",
                instructions="Use strict causal domination; preserve equal/concurrent alternatives and validate integer clocks.",
                mutations=[STRICT, VALID],
                public=[
                    c("singleton", {"records": [V("a", {"A": 1})]}, [R("a", {"A": 1})]),
                    c(
                        "bool clock",
                        {"op": "compare", "left": {"A": True}, "right": {}},
                        error="ValueError",
                    ),
                ],
                hidden=[
                    c(
                        "equal tie",
                        {"records": [V("a", {"A": 1}, "x"), V("b", {"A": 1}, "y")]},
                        [R("b", {"A": 1}, "y", conflict=True)],
                    ),
                    c("negative", {"records": [V("a", {"A": -1})]}, error="ValueError"),
                    c(
                        "same-node tie",
                        {"records": [V("a", {"A": 1}, "x"), V("a", {"A": 1}, "y")]},
                        [R("a", {"A": 1}, "y", conflict=True)],
                    ),
                    c(
                        "exact duplicates",
                        {"records": [V("a", {"A": 1}), V("a", {"A": 1})]},
                        [R("a", {"A": 1})],
                    ),
                ],
            ),
            dict(
                slug="replica-recovery",
                title="Recover deterministic offline replica reconciliation",
                category="long_horizon",
                difficulty="hard",
                summary="Clock comparison, join, frontier and deletion rules disagree.",
                instructions="Repair vector-key union, strict causal maximality, component-wise max joins, concurrent delete-wins and strict clock validation across modules. Miniature integrated stress task.",
                mutations=[KEYS, JOIN, STRICT, DELETE, VALID],
                public=[
                    c(
                        "combined",
                        {
                            "records": [
                                V("z", {}, "obsolete"),
                                V("a", {"A": 2}, deleted=True),
                                V("b", {"B": 1}, "live"),
                            ]
                        },
                        [R("a", {"A": 2, "B": 1}, deleted=True, conflict=True)],
                    ),
                    c(
                        "new replica",
                        {"op": "compare", "left": {"A": 1}, "right": {}},
                        1,
                    ),
                ],
                hidden=[
                    c(
                        "causal live",
                        {
                            "records": [
                                V("a", {"A": 1}, deleted=True),
                                V("b", {"A": 2}, "new"),
                            ]
                        },
                        [R("b", {"A": 2}, "new")],
                    ),
                    c(
                        "duplicate",
                        {"records": [V("a", {"A": 1}), V("a", {"A": 1})]},
                        [R("a", {"A": 1})],
                    ),
                    c("bool", {"records": [V("a", {"A": False})]}, error="ValueError"),
                    c(
                        "two components",
                        {
                            "records": [
                                V("a", {"A": 2, "B": 1}),
                                V("b", {"A": 1, "B": 2}),
                            ]
                        },
                        [R("b", {"A": 2, "B": 2}, conflict=True)],
                    ),
                    c("empty", {}, []),
                ],
            ),
        ],
    )
