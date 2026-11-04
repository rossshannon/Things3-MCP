"""Expose one fixed ClawBridge profile over MCP stdio."""

from __future__ import annotations

import argparse
import asyncio
import http.client
import importlib
import json
import math
import os
import socket
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode
from uuid import uuid4

from clawbridge.actions import Action, InvalidRequestError, correlation_id
from clawbridge.protocol import OUTCOMES, PROTOCOL_VERSION, error_envelope
from clawbridge.runtime import RuntimeSafetyError, private_open

if TYPE_CHECKING:
    from mcp.server import Server

TIMEOUT_SECONDS = 35.0
MAX_RESPONSE_BYTES = 16 * 1024 * 1024 + 4096
PROFILES = {
    "counter": ("clawbridge.demo", {"read": "GET", "echo": "POST", "increment": "POST"}),
    "music": ("clawbridge.examples.music", {"state": "GET", "play": "POST", "pause": "POST"}),
    "catalogue": ("clawbridge.examples.catalogue", {"items": "GET", "search": "POST"}),
}
MUTATIONS = frozenset({"counter_increment", "music_play", "music_pause"})
LABEL_SCHEMA = {"type": "string", "pattern": "^[A-Za-z0-9._:-]{1,128}$", "minLength": 1, "maxLength": 128}


