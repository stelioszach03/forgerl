from ..tasks import build_family, case as c

REFERENCE = {
    "graph.py": """
def dependencies(nodes):
    graph = {node["id"]: list(dict.fromkeys(node.get("needs", []))) for node in nodes}
    if len(graph) != len(nodes):
        raise ValueError("duplicate node")
    for needs in graph.values():
        if any(dep not in graph for dep in needs):
            raise ValueError("unknown dependency")
    return graph

def order(graph):
    pending, result = set(graph), []
    while pending:
        ready = sorted(node for node in pending if all(dep in result for dep in graph[node]))
        if not ready:
            raise ValueError("cycle")
        current = ready[0]
        result.append(current)
        pending.remove(current)
    return result
""",
    "state.py": """
def blocked(graph, failed):
    result = set(failed)
    changed = True
    while changed:
        changed = False
        for node, needs in graph.items():
            if node not in result and any(dep in result for dep in needs):
                result.add(node)
                changed = True
    return result - set(failed)

def classify(graph, sequence, statuses):
    if any(node not in graph for node in statuses):
        raise ValueError("unknown status node")
    if any(status not in ("pending", "running", "done", "failed") for status in statuses.values()):
        raise ValueError("unknown status")
    failed = {node for node,status in statuses.items() if status == "failed"}
    unavailable = blocked(graph, failed)
    result = {"ready": [], "blocked": [], "running": [], "done": [], "failed": []}
    for node in sequence:
        status = statuses.get(node, "pending")
        if status in ("running", "done", "failed"):
            result[status].append(node)
        elif node in unavailable:
            result["blocked"].append(node)
        elif all(statuses.get(dep) == "done" for dep in graph[node]):
            result["ready"].append(node)
    return result
""",
    "service.py": """
from graph import dependencies, order
from state import classify

def run(request):
    graph = dependencies(request.get("nodes", []))
    sequence = order(graph)
    if request.get("op") == "order":
        return sequence
    result = classify(graph, sequence, request.get("statuses", {}))
    result["complete"] = len(result["done"]) == len(graph)
    return result
""",
}
SPEC = "An in-memory DAG coordinator accepts unique node ids and dependency lists (repeated dependencies ignored). Reject missing dependencies and cycles before any result. Topological order chooses the lexicographically smallest currently available node at each step. statuses may contain only known ids and pending/running/done/failed. Missing means pending. Ready pending nodes require ALL direct dependencies done; failures block all pending transitive descendants. Explicit running/done/failed statuses retain precedence over derived blocked. Lists use canonical topological order. Pending nodes awaiting work are omitted from state lists. complete means every node done, including an empty graph. No tasks are actually executed."
N = lambda id, *needs: {"id": id, "needs": list(needs)}
R = lambda ready=[], blocked=[], running=[], done=[], failed=[], complete=False: {
    "ready": ready,
    "blocked": blocked,
    "running": running,
    "done": done,
    "failed": failed,
    "complete": complete,
}
CYCLE = ("graph.py", 'raise ValueError("cycle")', "return result + sorted(pending)")
ALL = (
    "state.py",
    'all(statuses.get(dep) == "done" for dep in graph[node])',
    'any(statuses.get(dep) == "done" for dep in graph[node])',
)
TRANS = (
    "state.py",
    "changed = True\n    while changed:",
    "changed = True\n    while changed:",
)
# Reverse iteration plus one pass is an explicit non-transitive legacy implementation.
BLOCK = (
    "state.py",
    """    result = set(failed)
    changed = True
    while changed:
        changed = False
        for node, needs in graph.items():
            if node not in result and any(dep in result for dep in needs):
                result.add(node)
                changed = True
    return result - set(failed)""",
    """    return {node for node,needs in graph.items() if any(dep in failed for dep in needs)} - set(failed)""",
)
ORDER = ("graph.py", "current = ready[0]", "current = ready[-1]")
UNKNOWN = ("graph.py", "if any(dep not in graph for dep in needs):", "if False:")


