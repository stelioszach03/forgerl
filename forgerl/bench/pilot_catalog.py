"""Fresh authored families for a prospective, explicitly limited v0.3 pilot.

These are compact specification-driven programs, not imported real-world issues.
Embedded source is data: it must run only in the isolated repository executor.
"""

from dataclasses import replace
import hashlib
import json

from .tasks import build_family, case as c, list_tasks, public_task
from .v03 import VerificationTask


def family(name, split, reference, spec, mutations, public, verification, hidden):
    """Three pairwise fault combinations; every variant changes two modules."""
    variants = []
    for index, (a, b) in enumerate(((0, 1), (0, 2), (1, 2)), 1):
        variants.append(
            dict(
                slug=f"repair-{index}",
                title=f"Repair {name.replace('_', ' ')} contract {index}",
                category="multi_file",
                difficulty="medium",
                summary="Restore two interacting source-module contracts.",
                instructions="Restore the complete specified behavior in the supplied modules. Do not mutate the request.",
                mutations=[mutations[a], mutations[b]],
                public=public,
                hidden=hidden,
            )
        )
    return tuple(
        VerificationTask(task, tuple(verification))
        for task in build_family(name, split, reference, spec, variants)
    )


def binary_protocol():
    reference = {
        "codec.py": """
def decode(values):
    if any(type(v) is not int or not 0 <= v <= 255 for v in values):
        raise ValueError("invalid byte")
    if len(values) % 2:
        raise ValueError("incomplete run")
    result = []
    for i in range(0, len(values), 2):
        count, value = values[i:i+2]
        if count == 0:
            raise ValueError("zero run")
        result.extend([value] * count)
    return result
""",
        "frame.py": """
def validate(values, length, checksum):
    if type(length) is not int or length < 0 or len(values) != length:
        raise ValueError("length mismatch")
    if type(checksum) is not int or sum(values) % 256 != checksum:
        raise ValueError("checksum mismatch")
    return values
""",
        "service.py": """
from codec import decode
from frame import validate
def run(request):
    values = decode(request["encoded"])
    return validate(values, request["length"], request["checksum"])
""",
    }
    q = lambda v, n, s: {"encoded": v, "length": n, "checksum": s}
    return family(
        "binary_protocol",
        "validation",
        reference,
        "Decode alternating (count,value) byte pairs. Every value is a strict integer in [0,255], boolean rejected; count=0 and odd length are errors. Expand runs in order. Validate strict nonnegative integer decoded length and strict integer checksum equal to sum(decoded)%256; any failure raises ValueError. Empty encoded input is valid with length=0/checksum=0.",
        [
            ("codec.py", "[value] * count", "[value] * (count + 1)"),
            ("frame.py", "sum(values) % 256", "sum(values)"),
            (
                "service.py",
                'request["length"], request["checksum"]',
                'request["checksum"], request["length"]',
            ),
        ],
        [
            c("wrapped", q([2, 200], 2, 144), [200, 200]),
            c("empty", q([], 0, 0), []),
            c("two runs", q([1, 3, 2, 5], 3, 13), [3, 5, 5]),
        ],
        [
            c("verify repeated", q([3, 99], 3, 41), [99, 99, 99]),
            c("verify zero", q([0, 2], 0, 0), error="ValueError"),
        ],
        [
            c("hidden mixed", q([1, 255, 2, 1], 3, 1), [255, 1, 1]),
            c("hidden odd", q([1], 0, 0), error="ValueError"),
            c("hidden bool", q([True, 9], 1, 9), error="ValueError"),
            c("hidden checksum", q([1, 8], 1, 9), error="ValueError"),
            c("hidden length", q([1, 8], 2, 8), error="ValueError"),
        ],
    )


