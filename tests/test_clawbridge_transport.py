"""Observable synthetic socket, worker and recovery contracts."""

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawbridge.demo import create_server
from clawbridge.protocol import error_envelope, ok_envelope


def request(server, method, path, body=None, *, token=None, headers=None):
    connection = http.client.HTTPConnection("localhost", timeout=3)
    connection.sock = socket.socket(socket.AF_UNIX)
    connection.sock.settimeout(3)
    connection.sock.connect(server.server_address)
    request_headers = {"Authorization": f"Bearer {server.token if token is None else token}", **(headers or {})}
    connection.request(method, path, json.dumps(body) if body is not None else None, request_headers)
    response = connection.getresponse()
    result = response.status, json.loads(response.read())
    connection.close()
    return result


@pytest.fixture
def demo(tmp_path_factory, monkeypatch):
    tmp_path = tmp_path_factory.mktemp("s")
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[1] / "src"))
    server = create_server(tmp_path / "bridge.sock", tmp_path / "bridge.token")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def test_authenticated_socket_worker_and_distinct_correlated_attempts(demo):
    wrong_token = "deliberately-invalid"  # noqa: S105 - deliberately invalid synthetic credential
    assert request(demo, "GET", "/demo/read", token=wrong_token)[0] == 401
    assert request(demo, "GET", "/status", token=wrong_token)[0] == 401
    assert request(demo, "GET", "/operations", token=wrong_token)[0] == 401
    status, health = request(demo, "GET", "/health", token="")
    assert status == 200
    assert set(health["data"]) == {"running", "version"}
    identity = request(demo, "GET", "/status")[1]["data"]
    assert identity["pid"] == os.getpid()
    assert identity["identity"]["build_id"] == "development"
    attempts = [request(demo, "POST", "/demo/increment", {"amount": 2}, headers={"X-Correlation-ID": "lost-reply"})[1] for _ in range(2)]
    assert attempts[0]["operation_id"] != attempts[1]["operation_id"]
    assert all(a["outcome"] == "succeeded" and a["protocol_version"] == 1 for a in attempts)
    assert request(demo, "GET", "/demo/read")[1]["data"]["value"] == 4
    recent = request(demo, "GET", "/operations?correlation_id=lost-reply")[1]["data"]
    assert len(recent) == 2
    record = request(demo, "GET", f"/operations/{attempts[0]['operation_id']}")[1]["data"]
    assert record["outcome"] == "succeeded"
    assert "payload" not in record
    assert request(demo, "GET", "/operations?limit=101")[0] == 400
    assert request(demo, "GET", "/operations/missing")[0] == 404


@pytest.mark.parametrize("body", [[], "text", {"amount": True}, {"amount": 1, "path": "/private/elsewhere"}, {}])
def test_invalid_action_never_creates_a_record_or_changes_state(demo, body):
    status, response = request(demo, "POST", "/demo/increment", body)
    assert status == 400 and response["outcome"] == "not_started"
    assert request(demo, "GET", "/operations")[1]["data"] == []
    assert request(demo, "GET", "/demo/read")[1]["data"] == {"value": 0}


@pytest.mark.parametrize("framing", [b"Content-Length: 65537\r\n", b"Content-Length: -1\r\n", b"Content-Length: 2\r\nContent-Length: 2\r\n", b"Transfer-Encoding: chunked\r\n"])
def test_invalid_framing_is_rejected_without_reading_body(demo, framing):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        client.connect(demo.server_address)
        client.sendall(b"POST /demo/increment HTTP/1.0\r\nAuthorization: Bearer " + demo.token.encode() + b"\r\n" + framing + b"\r\n")
        assert b"400" in client.recv(4096).split(b"\r\n")[0]
    assert demo.journal.recent() == []


