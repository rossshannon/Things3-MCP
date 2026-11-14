"""Cache fallback over the real bridge socket: labelled, honest about gaps, and kept recent."""

import os
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from clawbridge.protocol import error_envelope, ok_envelope
from tests.test_clawbridge_transport import request
from things3_mcp.providers.cache import CacheStore
from things3_mcp_bridge import server

CHECKLIST = [{"title": "Step one", "type": "checklist-item", "status": "incomplete"}]
SNAPSHOT_DATA = {
    "inbox": [{"title": "Inbox item", "uuid": "inbox-1", "type": "to-do", "notes": "alpha", "checklist": CHECKLIST}],
    "today": [],
    "upcoming": [],
    "anytime": [],
    "someday": [],
    "todos": [{"title": "Searchable", "uuid": "todo-1", "type": "to-do", "notes": "needle", "checklist": CHECKLIST}],
    "projects": [],
    "areas": [],
    "tags": [],
}


@pytest.fixture
def cache_file(tmp_path_factory, monkeypatch):
    path = tmp_path_factory.mktemp("c") / "cache" / "latest.json"
    monkeypatch.setenv("THINGS3_MCP_CACHE_FILE", str(path))
    return path


def write_cache(path, *, age=timedelta(hours=2), source="live"):
    generated = datetime.now(UTC) - age
    CacheStore(path).write_snapshot({"version": 1, "source": source, "generated_at": generated.isoformat(), "data": SNAPSHOT_DATA})
    os.utime(path, (generated.timestamp(), generated.timestamp()))


