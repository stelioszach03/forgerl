"""ForgeBench v0.2: 50 authored scenarios in ten miniature repository families.

This module contains trusted fixtures, not an executor. Candidate/reference source
is data and must only run in the isolated sandbox. Holdouts are not exported.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class RepoTask:
    id: str
    title: str
    family: str
    split: str
    category: str
    difficulty: str
    summary: str
    description: str
    files: dict[str, str]
    reference_files: dict[str, str]
    entrypoint: str
    public_cases: tuple[dict[str, Any], ...]
    hidden_cases: tuple[dict[str, Any], ...]
    allowed_edit_files: tuple[str, ...]
    success_criterion: str
    tags: tuple[str, ...]


def case(name: str, request: Any, expected: Any = None, error: str | None = None):
    row = {"name": name, "args": [request], "kwargs": {}, "expected": expected}
    if error is not None:
        row["expected_error"] = error
    return row


def build_family(family, split, reference, specification, variants):
    """Materialize reviewed, explicit mutations; never execute embedded source."""
    reference = {name: content.strip() + "\n" for name, content in reference.items()}
    result = []
    for row in variants:
        files = dict(reference)
        for filename, before, after in row["mutations"]:
            if files[filename].count(before) != 1:
                raise ValueError(
                    f"Ambiguous fixture mutation: {family}/{row['slug']}/{filename}"
                )
            files[filename] = files[filename].replace(before, after)
        criterion = row.get(
            "criterion",
            "All visible and held-out behavioral checks pass, including compatibility regressions; no edits outside the allowed repository source files.",
        )
        result.append(
            RepoTask(
                id=f"{family}-{row['slug']}",
                title=row["title"],
                family=family,
                split=split,
                category=row["category"],
                difficulty=row.get("difficulty", "medium"),
                summary=row["summary"],
                description=specification + "\n\nTask: " + row["instructions"],
                files=files,
                reference_files=dict(reference),
                entrypoint="service:run",
                public_cases=tuple(row["public"]),
                hidden_cases=tuple(row["hidden"]),
                allowed_edit_files=tuple(sorted(reference)),
                success_criterion=criterion,
                tags=(
                    "authored",
                    "python",
                    "miniature-repository",
                    family,
                    row["category"],
                ),
            )
        )
    return result


_TASKS: tuple[RepoTask, ...] | None = None


def list_tasks() -> tuple[RepoTask, ...]:
    global _TASKS
    if _TASKS is None:
        from .catalog import billing, scheduling, inventory, permissions, delivery
        from .catalog import publishing, analytics, workflows, search, federation

        modules = (
            billing,
            scheduling,
            inventory,
            permissions,
            delivery,
            publishing,
            analytics,
            workflows,
            search,
            federation,
        )
        _TASKS = tuple(task for module in modules for task in module.tasks())
    return _TASKS


def get_task(task_id: str) -> RepoTask:
    for item in list_tasks():
        if item.id == task_id:
            return item
    raise KeyError(task_id)


def public_task(task: RepoTask, include_cases: bool = False) -> dict[str, Any]:
    result = {
        key: getattr(task, key)
        for key in (
            "id",
            "title",
            "family",
            "split",
            "category",
            "difficulty",
            "summary",
            "description",
            "entrypoint",
            "success_criterion",
        )
    }
    result["files"] = dict(task.files)
    result["allowed_edit_files"] = list(task.allowed_edit_files)
    result["tags"] = list(task.tags)
    if include_cases:
        # A JSON copy prevents a caller mutating the trusted fixture dictionaries.
        result["public_cases"] = json.loads(json.dumps(task.public_cases))
    return result


def task_manifest_hash() -> str:
    rows = []
    for task in list_tasks():
        row = public_task(task, include_cases=True)
        row["hidden_cases"] = task.hidden_cases
        row["reference_files"] = task.reference_files
        rows.append(row)
    return hashlib.sha256(
        json.dumps(
            rows, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
