"""Exercise the optional MCP interface through genuine client sessions."""

import asyncio
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from clawbridge.actions import LABEL
from clawbridge.protocol import error_envelope, ok_envelope
from clawbridge_mcp import server as interface


@contextmanager
def serving(bridge):
    thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    thread.start()
    try:
        yield bridge
    finally:
        bridge.shutdown()
        thread.join(timeout=2)
        bridge.server_close()


@pytest.fixture
def demo(tmp_path_factory, monkeypatch):
    from clawbridge.demo import create_server

    runtime = tmp_path_factory.mktemp("mcp")
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[1] / "src"))
    with serving(create_server(runtime / "bridge.sock", runtime / "bridge.token")) as bridge:
        yield bridge


def mcp_server(bridge, profile="counter", *, token_file=None):
    runtime = Path(bridge.server_address).parent
    return interface.create_server(profile=profile, socket_path=Path(bridge.server_address), token_file=token_file or runtime / "bridge.token")


def envelope(result, *, error=False):
    assert result.isError is error
    assert len(result.content) == 1 and result.content[0].type == "text"
    assert json.loads(result.content[0].text) == result.structuredContent
    return result.structuredContent


def test_counter_protocol_initialise_discover_and_call(demo):
    async def protocol():
        async with create_connected_server_and_client_session(mcp_server(demo)) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert set(tools) == {"counter_read", "counter_echo", "counter_increment", "bridge_status", "get_operation", "list_operations"}
            annotations = tools["counter_increment"].annotations
            assert annotations is not None
            assert annotations.readOnlyHint is False
            assert annotations.idempotentHint is False
            assert all(tool.annotations is not None and tool.annotations.readOnlyHint for name, tool in tools.items() if name != "counter_increment")
            assert all(tool.inputSchema["additionalProperties"] is False for tool in tools.values())
            assert tools["counter_increment"].inputSchema["properties"]["amount"] == {"type": "integer"}
            assert tools["list_operations"].inputSchema["properties"]["limit"] == {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}
            assert envelope(await client.call_tool("counter_read", {}))["data"] == {"value": 0}
            echo = envelope(await client.call_tool("counter_echo", {"text": "synthetic text"}))
            assert echo["data"] == {"text": "synthetic text"}
            assert echo["source"] == "live" and echo["generated_at"] and echo["protocol_version"] == 1
            result = envelope(await client.call_tool("counter_increment", {"amount": 2, "correlation_id": "protocol-proof"}))
            assert result["data"]["value"] == 2 and result["outcome"] == "succeeded"
            assert result["correlation_id"] == "protocol-proof"
            assert envelope(await client.call_tool("bridge_status", {}))["data"]["pid"] == os.getpid()
            record = envelope(await client.call_tool("get_operation", {"operation_id": result["operation_id"]}))["data"]
            assert record["operation_id"] == result["operation_id"] and record["outcome"] == "succeeded"
            recent = envelope(await client.call_tool("list_operations", {"correlation_id": "protocol-proof", "limit": 1}))["data"]
            assert recent == [record] and "payload" not in record
            missing = envelope(await client.call_tool("get_operation", {"operation_id": "missing"}), error=True)
            assert missing["error_code"] == "not_found" and missing["protocol_version"] == 1
            assert envelope(await client.call_tool("counter_read", {}))["data"]["value"] == 2

    asyncio.run(protocol())


@pytest.mark.parametrize("profile,domain_tools", [("counter", {"read", "echo", "increment"}), ("music", {"state", "play", "pause"}), ("catalogue", {"items", "search"})])
def test_discovery_is_passive_without_credentials_service_or_adapter_imports(tmp_path, monkeypatch, profile, domain_tools):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Passive discovery attempted credential, transport or adapter access")

    monkeypatch.setattr(interface, "importlib", SimpleNamespace(import_module=forbidden))
    monkeypatch.setattr(interface, "_token", forbidden)

    async def protocol():
        server = interface.create_server(profile=profile, socket_path=runtime / "missing.sock", token_file=runtime / "missing.token")
        async with create_connected_server_and_client_session(server) as client:
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == {f"{profile}_{name}" for name in domain_tools} | {"bridge_status", "get_operation", "list_operations"}
            assert all(tool.annotations is not None and tool.annotations.readOnlyHint is (tool.name not in interface.MUTATIONS) for tool in tools)

    asyncio.run(protocol())
    assert list(runtime.iterdir()) == []


