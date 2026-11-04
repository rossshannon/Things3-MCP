"""Synthetic regressions for provider, cache and response-formatting review findings."""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import pytest

from clawbridge.protocol import error_envelope, ok_envelope
from things3_mcp import fast_server
from things3_mcp.formatters import format_project, format_todo
from things3_mcp.providers import AutoThingsProvider, ProviderError
from things3_mcp.providers.bridge import BridgeThingsProvider
from things3_mcp.providers.cache import CacheStore, CacheThingsProvider


class ResponseClient:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def request(self, *_args, **_kwargs):
        return SimpleNamespace(json=lambda: self.payload)


def bridge_provider(monkeypatch, payload):
    provider = BridgeThingsProvider()
    monkeypatch.setattr(provider, "_client", lambda: ResponseClient(payload))
    return provider


def cache_provider(tmp_path, rows):
    store = CacheStore(tmp_path / "snapshot.json")
    store.write_snapshot({"source": "sqlite", "data": {"todos": rows}})
    return CacheThingsProvider(store)


def test_unknown_cache_timestamp_reaches_mcp_as_unknown_age(monkeypatch):
    payload = ok_envelope([{"uuid": "task", "title": "Cached task", "type": "to-do"}], source="cache", generated_at=None, snapshot_source="sqlite")
    provider = bridge_provider(monkeypatch, payload)
    monkeypatch.setattr(fast_server, "get_provider", lambda: provider)
    result = fast_server.get_inbox()
    assert "Cached task" in result
    assert "Read source: cache" in result
    assert "Snapshot age: unknown" in result
    assert "bridge_protocol_error" not in result


@pytest.mark.parametrize("metadata", [{"generated_at": 123}, {"source": None}, {"snapshot_source": None}, {"cache_age_seconds": None}])
def test_nullable_timestamp_does_not_relax_other_envelope_fields(monkeypatch, metadata):
    provider = bridge_provider(monkeypatch, {"ok": True, "data": [], **metadata})
    with pytest.raises(ProviderError, match="invalid or unsupported envelope"):
        provider.inbox()


@pytest.mark.parametrize("field", ["area", "project", "heading", "start_date", "stop_date", "deadline"])
@pytest.mark.parametrize("expected,ids", [(True, ["present"]), (False, ["null", "absent"])])
def test_cache_boolean_filters_match_presence(tmp_path, field, expected, ids):
    provider = cache_provider(tmp_path, [{"uuid": "present", field: "value"}, {"uuid": "null", field: None}, {"uuid": "absent"}])
    assert [row["uuid"] for row in provider.todos(**{field: expected})] == ids


@pytest.mark.parametrize("field,value", [("area", "area-id"), ("project", "project-id"), ("heading", "heading-id"), ("start_date", "2026-11-04"), ("deadline", "2026-11-04")])
def test_cache_exact_filters_keep_their_match(tmp_path, field, value):
    provider = cache_provider(tmp_path, [{"uuid": "match", field: value}, {"uuid": "other", field: "other"}])
    assert [row["uuid"] for row in provider.todos(**{field: value})] == ["match"]


@pytest.mark.parametrize("field", ["start_date", "stop_date", "deadline"])
@pytest.mark.parametrize("expression", [">=2026-11-04", "past", "future"])
def test_unsupported_cache_date_expressions_are_explicit(tmp_path, field, expression):
    provider = cache_provider(tmp_path, [{"uuid": "matching", field: "2026-11-05"}])
    with pytest.raises(ProviderError) as error:
        provider.todos(**{field: expression})
    assert error.value.error_code == "cache_unsupported"


def test_stop_date_string_does_not_guess_timezone_from_snapshot(tmp_path):
    provider = cache_provider(tmp_path, [{"uuid": "completed", "stop_date": "2026-11-04 00:30:00"}])
    with pytest.raises(ProviderError) as error:
        provider.todos(stop_date="2026-11-04")
    assert error.value.error_code == "cache_unsupported"


@pytest.mark.parametrize("method", ["tasks", "todos"])
@pytest.mark.parametrize("status", ["completed", "canceled", None])
def test_incomplete_snapshot_rejects_uncaptured_status_coverage(tmp_path, method, status):
    provider = cache_provider(tmp_path, [{"uuid": "open", "status": "incomplete"}, {"uuid": "incidental", "status": "completed"}])
    with pytest.raises(ProviderError) as error:
        getattr(provider, method)(status=status)
    assert error.value.error_code == "cache_miss"
    assert "incomplete" in str(error.value)


