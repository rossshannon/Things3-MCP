"""Prove the installed MCP command uses real stdio and authenticated transport."""

import asyncio
import http.client
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from clawbridge.demo import create_server

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bridge(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "src"))
    runtime = tmp_path_factory.mktemp("stdio")
    server = create_server(runtime / "bridge.sock", runtime / "bridge.token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, runtime
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def envelope(result, *, error=False):
    assert result.isError is error
    assert len(result.content) == 1 and result.content[0].type == "text"
    assert json.loads(result.content[0].text) == result.structuredContent
    return result.structuredContent


def test_installed_stdio_command_calls_same_authenticated_counter(bridge, tmp_path):
    server, runtime = bridge
    command = Path(sys.executable).with_name("clawbridge-mcp")
    assert command.is_file(), "Install the project to expose its MCP command"
    canary = 'mcp-test-private-☘-"-payload'
    token = (runtime / "bridge.token").read_text().strip()
    diagnostics = tmp_path / "stdio.stderr"
    protocol_errors = []

    async def incoming(message):
        if isinstance(message, Exception):
            protocol_errors.append(message)

    async def protocol():
        parameters = StdioServerParameters(
            command=str(command),
            args=["--profile", "counter", "--socket", str(runtime / "bridge.sock"), "--token-file", str(runtime / "bridge.token")],
            env={"PYTHONPATH": str(ROOT / "src"), "HOME": str(tmp_path)},
        )
        with diagnostics.open("w+") as stderr, anyio.fail_after(20):
            # Observe parser failures explicitly: the default SDK callback
            # silently ignores malformed stdout lines.
            async with stdio_client(parameters, errlog=stderr) as (read, write), ClientSession(read, write, message_handler=incoming) as client:
                initialised = await client.initialize()
                assert initialised.serverInfo.name == "ClawBridge counter"
                tools = {tool.name for tool in (await client.list_tools()).tools}
                assert tools == {"counter_read", "counter_echo", "counter_increment", "bridge_status", "get_operation", "list_operations"}
                assert envelope(await client.call_tool("bridge_status", {}))["data"]["pid"] == os.getpid()
                assert envelope(await client.call_tool("counter_read", {}))["data"] == {"value": 0}
                assert envelope(await client.call_tool("counter_echo", {"text": canary}))["data"] == {"text": canary}
                changed = envelope(await client.call_tool("counter_increment", {"amount": 3, "correlation_id": "mcp-test-stdio"}))
                assert changed["data"]["value"] == 3 and changed["outcome"] == "succeeded"
                record = envelope(await client.call_tool("get_operation", {"operation_id": changed["operation_id"]}))["data"]
                assert record["operation_id"] == changed["operation_id"] and record["correlation_id"] == "mcp-test-stdio"
                assert record["outcome"] == "succeeded" and "payload" not in record
                assert envelope(await client.call_tool("list_operations", {"correlation_id": "mcp-test-stdio", "limit": 1}))["data"] == [record]
                rejected = envelope(await client.call_tool("counter_increment", {"amount": canary, "token": token}), error=True)
                assert rejected["error_code"] == "invalid_request" and rejected["outcome"] == "not_started"
                assert canary not in json.dumps(rejected) and token not in json.dumps(rejected)
                assert envelope(await client.call_tool("counter_read", {}))["data"]["value"] == 3

    asyncio.run(protocol())
    assert protocol_errors == []
    assert len(server.journal.recent()) == 1
    stderr = diagnostics.read_text()
    assert canary not in stderr and token not in stderr and "Traceback" not in stderr


def test_module_without_optional_sdk_has_actionable_stderr_and_no_stdout(tmp_path):
    result = subprocess.run(
        [sys.executable, "-S", "-m", "clawbridge_mcp.server", "--profile", "counter", "--socket", str(tmp_path / "missing.sock"), "--token-file", str(tmp_path / "missing.token")],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 2 and result.stdout == ""
    assert "uv sync --extra mcp" in result.stderr and "Traceback" not in result.stderr
    assert not (tmp_path / "missing.sock").exists() and not (tmp_path / "missing.token").exists()


def test_optional_smoke_client_uses_same_service_and_observed_baseline(bridge):
    server, runtime = bridge
    spec = importlib.util.spec_from_file_location("smoke_example_bridge", ROOT / "scripts/smoke_example_bridge.py")
    assert spec is not None and spec.loader is not None
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)

    def direct(method, path, payload=None):
        connection = http.client.HTTPConnection("localhost", timeout=10)
        connection.sock = socket.socket(socket.AF_UNIX)
        connection.sock.connect(str(runtime / "bridge.sock"))
        try:
            connection.request(method, path, json.dumps(payload) if payload else None, {"Authorization": "Bearer " + (runtime / "bridge.token").read_text().strip()})
            response = connection.getresponse()
            assert response.status == 200
            return json.loads(response.read())["data"]
        finally:
            connection.close()

    identity = direct("GET", "/status")
    assert direct("POST", "/demo/increment", {"amount": 7})["value"] == 7
    proof = asyncio.run(smoke.mcp_checks(runtime / "bridge.sock", runtime / "bridge.token", identity, 'synthetic-private-payload-☘-quoted-"'))
    assert proof["passed"] is True and proof["baseline"] == 7 and proof["value"] == 8
    assert proof["correlation_id"] == "synthetic-frozen-mcp-smoke"
    assert proof["operation_id"] in {record["operation_id"] for record in server.journal.recent()}
    assert len(server.journal.recent()) == 2 and direct("GET", "/demo/read")["value"] == 8
