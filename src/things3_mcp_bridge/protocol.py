"""Response envelopes for the local Things bridge."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def now_iso() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC).isoformat()


def ok_envelope(data: Any, *, source: str = "live", generated_at: str | None = None, cache_age_seconds: int | None = None) -> dict[str, Any]:
    """Build a successful bridge response envelope."""
    envelope: dict[str, Any] = {
        "ok": True,
        "source": source,
        "generated_at": generated_at or now_iso(),
        "data": data,
    }
    if cache_age_seconds is not None:
        envelope["cache_age_seconds"] = cache_age_seconds
    return envelope


def error_envelope(
    error_code: str,
    message: str,
    *,
    authorization_hint: str | None = None,
    cache_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an error bridge response envelope."""
    envelope: dict[str, Any] = {"ok": False, "error_code": error_code, "message": message}
    if authorization_hint:
        envelope["authorization_hint"] = authorization_hint
    if cache_status is not None:
        envelope["cache_status"] = cache_status
    return envelope
