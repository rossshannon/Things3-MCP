"""Faults in a read are reported as what they are: a bad request, a missing item, a cache gap or a bridge fault.

None of them may be mistaken for an unavailable database, an empty result or a
write of unknown outcome. Nothing here starts a worker or touches Things.
"""

import json
import socket
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from clawbridge.protocol import error_envelope, ok_envelope
from tests.test_cache_fallback import SNAPSHOT_DATA, bridge, cache_file, write_cache  # noqa: F401 - fixtures
from tests.test_clawbridge_transport import request
from things3_mcp.providers.base import ProviderError
from things3_mcp.providers.bridge import BridgeThingsProvider
from things3_mcp.providers.cache import CacheStore, CacheThingsProvider
from things3_mcp_bridge import db_reader, server


class RefusingDatabase:
    """Stands in for things-py, which raises ValueError for values it does not accept."""

    def __init__(self, error):
        self.error = error

    def todos(self, **_filters):
        raise self.error


@pytest.fixture
def no_apple_events(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("A request the database refused must not be retried through Apple Events")

    monkeypatch.setattr(db_reader, "run_jxa_action", forbidden)


@pytest.mark.parametrize(
    ("raised", "error_code"),
    [(ValueError("Unrecognized status type: 'bogus'"), "invalid_request"), (ValueError("No such task uuid found: 'nope'"), "not_found")],
)
def test_a_filter_the_database_refuses_is_the_callers_fault_not_an_outage(monkeypatch, no_apple_events, raised, error_code):
    monkeypatch.setattr(db_reader, "direct_provider", lambda: RefusingDatabase(raised))
    with pytest.raises(ProviderError) as refused:
        db_reader.run_action("todos", {"status": "bogus"})
    assert refused.value.error_code == error_code and refused.value.outcome == "failed"
    assert db_reader.capability_observations()["database"]["state"] == "available"
    assert "bogus" not in refused.value.message and "nope" not in refused.value.message


def test_an_unreadable_database_still_falls_back_to_apple_events(monkeypatch):
    monkeypatch.setattr(db_reader, "direct_provider", lambda: RefusingDatabase(sqlite3.OperationalError("unable to open database file")))
    monkeypatch.setattr(db_reader, "run_jxa_action", lambda action, _params: {"read_by": action})
    assert db_reader.run_action("todos", {}) == {"read_by": "todos", "_source": "apple_events"}
    observed = db_reader.capability_observations()
    assert observed["database"]["state"] == "unavailable" and observed["automation"]["state"] == "available"


def test_a_write_refused_before_any_script_ran_says_nothing_about_automation():
    with pytest.raises(Exception) as refused:  # noqa: PT011 - the error class is the AppleScript layer's own
        db_reader.run_action("add_task", {"title": "   "})
    assert refused.value.error_code == "invalid_title"
    assert "automation" not in db_reader.capability_observations()


@pytest.mark.parametrize("error_code", ["invalid_request", "not_found"])
def test_a_refused_read_is_not_answered_from_the_snapshot(bridge, cache_file, error_code):  # noqa: F811
    write_cache(cache_file)
    bridge.replies["*"] = error_envelope(error_code, "App action did not complete", outcome="failed")
    status, envelope = request(bridge, "POST", "/things/todos", {"status": "incomplete"})
    assert status == 200 and envelope["ok"] is False
    assert envelope["error_code"] == error_code and "source" not in envelope


def test_a_snapshot_of_unexpected_shape_keeps_the_live_error_visible(bridge, cache_file, monkeypatch):  # noqa: F811
    write_cache(cache_file)
    bridge.replies["*"] = error_envelope("things_db_timeout", "App action did not complete", outcome="failed")
    monkeypatch.setattr(CacheThingsProvider, "inbox", lambda *_args, **_kwargs: 1 / 0)
    status, envelope = request(bridge, "GET", "/things/inbox")
    assert status == 200
    assert envelope["error_code"] == "things_db_timeout"
    assert envelope["cache_error"]["error_code"] == "cache_unreadable"


def test_a_snapshot_timestamp_without_an_offset_is_read_as_utc(bridge, cache_file):  # noqa: F811
    generated = (datetime.now(UTC) - timedelta(hours=3)).replace(tzinfo=None)
    CacheStore(cache_file).write_snapshot({"version": 1, "source": "live", "generated_at": generated.isoformat(), "data": SNAPSHOT_DATA})
    bridge.replies["*"] = error_envelope("things_db_timeout", "App action did not complete", outcome="failed")
    for path in ("/cache/status", "/auth-status", "/status"):
        assert request(bridge, "GET", path)[0] == 200
    age = request(bridge, "GET", "/cache/status")[1]["data"]["age_seconds"]
    assert 3 * 3600 - 60 <= age <= 3 * 3600 + 60
    status, envelope = request(bridge, "GET", "/things/inbox")
    assert status == 200 and envelope["source"] == "cache"
    assert 3 * 3600 - 60 <= envelope["cache_age_seconds"] <= 3 * 3600 + 60


def test_the_snapshot_says_what_it_cannot_answer_instead_of_returning_nothing(cache_file):  # noqa: F811
    data = {**SNAPSHOT_DATA, "projects": [{"uuid": "project-1", "type": "project", "title": "Plan", "status": "incomplete"}]}
    CacheStore(cache_file).write_snapshot({"version": 1, "source": "live", "generated_at": datetime.now().astimezone().isoformat(), "data": data})
    provider = CacheThingsProvider()
    assert [item["uuid"] for item in provider.tasks(type="project")] == ["project-1"]
    for unanswerable in (lambda: provider.projects(status="completed"), lambda: provider.tasks(type="heading"), lambda: provider.todos(trashed=True), lambda: provider.tasks(type="project", status=None)):
        with pytest.raises(ProviderError) as gap:
            unanswerable()
        assert gap.value.error_code == "cache_miss"
    assert provider.todos(trashed=False) == []


def snapshot_reply():
    return ok_envelope(SNAPSHOT_DATA, outcome="succeeded")


def test_a_snapshot_that_cannot_be_written_is_reported_as_a_cache_fault(bridge, cache_file, monkeypatch):  # noqa: F811
    def unwritable(*_args, **_kwargs):
        raise OSError("read-only file system")

    bridge.replies["snapshot"] = snapshot_reply()
    monkeypatch.setattr(server, "write_snapshot", unwritable)
    status, envelope = request(bridge, "POST", "/snapshot")
    assert status == 200 and envelope["ok"] is False
    assert envelope["error_code"] == "cache_unwritable" and envelope["outcome"] == "failed"
    assert not cache_file.exists()


def test_snapshot_once_reports_an_unwritable_cache_without_a_traceback(cache_file, monkeypatch, capsys):  # noqa: F811
    cache_file.parent.mkdir(mode=0o755)  # A cache directory other users can read is refused.
    monkeypatch.setattr(server, "run_worker", lambda *_args, **_kwargs: snapshot_reply())
    assert server.snapshot_once() == 1
    printed = json.loads(capsys.readouterr().out)
    assert printed["ok"] is False and printed["error_code"] == "cache_unwritable"


def test_a_write_to_a_bridge_that_is_not_listening_is_known_not_to_have_happened(tmp_path_factory):
    directory = tmp_path_factory.mktemp("b")
    path = directory / "b.sock"
    with socket.socket(socket.AF_UNIX) as stale:
        stale.bind(str(path))  # Bound but never listening: connections are refused.
        (directory / "b.token").write_text("synthetic-token")
        provider = BridgeThingsProvider(socket_path=path, token_file=directory / "b.token")
        with pytest.raises(ProviderError) as refused:
            provider.add_task({"title": "never sent"})
        assert refused.value.error_code == "bridge_unavailable"
        assert refused.value.outcome == "failed"
        assert refused.value.correlation_id
        with pytest.raises(ProviderError) as read:
            provider.inbox()
        assert read.value.error_code == "bridge_unavailable"


def test_a_non_numeric_client_timeout_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv("THINGS3_MCP_BRIDGE_TIMEOUT", "soon")
    with pytest.raises(ProviderError) as invalid:
        BridgeThingsProvider()
    assert invalid.value.error_code == "bridge_timeout_invalid"
