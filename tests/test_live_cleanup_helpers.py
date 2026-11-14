"""The helpers that remove live-test data, exercised against a scripted stand-in for Things."""

import re

import pytest

from tests import conftest
from things3_mcp.applescript_bridge import AppleScriptError


class ScriptedThings:
    """Answers the two scripts the sweep uses: list what matches a prefix, and delete one item by id."""

    def __init__(self, items, *, broken_kind=None, undeletable=()):
        self.items = {kind: dict(entries) for kind, entries in items.items()}
        self.broken_kind = broken_kind
        self.undeletable = set(undeletable)
        self.deleted = []

    def __call__(self, script, timeout=8):
        assert timeout == conftest.SWEEP_TIMEOUT_SECONDS
        deletion = re.search(r'delete \(first (to do|project|area|tag) whose id is "([^"]+)"\)', script)
        if deletion:
            kind, item_id = deletion.groups()
            if item_id in self.undeletable:
                raise AppleScriptError("applescript_timeout", "Things did not confirm completion before the deadline", outcome="outcome_unknown")
            self.deleted.append(item_id)
            del self.items[kind][item_id]
            return ""
        kind, prefix = re.search(r'id of \(every (to do|project|area|tag) whose name starts with "([^"]+)"\)\n\s+set foundNames', script).groups()
        if kind == self.broken_kind:
            raise AppleScriptError("applescript_timeout", "Things did not confirm completion before the deadline", outcome="outcome_unknown")
        # AppleScript's "starts with" ignores case, as Things does.
        return "".join(f"{item_id}\t{name}\n" for item_id, name in self.items.get(kind, {}).items() if name.lower().startswith(prefix.lower()))


@pytest.fixture
def things(monkeypatch):
    def install(*args, **kwargs):
        scripted = ScriptedThings(*args, **kwargs)
        monkeypatch.setattr(conftest, "run_applescript", scripted)
        return scripted

    return install


def test_only_items_with_the_exact_test_prefix_are_swept(things):
    scripted = things(
        {
            "to do": {"T1": "mcp-test Buy milk", "T2": "MCP-Test plan for the server", "T3": "Unrelated"},
            "project": {"P1": "mcp-test Project"},
            "area": {"A1": "mcp-test-area1", "A2": "mcp-testing notes"},
            "tag": {"G1": "mcp-test-urgent", "G2": "Mcp-Test-Mine"},
        }
    )
    assert conftest.sweep_live_test_items() == []
    assert scripted.deleted == ["T1", "P1", "A1", "G1"]
    assert scripted.items == {"to do": {"T2": "MCP-Test plan for the server", "T3": "Unrelated"}, "project": {}, "area": {"A2": "mcp-testing notes"}, "tag": {"G2": "Mcp-Test-Mine"}}


def test_one_kind_failing_does_not_leave_the_others_behind(things):
    scripted = things({"to do": {"T1": "mcp-test a"}, "project": {"P1": "mcp-test b"}, "area": {"A1": "mcp-test-c"}, "tag": {"G1": "mcp-test-d"}}, broken_kind="project")
    problems = conftest.sweep_live_test_items()
    assert scripted.deleted == ["T1", "A1", "G1"]
    assert problems == ["sweep of projects failed: AppleScriptError", "could not check for leftover projects: AppleScriptError"]


def test_anything_that_could_not_be_deleted_is_named(things, capsys):
    scripted = things({"to do": {"T1": "mcp-test stuck", "T2": "mcp-test fine"}}, undeletable={"T1"})
    assert conftest.sweep_live_test_items() == ["to do left behind: mcp-test stuck (ID: T1)"]
    assert scripted.deleted == ["T2"]
    assert conftest.verify_cleanup() is False
    assert "mcp-test stuck" in capsys.readouterr().out


def test_a_tracked_cleanup_keeps_going_past_an_item_it_cannot_delete(things, monkeypatch):
    scripted = things({"to do": {"T1": "mcp-test tracked"}, "tag": {"G1": "mcp-test-tag"}})
    monkeypatch.setattr(conftest, "_require_live_cleanup", lambda: None)

    def refuse(_item_id):
        raise AppleScriptError("applescript_timeout", "Things did not confirm completion before the deadline", outcome="outcome_unknown")

    monkeypatch.setattr(conftest, "delete_todo_by_id", refuse)
    tracker = conftest.CleanupTracker()
    tracker.add_todo("T1")
    tracker.cleanup()
    assert scripted.deleted == ["T1", "G1"] and tracker.problems == []