@pytest.mark.parametrize("profile", ["counter", "music", "catalogue"])
def test_raw_invalid_calls_never_reach_the_socket(tmp_path, monkeypatch, profile):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)

    def forbidden(*_args):
        pytest.fail("Invalid tool arguments reached the socket client")

    monkeypatch.setattr(interface, "_request", forbidden)
    cases_by_profile: dict[str, list[tuple[str, dict[str, Any]]]] = {
        "counter": [
            ("counter_increment", {"amount": True}),
            ("counter_increment", {"amount": "2"}),
            ("counter_increment", {"amount": 1, "route": "/demo/read"}),
            ("counter_increment", {"amount": 1, "correlation_id": "bad/label"}),
            ("counter_increment", {"amount": 1, "correlation_id": None}),
            ("counter_echo", {"text": "\x00"}),
            ("counter_echo", {"text": "x" * 32769}),
            ("counter_read", {"correlation_id": "read-label"}),
            ("music_play", {}),
        ],
        "music": [("music_play", {"script": "private input"}), ("music_state", {"target": "another app"}), ("counter_read", {})],
        "catalogue": [("catalogue_search", {"query": ""}), ("catalogue_items", {"path": "/private/data"}), ("catalogue_search", {"query": "ok", "sql": "DELETE FROM items"}), ("music_play", {})],
    }
    cases = cases_by_profile[profile]
    cases += [("list_operations", {"limit": limit}) for limit in (0, 101, True, "1")]
    cases += [("list_operations", {"correlation_id": "x" * 129}), ("get_operation", {"operation_id": "../private"}), ("get_operation", {})]

    async def protocol():
        server = interface.create_server(profile=profile, socket_path=runtime / "missing.sock", token_file=runtime / "missing.token")
        async with create_connected_server_and_client_session(server) as client:
            for name, arguments in cases:
                result = envelope(await client.call_tool(name, arguments), error=True)
                assert result["error_code"] == "invalid_request" and result["outcome"] == "not_started"
                assert "private input" not in json.dumps(result)

    asyncio.run(protocol())
    assert list(runtime.iterdir()) == []


def test_unavailable_calls_create_no_state_and_keep_recovery_labels(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)

    async def protocol():
        server = interface.create_server(profile="counter", socket_path=runtime / "missing.sock", token_file=runtime / "missing.token")
        async with create_connected_server_and_client_session(server) as client:
            result = envelope(await client.call_tool("counter_increment", {"amount": 1}), error=True)
            assert result["error_code"] == "bridge_unavailable" and result["outcome"] == "not_started"
            assert LABEL.fullmatch(result["correlation_id"]) and str(tmp_path) not in json.dumps(result)
            token = runtime / "missing.token"
            token.write_text("synthetic-credential")
            token.chmod(0o600)
            result = envelope(await client.call_tool("counter_increment", {"amount": 1, "correlation_id": "not-sent"}), error=True)
            assert result["outcome"] == "not_started" and result["correlation_id"] == "not-sent"

    asyncio.run(protocol())
    assert [path.name for path in runtime.iterdir()] == ["missing.token"]


@pytest.mark.parametrize("unsafe", ["wrong-token", "permissions", "symlink", "parent-symlink"])
def test_credentials_are_private_and_errors_are_sanitised(demo, tmp_path, unsafe, capsys):
    token = tmp_path / "credential"
    token.write_text("private-invalid-credential")
    token.chmod(0o600 if unsafe == "wrong-token" else 0o644)
    if unsafe == "symlink":
        token.unlink()
        token.symlink_to(Path(demo.server_address).parent / "bridge.token")
    elif unsafe == "parent-symlink":
        parent = tmp_path / "link"
        parent.symlink_to(Path(demo.server_address).parent, target_is_directory=True)
        token = parent / "bridge.token"

    async def protocol():
        async with create_connected_server_and_client_session(mcp_server(demo, token_file=token)) as client:
            result = envelope(await client.call_tool("counter_increment", {"amount": 1, "correlation_id": "credential-proof"}), error=True)
            assert result["outcome"] == "not_started" and result["correlation_id"] == "credential-proof"
            assert result["error_code"] == ("bridge_unauthorized" if unsafe == "wrong-token" else "bridge_unavailable")
            assert str(token) not in json.dumps(result) and "private-invalid-credential" not in json.dumps(result)

    asyncio.run(protocol())
    assert demo.journal.recent() == []
    captured = capsys.readouterr()
    assert "private-invalid-credential" not in captured.out + captured.err


