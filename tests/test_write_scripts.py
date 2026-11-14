"""The AppleScript generated for writes, checked without running it.

``run_applescript`` is replaced by a recorder, so these tests pin what would be
sent to Things for each request and never touch the app.
"""

from datetime import date, timedelta

import pytest

from things3_mcp import applescript_bridge as ab
from things3_mcp import fast_server
from things3_mcp.providers.base import ProviderError
from things3_mcp.providers.direct import DirectThingsProvider


@pytest.fixture
def scripts(monkeypatch):
    sent = []

    def record(script, timeout=8):
        sent.append(script)
        return "true" if "theTodo" in script or "theProject" in script else "NewItemId123"

    monkeypatch.setattr(ab, "run_applescript", record)
    monkeypatch.setattr(ab, "ensure_things_ready", lambda: True)
    return sent


def status_lines(script):
    return [line.strip() for line in script.splitlines() if "set status of" in line]


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({}, []),
        ({"completed": True}, ["completed"]),
        ({"canceled": True}, ["canceled"]),
        ({"completed": False}, ["open"]),
        ({"canceled": False}, ["open"]),
        ({"completed": False, "canceled": False}, ["open"]),
        ({"completed": True, "canceled": False}, ["completed"]),
        ({"completed": False, "canceled": True}, ["canceled"]),
        ({"completed": True, "canceled": True}, ["canceled"]),
    ],
)
@pytest.mark.parametrize(("update", "reference"), [(ab.update_todo, "theTodo"), (ab.update_project, "theProject")])
def test_status_flags_produce_one_status_change_that_means_what_was_asked(scripts, update, reference, flags, expected):
    update(id="item-id", **flags)
    assert status_lines(scripts[0]) == [f"set status of {reference} to {status}" for status in expected]


def test_text_reaches_things_unaltered(scripts):
    ab.add_todo(title="C++ a+b 100%20", notes="https://example.com/?q=a+b&x=1%20y")
    assert 'name:"C++ a+b 100%20"' in scripts[0]
    assert 'notes:"https://example.com/?q=a+b&x=1%20y"' in scripts[0]


def test_tools_pass_text_to_the_provider_unaltered(monkeypatch):
    seen = {}

    class Provider:
        def add_task(self, params):
            seen.update(params)
            return {"id": "new-id"}

        def get(self, _uuid):
            return None

    monkeypatch.setattr(fast_server, "get_provider", Provider)
    fast_server.add_task(title="R+D 100%20", notes="a+b")
    assert seen == {"title": "R+D 100%20", "notes": "a+b"}


@pytest.mark.parametrize("hostile", ['x"\ndo shell script "touch /tmp/pwned"\nset y to "', 'back\\slash"quote', "line\rbreak\ttab"])
def test_identifiers_and_text_stay_inside_string_literals(scripts, hostile):
    ab.update_todo(id=hostile, title=hostile, list_id=hostile, list_name=hostile, tags=[hostile], add_tags=hostile)
    ab.update_project(id=hostile, title=hostile, area_id=hostile, area_title=hostile)
    ab.add_project(title=hostile, area_id=hostile, todos=[hostile])
    for script in scripts:
        # String literals may span lines, so quote parity is taken over the whole script.
        outside = "".join(script.split('"')[::2])
        assert "do shell script" not in outside
        assert "pwned" not in outside
        assert "\r" not in outside


def test_one_tag_name_given_as_a_string_is_one_tag(scripts):
    ab.add_todo(title="t", tags="work")
    ab.add_project(title="p", tags="work")
    ab.update_todo(id="i", tags="work")
    ab.update_project(id="i", tags="work")
    for script, reference in zip(scripts, ("newTodo", "newProject", "theTodo", "theProject"), strict=True):
        assert f'set tag names of {reference} to "work"' in script


def test_one_todo_title_given_as_a_string_creates_one_todo(scripts):
    ab.add_project(title="p", todos="Buy milk")
    assert scripts[0].count("make new to do") == 1
    assert 'make new to do with properties {name:"Buy milk"}' in scripts[0]


@pytest.mark.parametrize(("update", "reference"), [(ab.update_todo, "theTodo"), (ab.update_project, "theProject")])
def test_empty_notes_and_tags_clear_them_and_omitted_ones_are_left_alone(scripts, update, reference):
    update(id="i", notes="", tags=[])
    update(id="i", title="Renamed")
    assert f'set notes of {reference} to ""' in scripts[0]
    assert f'set tag names of {reference} to ""' in scripts[0]
    assert "set notes of" not in scripts[1] and "set tag names of" not in scripts[1]


def test_added_tags_are_appended_to_the_existing_ones(scripts):
    ab.update_todo(id="i", add_tags=["urgent", "home"])
    script = scripts[0]
    assert "set existingTagNames to tag names of theTodo" in script
    assert 'set addedTagNames to "urgent, home"' in script
    assert 'set tag names of theTodo to existingTagNames & ", " & addedTagNames' in script
    ab.update_todo(id="i", title="no tag change")
    assert "existingTagNames" not in scripts[1]


