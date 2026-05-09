"""Client provider for the local Things3 MCP bridge."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from .base import ProviderError
from .cache import APP_SUPPORT_DIR

DEFAULT_SOCKET = APP_SUPPORT_DIR / "bridge.sock"
DEFAULT_TOKEN_FILE = APP_SUPPORT_DIR / "bridge.token"
DEFAULT_TIMEOUT_SECONDS = 5.0


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
        self.base_url = base_url or os.environ.get("THINGS3_MCP_BRIDGE_URL") or "http://things3-mcp-bridge"

    def _token(self) -> str:
        try:
            return self.token_file.read_text().strip()
        except OSError as exc:
            raise ProviderError("bridge_unavailable", f"Bridge token is unavailable at {self.token_file}: {exc}") from exc

    def _client(self) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self._token()}"}
        if self.base_url.startswith("http://things3-mcp-bridge"):
            if not self.socket_path.exists():
                raise ProviderError("bridge_unavailable", f"Bridge socket is not available at {self.socket_path}")
            transport = httpx.HTTPTransport(uds=str(self.socket_path))
            return httpx.Client(transport=transport, base_url=self.base_url, headers=headers, timeout=self.timeout)
        return httpx.Client(base_url=self.base_url, headers=headers, timeout=self.timeout)

    def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> list[dict[str, Any]] | dict[str, Any] | None:
        try:
            with self._client() as client:
                response = client.request(method, path, json=json_body)
                response.raise_for_status()
                envelope = response.json()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - all transport failures become a provider diagnostic
            raise ProviderError("bridge_unavailable", f"Bridge request failed for {path}: {exc}") from exc

        if not envelope.get("ok"):
            raise ProviderError(
                envelope.get("error_code", "bridge_error"),
                envelope.get("message", "Bridge returned an error"),
                authorization_hint=envelope.get("authorization_hint"),
                cache_status=envelope.get("cache_status"),
            )
        return envelope.get("data")

    def health(self) -> dict[str, Any]:
        data = self._request("GET", "/health")
        return data if isinstance(data, dict) else {}

    def cache_status(self) -> dict[str, Any]:
        data = self._request("GET", "/cache/status")
        return data if isinstance(data, dict) else {}

    def _get_list(self, name: str, include_items: bool = True) -> list[dict[str, Any]]:
        data = self._request("GET", f"/things/{name}?include_items={str(include_items).lower()}")
        return data if isinstance(data, list) else []

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
        return data if isinstance(data, list) else []

    def todos(self, **kwargs: Any) -> list[dict[str, Any]]:
        data = self._request("POST", "/things/todos", json_body=kwargs)
        return data if isinstance(data, list) else []

    def search(self, query: str, include_items: bool = True) -> list[dict[str, Any]]:
        data = self._request("POST", "/things/search", json_body={"query": query, "include_items": include_items})
        return data if isinstance(data, list) else []

    def get(self, uuid: str) -> dict[str, Any] | None:
        data = self._request("GET", f"/things/get/{uuid}")
        return data if isinstance(data, dict) else None

    def projects(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        if kwargs:
            data = self._request("POST", "/things/projects", json_body={"include_items": include_items, **kwargs})
            return data if isinstance(data, list) else []
        return self._get_list("projects", include_items)

    def areas(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        if kwargs:
            data = self._request("POST", "/things/areas", json_body={"include_items": include_items, **kwargs})
            return data if isinstance(data, list) else []
        return self._get_list("areas", include_items)

    def tags(self, include_items: bool = False, **kwargs: Any) -> list[dict[str, Any]]:
        if kwargs:
            data = self._request("POST", "/things/tags", json_body={"include_items": include_items, **kwargs})
            return data if isinstance(data, list) else []
        return self._get_list("tags", include_items)

    def trash(self, include_items: bool = True) -> list[dict[str, Any]]:
        return self._get_list("trash", include_items)

    def last(self, period: str, include_items: bool = True) -> list[dict[str, Any]]:
        data = self._request("GET", f"/things/last/{period}?include_items={str(include_items).lower()}")
        return data if isinstance(data, list) else []

    # --- Write API --------------------------------------------------------

    def _write(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        data = self._request(method, path, json_body=body)
        return data if isinstance(data, dict) else {}

    def add_task(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._write("POST", "/things/todo", params)

    def update_task(self, uuid: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._write("PATCH", f"/things/todo/{uuid}", params)

    def add_project(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._write("POST", "/things/project", params)

    def update_project(self, uuid: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._write("PATCH", f"/things/project/{uuid}", params)