def test_completion_warning_and_structured_rejection_keep_bridge_metadata(demo, monkeypatch):
    original = demo.journal._persist

    def fail_completion(record):
        if record["outcome"] != "dispatched":
            raise OSError("private storage detail")
        original(record)

    monkeypatch.setattr(demo.journal, "_persist", fail_completion)

    async def protocol():
        async with create_connected_server_and_client_session(mcp_server(demo)) as client:
            success = envelope(await client.call_tool("counter_increment", {"amount": 1}))
            assert success["outcome"] == "succeeded" and success["journal_warning"]
            assert success["operation_id"] and success["correlation_id"]
            assert envelope(await client.call_tool("get_operation", {"operation_id": success["operation_id"]}))["data"]["outcome"] == "succeeded"
            demo.worker = lambda *_args: error_envelope(
                "automation_denied", "App action did not complete", outcome="failed", authorization_hint="Open Automation settings", capabilities={"automation": {"state": "denied"}}
            )
            rejected = envelope(await client.call_tool("counter_increment", {"amount": 1, "correlation_id": "rejected"}), error=True)
            assert rejected["error_code"] == "automation_denied" and rejected["outcome"] == "failed"
            assert rejected["authorization_hint"] == "Open Automation settings"
            assert rejected["capabilities"] == {"automation": {"state": "denied"}}
            assert rejected["operation_id"] and rejected["correlation_id"] == "rejected"

    asyncio.run(protocol())


@pytest.mark.parametrize("supplied", [None, "lost-reply"])
def test_lost_mutation_response_dispatches_once_and_is_recoverable(demo, monkeypatch, supplied):
    original = demo.RequestHandlerClass._send
    dispatches = []
    worker = demo.worker

    def dispatch(name, params):
        dispatches.append(name)
        return worker(name, params)

    def lose_response(handler, payload, status=200):
        if "operation_id" in payload:
            handler.connection.shutdown(socket.SHUT_RDWR)
            return
        original(handler, payload, status)

    demo.worker = dispatch
    monkeypatch.setattr(demo.RequestHandlerClass, "_send", lose_response)

    async def protocol():
        async with create_connected_server_and_client_session(mcp_server(demo)) as client:
            args = {"amount": 3, **({"correlation_id": supplied} if supplied else {})}
            result = envelope(await client.call_tool("counter_increment", args), error=True)
            assert result["error_code"] == result["outcome"] == "outcome_unknown"
            assert LABEL.fullmatch(result["correlation_id"])
            if supplied:
                assert result["correlation_id"] == supplied
            records = envelope(await client.call_tool("list_operations", {"correlation_id": result["correlation_id"]}))["data"]
            assert len(records) == 1 and records[0]["outcome"] == "succeeded"
            assert envelope(await client.call_tool("counter_read", {}))["data"]["value"] == 3

    asyncio.run(protocol())
    assert dispatches == ["increment", "read"]