@pytest.mark.parametrize("raw", [b"{", b'{"amount":1,"amount":2}', b'{"amount":NaN}', b"\xff"])
def test_malformed_json_is_rejected(demo, raw):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        client.connect(demo.server_address)
        client.sendall(b"POST /demo/increment HTTP/1.0\r\nAuthorization: Bearer " + demo.token.encode() + b"\r\nContent-Length: " + str(len(raw)).encode() + b"\r\n\r\n" + raw)
        assert b"400" in client.recv(4096).split(b"\r\n")[0]
    assert demo.journal.recent() == []


def test_capacity_rejection_precedes_journal_and_health_stays_available(demo):
    entered, release = threading.Event(), threading.Event()

    def waiting(_action, _params):
        entered.set()
        assert release.wait(2)
        return ok_envelope({"id": "done"}, outcome="succeeded")

    demo.worker = waiting
    result = []
    caller = threading.Thread(target=lambda: result.append(request(demo, "POST", "/demo/increment", {"amount": 1})), daemon=True)
    caller.start()
    assert entered.wait(1)
    try:
        status, rejected = request(demo, "POST", "/demo/increment", {"amount": 1})
        assert status == 503 and rejected["outcome"] == "not_started"
        assert request(demo, "GET", "/health")[0] == 200
        assert len(demo.journal.recent()) == 1
    finally:
        release.set()
        caller.join(timeout=2)
    assert result[0][1]["outcome"] == "succeeded"


def test_journal_admission_failure_blocks_dispatch(demo, monkeypatch):
    def fail(_record):
        raise OSError("private filesystem detail")

    monkeypatch.setattr(demo.journal, "_persist", fail)
    status, result = request(demo, "POST", "/demo/increment", {"amount": 1})
    assert status == 503 and result["outcome"] == "not_started"
    assert result["error_code"] == "journal_unavailable"
    assert not (Path(demo.server_address).parent / "demo-state.json").exists()


def test_completion_failure_preserves_known_success(demo, monkeypatch):
    original = demo.journal._persist

    def fail_completion(record):
        if record["outcome"] != "dispatched":
            raise OSError("disk full")
        original(record)

    monkeypatch.setattr(demo.journal, "_persist", fail_completion)
    status, result = request(demo, "POST", "/demo/increment", {"amount": 1})
    assert status == 200 and result["outcome"] == "succeeded"
    assert result["journal_warning"]
    record = request(demo, "GET", f"/operations/{result['operation_id']}")[1]["data"]
    assert record["outcome"] == "succeeded"
    assert request(demo, "GET", "/demo/read")[1]["data"]["value"] == 1


def test_unknown_outcome_is_recorded_without_replay(demo):
    called = []

    def uncertain(_name, _params):
        called.append(True)
        return error_envelope("worker_timeout", "Timed out", outcome="outcome_unknown")

    demo.worker = uncertain
    response = request(demo, "POST", "/demo/increment", {"amount": 1})[1]
    assert response["outcome"] == "outcome_unknown"
    assert request(demo, "GET", f"/operations/{response['operation_id']}")[1]["data"]["outcome"] == "outcome_unknown"
    assert len(called) == 1


def test_ordinary_logs_and_default_journal_exclude_payload_and_token(demo, capfd):
    canary = "private-task-canary"
    response = request(demo, "POST", "/demo/echo", {"text": canary})[1]
    assert response["data"]["text"] == canary
    private_token = "private-token-canary"  # noqa: S105 - synthetic log-leak canary
    request(demo, "POST", f"/unknown/{canary}", {"amount": 1}, token=private_token)
    request(demo, "POST", "/demo/increment", {"amount": 1})
    output = capfd.readouterr()
    assert canary not in output.out + output.err
    assert "private-token-canary" not in output.out + output.err
    assert demo.token not in output.out + output.err
    record = next(demo.journal.directory.glob("*.json")).read_text()
    assert "payload" not in record and demo.token not in record


