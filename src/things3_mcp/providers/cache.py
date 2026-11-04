"""Read-only cache provider for Things snapshots."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from clawbridge.runtime import RuntimeSafetyError, atomic_write, private_directory, private_open

from .base import ProviderError, live_read_required, record_read

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "Things3-MCP"
DEFAULT_CACHE_DIR = APP_SUPPORT_DIR / "cache"
DEFAULT_CACHE_FILE = DEFAULT_CACHE_DIR / "latest.json"
MAX_CACHE_BYTES = 64 * 1024 * 1024


def cache_file_from_env() -> Path:
    """Return the configured latest cache file path."""
    return Path(os.environ.get("THINGS3_MCP_CACHE_FILE", DEFAULT_CACHE_FILE)).expanduser()


def _parse_datetime(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class CacheStore:
    """JSON snapshot cache reader/writer."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or cache_file_from_env()

    def read_snapshot(self) -> dict[str, Any]:
        """Read a bounded, private regular file without following symlinks."""
        try:
            if any(parent.is_symlink() for parent in self.path.absolute().parents):
                raise RuntimeSafetyError("Cache paths must not contain symlinks")
            fd = private_open(self.path, os.O_RDONLY)
            with os.fdopen(fd, "rb") as source:
                raw = source.read(MAX_CACHE_BYTES + 1)
            if len(raw) > MAX_CACHE_BYTES:
                raise ValueError("Cache exceeds its size limit")
            snapshot = json.loads(raw)
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("data"), dict):
                raise ProviderError("cache_unreadable", "The cache does not contain a valid snapshot object")
            return snapshot
        except FileNotFoundError as exc:
            raise ProviderError("cache_missing", "Things cache is missing", cache_status={"available": False}) from exc
        except (OSError, ValueError) as exc:
            raise ProviderError("cache_unreadable", "Things cache is invalid, unsafe, too large, or unreadable", cache_status={"available": True, "readable": False}) from exc

    def write_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Atomically replace a snapshot using a unique mode-0600 file."""
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("data"), dict):
            raise ProviderError("cache_unwritable", "The snapshot must contain a data object")
        payload = (json.dumps(snapshot, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if len(payload) > MAX_CACHE_BYTES:
            raise ProviderError("cache_unwritable", "The snapshot exceeds the cache size limit")
        private_directory(self.path.parent)
        atomic_write(self.path, payload)

    def status(self) -> dict[str, Any]:
        """Return lightweight cache availability metadata."""
        available = self.path.exists() or self.path.is_symlink()
        status: dict[str, Any] = {"available": available, "path": str(self.path)}
        if not available:
            return status
        try:
            snapshot = self.read_snapshot()
        except ProviderError as exc:
            status.update({"available": exc.error_code != "cache_missing", "readable": False, "error_code": exc.error_code})
            return status
        generated_at = snapshot.get("generated_at")
        generated = _parse_datetime(generated_at)
        status.update(
            {
                "readable": True,
                "generated_at": generated_at,
                "source": snapshot.get("source"),
            }
        )
        if generated:
            now = datetime.now(generated.tzinfo or UTC)
            status["age_seconds"] = max(0, int((now - generated).total_seconds()))
        return status


class CacheThingsProvider:
    """Provider that serves read data from ``latest.json`` only."""

    source = "cache"

    def __init__(self, store: CacheStore | None = None) -> None:
        self.store = store or CacheStore()

    def _data(self) -> dict[str, Any]:
        if live_read_required():
            raise ProviderError("live_read_required", "A cache cannot satisfy a live read")
        snapshot = self.store.read_snapshot()
        generated = _parse_datetime(snapshot.get("generated_at"))
        age = max(0, int((datetime.now(generated.tzinfo or UTC) - generated).total_seconds())) if generated else None
        snapshot_source = snapshot.get("source")
        record_read(
            {"source": "cache", "snapshot_source": snapshot_source if isinstance(snapshot_source, str) else "unknown", "generated_at": snapshot.get("generated_at") if generated else None, "cache_age_seconds": age}
        )
        return snapshot.get("data", {})

    def _list(self, key: str) -> list[dict[str, Any]]:
        value = self._data().get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ProviderError("cache_unreadable", f"Cache key {key!r} is not a list", cache_status=self.store.status())
        return value

    def _filter_list(self, key: str, **kwargs: Any) -> list[dict[str, Any]]:
        include_items = kwargs.pop("include_items", None)
        count_only = kwargs.pop("count_only", False)
        result = list(self._list(key))
        for field, expected in kwargs.items():
            if expected is None:
                continue
            if field == "tag":
                result = [item for item in result if _item_has_tag(item, expected)]
            elif field in {"uuid", "area", "project", "heading", "status", "type", "start", "deadline", "start_date", "stop_date", "trashed"}:
                result = [item for item in result if item.get(field) == expected]
            else:
                raise ProviderError("cache_unsupported", f"Cache filtering by {field!r} is not supported", cache_status=self.store.status())
        if include_items is False:
            result = [_strip_nested_items(item) for item in result]
        if count_only:
            return len(result)
        return result

    def inbox(self, include_items: bool = True) -> list[dict[str, Any]]:  # noqa: ARG002
        return self._list("inbox")

    def today(self, include_items: bool = True) -> list[dict[str, Any]]:  # noqa: ARG002
        return self._list("today")

    def upcoming(self, include_items: bool = True) -> list[dict[str, Any]]:  # noqa: ARG002
        return self._list("upcoming")

    def anytime(self, include_items: bool = True) -> list[dict[str, Any]]:  # noqa: ARG002
        return self._list("anytime")

    def someday(self, include_items: bool = True) -> list[dict[str, Any]]:  # noqa: ARG002
        return self._list("someday")

    def tasks(self, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ARG002
        return self._filter_list("todos", **kwargs)

    def todos(self, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ARG002
        return self._filter_list("todos", **kwargs)

    def search(self, query: str, include_items: bool = True) -> list[dict[str, Any]]:  # noqa: ARG002
        needle = query.casefold()
        candidates = self._list("todos") or [*self._list("inbox"), *self._list("today"), *self._list("upcoming"), *self._list("anytime"), *self._list("someday")]
        return [item for item in candidates if needle in str(item.get("title", "")).casefold() or needle in str(item.get("notes", "")).casefold()]

    def get(self, uuid: str) -> dict[str, Any] | None:
        data = self._data()
        for key in ("inbox", "today", "upcoming", "anytime", "someday", "todos", "projects", "areas", "tags"):
            items = data.get(key, [])
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise ProviderError("cache_unreadable", "The cache contains invalid items")
            for item in items:
                if item.get("uuid") == uuid:
                    return item
        return None

    def projects(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        return self._filter_list("projects", include_items=include_items, **kwargs)

    def areas(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        return self._filter_list("areas", include_items=include_items, **kwargs)

    def tags(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        return self._filter_list("tags", include_items=include_items, **kwargs)

    def trash(self, include_items: bool = True) -> list[dict[str, Any]]:  # noqa: ARG002
        # The cache snapshot doesn't currently include trashed items. Raise so
        # AutoThingsProvider falls through to the next provider rather than
        # returning a misleading empty success.
        from .base import ProviderError

        raise ProviderError(
            "cache_miss",
            "Cache snapshot does not include trashed items; cannot satisfy trash() from cache.",
        )

    def last(self, period: str, include_items: bool = True) -> list[dict[str, Any]]:  # noqa: ARG002
        # ``last(period)`` requires a creation-date scan that the snapshot
        # doesn't materialise. Raise so AutoThingsProvider treats it as a cache
        # miss and falls through to the next provider.
        del period
        from .base import ProviderError

        raise ProviderError(
            "cache_miss",
            "Cache snapshot cannot satisfy last(period) — no creation-date index materialised.",
        )

    # --- Write API ---------------------------------------------------------
    # The cache is read-only by design. Surface a clear error so AutoThings
    # write callers don't silently lose mutations into a stale snapshot.

    def add_task(self, _params: dict[str, Any]) -> dict[str, Any]:
        from .base import WriteUnsupported

        raise WriteUnsupported("cache", "add_task")

    def update_task(self, _uuid: str, _params: dict[str, Any]) -> dict[str, Any]:
        from .base import WriteUnsupported

        raise WriteUnsupported("cache", "update_task")

    def add_project(self, _params: dict[str, Any]) -> dict[str, Any]:
        from .base import WriteUnsupported

        raise WriteUnsupported("cache", "add_project")

    def update_project(self, _uuid: str, _params: dict[str, Any]) -> dict[str, Any]:
        from .base import WriteUnsupported

        raise WriteUnsupported("cache", "update_project")


def _strip_nested_items(item: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy without nested item collections."""
    stripped = dict(item)
    for nested_key in ("items", "projects", "checklist"):
        stripped.pop(nested_key, None)
    return stripped


def _item_has_tag(item: dict[str, Any], expected: Any) -> bool:
    """Return whether a cached item carries a tag title/name."""
    if expected is True:
        return bool(item.get("tags") or item.get("tag_titles") or item.get("tag_names"))
    if expected is False:
        return not bool(item.get("tags") or item.get("tag_titles") or item.get("tag_names"))
    candidates: list[str] = []
    for key in ("tags", "tag_titles"):
        value = item.get(key)
        if isinstance(value, list):
            candidates.extend(str(part) for part in value)
    tag_names = item.get("tag_names")
    if isinstance(tag_names, str):
        candidates.extend(part.strip() for part in tag_names.split(","))
    return str(expected) in candidates
