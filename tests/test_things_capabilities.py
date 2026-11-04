"""Synthetic capability, freshness and mutation-outcome boundary tests."""

from __future__ import annotations

import json
import logging
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from things3_mcp import applescript_bridge as ab
from things3_mcp.providers import AutoThingsProvider, ProviderError
from things3_mcp.providers.base import read_context, read_observations
from things3_mcp.providers.bridge import BridgeThingsProvider
from things3_mcp.providers.cache import CacheStore, CacheThingsProvider
from things3_mcp_bridge import auth_status, db_reader


class ResponseClient:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        if isinstance(self.payload, Exception):
            raise self.payload
        payload = self.payload(method, path, kwargs) if callable(self.payload) else self.payload
        return SimpleNamespace(json=lambda: payload)


def client_provider(monkeypatch, payload):
    provider = BridgeThingsProvider()
    client = ResponseClient(payload)
    monkeypatch.setattr(provider, "_client", lambda: client)
    return provider, client


def test_readiness_uses_only_event_free_property(monkeypatch):
    calls = []

    def running(script, **kwargs):
        calls.append((script, kwargs))
        return "true"

    monkeypatch.setattr(ab, "run_applescript", running)
    assert ab.ensure_things_ready() is True
    assert calls == [('application id "com.culturedcode.ThingsMac" is running', {"timeout": 5})]


@pytest.mark.parametrize("function,params", [(ab.add_todo, {"title": "x"}), (ab.add_project, {"title": "x"}), (ab.update_todo, {"id": "x"}), (ab.update_project, {"id": "x"})])
def test_closed_app_rejects_before_mutation(monkeypatch, function, params):
    monkeypatch.setattr(ab, "ensure_things_ready", lambda: False)
    monkeypatch.setattr(ab, "run_applescript", lambda *_args, **_kwargs: pytest.fail("Closed app must not dispatch"))
    with pytest.raises(ProviderError) as error:
        function(**params)
    assert error.value.error_code == "app_not_running"
    assert error.value.outcome == "failed"


@pytest.mark.parametrize("stderr,code", [("secret-title Not authorized to send Apple events (-1743)", "automation_denied"), ("secret-title failed after creation (-10000)", "applescript_failed")])
def test_app_errors_are_sanitised_uncertain_and_script_uses_stdin(monkeypatch, caplog, stderr, code):
    calls = []

    def spawn(argv, **_kwargs):
        assert argv == ["/usr/bin/osascript", "-"]

        def communicate(**kwargs):
            calls.append(kwargs)
            return b"secret-result", stderr.encode()

        return SimpleNamespace(returncode=1, communicate=communicate)

    monkeypatch.setattr(ab.subprocess, "Popen", spawn)
    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError) as error:
        ab.run_applescript('return "secret-title"')
    assert error.value.error_code == code
    assert error.value.outcome == "outcome_unknown"
    assert "secret" not in caplog.text
    assert "secret" not in str(error.value)
    assert calls == [{"input": b'return "secret-title"', "timeout": 8}]


def test_timeout_kills_and_waits_for_stdin_script(monkeypatch):
    calls = []

    class Process:
        def communicate(self, **kwargs):
            calls.append(("communicate", kwargs))
            if kwargs:
                raise subprocess.TimeoutExpired(["osascript"], 1)
            return b"", b""

        def kill(self):
            calls.append(("kill", {}))

    def spawn(argv, **_kwargs):
        assert argv == ["/usr/bin/osascript", "-"]
        return Process()

    monkeypatch.setattr(ab.subprocess, "Popen", spawn)
    with pytest.raises(ProviderError) as error:
        ab.run_applescript("return true", timeout=1)
    assert error.value.outcome == "outcome_unknown"
    assert calls == [("communicate", {"input": b"return true", "timeout": 1}), ("kill", {}), ("communicate", {})]


def test_jxa_values_use_stdin_and_private_script_cleanup(monkeypatch):
    paths = []

    def run(argv, **kwargs):
        assert argv[:3] == ["/usr/bin/osascript", "-l", "JavaScript"]
        assert len(argv) == 4
        assert "secret-query" not in " ".join(argv)
        assert json.loads(kwargs["input"])["params"] == {"query": "secret-query"}
        paths.append(Path(argv[3]))
        assert stat.S_IMODE(paths[0].stat().st_mode) == 0o600
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(db_reader.subprocess, "run", run)
    assert db_reader._run_jxa_script(db_reader._JXA_SIMPLE, "inbox", {"query": "secret-query"}) == "[]"
    assert not paths[0].exists()


