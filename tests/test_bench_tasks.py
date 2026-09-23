"""Fixture integrity plus opt-in real-sandbox validation.

Never exec/import embedded reference or candidate source on the test host.
Set FORGERL_DOCKER_TESTS=1 with the rebuilt repository-v2 runner for behavioral
checks. A fixture passes only when its golden passes BOTH groups and its starter
has an actual visible failure, rather than being a solved/no-op task.
"""
import ast
from collections import Counter, defaultdict
import json
import os
import re

import pytest

from forgerl.bench.tasks import get_task, list_tasks, public_task, task_manifest_hash
from forgerl.bench.sandbox import evaluate, validate_files, payload

TASKS = list_tasks()


def test_catalog_has_fifty_unique_scenarios_and_fixed_family_splits():
    assert len(TASKS) == 50
    assert len({task.id for task in TASKS}) == 50
    assert len({task.title for task in TASKS}) == 50
    assert Counter(task.split for task in TASKS) == {"train": 30, "validation": 10, "test": 10}
    families = defaultdict(set)
    for task in TASKS:
        families[task.family].add(task.split)
    assert len(families) == 10
    assert all(len(splits) == 1 for splits in families.values())
    assert set(Counter(task.family for task in TASKS).values()) == {5}
    assert {task.category for task in TASKS} == {
        "bug_fix", "feature", "multi_file", "refactor", "failing_tests", "long_horizon"
    }


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.id)
def test_repository_fixture_contract(task):
    assert re.fullmatch(r"[a-z][a-z0-9-]+", task.id)
    assert 2 <= len(task.files) <= 8
    assert set(task.files) == set(task.reference_files)
    assert set(task.allowed_edit_files) <= set(task.files)
    assert task.files != task.reference_files
    assert 2 <= len(task.public_cases) <= 24
    assert 4 <= len(task.hidden_cases) <= 24
    assert len(task.description) > 250
    assert task.success_criterion
    changed = {name for name in task.files if task.files[name] != task.reference_files[name]}
    assert changed <= set(task.allowed_edit_files)
    if task.category in {"multi_file", "long_horizon"}:
        assert len(changed) >= 2
    # AST inspection is safe and is not a reference implementation execution.
    for files in (task.files, task.reference_files):
        validate_files(files, task.entrypoint)
        assert sum(len(source.encode()) for source in files.values()) <= 40000
        local_names = {name.removesuffix(".py") for name in files}
        linked = set()
        for name, source in files.items():
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in local_names:
                    linked.add(node.module)
        assert linked
    for cases in (task.public_cases, task.hidden_cases):
        assert len({case["name"] for case in cases}) == len(cases)
        for case in cases:
            assert isinstance(case["args"], list)
            assert isinstance(case["kwargs"], dict)
            assert "expected" in case
            assert case.get("expected_error") in (None, "ValueError")
            json.dumps(case, allow_nan=False)
    for hidden in (False, True):
        cases = list(task.hidden_cases if hidden else task.public_cases)
        execution, _ = payload(task.reference_files, task.entrypoint, cases)
        assert all("expected" not in item and "expected_error" not in item for item in execution["cases"])


def test_public_serialization_excludes_solutions_and_holdouts():
    for task in TASKS:
        for include in (False, True):
            exported = public_task(task, include_cases=include)
            assert "reference_files" not in exported
            assert "hidden_cases" not in exported
            assert "hidden" not in exported
            assert ("public_cases" in exported) is include
            assert exported["files"] == task.files
            assert exported["files"] is not task.files
            if include:
                assert exported["public_cases"][0] is not task.public_cases[0]
        assert get_task(task.id) is task
    with pytest.raises(KeyError):
        get_task("missing-task")


def test_manifest_is_complete_and_stable():
    digest = task_manifest_hash()
    assert len(digest) == 64
    assert digest == task_manifest_hash()
    int(digest, 16)


@pytest.mark.skipif(os.environ.get("FORGERL_DOCKER_TESTS") != "1", reason="real rebuilt Docker sandbox opt-in")
@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.id)
def test_reference_and_reproduction_inside_docker(task):
    for hidden in (False, True):
        result = evaluate(task, task.reference_files, hidden=hidden)
        assert result["execution_error"] is None, (task.id, hidden, result)
        assert result["passed"] == result["total"], (task.id, hidden, result)
    initial = evaluate(task, task.files)
    assert initial["execution_error"] is None, (task.id, initial)
    assert initial["passed"] < initial["total"], (task.id, "starter already solved", initial)