def geospatial():
    reference = {
        "rectangles.py": """
def area(rect):
    x1,y1,x2,y2 = rect
    if x1 > x2 or y1 > y2:
        raise ValueError("inverted rectangle")
    return (x2-x1)*(y2-y1)
def intersection(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))
""",
        "overlap.py": """
def score(left, right, shared):
    union = left + right - shared
    return shared / union if union else 0
""",
        "service.py": """
from rectangles import area, intersection
from overlap import score
def run(request):
    a,b = request["a"],request["b"]
    left,right = area(a),area(b)
    shared = intersection(a,b)
    return {"intersection":shared,"iou":score(left,right,shared)}
""",
    }
    q = lambda a, b: {"a": a, "b": b}
    return family(
        "geospatial",
        "validation",
        reference,
        "For two finite numeric axis-aligned rectangles [x1,y1,x2,y2], reject inverted coordinates with ValueError. Zero-area rectangles are valid. Return intersection area and intersection-over-union (IoU); touching edges have zero intersection, zero union yields IoU=0. Coordinates may be negative or fractional.",
        [
            ("rectangles.py", "(x2-x1)*(y2-y1)", "(x2-x1)+(y2-y1)"),
            ("overlap.py", "left + right - shared", "left + right"),
            ("service.py", "shared = intersection(a,b)", "shared = intersection(a,a)"),
        ],
        [
            c(
                "identical",
                q([0, 0, 3, 2], [0, 0, 3, 2]),
                {"intersection": 6, "iou": 1},
            ),
            c("separate", q([0, 0, 1, 1], [2, 2, 3, 3]), {"intersection": 0, "iou": 0}),
        ],
        [
            c(
                "verify containment",
                q([0, 0, 4, 4], [1, 1, 3, 3]),
                {"intersection": 4, "iou": 0.25},
            ),
            c("verify inverted", q([2, 0, 1, 1], [0, 0, 1, 1]), error="ValueError"),
        ],
        [
            c(
                "hidden overlap",
                q([0, 0, 2, 2], [1, 0, 3, 2]),
                {"intersection": 2, "iou": 1 / 3},
            ),
            c(
                "hidden edges",
                q([0, 0, 2, 2], [2, 0, 3, 2]),
                {"intersection": 0, "iou": 0},
            ),
            c(
                "hidden zeros",
                q([1, 1, 1, 1], [1, 1, 1, 1]),
                {"intersection": 0, "iou": 0},
            ),
            c(
                "hidden negative",
                q([-2, -2, 0, 0], [-1, -1, 1, 1]),
                {"intersection": 1, "iou": 1 / 7},
            ),
            c(
                "hidden fraction",
                q([0, 0, 0.5, 0.5], [0, 0, 1, 1]),
                {"intersection": 0.25, "iou": 0.25},
            ),
        ],
    )


def graph_dependencies():
    reference = {
        "graphdata.py": """
def normalize(nodes, edges):
    names = sorted(set(nodes))
    adjacency = {n:[] for n in names}
    indegree = {n:0 for n in names}
    for left,right in sorted(set(tuple(e) for e in edges)):
        if left not in adjacency or right not in adjacency:
            raise ValueError("unknown node")
        adjacency[left].append(right)
        indegree[right] += 1
    return names,adjacency,indegree
""",
        "topology.py": """
def order(names, adjacency, indegree):
    ready = sorted(n for n in names if indegree[n] == 0)
    result=[]
    while ready:
        node=ready.pop(0)
        result.append(node)
        for child in adjacency[node]:
            indegree[child]-=1
            if indegree[child] == 0:
                ready.append(child)
        ready.sort()
    if len(result) != len(names):
        raise ValueError("cycle")
    return result
""",
        "service.py": """
from graphdata import normalize
from topology import order
def run(request):
    names,adjacency,indegree = normalize(request["nodes"],request["edges"])
    return order(names,adjacency,indegree)
""",
    }
    q = lambda n, e: {"nodes": n, "edges": e}
    return family(
        "graph_dependencies",
        "test",
        reference,
        "Return lexicographically smallest topological order of string nodes. An edge [u,v] means u before v. Deduplicate nodes and identical edges. At each step select the lexicographically smallest currently ready node, including newly ready nodes. Reject unknown endpoints and cycles (including self-loops) with ValueError. Empty graph returns [].",
        [
            ("graphdata.py", "indegree[right] += 1", "indegree[left] += 1"),
            ("topology.py", "node=ready.pop(0)", "node=ready.pop()"),
            (
                "service.py",
                'normalize(request["nodes"],request["edges"])',
                'normalize(request["nodes"],[])',
            ),
        ],
        [
            c("chain", q(["a", "b", "c"], [["a", "b"], ["b", "c"]]), ["a", "b", "c"]),
            c("tie", q(["b", "a", "c"], []), ["a", "b", "c"]),
            c("reverse dependency", q(["a", "z"], [["z", "a"]]), ["z", "a"]),
        ],
        [
            c("verify new ready", q(["a", "b", "z"], [["a", "b"]]), ["a", "b", "z"]),
            c(
                "verify cycle",
                q(["x", "y"], [["x", "y"], ["y", "x"]]),
                error="ValueError",
            ),
        ],
        [
            c(
                "hidden duplicates",
                q(["b", "a", "a"], [["b", "a"], ["b", "a"]]),
                ["b", "a"],
            ),
            c("hidden empty", q([], []), []),
            c("hidden unknown", q(["a"], [["a", "x"]]), error="ValueError"),
            c("hidden self", q(["a"], [["a", "a"]]), error="ValueError"),
            c(
                "hidden diamond",
                q(
                    ["a", "b", "c", "d"],
                    [["a", "c"], ["a", "b"], ["b", "d"], ["c", "d"]],
                ),
                ["a", "b", "c", "d"],
            ),
        ],
    )


