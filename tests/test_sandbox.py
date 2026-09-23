import json
import os
from unittest.mock import patch
import pytest
from forgerl import sandbox
from forgerl.tasks import get_task, list_tasks


def test_every_initial_source_passes_supported_ast_screen():
    for task in list_tasks():
        sandbox.validate_source(task.source, task.function_name)


@pytest.mark.parametrize("source", [
    "import os\ndef repair(): return os.getcwd()",
    "def repair(): return open('/etc/passwd').read()",
    "def repair(): return (1).__class__",
    "def repair(): return getattr(1, '__class__')",
    "from collections import *\ndef repair(): return 1",
    "def repair(): return eval('1')",
])
def test_ast_screen_blocks_obvious_escape_inputs(source):
    with pytest.raises(sandbox.SandboxRejected):
        sandbox.validate_source(source, "repair")


def test_private_helper_variables_are_allowed_but_not_runtime_attributes():
    sandbox.validate_source("def _helper(_xs):\n    return [x for _, x in enumerate(_xs)]\ndef repair(xs):\n    return _helper(xs)", "repair")
    for source in (
        "def repair(xs): return xs._private",
        "def repair(xs): return xs.__class__",
        "from collections import _sys\ndef repair(xs): return xs",
        "def repair(xs): return __private(xs)",
    ):
        with pytest.raises(sandbox.SandboxRejected):
            sandbox.validate_source(source, "repair")


def test_docker_boundary_is_networkless_unprivileged_and_has_no_host_mount():
    command = sandbox.docker_command("forgerl-sandbox:v1", "forgerl-test")
    assert command[:4] == ["docker", "run", "--rm", "--interactive"]
    for flag, expected in {"--network": "none", "--user": "65534:65534", "--cap-drop": "ALL",
                           "--memory": "128m", "--pids-limit": "32", "--cpus": "0.5"}.items():
        assert command[command.index(flag) + 1] == expected
    assert "--read-only" in command
    assert not any(flag in command for flag in ("--privileged", "--mount", "-v", "--volume", "--publish"))


def test_expected_values_do_not_cross_execution_boundary():
    task = get_task("sequence-runs")
    payload, encoded = sandbox._payload(task.source, task.function_name, list(task.hidden_cases))
    assert "expected" not in encoded.decode()
    assert all(set(row) == {"name", "args", "kwargs"} for row in payload["cases"])


def test_host_grader_compares_values_and_handles_expected_exceptions():
    task = get_task("sequence-windows")
    fake = {"cases": [
        {"name": "last window", "actual": [3, 5, 7], "error": None, "input_mutated": False},
        {"name": "invalid", "actual": None, "error": "ValueError", "input_mutated": False},
    ]}
    with patch.dict(os.environ, {"FORGERL_EXECUTOR_SOCKET": "/private/executor.sock"}), patch.object(sandbox, "execute_broker", return_value=fake) as broker, patch.object(sandbox, "execute_docker") as docker:
        result = sandbox.evaluate(task, "def window_sums(values, k): return []")
    assert result["passed"] == result["total"] == 2
    assert "expected" not in json.dumps(broker.call_args.args[0])
    docker.assert_not_called()
    assert not sandbox._same(True, 1)
    assert sandbox._same(0.3, 0.1 + 0.2)


def test_no_host_fallback_when_broker_is_down():
    task = get_task("sequence-runs")
    with patch.dict(os.environ, {"FORGERL_EXECUTOR_SOCKET": "/missing"}), patch.object(sandbox, "execute_broker", side_effect=sandbox.SandboxUnavailable("down")), patch.object(sandbox, "execute_docker") as docker:
        with pytest.raises(sandbox.SandboxUnavailable):
            sandbox.evaluate(task, task.source)
    docker.assert_not_called()


def test_hidden_results_do_not_export_actual_answers():
    task = get_task("sequence-runs")
    fake = {"cases": [{"name": row["name"], "actual": row["expected"], "error": None, "input_mutated": False} for row in task.hidden_cases]}
    with patch.dict(os.environ, {}, clear=True), patch.object(sandbox, "execute_docker", return_value=fake):
        result = sandbox.evaluate(task, task.source, hidden=True)
    assert result["passed"] == result["total"]
    assert all(row["actual"] is None for row in result["cases"])


def test_mutation_is_a_failure_when_contract_requires_copy():
    task = get_task("sequence-runs")
    fake = {"cases": [{"name": row["name"], "actual": row["expected"], "error": None, "input_mutated": True} for row in task.public_cases]}
    with patch.dict(os.environ, {}, clear=True), patch.object(sandbox, "execute_docker", return_value=fake):
        result = sandbox.evaluate(task, task.source)
    assert result["passed"] == 0
    assert all(row["error"] == "InputMutation" for row in result["cases"])


