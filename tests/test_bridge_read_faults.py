"""Faults in a read are reported as what they are: a bad request, a missing item, a cache gap or a bridge fault.

None of them may be mistaken for an unavailable database, an empty result or a
write of unknown outcome. Nothing here starts a worker or touches Things.
"""

import sqlite3

import pytest

from clawbridge.protocol import error_envelope
from tests.test_cache_fallback import SNAPSHOT_DATA, bridge, cache_file, write_cache  # noqa: F401 - fixtures
from tests.test_clawbridge_transport import request
from things3_mcp.providers.base import ProviderError
from things3_mcp_bridge import db_reader


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
