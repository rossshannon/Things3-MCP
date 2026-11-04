"""Observable synthetic socket, worker and recovery contracts."""

import http.client
import json
import os
import socket
import threading
from pathlib import Path

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
    thread = threading.Thread(target=server.serve_forever, daemon=True)
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
