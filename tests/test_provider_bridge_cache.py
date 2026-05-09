from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from things3_mcp.providers import AutoThingsProvider, ProviderError, get_provider
from things3_mcp.providers.bridge import BridgeThingsProvider
from things3_mcp.providers.cache import CacheStore, CacheThingsProvider
from things3_mcp_bridge import db_reader
from things3_mcp_bridge.server import run_worker


class FailingProvider:
    def inbox(self, include_items: bool = True):  # noqa: ARG002
        raise ProviderError("bridge_unavailable", "not running")


class FakeProvider:
    def inbox(self, include_items: bool = True):  # noqa: ARG002
        return [{"title": "Cached", "uuid": "1", "type": "to-do"}]


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def request(self, *_args, **_kwargs):
        return FakeResponse(self.payload)


def snapshot(path: Path) -> None:
    CacheStore(path).write_snapshot(
        {
            "version": 1,
            "source": "test",
            "generated_at": "2026-05-03T12:00:00+00:00",
            "data": {
                "inbox": [{"title": "Inbox item", "uuid": "inbox-1", "type": "to-do", "notes": "alpha"}],
                "today": [{"title": "Today item", "uuid": "today-1", "type": "to-do"}],
                "upcoming": [],
                "anytime": [],
                "someday": [],
                "todos": [{"title": "Searchable", "uuid": "todo-1", "type": "to-do", "notes": "needle"}],
                "projects": [],
                "areas": [],
                "tags": [],
            },
        }
    )


def test_provider_selection_env(monkeypatch):
    monkeypatch.setenv("THINGS3_MCP_PROVIDER", "cache")
    assert isinstance(get_provider(), CacheThingsProvider)

    monkeypatch.setenv("THINGS3_MCP_PROVIDER", "not-real")
    with pytest.raises(ProviderError) as exc:
        get_provider()
    assert exc.value.error_code == "provider_invalid"


def test_auto_provider_falls_back_to_cache_like_provider():
    provider = AutoThingsProvider(providers=[FailingProvider(), FakeProvider()])
    assert provider.inbox()[0]["title"] == "Cached"


def test_cache_store_atomic_write_and_search(tmp_path):
    cache_file = tmp_path / "latest.json"
    snapshot(cache_file)
    store = CacheStore(cache_file)
    assert store.status()["available"] is True

    provider = CacheThingsProvider(store)
    assert provider.inbox()[0]["uuid"] == "inbox-1"
    assert provider.search("needle")[0]["uuid"] == "todo-1"
    assert provider.get("today-1")["title"] == "Today item"


def test_bridge_client_parses_error_envelope(monkeypatch, tmp_path):
    token = tmp_path / "bridge.token"
    token.write_text("secret")
    provider = BridgeThingsProvider(token_file=token, socket_path=tmp_path / "bridge.sock")
    payload = {
        "ok": False,
        "error_code": "bridge_not_authorized",
        "message": "grant access",
        "authorization_hint": "Grant Full Disk Access",
        "cache_status": {"available": False},
    }
    monkeypatch.setattr(provider, "_client", lambda: FakeClient(payload))

    with pytest.raises(ProviderError) as exc:
        provider.inbox()
    assert exc.value.error_code == "bridge_not_authorized"
    assert "Full Disk Access" in exc.value.authorization_hint


def test_worker_timeout_returns_timeout_envelope(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["worker"], timeout=0.01)

    monkeypatch.setattr(subprocess, "run", fake_run)
    envelope = run_worker("inbox", timeout=0.01)
    assert envelope["ok"] is False
    assert envelope["error_code"] == "things_db_timeout"