def test_invalid_runner_output_fails_closed_and_timeout_is_cleaned_up():
    payload, _ = sandbox._payload("def repair(): return None", "repair", [{"name": "x", "args": [], "kwargs": {}}])
    with patch.object(sandbox, "_bounded_process", return_value=(-1, b"", True)), patch.object(sandbox.subprocess, "run") as cleanup:
        result = sandbox.execute_docker(payload)
    assert "execution_error" in result
    assert cleanup.call_args.args[0][:3] == ["docker", "rm", "--force"]
    assert sandbox._validate_result({"cases": [{"name": "x", "error": None}]}, payload["cases"]).get("execution_error")


def test_rejected_source_never_starts_execution():
    task = get_task("sequence-runs")
    with patch.object(sandbox, "execute_docker") as docker:
        result = sandbox.evaluate(task, "import os\ndef compact_runs(values): return []")
    assert result["passed"] == 0
    docker.assert_not_called()


@pytest.mark.skipif(os.environ.get('FORGERL_RUN_DOCKER_TESTS') != '1', reason='requires explicitly enabled isolated Docker runtime')
@pytest.mark.parametrize('source', [
    'def compact_runs(values):\n    while True:\n        pass\n',
    "def compact_runs(values):\n    return 'x' * 200000\n",
])
def test_real_docker_cpu_and_output_limits(source):
    import time
    started = time.monotonic()
    result = sandbox.evaluate(get_task('sequence-runs'), source)
    assert result['passed'] == 0
    assert time.monotonic() - started < 18
    assert all(row['error'] for row in result['cases'])


def test_unix_broker_roundtrip_keeps_grading_outside_executor():
    import tempfile
    import threading
    task = get_task('sequence-runs')
    observed = []
    def fake_docker(payload):
        observed.append(payload)
        return {'cases': [{'name': row['name'], 'actual': [], 'error': None, 'input_mutated': False}
                          for row in payload['cases']]}
    with tempfile.TemporaryDirectory(dir='/tmp') as directory, patch.dict(os.environ, {'FORGERL_EXECUTOR_ALLOWED_UIDS': ''}), patch.object(sandbox, 'execute_docker', side_effect=fake_docker):
        path = directory + '/executor.sock'
        server = sandbox.ExecutorServer(path, sandbox.ExecutorHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload, _ = sandbox._payload(task.source, task.function_name, list(task.hidden_cases))
            result = sandbox.execute_broker(payload, path)
            assert len(result['cases']) == len(task.hidden_cases)
            assert observed and all('expected' not in row for row in observed[0]['cases'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


@pytest.mark.parametrize('diagnostic', [
    b'Cannot connect to the Docker daemon at unix:///run/user/1001/docker.sock. Is the docker daemon running?',
    b'permission denied while trying to connect to the Docker daemon socket',
    b'error during connect: Get "http://%2Frun%2Fuser%2F1001%2Fdocker.sock/v1.51/containers/json": EOF',
    b'failed to connect to the docker API at unix:///run/user/1001/docker.sock; dial unix: permission denied',
])
def test_docker_exit_one_connection_failures_abort_grading(diagnostic):
    task = get_task('sequence-runs')
    with patch.dict(os.environ, {}, clear=True), patch.object(sandbox, '_bounded_process', return_value=(1, diagnostic, False)), patch.object(sandbox.subprocess, 'run') as cleanup:
        with pytest.raises(sandbox.SandboxUnavailable, match='connection is unavailable') as caught:
            sandbox.evaluate(task, task.source)
    assert '/run/user' not in str(caught.value)
    assert cleanup.call_args.args[0][:3] == ['docker', 'rm', '--force']


def test_runner_failure_stays_a_model_execution_result():
    task = get_task('sequence-runs')
    with patch.dict(os.environ, {}, clear=True), patch.object(sandbox, '_bounded_process', return_value=(1, b'{"runner_error":"ValueError"}', False)), patch.object(sandbox.subprocess, 'run'):
        result = sandbox.evaluate(task, task.source)
    assert result['passed'] == 0
    assert all(row['error'] == 'Isolated runner failed or exceeded its resource limits' for row in result['cases'])


def test_successful_output_is_not_misclassified_by_error_phrase():
    task = get_task('sequence-runs')
    output = {'cases': [{'name': row['name'], 'actual': 'Cannot connect to the Docker daemon', 'error': None, 'input_mutated': False} for row in task.public_cases]}
    with patch.dict(os.environ, {}, clear=True), patch.object(sandbox, '_bounded_process', return_value=(0, json.dumps(output).encode(), False)), patch.object(sandbox.subprocess, 'run'):
        result = sandbox.evaluate(task, task.source)
    assert result['passed'] == 0
    assert result['cases'][0]['actual'] == 'Cannot connect to the Docker daemon'


@pytest.mark.skipif(os.environ.get('FORGERL_RUN_DOCKER_TESTS') != '1', reason='requires explicitly enabled isolated Docker runtime')
def test_real_docker_accepts_underscore_helpers_and_locals():
    source = '''def _compact(_values):
    _result = []
    for _, _value in enumerate(_values):
        if not _result or _result[-1] != _value:
            _result.append(_value)
    return _result

def compact_runs(values):
    return _compact(values)
'''
    task = get_task('sequence-runs')
    for hidden in (False, True):
        result = sandbox.evaluate(task, source, hidden=hidden)
        assert result['passed'] == result['total'], result
