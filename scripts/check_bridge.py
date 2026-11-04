#!/usr/bin/env python3
"""Diagnose the local Things3 MCP bridge without touching Things data directly."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from things3_mcp.providers.base import read_context
from things3_mcp.providers.bridge import DEFAULT_TIMEOUT_SECONDS, BridgeThingsProvider
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
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Client timeout in seconds for bridge requests. Default: {DEFAULT_TIMEOUT_SECONDS:g}.",
    )
    args = parser.parse_args()

    code_signature = run_codesign_summary(APP_BUNDLE)
    diagnostics = {
        "bridge_running": False,
        "bundle_path": str(APP_BUNDLE),
        "bundle_exists": APP_BUNDLE.exists(),
        "code_signature": code_signature,
        "code_signature_is_adhoc": "Signature=adhoc" in code_signature,
        "socket_reachable": False,
        "cache": CacheStore().status(),
        "authorization_status": None,
        "next_human_action": "Use --snapshot to verify live access. If it fails, inspect the reported error and grant only the permission needed by that backend; see docs/bridge-build.md.",
    }

    try:
        provider = BridgeThingsProvider(timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001 - return configuration failures as diagnostics
        diagnostics["configuration_error"] = str(exc)
        print(json.dumps(diagnostics, indent=2, sort_keys=True))
        return 1

    diagnostics.update({"socket_path": str(provider.socket_path), "token_file": str(provider.token_file), "token_file_exists": provider.token_file.exists()})

    missing_snapshot_prereqs = []
    if not provider.socket_path.exists():
        missing_snapshot_prereqs.append(f"bridge socket missing at {provider.socket_path}")
    if not provider.token_file.exists():
        missing_snapshot_prereqs.append(f"bridge token missing at {provider.token_file}")

    if not missing_snapshot_prereqs:
        try:
            diagnostics["health"] = provider.health()
            diagnostics["bridge_running"] = True
            diagnostics["socket_reachable"] = True
            diagnostics["authorization_status"] = "bridge reachable; use --snapshot to verify live Things authorisation"
        except Exception as exc:  # noqa: BLE001 - diagnostic command
            diagnostics["health_error"] = str(exc)

        if args.snapshot:
            try:
                with read_context(require_live=True):
                    diagnostics["snapshot"] = provider._request("POST", "/snapshot", json_body={})
                diagnostics["authorization_status"] = "live snapshot succeeded through the installed bridge"
                diagnostics["cache"] = CacheStore().status()
            except Exception as exc:  # noqa: BLE001 - diagnostic command
                diagnostics["snapshot_error"] = str(exc)
                diagnostics["authorization_status"] = "live snapshot failed; inspect snapshot_error for the affected backend and required permission"
    elif args.snapshot:
        diagnostics["snapshot_error"] = "Cannot run live snapshot: " + "; ".join(missing_snapshot_prereqs)
        diagnostics["authorization_status"] = "live snapshot was not attempted because the installed bridge is not reachable"

    print(json.dumps(diagnostics, indent=2, sort_keys=True))
    if args.snapshot and diagnostics.get("snapshot_error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