def test_check_bridge_snapshot_fails_when_bridge_prerequisites_are_missing(monkeypatch, tmp_path, capsys):
    """``check_bridge.py --snapshot`` must not exit 0 when no bridge is reachable."""
    script_path = Path(__file__).parents[1] / "scripts" / "check_bridge.py"
    spec = importlib.util.spec_from_file_location("check_bridge_under_test", script_path)
    assert spec and spec.loader
    check_bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check_bridge)

    class FakeCacheStore:
        def status(self):
            return {"available": False}

    monkeypatch.setattr(check_bridge, "DEFAULT_SOCKET", tmp_path / "missing.sock")
    monkeypatch.setattr(check_bridge, "DEFAULT_TOKEN_FILE", tmp_path / "missing.token")
    monkeypatch.setattr(check_bridge, "APP_BUNDLE", tmp_path / "Things3 MCP Bridge.app")
    monkeypatch.setattr(check_bridge, "CacheStore", FakeCacheStore)
    monkeypatch.setattr(sys, "argv", ["check_bridge.py", "--snapshot"])

    exit_code = check_bridge.main()
    diagnostics = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert diagnostics["socket_reachable"] is False
    assert diagnostics["snapshot_error"].startswith("Cannot run live snapshot")
    assert "bridge socket missing" in diagnostics["snapshot_error"]
    assert "bridge token missing" in diagnostics["snapshot_error"]


def test_sqlite_probe_stays_inside_worker_process(monkeypatch, tmp_path):
    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query):
            assert query == "select 1"
            return self

        def fetchone(self):
            return (1,)

    def fail_subprocess(*_args, **_kwargs):
        pytest.fail("SQLite validation must not spawn /usr/bin/sqlite3")

    monkeypatch.setattr(db_reader.subprocess, "run", fail_subprocess)
    monkeypatch.setattr(db_reader.sqlite3, "connect", lambda *_args, **_kwargs: FakeConnection())

    assert db_reader._can_open_sqlite(tmp_path / "main.sqlite") is True


def test_resolve_db_path_globs_group_container_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("THINGSDB", raising=False)
    monkeypatch.delenv("THINGS3_MCP_DATA_FOLDER", raising=False)

    fake_db = tmp_path / "ThingsData-FAKE" / "Things Database.thingsdatabase" / "main.sqlite"
    fake_db.parent.mkdir(parents=True)
    fake_db.touch()

    monkeypatch.setattr(db_reader, "_data_folder_from_thingscli_defaults", lambda: None)
    monkeypatch.setattr(db_reader.glob, "glob", lambda _pattern: [str(fake_db)])
    monkeypatch.setattr(db_reader, "_can_open_sqlite", lambda _path: True)

    assert db_reader.resolve_things_db_path() == str(fake_db)


def test_resolve_db_path_raises_when_glob_finds_nothing(monkeypatch):
    monkeypatch.delenv("THINGSDB", raising=False)
    monkeypatch.delenv("THINGS3_MCP_DATA_FOLDER", raising=False)

    monkeypatch.setattr(db_reader, "_data_folder_from_thingscli_defaults", lambda: None)
    monkeypatch.setattr(db_reader.glob, "glob", lambda _pattern: [])

    with pytest.raises(FileNotFoundError, match="Full Disk Access"):
        db_reader.resolve_things_db_path()


def test_diagnose_access_enumerates_group_container(monkeypatch, tmp_path):
    monkeypatch.delenv("THINGSDB", raising=False)
    monkeypatch.delenv("THINGS3_MCP_DATA_FOLDER", raising=False)

    fake_db = tmp_path / "ThingsData-FAKE" / "Things Database.thingsdatabase" / "main.sqlite"
    fake_db.parent.mkdir(parents=True)
    fake_db.touch()

    monkeypatch.setattr(db_reader, "_data_folder_from_thingscli_defaults", lambda: None)
    monkeypatch.setattr(db_reader.glob, "glob", lambda _pattern: [str(fake_db)])
    monkeypatch.setattr(db_reader, "_can_open_sqlite", lambda _path: True)
    monkeypatch.setattr(db_reader, "things_process_running", lambda: True)

    result = db_reader.diagnose_access()

    assert result["ok"] is True
    assert result["path"] == str(fake_db)
    assert result["patterns"]
    assert result["patterns"][0]["matches"] == [str(fake_db)]
    assert result["things_process_running"] is True


def test_things_process_running_uses_system_events(monkeypatch):
    captured: dict[str, Any] = {}

    class FakeCompleted:
        returncode = 0
        stdout = "true\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return FakeCompleted()

    monkeypatch.setattr(db_reader.subprocess, "run", fake_run)

    assert db_reader.things_process_running() is True
    assert captured["cmd"] == [
        "/usr/bin/osascript",
        "-e",
        'tell application "System Events" to exists process "Things3"',
    ]
    assert captured["kwargs"]["timeout"] == 5


