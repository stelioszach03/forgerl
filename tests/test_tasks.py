"""Trusted reference implementations validate fixtures, never repair agent inputs.

Optional Docker checks use these reference sources inside the same isolated
runner. They are excluded from application task serialization and prompts.
"""

import copy
import inspect
import os
import re
from collections import Counter, deque
from datetime import date, timedelta
from heapq import heapify, heappop, heappush
import pytest
from forgerl.tasks import list_tasks, get_task, public_task, task_manifest_hash


def compact_runs(values):
    out = []
    for value in values:
        if not out or value != out[-1]:
            out.append(value)
    return out


def rotate(values, k):
    if not values:
        return []
    k %= len(values)
    return values[-k:] + values[:-k]


def window_sums(values, k):
    if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
        raise ValueError("positive integer width required")
    return [sum(values[i : i + k]) for i in range(len(values) - k + 1)]


def parse_settings(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip():
            raise ValueError("malformed setting")
        out[key.strip()] = value.strip()
    return out


def duration_seconds(text):
    pattern = r"(\d+)([hms])"
    remaining = re.sub(pattern, "", text)
    matches = re.findall(pattern, text)
    if not matches or remaining.strip():
        raise ValueError("invalid duration")
    return sum(
        int(number) * {"h": 3600, "m": 60, "s": 1}[unit] for number, unit in matches
    )


def compare_versions(left, right):
    def parts(text):
        values = text.split(".")
        if not all(value and value.isascii() and value.isdigit() for value in values):
            raise ValueError("invalid version")
        return [int(value) for value in values]

    a, b = parts(left), parts(right)
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return (a > b) - (a < b)


def aggregate_counts(records):
    out = {}
    for row in records:
        out[row["item"]] = out.get(row["item"], 0) + row["quantity"]
    return out


def invert_multimap(mapping):
    out = {}
    for owner, tags in mapping.items():
        for tag in tags:
            owners = out.setdefault(tag, [])
            if owner not in owners:
                owners.append(owner)
    return out


def deep_merge(left, right):
    out = dict(left)
    for key, value in right.items():
        if isinstance(out.get(key), dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def minimum_coins(coins, amount):
    best = [0] + [amount + 1] * amount
    for total in range(1, amount + 1):
        for coin in coins:
            if coin <= total:
                best[total] = min(best[total], best[total - coin] + 1)
    return best[amount] if best[amount] <= amount else -1


def weighted_mean(values, weights):
    if len(values) != len(weights) or any(w < 0 for w in weights) or sum(weights) <= 0:
        raise ValueError("invalid weights")
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)


def quantile(values, q):
    if not values or not 0 <= q <= 1:
        raise ValueError("invalid quantile")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def merge_intervals(intervals):
    out = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out


def intersect_intervals(left, right):
    return [
        [max(a, c), min(b, d)]
        for a, b in left
        for c, d in right
        if max(a, c) < min(b, d)
    ]


def subtract_intervals(interval, blackouts):
    out = [list(interval)]
    for a, b in blackouts:
        updated = []
        for start, end in out:
            if b <= start or a >= end:
                updated.append([start, end])
            else:
                if start < a:
                    updated.append([start, a])
                if end > b:
                    updated.append([b, end])
        out = updated
    return sorted(out)


def rle_encode(text):
    out = []
    for char in text:
        if out and out[-1][0] == char:
            out[-1][1] += 1
        else:
            out.append([char, 1])
    return out


def rle_decode(runs):
    pieces = []
    for run in runs:
        if not isinstance(run, list) or len(run) != 2:
            raise ValueError("bad shape")
        char, count = run
        if (
            not isinstance(char, str)
            or len(char) != 1
            or type(count) is not int
            or count < 0
        ):
            raise ValueError("invalid run")
        pieces.append(char * count)
    return "".join(pieces)


def split_escaped(text):
    fields = [""]
    escaped = False
    for char in text:
        if escaped:
            fields[-1] += char
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            fields.append("")
        else:
            fields[-1] += char
    if escaped:
        raise ValueError("trailing escape")
    return fields


def shortest_path(graph, start, end):
    queue = deque([(start, [start])])
    seen = {start}
    while queue:
        node, path = queue.popleft()
        if node == end:
            return path
        for neighbor in graph.get(node, []):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
    return []


def topological_order(graph):
    nodes = set(graph)
    for neighbors in graph.values():
        nodes.update(neighbors)
    degree = {node: 0 for node in nodes}
    for neighbors in graph.values():
        for node in set(neighbors):
            degree[node] += 1
    queue = [node for node in nodes if degree[node] == 0]
    heapify(queue)
    out = []
    while queue:
        node = heappop(queue)
        out.append(node)
        for neighbor in set(graph.get(node, [])):
            degree[neighbor] -= 1
            if degree[neighbor] == 0:
                heappush(queue, neighbor)
    if len(out) != len(nodes):
        raise ValueError("cycle")
    return out


def connected_components(graph):
    adjacency = {node: set() for node in graph}
    for node, neighbors in graph.items():
        for neighbor in neighbors:
            adjacency.setdefault(node, set()).add(neighbor)
            adjacency.setdefault(neighbor, set()).add(node)
    seen, groups = set(), []
    for start in sorted(adjacency):
        if start in seen:
            continue
        stack, members = [start], []
        seen.add(start)
        while stack:
            node = stack.pop()
            members.append(node)
            for neighbor in adjacency[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        groups.append(sorted(members))
    return groups


def days_in_month(year, month):
    if not 1 <= year <= 9999 or not 1 <= month <= 12:
        raise ValueError("invalid date")
    if month == 2:
        return 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def add_months(text, months):
    value = date.fromisoformat(text)
    index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(index, 12)
    month = month_zero + 1
    if month == 2:
        length = 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    else:
        length = 30 if month in (4, 6, 9, 11) else 31
    return date(year, month, min(value.day, length)).isoformat()


def business_days(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first:
        raise ValueError("reversed range")
    count = 0
    while first < last:
        count += first.weekday() < 5
        first += timedelta(days=1)
    return count


REFERENCES = {
    function.__name__: function
    for function in (
        compact_runs,
        rotate,
        window_sums,
        parse_settings,
        duration_seconds,
        compare_versions,
        aggregate_counts,
        invert_multimap,
        deep_merge,
        minimum_coins,
        weighted_mean,
        quantile,
        merge_intervals,
        intersect_intervals,
        subtract_intervals,
        rle_encode,
        rle_decode,
        split_escaped,
        shortest_path,
        topological_order,
        connected_components,
        days_in_month,
        add_months,
        business_days,
    )
}
REFERENCE_IMPORTS = "import re\nfrom collections import deque\nfrom datetime import date, timedelta\nfrom heapq import heapify, heappop, heappush\n"


def test_catalog_has_exact_family_disjoint_splits():
    tasks = list_tasks()
    assert len(tasks) == len({task.id for task in tasks}) == 24
    assert Counter(task.split for task in tasks) == {
        "train": 12,
        "validation": 6,
        "test": 6,
    }
    families = {}
    for task in tasks:
        assert task.split == families.setdefault(task.family, task.split)
        assert len(task.public_cases) >= 2 and len(task.hidden_cases) >= 3
        assert len(
            {row["name"] for row in task.public_cases + task.hidden_cases}
        ) == len(task.public_cases) + len(task.hidden_cases)


@pytest.mark.parametrize("task", list_tasks(), ids=lambda task: task.id)
def test_trusted_reference_validates_all_authored_expected_outputs(task):
    function = REFERENCES[task.function_name]
    for row in task.public_cases + task.hidden_cases:
        args, kwargs = copy.deepcopy(row["args"]), copy.deepcopy(row["kwargs"])
        if row.get("expected_error"):
            with pytest.raises(Exception) as caught:
                function(*args, **kwargs)
            assert type(caught.value).__name__ == row["expected_error"]
        else:
            assert (
                function(*args, **kwargs) == pytest.approx(row["expected"])
                if isinstance(row["expected"], float)
                else function(*args, **kwargs) == row["expected"]
            )
        if any(
            phrase in task.description.lower()
            for phrase in ("do not modify", "do not mutate", "must remain unchanged")
        ):
            assert args == row["args"] and kwargs == row["kwargs"]


def test_public_serialization_cannot_leak_hidden_cases():
    task = get_task("graph-topological")
    public = public_task(task, True)
    assert "hidden_cases" not in public
    assert public["public_tests"] == list(task.public_cases)
    public["public_tests"][0]["name"] = "mutated client copy"
    assert task.public_cases[0]["name"] != "mutated client copy"
    assert (
        len(task_manifest_hash()) == 64 and task_manifest_hash() == task_manifest_hash()
    )
    with pytest.raises(KeyError):
        get_task("../untrusted")


@pytest.mark.skipif(
    os.environ.get("FORGERL_RUN_DOCKER_TESTS") != "1",
    reason="requires explicitly enabled isolated Docker runtime",
)
@pytest.mark.parametrize("task", list_tasks(), ids=lambda task: task.id)
def test_initial_regression_fails_and_reference_passes_in_docker(task):
    from forgerl.sandbox import evaluate

    baseline = evaluate(task, task.source)
    assert baseline["passed"] < baseline["total"], (
        f"No visible regression for {task.id}"
    )
    repaired = REFERENCE_IMPORTS + inspect.getsource(REFERENCES[task.function_name])
    for hidden in (False, True):
        result = evaluate(task, repaired, hidden=hidden)
        assert result["passed"] == result["total"], (task.id, hidden, result)
