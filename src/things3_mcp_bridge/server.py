"""Local Things3 MCP bridge server."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import socketserver
import stat
import subprocess  # nosec B404 - required for spawning the worker
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from things3_mcp.providers.base import ProviderError
from things3_mcp.providers.bridge import DEFAULT_SOCKET, DEFAULT_TOKEN_FILE
from things3_mcp.providers.cache import CacheStore, CacheThingsProvider

from .auth_status import AUTHORIZATION_HINT, build_auth_status
from .cache import cache_status, write_snapshot
from .protocol import error_envelope, ok_envelope

DEFAULT_WORKER_TIMEOUT = float(os.environ.get("THINGS3_MCP_BRIDGE_WORKER_TIMEOUT", "30"))


def _restrict_owner_only(path: Path, *, is_dir: bool) -> None:
    """Set permissions to owner-only for a sensitive credential file/dir.

    Uses computed mode bits so this is a deliberate, secret-handling choice
    rather than a "default permissions" mistake. Files holding bearer tokens
    or directories containing them must not be readable by other local users.
    """
    owner_read = stat.S_IRUSR
    owner_write = stat.S_IWUSR
    owner_exec = stat.S_IXUSR if is_dir else 0
    os.chmod(path, owner_read | owner_write | owner_exec)


def ensure_token(token_file: Path = DEFAULT_TOKEN_FILE) -> str:
    """Create/read the local bearer token, locked down to the current user.

    Token creation uses ``os.open(..., O_CREAT | O_EXCL | O_WRONLY, 0o600)`` so
    the file is created with owner-only permissions atomically — no window
    where another local process at the same UID could race-read a freshly
    written but not-yet-chmodded token.
    """
    parent = token_file.parent
    parent.mkdir(parents=True, exist_ok=True)
    _restrict_owner_only(parent, is_dir=True)
    if token_file.exists():
        os.chmod(token_file, 0o600)
        return token_file.read_text().strip()
    token = secrets.token_urlsafe(32)
    fd = os.open(str(token_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, token.encode())
    finally:
        os.close(fd)
    return token


def run_worker(action: str, params: dict[str, Any] | None = None, *, timeout: float = DEFAULT_WORKER_TIMEOUT) -> dict[str, Any]:
    """Run a Things action in a killable child process.

    The worker is the same signed Mach-O as the bridge bundle, so TCC matches
    its code identity directly against the bundle's FDA / Automation grants.
    No disclaim shim — ``responsibility_spawnattrs_setdisclaim`` is broken on
    macOS Tahoe (verified with a pure-C reproducer); the bridge's own
    responsibility chain is what matters and gets cleared by reboot rather
    than by per-spawn disclaim. See docs/sessions/2026-05-05-0834-… for the
    full debugging trail.
    """
    is_frozen = getattr(sys, "frozen", False)
    if is_frozen:
        cmd = [sys.executable, "--worker-action", action, "--worker-params", json.dumps(params or {})]
    else:
        cmd = [sys.executable, "-m", "things3_mcp_bridge.db_reader", action, "--params", json.dumps(params or {})]

    try:
        # Capture stdout (the worker's JSON envelope) but let stderr flow through
        # to the bridge's own stderr so worker-progress traces land in bridge.err.log.
        completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=None, text=True, timeout=timeout, check=False)  # noqa: S603 # nosec B603 - fixed argv, no shell
    except subprocess.TimeoutExpired:
        return error_envelope("things_db_timeout", f"Things DB read worker timed out after {timeout:g}s", authorization_hint=AUTHORIZATION_HINT, cache_status=cache_status())
    stdout = completed.stdout.strip()

    if not stdout:
        return error_envelope("things_db_unreadable", "Things DB read worker returned no output", authorization_hint=AUTHORIZATION_HINT, cache_status=cache_status())
    try:
        payload = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        return error_envelope("things_db_unreadable", f"Things DB read worker returned invalid JSON: {exc}", authorization_hint=AUTHORIZATION_HINT, cache_status=cache_status())
    if not payload.get("ok"):
        return error_envelope(payload.get("error_code", "things_db_unreadable"), payload.get("message", "Things DB read failed"), authorization_hint=AUTHORIZATION_HINT, cache_status=cache_status())
    return ok_envelope(payload.get("data"), source="live")


def _cache_envelope(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    provider = CacheThingsProvider()
    params = params or {}
    try:
        if action == "search":
            data = provider.search(params.get("query", ""), include_items=bool(params.get("include_items", True)))
        elif action == "get":
            data = provider.get(params["uuid"])
        elif action in {"tasks", "todos", "projects", "areas", "tags"}:
            data = getattr(provider, action)(**params)
        else:
            data = getattr(provider, action)(include_items=bool(params.get("include_items", True)))
        status = CacheStore().status()
        return ok_envelope(data, source="cache", generated_at=status.get("generated_at"), cache_age_seconds=status.get("age_seconds"))
    except ProviderError as exc:
        return error_envelope(exc.error_code, exc.message, authorization_hint=exc.authorization_hint, cache_status=exc.cache_status or cache_status())


def live_or_cache(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attempt live worker read, falling back to cache on authorization/read failure.

    When both fail (e.g. fresh install where the bridge is not yet authorised
    *and* no cache snapshot has been written), surface both error envelopes so
    the user sees that cache is also missing — otherwise the response only
    mentions the live failure and the user wonders silently about the cache
    state.
    """
    live = run_worker(action, params)
    if live.get("ok"):
        return live
    cached = _cache_envelope(action, params)
    if cached.get("ok"):
        cached["live_error"] = {key: live.get(key) for key in ("error_code", "message", "authorization_hint") if live.get(key)}
        return cached
    # Both failed — annotate the live envelope with the cache error fields too.
    combined = dict(live)
    combined["cache_error"] = {key: cached.get(key) for key in ("error_code", "message") if cached.get(key)}
    return combined