@pytest.fixture
def bridge(tmp_path_factory, monkeypatch):
    """A Things bridge whose worker replies come from ``bridge.replies``."""
    directory = tmp_path_factory.mktemp("b")
    calls = []
    replies = {}

    def worker(action, params=None, **_kwargs):
        calls.append(action)
        reply = replies.get(action, replies.get("*"))
        return reply() if callable(reply) else reply

    monkeypatch.setattr(server, "run_worker", worker)
    with server.UnixHTTPServer(directory / "b.sock", token_file=directory / "b.token") as running:
        running.calls, running.replies = calls, replies
        thread = threading.Thread(target=running.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield running
        finally:
            running.shutdown()
            thread.join(timeout=2)
            if running.snapshot_refresh_thread is not None:
                running.snapshot_refresh_thread.join(timeout=2)


def live_failure():
    return error_envelope("things_db_timeout", "App action did not complete", outcome="failed")


def test_failed_live_read_serves_the_snapshot_with_its_age_and_the_live_error(bridge, cache_file):
    write_cache(cache_file, age=timedelta(days=4, hours=14))
    bridge.replies["*"] = live_failure()
    status, envelope = request(bridge, "GET", "/things/inbox")
    assert status == 200 and envelope["ok"] is True
    assert envelope["source"] == "cache"
    assert envelope["data"][0]["title"] == "Inbox item"
    assert envelope["cache_age_seconds"] == pytest.approx(timedelta(days=4, hours=14).total_seconds(), abs=5)
    assert envelope["live_error"]["error_code"] == "things_db_timeout"


@pytest.mark.parametrize(("path", "method", "body"), [("/things/inbox", "GET", None), ("/things/search", "POST", {"query": "needle"}), ("/things/todos", "POST", {})])
def test_cached_reads_include_nested_items_only_when_asked(bridge, cache_file, path, method, body):
    write_cache(cache_file)
    bridge.replies["*"] = live_failure()
    with_items = request(bridge, method, path + ("?include_items=true" if method == "GET" else ""), None if body is None else {**body, "include_items": True})[1]
    without_items = request(bridge, method, path + ("?include_items=false" if method == "GET" else ""), None if body is None else {**body, "include_items": False})[1]
    assert with_items["data"][0]["checklist"] == CHECKLIST
    assert "checklist" not in without_items["data"][0]
    assert without_items["data"][0]["title"] == with_items["data"][0]["title"]


def test_failed_recent_read_reports_both_errors_instead_of_dropping_the_connection(bridge, cache_file):
    """The snapshot has no creation-date index, so "last" cannot be answered from it."""
    write_cache(cache_file)
    bridge.replies["*"] = live_failure()
    status, envelope = request(bridge, "GET", "/things/last/7d")
    assert status == 200 and envelope["ok"] is False
    assert envelope["error_code"] == "things_db_timeout"
    assert envelope["cache_error"]["error_code"] == "cache_miss"
    assert request(bridge, "GET", "/health")[0] == 200


def test_failed_live_read_without_a_snapshot_reports_that_too(bridge, cache_file):
    bridge.replies["*"] = live_failure()
    envelope = request(bridge, "GET", "/things/today")[1]
    assert envelope["ok"] is False and envelope["error_code"] == "things_db_timeout"
    assert envelope["cache_error"]["error_code"] == "cache_missing"


def test_writes_never_fall_back_to_the_snapshot(bridge, cache_file):
    write_cache(cache_file)
    bridge.replies["*"] = error_envelope("applescript_failed", "App action did not complete", outcome="outcome_unknown")
    envelope = request(bridge, "POST", "/things/todo", {"title": "synthetic"})[1]
    assert envelope["ok"] is False and envelope["outcome"] == "outcome_unknown"
    assert "source" not in envelope
    assert bridge.calls == ["add_task"]


def refreshed(bridge):
    thread = bridge.snapshot_refresh_thread
    if thread is not None:
        thread.join(timeout=3)
        assert not thread.is_alive()
    return bridge.calls.count("snapshot")


@pytest.fixture
def refreshing(monkeypatch):
    monkeypatch.setenv(server.SNAPSHOT_REFRESH_ENV, "3600")


def test_successful_live_read_renews_a_stale_snapshot_in_the_background(bridge, cache_file, refreshing):
    write_cache(cache_file, age=timedelta(days=4))
    fresh = {**SNAPSHOT_DATA, "inbox": [{"title": "Fresh item", "uuid": "inbox-2", "type": "to-do"}]}
    bridge.replies.update({"inbox": ok_envelope([], outcome="succeeded"), "snapshot": ok_envelope(fresh, outcome="succeeded")})
    assert request(bridge, "GET", "/things/inbox")[1]["source"] == "live"
    assert refreshed(bridge) == 1
    snapshot = CacheStore(cache_file).read_snapshot()
    assert snapshot["data"]["inbox"][0]["title"] == "Fresh item"
    assert snapshot["source"] == "live"
    assert CacheStore(cache_file).status()["age_seconds"] < 60


def test_first_successful_live_read_creates_a_missing_snapshot(bridge, cache_file, refreshing):
    bridge.replies.update({"inbox": ok_envelope([], outcome="succeeded"), "snapshot": ok_envelope(SNAPSHOT_DATA, outcome="succeeded")})
    request(bridge, "GET", "/things/inbox")
    assert refreshed(bridge) == 1
    assert CacheStore(cache_file).read_snapshot()["data"]["todos"][0]["title"] == "Searchable"


def test_recent_snapshot_is_left_alone(bridge, cache_file, refreshing):
    write_cache(cache_file, age=timedelta(minutes=5))
    bridge.replies["*"] = ok_envelope([], outcome="succeeded")
    request(bridge, "GET", "/things/inbox")
    assert refreshed(bridge) == 0


def test_snapshot_age_is_checked_at_most_once_a_minute(bridge, cache_file, refreshing):
    write_cache(cache_file, age=timedelta(days=4))
    bridge.replies.update({"inbox": ok_envelope([], outcome="succeeded"), "snapshot": live_failure()})
    for _ in range(3):
        request(bridge, "GET", "/things/inbox")
        refreshed(bridge)
    assert bridge.calls.count("snapshot") == 1


@pytest.mark.parametrize("setting", ["0", "-1", "inf", "nan", "never"])
def test_renewal_can_be_disabled_and_ignores_unusable_settings(bridge, cache_file, monkeypatch, setting):
    monkeypatch.setenv(server.SNAPSHOT_REFRESH_ENV, setting)
    bridge.replies["*"] = ok_envelope([], outcome="succeeded")
    request(bridge, "GET", "/things/inbox")
    expected = 1 if setting == "never" else 0  # unparseable text falls back to the default interval
    assert refreshed(bridge) == expected


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(lambda: live_failure(), id="snapshot read fails"),
        pytest.param(lambda: {**ok_envelope(SNAPSHOT_DATA, outcome="succeeded"), "source": "apple_events"}, id="snapshot comes from the limited Apple Events backend"),
        pytest.param(lambda: 1 / 0, id="snapshot worker raises"),
    ],
)
def test_unusable_renewal_keeps_the_existing_snapshot_and_the_read_succeeds(bridge, cache_file, refreshing, reply, capfd):
    write_cache(cache_file, age=timedelta(days=4))
    before = cache_file.read_bytes()
    bridge.replies.update({"inbox": ok_envelope([], outcome="succeeded"), "snapshot": reply})
    assert request(bridge, "GET", "/things/inbox")[1]["ok"] is True
    assert refreshed(bridge) == 1
    assert cache_file.read_bytes() == before
    assert bridge.workers.acquire(blocking=False) and bridge.workers.acquire(blocking=False) and bridge.workers.acquire(blocking=False) and bridge.workers.acquire(blocking=False)
    for _ in range(4):
        bridge.workers.release()
    assert "Traceback" not in capfd.readouterr().err