def test_partial_request_expires_without_dispatch(demo, monkeypatch):
    monkeypatch.setattr("clawbridge.server.REQUEST_TIMEOUT", 0.1)
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(1)
        client.connect(demo.server_address)
        client.sendall(b"POST /demo/increment HTTP/1.0\r\nAuthorization: Bearer " + demo.token.encode() + b"\r\nContent-Length: 12\r\n\r\n{")
        assert b"400" in client.recv(4096).split(b"\r\n")[0]
    assert demo.journal.recent() == []


def test_rejected_correlations_never_dispatch(demo):
    result = request(demo, "POST", "/demo/increment", {"amount": 1}, headers={"X-Correlation-ID": "invalid label"})
    assert result[0] == 400
    assert demo.journal.recent() == []


def test_worker_slots_are_bounded(demo):
    for _ in range(4):
        assert demo.workers.acquire(blocking=False)
    try:
        status, result = request(demo, "POST", "/demo/increment", {"amount": 1})
        assert status == 503 and result["outcome"] == "not_started"
        assert demo.journal.recent() == []
    finally:
        for _ in range(4):
            demo.workers.release()


def test_close_retains_ownership_until_mutation_and_completion_are_persisted(tmp_path_factory, monkeypatch):
    directory = tmp_path_factory.mktemp("close")
    server = create_server(directory / "bridge.sock", directory / "bridge.token")
    serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    entered, release_worker = threading.Event(), threading.Event()
    persisting, release_completion, closed = threading.Event(), threading.Event(), threading.Event()
    result = []

    def worker(_action, _params):
        entered.set()
        assert release_worker.wait(5)
        return ok_envelope({"id": "finished"}, outcome="succeeded")

    persist = server.journal._persist

    def hold_completion(record):
        if record["outcome"] != "dispatched":
            persisting.set()
            assert release_completion.wait(5)
        persist(record)

    def close():
        server.server_close()
        closed.set()

    server.worker = worker
    monkeypatch.setattr(server.journal, "_persist", hold_completion)
    serving.start()
    caller = threading.Thread(target=lambda: result.append(request(server, "POST", "/demo/increment", {"amount": 1})))
    closer = threading.Thread(target=close)
    caller.start()
    try:
        assert entered.wait(2)
        server.shutdown()
        serving.join(timeout=2)
        assert not serving.is_alive()
        closer.start()
        assert not closed.wait(0.1)
        with pytest.raises(BlockingIOError):
            create_server(directory / "bridge.sock", directory / "bridge.token")
        release_worker.set()
        assert persisting.wait(2)
        assert not closed.wait(0.1)
        with pytest.raises(BlockingIOError):
            create_server(directory / "bridge.sock", directory / "bridge.token")
    finally:
        release_worker.set()
        release_completion.set()
        caller.join(timeout=3)
        if closer.ident is not None:
            closer.join(timeout=3)
        server.shutdown()
        serving.join(timeout=2)
        server.server_close()
    assert closed.is_set() and not closer.is_alive() and not caller.is_alive()
    response = result[0][1]
    assert response["outcome"] == "succeeded"
    with create_server(directory / "bridge.sock", directory / "bridge.token") as replacement:
        assert replacement.journal.lookup(response["operation_id"])["outcome"] == "succeeded"