def _token(path: Path) -> str:
    if any(component.is_symlink() for component in (path, *path.absolute().parents)):
        raise RuntimeSafetyError("Credential paths must not contain symlinks")
    fd = private_open(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as source:
        raw = source.read(4097)
    token = raw.decode("ascii").strip()
    if len(raw) > 4096 or not token or any(character.isspace() or ord(character) < 33 or ord(character) > 126 for character in token):
        raise RuntimeSafetyError("Invalid bridge token file")
    return token


def _validate_envelope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or type(value.get("ok")) is not bool or type(value.get("protocol_version")) is not int or value["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("Invalid bridge envelope")
    for key in ("source", "snapshot_source", "error_code", "message", "authorization_hint", "operation_id", "journal_warning"):
        if key in value and not isinstance(value[key], str):
            raise ValueError("Invalid bridge metadata")
    for key in ("correlation_id", "generated_at"):
        if key in value and value[key] is not None and not isinstance(value[key], str):
            raise ValueError("Invalid bridge metadata")
    if "journal_warning" in value and len(value["journal_warning"]) > 1024:
        raise ValueError("Invalid journal warning")
    if "outcome" in value and (not isinstance(value["outcome"], str) or value["outcome"] not in OUTCOMES):
        raise ValueError("Invalid outcome")
    for key in ("cache_status", "live_error"):
        if key in value and not isinstance(value[key], dict):
            raise ValueError("Invalid bridge metadata")
    if "cache_age_seconds" in value:
        age = value["cache_age_seconds"]
        if type(age) not in {int, float} or not math.isfinite(age) or age < 0:
            raise ValueError("Invalid cache age")
    if value["ok"]:
        if "data" not in value or (value["data"] is not None and not isinstance(value["data"], dict | list) and type(value["data"]) is not int):
            raise ValueError("Invalid bridge data")
    elif not isinstance(value.get("error_code"), str) or not isinstance(value.get("message"), str):
        raise ValueError("Invalid bridge error")
    return value


def _decode(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate response field")
            result[key] = value
        return result

    def constant(_value: str) -> None:
        raise ValueError("Invalid response number")

    return _validate_envelope(json.loads(raw, object_pairs_hook=pairs, parse_constant=constant))


def _request(socket_path: Path, token_file: Path, method: str, path: str, body: dict[str, Any], correlation: str | None) -> dict[str, Any]:
    mutation = correlation is not None
    sending = False
    envelope: dict[str, Any] | None = None
    connection = http.client.HTTPConnection("localhost", timeout=TIMEOUT_SECONDS)
    timer: threading.Timer | None = None
    try:
        token = _token(token_file)
        payload = json.dumps(body, allow_nan=False).encode() if method == "POST" else None
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(TIMEOUT_SECONDS)
        endpoint = connection.sock

        def expire() -> None:
            try:
                endpoint.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            finally:
                endpoint.close()

        timer = threading.Timer(TIMEOUT_SECONDS, expire)
        timer.daemon = True
        timer.start()
        connection.sock.connect(str(socket_path))
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        if correlation is not None:
            headers["X-Correlation-ID"] = correlation
        # A send failure can follow a partial write. Never retry this connection.
        sending = True
        connection.request(method, path, payload, headers)
        response = connection.getresponse()
        lengths = response.headers.get_all("Content-Length", [])
        if lengths and (len(lengths) != 1 or not lengths[0].isdigit() or int(lengths[0]) > MAX_RESPONSE_BYTES):
            raise ValueError("Invalid response size")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES or (lengths and len(raw) != int(lengths[0])):
            raise ValueError("Invalid response size")
        envelope = _decode(raw)
        if not 200 <= response.status < 300 and envelope["ok"]:
            raise ValueError("HTTP status did not confirm success")
        if mutation:
            if envelope.get("correlation_id") not in {None, correlation}:
                raise ValueError("Mismatched correlation")
            if "outcome" not in envelope or (envelope["ok"] and (envelope["outcome"] != "succeeded" or not isinstance(envelope.get("data"), dict) or not envelope.get("operation_id"))):
                raise ValueError("Unconfirmed mutation")
            envelope["correlation_id"] = correlation
        return envelope
    except (OSError, ValueError, http.client.HTTPException, RecursionError):
        unknown = mutation and sending
        result = error_envelope(
            "outcome_unknown" if unknown else "bridge_unavailable",
            (
                "The bridge response was unavailable or invalid; the action may have completed. Inspect operations before trying again."
                if unknown
                else "The local bridge or its private credential is unavailable or invalid."
            ),
            **({"outcome": "outcome_unknown" if unknown else "not_started", "correlation_id": correlation} if mutation else {}),
        )
        if unknown and envelope is not None and isinstance(envelope.get("operation_id"), str):
            result["operation_id"] = envelope["operation_id"]
        return result
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()


def _schema(name: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required = []
    for tool, field in (("counter_echo", "text"), ("catalogue_search", "query")):
        if name == tool:
            properties[field] = {"type": "string", "maxLength": 32768, **({"minLength": 1} if field == "query" else {})}
            required.append(field)
    if name == "counter_increment":
        properties["amount"] = {"type": "integer"}
        required.append("amount")
    if name in MUTATIONS or name == "list_operations":
        properties["correlation_id"] = dict(LABEL_SCHEMA)
    if name == "get_operation":
        properties["operation_id"] = dict(LABEL_SCHEMA)
        required.append("operation_id")
    if name == "list_operations":
        properties["limit"] = {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _prepare(profile: str, name: str, arguments: dict[str, Any]) -> tuple[str, str, dict[str, Any], str | None]:
    fields = _schema(name)["properties"]
    if set(arguments) - fields.keys():
        raise InvalidRequestError("Unsupported parameters")
    params = dict(arguments)
    correlation = params.pop("correlation_id", None)
    if "correlation_id" in arguments and type(correlation) is not str:
        raise InvalidRequestError("Invalid correlation ID")
    correlation_id(correlation)
    if name == "bridge_status":
        return "GET", "/status", {}, None
    if name == "get_operation":
        Action("operation", fields={"operation_id": str}, required=frozenset({"operation_id"})).validate(params)
        correlation_id(params["operation_id"])
        return "GET", f"/operations/{quote(params['operation_id'], safe='')}", {}, None
    if name == "list_operations":
        Action("operations", fields={"limit": int}).validate(params)
        limit = params.get("limit", 25)
        if not 1 <= limit <= 100:
            raise InvalidRequestError("Invalid operation limit")
        query = {"limit": limit, **({"correlation_id": correlation} if correlation is not None else {})}
        return "GET", f"/operations?{urlencode(query)}", {}, None
    module_name, actions = PROFILES[profile]
    action = name.removeprefix(profile + "_")
    # App execution modules are not loaded by initialise or tool discovery.
    params = importlib.import_module(module_name).ACTIONS[action].validate(params)
    route_profile = "demo" if profile == "counter" else profile
    return actions[action], f"/{route_profile}/{action}", params, (correlation or str(uuid4())) if name in MUTATIONS else None


def create_server(*, profile: str, socket_path: Path, token_file: Path) -> Server:
    """Create a passive MCP server for one operator-selected example profile."""
    from anyio import to_thread
    from mcp import types
    from mcp.server import Server

    if profile not in PROFILES:
        raise ValueError("Unknown ClawBridge profile")
    names = [f"{profile}_{action}" for action in PROFILES[profile][1]] + ["bridge_status", "get_operation", "list_operations"]
    server = Server(f"ClawBridge {profile}", version="0.1.0")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=name,
                description=("Inspect retained recovery records; never retries an operation." if name in {"get_operation", "list_operations"} else f"Call the fixed {name.replace('_', ' ')} bridge action."),
                inputSchema=_schema(name),
                annotations=types.ToolAnnotations(readOnlyHint=name not in MUTATIONS, idempotentHint=name not in MUTATIONS, openWorldHint=False),
            )
            for name in names
        ]

    async def call_tool(request: types.CallToolRequest) -> types.ServerResult:
        try:
            if request.params.name not in names:
                raise InvalidRequestError("Unknown tool")
            prepared = _prepare(profile, request.params.name, request.params.arguments or {})
        except InvalidRequestError:
            envelope = error_envelope("invalid_request", "Unknown tool or invalid tool parameters", outcome="not_started")
        else:
            envelope = await to_thread.run_sync(_request, socket_path, token_file, *prepared)
        return types.ServerResult(types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(envelope, allow_nan=False))], structuredContent=envelope, isError=not envelope["ok"]))

    # The pinned SDK's convenience decorator always sets isError=False.
    server.request_handlers[types.CallToolRequest] = call_tool
    return server


def main(argv: list[str] | None = None) -> int:
    """Run the selected profile over stdio without starting the local helper."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        from mcp.server.stdio import stdio_server

        server = create_server(profile=args.profile, socket_path=args.socket.expanduser(), token_file=args.token_file.expanduser())
    except ModuleNotFoundError:
        print("Install the optional MCP dependency with uv sync --extra mcp before running clawbridge-mcp.", file=sys.stderr)
        return 2

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