def test_things_process_running_returns_false_when_process_absent(monkeypatch):
    class FakeCompleted:
        returncode = 0
        stdout = "false\n"
        stderr = ""

    monkeypatch.setattr(db_reader.subprocess, "run", lambda *_args, **_kwargs: FakeCompleted())

    assert db_reader.things_process_running() is False


def test_things_process_running_returns_false_on_error(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["osascript"], timeout=5)

    monkeypatch.setattr(db_reader.subprocess, "run", fake_run)

    assert db_reader.things_process_running() is False


def test_snapshot_falls_back_to_apple_events_when_sqlite_path_unresolved(monkeypatch):
    def fail_sqlite(*_args, **_kwargs):
        raise FileNotFoundError("no db")

    monkeypatch.setattr(db_reader, "run_sqlite_action", fail_sqlite)
    monkeypatch.setattr(db_reader, "run_jxa_action", lambda action, _params: {"inbox": [{"title": action}]})

    result = db_reader.run_action("snapshot")

    assert result["_source"] == "apple_events"
    assert result["inbox"][0]["title"] == "snapshot"


def test_mcp_read_tools_use_provider_facade(monkeypatch):
    import things3_mcp.fast_server as fast_server

    class FacadeProvider:
        def inbox(self, include_items: bool = True):  # noqa: ARG002
            return [{"title": "Inbox via facade", "uuid": "i", "type": "to-do"}]

        def today(self, include_items: bool = True):  # noqa: ARG002
            return []

        def search(self, query: str, include_items: bool = True):  # noqa: ARG002
            return [{"title": f"Search {query}", "uuid": "s", "type": "to-do"}]

        def get(self, uuid: str):  # noqa: ARG002
            return None

    monkeypatch.setattr(fast_server, "get_provider", lambda: FacadeProvider())

    assert "Inbox via facade" in fast_server.get_inbox()
    assert fast_server.get_today() == "No items due today"
    assert "Search alpha" in fast_server.search_todos("alpha")


# --- Write path tests -----------------------------------------------------


def test_bridge_provider_add_task_posts_correct_payload(monkeypatch, tmp_path):
    """The HTTP client should POST to /things/todo with the params as JSON body."""
    token = tmp_path / "bridge.token"
    token.write_text("secret")
    provider = BridgeThingsProvider(token_file=token, socket_path=tmp_path / "bridge.sock")

    captured: dict[str, Any] = {}

    class CapturingClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, method, path, json=None):
            captured["method"] = method
            captured["path"] = path
            captured["json"] = json
            return FakeResponse({"ok": True, "data": {"id": "new-uuid"}})

    monkeypatch.setattr(provider, "_client", lambda: CapturingClient())

    result = provider.add_task({"title": "Hello", "tags": ["a"]})
    assert captured["method"] == "POST"
    assert captured["path"] == "/things/todo"
    assert captured["json"] == {"title": "Hello", "tags": ["a"]}
    assert result == {"id": "new-uuid"}


def test_bridge_provider_update_task_uses_patch(monkeypatch, tmp_path):
    token = tmp_path / "bridge.token"
    token.write_text("secret")
    provider = BridgeThingsProvider(token_file=token, socket_path=tmp_path / "bridge.sock")

    captured: dict[str, Any] = {}

    class CapturingClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, method, path, json=None):
            captured["method"] = method
            captured["path"] = path
            captured["json"] = json
            return FakeResponse({"ok": True, "data": {}})

    monkeypatch.setattr(provider, "_client", lambda: CapturingClient())

    provider.update_task("ABC123", {"title": "Updated"})
    assert captured["method"] == "PATCH"
    assert captured["path"] == "/things/todo/ABC123"
    assert captured["json"] == {"title": "Updated"}


def test_cache_provider_refuses_writes():
    provider = CacheThingsProvider()
    with pytest.raises(ProviderError) as exc:
        provider.add_task({"title": "x"})
    assert exc.value.error_code == "writes_unsupported"


