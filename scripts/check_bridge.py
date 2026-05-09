#!/usr/bin/env python3
"""Diagnose the local Things3 MCP bridge without touching Things data directly."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from things3_mcp.providers.bridge import DEFAULT_SOCKET, DEFAULT_TOKEN_FILE, BridgeThingsProvider
from things3_mcp.providers.cache import CacheStore

APP_BUNDLE = Path.home() / "Applications" / "Things3 MCP Bridge.app"


def run_codesign_summary(bundle: Path) -> str:
    """Return a compact code signature summary, if available."""
    if not bundle.exists():
        return "bundle not found"
    if not shutil.which("codesign"):
        return "codesign not found"
    result = subprocess.run(["codesign", "-dv", str(bundle)], capture_output=True, text=True, check=False)  # noqa: S603, S607 - diagnostic fixed argv
    return (result.stderr or result.stdout or "no codesign output").strip()


def main() -> int:
    """Print bridge diagnostics as JSON."""
    parser = argparse.ArgumentParser(description="Diagnose the local Things3 MCP bridge")
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Ask the installed bridge over its socket to run a live snapshot and update the cache.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Client timeout in seconds for bridge requests. Default: 20.",
    )
    args = parser.parse_args()

    code_signature = run_codesign_summary(APP_BUNDLE)
    diagnostics = {
        "bridge_running": False,
        "bundle_path": str(APP_BUNDLE),
        "bundle_exists": APP_BUNDLE.exists(),
        "code_signature": code_signature,
        "code_signature_is_adhoc": "Signature=adhoc" in code_signature,
        "socket_path": str(DEFAULT_SOCKET),
        "socket_reachable": False,
        "token_file": str(DEFAULT_TOKEN_FILE),
        "token_file_exists": DEFAULT_TOKEN_FILE.exists(),
        "cache": CacheStore().status(),
        "authorization_status": None,
        "next_human_action": "If live reads fail, grant Full Disk Access to Things3 MCP Bridge.app and run uv run python scripts/check_bridge.py --snapshot.",
    }

    missing_snapshot_prereqs = []
    if not DEFAULT_SOCKET.exists():
        missing_snapshot_prereqs.append(f"bridge socket missing at {DEFAULT_SOCKET}")
    if not DEFAULT_TOKEN_FILE.exists():
        missing_snapshot_prereqs.append(f"bridge token missing at {DEFAULT_TOKEN_FILE}")

    if DEFAULT_SOCKET.exists() and DEFAULT_TOKEN_FILE.exists():
        provider = BridgeThingsProvider(timeout=args.timeout)
        try:
            diagnostics["health"] = provider.health()
            diagnostics["bridge_running"] = True
            diagnostics["socket_reachable"] = True
            diagnostics["authorization_status"] = "bridge reachable; run snapshot-once to verify live Things authorization"
        except Exception as exc:  # noqa: BLE001 - diagnostic command
            diagnostics["health_error"] = str(exc)

        if args.snapshot:
            try:
                diagnostics["snapshot"] = provider._request("POST", "/snapshot", json_body={})
                diagnostics["authorization_status"] = "live snapshot succeeded through the installed bridge"
                diagnostics["cache"] = CacheStore().status()
            except Exception as exc:  # noqa: BLE001 - diagnostic command
                diagnostics["snapshot_error"] = str(exc)
                diagnostics["authorization_status"] = "live snapshot failed; check snapshot_error and macOS Full Disk Access"
    elif args.snapshot:
        diagnostics["snapshot_error"] = "Cannot run live snapshot: " + "; ".join(missing_snapshot_prereqs)
        diagnostics["authorization_status"] = "live snapshot was not attempted because the installed bridge is not reachable"

    print(json.dumps(diagnostics, indent=2, sort_keys=True))
    if args.snapshot and diagnostics.get("snapshot_error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
