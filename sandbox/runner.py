"""Trusted in-container runner. NEVER import this module on an API host."""
import ast
import builtins
import json
import resource
import sys

MAX_INPUT = 65536
ALLOWED_MODULES = {"math", "re", "collections", "itertools", "functools", "heapq", "bisect", "statistics", "datetime", "decimal", "fractions", "json", "string"}
SAFE_NAMES = ("abs", "all", "any", "ascii", "bin", "bool", "bytes", "bytearray", "callable", "chr", "complex", "dict", "divmod", "enumerate", "filter", "float", "format", "frozenset", "hash", "hex", "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next", "oct", "ord", "pow", "range", "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "type", "zip", "Exception", "ValueError", "TypeError", "KeyError", "IndexError", "ZeroDivisionError", "RuntimeError", "StopIteration", "AssertionError", "OverflowError")


def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name.split('.')[0] not in ALLOWED_MODULES:
        raise ImportError("Module is not available in the repair sandbox")
    return builtins.__import__(name, globals, locals, fromlist, level)


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (2, 3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError("Input exceeds runner limit")
    payload = json.loads(raw)
    source, function_name = payload["source"], payload["function_name"]
    # The host performs the same AST screening. Isolation is provided by Docker,
    # not by either AST guard or this restricted builtins dictionary.
    tree = ast.parse(source)
    forbidden = (ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Global, ast.Nonlocal)
    for node in ast.walk(tree):
        if isinstance(node, forbidden):
            raise ValueError("Unsupported construct")
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if '__' in name or (isinstance(node, ast.Attribute) and name.startswith('_')):
                raise ValueError("Private runtime access is unavailable")
        if isinstance(node, ast.Import):
            if any(alias.name.split('.')[0] not in ALLOWED_MODULES for alias in node.names):
                raise ValueError("Unsupported import")
        if isinstance(node, ast.ImportFrom):
            if node.level or not node.module or node.module.split('.')[0] not in ALLOWED_MODULES or any(alias.name.startswith('_') or alias.name == '*' for alias in node.names):
                raise ValueError("Unsupported import")
    safe = {name: getattr(builtins, name) for name in SAFE_NAMES}
    safe["__import__"] = restricted_import
    namespace = {"__builtins__": safe}
    # This is the sole generated-code execution point, inside the disposable
    # container with no mounts, network, capabilities or root user.
    exec(compile(tree, "solution.py", "exec"), namespace)
    function = namespace.get(function_name)
    if not callable(function):
        raise ValueError("Required function missing")
    cases = []
    for case in payload["cases"]:
        before = json.dumps([case["args"], case.get("kwargs", {})], sort_keys=True)
        result = {"name": case["name"], "actual": None, "error": None}
        try:
            actual = function(*case["args"], **case.get("kwargs", {}))
            # Convert tuples and other JSON-compatible result containers exactly
            # as transport does; reject unsupported or nonfinite values.
            result["actual"] = json.loads(json.dumps(actual, allow_nan=False))
        except BaseException as exc:
            result["error"] = type(exc).__name__
        result["input_mutated"] = before != json.dumps([case["args"], case.get("kwargs", {})], sort_keys=True)
        cases.append(result)
    print(json.dumps({"cases": cases}, allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        print(json.dumps({"runner_error": type(exc).__name__}))
        sys.exit(1)
