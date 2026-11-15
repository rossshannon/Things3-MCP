"""The helpers that remove live-test data, exercised against a scripted stand-in for Things."""

import re

import pytest

from tests import conftest
from things3_mcp.applescript_bridge import AppleScriptError


class ScriptedThings:
    """Answers the two scripts the sweep uses: list what matches a prefix, and delete one item by id.

    ``logbook`` holds completed to-dos, which ``every to do`` does not return.
    """

    def __init__(self, items, *, logbook=None, broken_kind=None, undeletable=()):
        self.items = {kind: dict(entries) for kind, entries in items.items()}
        self.logbook = dict(logbook or {})
        self.broken_kind = broken_kind
        self.undeletable = set(undeletable)
        self.deleted = []
        self.scripts = []

    def __call__(self, script, timeout=8):
        assert timeout == conftest.SWEEP_TIMEOUT_SECONDS
        self.scripts.append(script)
        deletion = re.search(r'delete (?:(to do|project) id "([^"]+)"|\(first (area|tag) whose id is "([^"]+)"\))', script)
        if deletion:
            kind = deletion.group(1) or deletion.group(3)
            item_id = deletion.group(2) or deletion.group(4)
            if item_id in self.undeletable:
                raise AppleScriptError("applescript_timeout", "Things did not confirm completion before the deadline", outcome="outcome_unknown")
            self.deleted.append(item_id)
            if item_id in self.logbook:
                del self.logbook[item_id]
            else:
                del self.items[kind][item_id]
            return ""
        kind, prefix = re.search(r'id of \(every (to do|project|area|tag) whose name starts with "([^"]+)"\)', script).groups()
        if kind == self.broken_kind:
            raise AppleScriptError("applescript_timeout", "Things did not confirm completion before the deadline", outcome="outcome_unknown")

        # AppleScript's "starts with" ignores case, as Things does.
        def matching(entries):
            return [(item_id, name) for item_id, name in entries.items() if name.lower().startswith(prefix.lower())]

        found = matching(self.items.get(kind, {}))
        if 'list "Logbook"' in script:
            found += matching(self.logbook)
        return "\n".join(item_id for item_id, _ in found) + "\x1e" + "\n".join(name for _, name in found)


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


def test_completed_test_to_dos_in_the_logbook_are_swept_too(things):
    scripted = things({"to do": {"T1": "mcp-test open"}}, logbook={"L1": "mcp-test done", "L2": "A real finished task"})
    assert conftest.sweep_live_test_items() == []
    assert scripted.deleted == ["T1", "L1"]
    assert scripted.logbook == {"L2": "A real finished task"}


def test_the_trash_is_never_filtered(things):
    """A name filter on a large Trash outlasts the Apple Event timeout and leaves Things busy."""
    scripted = things({"to do": {"T1": "mcp-test a"}, "project": {"P1": "mcp-test b"}})
    conftest.sweep_live_test_items()
    assert scripted.scripts and not any('"Trash"' in script for script in scripted.scripts)


def test_a_listing_whose_ids_and_names_do_not_line_up_is_refused(monkeypatch):
    monkeypatch.setattr(conftest, "run_applescript", lambda _script, timeout=8: "T1\nT2\x1emcp-test only one")
    with pytest.raises(ValueError, match="2 ids and 1 names"):
        conftest.live_test_items("to do")


def test_an_id_that_could_not_be_a_things_id_is_never_put_in_a_script(things):
    scripted = things({"to do": {'T1" & (do shell script "id") & "': "mcp-test hostile"}})
    assert conftest.live_test_items("to do") == []
    assert scripted.deleted == []