def test_auto_provider_writes_use_bridge_when_healthy():
    """When the bridge succeeds, writes never reach any fallback provider."""

    class FakeBridge(BridgeThingsProvider):
        def __init__(self):
            self.add_task_called_with: dict[str, Any] | None = None

        def add_task(self, params):
            self.add_task_called_with = params
            return {"ok": True, "id": "from-bridge"}

    class FakeDirect:
        def __init__(self):
            self.called = False

        def add_task(self, _params):
            self.called = True
            return {"ok": True, "id": "from-direct"}

    bridge = FakeBridge()
    direct = FakeDirect()
    auto = AutoThingsProvider(providers=[bridge, CacheThingsProvider()], write_providers=[bridge, direct])

    result = auto.add_task({"title": "test"})
    assert result == {"ok": True, "id": "from-bridge"}
    assert bridge.add_task_called_with == {"title": "test"}
    assert direct.called is False, "Direct provider should not be called when bridge succeeds"


def test_auto_provider_writes_fall_back_to_direct_when_bridge_fails():
    """Bridge failures must fall through to the direct AppleScript path so
    installs without the bridge built/authorised keep working.
    """

    class FailingBridge(BridgeThingsProvider):
        def __init__(self):
            pass

        def add_task(self, _params):
            raise ProviderError("bridge_unavailable", "socket gone")

    class FakeDirect:
        def __init__(self):
            self.add_task_called_with: dict[str, Any] | None = None

        def add_task(self, params):
            self.add_task_called_with = params
            return {"ok": True, "id": "from-direct"}

    bridge = FailingBridge()
    direct = FakeDirect()
    auto = AutoThingsProvider(providers=[bridge, CacheThingsProvider()], write_providers=[bridge, direct])

    result = auto.add_task({"title": "test"})
    assert result == {"ok": True, "id": "from-direct"}
    assert direct.add_task_called_with == {"title": "test"}


def test_auto_provider_writes_surface_bridge_error_when_no_fallback():
    """When the write chain has no direct fallback, bridge errors propagate.

    Production code never wires this configuration (the default
    ``_auto_write_chain`` always includes Direct), but explicit construction
    in tests / programmatic use must not silently swallow the error.
    """

    class FailingBridge(BridgeThingsProvider):
        def __init__(self):
            pass

        def add_task(self, _params):
            raise ProviderError("bridge_unavailable", "socket gone")

    auto = AutoThingsProvider(
        providers=[FailingBridge(), CacheThingsProvider()],
        write_providers=[FailingBridge()],
    )
    with pytest.raises(ProviderError) as exc:
        auto.add_task({"title": "x"})
    assert exc.value.error_code == "bridge_unavailable"


def test_default_auto_write_chain_includes_direct():
    """The factory chain must always include direct so the bridge stays optional."""
    from things3_mcp.providers import _auto_write_chain
    from things3_mcp.providers.direct import DirectThingsProvider

    chain = _auto_write_chain()
    types = [type(p) for p in chain]
    assert BridgeThingsProvider in types, "Bridge should always be in the write chain"
    assert DirectThingsProvider in types, "Direct should always be in the write chain (fallback when bridge is absent)"


# --- Bridge HTTP authorization (security) ---------------------------------


def test_bridge_authorization_uses_constant_time_comparison(monkeypatch):
    """``_authorized`` should use ``hmac.compare_digest`` to defeat timing oracles."""
    import hmac as hmac_module

    from things3_mcp_bridge import server as bridge_server

    monkeypatch.setattr(bridge_server, "ensure_token", lambda: "real-token-value")

    # Hook compare_digest so we can prove it was called.
    calls: list[tuple[str, str]] = []
    real_compare = hmac_module.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real_compare(a, b)

    monkeypatch.setattr(bridge_server.hmac, "compare_digest", spy)

    handler = bridge_server.BridgeRequestHandler.__new__(bridge_server.BridgeRequestHandler)
    handler.path = "/things/inbox"
    handler.headers = {"Authorization": "Bearer real-token-value"}

    assert handler._authorized() is True
    assert calls, "compare_digest should be invoked"


