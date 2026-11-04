"""Standalone synthetic adapter: echo text and update an app-owned counter."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any

from .actions import Action
from .protocol import ok_envelope
from .runtime import atomic_write, private_directory, private_open
from .server import BridgeRequestHandler, UnixHTTPServer, build_identity
from .worker import run_worker, worker_main

DEFAULT_RUNTIME = Path.home() / "Library" / "Application Support" / "ClawBridgeDemo"
ACTIONS = {
    "read": Action("read"),
    "echo": Action("echo", fields={"text": str}, required=frozenset({"text"})),
    "increment": Action("increment", True, {"amount": int}, frozenset({"amount"})),
}


def execute(name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Use only a synthetic app-owned file, never a caller-supplied path."""
    if name == "echo":
        return {"text": params["text"]}
    directory = Path(os.environ.get("CLAWBRIDGE_DEMO_STATE_DIR", str(DEFAULT_RUNTIME)))
    private_directory(directory)
    path = directory / "demo-state.json"
    try:
        fd = private_open(path, os.O_RDONLY)
        with os.fdopen(fd) as source:
            state = json.load(source)
    except FileNotFoundError:
        state = {"value": 0}
    if name == "increment":
        state = {"value": state["value"] + params["amount"], "id": str(uuid.uuid4())}
        atomic_write(path, json.dumps(state).encode())
    return state


class DemoRequestHandler(BridgeRequestHandler):
    """Expose three fixed routes for the synthetic adapter."""

    def resolve(self, method: str, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Translate only the compiled-in demonstration routes."""
        if query:
            return None
        routes = {("GET", "/demo/read"): "read", ("POST", "/demo/echo"): "echo", ("POST", "/demo/increment"): "increment"}
        action = routes.get((method, path))
        return (action, body) if action else None


def create_server(socket_path: Path, token_file: Path, *, timeout: float = 30, capture_payloads: bool = False) -> UnixHTTPServer:
    """Build the demo server with state fixed to its private runtime directory."""
    env = {**os.environ, "CLAWBRIDGE_DEMO_STATE_DIR": str(socket_path.parent)}

    def worker(name: str, params: dict[str, Any]) -> dict[str, Any]:
        return run_worker("clawbridge.demo", ACTIONS[name], params, timeout=timeout, env=env)

    return UnixHTTPServer(
        socket_path, DemoRequestHandler, token_file=token_file, actions=ACTIONS, worker=worker, identity=build_identity(bundle_id="org.clawbridge.demo", version="0.1.0"), capture_payloads=capture_payloads
    )


def main(argv: list[str] | None = None) -> int:
    """Serve the synthetic demo without importing Things or requiring grants."""
    parser = argparse.ArgumentParser(description="ClawBridge synthetic demonstration")
    parser.add_argument("--socket", default=str(DEFAULT_RUNTIME / "bridge.sock"))
    parser.add_argument("--token-file", default=str(DEFAULT_RUNTIME / "bridge.token"))
    parser.add_argument("--worker-action", help=argparse.SUPPRESS)
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args(argv)
    if args.worker_action:
        return worker_main(ACTIONS, args.worker_action, execute)
    if args.health:
        print(json.dumps(ok_envelope({"adapter": "synthetic", "version": "0.1.0"})))
        return 0
    with create_server(Path(args.socket).expanduser(), Path(args.token_file).expanduser(), capture_payloads=os.environ.get("CLAWBRIDGE_JOURNAL_PAYLOADS") == "1") as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
