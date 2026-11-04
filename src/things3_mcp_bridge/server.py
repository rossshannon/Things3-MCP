"""Things routes and cache policy over the shared authenticated local core."""

from __future__ import annotations

import argparse
import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from clawbridge.actions import InvalidRequestError
from clawbridge.protocol import error_envelope, ok_envelope
from clawbridge.runtime import ensure_token as _ensure_token
from clawbridge.server import BridgeRequestHandler as CoreRequestHandler
from clawbridge.server import UnixHTTPServer as CoreHTTPServer
from clawbridge.server import build_identity, serve_until_stopped
from clawbridge.worker import run_worker as _run_worker
from clawbridge.worker import worker_main
from things3_mcp import __version__
from things3_mcp.providers.base import ProviderError, read_context, read_observations
from things3_mcp.providers.bridge import DEFAULT_SOCKET, DEFAULT_TOKEN_FILE
from things3_mcp.providers.cache import CacheThingsProvider

from .actions import ACTIONS
from .auth_status import build_auth_status
from .cache import cache_status, write_snapshot

DEFAULT_WORKER_TIMEOUT = float(os.environ.get("THINGS3_MCP_BRIDGE_WORKER_TIMEOUT", "30"))


def ensure_token(token_file: Path = DEFAULT_TOKEN_FILE) -> str:
    """Read or create the existing Things token using private runtime checks."""
    return _ensure_token(token_file)


def run_worker(action: str, params: dict[str, Any] | None = None, *, timeout: float = DEFAULT_WORKER_TIMEOUT) -> dict[str, Any]:
    """Run one fixed Things action with bounded stdin and captured stderr."""
    definition = ACTIONS.get(action)
    if definition is None:
        return error_envelope("invalid_request", "Unsupported action", outcome="not_started")
    result = _run_worker("things3_mcp_bridge.server", definition, params or {}, timeout=timeout)
    if result.get("error_code") == "worker_timeout" and not definition.mutation:
        result["error_code"] = "things_db_timeout"
    if result.get("ok") and not definition.mutation:
        observed = result.get("capabilities", {})
        if observed.get("automation", {}).get("state") == "available" and observed.get("database", {}).get("state") in {"denied", "unavailable"}:
            result["source"] = "apple_events"
    return result


