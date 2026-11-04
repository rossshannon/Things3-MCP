"""Bridge-side cache helpers."""

from __future__ import annotations

from typing import Any

from things3_mcp.providers.cache import CacheStore

SNAPSHOT_KEYS = ("inbox", "today", "upcoming", "anytime", "someday", "todos", "projects", "areas", "tags")


def write_snapshot(data: dict[str, Any], *, source: str = "live") -> dict[str, Any]:
    """Write a bridge snapshot and return it."""
    from .protocol import now_iso

    snapshot = {"version": 1, "source": source, "generated_at": now_iso(), "data": data}
    CacheStore().write_snapshot(snapshot)
    return snapshot


def cache_status() -> dict[str, Any]:
    """Return cache status."""
    return CacheStore().status()
