"""Read-only cache provider for Things snapshots."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import ProviderError

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "Things3-MCP"
DEFAULT_CACHE_DIR = APP_SUPPORT_DIR / "cache"
DEFAULT_CACHE_FILE = DEFAULT_CACHE_DIR / "latest.json"


def cache_file_from_env() -> Path:
    """Return the configured latest cache file path."""
    return Path(os.environ.get("THINGS3_MCP_CACHE_FILE", DEFAULT_CACHE_FILE)).expanduser()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
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
        """Read the latest cache snapshot."""
        if not self.path.exists():
            raise ProviderError("cache_missing", f"Things cache is missing at {self.path}", cache_status=self.status())
        try:
            return json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise ProviderError("cache_unreadable", f"Things cache is not valid JSON: {exc}", cache_status=self.status()) from exc
        except OSError as exc:
            raise ProviderError("cache_unreadable", f"Things cache could not be read: {exc}", cache_status=self.status()) from exc

    def write_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Atomically write a cache snapshot."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        payload = json.dumps(snapshot, indent=2, sort_keys=True)
        with tmp_path.open("w") as handle:
            os.chmod(tmp_path, 0o600)
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(self.path)
        os.chmod(self.path, 0o600)

    def status(self) -> dict[str, Any]:
        """Return lightweight cache availability metadata."""
        available = self.path.exists()
        status: dict[str, Any] = {"available": available, "path": str(self.path)}
        if not available:
            return status
        try:
            snapshot = json.loads(self.path.read_text())
        except Exception as exc:  # noqa: BLE001 - diagnostic path only
            status.update({"readable": False, "error": str(exc)})
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
        snapshot = self.store.read_snapshot()
        return snapshot.get("data", {})

    def _list(self, key: str) -> list[dict[str, Any]]:
        value = self._data().get(key, [])
        if not isinstance(value, list):
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
        for key in ("inbox", "today", "upcoming", "anytime", "someday", "todos", "projects", "areas", "tags"):
            for item in self._data().get(key, []):
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