@pytest.mark.parametrize("title", ["", "   ", None])
@pytest.mark.parametrize("create", [ab.add_todo, ab.add_project])
def test_blank_title_is_refused_before_anything_runs(scripts, create, title):
    with pytest.raises(ab.AppleScriptError) as refused:
        create(title=title)
    assert refused.value.error_code == "invalid_title" and refused.value.outcome == "failed"
    assert scripts == []


def test_refused_requests_are_safe_to_resend_through_the_provider(scripts):
    with pytest.raises(ProviderError) as refused:
        DirectThingsProvider().add_task({"title": " "})
    assert refused.value.outcome == "failed"
    assert "Do not retry automatically" not in str(refused.value)


@pytest.mark.parametrize("list_name", ["Inbox", "Logbook", "Upcoming", "today", "No Such List"])
def test_impossible_project_destination_is_refused_before_anything_runs(scripts, list_name):
    with pytest.raises(ab.AppleScriptError) as refused:
        ab.update_project(id="i", list_name=list_name)
    assert refused.value.error_code == "invalid_destination" and refused.value.outcome == "failed"
    assert scripts == []


@pytest.mark.parametrize("list_name", ab.PROJECT_LISTS)
def test_projects_move_to_the_lists_they_can_live_in(scripts, list_name):
    ab.update_project(id="i", list_name=list_name, when="tomorrow")
    assert f'move theProject to list "{list_name}"' in scripts[0]
    assert "schedule theProject" not in scripts[0], "a list move takes precedence over a schedule"


def schedule_lines(script, reference):
    return [line.strip() for line in script.splitlines() if line.strip().startswith((f"move {reference}", f"schedule {reference}"))]


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        ("today", 'move {ref} to list "Today"'),
        ("anytime", 'move {ref} to list "Anytime"'),
        ("someday", 'move {ref} to list "Someday"'),
        ("tomorrow", "schedule {ref} for (current date) + 1 * days"),
        ((date.today() + timedelta(days=10)).isoformat(), "schedule {ref} for (current date) + 10 * days"),
        (date.today().isoformat(), "schedule {ref} for (current date)"),
        ((date.today() - timedelta(days=3)).isoformat(), "schedule {ref} for (current date)"),
        ("evening", None),
        ("2026-02-30", None),
        (None, None),
    ],
)
def test_todos_and_projects_are_scheduled_the_same_way(scripts, when, expected):
    ab.add_todo(title="t", when=when)
    ab.add_project(title="p", when=when)
    ab.update_todo(id="i", when=when)
    ab.update_project(id="i", when=when)
    for script, reference in zip(scripts, ("newTodo", "newProject", "theTodo", "theProject"), strict=True):
        assert schedule_lines(script, reference) == ([expected.format(ref=reference)] if expected else [])


class RecordingProvider:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "get":
                return {"uuid": "new-id", "title": "p", "start": "Anytime"}
            return {"id": "new-id"} if name.startswith(("add_", "update_")) else []

        return call


@pytest.fixture
def provider(monkeypatch):
    recording = RecordingProvider()
    monkeypatch.setattr(fast_server, "get_provider", lambda: recording)
    return recording


TOOLS = {
    "add_todo": lambda **kw: fast_server.add_task(title="t", **kw),
    "add_project": lambda **kw: fast_server.add_new_project(title="p", **kw),
    "update_todo": lambda **kw: fast_server.update_task(id="i", **kw),
    "update_project": lambda **kw: fast_server.update_existing_project(id="i", **kw),
}


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize(
    "values", [{"when": "evening"}, {"when": "next week"}, {"when": "2026-02-30"}, {"when": ""}, {"deadline": "2026-1-5"}, {"deadline": "2026-02-30"}, {"deadline": "tomorrow"}, {"deadline": "2026-01-05\n"}]
)
def test_unusable_schedule_values_are_refused_instead_of_silently_dropped(provider, tool, values):
    result = TOOLS[tool](**values)
    assert result.startswith("⚠️ Error: Unsupported")
    assert "Nothing was changed" in result
    assert provider.calls == []


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize(("given", "sent"), [("Today", "today"), (" SOMEDAY ", "someday"), ("tomorrow", "tomorrow"), ("2027-03-15", "2027-03-15")])
def test_schedule_keywords_are_accepted_in_any_case(provider, tool, given, sent):
    assert "✅" in TOOLS[tool](when=given, deadline="2027-03-20")
    params = provider.calls[0][1][-1]
    assert params["when"] == sent and params["deadline"] == "2027-03-20"


@pytest.mark.parametrize("tool", TOOLS)
def test_a_single_tag_string_reaches_the_provider_as_one_tag(provider, tool):
    TOOLS[tool](tags="work")
    assert provider.calls[0][1][-1]["tags"] == ["work"]


def test_a_single_todo_string_reaches_the_provider_as_one_todo(provider):
    fast_server.add_new_project(title="p", todos="Buy milk")
    assert provider.calls[0][1][-1]["todos"] == ["Buy milk"]