def apportionment():
    reference = {
        "quotas.py": """
def quotas(weights, seats):
    if type(seats) is not int or seats < 0 or any(type(v) is not int or v < 0 for v in weights.values()):
        raise ValueError("invalid allocation")
    total=sum(weights.values())
    if total == 0:
        if seats:
            raise ValueError("zero total")
        return {k:0 for k in weights},{k:0 for k in weights}
    base={k:seats*v//total for k,v in weights.items()}
    rem={k:seats*v%total for k,v in weights.items()}
    return base,rem
""",
        "remainders.py": """
def distribute(base, remainders, seats):
    result=dict(base)
    priority=sorted(base,key=lambda k:(-remainders[k],k))
    for name in priority[:seats-sum(base.values())]:
        result[name]+=1
    return {k:result[k] for k in sorted(result)}
""",
        "service.py": """
from quotas import quotas
from remainders import distribute
def run(request):
    weights,seats=request["weights"],request["seats"]
    base,remainders=quotas(weights,seats)
    return distribute(base,remainders,seats)
""",
    }
    q = lambda w, s: {"weights": w, "seats": s}
    return family(
        "apportionment",
        "test",
        reference,
        "Allocate integer seats using Hamilton largest remainders over named nonnegative strict-integer weights. Start with floor(seats*weight/total); distribute remaining seats by descending exact integer remainder, tie by ascending name. Return every name including zero allocation. seats must be nonnegative strict integer. Empty/zero total only permits zero seats. Reject invalid inputs with ValueError. Avoid floating point so large integers remain exact.",
        [
            ("quotas.py", "seats*v//total", "(seats*v+total-1)//total"),
            ("remainders.py", "(-remainders[k],k)", "(remainders[k],k)"),
            (
                "service.py",
                "distribute(base,remainders,seats)",
                "distribute(base,remainders,sum(base.values()))",
            ),
        ],
        [
            c("unequal", q({"a": 1, "b": 3}, 3), {"a": 1, "b": 2}),
            c("tie", q({"b": 1, "a": 1}, 1), {"a": 1, "b": 0}),
        ],
        [
            c(
                "verify zero weights",
                q({"a": 0, "b": 5, "c": 2}, 4),
                {"a": 0, "b": 3, "c": 1},
            ),
            c("verify invalid", q({"a": True}, 1), error="ValueError"),
        ],
        [
            c("hidden exact", q({"a": 1, "b": 2}, 6), {"a": 2, "b": 4}),
            c("hidden none", q({}, 0), {}),
            c("hidden impossible", q({"x": 0}, 1), error="ValueError"),
            c("hidden zero seats", q({"a": 2, "b": 0}, 0), {"a": 0, "b": 0}),
            c(
                "hidden big",
                q({"a": 9007199254740993, "b": 9007199254740992}, 1),
                {"a": 1, "b": 0},
            ),
        ],
    )