def test_passive_status_keeps_unknown_separate_from_cache(monkeypatch):
    monkeypatch.setattr(auth_status, "cache_status", lambda: {"available": True})
    status = auth_status.build_auth_status(last_live_error={"error_code": "worker_timeout", "message": "secret"})
    assert status["capabilities"] == {"database": {"state": "unknown"}, "automation": {"state": "unknown"}}
    assert status["authorization_known"] is False
    assert status["authorized"] is None
    assert status["app_process"] == "unknown"
    assert "secret" not in json.dumps(status)


def test_database_denied_with_automation_available_is_distinct(monkeypatch):
    def denied(*_args):
        raise PermissionError("private-path")

    monkeypatch.setattr(db_reader, "run_sqlite_action", denied)
    monkeypatch.setattr(db_reader, "run_jxa_action", lambda *_args: [])
    assert db_reader.run_action("inbox") == []
    observations = db_reader.capability_observations()
    assert observations["database"]["state"] == "denied"
    assert observations["automation"]["state"] == "available"
    assert "private-path" not in json.dumps(observations)


@pytest.mark.parametrize("action,params", [("trash", {}), ("search", {"query": "x"}), ("get", {"uuid": "x"}), ("projects", {"include_items": True}), ("inbox", {"status": "completed"})])
def test_unsupported_apple_events_fallback_is_explicit_without_launch(monkeypatch, action, params):
    monkeypatch.setattr(db_reader, "things_process_running", lambda: pytest.fail("Unsupported reads must not probe Things"))
    with pytest.raises(ProviderError) as error:
        db_reader.run_jxa_action(action, params)
    assert error.value.error_code == "apple_events_unsupported"


def test_sqlite_probe_uses_read_only_wal_aware_uri(monkeypatch, tmp_path):
    import sqlite3

    path = tmp_path / "main.sqlite"
    with sqlite3.connect(path) as writer:
        writer.execute("pragma journal_mode=wal")
        writer.execute("create table example (value text)")
        writer.execute("insert into example values ('committed in WAL')")
        writer.commit()
        original = sqlite3.connect

        def connect(database, **kwargs):
            assert "mode=ro" in database
            assert "immutable" not in database
            connection = original(database, **kwargs)
            assert connection.execute("select value from example").fetchone() == ("committed in WAL",)
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                connection.execute("delete from example")
            return connection

        monkeypatch.setattr(db_reader.sqlite3, "connect", connect)
        assert db_reader._can_open_sqlite(path)


@pytest.mark.parametrize("url", ["http://example.test", "http://things3-mcp-bridge.evil.test", "http://things3-mcp-bridge@evil.test", "http://things3-mcp-bridge/path", "http://things3-mcp-bridge:80"])
def test_http_bridge_urls_are_rejected_before_token_read(monkeypatch, url):
    monkeypatch.setattr(BridgeThingsProvider, "_token", lambda _self: pytest.fail("Credentials must not be read"))
    with pytest.raises(ProviderError) as error:
        BridgeThingsProvider(base_url=url)
    assert error.value.error_code == "bridge_url_invalid"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"ok": "true", "data": []},
        {"ok": True},
        {"ok": True, "data": [], "protocol_version": 2},
        {"ok": True, "data": [], "protocol_version": True},
        {"ok": True, "data": [], "cache_age_seconds": "fresh"},
        {"ok": False, "error_code": []},
        {"ok": True, "data": "secret"},
    ],
)
def test_corrupt_envelopes_do_not_become_empty_success(monkeypatch, payload):
    provider, _client = client_provider(monkeypatch, payload)
    with pytest.raises(ProviderError):
        provider.inbox()


def test_legacy_read_envelope_has_unknown_provenance(monkeypatch):
    provider, _client = client_provider(monkeypatch, {"ok": True, "data": [{"uuid": "x"}]})
    with read_context():
        assert provider.inbox() == [{"uuid": "x"}]
        assert read_observations() == ({"source": "unknown"},)


