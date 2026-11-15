"""The AppleScript read-back used by live tests, exercised against scripted replies."""

import ast
import re
from pathlib import Path

import pytest

from tests import conftest, live_reads

SEP = "\x1f"


def record(*, kind="to-do", title="mcp-test Buy milk", status="incomplete", tags="", deadline="", start_date="", project="", area="", notes=""):
    return SEP.join(["item", kind, title, status, tags, deadline, start_date, project, area, notes, "end"])


@pytest.fixture
def scripts(monkeypatch):
    """Answer every script with the queued reply and keep what was sent."""

    class Scripted:
        def __init__(self):
            self.sent = []
            self.reply = ""

        def __call__(self, script, timeout=8):
            assert timeout == live_reads.READ_TIMEOUT_SECONDS
            self.sent.append(script)
            return self.reply

    scripted = Scripted()
    monkeypatch.setattr(conftest, "run_applescript", scripted)
    return scripted


def test_an_item_is_returned_with_the_field_names_the_assertions_use(scripts):
    scripts.reply = record(tags="mcp-test-home, mcp-test-urgent", deadline="2026-12-01", start_date="2026-11-20", project="P1", area="A1", notes="line one\nline two")

    item = live_reads.get("T1")

    assert item == {
        "uuid": "T1",
        "type": "to-do",
        "title": "mcp-test Buy milk",
        "status": "incomplete",
        "tags": ["mcp-test-home", "mcp-test-urgent"],
        "deadline": "2026-12-01",
        "start_date": "2026-11-20",
        "project": "P1",
        "area": "A1",
        "notes": "line one\nline two",
    }
    (script,) = scripts.sent
    assert 'project id "T1"' in script and 'to do id "T1"' in script
    assert "ITEM_ID" not in script


def test_unset_dates_and_containers_read_as_none(scripts):
    scripts.reply = record(kind="project", status="completed")

    item = live_reads.get("P1")

    assert item["type"] == "project"
    assert item["status"] == "completed"
    assert item["tags"] == []
    assert item["deadline"] is None and item["start_date"] is None
    assert item["project"] is None and item["area"] is None
    assert item["notes"] == ""


def test_an_id_things_does_not_know_reads_as_none(scripts):
    scripts.reply = "missing"

    assert live_reads.get("T404") is None


@pytest.mark.parametrize("item_id", [None, False, "", 'T1" & (do shell script "id") & "', "T 1"])
def test_only_a_plain_id_reaches_a_script(scripts, item_id):
    assert live_reads.get(item_id) is None
    assert live_reads.in_list(item_id, "Today") is False
    assert scripts.sent == []


def test_a_record_of_the_wrong_shape_is_an_error_rather_than_a_guess(scripts):
    scripts.reply = SEP.join(["item", "to-do", "only a title", "end"])

    with pytest.raises(ValueError, match="2 fields"):
        live_reads.get("T1")


@pytest.mark.parametrize(("reply", "expected"), [("listed", True), ("absent", False)])
def test_list_membership_follows_the_reply(scripts, reply, expected):
    scripts.reply = reply

    assert live_reads.in_list("T1", "Someday") is expected
    (script,) = scripts.sent
    assert 'list "Someday" whose id is "T1"' in script
    assert "LIST_NAME" not in script and "ITEM_ID" not in script


def test_only_built_in_lists_can_be_asked_about(scripts):
    with pytest.raises(ValueError, match="Unknown built-in list"):
        live_reads.in_list("T1", 'Today" & "')
    assert scripts.sent == []


def test_the_scripts_are_balanced():
    for script in (live_reads._GET_SCRIPT, live_reads._IN_LIST_SCRIPT):
        assert script.count('"') % 2 == 0
        outside_strings = "".join(script.split('"')[::2])
        assert outside_strings.count("(") == outside_strings.count(")")
        opened = len(re.findall(r"^\s*(?:tell application|try|on isoDate)\b", script, re.M))
        closed = len(re.findall(r"^\s*end (?:tell|try|isoDate)\b", script, re.M))
        assert opened == closed


