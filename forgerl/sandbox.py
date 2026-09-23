"""Fail-closed Docker execution, host grading and a local Unix-socket broker.

Production API workers use FORGERL_EXECUTOR_SOCKET and receive no Docker access.
The dedicated broker is started with ``python -m forgerl.sandbox --serve PATH``.
Expected outputs remain in the caller's process, outside the execution payload.
"""

from __future__ import annotations
import argparse
import ast
import json
import math
import os
import re
import socket
import socketserver
import struct
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .tasks import Task

MAX_SOURCE_BYTES = 24000
MAX_PAYLOAD_BYTES = 65536
MAX_OUTPUT_BYTES = 65536
MAX_CASES = 24
EXECUTION_TIMEOUT = 8.0
DEFAULT_IMAGE = "forgerl-sandbox:v1"
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
FORBIDDEN_NAMES = {
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


class SandboxUnavailable(RuntimeError):
    pass


class SandboxRejected(ValueError):
    pass


def validate_source(source: str, function_name: str) -> None:
    if not isinstance(source, str) or len(source.encode()) > MAX_SOURCE_BYTES:
        raise SandboxRejected("Source exceeds the curated repair limit")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", function_name):
        raise SandboxRejected("Invalid function name")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise SandboxRejected("Source is not valid supported Python") from exc
    if not any(
        isinstance(n, ast.FunctionDef) and n.name == function_name for n in tree.body
    ):
        raise SandboxRejected("Required function definition is missing")
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Global, ast.Nonlocal),
        ):
            raise SandboxRejected("Unsupported Python construct")
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if (
                "__" in name
                or (isinstance(node, ast.Attribute) and name.startswith("_"))
                or name in FORBIDDEN_NAMES
            ):
                raise SandboxRejected(
                    "Runtime introspection and host access are unavailable"
                )
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] not in ALLOWED_MODULES for a in node.names):
                raise SandboxRejected(
                    "Import outside the supported standard-library allowlist"
                )
        if isinstance(node, ast.ImportFrom):
            if (
                node.level
                or not node.module
                or node.module.split(".")[0] not in ALLOWED_MODULES
                or any(a.name.startswith("_") or a.name == "*" for a in node.names)
            ):
                raise SandboxRejected(
                    "Import outside the supported standard-library allowlist"
                )


def _payload(source, function_name, cases):
    validate_source(source, function_name)
    if not isinstance(cases, list) or len(cases) > MAX_CASES:
        raise SandboxRejected("Invalid case collection")
    clean = []
    for row in cases:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("name"), str)
            or not isinstance(row.get("args"), list)
            or not isinstance(row.get("kwargs", {}), dict)
        ):
            raise SandboxRejected("Invalid input case")
        clean.append(
            {"name": row["name"], "args": row["args"], "kwargs": row.get("kwargs", {})}
        )
    result = {"source": source, "function_name": function_name, "cases": clean}
    encoded = json.dumps(result, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise SandboxRejected("Execution payload exceeds the input limit")
    return result, encoded


def docker_command(image: str, name: str) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,200}", image):
        raise SandboxUnavailable("Invalid sandbox image configuration")
    return [
        "docker",
        "run",
        "--rm",
        "--interactive",
        "--name",
        name,
        "--network",
        "none",
        "--user",
        "65534:65534",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "32",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--cpus",
        "0.5",
        "--ulimit",
        "nofile=64:64",
        "--ulimit",
        "fsize=1048576:1048576",
        "--log-driver",
        "none",
        image,
    ]


def _bounded_process(
    command: list[str], payload: bytes, timeout: float
) -> tuple[int, bytes, bool]:
    """Drain bounded pipe output; do not use unbounded communicate()."""
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
        )
    except (OSError, ValueError) as exc:
        raise SandboxUnavailable("Docker executor is unavailable") from exc
    chunks: list[bytes] = []
    cap_reached = threading.Event()

    def drain():
        count = 0
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                break
            count += len(chunk)
            if count > MAX_OUTPUT_BYTES:
                cap_reached.set()
                process.kill()
                break
            chunks.append(chunk)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()

    def send_input():
        try:
            process.stdin.write(payload)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    writer = threading.Thread(target=send_input, daemon=True)
    writer.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
        reader.join(timeout=2)
        return -1, b"", True
    except (BrokenPipeError, OSError):
        process.kill()
        process.wait(timeout=2)
    reader.join(timeout=2)
    return process.returncode, b"".join(chunks), cap_reached.is_set()


