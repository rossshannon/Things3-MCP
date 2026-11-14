"""Malformed and hostile requests to the Things bridge get an HTTP error, never a dropped connection.

Each case reproduces a request that used to end its handler thread with an
uncaught exception. Nothing here starts a worker, so Things is never involved.
"""

import json
import socket
import threading

import pytest

from clawbridge.protocol import ok_envelope
from things3_mcp_bridge import server


@pytest.fixture
def bridge(tmp_path_factory, monkeypatch):
    directory = tmp_path_factory.mktemp("b")
    calls = []

    def worker(action, params=None, **_kwargs):
        calls.append((action, params))
        return ok_envelope([], outcome="succeeded")

    monkeypatch.setattr(server, "run_worker", worker)
    monkeypatch.setattr("clawbridge.server.REQUEST_TIMEOUT", 0.3)
    with server.UnixHTTPServer(directory / "b.sock", token_file=directory / "b.token") as running:
        running.calls = calls
        thread = threading.Thread(target=running.serve_forever, daemon=True)
        thread.start()
        try:
            yield running
        finally:
            running.shutdown()
            thread.join(timeout=2)


def raw_exchange(bridge, method, path, *, headers=(), body=b"", authorised=True):
    """Send hand-built HTTP so framing errors reach the server unmodified."""
    lines = [f"{method} {path} HTTP/1.0".encode()]
    if authorised:
        lines.append(b"Authorization: Bearer " + bridge.token.encode())
    lines.extend(headers)
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3)
        client.connect(bridge.server_address)
        client.sendall(b"\r\n".join(lines) + b"\r\n\r\n" + body)
        received = b""
        while chunk := client.recv(65536):
            received += chunk
    head, _, payload = received.partition(b"\r\n\r\n")
    assert head, "the bridge closed the connection without replying"
    return int(head.split()[1]), json.loads(payload)


def framed(body: bytes) -> tuple[bytes, ...]:
    return (b"Content-Length: " + str(len(body)).encode(),)


MALFORMED = {
    "body is not JSON": ("POST", "/things/search", framed(b"{not json"), b"{not json"),
    "body is not UTF-8": ("POST", "/things/search", framed(b"\xff\xfe"), b"\xff\xfe"),
    "non-numeric Content-Length": ("POST", "/things/search", (b"Content-Length: abc",), b""),
    "negative Content-Length": ("POST", "/things/search", (b"Content-Length: -1",), b""),
    "oversized Content-Length": ("POST", "/things/search", (b"Content-Length: 999999999",), b""),
    "JSON list sent to search": ("POST", "/things/search", framed(b'["backblaze"]'), b'["backblaze"]'),
    "JSON string sent to search": ("POST", "/things/search", framed(b'"backblaze"'), b'"backblaze"'),
    "JSON null sent to tasks": ("POST", "/things/tasks", framed(b"null"), b"null"),
    "search query of the wrong type": ("POST", "/things/search", framed(b'{"query": ["a"]}'), b'{"query": ["a"]}'),
    "JSON list sent to PATCH todo": ("PATCH", "/things/todo/some-id", framed(b'[{"title": "x"}]'), b'[{"title": "x"}]'),
    "JSON list sent to PATCH project": ("PATCH", "/things/project/some-id", framed(b"[1, 2]"), b"[1, 2]"),
    "JSON list sent to create todo": ("POST", "/things/todo", framed(b"[]"), b"[]"),
    "period that is not a duration": ("GET", "/things/last/banana", (), b""),
    "period with an unsupported unit": ("GET", "/things/last/3h", (), b""),
    "empty period": ("GET", "/things/last/", (), b""),
    "include_items that is not a boolean": ("GET", "/things/inbox?include_items=maybe", (), b""),
    "unknown query parameter": ("GET", "/things/inbox?filepath=/etc/passwd", (), b""),
}


@pytest.mark.parametrize("case", MALFORMED)
def test_malformed_request_gets_a_400_envelope_and_starts_nothing(bridge, case):
    method, path, headers, body = MALFORMED[case]
    status, envelope = raw_exchange(bridge, method, path, headers=headers, body=body)
    assert status == 400
    assert envelope["ok"] is False
    assert envelope["error_code"] == "invalid_request"
    assert envelope["outcome"] == "not_started"
    assert bridge.calls == []
    assert bridge.journal.recent() == []


def test_content_length_larger_than_the_body_times_out_with_a_reply(bridge):
    """A client that promises more bytes than it sends must not hold a thread forever."""
    status, envelope = raw_exchange(bridge, "POST", "/things/search", headers=(b"Content-Length: 500",), body=b'{"query": "x"}')
    assert status == 400
    assert envelope["error_code"] == "invalid_request"
    assert bridge.calls == []


def test_bridge_keeps_serving_after_every_malformed_request(bridge):
    for method, path, headers, body in MALFORMED.values():
        raw_exchange(bridge, method, path, headers=headers, body=body)
    raw_exchange(bridge, "POST", "/things/search", headers=(b"Content-Length: 500",), body=b"{")
    assert raw_exchange(bridge, "GET", "/health", authorised=False)[0] == 200
    status, envelope = raw_exchange(bridge, "GET", "/things/inbox")
    assert status == 200 and envelope["ok"] is True
    assert bridge.calls == [("inbox", {"include_items": True})]


def test_missing_and_wrong_tokens_are_refused_before_the_body_is_parsed(bridge):
    assert raw_exchange(bridge, "POST", "/things/search", headers=framed(b"{not json"), body=b"{not json", authorised=False)[0] == 401
    status, envelope = raw_exchange(bridge, "GET", "/things/inbox", headers=(b"Authorization: Bearer wrong",), authorised=False)
    assert status == 401 and envelope["error_code"] == "bridge_unauthorized"
    assert bridge.calls == []


def test_unknown_paths_and_traversal_ids_do_not_reach_anything_else(bridge):
    assert raw_exchange(bridge, "GET", "/things/nonsense")[0] == 404
    assert raw_exchange(bridge, "DELETE", "/things/todo/some-id")[0] in {400, 404, 405, 501}
    status, envelope = raw_exchange(bridge, "GET", "/things/get/..%2F..%2Fetc%2Fpasswd")
    assert status == 200 and envelope["ok"] is True
    assert bridge.calls == [("get", {"uuid": "../../etc/passwd"})]