def test_live_tests_do_not_open_the_things_database_themselves():
    """A live test process holds the Automation permission only; reads go through AppleScript or the bridge."""
    offenders = []
    for path in sorted(Path(__file__).parent.glob("*.py")):
        source = path.read_text()
        if "pytest.mark.live_things" not in source:
            continue
        if re.search(r"^\s*(?:import things\b(?!3)|from things import)", source, re.M) or re.search(r'THINGS3_MCP_PROVIDER",\s*"direct"', source):
            offenders.append(path.name)
    assert offenders == []


def _mcp_tool_names(node):
    """Names a module or function binds to the MCP tool module or to anything imported from it."""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.ImportFrom) and sub.module == "things3_mcp.fast_server":
            names |= {alias.asname or alias.name for alias in sub.names}
        if isinstance(sub, ast.ImportFrom) and sub.module == "things3_mcp" and any(alias.name == "fast_server" for alias in sub.names):
            names.add("fast_server")
    return names


def _marks(decorators):
    return {ast.unparse(decorator).removeprefix("pytest.mark.") for decorator in decorators}


def _module_marks(tree):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
            return _marks(node.value.elts if isinstance(node.value, ast.List) else [node.value])
    return set()


def test_live_tests_that_call_an_mcp_tool_say_they_need_the_bridge():
    """The MCP tools go through the bridge; a live test without the marker must work with Automation alone."""
    unmarked = []
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        tree = ast.parse(path.read_text())
        module_marks = _module_marks(tree)
        module_tools = {name for node in tree.body if isinstance(node, ast.ImportFrom) for name in _mcp_tool_names(node)}
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            marks = module_marks | _marks(node.decorator_list)
            tools = module_tools | _mcp_tool_names(node)
            uses_a_tool = any(isinstance(sub, ast.Name) and sub.id in tools for sub in ast.walk(node))
            if "live_things" in marks and uses_a_tool and "things_bridge" not in marks:
                unmarked.append(f"{path.name}::{node.name}")
    assert unmarked == []


@pytest.mark.parametrize(
    ("list_name", "status", "someday", "start", "expected"),
    [
        ("Anytime", "incomplete", "no", "", True),
        ("Anytime", "incomplete", "yes", "", False),
        ("Anytime", "incomplete", "no", "2026-11-15", False),
        ("Anytime", "completed", "no", "", False),
        ("Today", "incomplete", "no", "2026-11-15", True),
        ("Today", "incomplete", "no", "2026-11-01", True),
        ("Today", "incomplete", "no", "2026-12-01", False),
        ("Today", "incomplete", "no", "", False),
        ("Upcoming", "incomplete", "no", "2026-12-01", True),
        ("Upcoming", "incomplete", "no", "2026-11-15", False),
        ("Someday", "incomplete", "yes", "", False),
        ("Inbox", "incomplete", "no", "", False),
    ],
)
def test_a_project_is_placed_by_its_status_and_start_date(scripts, monkeypatch, list_name, status, someday, start, expected):
    """Things names projects only in Someday's to dos, so the other lists are worked out."""

    class FixedDate:
        @staticmethod
        def today():
            import datetime

            return datetime.date(2026, 11, 15)

    monkeypatch.setattr(live_reads, "date", FixedDate)
    scripts.reply = f"project\t{status}\t{someday}\t{start}"
    assert live_reads.in_list("P1", list_name) is expected
    (script,) = scripts.sent
    assert 'project id "P1"' in script and 'list "Someday" whose id is "P1"' in script


def test_an_unexpected_membership_reply_is_an_error(scripts):
    scripts.reply = "true"
    with pytest.raises(ValueError, match="unexpected"):
        live_reads.in_list("T1", "Today")