def test_sigterm_drains_synthetic_worker_before_releasing_endpoint(tmp_path_factory, monkeypatch):
    directory = tmp_path_factory.mktemp("term")
    module = directory / "synthetic_shutdown.py"
    module.write_text("""
import os
import sys
import time
from pathlib import Path
from clawbridge import demo
from clawbridge.worker import run_worker, worker_main

directory = Path(os.environ["SYNTHETIC_RUNTIME"])
if "--worker-action" in sys.argv:
    def execute(name, params):
        (directory / "started").write_text("ready")
        while not (directory / "release").exists():
            time.sleep(0.01)
        return {"id": "completed-synthetic-write"}
    raise SystemExit(worker_main(demo.ACTIONS, sys.argv[-1], execute))

original = demo.create_server
def create(*args, **kwargs):
    server = original(*args, **kwargs)
    server.worker = lambda name, params: run_worker("synthetic_shutdown", demo.ACTIONS[name], params, timeout=5)
    return server
demo.create_server = create
raise SystemExit(demo.main())
""")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(directory), str(Path(__file__).parents[1] / "src"))))
    monkeypatch.setenv("SYNTHETIC_RUNTIME", str(directory))
    endpoint, token = directory / "bridge.sock", directory / "bridge.token"
    process = subprocess.Popen([sys.executable, "-m", "synthetic_shutdown", "--socket", str(endpoint), "--token-file", str(token)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result, failures = [], []
    caller = None
    try:
        deadline = time.monotonic() + 5
        while not endpoint.exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        bridge = SimpleNamespace(server_address=str(endpoint), token=token.read_text())
        assert request(bridge, "GET", "/health")[0] == 200

        def mutate():
            try:
                result.append(request(bridge, "POST", "/demo/increment", {"amount": 1}))
            except Exception as error:
                failures.append(error)

        caller = threading.Thread(target=mutate)
        caller.start()
        while not (directory / "started").exists():
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        process.send_signal(signal.SIGTERM)
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.2)
        with pytest.raises(BlockingIOError):
            create_server(endpoint, token)
        (directory / "release").touch()
        caller.join(timeout=3)
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0 and stdout == stderr == b""
        assert not failures and not caller.is_alive()
        response = result[0][1]
        assert response["outcome"] == "succeeded"
        assert not endpoint.exists()
        with create_server(endpoint, token) as replacement:
            assert replacement.journal.lookup(response["operation_id"])["outcome"] == "succeeded"
    finally:
        (directory / "release").touch()
        if caller is not None:
            caller.join(timeout=3)
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


def raw_reply(server, payload, *, half_close=False):
    """Send bytes exactly as given and return everything the bridge answers."""
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3)
        client.connect(server.server_address)
        client.sendall(payload)
        if half_close:
            client.shutdown(socket.SHUT_WR)
        received = b""
        while chunk := client.recv(65536):
            received += chunk
    return received


def test_result_that_cannot_be_encoded_is_never_reported_as_not_started(demo):
    demo.worker = lambda _name, _params: ok_envelope({"id": "object-1", "value": float("nan")}, outcome="succeeded")
    status, result = request(demo, "POST", "/demo/increment", {"amount": 1}, headers={"X-Correlation-ID": "nan-result"})
    assert status == 500
    assert result["error_code"] == "bridge_invalid_response" and result["outcome"] == "outcome_unknown"
    assert result["correlation_id"] == "nan-result"
    record = request(demo, "GET", f"/operations/{result['operation_id']}")[1]["data"]
    assert record["outcome"] == "succeeded" and record["result_id"] == "object-1"


@pytest.mark.parametrize("reply", [{"ok": True, "data": {}}, {"ok": True, "data": {}, "outcome": "finished"}, None, "done"])
def test_mutation_reply_without_a_valid_outcome_is_unknown_and_its_record_is_closed(demo, reply):
    demo.worker = lambda _name, _params: reply
    status, result = request(demo, "POST", "/demo/increment", {"amount": 1})
    assert status == 200
    assert result["error_code"] == "worker_invalid_response" and result["outcome"] == "outcome_unknown"
    assert demo.journal.lookup(result["operation_id"])["outcome"] == "outcome_unknown"
    assert not demo.journal.active
    assert request(demo, "POST", "/demo/increment", {"amount": 1})[1]["operation_id"] != result["operation_id"]


