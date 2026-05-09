"""Provider protocol and shared errors for Things read access."""

from __future__ import annotations

from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Raised when a Things provider cannot satisfy a read request."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        authorization_hint: str | None = None,
        cache_status: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.authorization_hint = authorization_hint
        self.cache_status = cache_status or {}

    def to_dict(self) -> dict[str, Any]:
        """Return an MCP-safe diagnostic payload."""
        payload: dict[str, Any] = {
            "ok": False,
            "error_code": self.error_code,
            "message": self.message,
        }
        if self.authorization_hint:
            payload["authorization_hint"] = self.authorization_hint
        if self.cache_status:
            payload["cache_status"] = self.cache_status
        return payload

    def __str__(self) -> str:
        """Return a concise human-readable error."""
        bits = [f"Things provider error ({self.error_code}): {self.message}"]
        if self.authorization_hint:
            bits.append(f"Authorization hint: {self.authorization_hint}")
        if self.cache_status:
            bits.append(f"Cache status: {self.cache_status}")
        return "\n".join(bits)


class ThingsProvider(Protocol):
    """Read facade used by the MCP server."""

    def inbox(self, include_items: bool = True) -> list[dict[str, Any]]: ...
    def today(self, include_items: bool = True) -> list[dict[str, Any]]: ...
    def upcoming(self, include_items: bool = True) -> list[dict[str, Any]]: ...
    def anytime(self, include_items: bool = True) -> list[dict[str, Any]]: ...
    def someday(self, include_items: bool = True) -> list[dict[str, Any]]: ...
    def tasks(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def todos(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def search(self, query: str, include_items: bool = True) -> list[dict[str, Any]]: ...
    def get(self, uuid: str) -> dict[str, Any] | None: ...
    def projects(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]: ...
    def areas(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]: ...
    def tags(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]: ...
    def trash(self, include_items: bool = True) -> list[dict[str, Any]]: ...
    def last(self, period: str, include_items: bool = True) -> list[dict[str, Any]]: ...


class WriteThingsProvider(Protocol):
    """Write facade used by the MCP server.

    Separate from the read protocol so providers like cache and direct can opt
    out: the cache provider has no way to persist writes durably, and the
    direct provider's writes still go through the MCP-server-process AppleScript
    path (which has the original transient-runtime TCC issues we built the
    bridge to solve). Use ``WriteUnsupported`` for providers that cannot satisfy
    a write request — auto-providers should fail-fast on writes rather than
    silently downgrade to a stale cache.
    """

    def add_task(self, params: dict[str, Any]) -> dict[str, Any]: ...
    def update_task(self, uuid: str, params: dict[str, Any]) -> dict[str, Any]: ...
    def add_project(self, params: dict[str, Any]) -> dict[str, Any]: ...
    def update_project(self, uuid: str, params: dict[str, Any]) -> dict[str, Any]: ...


class WriteUnsupportedError(ProviderError):
    """Raised by providers that cannot satisfy write requests (e.g. cache)."""

    def __init__(self, provider_name: str, operation: str) -> None:
        super().__init__(
            "writes_unsupported",
            f"Provider '{provider_name}' cannot satisfy write operation '{operation}'. Writes require a live bridge or direct AppleScript path.",
        )


# Backwards-compatible alias for callers that imported the older name.
WriteUnsupported = WriteUnsupportedError
