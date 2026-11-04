"""Provider facade for Things read access."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from .base import ProviderError, ThingsProvider, WriteThingsProvider, WriteUnsupported, live_read_required, read_context, record_read
from .bridge import BridgeThingsProvider
from .cache import CacheThingsProvider
from .direct import DirectThingsProvider

PROVIDER_ENV = "THINGS3_MCP_PROVIDER"
ALLOW_DIRECT_FALLBACK_ENV = "THINGS3_MCP_ALLOW_DIRECT_FALLBACK"


def _direct_fallback_allowed() -> bool:
    return os.environ.get(ALLOW_DIRECT_FALLBACK_ENV, "0") in {"1", "true", "TRUE", "yes", "YES"}


class UnavailableThingsProvider:
    """Provider that fails fast with a useful diagnostic."""

    source = "unavailable"

    def __init__(self, error: ProviderError | None = None) -> None:
        self.error = error or ProviderError(
            "bridge_unavailable",
            "No Things provider is available. Start/authorize the local bridge or create a cache snapshot.",
            authorization_hint="Start the bridge and inspect its status. Database access and Things Automation are separate capabilities.",
        )

    def _raise(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise self.error

    inbox = today = upcoming = anytime = someday = tasks = todos = search = projects = areas = tags = _raise

    def get(self, uuid: str) -> dict[str, Any] | None:  # noqa: ARG002
        raise self.error


class AutoThingsProvider:
    """Provider that tries bridge, then cache, then optional direct fallback.

    Reads use the cache as a graceful AFK fallback when the bridge is
    unavailable. The direct (in-process AppleScript / things-py) provider only
    enters the read chain when ``THINGS3_MCP_ALLOW_DIRECT_FALLBACK=1`` is set,
    because direct reads from a non-FDA-having host process trigger TCC prompts.

    Writes use one bridge attempt. Explicit direct mode remains available for
    installations that choose the legacy host-process Automation authority.
    """

    source = "auto"

    def __init__(
        self,
        providers: list[ThingsProvider] | None = None,
        *,
        write_providers: list[ThingsProvider] | None = None,
    ) -> None:
        self.providers = providers if providers is not None else _auto_provider_chain()
        self.write_providers = write_providers if write_providers is not None else _auto_write_chain()

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        first_error: ProviderError | None = None
        last_error: ProviderError | None = None
        for provider in self.providers:
            try:
                if live_read_required() and getattr(provider, "source", None) == "cache":
                    continue
                result = getattr(provider, method_name)(*args, **kwargs)
                if first_error:
                    record_read({"live_error": {"error_code": first_error.error_code}})
                return result
            except ProviderError as exc:
                if first_error is None:
                    first_error = exc
                last_error = exc
                continue
        if first_error:
            if last_error and last_error is not first_error and last_error.cache_status and not first_error.cache_status:
                first_error.cache_status = last_error.cache_status
            raise first_error
        raise ProviderError("bridge_unavailable", "No Things provider candidates are configured")

    def inbox(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._call("inbox", include_items=include_items)

    def today(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._call("today", include_items=include_items)

    def upcoming(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._call("upcoming", include_items=include_items)

    def anytime(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._call("anytime", include_items=include_items)

    def someday(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._call("someday", include_items=include_items)

    def tasks(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call("tasks", **kwargs)

    def todos(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call("todos", **kwargs)

    def search(self, query: str, include_items: bool = True) -> list[dict[str, Any]]:
        return self._call("search", query, include_items=include_items)

    def get(self, uuid: str) -> dict[str, Any] | None:
        return self._call("get", uuid)

    def projects(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call("projects", include_items=include_items, **kwargs)

    def areas(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call("areas", include_items=include_items, **kwargs)

    def tags(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        return self._call("tags", include_items=include_items, **kwargs)

    def trash(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._call("trash", include_items=include_items)

    def last(self, period: str, include_items: bool = True) -> list[dict[str, Any]]:
        return self._call("last", period, include_items=include_items)

    def read_live(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Perform an existing read with all cache fallback disabled."""
        if method_name not in {"inbox", "today", "upcoming", "anytime", "someday", "tasks", "todos", "search", "get", "projects", "areas", "tags", "trash", "last"}:
            raise ProviderError("invalid_read", "Unsupported live-read method")
        with read_context(require_live=True):
            return self._call(method_name, *args, **kwargs)

    # A mutation has exactly one authority; a failed response can hide success.
    def _call_write(self, method_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if not self.write_providers:
            raise ProviderError("bridge_unavailable", "No Things write provider is configured", outcome="failed")
        return getattr(self.write_providers[0], method_name)(*args, **kwargs)

    def add_task(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._call_write("add_task", params)

    def update_task(self, uuid: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._call_write("update_task", uuid, params)

    def add_project(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._call_write("add_project", params)

    def update_project(self, uuid: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._call_write("update_project", uuid, params)


def _auto_provider_chain() -> list[ThingsProvider]:
    """Default read chain: bridge → cache → optional direct.

    Direct reads from a non-FDA-having host trigger TCC prompts, so the direct
    provider is opt-in for reads via ``THINGS3_MCP_ALLOW_DIRECT_FALLBACK=1``.
    """
    providers: list[ThingsProvider] = [BridgeThingsProvider(), CacheThingsProvider()]
    if _direct_fallback_allowed():
        providers.append(DirectThingsProvider())
    return providers


def _auto_write_chain() -> list[ThingsProvider]:
    """Use the bridge for automatic writes; direct mode is explicit."""
    return [BridgeThingsProvider()]


def get_provider() -> ThingsProvider:
    """Return the configured Things provider.

    ``auto`` is deliberately conservative: it does not hit the protected Things
    DB directly unless ``THINGS3_MCP_ALLOW_DIRECT_FALLBACK=1`` is set.
    """
    provider_name = os.environ.get(PROVIDER_ENV, "auto").casefold()
    providers: dict[str, Callable[[], ThingsProvider]] = {
        "auto": AutoThingsProvider,
        "bridge": BridgeThingsProvider,
        "cache": CacheThingsProvider,
        "direct": DirectThingsProvider,
    }
    try:
        return providers[provider_name]()
    except KeyError as exc:
        raise ProviderError("provider_invalid", f"Unknown THINGS3_MCP_PROVIDER={provider_name!r}") from exc


__all__ = [
    "ALLOW_DIRECT_FALLBACK_ENV",
    "PROVIDER_ENV",
    "AutoThingsProvider",
    "BridgeThingsProvider",
    "CacheThingsProvider",
    "DirectThingsProvider",
    "ProviderError",
    "ThingsProvider",
    "UnavailableThingsProvider",
    "WriteThingsProvider",
    "WriteUnsupported",
    "get_provider",
]