def test_bridge_authorization_rejects_empty_token_file(monkeypatch):
    """An empty token file must NOT authorize an empty Authorization header.

    Pre-fix: ``"Bearer " == "Bearer " + ""`` → True. That's an authentication
    bypass for any local process at the same UID if the token file got
    truncated. Post-fix: empty expected token → fail closed.
    """
    from things3_mcp_bridge import server as bridge_server

    monkeypatch.setattr(bridge_server, "ensure_token", lambda: "")

    handler = bridge_server.BridgeRequestHandler.__new__(bridge_server.BridgeRequestHandler)
    handler.path = "/things/inbox"
    handler.headers = {"Authorization": "Bearer "}
    assert handler._authorized() is False, "Empty token must never authorize"

    handler.headers = {"Authorization": ""}
    assert handler._authorized() is False, "Empty header must never authorize"


def test_bridge_authorization_rejects_missing_header(monkeypatch):
    from things3_mcp_bridge import server as bridge_server

    monkeypatch.setattr(bridge_server, "ensure_token", lambda: "real-token")

    handler = bridge_server.BridgeRequestHandler.__new__(bridge_server.BridgeRequestHandler)
    handler.path = "/things/inbox"
    handler.headers = {}  # no Authorization header at all
    assert handler._authorized() is False


def test_bridge_token_file_created_with_owner_only_permissions(monkeypatch, tmp_path):
    """``ensure_token`` must create the token file with mode 0o600 atomically.

    Pre-fix sequence: write_text() (creates 0o644 by default umask) → chmod 0o600.
    Window: another local process at the same UID can read the token.
    Post-fix: ``os.open(O_CREAT|O_EXCL|O_WRONLY, 0o600)`` is atomic.
    """
    from things3_mcp_bridge import server as bridge_server

    token_file = tmp_path / "subdir" / "bridge.token"
    bridge_server.ensure_token(token_file)

    mode = token_file.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600 but got {oct(mode)}"

    # Owner-only is also required for the parent directory.
    parent_mode = token_file.parent.stat().st_mode & 0o777
    assert parent_mode == 0o700, f"Expected parent dir 0o700 but got {oct(parent_mode)}"

    # Re-call should be idempotent and return the same token.
    assert bridge_server.ensure_token(token_file) == token_file.read_text()


# --- live_or_cache surface for both-failed scenarios ----------------------


def test_live_or_cache_combines_errors_when_both_fail(monkeypatch):
    """When the live worker AND the cache provider both fail, the response should
    expose both errors so the user knows the cache is also missing.
    """
    from things3_mcp_bridge import server as bridge_server

    monkeypatch.setattr(
        bridge_server,
        "run_worker",
        lambda *_args, **_kwargs: {"ok": False, "error_code": "things_db_timeout", "message": "live failed"},
    )
    monkeypatch.setattr(
        bridge_server,
        "_cache_envelope",
        lambda *_args, **_kwargs: {"ok": False, "error_code": "cache_missing", "message": "no snapshot"},
    )

    envelope = bridge_server.live_or_cache("inbox", {"include_items": True})
    assert envelope["ok"] is False
    assert envelope["error_code"] == "things_db_timeout"  # primary live error preserved
    assert "cache_error" in envelope
    assert envelope["cache_error"]["error_code"] == "cache_missing"