def tasks():
    return build_family(
        "workflows",
        "validation",
        REFERENCE,
        SPEC,
        [
            dict(
                slug="cycle-validation",
                title="Reject cyclic workflow definitions",
                category="bug_fix",
                summary="Cycles are returned as a plausible execution order.",
                instructions="Fail closed on cyclic graphs, while preserving valid disconnected DAGs.",
                mutations=[CYCLE],
                public=[
                    c(
                        "cycle",
                        {"nodes": [N("a", "b"), N("b", "a")], "op": "order"},
                        error="ValueError",
                    ),
                    c("self cycle", {"nodes": [N("a", "a")]}, error="ValueError"),
                ],
                hidden=[
                    c(
                        "partial cycle",
                        {"nodes": [N("start"), N("a", "b"), N("b", "a")]},
                        error="ValueError",
                    ),
                    c(
                        "disconnected",
                        {"nodes": [N("b"), N("a")], "op": "order"},
                        ["a", "b"],
                    ),
                    c("empty", {"nodes": []}, R(complete=True)),
                    c("missing", {"nodes": [N("a", "missing")]}, error="ValueError"),
                ],
            ),
            dict(
                slug="readiness-gates",
                title="Require every prerequisite before scheduling",
                category="feature",
                summary="A node becomes ready after only one prerequisite completes.",
                instructions="Implement all-dependencies gating and vacuous readiness for root nodes.",
                mutations=[ALL],
                public=[
                    c("root", {"nodes": [N("a")]}, R(ready=["a"])),
                    c(
                        "partial",
                        {
                            "nodes": [N("a"), N("b"), N("c", "a", "b")],
                            "statuses": {"a": "done"},
                        },
                        R(ready=["b"], done=["a"]),
                    ),
                ],
                hidden=[
                    c(
                        "all done",
                        {
                            "nodes": [N("a"), N("b"), N("c", "a", "b")],
                            "statuses": {"a": "done", "b": "done"},
                        },
                        R(ready=["c"], done=["a", "b"]),
                    ),
                    c(
                        "running dependency",
                        {"nodes": [N("a"), N("b", "a")], "statuses": {"a": "running"}},
                        R(running=["a"]),
                    ),
                    c(
                        "complete",
                        {"nodes": [N("a")], "statuses": {"a": "done"}},
                        R(done=["a"], complete=True),
                    ),
                    c(
                        "duplicate needs",
                        {
                            "nodes": [N("a"), N("b", "a", "a")],
                            "statuses": {"a": "done"},
                        },
                        R(ready=["b"], done=["a"]),
                    ),
                ],
            ),
            dict(
                slug="failure-propagation",
                title="Propagate failure through the entire workflow DAG",
                category="failing_tests",
                summary="Grandchildren of failed nodes remain silently pending.",
                instructions="Compute the transitive blocked closure independent of node input order; keep explicit states authoritative.",
                mutations=[BLOCK],
                public=[
                    c(
                        "chain",
                        {
                            "nodes": [N("c", "b"), N("b", "a"), N("a")],
                            "statuses": {"a": "failed"},
                        },
                        R(blocked=["b", "c"], failed=["a"]),
                    ),
                    c(
                        "branch",
                        {
                            "nodes": [N("a"), N("b", "a"), N("c", "b"), N("z")],
                            "statuses": {"a": "failed"},
                        },
                        R(ready=["z"], blocked=["b", "c"], failed=["a"]),
                    ),
                ],
                hidden=[
                    c(
                        "explicit done",
                        {
                            "nodes": [N("a"), N("b", "a"), N("c", "b")],
                            "statuses": {"a": "failed", "b": "done"},
                        },
                        R(blocked=["c"], done=["b"], failed=["a"]),
                    ),
                    c("no failures", {"nodes": [N("a"), N("b", "a")]}, R(ready=["a"])),
                    c(
                        "two failed",
                        {
                            "nodes": [N("a"), N("b"), N("c", "a", "b")],
                            "statuses": {"a": "failed", "b": "failed"},
                        },
                        R(blocked=["c"], failed=["a", "b"]),
                    ),
                    c(
                        "running override",
                        {
                            "nodes": [N("a"), N("b", "a")],
                            "statuses": {"a": "failed", "b": "running"},
                        },
                        R(running=["b"], failed=["a"]),
                    ),
                ],
            ),
            dict(
                slug="canonical-order",
                title="Restore deterministic coordinator ordering",
                category="refactor",
                summary="A refactor changed tie-breaking across order and status APIs.",
                instructions="Use the smallest currently available identifier at every topological step, consistently across both facades; preserve graph validation.",
                mutations=[ORDER],
                public=[
                    c("roots", {"op": "order", "nodes": [N("z"), N("a")]}, ["a", "z"]),
                    c(
                        "new ready",
                        {"op": "order", "nodes": [N("b"), N("a"), N("aa", "a")]},
                        ["a", "aa", "b"],
                    ),
                ],
                hidden=[
                    c("status order", {"nodes": [N("z"), N("a")]}, R(ready=["a", "z"])),
                    c(
                        "dependency",
                        {"op": "order", "nodes": [N("a", "z"), N("z")]},
                        ["z", "a"],
                    ),
                    c("duplicate id", {"nodes": [N("a"), N("a")]}, error="ValueError"),
                    c(
                        "unknown status",
                        {"nodes": [N("a")], "statuses": {"z": "done"}},
                        error="ValueError",
                    ),
                ],
            ),
            dict(
                slug="coordinator-recovery",
                title="Recover workflow validation and execution readiness",
                category="long_horizon",
                difficulty="hard",
                summary="The coordinator has interacting validation, order and state bugs.",
                instructions="Restore cycle rejection, canonical topological ordering, all-prerequisite gates and transitive failure blocking. Miniature integrated stress task.",
                mutations=[CYCLE, ALL, BLOCK, ORDER],
                public=[
                    c(
                        "recovery",
                        {
                            "nodes": [N("z"), N("c", "b"), N("b", "a"), N("a")],
                            "statuses": {"a": "failed"},
                        },
                        R(ready=["z"], blocked=["b", "c"], failed=["a"]),
                    ),
                    c(
                        "cycle",
                        {"nodes": [N("a", "b"), N("b", "a")]},
                        error="ValueError",
                    ),
                ],
                hidden=[
                    c(
                        "ready",
                        {
                            "nodes": [N("a"), N("b"), N("c", "a", "b")],
                            "statuses": {"a": "done"},
                        },
                        R(ready=["b"], done=["a"]),
                    ),
                    c(
                        "order",
                        {"op": "order", "nodes": [N("b"), N("a"), N("aa", "a")]},
                        ["a", "aa", "b"],
                    ),
                    c("empty", {}, R(complete=True)),
                    c(
                        "complete",
                        {"nodes": [N("a")], "statuses": {"a": "done"}},
                        R(done=["a"], complete=True),
                    ),
                    c(
                        "invalid state",
                        {"nodes": [N("a")], "statuses": {"a": "unknown"}},
                        error="ValueError",
                    ),
                ],
            ),
        ],
    )