@pytest.mark.parametrize("automatic", [False, True])
def test_logbook_range_does_not_report_missing_coverage_as_empty(monkeypatch, tmp_path, automatic):
    cache = cache_provider(tmp_path, [{"uuid": "completed", "title": "Captured incidentally", "type": "to-do", "status": "completed", "stop_date": "2026-11-04 12:30:00"}])

    class Unavailable:
        def tasks(self, **_kwargs):
            raise ProviderError("bridge_unavailable", "Live access is unavailable")

    provider = AutoThingsProvider(providers=[Unavailable(), cache]) if automatic else cache
    monkeypatch.setattr(fast_server, "get_provider", lambda: provider)
    result = fast_server.get_logbook("7d")
    assert "No completed items found" not in result
    assert "cache_miss" in result
    assert "incomplete" in result


@pytest.mark.parametrize("success", [True, False])
def test_completion_persistence_warning_reaches_mcp_and_error_data(monkeypatch, success):
    warning = "Completion could not be persisted. Retain this response for recovery."
    metadata = {"operation_id": "operation", "outcome": "succeeded" if success else "failed", "journal_warning": warning}
    payload = ok_envelope({"id": "created"}, **metadata) if success else error_envelope("automation_denied", "Permission denied", **metadata)
    provider = bridge_provider(monkeypatch, payload)
    monkeypatch.setattr(fast_server, "get_provider", lambda: provider)
    monkeypatch.setattr(fast_server, "_resolve_todo_location", lambda _uuid: "Inbox")
    result = fast_server.add_task("Synthetic task")
    assert warning in result
    assert ("Successfully created" in result) is success
    assert "outcome_unknown" not in result
    if success:
        assert provider.add_task({"title": "Synthetic task"})["journal_warning"] == warning
    else:
        with pytest.raises(ProviderError) as error:
            provider.add_task({"title": "Synthetic task"})
        assert error.value.to_dict()["journal_warning"] == warning


@pytest.mark.parametrize("warning", [None, [], 7, "x" * 1025])
def test_completion_persistence_warning_is_a_bounded_string(monkeypatch, warning):
    provider = bridge_provider(monkeypatch, ok_envelope({"id": "created"}, outcome="succeeded", journal_warning=warning))
    with pytest.raises(ProviderError) as error:
        provider.add_task({"title": "Synthetic task"})
    assert error.value.outcome == "outcome_unknown"


@pytest.mark.parametrize(
    "formatter,item",
    [
        (format_todo, {"uuid": "task", "type": "to-do", "title": "Task", "project": "project", "project_title": "Project", "area": "area", "area_title": "Area"}),
        (format_project, {"uuid": "project", "title": "Project", "area": "area", "area_title": "Area"}),
    ],
)
def test_joined_parent_titles_do_not_require_lookups(formatter, item):
    result = formatter(item, get_item=lambda _uuid: pytest.fail("Joined parent title must be used"))
    assert "Area: Area" in result
    if formatter is format_todo:
        assert "Project: Project" in result


class ListProvider:
    def __init__(self, *, supplied_titles, missing_parent=False):
        self.lookups = Counter()
        self.missing_parent = missing_parent
        self.rows = [{"uuid": str(index), "title": f"Task {index}", "type": "to-do", "project": "project", "area": "area"} for index in range(50)]
        if supplied_titles:
            for row in self.rows:
                row.update(project_title="Project", area_title="Area")

    def get(self, uuid):
        self.lookups[uuid] += 1
        if self.missing_parent:
            raise ProviderError("bridge_unavailable", "Parent unavailable")
        return {"title": uuid.title()}

    def inbox(self, **_kwargs):
        return self.rows

    anytime = inbox

    def projects(self, **_kwargs):
        return [{**row, "type": "project"} for row in self.rows]

    def todos(self, **_kwargs):
        return []

    def last(self, *_args, **_kwargs):
        return [{**row, "type": "project" if index % 2 else "to-do"} for index, row in enumerate(self.rows)]


@pytest.mark.parametrize("tool,args", [("get_inbox", ()), ("get_random_inbox", (50,)), ("get_random_anytime", (50,)), ("get_projects", ()), ("get_recent", ("7d",))])
@pytest.mark.parametrize("supplied_titles,missing_parent", [(True, False), (False, False), (False, True)])
def test_parent_lookup_cache_is_shared_only_within_one_response(monkeypatch, tool, args, supplied_titles, missing_parent):
    provider = ListProvider(supplied_titles=supplied_titles, missing_parent=missing_parent)
    monkeypatch.setattr(fast_server, "get_provider", lambda: provider)
    operation = getattr(fast_server, tool)
    assert "Task 49" in operation(*args)
    assert max(provider.lookups.values(), default=0) == (0 if supplied_titles else 1)
    assert "Task 49" in operation(*args)
    assert max(provider.lookups.values(), default=0) == (0 if supplied_titles else 2)