@pytest.mark.parametrize("payload", [httpx.ReadTimeout("secret transport payload"), {"ok": True, "data": {"id": "x"}}, {"ok": False, "error_code": "legacy_failure", "message": "legacy error"}])
def test_lost_or_legacy_mutation_outcome_retains_correlation(monkeypatch, payload):
    provider, client = client_provider(monkeypatch, payload)
    with pytest.raises(ProviderError) as error:
        provider.add_task({"title": "secret"})
    assert error.value.outcome == "outcome_unknown"
    assert error.value.error_code == "outcome_unknown"
    assert UUID(error.value.correlation_id)
    assert error.value.correlation_id == client.requests[0][2]["headers"]["X-Correlation-ID"]
    assert len(client.requests) == 1
    assert "secret" not in str(error.value)


def test_mutation_failure_keeps_operation_and_permission_category(monkeypatch):
    payload = {"protocol_version": 1, "ok": False, "error_code": "automation_denied", "message": "Things Automation denied", "outcome": "outcome_unknown", "operation_id": "op-123"}
    provider, _client = client_provider(monkeypatch, payload)
    with pytest.raises(ProviderError) as error:
        provider.add_task({"title": "x"})
    assert error.value.error_code == "automation_denied"
    assert error.value.operation_id == "op-123"
    assert error.value.outcome == "outcome_unknown"
    assert error.value.to_dict()["correlation_id"]


def test_live_required_read_sends_header_and_rejects_cache(monkeypatch):
    provider, client = client_provider(monkeypatch, {"ok": True, "data": [], "source": "cache", "cache_age_seconds": 12})
    with pytest.raises(ProviderError) as error:
        provider.read_live("inbox")
    assert error.value.error_code == "live_read_required"
    assert client.requests[0][2]["headers"]["X-Require-Live"] == "true"


def test_read_metadata_is_isolated_between_concurrent_calls(monkeypatch):
    barrier = Barrier(2)

    def payload(_method, path, _kwargs):
        cached = path.endswith("cached")
        return {"ok": True, "data": {"uuid": path}, "source": "cache" if cached else "live", **({"cache_age_seconds": 42} if cached else {})}

    provider, _client = client_provider(monkeypatch, payload)

    def read(name):
        with read_context():
            provider.get(name)
            barrier.wait(timeout=2)
            return read_observations()

    with ThreadPoolExecutor(max_workers=2) as executor:
        cached, live = list(executor.map(read, ["cached", "live"]))
    assert cached == ({"source": "cache", "cache_age_seconds": 42},)
    assert live == ({"source": "live"},)
    assert read_observations() == ()


def test_mcp_empty_cache_output_exposes_age_and_live_failure(monkeypatch, tmp_path):
    from things3_mcp import fast_server

    store = CacheStore(tmp_path / "snapshot.json")
    store.write_snapshot({"generated_at": "2026-01-01T00:00:00+00:00", "data": {"inbox": []}})

    class Unavailable:
        def inbox(self, **_kwargs):
            raise ProviderError("bridge_unavailable", "offline")

    provider = AutoThingsProvider(providers=[Unavailable(), CacheThingsProvider(store)])
    monkeypatch.setattr(fast_server, "get_provider", lambda: provider)
    result = fast_server.get_inbox()
    assert result.startswith("No items found in Inbox")
    assert "Read source: cache" in result
    assert "Snapshot age:" in result
    assert "Live read failed: bridge_unavailable" in result


def test_mcp_diagnostics_use_status_and_operation_routes(monkeypatch):
    from things3_mcp import fast_server

    def response(_method, path, _kwargs):
        return {"ok": True, "data": [] if path.startswith("/operations?") else {"instance_id": "test-instance"}}

    provider, client = client_provider(monkeypatch, response)
    monkeypatch.setattr(fast_server, "BridgeThingsProvider", lambda: provider)
    assert "test-instance" in fast_server.get_bridge_status()
    fast_server.get_bridge_operation("op-id")
    assert fast_server.list_bridge_operations("correlation-x", 10) == "[]"
    assert [request[1] for request in client.requests] == ["/status", "/operations/op-id", "/operations?limit=10&correlation_id=correlation-x"]