def test_one_deadline_covers_connection_and_response_without_replay(demo, monkeypatch):
    class DelayedConnection(socket.socket):
        def connect(self, address):
            time.sleep(0.3)
            return super().connect(address)

    calls = []

    def delayed_worker(name, _params):
        calls.append(name)
        time.sleep(0.3)
        return ok_envelope({"accepted": True}, outcome="succeeded")

    demo.worker = delayed_worker
    monkeypatch.setattr(interface, "TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(interface, "socket", SimpleNamespace(socket=DelayedConnection, AF_UNIX=socket.AF_UNIX, SOCK_STREAM=socket.SOCK_STREAM, SHUT_RDWR=socket.SHUT_RDWR))

    async def protocol():
        async with create_connected_server_and_client_session(mcp_server(demo)) as client:
            result = envelope(await client.call_tool("counter_increment", {"amount": 1, "correlation_id": "whole-deadline"}), error=True)
            assert result["outcome"] == "outcome_unknown" and result["correlation_id"] == "whole-deadline"
            records = envelope(await client.call_tool("list_operations", {"correlation_id": "whole-deadline"}))["data"]
            assert len(records) == 1 and records[0]["outcome"] == "succeeded"

    asyncio.run(protocol())
    assert calls == ["increment"]


@pytest.mark.parametrize("reply", [b"{", b'{"ok":true,"protocol_version":1,"data":{},"outcome":"succeeded"}', b'{"ok":true,"ok":false}', b"oversized"])
def test_malformed_or_oversized_response_never_claims_mutation_success(demo, monkeypatch, reply):
    original = demo.RequestHandlerClass._send

    def malformed(handler, payload, status=200):
        if "operation_id" not in payload:
            original(handler, payload, status)
            return
        handler.send_response(200)
        handler.send_header("Content-Length", str(interface.MAX_RESPONSE_BYTES + 1 if reply == b"oversized" else len(reply)))
        handler.end_headers()
        if reply != b"oversized":
            handler.wfile.write(reply)

    monkeypatch.setattr(demo.RequestHandlerClass, "_send", malformed)

    async def protocol():
        async with create_connected_server_and_client_session(mcp_server(demo)) as client:
            result = envelope(await client.call_tool("counter_increment", {"amount": 1, "correlation_id": "invalid-reply"}), error=True)
            assert result["outcome"] == "outcome_unknown" and result["correlation_id"] == "invalid-reply"
            assert envelope(await client.call_tool("counter_read", {}))["data"]["value"] == 1

    asyncio.run(protocol())
    assert len(demo.journal.recent()) == 1


def test_music_protocol_uses_fixed_scripts_with_only_os_call_mocked(tmp_path_factory, monkeypatch):
    from clawbridge.examples import music

    runtime = tmp_path_factory.mktemp("music")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="paused\n" if kwargs["input"] == music.SCRIPTS["state"] else "ok\n", stderr="")

    monkeypatch.setattr(music.subprocess, "run", run)
    bridge = music.create_server(runtime / "bridge.sock", runtime / "bridge.token")

    def worker(name, params):
        result = ok_envelope(music.execute(name, params))
        if music.ACTIONS[name].mutation:
            result["outcome"] = "succeeded"
        return result

    bridge.worker = worker

    async def protocol():
        async with create_connected_server_and_client_session(mcp_server(bridge, "music")) as client:
            assert envelope(await client.call_tool("music_state", {}))["data"] == {"state": "paused"}
            for action in ("play", "pause"):
                result = envelope(await client.call_tool(f"music_{action}", {}))
                assert result["data"] == {"action": action, "accepted": True}
                assert result["outcome"] == "succeeded" and result["operation_id"] and result["correlation_id"]

    with serving(bridge):
        asyncio.run(protocol())
    assert [options["input"] for _, options in calls] == [music.SCRIPTS[name] for name in ("state", "play", "pause")]
    assert all(argv == ["/usr/bin/osascript"] for argv, _ in calls)


def test_catalogue_protocol_is_read_only_bounded_and_uses_fixture_account_home(tmp_path_factory, monkeypatch):
    from clawbridge.examples import catalogue

    runtime = tmp_path_factory.mktemp("cat")
    account_home = runtime / "account-home"
    path = account_home / catalogue.DATABASE_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(catalogue.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=str(account_home)))
    with sqlite3.connect(path) as database:
        database.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
        database.executemany("INSERT INTO items VALUES (?, ?)", [(index, f"Synthetic title {index}") for index in range(105)])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    bridge = catalogue.create_server(runtime / "bridge.sock", runtime / "bridge.token")
    bridge.worker = lambda name, params: ok_envelope(catalogue.execute(name, params), source="sqlite")

    async def protocol():
        async with create_connected_server_and_client_session(mcp_server(bridge, "catalogue")) as client:
            items = envelope(await client.call_tool("catalogue_items", {}))
            assert len(items["data"]["items"]) == 100 and items["data"]["truncated"] is True
            assert items["source"] == "sqlite" and items["generated_at"]
            found = envelope(await client.call_tool("catalogue_search", {"query": "title 104"}))
            assert found["data"] == {"items": [{"id": 104, "title": "Synthetic title 104"}], "truncated": False}
            assert envelope(await client.call_tool("catalogue_search", {"query": "' OR 1=1 --"}))["data"]["items"] == []
            assert envelope(await client.call_tool("list_operations", {}))["data"] == []

    with serving(bridge):
        asyncio.run(protocol())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
