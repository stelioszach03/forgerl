"""Trusted host grading for bounded in-memory Python repositories.

Candidate code is never imported or executed in this process. The existing
rootless executor is the only execution backend; expected outputs stay here.
"""

from __future__ import annotations
import ast
import json
import os
import re
import time
from .. import sandbox as base

MAX_FILES = 8
MAX_FILES_BYTES = 40000
MODULE = re.compile(r"[a-z][a-z0-9_]{0,39}\.py\Z")
ENTRYPOINT = re.compile(r"([a-z][a-z0-9_]{0,39}):([a-z][a-z0-9_]{0,59})\Z")


def validate_files(files: dict[str, str], entrypoint: str) -> None:
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise base.SandboxRejected("Repository must contain one to eight flat modules")
    if any(
        not isinstance(k, str) or not MODULE.fullmatch(k) or "__" in k for k in files
    ):
        raise base.SandboxRejected("Only flat Python module filenames are supported")
    if (
        any(not isinstance(v, str) for v in files.values())
        or sum(len(v.encode()) for v in files.values()) > MAX_FILES_BYTES
    ):
        raise base.SandboxRejected("Repository source exceeds its bounded input limit")
    match = ENTRYPOINT.fullmatch(entrypoint) if isinstance(entrypoint, str) else None
    if not match or match[1] + ".py" not in files or "__" in entrypoint:
        raise base.SandboxRejected("Invalid repository entrypoint")
    local = {name[:-3] for name in files}
    if local & base.ALLOWED_MODULES:
        raise base.SandboxRejected(
            "Repository modules cannot shadow supported standard libraries"
        )
    imports = {module: set() for module in local}
    for filename, source in files.items():
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise base.SandboxRejected("Repository contains invalid Python") from exc
        if filename == match[1] + ".py" and not any(
            isinstance(n, ast.FunctionDef) and n.name == match[2] for n in tree.body
        ):
            raise base.SandboxRejected("Required entrypoint function is missing")
        for node in ast.walk(tree):
            if isinstance(
                node,
                (
                    ast.ClassDef,
                    ast.AsyncFunctionDef,
                    ast.Await,
                    ast.Global,
                    ast.Nonlocal,
                ),
            ):
                raise base.SandboxRejected("Unsupported Python construct")
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if (
                    "__" in name
                    or (isinstance(node, ast.Attribute) and name.startswith("_"))
                    or name in base.FORBIDDEN_NAMES
                ):
                    raise base.SandboxRejected(
                        "Runtime introspection and host access are unavailable"
                    )
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if (
                    node.level
                    or not node.module
                    or any(a.name.startswith("_") or a.name == "*" for a in node.names)
                ):
                    raise base.SandboxRejected("Unsupported repository import")
                names = [node.module]
            for name in names:
                if name not in local and name.split(".")[0] not in base.ALLOWED_MODULES:
                    raise base.SandboxRejected(
                        "Import outside the supported module allowlist"
                    )
                if name in local:
                    imports[filename[:-3]].add(name)

    def visit(name, trail):
        if name in trail:
            raise base.SandboxRejected("Cyclic repository imports are unsupported")
        for target in imports[name]:
            visit(target, trail | {name})

    for module in local:
        visit(module, set())


def payload(files, entrypoint, cases):
    validate_files(files, entrypoint)
    if not isinstance(cases, list) or len(cases) > base.MAX_CASES:
        raise base.SandboxRejected("Invalid repository case collection")
    clean = []
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("name"), str)
            or not isinstance(case.get("args"), list)
            or not isinstance(case.get("kwargs", {}), dict)
        ):
            raise base.SandboxRejected("Invalid repository input case")
        clean.append(
            {
                "name": case["name"],
                "args": case["args"],
                "kwargs": case.get("kwargs", {}),
            }
        )
    result = {
        "kind": "repository-v2",
        "files": files,
        "entrypoint": entrypoint,
        "cases": clean,
    }
    encoded = json.dumps(result, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > base.MAX_PAYLOAD_BYTES:
        raise base.SandboxRejected("Repository execution payload exceeds input limit")
    return result, encoded


def validate_edits(task, files):
    if set(files) != set(task.files):
        raise base.SandboxRejected("Adding or deleting repository files is unsupported")
    if any(
        files[name] != original and name not in task.allowed_edit_files
        for name, original in task.files.items()
    ):
        raise base.SandboxRejected("Candidate changed a protected repository file")
    validate_files(files, task.entrypoint)


def evaluate(task, files, hidden=False):
    started = time.monotonic()
    cases = list(task.hidden_cases if hidden else task.public_cases)
    result = {}
    try:
        validate_edits(task, files)
        clean, _ = payload(files, task.entrypoint, cases)
        path = os.environ.get("FORGERL_EXECUTOR_SOCKET")
        result = (
            base.execute_broker(clean, path) if path else base.execute_docker(clean)
        )
    except base.SandboxRejected as exc:
        result = {"execution_error": str(exc)}
    rows, results = result.get("cases", []), []
    no_mutation = any(
        phrase in task.description.lower()
        for phrase in ("do not modify", "do not mutate", "must remain unchanged")
    )
    for index, case in enumerate(cases):
        row = rows[index] if index < len(rows) else {}
        actual, error = row.get("actual"), row.get("error")
        if result.get("execution_error"):
            passed, error = False, result["execution_error"]
        elif no_mutation and row.get("input_mutated"):
            passed, error = False, "InputMutation"
        elif case.get("expected_error"):
            passed = error == case["expected_error"]
        else:
            passed = error is None and base._same(actual, case["expected"])
        results.append(
            {
                "name": f"heldout-{index + 1}" if hidden else case["name"],
                "passed": bool(passed),
                "actual": None if hidden else actual,
                "error": (None if passed else "Held-out case failed")
                if hidden
                else error,
            }
        )
    return {
        "passed": sum(r["passed"] for r in results),
        "total": len(results),
        "cases": results,
        "elapsed_s": round(time.monotonic() - started, 6),
        "execution_error": result.get("execution_error"),
        "security": {
            "backend": "rootless-docker",
            "network": "none",
            "read_only": True,
            "non_root": True,
            "host_mounts": False,
            "expected_outputs_in_container": False,
            "memory_mb": 128,
            "cpu_limit": 0.5,
            "pids_limit": 32,
            "timeout_s": base.EXECUTION_TIMEOUT,
        },
    }