def _validated_payload(payload: dict):
    if not isinstance(payload, dict):
        raise SandboxRejected("Invalid executor payload")
    if payload.get("kind") == "repository-v2":
        from .bench.sandbox import payload as repository_payload
        return repository_payload(payload["files"], payload["entrypoint"], payload["cases"])
    return _payload(payload["source"], payload["function_name"], payload["cases"])


def execute_docker(payload: dict, image: str | None = None) -> dict:
    clean, encoded = _validated_payload(payload)
    name = "forgerl-" + uuid.uuid4().hex
    selected_image = image or os.environ.get("FORGERL_SANDBOX_IMAGE", DEFAULT_IMAGE)
    try:
        returncode, output, limited = _bounded_process(
            docker_command(selected_image, name), encoded, EXECUTION_TIMEOUT
        )
    finally:
        # Killing the Docker client alone does not reliably stop its container.
        # The explicit bounded cleanup also covers timeout and output-limit exits.
        try:
            subprocess.run(
                ["docker", "rm", "--force", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if limited:
        return {"execution_error": "Execution timeout or output limit exceeded"}
    if returncode == 125 or returncode == 127:
        raise SandboxUnavailable("Sandbox image or Docker runtime is unavailable")
    if returncode != 0:
        # Docker also uses exit 1 for daemon/socket infrastructure failures. They
        # must abort an episode before inference, not become model-test failures
        # or negative controller rewards. Do not expose daemon paths in errors.
        diagnostic = output.decode("utf-8", errors="replace").lower()
        infrastructure_errors = (
            "cannot connect to the docker daemon",
            "permission denied while trying to connect",
            "error during connect",
            "failed to connect",
        )
        if any(pattern in diagnostic for pattern in infrastructure_errors):
            raise SandboxUnavailable("Docker executor connection is unavailable")
        return {
            "execution_error": "Isolated runner failed or exceeded its resource limits"
        }
    try:
        result = json.loads(output)
    except (ValueError, UnicodeDecodeError):
        return {"execution_error": "Runner returned invalid bounded output"}
    return _validate_result(result, clean["cases"])


def _validate_result(result: dict, cases: list[dict]) -> dict:
    if not isinstance(result, dict):
        return {"execution_error": "Malformed runner result"}
    if "execution_error" in result:
        return {"execution_error": str(result["execution_error"])[:200]}
    rows = result.get("cases")
    if not isinstance(rows, list) or len(rows) != len(cases):
        return {"execution_error": "Runner result count mismatch"}
    for expected, row in zip(cases, rows):
        if (
            not isinstance(row, dict)
            or row.get("name") != expected["name"]
            or "actual" not in row
            or not isinstance(row.get("input_mutated"), bool)
            or not isinstance(row.get("error"), (str, type(None)))
        ):
            return {"execution_error": "Runner result identity mismatch"}
    return {"cases": rows}


def execute_broker(payload: dict, path: str) -> dict:
    clean, encoded = _validated_payload(payload)
    data = bytearray()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(EXECUTION_TIMEOUT + 6)
            client.connect(path)
            client.sendall(encoded + b"\n")
            client.shutdown(socket.SHUT_WR)
            while len(data) <= MAX_OUTPUT_BYTES:
                chunk = client.recv(min(4096, MAX_OUTPUT_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
    except (OSError, TimeoutError) as exc:
        raise SandboxUnavailable(
            "Isolated executor is temporarily unavailable"
        ) from exc
    if len(data) > MAX_OUTPUT_BYTES:
        raise SandboxUnavailable("Executor response exceeded transport limit")
    try:
        result = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SandboxUnavailable("Executor returned an invalid response") from exc
    if isinstance(result, dict) and result.get("unavailable"):
        raise SandboxUnavailable("Isolated executor is temporarily unavailable")
    return _validate_result(result, clean["cases"])


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or expected is None:
        return actual is expected
    if isinstance(expected, (int, float)):
        return (
            not isinstance(actual, bool)
            and isinstance(actual, (int, float))
            and math.isfinite(actual)
            and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_same(a, b) for a, b in zip(actual, expected))
        )
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and actual.keys() == expected.keys()
            and all(_same(actual[k], value) for k, value in expected.items())
        )
    return type(actual) is type(expected) and actual == expected


def evaluate(task: Task, source: str, hidden: bool = False) -> dict:
    started = time.monotonic()
    cases = list(task.hidden_cases if hidden else task.public_cases)
    security = {
        "backend": "docker",
        "network": "none",
        "non_root": True,
        "read_only": True,
        "host_mounts": False,
        "capabilities": [],
        "expected_outputs_in_container": False,
        "timeout_s": EXECUTION_TIMEOUT,
        "memory_mb": 128,
        "cpu_limit": 0.5,
        "pids_limit": 32,
        "output_limit_bytes": MAX_OUTPUT_BYTES,
    }
    try:
        payload, _ = _payload(source, task.function_name, cases)
        socket_path = os.environ.get("FORGERL_EXECUTOR_SOCKET")
        result = (
            execute_broker(payload, socket_path)
            if socket_path
            else execute_docker(payload)
        )
    except SandboxRejected as exc:
        result = {"execution_error": str(exc)}
    rows = result.get("cases", [])
    results = []
    for index, case in enumerate(cases):
        row = rows[index] if index < len(rows) else {}
        actual, error = row.get("actual"), row.get("error")
        expected_error = case.get("expected_error")
        mutation_violation = bool(row.get("input_mutated")) and any(
            phrase in task.description.lower()
            for phrase in ("do not modify", "do not mutate", "must remain unchanged")
        )
        if result.get("execution_error"):
            passed = False
            error = result["execution_error"]
        elif mutation_violation:
            passed, error = False, "InputMutation"
        elif expected_error:
            passed = error == expected_error
        else:
            passed = error is None and _same(actual, case["expected"])
        # Hidden grading exports only labels/counts; no hidden inputs, actuals or
        # expected answers flow into model prompts or public traces.
        results.append(
            {
                "name": case["name"],
                "passed": bool(passed),
                "actual": None if hidden else actual,
                "error": ("Held-out case failed" if not passed else None)
                if hidden
                else error,
            }
        )
    return {
        "passed": sum(row["passed"] for row in results),
        "total": len(results),
        "cases": results,
        "elapsed_s": round(time.monotonic() - started, 6),
        "security": security,
    }


class ExecutorServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 4
    slots = threading.BoundedSemaphore(2)


class ExecutorHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(3)
        permitted = os.environ.get("FORGERL_EXECUTOR_ALLOWED_UIDS", "")
        if permitted:
            if not hasattr(socket, "SO_PEERCRED"):
                return
            _, uid, _ = struct.unpack(
                "3i",
                self.connection.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
                ),
            )
            if str(uid) not in {part.strip() for part in permitted.split(",")}:
                return
        if not self.server.slots.acquire(blocking=False):
            self.wfile.write(b'{"unavailable":true}')
            return
        try:
            raw = self.rfile.readline(MAX_PAYLOAD_BYTES + 2)
            if len(raw) > MAX_PAYLOAD_BYTES + 1 or not raw.endswith(b"\n"):
                raise SandboxRejected("Invalid executor request")
            payload = json.loads(raw)
            # Server repeats validation and has no API to accept Docker flags,
            # mounts, arbitrary images, commands, or grading expectations.
            result = execute_docker(payload)
        except SandboxUnavailable:
            result = {"unavailable": True}
        except (ValueError, KeyError, TypeError, OSError):
            result = {"execution_error": "Executor rejected malformed request"}
        finally:
            self.server.slots.release()
        encoded = json.dumps(result, allow_nan=False, separators=(",", ":")).encode()
        if len(encoded) > MAX_OUTPUT_BYTES:
            encoded = b'{"execution_error":"Executor output limit exceeded"}'
        try:
            self.wfile.write(encoded)
        except OSError:
            pass


def serve(path: str) -> None:
    location = Path(path)
    if location.exists():
        if not location.is_socket():
            raise SandboxUnavailable("Refusing to replace a non-socket executor path")
        location.unlink()
    server = ExecutorServer(path, ExecutorHandler)
    os.chmod(path, 0o660)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        location.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ForgeRL dedicated Docker executor broker"
    )
    parser.add_argument("--serve", required=True, help="Private Unix socket path")
    args = parser.parse_args()
    serve(args.serve)
