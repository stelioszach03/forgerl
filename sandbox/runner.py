"""Trusted in-container runner. NEVER import this module on an API host."""

import ast
import builtins
import json
import resource
import sys
import types
import re

MAX_INPUT = 65536
ALLOWED_MODULES = {
    "math",
    "re",
    "collections",
    "itertools",
    "functools",
    "heapq",
    "bisect",
    "statistics",
    "datetime",
    "decimal",
    "fractions",
    "json",
    "string",
}
SAFE_NAMES = (
    "abs",
    "all",
    "any",
    "ascii",
    "bin",
    "bool",
    "bytes",
    "bytearray",
    "callable",
    "chr",
    "complex",
    "dict",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "hash",
    "hex",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "oct",
    "ord",
    "pow",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "str",
    "sum",
    "tuple",
    "type",
    "zip",
    "Exception",
    "ValueError",
    "TypeError",
    "KeyError",
    "IndexError",
    "ZeroDivisionError",
    "RuntimeError",
    "StopIteration",
    "AssertionError",
    "OverflowError",
)


def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name.split(".")[0] not in ALLOWED_MODULES:
        raise ImportError("Module is not available in the repair sandbox")
    return builtins.__import__(name, globals, locals, fromlist, level)


def checked_tree(source, local_modules):
    tree = ast.parse(source)
    forbidden = (
        ast.ClassDef,
        ast.AsyncFunctionDef,
        ast.Await,
        ast.Global,
        ast.Nonlocal,
    )
    forbidden_names = {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "breakpoint",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "dir",
        "help",
        "exit",
        "quit",
        "memoryview",
        "print",
    }
    for node in ast.walk(tree):
        if isinstance(node, forbidden):
            raise ValueError("Unsupported construct")
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if (
                "__" in name
                or (isinstance(node, ast.Attribute) and name.startswith("_"))
                or name in forbidden_names
            ):
                raise ValueError("Private runtime access is unavailable")
        if isinstance(node, ast.Import):
            if any(
                alias.name not in local_modules
                and alias.name.split(".")[0] not in ALLOWED_MODULES
                for alias in node.names
            ):
                raise ValueError("Unsupported import")
        if isinstance(node, ast.ImportFrom):
            if (
                node.level
                or not node.module
                or (
                    node.module not in local_modules
                    and node.module.split(".")[0] not in ALLOWED_MODULES
                )
                or any(
                    alias.name.startswith("_") or alias.name == "*"
                    for alias in node.names
                )
            ):
                raise ValueError("Unsupported import")
    return tree


def load_entry(files, entrypoint):
    """Flat modules loaded only in container memory; never write source to disk."""
    local = {name[:-3] for name in files}
    trees = {name[:-3]: checked_tree(source, local) for name, source in files.items()}
    loaded, loading = {}, set()

    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        if level:
            raise ImportError("Relative imports unavailable")
        if name in trees:
            return load(name)
        return restricted_import(name, globals, locals, fromlist, level)

    def load(name):
        if name in loading:
            raise ImportError("Cyclic repository import")
        if name in loaded:
            return loaded[name]
        loading.add(name)
        module = types.ModuleType(name)
        safe = {key: getattr(builtins, key) for key in SAFE_NAMES}
        safe["__import__"] = importer
        module.__dict__["__builtins__"] = safe
        # Sole candidate execution boundary: disposable, networkless container.
        exec(compile(trees[name], name + ".py", "exec"), module.__dict__)
        loaded[name] = module
        loading.remove(name)
        return module

    module_name, function_name = entrypoint.split(":")
    function = load(module_name).__dict__.get(function_name)
    if not callable(function):
        raise ValueError("Required function missing")
    return function


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (2, 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError("Input exceeds runner limit")
    payload = json.loads(raw)
    repository = payload.get("kind") == "repository-v2"
    if repository:
        files, entrypoint = payload["files"], payload["entrypoint"]
        if (
            not isinstance(files, dict)
            or not 1 <= len(files) <= 8
            or any(
                not re.fullmatch(r"[a-z][a-z0-9_]{0,39}\.py", name) or "__" in name
                for name in files
            )
            or any(not isinstance(source, str) for source in files.values())
            or sum(len(source.encode()) for source in files.values()) > 40000
        ):
            raise ValueError("Invalid repository")
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,39}:[a-z][a-z0-9_]{0,59}", entrypoint)
            or "__" in entrypoint
            or entrypoint.split(":")[0] + ".py" not in files
        ):
            raise ValueError("Invalid entrypoint")
        if {name[:-3] for name in files} & ALLOWED_MODULES:
            raise ValueError("Standard library shadowing unavailable")
    else:
        files = {"solution.py": payload["source"]}
        entrypoint = "solution:" + payload["function_name"]
    if not isinstance(payload["cases"], list) or len(payload["cases"]) > 24:
        raise ValueError("Invalid case collection")
    function = None if repository else load_entry(files, entrypoint)
    cases = []
    for case in payload["cases"]:
        before = json.dumps([case["args"], case.get("kwargs", {})], sort_keys=True)
        result = {"name": case["name"], "actual": None, "error": None}
        try:
            # Independent module state per v2 case prevents order-dependent answers.
            if repository:
                function = load_entry(files, entrypoint)
            actual = function(*case["args"], **case.get("kwargs", {}))
            result["actual"] = json.loads(json.dumps(actual, allow_nan=False))
        except BaseException as exc:
            result["error"] = type(exc).__name__
        result["input_mutated"] = before != json.dumps(
            [case["args"], case.get("kwargs", {})], sort_keys=True
        )
        cases.append(result)
    print(json.dumps({"cases": cases}, allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        print(json.dumps({"runner_error": type(exc).__name__}))
        sys.exit(1)