@pytest.mark.parametrize("timeout", [1, 30, float("nan"), float("inf")])
def test_client_deadline_must_exceed_worker_deadline(timeout):
    with pytest.raises(ProviderError) as error:
        BridgeThingsProvider(timeout=timeout)
    assert error.value.error_code == "bridge_timeout_invalid"
    assert BridgeThingsProvider().timeout > 30


@pytest.mark.parametrize("snapshot", [[], {"data": []}, {"data": {"inbox": "bad"}}, {"data": {"inbox": ["bad"]}}])
def test_invalid_cache_shape_cannot_become_empty_success(tmp_path, snapshot):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps(snapshot))
    path.chmod(0o600)
    provider = CacheThingsProvider(CacheStore(path))
    with pytest.raises(ProviderError) as error:
        provider.inbox()
    assert error.value.error_code == "cache_unreadable"


def test_fixed_database_discovery_rejects_outside_paths_and_symlinks(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    outside = tmp_path / "unrelated" / "main.sqlite"
    outside.parent.mkdir()
    outside.touch()
    target = tmp_path / "Library/Group Containers" / db_reader.DEFAULT_THINGS_GROUP_CONTAINER / "ThingsData-FAKE" / "Things Database.thingsdatabase" / "main.sqlite"
    target.parent.mkdir(parents=True)
    target.symlink_to(outside)
    monkeypatch.setattr(db_reader, "_can_open_sqlite", lambda _path: pytest.fail("Outside database must not be opened"))
    assert db_reader._valid_sqlite_path(outside) is None
    assert db_reader._valid_sqlite_path(target) is None
    assert db_reader._validated_path_for_data_folder("../../unrelated") is None


def test_diagnose_never_lists_unrelated_application_directories(monkeypatch):
    monkeypatch.setattr(db_reader, "things_process_running", lambda: False)
    monkeypatch.setattr(db_reader.glob, "glob", lambda _pattern: [])
    monkeypatch.setattr(db_reader, "_data_folder_from_thingscli_defaults", lambda: None)
    monkeypatch.setattr(db_reader.os, "listdir", lambda *_args: pytest.fail("No unrelated directory probes"))
    result = db_reader.diagnose_access()
    assert result["things_process_running"] is False
    assert "fda_probe" not in result
    assert all(db_reader.DEFAULT_THINGS_GROUP_CONTAINER in pattern["pattern"] for pattern in result["patterns"])


def test_legacy_live_required_read_is_rejected(monkeypatch):
    provider, _client = client_provider(monkeypatch, {"ok": True, "data": []})
    with pytest.raises(ProviderError) as error:
        provider.read_live("inbox")
    assert error.value.error_code == "live_read_required"


def test_local_failure_has_correlation_but_is_not_dispatched(monkeypatch):
    provider = BridgeThingsProvider()

    def unavailable():
        raise ProviderError("bridge_unavailable", "socket missing")

    monkeypatch.setattr(provider, "_client", unavailable)
    with pytest.raises(ProviderError) as error:
        provider.add_task({"title": "x"})
    assert error.value.outcome == "failed"
    assert error.value.error_code == "bridge_unavailable"
    assert UUID(error.value.correlation_id)


def test_corrupt_mutation_retains_observed_operation_id(monkeypatch):
    provider, _client = client_provider(monkeypatch, {"ok": True, "data": {}, "operation_id": "observed-id", "outcome": []})
    with pytest.raises(ProviderError) as error:
        provider.add_task({"title": "x"})
    assert error.value.outcome == "outcome_unknown"
    assert error.value.operation_id == "observed-id"


def test_third_party_request_and_exception_logs_omit_payloads():
    import io

    from things3_mcp.logging_config import OperationLogFilter, StructuredFormatter

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.addFilter(OperationLogFilter())
    handler.setFormatter(StructuredFormatter())
    logger = logging.getLogger("mcp.synthetic.logging-canary")
    logger.addHandler(handler)
    try:
        logger.error("Received message: %s", {"title": "private-title-canary", "notes": "private-note-canary"})
        try:
            raise ValueError("private-error-canary")
        except ValueError:
            logger.exception("Validation failed: private-title-canary")
    finally:
        logger.removeHandler(handler)
    assert "private-" not in output.getvalue()
    records = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(records) == 2
    assert records[0]["level"] == "ERROR"
    assert records[1]["error_type"] == "ValueError"


def test_concurrent_cache_snapshots_use_distinct_atomic_files(monkeypatch, tmp_path):
    import os

    barrier = Barrier(2)
    sources = []
    original = os.replace

    def replace(source, destination):
        sources.append(str(source))
        barrier.wait(timeout=2)
        original(source, destination)

    monkeypatch.setattr(os, "replace", replace)
    store = CacheStore(tmp_path / "latest.json")
    snapshots = [{"data": {"inbox": [{"title": str(index)}]}} for index in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(store.write_snapshot, snapshots))
    assert len(set(sources)) == 2
    assert store.read_snapshot() in snapshots
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_snapshot_write_does_not_follow_legacy_temp_symlink(tmp_path):
    canary = tmp_path / "canary"
    canary.write_text("unchanged")
    (tmp_path / "latest.json.tmp").symlink_to(canary)
    store = CacheStore(tmp_path / "latest.json")
    store.write_snapshot({"data": {"inbox": []}})
    assert canary.read_text() == "unchanged"
    assert not store.path.is_symlink()


def test_cache_read_rejects_symlink(tmp_path):
    canary = tmp_path / "canary"
    canary.write_text('{"data": {"inbox": []}}')
    canary.chmod(0o600)
    path = tmp_path / "latest.json"
    path.symlink_to(canary)
    with pytest.raises(ProviderError) as error:
        CacheStore(path).read_snapshot()
    assert error.value.error_code == "cache_unreadable"


def test_cache_limits_are_bounded_and_shared_directory_mode_is_unchanged(monkeypatch, tmp_path):
    from clawbridge.runtime import RuntimeSafetyError
    from things3_mcp.providers import cache

    shared = tmp_path / "shared"
    shared.mkdir(mode=0o755)
    shared.chmod(0o755)
    with pytest.raises(RuntimeSafetyError):
        CacheStore(shared / "snapshot.json").write_snapshot({"data": {}})
    assert stat.S_IMODE(shared.stat().st_mode) == 0o755

    path = tmp_path / "oversize.json"
    path.write_text('{"data": {"inbox": []}}')
    path.chmod(0o600)
    monkeypatch.setattr(cache, "MAX_CACHE_BYTES", 10)
    with pytest.raises(ProviderError, match="too large"):
        CacheStore(path).read_snapshot()
    with pytest.raises(ProviderError, match="size limit"):
        CacheStore(path).write_snapshot({"data": {}})


def test_snapshot_destination_symlink_is_not_replaced_or_written(tmp_path):
    from clawbridge.runtime import RuntimeSafetyError

    target = tmp_path / "canary"
    target.write_text("unchanged")
    target.chmod(0o600)
    path = tmp_path / "latest.json"
    path.symlink_to(target)
    with pytest.raises(RuntimeSafetyError):
        CacheStore(path).write_snapshot({"data": {}})
    assert target.read_text() == "unchanged"
    assert path.is_symlink()
    assert list(tmp_path.glob(".latest.json.*.tmp")) == []


@pytest.mark.parametrize("method", ["tasks", "todos", "projects", "areas"])
def test_explicit_count_queries_keep_their_integer_shape(monkeypatch, method):
    provider, _client = client_provider(monkeypatch, {"ok": True, "data": 7, "source": "live"})
    assert getattr(provider, method)(count_only=True) == 7
    with pytest.raises(ProviderError):
        getattr(provider, method)()


def test_explicit_tag_titles_query_keeps_its_string_list_shape(monkeypatch):
    provider, _client = client_provider(monkeypatch, {"ok": True, "data": ["Home", "Work"], "source": "live"})
    assert provider.tags(titles_only=True) == ["Home", "Work"]
    with pytest.raises(ProviderError):
        provider.tags()


def test_mcp_cache_snapshot_retains_limited_backend_provenance(monkeypatch, tmp_path):
    from things3_mcp import fast_server

    store = CacheStore(tmp_path / "latest.json")
    store.write_snapshot({"source": "apple_events", "data": {"inbox": []}})
    monkeypatch.setattr(fast_server, "get_provider", lambda: CacheThingsProvider(store))
    result = fast_server.get_inbox()
    assert "Snapshot backend: apple_events" in result
    assert "limited Apple Events coverage" in result
    assert "Snapshot age: unknown" in result
