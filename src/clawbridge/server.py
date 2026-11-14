"""Authenticated, bounded Unix HTTP transport for a compiled-in app adapter."""

from __future__ import annotations

import hmac
import json
import os
import signal
import socket
import socketserver
import sys
import threading
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from types import FrameType
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from .actions import MAX_BODY_BYTES, Action, InvalidRequestError, correlation_id, json_object
from .journal import Journal, JournalError
from .protocol import OUTCOMES, error_envelope, ok_envelope
from .runtime import RuntimeSafetyError, SocketLease, ensure_token

REQUEST_TIMEOUT = 5.0


def build_identity(*, bundle_id: str, version: str) -> dict[str, str]:
    """Report frozen build provenance or explicit development identity."""
    if getattr(sys, "frozen", False):
        path = Path(sys.executable).parent.parent / "Resources" / "build-manifest.json"
        data = json.loads(path.read_text())
        identity = {key: data[key] for key in ("bundle_id", "version", "build_id")}
        if any(not isinstance(value, str) or not value for value in identity.values()):
            raise RuntimeSafetyError("Invalid bundle build identity")
        return identity
    return {"bundle_id": bundle_id, "version": version, "build_id": "development"}


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Bound request threads, worker concurrency, and durable mutation admission."""

    daemon_threads = False
    block_on_close = True

    def __init__(
        self,
        socket_path: Path,
        handler: type[BridgeRequestHandler],
        *,
        token_file: Path,
        actions: dict[str, Action],
        worker: Callable[[str, dict[str, Any]], dict[str, Any]],
        identity: dict[str, str],
        capture_payloads: bool = False,
        max_workers: int = 4,
        max_connections: int = 16,
    ) -> None:
        """Acquire endpoint ownership before touching shared recovery state."""
        self.lease = SocketLease(socket_path)
        try:
            self.token = ensure_token(token_file)
            self.actions = actions
            self.worker = worker
            self.identity = identity
            self.instance_id = str(uuid.uuid4())
            self.journal = Journal(socket_path.parent / "operations", capture_payloads=capture_payloads)
            self.workers = threading.BoundedSemaphore(max_workers)
            self.mutations = threading.BoundedSemaphore(1)
            self.connections = threading.BoundedSemaphore(max_connections)
            super().__init__(str(socket_path), handler)
        except BaseException:
            self.lease.close()
            raise

    def server_bind(self) -> None:
        """Restrict the endpoint before it starts listening."""
        super().server_bind()
        self.lease.bound()

    def server_close(self) -> None:
        """Drain request handlers before releasing endpoint and journal ownership."""
        super().server_close()
        self.lease.close()

    def process_request(self, request: Any, client_address: Any) -> None:
        """Reject excess clients without creating another request thread."""
        if not self.connections.acquire(blocking=False):
            body = json.dumps(error_envelope("bridge_busy", "Bridge request capacity is full", outcome="not_started")).encode()
            try:
                request.settimeout(0.2)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        """Release connection capacity when its handler terminates."""
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Avoid default tracebacks, which can contain app payloads; an exception's type name cannot."""
        print(f"Bridge request failed: {type(sys.exc_info()[1]).__name__}", file=sys.stderr)

    def status(self) -> dict[str, Any]:
        """Describe this exact instance without probing or launching an app."""
        return {"pid": os.getpid(), "executable": sys.executable, "instance_id": self.instance_id, "identity": self.identity}

    def read_action(self, action: str, params: dict[str, Any], *, require_live: bool = False) -> dict[str, Any]:
        """Run the adapter's fixed read action; adapters may supply cache policy."""
        return self.worker(action, params)

    def execute(self, name: str, params: dict[str, Any], *, correlation: str | None = None, require_live: bool = False) -> dict[str, Any]:
        """Validate, reserve capacity, journal mutations, and dispatch once."""
        action = self.actions.get(name)
        if action is None:
            raise InvalidRequestError("Unsupported action")
        params = action.validate(params)
        correlation = correlation_id(correlation)
        if not self.workers.acquire(blocking=False):
            return error_envelope("bridge_busy", "Bridge worker capacity is full", outcome="not_started", correlation_id=correlation)
        mutation_reserved = False
        try:
            if not action.mutation:
                try:
                    return self.read_action(name, params, require_live=require_live)
                except Exception:  # noqa: BLE001 - a read fault is the bridge's, never the caller's request
                    print("Bridge read failed", file=sys.stderr)
                    return error_envelope("bridge_failed", "Bridge could not complete the read", outcome="failed", correlation_id=correlation)
            mutation_reserved = self.mutations.acquire(blocking=False)
            if not mutation_reserved:
                return error_envelope("bridge_busy", "A mutation is already active", outcome="not_started", correlation_id=correlation)
            try:
                key = self.journal.start(name, params, correlation)
            except (OSError, ValueError):
                return error_envelope("journal_unavailable", "Recovery record could not be persisted; no action was started", outcome="not_started", correlation_id=correlation)
            try:
                response = self.worker(name, params)
            except Exception:  # noqa: BLE001 - dispatch exceptions must not imply safe replay
                response = error_envelope("worker_failed", "App outcome could not be established", outcome="outcome_unknown")
            if not isinstance(response, dict) or type(response.get("ok")) is not bool or response.get("outcome") not in OUTCOMES:
                # The worker did run, so a response that cannot be interpreted is never safe to replay.
                response = error_envelope("worker_invalid_response", "App outcome could not be established", outcome="outcome_unknown")
            response.update(operation_id=key, correlation_id=correlation)
            try:
                self.journal.finish(key, response)
            except (OSError, ValueError):
                response["journal_warning"] = "Completion record could not be persisted; retain this response for recovery"
            return response
        finally:
            if mutation_reserved:
                self.mutations.release()
            self.workers.release()