def interpolation():
    reference = {
        "samples.py": """
def prepare(points):
    seen={}
    for x,y in points:
        if x in seen:
            raise ValueError("duplicate coordinate")
        seen[x]=y
    if not seen:
        raise ValueError("empty samples")
    return sorted(seen.items())
""",
        "linear.py": """
def estimate(points, x):
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for i in range(1,len(points)):
        left,right=points[i-1],points[i]
        if x <= right[0]:
            return left[1]+(right[1]-left[1])*(x-left[0])/(right[0]-left[0])
""",
        "service.py": """
from samples import prepare
from linear import estimate
def run(request):
    points=prepare(request["points"])
    return [estimate(points,x) for x in request["queries"]]
""",
    }
    q = lambda p, x: {"points": p, "queries": x}
    return family(
        "interpolation",
        "test",
        reference,
        "Prepare distinct finite numeric (x,y) samples sorted by x, rejecting duplicate x and empty samples with ValueError even for an empty query list. Evaluate finite numeric queries in their original order using piecewise linear interpolation; clamp outside support to the nearest endpoint y. A single sample gives its y for every query. Preserve signed slopes and nonuniform x spacing.",
        [
            ("samples.py", "return sorted(seen.items())", "return list(seen.items())"),
            ("linear.py", "(right[0]-left[0])", "1"),
            (
                "service.py",
                'for x in request["queries"]',
                'for x in sorted(request["queries"])',
            ),
        ],
        [
            c("unsorted spacing", q([[4, 8], [0, 0]], [3, 1]), [6, 2]),
            c("negative slope", q([[0, 10], [5, 0]], [2]), [6]),
        ],
        [
            c("verify knots", q([[0, 2], [2, 6], [5, 3]], [4, 2, -1, 6]), [4, 6, 2, 3]),
            c("verify duplicate", q([[1, 2], [1, 3]], []), error="ValueError"),
        ],
        [
            c("hidden singleton", q([[2, 9]], [99, -9, 2]), [9, 9, 9]),
            c("hidden empty", q([], []), error="ValueError"),
            c("hidden signed", q([[-4, 0], [0, -8]], [-1, -3]), [-6, -2]),
            c("hidden none", q([[1, 2]], []), []),
            c("hidden fractional", q([[0.5, 1], [1.5, 5]], [0.75, 1.25]), [2, 4]),
        ],
    )


def tabular_join():
    reference = {
        "records.py": """
def index_rows(rows):
    index={}
    for row in rows:
        key=row.get("key")
        if key is not None:
            index.setdefault(key,[]).append(row["value"])
    return index
""",
        "joinrows.py": """
def left_join(rows, index):
    result=[]
    for row in rows:
        key=row.get("key")
        matches=index.get(key,[]) if key is not None else []
        for value in matches or [None]:
            result.append({"key":key,"left":row["value"],"right":value})
    return result
""",
        "service.py": """
from records import index_rows
from joinrows import left_join
def run(request):
    return left_join(request["left"],index_rows(request["right"]))
""",
    }
    row = lambda k, v: {"key": k, "value": v}
    out = lambda k, l, r: {"key": k, "left": l, "right": r}
    q = lambda l, r: {"left": l, "right": r}
    return family(
        "tabular_join",
        "test",
        reference,
        "Perform a stable left equijoin of two lists of rows with key and value fields. Keys are strings or null; missing key is null. Preserve left row order, then right matching order. Retain duplicate-key Cartesian matches. Null keys never match, including other nulls. For unmatched left rows return right=null. Output rows are {key,left,right}; do not mutate input rows.",
        [
            (
                "records.py",
                'index.setdefault(key,[]).append(row["value"])',
                'index[key]=[row["value"]]',
            ),
            ("joinrows.py", "matches or [None]", "matches"),
            (
                "service.py",
                'left_join(request["left"],index_rows(request["right"]))',
                'left_join(request["right"],index_rows(request["left"]))',
            ),
        ],
        [
            c(
                "many",
                q([row("a", 1), row("b", 2)], [row("a", 3), row("a", 4)]),
                [out("a", 1, 3), out("a", 1, 4), out("b", 2, None)],
            ),
            c("null", q([row(None, 5)], [row(None, 6)]), [out(None, 5, None)]),
        ],
        [
            c(
                "verify duplicates",
                q([row("z", 1), row("z", 2)], [row("z", 7)]),
                [out("z", 1, 7), out("z", 2, 7)],
            ),
            c("verify empty right", q([row("", 0)], []), [out("", 0, None)]),
        ],
        [
            c("hidden empty left", q([], [row("a", 1)]), []),
            c(
                "hidden cross",
                q([row("a", 1), row("a", 2)], [row("a", 3), row("a", 4)]),
                [out("a", 1, 3), out("a", 1, 4), out("a", 2, 3), out("a", 2, 4)],
            ),
            c(
                "hidden missing",
                q([{"value": 9}], [{"value": 8}]),
                [out(None, 9, None)],
            ),
            c(
                "hidden order",
                q([row("z", 0), row("a", 1)], [row("a", 2), row("z", 3)]),
                [out("z", 0, 3), out("a", 1, 2)],
            ),
        ],
    )


