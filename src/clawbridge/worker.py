"""Bounded stdin worker execution, with no payloads in argv or ordinary logs."""

from __future__ import annotations

import contextlib
import json
import os
import re
import selectors
import signal
import subprocess  # nosec B404
import sys
import time
from collections.abc import Callable
from typing import Any

from .actions import MAX_BODY_BYTES, Action, InvalidRequestError, json_object
from .protocol import OUTCOMES, PROTOCOL_VERSION, error_envelope, ok_envelope

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def _stop_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _exchange(process: subprocess.Popen[bytes], payload: bytes, timeout: float) -> bytes:
    """Drain private stderr and bound stdout while enforcing one total deadline."""
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise ValueError("Worker pipes are unavailable")
    deadline = time.monotonic() + timeout
    output = bytearray()
    with selectors.DefaultSelector() as selector:
        for pipe in (process.stdin, process.stdout, process.stderr):
            os.set_blocking(pipe.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE)
        selector.register(process.stdout, selectors.EVENT_READ)
        selector.register(process.stderr, selectors.EVENT_READ)
        pending = memoryview(payload)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            for key, _events in selector.select(remaining):
                stream = key.fileobj
                if stream is process.stdin:
                    try:
                        sent = os.write(process.stdin.fileno(), pending[:65536])
                        pending = pending[sent:]
                    except BrokenPipeError:
                        pending = pending[len(pending) :]
                    if not pending:
                        selector.unregister(stream)
                        process.stdin.close()
                    continue
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(stream)
                elif stream is process.stdout:
                    output.extend(chunk)
                    if len(output) > MAX_RESPONSE_BYTES:
                        raise ValueError("Worker output limit")
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError from exc
    return bytes(output)


def run_worker(entry_module: str, action: Action, params: dict[str, Any], *, timeout: float = 30, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Execute a fixed action in the same executable, validating its response."""
    try:
        params = action.validate(params)
    except InvalidRequestError:
        return error_envelope("invalid_request", "Invalid action parameters", outcome="not_started")
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command += ["-m", entry_module]
    command += ["--worker-action", action.name]
    unknown = "outcome_unknown" if action.mutation else "failed"
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env=env)  # nosec B603
    except OSError:
        return error_envelope("worker_unavailable", "App worker could not be started", outcome="not_started")
    try:
        with process:
            try:
                stdout = _exchange(process, json.dumps(params, allow_nan=False).encode(), timeout)
            except (TimeoutError, OSError, ValueError):
                _stop_group(process)
                return error_envelope("worker_timeout", "App worker exceeded its deadline or output limit", outcome=unknown)
            returncode = process.returncode
    except OSError:
        return error_envelope("worker_failed", "App worker outcome could not be established", outcome=unknown)
    try:
        if len(stdout) > MAX_RESPONSE_BYTES:
            raise ValueError("Oversized worker response")
        payload = json.loads(stdout)
        if not isinstance(payload, dict) or type(payload.get("ok")) is not bool or type(payload.get("protocol_version")) is not int or payload.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("Invalid envelope")
        if payload["ok"]:
            if returncode != 0 or "data" not in payload or (action.mutation and payload.get("outcome") != "succeeded"):
                raise ValueError("Invalid success")
            return ok_envelope(payload["data"], outcome="succeeded", capabilities=_capabilities(payload.get("capabilities", {})))
        code, outcome = payload.get("error_code"), payload.get("outcome")
        if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code) or outcome not in OUTCOMES - {"succeeded"}:
            raise ValueError("Invalid failure")
        hint = payload.get("authorization_hint")
        if hint is not None and (not isinstance(hint, str) or len(hint) > 1000):
            raise ValueError("Invalid hint")
        return error_envelope(code, "App action did not complete", outcome=outcome, authorization_hint=hint, capabilities=_capabilities(payload.get("capabilities", {})))
    except (ValueError, TypeError, RecursionError):
        return error_envelope("worker_invalid_response", "App worker returned an invalid response", outcome=unknown)


def _capabilities(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or len(value) > 8:
        raise ValueError("Invalid capability observations")
    for name, observation in value.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z_]{1,32}", name) or not isinstance(observation, dict):
            raise ValueError("Invalid capability observation")
        if set(observation) - {"state", "observed_at", "error_code"} or observation.get("state") not in {"available", "denied", "unavailable", "unknown"}:
            raise ValueError("Invalid capability observation")
        timestamp = observation.get("observed_at")
        code = observation.get("error_code")
        if timestamp is not None and (not isinstance(timestamp, str) or len(timestamp) > 64):
            raise ValueError("Invalid capability timestamp")
        if code is not None and (not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code)):
            raise ValueError("Invalid capability error code")
    return value


def worker_main(actions: dict[str, Action], name: str, execute: Callable[[str, dict[str, Any]], Any], *, observations: Callable[[], dict[str, Any]] | None = None) -> int:
    """Run a compiled-in adapter action and emit exactly one JSON envelope."""
    action = actions.get(name)
    try:
        if action is None:
            raise InvalidRequestError("Unsupported action")
        params = action.validate(json_object(sys.stdin.buffer.read(MAX_BODY_BYTES + 1)))
    except (InvalidRequestError, OSError):
        print(json.dumps(error_envelope("invalid_request", "Invalid action parameters", outcome="not_started")))
        return 1
    try:
        # Adapter output and exception text may contain private task content.
        with open(os.devnull, "w") as discard, contextlib.redirect_stdout(discard), contextlib.redirect_stderr(discard):
            data = execute(name, params)
        envelope = ok_envelope(data, outcome="succeeded", capabilities=_capabilities(observations() if observations else {}))
        encoded = json.dumps(envelope, allow_nan=False)
    except Exception as exc:  # noqa: BLE001 - cross-process errors are a fixed JSON contract
        code = getattr(exc, "error_code", "worker_failed")
        if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code):
            code = "worker_failed"
        outcome = getattr(exc, "outcome", "outcome_unknown" if action.mutation else "failed")
        if outcome not in OUTCOMES - {"succeeded"}:
            outcome = "outcome_unknown" if action.mutation else "failed"
        hint = getattr(exc, "authorization_hint", None)
        if not isinstance(hint, str) or len(hint) > 1000:
            hint = None
        encoded = json.dumps(error_envelope(code, "App action did not complete", outcome=outcome, authorization_hint=hint, capabilities=_capabilities(observations() if observations else {})))
        print(encoded)
        return 1
    print(encoded)
    return 0
