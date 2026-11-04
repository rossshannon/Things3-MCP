"""Passive capability observations; never request privacy grants or app launch."""

from __future__ import annotations

from typing import Any

from .cache import cache_status

AUTHORIZATION_HINT = "Inspect database access and Things Automation separately. No privacy grant has been inferred from cache availability."


def build_auth_status(*, last_live_error: dict[str, Any] | None = None, observations: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Report actual observations, leaving untested capabilities unknown."""
    capabilities = {name: dict((observations or {}).get(name, {"state": "unknown"})) for name in ("database", "automation")}
    status: dict[str, Any] = {
        "authorization_known": all(value["state"] in {"available", "denied"} for value in capabilities.values()),
        "authorized": None,
        "authorization_hint": AUTHORIZATION_HINT,
        "capabilities": capabilities,
        "app_process": "unknown",
        "cache_status": cache_status(),
        "message": "Capabilities describe the last observed operation, not a current permission guarantee.",
    }
    if last_live_error:
        status["last_live_error"] = {"error_code": last_live_error.get("error_code", "unknown")}
    return status
