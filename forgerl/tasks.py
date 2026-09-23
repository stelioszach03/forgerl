"""Authored, bounded repair tasks; these are not sourced from SWE-bench.

Family-level splits are fixed before any model evaluation. Hidden cases never
appear in public_task(), including when public examples are requested.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

Case = dict[str, Any]

@dataclass(frozen=True)
class Task:
    id: str
    title: str
    family: str
    split: str
    difficulty: str
    summary: str
    description: str
    source: str
    function_name: str
    public_cases: tuple[Case, ...]
    hidden_cases: tuple[Case, ...]
    tags: tuple[str, ...] = field(default_factory=tuple)
    filename: str = "solution.py"


def case(name: str, *args: Any, expected: Any = None, error: str | None = None) -> Case:
    result = {"name": name, "args": list(args), "kwargs": {}, "expected": expected}
    if error:
        result["expected_error"] = error
    return result


def task(id, title, family, split, function, summary, description, source, public, hidden, difficulty="medium"):
    return Task(id, title, family, split, difficulty, summary, description,
                source.strip() + "\n", function, tuple(public), tuple(hidden), (family, "python", "regression"))


_TASKS = (
    task("sequence-runs", "Preserve non-adjacent repeated values", "sequences", "train", "compact_runs",
         "An event compressor removes valid events when values recur later.",
         "Return a new list collapsing only adjacent equal values. Preserve order and allow arbitrary JSON scalar values. Do not modify the input.",
         '''def compact_runs(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result''',
         [case("separated repeats", [1, 1, 2, 1], expected=[1, 2, 1]), case("one run", ["a", "a"], expected=["a"])],
         [case("empty", [], expected=[]), case("null values", [None, None, "x", None], expected=[None, "x", None]),
          case("alternating", [0, 1, 0, 1], expected=[0, 1, 0, 1]), case("several runs", [3, 3, 2, 2, 2, 3, 3], expected=[3, 2, 3])]),
    task("sequence-rotate", "Rotate a queue in either direction", "sequences", "train", "rotate",
         "Queue rotation mishandles empty queues and large offsets.",
         "Rotate a list right by integer k positions. Negative k rotates left. Empty input returns an empty list. Do not modify the input.",
         '''def rotate(values, k):
    if k <= 0:
        return values[:]
    return values[-k:] + values[:-k]''',
         [case("large offset", [1, 2, 3], 4, expected=[3, 1, 2]), case("negative", [1, 2, 3], -1, expected=[2, 3, 1])],
         [case("empty", [], 7, expected=[]), case("zero", [1, 2], 0, expected=[1, 2]),
          case("multiple", [1, 2, 3], 6, expected=[1, 2, 3]), case("large negative", [1, 2, 3, 4], -9, expected=[2, 3, 4, 1])], "easy"),
    task("sequence-windows", "Include the last complete rolling window", "sequences", "train", "window_sums",
         "Rolling totals omit a boundary window and accept invalid sizes.",
         "Return sums of all consecutive windows of width k, in order. k must be a positive integer or raise ValueError. If k exceeds the list length return [].",
         '''def window_sums(values, k):
    return [sum(values[i:i+k]) for i in range(len(values) - k)]''',
         [case("last window", [1, 2, 3, 4], 2, expected=[3, 5, 7]), case("invalid", [1, 2], 0, error="ValueError")],
         [case("equal width", [2, -1, 4], 3, expected=[5]), case("singletons", [-2, 0, 3], 1, expected=[-2, 0, 3]),
          case("too wide", [1], 3, expected=[]), case("negative size", [], -1, error="ValueError")]),
    task("text-key-value", "Parse configuration values containing equals", "text_parsing", "train", "parse_settings",
         "A settings parser truncates values and mishandles whitespace.",
         "Parse nonempty newline-separated key=value lines. Ignore blank lines and lines whose first non-whitespace character is #. Strip surrounding key/value whitespace, preserve further equals signs in values, and let the last duplicate key win. Missing equals or an empty key raises ValueError.",
         '''def parse_settings(text):
    result = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        parts = line.split('=')
        result[parts[0]] = parts[1]
    return result''',
         [case("embedded equals", "token = a=b\ncount=2", expected={"token": "a=b", "count": "2"}), case("comment", "  # comment\nx=yes", expected={"x": "yes"})],
         [case("empty", " \n\n", expected={}), case("duplicate", "x=1\nx=2", expected={"x": "2"}),
          case("empty value", "empty = ", expected={"empty": ""}), case("malformed", "oops", error="ValueError"), case("empty key", " =x", error="ValueError")]),
    task("text-duration", "Read compound duration strings", "text_parsing", "train", "duration_seconds",
         "A duration parser reads only the first component.",
         "Parse a nonempty sequence of unsigned integer components with units h, m or s, for example '1h 2m 3s'. Whitespace may surround or separate components. Units may repeat and appear in any order. Reject any unmatched characters, decimals, negative numbers or empty input with ValueError. Return total seconds.",
         r'''import re

def duration_seconds(text):
    match = re.search(r'(\d+)([hms])', text)
    if not match:
        return 0
    return int(match.group(1)) * {'h': 3600, 'm': 60, 's': 1}[match.group(2)]''',
         [case("compound", "1h 2m 3s", expected=3723), case("bad unit", "2d", error="ValueError")],
         [case("repeated", "2m1m", expected=180), case("surrounding spaces", " 0h 7s ", expected=7),
          case("junk suffix", "3s!", error="ValueError"), case("negative", "-2m", error="ValueError"), case("empty", " ", error="ValueError")]),
    task("text-version", "Compare dotted numeric versions", "text_parsing", "train", "compare_versions",
         "Version ordering uses string comparison instead of component values.",
         "Compare two dot-separated versions made of one or more nonnegative integer components. Return -1, 0 or 1. Missing trailing components are zero; leading zeroes are allowed. Empty components or non-digit characters raise ValueError.",
         '''def compare_versions(left, right):
    return (left > right) - (left < right)''',
         [case("numeric ordering", "1.10", "1.2", expected=1), case("trailing zeros", "1.0", "1", expected=0)],
         [case("less", "2.9", "3", expected=-1), case("leading zero", "01.002", "1.2.0", expected=0),
          case("empty component", "1..2", "1", error="ValueError"), case("suffix", "1a", "1", error="ValueError")]),
    task("mapping-counts", "Aggregate inventory updates", "mappings", "train", "aggregate_counts",
         "Repeated inventory records overwrite earlier quantities.",
         "Each record has item (string) and quantity (integer). Sum all quantities per item, retain zero and negative totals, and return a dictionary. Input records must remain unchanged.",
         '''def aggregate_counts(records):
    return {record['item']: record['quantity'] for record in records}''',
         [case("repeated", [{"item": "a", "quantity": 3}, {"item": "a", "quantity": 2}], expected={"a": 5}),
          case("two items", [{"item": "b", "quantity": 1}, {"item": "a", "quantity": -2}], expected={"b": 1, "a": -2})],
         [case("empty", [], expected={}), case("zero sum", [{"item": "x", "quantity": 4}, {"item": "x", "quantity": -4}], expected={"x": 0}),
          case("interleaved", [{"item": "x", "quantity": 1}, {"item": "y", "quantity": 2}, {"item": "x", "quantity": -3}], expected={"x": -2, "y": 2})], "easy"),
    task("mapping-invert", "Invert a multimap without losing owners", "mappings", "train", "invert_multimap",
         "An index stores only the final owner of each tag.",
         "Given a dictionary mapping strings to lists of string tags, return each tag mapped to its owners. Preserve input key order in owner lists. Repeated tags for the same owner must not duplicate that owner.",
         '''def invert_multimap(mapping):
    result = {}
    for owner, tags in mapping.items():
        for tag in tags:
            result[tag] = [owner]
    return result''',
         [case("shared", {"a": ["x"], "b": ["x", "y"]}, expected={"x": ["a", "b"], "y": ["b"]}), case("duplicates", {"a": ["x", "x"]}, expected={"x": ["a"]})],
         [case("empty", {}, expected={}), case("empty list", {"a": [], "b": ["y"]}, expected={"y": ["b"]}),
          case("order", {"z": ["x", "y"], "a": ["y", "x", "y"]}, expected={"x": ["z", "a"], "y": ["z", "a"]})]),
    task("mapping-merge", "Merge nested configuration dictionaries", "mappings", "train", "deep_merge",
         "Applying a configuration override erases unrelated nested settings.",
         "Recursively merge two JSON dictionaries into a new dictionary. When both values are dictionaries, merge recursively; otherwise the right value replaces the left. Lists are replaced, not concatenated. Do not mutate either input.",
         '''def deep_merge(left, right):
    result = dict(left)
    result.update(right)
    return result''',
         [case("nested", {"db": {"host": "a", "port": 1}}, {"db": {"port": 2}}, expected={"db": {"host": "a", "port": 2}}),
          case("replace list", {"x": [1]}, {"x": [2]}, expected={"x": [2]})],
         [case("new key", {}, {"x": {"y": 1}}, expected={"x": {"y": 1}}), case("replace type", {"x": {"a": 1}}, {"x": None}, expected={"x": None}),
          case("nested depth", {"x": {"y": {"a": 1, "b": 2}}}, {"x": {"y": {"a": 3}}}, expected={"x": {"y": {"a": 3, "b": 2}}})]),
    task("numeric-coins", "Find an optimal bounded-amount coin count", "numeric_algorithms", "train", "minimum_coins",
         "Greedy change-making fails for noncanonical coin systems.",
         "Return the minimum number of coins to make nonnegative integer amount using unlimited coins of the supplied positive integer denominations. Return -1 if impossible, and 0 for amount zero. An empty coin list is allowed. Test amounts are at most 1000.",
         '''def minimum_coins(coins, amount):
    count = 0
    for coin in sorted(coins, reverse=True):
        count += amount // coin
        amount %= coin
    return count if amount == 0 else -1''',
         [case("noncanonical", [1, 3, 4], 6, expected=2), case("impossible", [4, 6], 7, expected=-1)],
         [case("zero", [], 0, expected=0), case("empty", [], 2, expected=-1), case("duplicate coins", [2, 2, 5], 10, expected=2), case("greedy trap", [1, 7, 10], 14, expected=2)]),
    task("numeric-weighted", "Compute a weighted mean correctly", "numeric_algorithms", "train", "weighted_mean",
         "Weighted measurements are divided by the number of samples.",
         "Return sum(value*weight)/sum(weight). Lists must have equal length, nonnegative weights and positive total weight; otherwise raise ValueError. Inputs are finite numbers.",
         '''def weighted_mean(values, weights):
    return sum(v * w for v, w in zip(values, weights)) / len(values)''',
         [case("unequal weights", [10, 20], [1, 3], expected=17.5), case("zero total", [1, 2], [0, 0], error="ValueError")],
         [case("zero weight", [999, 2], [0, 2], expected=2), case("length mismatch", [1, 2], [1], error="ValueError"),
          case("negative", [1, 2], [2, -1], error="ValueError"), case("empty", [], [], error="ValueError")]),
    task("numeric-quantile", "Interpolate a quantile from sorted measurements", "numeric_algorithms", "train", "quantile",
         "A percentile helper indexes unsorted input and truncates fractions.",
         "For nonempty finite numeric values and q in [0,1], sort a copy, set p=(n-1)*q and linearly interpolate between floor(p) and ceil(p). Empty values or q outside [0,1] raises ValueError. Do not modify input.",
         '''def quantile(values, q):
    return values[int((len(values) - 1) * q)]''',
         [case("sort and interpolate", [30, 0, 10, 20], 0.5, expected=15), case("quarter", [0, 100], 0.25, expected=25)],
         [case("single", [7], 0.9, expected=7), case("max", [4, 1, 3], 1, expected=4), case("empty", [], 0.5, error="ValueError"), case("outside", [1], -0.1, error="ValueError")]),
    task("interval-merge", "Merge touching reservation intervals", "intervals", "validation", "merge_intervals",
         "Reservation consolidation assumes input order and drops outer bounds.",
         "Intervals are [start,end] numeric pairs with start<end. Return sorted disjoint intervals, merging overlaps and touching endpoints. Do not mutate the input.",
         '''def merge_intervals(intervals):
    result = []
    for start, end in intervals:
        if result and start < result[-1][1]:
            result[-1][1] = end
        else:
            result.append([start, end])
    return result''',
         [case("unsorted touching", [[5, 8], [1, 3], [3, 6]], expected=[[1, 8]]), case("contained", [[1, 10], [2, 3]], expected=[[1, 10]])],
         [case("empty", [], expected=[]), case("separated", [[3, 4], [0, 1]], expected=[[0, 1], [3, 4]]),
          case("negative", [[-3, -1], [-2, 2], [5, 6]], expected=[[-3, 2], [5, 6]])]),
    task("interval-intersection", "Intersect half-open availability intervals", "intervals", "validation", "intersect_intervals",
         "Availability intersection includes zero-length meetings.",
         "Each input is a sorted list of disjoint half-open [start,end) intervals with start<end. Return sorted nonempty intersections as [start,end] pairs. Merely touching endpoints do not overlap.",
         '''def intersect_intervals(left, right):
    result = []
    for a, b in left:
        for c, d in right:
            if max(a, c) <= min(b, d):
                result.append([max(a, c), min(b, d)])
    return result''',
         [case("touching", [[1, 3]], [[3, 5]], expected=[]), case("overlap", [[1, 5]], [[2, 4]], expected=[[2, 4]])],
         [case("empty", [], [[1, 2]], expected=[]), case("several", [[0, 2], [4, 8]], [[1, 5], [6, 9]], expected=[[1, 2], [4, 5], [6, 8]]),
          case("same", [[-1, 2]], [[-1, 2]], expected=[[-1, 2]])], "easy"),
    task("interval-subtract", "Subtract blackout windows from a reservation", "intervals", "validation", "subtract_intervals",
         "A blackout overlap deletes an entire valid reservation.",
         "Given one half-open [start,end) interval and arbitrary half-open blackout intervals, return the sorted nonempty portions remaining. Blackouts may overlap, touch, or extend beyond the original interval. Inputs have start<end.",
         '''def subtract_intervals(interval, blackouts):
    start, end = interval
    for a, b in blackouts:
        if a < end and b > start:
            return []
    return [[start, end]]''',
         [case("middle gap", [0, 10], [[3, 6]], expected=[[0, 3], [6, 10]]), case("outside", [2, 5], [[5, 9]], expected=[[2, 5]])],
         [case("overlapping", [0, 12], [[7, 10], [3, 8]], expected=[[0, 3], [10, 12]]), case("full", [2, 4], [[0, 8]], expected=[]),
          case("trim ends", [0, 10], [[-1, 2], [8, 12]], expected=[[2, 8]]), case("no blackouts", [1, 2], [], expected=[[1, 2]])]),
    task("codec-rle-encode", "Encode the final run in run-length compression", "codecs", "validation", "rle_encode",
         "A compressor silently omits its final character run.",
         "Encode a string as a list of [character,count] pairs for adjacent runs. Empty string returns []. Unicode characters are supported as Python string characters.",
         '''def rle_encode(text):
    result = []
    previous = None
    count = 0
    for char in text:
        if char != previous:
            if count:
                result.append([previous, count])
            previous = char
            count = 1
        else:
            count += 1
    return result''',
         [case("last run", "aaabb", expected=[["a", 3], ["b", 2]]), case("single", "x", expected=[["x", 1]])],
         [case("empty", "", expected=[]), case("unicode", "ααβ", expected=[["α", 2], ["β", 1]]),
          case("alternating", "aba", expected=[["a", 1], ["b", 1], ["a", 1]])], "easy"),
    task("codec-rle-decode", "Reject malformed run-length payloads", "codecs", "validation", "rle_decode",
         "A decoder accepts negative counts and multicharacter run keys.",
         "Decode a list of [character,count] pairs. A character must be a string of length one and count a nonnegative integer (booleans are invalid). Malformed pairs raise ValueError. A zero count contributes nothing. Valid output has at most 10000 characters.",
         '''def rle_decode(runs):
    return ''.join(char * count for char, count in runs)''',
         [case("valid", [["a", 2], ["b", 1]], expected="aab"), case("negative", [["x", -1]], error="ValueError")],
         [case("empty", [], expected=""), case("zero", [["x", 0], ["y", 2]], expected="yy"),
          case("long key", [["ab", 2]], error="ValueError"), case("boolean", [["x", True]], error="ValueError"), case("bad shape", [["x"]], error="ValueError")]),
    task("codec-escaped-fields", "Split escaped delimited fields", "codecs", "validation", "split_escaped",
         "Escaped delimiters are split as if they were field boundaries.",
         "Split text at unescaped | characters. Backslash escapes the next character, including | or backslash, and is removed. Preserve empty fields. A trailing unpaired backslash raises ValueError.",
         '''def split_escaped(text):
    return text.split('|')''',
         [case("escaped pipe", "a\\|b|c", expected=["a|b", "c"]), case("empty fields", "|a||", expected=["", "a", "", ""])],
         [case("empty", "", expected=[""]), case("escaped backslash", "a\\\\|b", expected=["a\\", "b"]),
          case("general escape", "a\\q", expected=["aq"]), case("trailing slash", "abc\\", error="ValueError")]),
    task("graph-shortest-path", "Find a shortest directed path without cycling", "graphs", "test", "shortest_path",
         "Path search loops on cycles and returns a non-shortest route.",
         "Given a directed adjacency dictionary and start/end strings, return a shortest path as a list of node names, or [] if unreachable. A missing adjacency key has no outgoing edges. Return [start] if start==end. Break ties by neighbor list order.",
         '''def shortest_path(graph, start, end):
    stack = [(start, [start])]
    seen = set()
    while stack:
        node, path = stack.pop()
        if node == end:
            return path
        if node in seen:
            continue
        seen.add(node)
        for neighbor in graph.get(node, []):
            stack.append((neighbor, path + [neighbor]))
    return []''',
         [case("shorter branch", {"a": ["b", "c"], "b": ["z"], "c": ["d"], "d": ["z"]}, "a", "z", expected=["a", "b", "z"]),
          case("unreachable", {"a": ["b"], "b": ["a"]}, "a", "z", expected=[])],
         [case("same", {}, "x", "x", expected=["x"]), case("tie order", {"a": ["b", "c"], "b": ["z"], "c": ["z"]}, "a", "z", expected=["a", "b", "z"]),
          case("neighbor only", {"a": ["b"]}, "a", "b", expected=["a", "b"]), case("self loop", {"a": ["a", "b"], "b": ["c"]}, "a", "c", expected=["a", "b", "c"])]),
    task("graph-topological", "Order dependencies deterministically", "graphs", "test", "topological_order",
         "A dependency planner returns insertion order even when prerequisites are unmet.",
         "Given a directed graph whose edges u->v mean u must appear before v, return a topological ordering of all keys and neighbors. At every step choose the lexicographically smallest available node. Duplicate edges count once. Raise ValueError for a cycle.",
         '''def topological_order(graph):
    return sorted(graph)''',
         [case("dependency", {"z": ["a"], "a": []}, expected=["z", "a"]), case("cycle", {"a": ["b"], "b": ["a"]}, error="ValueError")],
         [case("neighbor node", {"a": ["b"]}, expected=["a", "b"]), case("available ordering", {"b": ["d"], "a": ["c"], "c": [], "d": []}, expected=["a", "b", "c", "d"]),
          case("duplicate", {"a": ["b", "b"]}, expected=["a", "b"]), case("empty", {}, expected=[])], "hard"),
    task("graph-components", "Group undirected connected components", "graphs", "test", "connected_components",
         "A grouping helper mistakes adjacency lists for whole components.",
         "Treat every listed adjacency edge as undirected even if listed on only one side. Include all keys and neighbors, including isolated keys. Return each component sorted, and sort components by their first node. Nodes are strings.",
         '''def connected_components(graph):
    return [sorted(set([node] + neighbors)) for node, neighbors in graph.items()]''',
         [case("transitive", {"a": ["b"], "b": ["c"], "x": []}, expected=[["a", "b", "c"], ["x"]]),
          case("reverse edge", {"a": [], "b": ["a"]}, expected=[["a", "b"]])],
         [case("empty", {}, expected=[]), case("neighbor only", {"z": ["y"]}, expected=[["y", "z"]]),
          case("self and duplicate", {"b": ["b", "a", "a"], "x": []}, expected=[["a", "b"], ["x"]])]),
    task("calendar-leap-days", "Count the days in a Gregorian month", "calendar_arithmetic", "test", "days_in_month",
         "February treats every year divisible by four as a leap year.",
         "Return Gregorian month length for integer year in 1..9999 and month in 1..12. Leap years are divisible by 4 except century years not divisible by 400. Invalid year or month raises ValueError.",
         '''def days_in_month(year, month):
    if month == 2:
        return 29 if year % 4 == 0 else 28
    return 30 if month in [4, 6, 9, 11] else 31''',
         [case("century", 1900, 2, expected=28), case("four hundred", 2000, 2, expected=29)],
         [case("ordinary leap", 2024, 2, expected=29), case("april", 2026, 4, expected=30),
          case("invalid month", 2026, 13, error="ValueError"), case("invalid year", 0, 1, error="ValueError")]),
    task("calendar-month-shift", "Shift dates across month and year boundaries", "calendar_arithmetic", "test", "add_months",
         "Monthly recurrence overflows on short months and negative offsets.",
         "Given an ISO YYYY-MM-DD date and integer month offset, return the shifted ISO date. Preserve the day when possible; otherwise clamp it to the final day of the target month. Offsets may be negative. Inputs and target years are valid Gregorian years.",
         '''from datetime import date

def add_months(text, months):
    value = date.fromisoformat(text)
    return date(value.year, value.month + months, value.day).isoformat()''',
         [case("short month", "2024-01-31", 1, expected="2024-02-29"), case("year boundary", "2025-12-15", 2, expected="2026-02-15")],
         [case("negative", "2026-01-31", -2, expected="2025-11-30"), case("nonleap", "2024-02-29", 12, expected="2025-02-28"),
          case("zero", "2026-09-22", 0, expected="2026-09-22"), case("large offset", "2020-03-31", 25, expected="2022-04-30")]),
    task("calendar-business-days", "Count weekdays over a half-open date range", "calendar_arithmetic", "test", "business_days",
         "A reporting period counts weekend dates and the excluded end date.",
         "Count Monday-Friday dates in [start,end), using ISO YYYY-MM-DD strings. No holidays are excluded. Equal dates return zero; end earlier than start raises ValueError.",
         '''from datetime import date

def business_days(start, end):
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1''',
         [case("full week", "2026-09-21", "2026-09-28", expected=5), case("weekend", "2026-09-26", "2026-09-28", expected=0)],
         [case("equal", "2026-09-22", "2026-09-22", expected=0), case("friday included", "2026-09-25", "2026-09-28", expected=1),
          case("year boundary", "2025-12-31", "2026-01-03", expected=3), case("reversed", "2026-09-23", "2026-09-22", error="ValueError")]),
)
_BY_ID = {item.id: item for item in _TASKS}


def list_tasks() -> list[Task]:
    return list(_TASKS)


def get_task(task_id: str) -> Task:
    try:
        return _BY_ID[task_id]
    except KeyError:
        raise KeyError(f"Unknown curated task: {task_id}") from None


def public_task(value: Task, include_cases: bool = False) -> dict[str, Any]:
    result = {key: getattr(value, key) for key in (
        "id", "title", "family", "split", "difficulty", "summary", "description", "source", "filename", "function_name")}
    result.update(public_tests_count=len(value.public_cases), tags=list(value.tags))
    if include_cases:
        result["public_tests"] = json.loads(json.dumps(value.public_cases))
    return result


def task_manifest_hash() -> str:
    """Fingerprint full grading content, including hidden tests, without exposing it."""
    rows = [dict(public_task(item, True), hidden_cases=item.hidden_cases) for item in _TASKS]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