def test_worker_run_action_dispatches_add_task_to_applescript(monkeypatch):
    """run_action('add_task', params) should call applescript_bridge.add_todo."""
    import things3_mcp.applescript_bridge as ab

    captured: dict[str, Any] = {}

    def fake_add_todo(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "new-uuid-1234"

    monkeypatch.setattr(ab, "add_todo", fake_add_todo)

    result = db_reader.run_action("add_task", {"title": "Hello", "notes": "world"})
    assert captured == {"title": "Hello", "notes": "world"}
    assert result == {"ok": True, "id": "new-uuid-1234"}


def test_worker_run_action_update_task_extracts_uuid(monkeypatch):
    import things3_mcp.applescript_bridge as ab

    captured: dict[str, Any] = {}

    def fake_update_todo(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "true"

    monkeypatch.setattr(ab, "update_todo", fake_update_todo)

    result = db_reader.run_action("update_task", {"uuid": "ABC123", "title": "new"})
    assert captured == {"id": "ABC123", "title": "new"}
    assert result == {"ok": True}


def test_worker_run_action_update_task_requires_uuid():
    with pytest.raises(ValueError, match="uuid"):
        db_reader.run_action("update_task", {"title": "no uuid"})


def test_worker_coerces_applescript_error_into_runtime_error(monkeypatch):
    import things3_mcp.applescript_bridge as ab

    monkeypatch.setattr(ab, "add_todo", lambda **_kwargs: "Error: list not found")

    with pytest.raises(RuntimeError, match="list not found"):
        db_reader.run_action("add_task", {"title": "x"})


# --- Provider routing for the remaining 8 read tools ----------------------


class _ReadProvider:
    """Minimal stand-in capturing provider calls for fast_server tools."""

    def __init__(self, *, todos_result=None, tasks_result=None, search_result=None, trash_result=None, last_result=None, get_result=None):
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.todos_result = todos_result if todos_result is not None else []
        self.tasks_result = tasks_result if tasks_result is not None else []
        self.search_result = search_result if search_result is not None else []
        self.trash_result = trash_result if trash_result is not None else []
        self.last_result = last_result if last_result is not None else []
        self.get_result = get_result

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def todos(self, **kwargs):
        self._record("todos", **kwargs)
        return self.todos_result

    def tasks(self, **kwargs):
        self._record("tasks", **kwargs)
        return self.tasks_result

    def search(self, query, include_items=True):
        self._record("search", query, include_items=include_items)
        return self.search_result

    def trash(self, include_items=True):
        self._record("trash", include_items=include_items)
        return self.trash_result

    def last(self, period, include_items=True):
        self._record("last", period, include_items=include_items)
        return self.last_result

    def get(self, uuid):
        self._record("get", uuid)
        return self.get_result


def _patch_provider(monkeypatch, provider):
    import things3_mcp.fast_server as fast_server

    monkeypatch.setattr(fast_server, "get_provider", lambda: provider)
    return fast_server


def test_get_logbook_calls_provider_tasks_with_completion_filter(monkeypatch):
    provider = _ReadProvider(tasks_result=[{"title": "Done", "uuid": "1", "type": "to-do", "stop_date": "2026-05-01"}])
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.get_logbook(period="7d", limit=10)
    assert "Done" in result
    name, _args, kwargs = provider.calls[0]
    assert name == "tasks"
    assert kwargs.get("status") == "completed"
    assert "stop_date" in kwargs


def test_get_trash_calls_provider_trash(monkeypatch):
    provider = _ReadProvider(trash_result=[{"title": "Trashed thing", "uuid": "1", "type": "to-do"}])
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.get_trash()
    assert "Trashed thing" in result
    assert provider.calls[0][0] == "trash"
    assert provider.calls[0][2]["include_items"] is False


def test_get_trash_limits_large_trash_without_per_item_enrichment(monkeypatch):
    items = [{"title": f"Trash {i}", "uuid": str(i), "type": "to-do", "project": "project-1"} for i in range(300)]
    provider = _ReadProvider(trash_result=items, get_result={"title": "Should not be fetched", "uuid": "project-1", "type": "project"})
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.get_trash()

    assert "Trash 0" in result
    assert "Trash 49" in result
    assert "Trash 50" not in result
    assert "Showing trashed items 1-50 of 300" in result
    assert "Next page: call get_trash(limit=50, offset=50)" in result
    assert [call[0] for call in provider.calls] == ["trash"]


def test_get_trash_supports_offset_and_caps_limit(monkeypatch):
    items = [{"title": f"Trash {i}", "uuid": str(i), "type": "to-do"} for i in range(300)]
    provider = _ReadProvider(trash_result=items)
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.get_trash(limit=250, offset=100)

    assert "Trash 100" in result
    assert "Trash 299" in result
    assert "Trash 99" not in result
    assert "Requested limit 250 was capped at 200" in result
    assert "Next page" not in result


def test_get_trash_rejects_invalid_paging(monkeypatch):
    provider = _ReadProvider()
    fast_server = _patch_provider(monkeypatch, provider)

    assert fast_server.get_trash(limit=0) == "Error: limit must be at least 1"
    assert fast_server.get_trash(offset=-1) == "Error: offset must be at least 0"
    assert fast_server.get_trash(limit="many") == "Error: limit and offset must be integers"
    assert provider.calls == []


def test_get_trash_empty_returns_friendly_message(monkeypatch):
    provider = _ReadProvider(trash_result=[])
    fast_server = _patch_provider(monkeypatch, provider)

    assert fast_server.get_trash() == "No items in trash"


def test_get_todos_filters_by_project_uuid(monkeypatch):
    provider = _ReadProvider(
        todos_result=[{"title": "In project", "uuid": "1", "type": "to-do"}],
        get_result={"type": "project", "uuid": "PROJ", "title": "Project name"},
    )
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.get_todos(project_uuid="PROJ")
    assert "In project" in result
    # First call resolves the project, second pulls todos.
    assert provider.calls[0][0] == "get"
    assert provider.calls[1][0] == "todos"
    assert provider.calls[1][2].get("project") == "PROJ"


def test_get_todos_rejects_invalid_project_uuid(monkeypatch):
    provider = _ReadProvider(get_result=None)
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.get_todos(project_uuid="MISSING")
    assert "Invalid project UUID" in result


def test_get_random_todos_samples_provider_results(monkeypatch):
    items = [{"title": f"todo-{i}", "uuid": str(i), "type": "to-do"} for i in range(50)]
    provider = _ReadProvider(todos_result=items)
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.get_random_todos(count=3)
    # Random sample of 3 → result string contains 3 separator blocks.
    assert result.count("---") == 2
    assert provider.calls[0][0] == "todos"


def test_get_tagged_items_routes_through_provider_todos(monkeypatch):
    provider = _ReadProvider(todos_result=[{"title": "Tagged", "uuid": "1", "type": "to-do"}])
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.get_tagged_items(tag="urgent")
    assert "Tagged" in result
    name, _args, kwargs = provider.calls[0]
    assert name == "todos"
    assert kwargs.get("tag") == "urgent"


def test_search_advanced_passes_filters_to_provider_todos(monkeypatch):
    provider = _ReadProvider(todos_result=[{"title": "Match", "uuid": "1", "type": "to-do"}])
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.search_advanced(status="incomplete", tag="urgent", deadline="2026-12-31")
    assert "Match" in result
    name, _args, kwargs = provider.calls[0]
    assert name == "todos"
    assert kwargs.get("status") == "incomplete"
    assert kwargs.get("tag") == "urgent"
    assert kwargs.get("deadline") == "2026-12-31"


def test_search_all_items_routes_through_provider_search(monkeypatch):
    provider = _ReadProvider(search_result=[{"title": "Found", "uuid": "1", "type": "to-do"}])
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.search_all_items(query="needle")
    assert "Found" in result
    name, args, _kwargs = provider.calls[0]
    assert name == "search"
    assert args[0] == "needle"


def test_get_recent_routes_through_provider_last(monkeypatch):
    provider = _ReadProvider(last_result=[{"title": "Recent", "uuid": "1", "type": "to-do"}])
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.get_recent(period="7d")
    assert "Recent" in result
    name, args, _kwargs = provider.calls[0]
    assert name == "last"
    assert args[0] == "7d"


def test_get_recent_project_area_lookup_stays_on_provider(monkeypatch):
    provider = _ReadProvider(
        last_result=[{"title": "Recent Project", "uuid": "project-1", "type": "project", "area": "area-1"}],
        get_result={"title": "Bridge Area", "uuid": "area-1", "type": "area"},
    )
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.get_recent(period="7d")

    assert "Recent Project" in result
    assert "Area: Bridge Area" in result
    assert provider.calls[0][0] == "last"
    assert provider.calls[1] == ("get", ("area-1",), {})


def test_get_recent_validates_period_format(monkeypatch):
    provider = _ReadProvider()
    fast_server = _patch_provider(monkeypatch, provider)

    result = fast_server.get_recent(period="bogus")
    assert "Error" in result
    # Should not even reach the provider on invalid input.
    assert provider.calls == []


# --- New provider-protocol surface tests ----------------------------------


def test_bridge_provider_trash_uses_get_endpoint(monkeypatch, tmp_path):
    token = tmp_path / "bridge.token"
    token.write_text("secret")
    provider = BridgeThingsProvider(token_file=token, socket_path=tmp_path / "bridge.sock")

    captured: dict[str, Any] = {}

    class CapturingClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, method, path, json=None):
            captured["method"] = method
            captured["path"] = path
            return FakeResponse({"ok": True, "data": [{"title": "trashed", "uuid": "1", "type": "to-do"}]})

    monkeypatch.setattr(provider, "_client", lambda: CapturingClient())

    result = provider.trash(include_items=True)
    assert captured["method"] == "GET"
    assert captured["path"] == "/things/trash?include_items=true"
    assert result[0]["title"] == "trashed"


def test_bridge_provider_last_passes_period_in_path(monkeypatch, tmp_path):
    token = tmp_path / "bridge.token"
    token.write_text("secret")
    provider = BridgeThingsProvider(token_file=token, socket_path=tmp_path / "bridge.sock")

    captured: dict[str, Any] = {}

    class CapturingClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, method, path, json=None):
            captured["method"] = method
            captured["path"] = path
            return FakeResponse({"ok": True, "data": []})

    monkeypatch.setattr(provider, "_client", lambda: CapturingClient())

    provider.last("7d")
    assert captured["method"] == "GET"
    assert captured["path"] == "/things/last/7d?include_items=true"


