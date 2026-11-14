"""Look-back periods are validated once and mean the same thing in every tool."""

from datetime import datetime, timedelta

import pytest

from clawbridge.actions import InvalidRequestError
from things3_mcp import fast_server
from things3_mcp_bridge.actions import ACTIONS


class RecordingProvider:
    def __init__(self):
        self.calls = []

    def last(self, period, include_items=True):
        self.calls.append(("last", period))
        return []

    def tasks(self, **kwargs):
        self.calls.append(("tasks", kwargs))
        return []


@pytest.fixture
def provider(monkeypatch):
    recording = RecordingProvider()
    monkeypatch.setattr(fast_server, "get_provider", lambda: recording)
    return recording


@pytest.mark.parametrize(("period", "sent"), [("3d", "3d"), ("1w", "1w"), ("1y", "1y"), ("2m", "60d"), ("12m", "360d")])
def test_recent_translates_months_into_the_days_things_understands(provider, period, sent):
    assert "No items found" in fast_server.get_recent(period=period)
    assert provider.calls == [("last", sent)]


@pytest.mark.parametrize("period", ["", "bogus", "d", "m", "3h", "-3d", "3.5d", "3 d", "3dd", "١d", "99999d", None, 7])
def test_invalid_periods_are_refused_before_any_read(provider, period):
    for tool in (fast_server.get_recent, fast_server.get_logbook):
        assert tool(period=period).startswith("Error: Invalid period format")
    assert provider.calls == []


@pytest.mark.parametrize(("period", "days"), [("3d", 3), ("2w", 14), ("2m", 60), ("1y", 365)])
def test_logbook_looks_back_the_stated_number_of_days(provider, period, days):
    before = datetime.now()
    fast_server.get_logbook(period=period)
    after = datetime.now()
    ((name, filters),) = provider.calls
    assert name == "tasks" and filters["status"] == "completed"
    assert filters["stop_date"] in {f">={(moment - timedelta(days=days)).strftime('%Y-%m-%d')}" for moment in (before, after)}


def test_logbook_accepts_the_longest_expressible_period(provider):
    assert fast_server.get_logbook(period="9999y") == "No completed items found"
    ((_name, filters),) = provider.calls
    assert filters["stop_date"].startswith(">=")


@pytest.mark.parametrize("period", ["7d", "2w", "1y", "0d", "9999d"])
def test_bridge_accepts_things_durations(period):
    assert ACTIONS["last"].validate({"period": period}) == {"period": period}


@pytest.mark.parametrize("period", ["banana", "3h", "2m", "7", "d", "-7d", "7d ", "7d\n", "99999d", "7D", "../7d"])
def test_bridge_rejects_other_periods_before_starting_a_worker(period):
    with pytest.raises(InvalidRequestError):
        ACTIONS["last"].validate({"period": period})
