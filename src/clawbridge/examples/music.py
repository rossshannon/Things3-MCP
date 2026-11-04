"""Control Music playback through fixed Apple Events, without UI automation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from clawbridge.actions import Action
from clawbridge.protocol import ok_envelope
from clawbridge.server import BridgeRequestHandler, UnixHTTPServer, build_identity, serve_until_stopped
from clawbridge.worker import run_worker, worker_main

DEFAULT_RUNTIME = Path.home() / "Library/Application Support/ClawBridgeMusic"
ACTIONS = {"state": Action("state"), "play": Action("play", mutation=True), "pause": Action("pause", mutation=True)}
SCRIPTS = {
    "state": """if application id "com.apple.Music" is running then
    tell application id "com.apple.Music" to return player state as text
else
    return "not_running"
end if""",
    "play": 'tell application id "com.apple.Music" to play\nreturn "ok"',
    "pause": 'tell application id "com.apple.Music" to pause\nreturn "ok"',
}


class AutomationDeniedError(RuntimeError):
    """The only requested Apple Event was denied before it could execute."""

    error_code = "automation_denied"
    outcome = "failed"
    authorization_hint = "Allow this signed bridge to control Music in System Settings > Privacy & Security > Automation."


def execute(name: str, _params: dict[str, Any]) -> dict[str, Any]:
    """Run one compiled-in script; neither script nor target comes from input."""
    result = subprocess.run(["/usr/bin/osascript"], input=SCRIPTS[name], capture_output=True, text=True, timeout=25, check=False)
    if result.returncode:
        if "(-1743)" in result.stderr:
            raise AutomationDeniedError("Music Automation permission was denied")
        # An unexpected failure after dispatch cannot establish that playback stayed unchanged.
        raise RuntimeError("Music did not confirm the requested action")
    output = result.stdout.strip()
    if name == "state" and output in {"not_running", "stopped", "playing", "paused", "fast forwarding", "rewinding"}:
        return {"state": output}
    if name in {"play", "pause"} and output == "ok":
        return {"action": name, "accepted": True}
    raise RuntimeError("Music returned an unexpected response")


class RequestHandler(BridgeRequestHandler):
    """Expose only playback state, play and pause."""

    def resolve(self, method: str, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Resolve exact routes; schemas reject every caller-supplied field."""
        if query:
            return None
        action = {("GET", "/music/state"): "state", ("POST", "/music/play"): "play", ("POST", "/music/pause"): "pause"}.get((method, path))
        return (action, body) if action else None


def create_server(socket_path: Path, token_file: Path, *, capture_payloads: bool = False) -> UnixHTTPServer:
    """Bind the Music adapter to the shared private transport and journal."""
    return UnixHTTPServer(
        socket_path,
        RequestHandler,
        token_file=token_file,
        actions=ACTIONS,
        worker=lambda name, params: run_worker("clawbridge.examples.music", ACTIONS[name], params),
        identity=build_identity(bundle_id="org.example.ClawBridgeMusic", version="0.1.0"),
        capture_payloads=capture_payloads,
    )


def main(argv: list[str] | None = None) -> int:
    """Serve Music actions; health is passive and sends no Apple Events."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default=str(DEFAULT_RUNTIME / "bridge.sock"))
    parser.add_argument("--token-file", default=str(DEFAULT_RUNTIME / "bridge.token"))
    parser.add_argument("--worker-action", help=argparse.SUPPRESS)
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args(argv)
    if args.worker_action:
        return worker_main(ACTIONS, args.worker_action, execute)
    if args.health:
        print(json.dumps(ok_envelope({"adapter": "music"})))
        return 0
    serve_until_stopped(create_server(Path(args.socket).expanduser(), Path(args.token_file).expanduser(), capture_payloads=os.environ.get("CLAWBRIDGE_JOURNAL_PAYLOADS") == "1"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