def expression_engine():
    reference = {
        "operands.py": """
def parse(token):
    if not isinstance(token,str):
        raise ValueError("invalid token")
    try:
        return int(token)
    except ValueError:
        raise ValueError("invalid integer")
""",
        "operators.py": """
def apply(op, left, right):
    if op == "+":
        return left+right
    if op == "-":
        return left-right
    if op == "*":
        return left*right
    if right == 0:
        raise ValueError("division by zero")
    magnitude=abs(left)//abs(right)
    return -magnitude if (left<0) != (right<0) else magnitude
""",
        "service.py": """
from operands import parse
from operators import apply
def run(request):
    stack=[]
    for token in request["tokens"]:
        if token in ("+","-","*","/"):
            if len(stack)<2:
                raise ValueError("missing operands")
            right,left=stack.pop(),stack.pop()
            stack.append(apply(token,left,right))
        else:
            stack.append(parse(token))
    if len(stack) != 1:
        raise ValueError("incomplete expression")
    return stack[0]
""",
    }
    q = lambda t: {"tokens": t}
    return family(
        "expression_engine",
        "test",
        reference,
        "Evaluate reverse-Polish integer expressions from a list of string tokens using +,-,*,/. Numeric tokens use Python int parsing. Division truncates toward zero with exact arbitrary-precision integer arithmetic, never float. Operand order is left then right. Raise ValueError for invalid numeric tokens, zero division, missing operands, or a final stack size other than one. Empty expression is invalid.",
        [
            ("operands.py", "return int(token)", "return abs(int(token))"),
            ("operators.py", "return left-right", "return right-left"),
            (
                "service.py",
                "right,left=stack.pop(),stack.pop()",
                "left,right=stack.pop(),stack.pop()",
            ),
        ],
        [
            c("subtraction", q(["8", "3", "-"]), 5),
            c("signed", q(["-7", "2", "/"]), -3),
            c("expression", q(["-2", "3", "*", "4", "+"]), -2),
        ],
        [
            c("verify negative divisor", q(["11", "-3", "/"]), -3),
            c("verify extra", q(["1", "2"]), error="ValueError"),
        ],
        [
            c("hidden order", q(["2", "8", "-"]), -6),
            c("hidden empty", q([]), error="ValueError"),
            c("hidden zero", q(["3", "0", "/"]), error="ValueError"),
            c("hidden missing", q(["+"]), error="ValueError"),
            c("hidden big", q(["9007199254740995", "3", "/"]), 3002399751580331),
            c("hidden invalid", q(["1.5"]), error="ValueError"),
        ],
    )


