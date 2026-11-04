"""Additive response envelopes shared by local adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

PROTOCOL_VERSION = 1
OUTCOMES = frozenset({"not_started", "succeeded", "failed", "outcome_unknown"})


def now_iso() -> str:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC).isoformat()


def ok_envelope(data: Any, *, source: str = "live", generated_at: str | None = None, cache_age_seconds: int | None = None, **metadata: Any) -> dict[str, Any]:
    """Build a successful response without changing the adapter's data shape."""
    envelope = {"ok": True, "protocol_version": PROTOCOL_VERSION, "source": source, "generated_at": generated_at if source == "cache" else generated_at or now_iso(), "data": data, **metadata}
    if cache_age_seconds is not None:
        envelope["cache_age_seconds"] = cache_age_seconds
    return envelope


def error_envelope(error_code: str, message: str, *, authorization_hint: str | None = None, cache_status: dict[str, Any] | None = None, **metadata: Any) -> dict[str, Any]:
    """Build a sanitised error response."""
    envelope = {"ok": False, "protocol_version": PROTOCOL_VERSION, "error_code": error_code, "message": message, **metadata}
    if authorization_hint:
        envelope["authorization_hint"] = authorization_hint
    if cache_status is not None:
        envelope["cache_status"] = cache_status
    return envelope