def serve_until_stopped(server: UnixHTTPServer) -> None:
    """Serve on the main thread and drain requests on SIGTERM or SIGINT."""
    stopping = False

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    previous = {signum: signal.signal(signum, request_stop) for signum in (signal.SIGTERM, signal.SIGINT)}
    previous_timeout = server.timeout
    try:
        server.timeout = 0.2
        with server:
            while not stopping:
                server.handle_request()
    finally:
        server.timeout = previous_timeout
        for signum, handler in previous.items():
            signal.signal(signum, handler)


class _RequestInput:
    """Request stream that remembers the last line read, to tell complete headers from truncated ones."""

    def __init__(self, raw: Any) -> None:
        self.raw = raw
        self.last_line = b""

    def readline(self, size: int = -1) -> bytes:
        self.last_line = self.raw.readline(size)
        return self.last_line

    def read(self, size: int = -1) -> bytes:
        return self.raw.read(size)

    def close(self) -> None:
        self.raw.close()


class BridgeRequestHandler(BaseHTTPRequestHandler):
    """Strict HTTP framing and authentication, shared by fixed-route adapters."""

    server: UnixHTTPServer
    server_version = "ClawBridge/1"
    sys_version = ""

    def setup(self) -> None:
        """Bound both idle reads and total request input time."""
        super().setup()
        self.request_input = _RequestInput(self.rfile)
        self.rfile = cast(Any, self.request_input)
        self.connection.settimeout(REQUEST_TIMEOUT)
        self.input_deadline = threading.Timer(REQUEST_TIMEOUT, self._end_input)
        self.input_deadline.daemon = True
        self.input_deadline.start()

    def _end_input(self) -> None:
        try:
            self.connection.shutdown(socket.SHUT_RD)
        except OSError:
            pass

    def finish(self) -> None:
        """Stop the input deadline even when request parsing fails."""
        self.input_deadline.cancel()
        super().finish()

    def parse_request(self) -> bool:
        """Refuse a request line without a protocol version before waiting for its headers.

        The standard library treats one as HTTP/0.9 and, depending on the Python
        version, either waits for headers that never come or skips them entirely.
        """
        request_line: bytes = getattr(self, "raw_requestline", b"")
        if len(request_line.split()) == 2:
            self.command = ""
            self.request_version = self.default_request_version
            self.requestline = ""
            self.close_connection = True
            self.send_error(400)
            return False
        return super().parse_request()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Suppress BaseHTTPRequestHandler's payload-bearing request log."""

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Return static errors without reflecting request paths or headers."""
        self._send(error_envelope("invalid_request", "Invalid HTTP request", outcome="not_started"), code)

    def _authorized(self) -> bool:
        return bool(self.server.token) and hmac.compare_digest((self.headers.get("Authorization") or "").encode(), f"Bearer {self.server.token}".encode())

    def _send(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, allow_nan=False).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (OSError, TimeoutError):
            # The client has gone; there is nobody left to tell.
            pass

    def _body(self) -> dict[str, Any]:
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") is not None or len(lengths) > 1:
            raise InvalidRequestError("Unsupported request framing")
        if not lengths:
            return {}
        if not lengths[0].isascii() or not lengths[0].isdigit():
            raise InvalidRequestError("Invalid content length")
        length = int(lengths[0])
        if length > MAX_BODY_BYTES:
            raise InvalidRequestError("Request body is too large")
        try:
            raw = self.rfile.read(length)
        except OSError as exc:
            raise InvalidRequestError("Incomplete request body") from exc
        if len(raw) != length:
            raise InvalidRequestError("Incomplete request body")
        return json_object(raw) if raw else {}

    def resolve(self, method: str, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Map adapter routes to fixed actions without importing caller code."""
        return None

    def special(self, method: str, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> dict[str, Any] | None:
        """Supply adapter-local read-only status endpoints."""
        return None

    def _route(self) -> tuple[dict[str, Any], int] | tuple[str, dict[str, Any], bool]:
        """Authenticate and validate a request, answering it directly unless an action must run."""
        if self.request_input.last_line not in {b"\r\n", b"\n"}:
            # The header block was cut short by the client or by the input deadline.
            # Acting on it would drop whatever headers were lost, such as the body length.
            raise InvalidRequestError("Incomplete request headers")
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise InvalidRequestError("Only local request paths are supported")
        public_health = self.command == "GET" and parsed.path == "/health" and not parsed.query
        if not public_health and not self._authorized():
            return error_envelope("bridge_unauthorized", "Bridge token is missing or invalid", outcome="not_started"), 401
        body = self._body()
        self.input_deadline.cancel()
        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
        if any(len(values) != 1 for values in query.values()):
            raise InvalidRequestError("Repeated query field")
        if self.command == "GET" and body:
            raise InvalidRequestError("GET request bodies are unsupported")
        if public_health:
            return ok_envelope({"running": True, "version": self.server.identity["version"]}), 200
        if self.command == "GET" and parsed.path == "/status":
            return ok_envelope(self.server.status()), 200
        if self.command == "GET" and parsed.path == "/operations":
            if set(query) - {"correlation_id", "limit"}:
                raise InvalidRequestError("Unsupported operation query")
            correlation = correlation_id(query.get("correlation_id", [None])[0])
            limit = query.get("limit", ["25"])[0]
            if not limit.isascii() or not limit.isdigit():
                raise InvalidRequestError("Invalid operation limit")
            return ok_envelope(self.server.journal.recent(correlation=correlation, limit=int(limit))), 200
        if self.command == "GET" and parsed.path.startswith("/operations/"):
            record = self.server.journal.lookup(parsed.path.removeprefix("/operations/"))
            if record is None:
                return error_envelope("not_found", "Operation is outside the retained history"), 404
            return ok_envelope(record), 200
        special = self.special(self.command, parsed.path, query, body)
        if special is not None:
            return special, 200
        resolved = self.resolve(self.command, parsed.path, query, body)
        if resolved is None:
            return error_envelope("not_found", "No bridge endpoint", outcome="not_started"), 404
        live = self.headers.get("X-Require-Live", "false").lower()
        if live not in {"true", "false"}:
            raise InvalidRequestError("Invalid live-read requirement")
        return *resolved, live == "true"

    def _handle(self) -> None:
        """Answer every request with one JSON envelope, whatever goes wrong.

        Nothing has run while the request is being routed, so faults there are
        reported as not started. Once an action is dispatched, a fault is the
        bridge's own and must never read as a request that is safe to resend.
        """
        try:
            routed = self._route()
        except (JournalError, RuntimeSafetyError, OSError):
            self._send(error_envelope("bridge_unavailable", "Bridge storage is unavailable", outcome="not_started"), 503)
            return
        except (InvalidRequestError, ValueError, UnicodeError):
            self._send(error_envelope("invalid_request", "Invalid bridge request", outcome="not_started"), 400)
            return
        except Exception as exc:  # noqa: BLE001 - a handler that raises would close the connection without a reply
            print(f"Bridge request failed: {type(exc).__name__}", file=sys.stderr)
            self._send(error_envelope("bridge_failed", "Bridge could not handle the request", outcome="not_started"), 500)
            return
        if len(routed) == 2:
            self._send(*routed)
            return
        name, params, require_live = routed
        definition = self.server.actions.get(name)
        unknown = "outcome_unknown" if definition is not None and definition.mutation else "failed"
        try:
            response = self.server.execute(name, params, correlation=self.headers.get("X-Correlation-ID"), require_live=require_live)
        except InvalidRequestError:
            # Raised only while validating, before anything is journalled or started.
            self._send(error_envelope("invalid_request", "Invalid bridge request", outcome="not_started"), 400)
            return
        except Exception as exc:  # noqa: BLE001 - see above
            print(f"Bridge action failed: {type(exc).__name__}", file=sys.stderr)
            self._send(error_envelope("bridge_failed", "Bridge could not establish the outcome", outcome=unknown), 500)
            return
        try:
            self._send(response, {"bridge_busy": 503, "journal_unavailable": 503, "bridge_failed": 500}.get(str(response.get("error_code")), 200))
        except (ValueError, TypeError, RecursionError):
            # The action ran but its result cannot be encoded; say so without implying it never started.
            failure = error_envelope("bridge_invalid_response", "Bridge could not encode the result", outcome=unknown)
            for key in ("operation_id", "correlation_id"):
                if isinstance(response.get(key), str):
                    failure[key] = response[key]
            self._send(failure, 500)

    def do_GET(self) -> None:  # noqa: N802
        """Handle a fixed read-only endpoint."""
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        """Handle a fixed action endpoint."""
        self._handle()

    def do_PATCH(self) -> None:  # noqa: N802
        """Handle a fixed mutation endpoint."""
        self._handle()