def _cache_envelope(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    provider = CacheThingsProvider()
    params = params or {}
    try:
        with read_context():
            if action == "search":
                data = provider.search(params.get("query", ""), include_items=bool(params.get("include_items", True)))
            elif action == "last":
                data = provider.last(params["period"], include_items=bool(params.get("include_items", True)))
            elif action == "get":
                data = provider.get(params["uuid"])
            elif action in {"tasks", "todos", "projects", "areas", "tags"}:
                data = getattr(provider, action)(**params)
            else:
                data = getattr(provider, action)(include_items=bool(params.get("include_items", True)))
            observations = read_observations()
            metadata = observations[-1] if observations else {}
            return ok_envelope(data, source="cache", generated_at=metadata.get("generated_at"), cache_age_seconds=metadata.get("cache_age_seconds"), snapshot_source=metadata.get("snapshot_source", "unknown"))
    except ProviderError as exc:
        return error_envelope(exc.error_code, exc.message, authorization_hint=exc.authorization_hint, cache_status=exc.cache_status or cache_status())


def live_or_cache(action: str, params: dict[str, Any] | None = None, *, require_live: bool = False) -> dict[str, Any]:
    """Keep read shapes and provenance, permitting callers to require live data."""
    live = run_worker(action, params)
    if live.get("ok") or require_live or live.get("error_code") == "invalid_request":
        return live
    cached = _cache_envelope(action, params)
    if cached.get("ok"):
        cached["capabilities"] = live.get("capabilities", {})
        cached["live_error"] = {key: live.get(key) for key in ("error_code", "message", "authorization_hint") if live.get(key)}
        return cached
    combined = dict(live)
    combined["cache_error"] = {key: cached.get(key) for key in ("error_code", "message") if cached.get(key)}
    return combined


class UnixHTTPServer(CoreHTTPServer):
    """Add Things cache policy and observations of real Automation operations."""

    def __init__(self, socket_path: Path = DEFAULT_SOCKET, *, token_file: Path = DEFAULT_TOKEN_FILE) -> None:
        self.observations: dict[str, Any] = {}
        self.observation_lock = threading.Lock()
        super().__init__(
            socket_path,
            BridgeRequestHandler,
            token_file=token_file,
            actions=ACTIONS,
            worker=self._worker,
            identity=build_identity(bundle_id="com.rossshannon.things3-mcp.bridge", version=__version__),
            capture_payloads=os.environ.get("THINGS3_MCP_BRIDGE_JOURNAL_PAYLOADS") == "1",
        )

    def _worker(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        result = run_worker(action, params)
        with self.observation_lock:
            self.observations.update(result.get("capabilities", {}))
        return result

    def status(self) -> dict[str, Any]:
        with self.observation_lock:
            return {**super().status(), **build_auth_status(observations=dict(self.observations))}

    def read_action(self, action: str, params: dict[str, Any], *, require_live: bool = False) -> dict[str, Any]:
        if action == "snapshot":
            envelope = self._worker(action, params)
            if envelope.get("ok"):
                source = envelope.get("source", "unknown")
                snapshot = write_snapshot(envelope["data"], source=source)
                return ok_envelope({"cache_status": cache_status(), "generated_at": snapshot["generated_at"]}, source=source, capabilities=envelope.get("capabilities", {}))
            return envelope
        if action == "diagnose":
            return self._worker(action, params)
        result = live_or_cache(action, params, require_live=require_live)
        with self.observation_lock:
            self.observations.update(result.get("capabilities", {}))
        return result


class BridgeRequestHandler(CoreRequestHandler):
    """Preserve established Things routes while validating every action."""

    server: UnixHTTPServer

    def special(self, method: str, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> dict[str, Any] | None:
        if method == "GET" and path == "/auth-status":
            with self.server.observation_lock:
                return ok_envelope(build_auth_status(observations=dict(self.server.observations)))
        if method == "GET" and path == "/cache/status":
            return ok_envelope(cache_status(), source="cache")
        return None

    def resolve(self, method: str, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        if method == "GET":
            if set(query) - {"include_items"}:
                raise InvalidRequestError("Unsupported query parameter")
            include = query.get("include_items", ["true"])[0].lower()
            if include not in {"true", "false"}:
                raise InvalidRequestError("Invalid include_items")
            if path == "/diagnose":
                return "diagnose", {}
            if path.startswith("/things/get/"):
                return "get", {"uuid": unquote(path.removeprefix("/things/get/"))}
            if path.startswith("/things/last/"):
                return "last", {"period": unquote(path.removeprefix("/things/last/")), "include_items": include == "true"}
            name = path.removeprefix("/things/")
            if path.startswith("/things/") and name in {"inbox", "today", "upcoming", "anytime", "someday", "projects", "areas", "tags", "trash"}:
                return name, {"include_items": include == "true"}
        if query:
            raise InvalidRequestError("Unsupported query parameter")
        if method == "POST":
            routes = {"/snapshot": "snapshot", "/things/todo": "add_task", "/things/project": "add_project"}
            routes.update({f"/things/{name}": name for name in ("search", "tasks", "todos", "projects", "areas", "tags")})
            if path in routes:
                return routes[path], body
        if method == "PATCH":
            for prefix, name in (("/things/todo/", "update_task"), ("/things/project/", "update_project")):
                if path.startswith(prefix):
                    if "uuid" in body:
                        raise InvalidRequestError("Object ID must come from the route")
                    return name, {**body, "uuid": unquote(path.removeprefix(prefix))}
        return None


def serve(socket_path: Path = DEFAULT_SOCKET, *, token_file: Path = DEFAULT_TOKEN_FILE) -> None:
    """Run the Things bridge with explicit ownership of its local endpoint."""
    serve_until_stopped(UnixHTTPServer(socket_path, token_file=token_file))


def snapshot_once() -> int:
    """Create one live snapshot and exit."""
    import json

    envelope = run_worker("snapshot")
    if not envelope.get("ok"):
        print(json.dumps(envelope))
        return 1
    source = envelope.get("source", "unknown")
    snapshot = write_snapshot(envelope["data"], source=source)
    print(json.dumps(ok_envelope({"cache_status": cache_status(), "generated_at": snapshot["generated_at"]}, source=source, capabilities=envelope.get("capabilities", {}))))
    return 0


def print_health() -> int:
    """Print passive local cache status without creating runtime files."""
    import json

    print(json.dumps(ok_envelope({"socket": str(DEFAULT_SOCKET), "token_file": str(DEFAULT_TOKEN_FILE), "cache_status": cache_status()})))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Serve the Things adapter or execute one compiled-in worker action."""
    parser = argparse.ArgumentParser(description="Local Things3 MCP bridge")
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET))
    parser.add_argument("--token-file", default=str(DEFAULT_TOKEN_FILE))
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--snapshot-once", action="store_true")
    parser.add_argument("--worker-action", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker_action:
        from .db_reader import capability_observations, run_action

        return worker_main(ACTIONS, args.worker_action, run_action, observations=capability_observations)
    if args.health:
        return print_health()
    if args.snapshot_once:
        return snapshot_once()
    serve(Path(args.socket).expanduser(), token_file=Path(args.token_file).expanduser())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