def test_cache_provider_raises_cache_miss_for_unsupported_reads():
    """``trash`` and ``last`` aren't materialised in the snapshot; the cache
    provider must raise so AutoThingsProvider falls through to the next
    provider rather than treating an empty list as a hit.
    """
    provider = CacheThingsProvider()

    with pytest.raises(ProviderError) as trash_exc:
        provider.trash()
    assert trash_exc.value.error_code == "cache_miss"

    with pytest.raises(ProviderError) as last_exc:
        provider.last("7d")
    assert last_exc.value.error_code == "cache_miss"


def test_auto_provider_falls_through_cache_miss_for_unsupported_reads():
    """When the bridge is down and the cache surfaces ``cache_miss`` for
    ``trash``/``last``, the auto-provider should walk to the next provider
    (direct, when configured) instead of bubbling up the cache miss.
    """

    class FailingBridge(BridgeThingsProvider):
        def __init__(self):
            pass

        def trash(self, include_items: bool = True):  # noqa: ARG002
            raise ProviderError("bridge_unavailable", "socket gone")

    class StubDirect:
        def trash(self, include_items: bool = True):  # noqa: ARG002
            return [{"title": "from direct", "uuid": "1", "type": "to-do"}]

    auto = AutoThingsProvider(providers=[FailingBridge(), CacheThingsProvider(), StubDirect()])
    assert auto.trash()[0]["title"] == "from direct"


def test_worker_run_action_dispatches_trash_and_last(monkeypatch):
    """Verify run_sqlite_action routes 'trash' and 'last' to direct_provider."""
    captured: dict[str, Any] = {}

    class FakeDirectProvider:
        def trash(self, include_items=True):
            captured["trash_include_items"] = include_items
            return [{"title": "T", "uuid": "1", "type": "to-do"}]

        def last(self, period, include_items=True):
            captured["last_period"] = period
            captured["last_include_items"] = include_items
            return [{"title": "R", "uuid": "2", "type": "to-do"}]

    monkeypatch.setattr(db_reader, "direct_provider", lambda: FakeDirectProvider())

    trash = db_reader.run_sqlite_action("trash", {"include_items": True})
    last = db_reader.run_sqlite_action("last", {"period": "7d", "include_items": True})

    assert trash[0]["title"] == "T"
    assert last[0]["title"] == "R"
    assert captured == {"trash_include_items": True, "last_period": "7d", "last_include_items": True}


def test_worker_last_action_requires_period(monkeypatch):
    monkeypatch.setattr(db_reader, "direct_provider", lambda: object())
    with pytest.raises(ValueError, match="period"):
        db_reader.run_sqlite_action("last", {})
