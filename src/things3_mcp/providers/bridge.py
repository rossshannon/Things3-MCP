"""Client provider for the local Things3 MCP bridge."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx

from .base import ProviderError, live_read_required, read_context, record_read
from .cache import APP_SUPPORT_DIR

DEFAULT_SOCKET = APP_SUPPORT_DIR / "bridge.sock"
DEFAULT_TOKEN_FILE = APP_SUPPORT_DIR / "bridge.token"
DEFAULT_TIMEOUT_SECONDS = 35.0
LOCAL_BASE_URL = "http://things3-mcp-bridge"


class BridgeThingsProvider:
    """Provider that talks to the local signed bridge service."""

    source = "bridge"

    def __init__(
        self,
        *,
        socket_path: Path | None = None,
        token_file: Path | None = None,
        timeout: float | None = None,
        base_url: str | None = None,
    ) -> None:
        self.socket_path = socket_path or Path(os.environ.get("THINGS3_MCP_BRIDGE_SOCKET", DEFAULT_SOCKET)).expanduser()
        self.token_file = token_file or Path(os.environ.get("THINGS3_MCP_BRIDGE_TOKEN_FILE", DEFAULT_TOKEN_FILE)).expanduser()
        self.timeout = timeout if timeout is not None else float(os.environ.get("THINGS3_MCP_BRIDGE_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
        self.base_url = base_url or os.environ.get("THINGS3_MCP_BRIDGE_URL") or LOCAL_BASE_URL
        if self.base_url != LOCAL_BASE_URL:
            raise ProviderError("bridge_url_invalid", "The bridge requires its local Unix socket; HTTP bridge URLs are unsupported", outcome="failed")
        if not math.isfinite(self.timeout) or self.timeout <= 30:
            raise ProviderError("bridge_timeout_invalid", "The client timeout must exceed the bridge worker's 30-second deadline", outcome="failed")

    def _token(self) -> str:
        try:
            return self.token_file.read_text().strip()
        except OSError as exc:
            raise ProviderError("bridge_unavailable", f"Bridge token is unavailable at {self.token_file}: {exc}") from exc

    def _client(self) -> httpx.Client:
        # Validate before reading credentials, including after object mutation.
        if self.base_url != LOCAL_BASE_URL:
            raise ProviderError("bridge_url_invalid", "The bridge requires its local Unix socket", outcome="failed")
        if not self.socket_path.exists():
            raise ProviderError("bridge_unavailable", "The local bridge socket is unavailable", outcome="failed")
        transport = httpx.HTTPTransport(uds=str(self.socket_path))
        return httpx.Client(transport=transport, base_url=LOCAL_BASE_URL, headers={"Authorization": f"Bearer {self._token()}"}, timeout=self.timeout, follow_redirects=False)

    def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None, mutation: bool = False) -> Any:
        correlation_id = str(uuid4()) if mutation else None
        dispatched = False
        envelope: Any = None
        try:
            with self._client() as client:
                headers = {"X-Correlation-ID": correlation_id} if correlation_id else {}
                if live_read_required() and not mutation:
                    headers["X-Require-Live"] = "true"
                dispatched = True
                response = client.request(method, path, json=json_body, headers=headers)
                envelope = response.json()
                self._validate_envelope(envelope, mutation=mutation)
        except ProviderError as exc:
            if mutation:
                exc.correlation_id = correlation_id
                if dispatched:
                    exc.outcome = "outcome_unknown"
                    exc.error_code = "outcome_unknown"
                    if isinstance(envelope, dict) and isinstance(envelope.get("operation_id"), str):
                        exc.operation_id = envelope["operation_id"]
                else:
                    exc.outcome = "failed"
            raise
        except Exception as exc:  # noqa: BLE001 - transport/decoding failure must preserve uncertainty
            unknown = mutation and dispatched
            raise ProviderError(
                "outcome_unknown" if unknown else "bridge_unavailable",
                "The bridge response was unavailable or invalid. The mutation may have completed." if unknown else "The local bridge request failed",
                outcome="outcome_unknown" if unknown else ("failed" if mutation else None),
                correlation_id=correlation_id,
            ) from exc

        if mutation:
            outcome = envelope.get("outcome")
            operation_id = envelope.get("operation_id")
            returned_correlation = envelope.get("correlation_id")
            if returned_correlation is not None and returned_correlation != correlation_id:
                raise ProviderError("outcome_unknown", "Bridge correlation did not match the request", outcome="outcome_unknown", operation_id=operation_id, correlation_id=correlation_id)
            if outcome is None or (envelope["ok"] and outcome != "succeeded"):
                raise ProviderError("outcome_unknown", "The bridge did not confirm a mutation outcome", outcome="outcome_unknown", operation_id=operation_id, correlation_id=correlation_id)
        if not envelope["ok"]:
            raise ProviderError(
                envelope["error_code"],
                envelope["message"],
                authorization_hint=envelope.get("authorization_hint"),
                cache_status=envelope.get("cache_status"),
                outcome=envelope.get("outcome"),
                operation_id=envelope.get("operation_id"),
                correlation_id=correlation_id or envelope.get("correlation_id"),
            )
        if mutation:
            data = dict(envelope["data"])
            data.update({key: envelope[key] for key in ("operation_id", "outcome") if key in envelope})
            data["correlation_id"] = correlation_id
            return data
        source = envelope.get("source", "unknown")
        if live_read_required() and source not in {"live", "sqlite", "apple_events", "direct"}:
            raise ProviderError("live_read_required", "The bridge did not confirm a live read")
        record_read({key: envelope[key] for key in ("source", "snapshot_source", "generated_at", "cache_age_seconds", "live_error", "cache_status") if key in envelope} | {"source": source})
        return envelope["data"]

    @staticmethod
    def _validate_envelope(envelope: Any, *, mutation: bool) -> None:
        valid = isinstance(envelope, dict) and type(envelope.get("ok")) is bool
        if valid and "protocol_version" in envelope:
            valid = type(envelope["protocol_version"]) is int and envelope["protocol_version"] == 1
        if valid:
            for key in ("source", "snapshot_source", "generated_at", "error_code", "message", "authorization_hint", "operation_id", "correlation_id"):
                if key in envelope and not isinstance(envelope[key], str):
                    valid = False
            for key in ("live_error", "cache_status"):
                if key in envelope and not isinstance(envelope[key], dict):
                    valid = False
            if "cache_age_seconds" in envelope:
                age = envelope["cache_age_seconds"]
                valid = valid and type(age) in {int, float} and math.isfinite(age) and age >= 0
            if "outcome" in envelope and (not isinstance(envelope["outcome"], str) or envelope["outcome"] not in {"succeeded", "failed", "not_started", "outcome_unknown"}):
                valid = False
            if envelope["ok"]:
                valid = valid and "data" in envelope and (envelope["data"] is None or isinstance(envelope["data"], list | dict) or type(envelope["data"]) is int)
                if mutation:
                    valid = valid and isinstance(envelope.get("data"), dict)
            else:
                valid = valid and isinstance(envelope.get("error_code"), str) and isinstance(envelope.get("message"), str)
        if not valid:
            raise ProviderError("bridge_protocol_error", "The bridge returned an invalid or unsupported envelope")

    def read_live(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Perform an existing read while explicitly forbidding cache fallback."""
        if method_name not in {"inbox", "today", "upcoming", "anytime", "someday", "tasks", "todos", "search", "get", "projects", "areas", "tags", "trash", "last"}:
            raise ProviderError("invalid_read", "Unsupported live-read method")
        with read_context(require_live=True):
            return getattr(self, method_name)(*args, **kwargs)

    def status(self) -> dict[str, Any]:
        return self._dict_data(self._request("GET", "/status"))

    def operation(self, operation_id: str) -> dict[str, Any]:
        return self._dict_data(self._request("GET", f"/operations/{quote(operation_id, safe='')}"))

    def operations(self, correlation_id: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        query: dict[str, str | int] = {"limit": limit}
        if correlation_id is not None:
            query["correlation_id"] = correlation_id
        return self._list_data(self._request("GET", f"/operations?{urlencode(query)}"))

    @staticmethod
    def _list_data(data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise ProviderError("bridge_protocol_error", "Expected a list of items from the bridge")
        return data

    @staticmethod
    def _dict_data(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ProviderError("bridge_protocol_error", "Expected an object from the bridge")
        return data

    @classmethod
    def _filtered_data(cls, data: Any, *, count_only: bool = False) -> Any:
        if count_only:
            if type(data) is not int or data < 0:
                raise ProviderError("bridge_protocol_error", "Expected an item count from the bridge")
            return data
        return cls._list_data(data)

    def health(self) -> dict[str, Any]:
        data = self._request("GET", "/health")
        return self._dict_data(data)

    def cache_status(self) -> dict[str, Any]:
        data = self._request("GET", "/cache/status")
        return self._dict_data(data)

    def _get_list(self, name: str, include_items: bool = True) -> list[dict[str, Any]]:
        data = self._request("GET", f"/things/{name}?include_items={str(include_items).lower()}")
        return self._list_data(data)

    def inbox(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._get_list("inbox", include_items)

    def today(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._get_list("today", include_items)

    def upcoming(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._get_list("upcoming", include_items)

    def anytime(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._get_list("anytime", include_items)

    def someday(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._get_list("someday", include_items)

    def tasks(self, **kwargs: Any) -> list[dict[str, Any]]:
        data = self._request("POST", "/things/tasks", json_body=kwargs)
        return self._filtered_data(data, count_only=bool(kwargs.get("count_only")))

    def todos(self, **kwargs: Any) -> list[dict[str, Any]]:
        data = self._request("POST", "/things/todos", json_body=kwargs)
        return self._filtered_data(data, count_only=bool(kwargs.get("count_only")))

    def search(self, query: str, include_items: bool = True) -> list[dict[str, Any]]:
        data = self._request("POST", "/things/search", json_body={"query": query, "include_items": include_items})
        return self._list_data(data)

    def get(self, uuid: str) -> dict[str, Any] | None:
        data = self._request("GET", f"/things/get/{quote(uuid, safe='')}")
        if data is not None and not isinstance(data, dict):
            raise ProviderError("bridge_protocol_error", "Expected an item or null from the bridge")
        return data

    def projects(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        if kwargs:
            data = self._request("POST", "/things/projects", json_body={"include_items": include_items, **kwargs})
            return self._filtered_data(data, count_only=bool(kwargs.get("count_only")))
        return self._get_list("projects", include_items)

    def areas(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        if kwargs:
            data = self._request("POST", "/things/areas", json_body={"include_items": include_items, **kwargs})
            return self._filtered_data(data, count_only=bool(kwargs.get("count_only")))
        return self._get_list("areas", include_items)

    def tags(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        if kwargs:
            data = self._request("POST", "/things/tags", json_body={"include_items": include_items, **kwargs})
            if kwargs.get("titles_only"):
                if not isinstance(data, list) or any(not isinstance(item, str) for item in data):
                    raise ProviderError("bridge_protocol_error", "Expected tag titles from the bridge")
                return data
            return self._list_data(data)
        return self._get_list("tags", include_items)

    def trash(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._get_list("trash", include_items)

    def last(self, period: str, include_items: bool = True) -> list[dict[str, Any]]:
        data = self._request("GET", f"/things/last/{period}?include_items={str(include_items).lower()}")
        return self._list_data(data)

    # --- Write API --------------------------------------------------------

    def _write(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        data = self._request(method, path, json_body=body, mutation=True)
        return self._dict_data(data)

    def add_task(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._write("POST", "/things/todo", params)

    def update_task(self, uuid: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._write("PATCH", f"/things/todo/{quote(uuid, safe='')}", params)

    def add_project(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._write("POST", "/things/project", params)

    def update_project(self, uuid: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._write("PATCH", f"/things/project/{quote(uuid, safe='')}", params)
