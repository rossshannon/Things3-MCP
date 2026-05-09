"""Direct things-py provider.

This preserves historical behaviour and may touch the macOS-protected Things group
container from the current process. It is intentionally opt-in for auto fallback.
"""

from __future__ import annotations

from typing import Any

import things


class DirectThingsProvider:
    """Thin adapter around the ``things-py`` module."""

    source = "direct"

    def inbox(self, include_items: bool = True) -> list[dict[str, Any]]:
        return things.inbox(include_items=include_items)

    def today(self, include_items: bool = True) -> list[dict[str, Any]]:
        """Return Today, preserving the server's historical None-safe fallback."""
        try:
            return things.today(include_items=include_items)
        except TypeError as exc:
            if "'<' not supported between instances of 'NoneType' and 'str'" not in str(exc):
                raise
            result = [
                *things.tasks(start_date=True, start="Anytime", index="todayIndex", status="incomplete", include_items=include_items),
                *things.tasks(start_date="past", start="Someday", index="todayIndex", status="incomplete", include_items=include_items),
                *things.tasks(start_date=False, deadline="past", deadline_suppressed=False, status="incomplete", include_items=include_items),
            ]
            result.sort(key=lambda task: (task.get("today_index") or 999999, task.get("start_date") or ""))
            return result

    def upcoming(self, include_items: bool = True) -> list[dict[str, Any]]:
        return things.upcoming(include_items=include_items)

    def anytime(self, include_items: bool = True) -> list[dict[str, Any]]:
        return things.anytime(include_items=include_items)

    def someday(self, include_items: bool = True) -> list[dict[str, Any]]:
        return things.someday(include_items=include_items)

    def tasks(self, **kwargs: Any) -> list[dict[str, Any]]:
        return things.tasks(**kwargs)

    def todos(self, **kwargs: Any) -> list[dict[str, Any]]:
        return things.todos(**kwargs)

    def search(self, query: str, include_items: bool = True) -> list[dict[str, Any]]:
        return things.search(query, include_items=include_items)

    def get(self, uuid: str) -> dict[str, Any] | None:
        return things.get(uuid)

    def projects(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        projects = things.projects(**kwargs)
        if include_items:
            for project in projects:
                project.setdefault("items", things.todos(project=project.get("uuid"), include_items=True))
        return projects

    def areas(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        areas = things.areas(**kwargs)
        if include_items:
            for area in areas:
                area.setdefault("projects", things.projects(area=area.get("uuid")))
                area.setdefault("items", things.todos(area=area.get("uuid"), include_items=True))
        return areas

    def tags(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        tags = things.tags(**kwargs)
        if include_items:
            for tag in tags:
                tag.setdefault("items", things.todos(tag=tag.get("title"), include_items=True))
        return tags

    def trash(self, include_items: bool = True) -> list[dict[str, Any]]:
        return things.trash(include_items=include_items)

    def last(self, period: str, include_items: bool = True) -> list[dict[str, Any]]:
        return things.last(period, include_items=include_items)

    # --- Write API ---------------------------------------------------------
    # These delegate to the legacy applescript_bridge from inside the MCP
    # server process. They preserve historical behaviour for users who haven't
    # set up the signed bridge — useful as a fallback when the bridge is down,
    # but suffers the original transient-runtime TCC issues that motivated the
    # bridge work in the first place.

    def _coerce(self, result: Any, op_desc: str) -> dict[str, Any]:
        from .base import ProviderError

        if isinstance(result, bool):
            if result:
                return {"ok": True}
            raise ProviderError("applescript_failed", f"AppleScript reported failure on {op_desc}")
        if isinstance(result, str):
            stripped = result.strip()
            lowered = stripped.lower()
            if lowered == "true":
                return {"ok": True}
            if any(marker in lowered for marker in ("error:", "applescript error", "⚠️", "failed", "exception")):
                raise ProviderError("applescript_failed", f"AppleScript error on {op_desc}: {stripped}")
            return {"ok": True, "id": stripped}
        raise ProviderError("applescript_failed", f"Unexpected AppleScript result type on {op_desc}: {type(result).__name__}")

    def add_task(self, params: dict[str, Any]) -> dict[str, Any]:
        from things3_mcp import applescript_bridge as ab

        return self._coerce(ab.add_todo(**params), "create todo")

    def update_task(self, uuid: str, params: dict[str, Any]) -> dict[str, Any]:
        from things3_mcp import applescript_bridge as ab

        return self._coerce(ab.update_todo(id=uuid, **params), f"update todo {uuid}")

    def add_project(self, params: dict[str, Any]) -> dict[str, Any]:
        from things3_mcp import applescript_bridge as ab

        return self._coerce(ab.add_project(**params), "create project")

    def update_project(self, uuid: str, params: dict[str, Any]) -> dict[str, Any]:
        from things3_mcp import applescript_bridge as ab

        return self._coerce(ab.update_project(id=uuid, **params), f"update project {uuid}")