def test_fallback_and_apple_events_reads_never_trigger_renewal(bridge, cache_file, refreshing):
    write_cache(cache_file, age=timedelta(days=4))
    bridge.replies["*"] = live_failure()
    assert request(bridge, "GET", "/things/inbox")[1]["source"] == "cache"
    bridge.replies["*"] = {**ok_envelope([], outcome="succeeded"), "source": "apple_events"}
    assert request(bridge, "GET", "/things/inbox")[1]["source"] == "apple_events"
    assert refreshed(bridge) == 0


def test_renewal_is_skipped_while_every_worker_slot_is_busy(bridge, cache_file, refreshing):
    write_cache(cache_file, age=timedelta(days=4))
    bridge.replies["*"] = ok_envelope([], outcome="succeeded")
    for _ in range(4):
        assert bridge.workers.acquire(blocking=False)
    try:
        assert bridge.refresh_stale_snapshot() is False
    finally:
        for _ in range(4):
            bridge.workers.release()
    assert refreshed(bridge) == 0
    time.sleep(0)
    assert bridge.snapshot_refresh.acquire(blocking=False)
    bridge.snapshot_refresh.release()


@pytest.mark.parametrize(
    ("seconds", "described"),
    [(0, "0 seconds"), (1, "1 second"), (59, "59 seconds"), (60, "1 minute"), (3725, "1 hour 2 minutes"), (86400, "1 day"), (396000, "4 days 14 hours"), (90061.9, "1 day 1 hour"), (-5, "0 seconds")],
)
def test_snapshot_age_is_described_in_its_two_largest_units(seconds, described):
    from things3_mcp import fast_server

    assert fast_server._describe_age(seconds) == described


@pytest.mark.parametrize(("age", "stale"), [(timedelta(hours=2), False), (timedelta(days=4, hours=14), True)])
def test_tool_output_states_the_snapshot_age_and_warns_once_it_is_stale(cache_file, monkeypatch, age, stale):
    from things3_mcp import fast_server
    from things3_mcp.providers import AutoThingsProvider, CacheThingsProvider, ProviderError

    write_cache(cache_file, age=age)

    class Unavailable:
        def inbox(self, **_kwargs):
            raise ProviderError("bridge_unavailable", "offline")

    monkeypatch.setattr(fast_server, "get_provider", lambda: AutoThingsProvider(providers=[Unavailable(), CacheThingsProvider(CacheStore(cache_file))]))
    result = fast_server.get_inbox()
    assert "Inbox item" in result
    assert f"Snapshot age: {'4 days 14 hours' if stale else '2 hours'}." in result
    assert ("may be out of date" in result) is stale
    assert "Live read failed: bridge_unavailable" in result
