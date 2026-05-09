"""Authorization status helpers for the Things bridge.

These helpers intentionally infer status from safe bridge/cache diagnostics rather
than editing or inspecting macOS TCC databases.
"""

from __future__ import annotations

from typing import Any

from .cache import cache_status

AUTHORIZATION_HINT = "Grant Full Disk Access to Things3 MCP Bridge.app in System Settings, then run Things3-MCP-bridge --snapshot-once."


def build_auth_status(*, last_live_error: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a human-readable authorization status payload."""
    status: dict[str, Any] = {
        "authorization_known": False,
        "authorization_hint": AUTHORIZATION_HINT,
        "cache_status": cache_status(),
    }
    if last_live_error:
        status["last_live_error"] = last_live_error
        status["authorized"] = False
    elif status["cache_status"].get("available"):
        status["authorized"] = None
        status["message"] = "Cache is available; live bridge authorization has not been verified in this process."
    else:
        status["authorized"] = None
        status["message"] = "No live read has been attempted and no cache is available."
    return status