def _run_write(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a write action through the worker.

    No cache fallback — writes that can't reach Things must surface as errors
    so callers don't silently lose data into a stale cache.
    """
    return run_worker(action, params)


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Unix-domain HTTP server with one thread per request.

    A single hung worker subprocess (e.g. tccd queueing on first call) shouldn't
    block ``/health`` or other concurrent requests — without threading, every
    other call sits behind the slow one. Each request handler spawns a child
    via ``run_worker``; threading the HTTP layer is safe because no shared
    mutable state is touched outside the worker subprocess.
    """

    allow_reuse_address = True
    daemon_threads = True

    def server_bind(self) -> None:
        socketserver.UnixStreamServer.server_bind(self)
        os.chmod(self.server_address, 0o600)


class BridgeRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for bridge commands."""

    server_version = "Things3MCPBridge/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        client = "unix"
        if isinstance(self.client_address, tuple) and self.client_address:
            client = str(self.client_address[0])
        print(f"{client} - {format % args}", file=sys.stderr)

    def _authorized(self) -> bool:
        if self.path == "/health":
            return True
        expected = ensure_token()
        if not expected:
            # Empty/missing token file → treat as unauthorized rather than
            # accepting a request whose Authorization header also happens to
            # be empty. (Fail closed.)
            return False
        provided = self.headers.get("Authorization") or ""
        return hmac.compare_digest(provided, f"Bearer {expected}")

    def _send(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(error_envelope("bridge_unauthorized", "Bridge token is missing or invalid"), 401)
            return
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        include_items = qs.get("include_items", ["true"])[0].lower() == "true"
        path = parsed.path
        if path == "/health":
            self._send(ok_envelope({"running": True, "socket": str(DEFAULT_SOCKET), "cache_status": cache_status()}))
            return
        if path == "/auth-status":
            self._send(ok_envelope(build_auth_status()))
            return
        if path == "/cache/status":
            self._send(ok_envelope(cache_status(), source="cache"))
            return
        if path == "/diagnose":
            envelope = run_worker("diagnose")
            self._send(envelope)
            return
        if path.startswith("/things/get/"):
            self._send(live_or_cache("get", {"uuid": path.rsplit("/", 1)[-1]}))
            return
        if path.startswith("/things/last/"):
            period = path.rsplit("/", 1)[-1]
            self._send(live_or_cache("last", {"period": period, "include_items": include_items}))
            return
        if path.startswith("/things/"):
            action = path.rsplit("/", 1)[-1]
            if action in {"inbox", "today", "upcoming", "anytime", "someday", "projects", "areas", "tags", "trash"}:
                self._send(live_or_cache(action, {"include_items": include_items}))
                return
        self._send(error_envelope("not_found", f"No bridge endpoint for {path}"), 404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(error_envelope("bridge_unauthorized", "Bridge token is missing or invalid"), 401)
            return
        path = urlparse(self.path).path
        body = self._body()
        if path == "/snapshot":
            envelope = run_worker("snapshot", body or None)
            if envelope.get("ok"):
                snapshot = write_snapshot(envelope.get("data", {}), source="live")
                self._send(ok_envelope({"cache_status": cache_status(), "generated_at": snapshot["generated_at"]}))
            else:
                self._send(envelope)
            return
        if path == "/things/search":
            self._send(live_or_cache("search", body))
            return
        if path in {"/things/tasks", "/things/todos", "/things/projects", "/things/areas", "/things/tags"}:
            self._send(live_or_cache(path.rsplit("/", 1)[-1], body))
            return
        if path == "/things/todo":
            self._send(_run_write("add_task", body))
            return
        if path == "/things/project":
            self._send(_run_write("add_project", body))
            return
        self._send(error_envelope("not_found", f"No bridge endpoint for {path}"), 404)

    def do_PATCH(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(error_envelope("bridge_unauthorized", "Bridge token is missing or invalid"), 401)
            return
        path = urlparse(self.path).path
        body = self._body()
        if path.startswith("/things/todo/"):
            uuid = path.rsplit("/", 1)[-1]
            self._send(_run_write("update_task", {**body, "uuid": uuid}))
            return
        if path.startswith("/things/project/"):
            uuid = path.rsplit("/", 1)[-1]
            self._send(_run_write("update_project", {**body, "uuid": uuid}))
            return
        self._send(error_envelope("not_found", f"No bridge endpoint for PATCH {path}"), 404)


def serve(socket_path: Path = DEFAULT_SOCKET) -> None:
    """Run the Unix socket bridge server forever."""
    ensure_token()
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()
    is_frozen = getattr(sys, "frozen", False)
    print(f"Things3 MCP bridge starting: frozen={is_frozen}", file=sys.stderr)
    with UnixHTTPServer(str(socket_path), BridgeRequestHandler) as server:
        print(f"Things3 MCP bridge listening on {socket_path}", file=sys.stderr)
        server.serve_forever()


def snapshot_once() -> int:
    """Create one live snapshot and exit."""
    ensure_token()
    envelope = run_worker("snapshot")
    if not envelope.get("ok"):
        print(json.dumps(envelope, indent=2))
        return 1
    snapshot = write_snapshot(envelope.get("data", {}), source="live")
    print(json.dumps(ok_envelope({"cache_status": cache_status(), "generated_at": snapshot["generated_at"]}), indent=2))
    return 0


def print_health() -> int:
    """Print local bridge/cache status without touching the Things DB."""
    print(json.dumps(ok_envelope({"socket": str(DEFAULT_SOCKET), "token_file": str(DEFAULT_TOKEN_FILE), "cache_status": cache_status()}), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Console entry point."""
    parser = argparse.ArgumentParser(description="Local Things3 MCP bridge")
    parser.add_argument("--socket", default=str(DEFAULT_SOCKET), help="Unix socket path")
    parser.add_argument("--health", action="store_true", help="Print bridge/cache health and exit")
    parser.add_argument("--snapshot-once", action="store_true", help="Run one live Things read and update cache")
    parser.add_argument("--worker-action", help=argparse.SUPPRESS)
    parser.add_argument("--worker-params", default="{}", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.worker_action:
        from .db_reader import run_action

        try:
            result = run_action(args.worker_action, json.loads(args.worker_params))
            print(json.dumps({"ok": True, "data": result}))
            return 0
        except Exception as exc:  # noqa: BLE001 - serialize worker failures to parent
            print(json.dumps({"ok": False, "error_code": "things_db_unreadable", "message": str(exc), "diagnostics": run_action("diagnose")}))
            return 1

    if args.health:
        return print_health()
    if args.snapshot_once:
        return snapshot_once()
    serve(Path(args.socket).expanduser())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