def edit_distance():
    reference = {
        "normalization.py": """
def normalize(value, fold):
    return value.casefold() if fold else value
""",
        "distance.py": """
def distance(a,b):
    previous=list(range(len(b)+1))
    for i,left in enumerate(a,1):
        current=[i]
        for j,right in enumerate(b,1):
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(left!=right)))
        previous=current
    return previous[-1]
""",
        "service.py": """
from normalization import normalize
from distance import distance
def run(request):
    query=normalize(request["query"],request.get("fold",False))
    maximum=request["maximum"]
    if type(maximum) is not int or maximum<0:
        raise ValueError("invalid maximum")
    result=[]
    for position,value in enumerate(request["candidates"]):
        score=distance(query,normalize(value,request.get("fold",False)))
        if score<=maximum:
            result.append({"value":value,"distance":score,"position":position})
    return sorted(result,key=lambda row:(row["distance"],row["position"]))
""",
    }
    q = lambda text, values, n, **kw: {
        "query": text,
        "candidates": values,
        "maximum": n,
        **kw,
    }
    r = lambda v, d, p: {"value": v, "distance": d, "position": p}
    return family(
        "edit_distance",
        "test",
        reference,
        "Rank candidate strings by unit-cost Levenshtein distance (insertion/deletion/substitution, no transposition) from query. Optional fold=true uses Unicode casefold before distance on both query and candidate; preserve original candidate spelling. Include distances <= strict nonnegative integer maximum. Return {value,distance,position}, sorted by distance then original zero-based position. Retain duplicates. Empty strings valid. Booleans invalid maximum.",
        [
            ("normalization.py", "value.casefold()", "value.lower()"),
            ("distance.py", "(left!=right)", "(left==right)"),
            ("service.py", "if score<=maximum:", "if score<maximum:"),
        ],
        [
            c(
                "unicode",
                q("Straße", ["STRASSE", "Straße"], 0, fold=True),
                [r("STRASSE", 0, 0), r("Straße", 0, 1)],
            ),
            c(
                "edits",
                q("cat", ["bat", "cat", "cats"], 1),
                [r("cat", 0, 1), r("bat", 1, 0), r("cats", 1, 2)],
            ),
        ],
        [
            c("verify empty", q("", ["x", ""], 1), [r("", 0, 1), r("x", 1, 0)]),
            c(
                "verify sigma",
                q("Σ", ["ς", "σ"], 0, fold=True),
                [r("ς", 0, 0), r("σ", 0, 1)],
            ),
        ],
        [
            c("hidden standard", q("kitten", ["sitting"], 3), [r("sitting", 3, 0)]),
            c("hidden transpose", q("ab", ["ba"], 1), []),
            c(
                "hidden preserve",
                q("A", ["a", "A", "a"], 1),
                [r("A", 0, 1), r("a", 1, 0), r("a", 1, 2)],
            ),
            c("hidden no candidates", q("x", [], 0), []),
            c("hidden invalid", q("x", [], True), error="ValueError"),
            c("hidden ligature", q("ﬂ", ["fl"], 0, fold=True), [r("fl", 0, 0)]),
        ],
    )


def fresh_specs():
    return tuple(
        spec
        for create in (
            binary_protocol,
            geospatial,
            graph_dependencies,
            apportionment,
            interpolation,
            tabular_join,
            expression_engine,
            edit_distance,
        )
        for spec in create()
    )


def prior_development_tasks():
    """Never count the previously inspected v0.2 holdouts as new holdouts."""
    return tuple(replace(t, split="development") for t in list_tasks())


def manifest():
    rows = []
    for spec in fresh_specs():
        rows.append(
            {
                **public_task(spec.task, include_cases=True),
                "reference_files": spec.task.reference_files,
                "hidden_cases": spec.task.hidden_cases,
                "verification_cases": spec.verification_cases,
                "provenance": {
                    "kind": "new_authored",
                    "license": "MIT",
                    "external": False,
                    "authoring": "AI-assisted; source/reference/checks authored together; not independent-author verification",
                },
            }
        )
    return rows


def manifest_hash():
    return hashlib.sha256(
        json.dumps(
            manifest(), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
