"""Synthetic subprocess fixtures for deadlines and untrusted worker output."""

import time

import pytest

from clawbridge.actions import Action
from clawbridge.worker import run_worker


@pytest.fixture
def worker_fixture(tmp_path, monkeypatch):
    module = tmp_path / "synthetic_worker.py"
    module.write_text("""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

name = sys.argv[-1]
params = json.load(sys.stdin)
if name == "children":
    child = "import os,time; from pathlib import Path; Path(os.environ['STARTED']).write_text('ready'); time.sleep(0.8); Path(os.environ['MARKER']).write_text('changed')"
    subprocess.Popen([sys.executable, "-c", child])
    time.sleep(10)
elif name == "bad_json":
    print("private-worker-canary")
elif name == "legacy":
    print(json.dumps({"ok": True, "data": {"id": "one"}}))
elif name == "malformed":
    print(json.dumps({"ok": "yes", "protocol_version": 1, "data": {}}))
elif name == "overflow":
    print("x" * 100000)
else:
    if name == "stderr":
        print("private-worker-canary" * 100000, file=sys.stderr)
    print(json.dumps({"ok": True, "protocol_version": 1, "data": params, "outcome": "succeeded"}))
    if name == "bad_exit":
        sys.exit(1)
""")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("name", ["bad_json", "legacy", "malformed", "bad_exit"])
def test_invalid_mutation_response_is_unknown(worker_fixture, name, capfd):
    result = run_worker("synthetic_worker", Action(name, True), {})
    assert result["ok"] is False
    assert result["outcome"] == "outcome_unknown"
    assert result["error_code"] == "worker_invalid_response"
    output = capfd.readouterr()
    assert "private-worker-canary" not in output.out + output.err
    assert "private-worker-canary" not in str(result)


def test_stderr_is_drained_and_not_copied_into_logs(worker_fixture, capfd):
    result = run_worker("synthetic_worker", Action("stderr", True), {})
    assert result["outcome"] == "succeeded"
    output = capfd.readouterr()
    assert "private-worker-canary" not in output.out + output.err


def test_output_limit_stops_worker_and_preserves_uncertainty(worker_fixture, monkeypatch):
    monkeypatch.setattr("clawbridge.worker.MAX_RESPONSE_BYTES", 8192)
    result = run_worker("synthetic_worker", Action("overflow", True), {})
    assert result["outcome"] == "outcome_unknown"


def test_deadline_stops_worker_descendants_before_they_can_mutate(worker_fixture, monkeypatch):
    started, marker = worker_fixture / "started", worker_fixture / "mutation"
    monkeypatch.setenv("STARTED", str(started))
    monkeypatch.setenv("MARKER", str(marker))
    result = run_worker("synthetic_worker", Action("children", True), {}, timeout=0.3)
    assert started.read_text() == "ready"
    assert result["error_code"] == "worker_timeout"
    assert result["outcome"] == "outcome_unknown"
    time.sleep(0.9)
    assert not marker.exists()


def test_invalid_parameters_are_rejected_before_spawn(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("No worker should start for an invalid schema")

    monkeypatch.setattr("clawbridge.worker.subprocess.Popen", forbidden)
    result = run_worker("synthetic_worker", Action("write", True, {"title": str}, frozenset({"title"})), {"script": "unsafe"})
    assert result["outcome"] == "not_started"


def test_worker_start_failure_is_known_not_started(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise OSError("cannot spawn")

    monkeypatch.setattr("clawbridge.worker.subprocess.Popen", unavailable)
    result = run_worker("synthetic_worker", Action("write", True), {})
    assert result["outcome"] == "not_started"


@pytest.mark.parametrize(("name", "expected"), [("known", "failed"), ("partial", "outcome_unknown")])
def test_worker_entry_preserves_proven_rejection_and_uncertainty(tmp_path, monkeypatch, capfd, name, expected):
    from pathlib import Path

    (tmp_path / "outcome_worker.py").write_text("""
import sys
from clawbridge.actions import Action
from clawbridge.worker import worker_main

class KnownFailure(RuntimeError):
    error_code = "automation_denied"
    outcome = "failed"
    authorization_hint = "Allow the configured app in Automation settings"

def execute(name, params):
    print("private-title-from-worker")
    if name == "known":
        raise KnownFailure("private-title-from-exception")
    raise RuntimeError("private-title-from-exception")

actions = {name: Action(name, True) for name in ("known", "partial")}
def observations():
    return {"automation": {"state": "denied", "error_code": "automation_denied"}}
raise SystemExit(worker_main(actions, sys.argv[-1], execute, observations=observations))
""")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path) + ":" + str(Path(__file__).parents[1] / "src"))
    result = run_worker("outcome_worker", Action(name, True), {})
    assert result["outcome"] == expected
    assert result["capabilities"]["automation"]["state"] == "denied"
    output = capfd.readouterr()
    assert "private-title" not in output.out + output.err + str(result)


def test_io_failure_after_spawn_must_not_claim_not_started(worker_fixture, monkeypatch):
    import subprocess

    real_popen = subprocess.Popen

    class BrokenCleanup:
        def __init__(self, *args, **kwargs):
            self.process = real_popen(*args, **kwargs)

        def __enter__(self):
            return self.process.__enter__()

        def __exit__(self, *args):
            self.process.__exit__(*args)
            raise OSError("post-execution cleanup error")

    monkeypatch.setattr("clawbridge.worker.subprocess.Popen", BrokenCleanup)
    result = run_worker("synthetic_worker", Action("success", True), {})
    assert result["outcome"] == "outcome_unknown"
