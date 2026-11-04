"""Things adapter tests that never invoke Things or AppleScript."""

import subprocess

import pytest

from things3_mcp_bridge import server


def test_worker_payload_uses_stdin_and_stderr_is_captured(monkeypatch):
    from pathlib import Path

    from clawbridge.demo import ACTIONS
    from clawbridge.worker import run_worker

    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parents[1] / "src"))
    seen = {}
    real_popen = subprocess.Popen

    def popen(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)
    result = run_worker("clawbridge.demo", ACTIONS["echo"], {"text": "private-canary-title"})
    assert result["data"] == {"text": "private-canary-title"}
    assert "private-canary-title" not in " ".join(seen["argv"])
    assert seen["stdin"] == subprocess.PIPE
    assert seen["stderr"] == subprocess.PIPE
    assert seen["start_new_session"] is True


def test_token_symlink_is_rejected_without_changing_target(tmp_path):
    target = tmp_path / "target"
    target.write_text("not-a-token")
    target.chmod(0o644)
    token = tmp_path / "bridge.token"
    token.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        server.ensure_token(token)
    assert target.stat().st_mode & 0o777 == 0o644


def test_things_schemas_reject_arbitrary_paths_and_keep_existing_write_fields():
    from clawbridge.actions import InvalidRequestError
    from things3_mcp_bridge.actions import ACTIONS

    for name in ("tasks", "todos", "projects", "areas", "tags"):
        with pytest.raises(InvalidRequestError):
            ACTIONS[name].validate({"filepath": "/private/elsewhere.sqlite"})
    assert ACTIONS["add_task"].validate({"title": "task", "list_title": "project", "tags": ["tag"]})["list_title"] == "project"
    assert ACTIONS["update_task"].validate({"uuid": "task-id", "list_name": "Today", "add_tags": "tag", "completed": False})["completed"] is False
    assert ACTIONS["add_project"].validate({"title": "project", "todos": ["task"], "area_title": "area"})["todos"] == ["task"]
    with pytest.raises(InvalidRequestError):
        ACTIONS["add_task"].validate({"title": "task", "unexpected": True})


def test_live_required_never_uses_cached_results(monkeypatch):
    monkeypatch.setattr(server, "run_worker", lambda *_a, **_kw: {"ok": False, "error_code": "read_unavailable", "outcome": "failed"})
    monkeypatch.setattr(server, "_cache_envelope", lambda *_a, **_kw: pytest.fail("No cache read allowed"))
    assert server.live_or_cache("inbox", require_live=True)["error_code"] == "read_unavailable"


def test_read_worker_start_failure_can_use_labelled_cache(monkeypatch):
    monkeypatch.setattr(server, "run_worker", lambda *_a, **_kw: {"ok": False, "error_code": "worker_unavailable", "outcome": "not_started"})
    monkeypatch.setattr(server, "_cache_envelope", lambda *_a, **_kw: {"ok": True, "source": "cache", "data": []})
    result = server.live_or_cache("inbox")
    assert result["source"] == "cache"
    assert result["live_error"]["error_code"] == "worker_unavailable"


def test_cache_envelope_uses_the_snapshot_actually_read(monkeypatch):
    from things3_mcp.providers.base import record_read

    class SnapshotReader:
        def inbox(self, **_kwargs):
            record_read({"source": "cache", "generated_at": "2026-01-01T00:00:00+00:00", "cache_age_seconds": 123})
            return [{"title": "synthetic snapshot"}]

    monkeypatch.setattr(server, "CacheThingsProvider", SnapshotReader)
    monkeypatch.setattr(server, "cache_status", lambda: pytest.fail("Must not reread a newer snapshot for freshness"))
    result = server._cache_envelope("inbox")
    assert result["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert result["cache_age_seconds"] == 123


def test_things_worker_reports_automation_fallback_source(monkeypatch):
    monkeypatch.setattr(server, "_run_worker", lambda *_a, **_kw: {"ok": True, "data": [], "capabilities": {"database": {"state": "denied"}, "automation": {"state": "available"}}})
    assert server.run_worker("inbox")["source"] == "apple_events"


def test_snapshot_preserves_automation_origin_in_storage_and_responses(tmp_path_factory, monkeypatch, capsys):
    import json

    from clawbridge.protocol import ok_envelope
    from things3_mcp.providers.cache import CacheStore
    from things3_mcp_bridge import cache

    directory = tmp_path_factory.mktemp("t")
    store = CacheStore(directory / "snapshot.json")
    observations = {"database": {"state": "denied"}, "automation": {"state": "available"}}
    monkeypatch.setattr(server, "run_worker", lambda *_a, **_kw: ok_envelope({"inbox": []}, source="apple_events", capabilities=observations))
    monkeypatch.setattr(cache, "CacheStore", lambda: store)
    monkeypatch.setattr(server, "cache_status", store.status)
    with server.UnixHTTPServer(directory / "b.sock", token_file=directory / "b.token") as bridge:
        result = bridge.read_action("snapshot", {})
    assert result["source"] == "apple_events"
    assert result["capabilities"] == observations
    assert store.read_snapshot()["source"] == "apple_events"
    assert server.snapshot_once() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["source"] == "apple_events"
    assert output["capabilities"] == observations


def test_required_presence_keeps_empty_search_but_rejects_empty_mutation_title():
    from clawbridge.actions import InvalidRequestError
    from things3_mcp_bridge.actions import ACTIONS

    assert ACTIONS["search"].validate({"query": ""}) == {"query": ""}
    with pytest.raises(InvalidRequestError):
        ACTIONS["add_task"].validate({"title": ""})


def test_existing_things_routes_use_validated_actions_over_the_socket(tmp_path_factory, monkeypatch):
    import threading

    from clawbridge.protocol import ok_envelope
    from tests.test_clawbridge_transport import request

    directory = tmp_path_factory.mktemp("t")
    monkeypatch.setattr(server, "run_worker", lambda action, params=None, **_kw: ok_envelope({"action": action, "params": params}, outcome="succeeded"))
    with server.UnixHTTPServer(directory / "b.sock", token_file=directory / "b.token") as bridge:
        thread = threading.Thread(target=bridge.serve_forever, daemon=True)
        thread.start()
        try:
            for name in ("inbox", "today", "upcoming", "anytime", "someday", "projects", "areas", "tags", "trash"):
                assert request(bridge, "GET", f"/things/{name}?include_items=false")[1]["data"] == {"action": name, "params": {"include_items": False}}
            assert request(bridge, "GET", "/things/get/task-id")[1]["data"]["params"] == {"uuid": "task-id"}
            assert request(bridge, "GET", "/things/last/7d")[1]["data"]["params"]["period"] == "7d"
            for name in ("tasks", "todos", "projects", "areas", "tags"):
                assert request(bridge, "POST", f"/things/{name}", {})[1]["data"]["action"] == name
            assert request(bridge, "POST", "/things/search", {"query": ""})[1]["data"]["action"] == "search"
            for route, create, update in (("todo", "add_task", "update_task"), ("project", "add_project", "update_project")):
                response = request(bridge, "POST", f"/things/{route}", {"title": "synthetic"})[1]
                assert response["data"]["action"] == create and response["operation_id"]
                response = request(bridge, "PATCH", f"/things/{route}/object-id", {"completed": True})[1]
                assert response["data"] == {"action": update, "params": {"completed": True, "uuid": "object-id"}}
            assert request(bridge, "POST", "/things/tasks", {"filepath": "/elsewhere.sqlite"})[0] == 400
        finally:
            bridge.shutdown()
            thread.join(timeout=2)