def test_read_fault_gets_a_reply_and_leaves_the_bridge_serving(demo, monkeypatch, capfd):
    def broken(_name, _params):
        raise KeyError("private-read-detail")

    monkeypatch.setattr(demo, "worker", broken)
    status, result = request(demo, "GET", "/demo/read")
    assert status == 500
    assert result["error_code"] == "bridge_failed" and result["outcome"] == "failed"
    monkeypatch.undo()
    assert request(demo, "GET", "/demo/read")[0] == 200
    assert "private-read-detail" not in "".join(capfd.readouterr())


def test_fault_while_routing_gets_a_reply_and_dispatches_nothing(demo, monkeypatch):
    def broken(*_args):
        raise KeyError("adapter bug")

    monkeypatch.setattr(demo.RequestHandlerClass, "special", broken)
    status, result = request(demo, "POST", "/demo/increment", {"amount": 1})
    assert status == 500
    assert result["error_code"] == "bridge_failed" and result["outcome"] == "not_started"
    assert demo.journal.recent() == []


def test_storage_fault_is_unavailable_rather_than_a_bad_request(demo, monkeypatch):
    from clawbridge.journal import JournalError

    def broken(**_kwargs):
        raise JournalError("Recovery storage is full")

    monkeypatch.setattr(demo.journal, "recent", broken)
    status, result = request(demo, "GET", "/operations")
    assert status == 503 and result["error_code"] == "bridge_unavailable"


@pytest.mark.parametrize("half_close", [True, False])
def test_truncated_header_block_is_rejected_without_dispatch(demo, monkeypatch, half_close):
    """Whether the client stops sending or the input deadline cuts it off, lost headers must not be guessed."""
    monkeypatch.setattr("clawbridge.server.REQUEST_TIMEOUT", 0.2)
    called = []
    demo.worker = lambda name, _params: called.append(name) or ok_envelope({}, outcome="succeeded")
    truncated = b"GET /demo/read HTTP/1.0\r\nAuthorization: Bearer " + demo.token.encode() + b"\r\nX-Require-Li"
    reply = raw_reply(demo, truncated, half_close=half_close)
    assert reply.split(b"\r\n")[0].split()[1] == b"400"
    assert json.loads(reply.partition(b"\r\n\r\n")[2])["outcome"] == "not_started"
    assert called == []


def test_request_without_a_protocol_version_is_refused_at_once(demo):
    """Answered from the request line alone: there are no headers to wait for."""
    started = time.monotonic()
    reply = json.loads(raw_reply(demo, b"GET /health\r\n"))
    assert reply["ok"] is False and reply["error_code"] == "invalid_request"
    assert time.monotonic() - started < 2
    assert request(demo, "GET", "/health", token="")[0] == 200


def test_client_that_leaves_before_the_reply_is_not_logged_as_a_failure(demo, capfd):
    entered, release = threading.Event(), threading.Event()

    def slow(_name, _params):
        entered.set()
        release.wait(3)
        return ok_envelope({}, outcome="succeeded")

    demo.worker = slow
    with socket.socket(socket.AF_UNIX) as client:
        client.connect(demo.server_address)
        client.sendall(b"GET /demo/read HTTP/1.0\r\nAuthorization: Bearer " + demo.token.encode() + b"\r\n\r\n")
        assert entered.wait(3)
    release.set()
    deadline = time.monotonic() + 3
    while demo.connections._value != 16 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert demo.connections._value == 16
    assert "Bridge request failed" not in capfd.readouterr().err


def test_operation_lookups_accept_only_plain_limits_and_whole_identifiers(demo):
    done = request(demo, "POST", "/demo/increment", {"amount": 1})[1]
    assert request(demo, "GET", f"/operations/{done['operation_id']}")[0] == 200
    assert request(demo, "GET", f"/operations/elsewhere/{done['operation_id']}")[0] == 404
    assert request(demo, "GET", "/operations?limit=%D9%A3")[0] == 400
    assert request(demo, "GET", "/operations?limit=-1")[0] == 400
    assert request(demo, "GET", "/operations?limit=3")[0] == 200
