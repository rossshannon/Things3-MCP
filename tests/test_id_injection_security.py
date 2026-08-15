"""Security regression tests for AppleScript injection via id/list_id/area_id.

`applescript_bridge.py` builds AppleScript source with f-strings. The `id`,
`list_id`, and `area_id` parameters used to be interpolated directly into
that source with no escaping or format validation, while `title`, `notes`,
and `tags` were already passed through `escape_applescript_string()`. Since
`do shell script` is a top-level AppleScript command (not scoped to
`tell application`), a crafted id containing a `"` could break out of the
generated string literal and inject arbitrary AppleScript, including a
shell-out - i.e. remote/local code execution with the invoking user's OS
privileges.

These tests confirm that `is_valid_things_id()` rejects unsafe input, that
the bridge functions neutralize malformed ids without ever executing
injected AppleScript, and that legitimately formatted ids keep working.
"""

import os
import sys

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from things3_mcp.applescript_bridge import (  # noqa: E402
    add_project,
    add_todo,
    is_valid_things_id,
    update_project,
    update_todo,
)
from things3_mcp.fast_server import (  # noqa: E402
    add_new_project,
    add_task,
    update_existing_project,
    update_task,
)

from .conftest import (  # noqa: E402
    create_test_area,
    delete_project_by_id,
    delete_todo_by_id,
    generate_random_string,
)


# Payloads that attempt to break out of the `"..."` AppleScript string literal
# the id is interpolated into. Each embeds a `do shell script` call that
# touches a uniquely named marker file; if any payload were ever executed,
# the marker file would exist on disk afterwards.
def _injection_payloads(marker_path: str) -> list[str]:
    return [
        f'x" \nend try\nend tell\ndo shell script "touch {marker_path}"\ntell application "Things3"\ntry\nset y to "',
        f'" & (do shell script "touch {marker_path}") & "',
        f'";do shell script "touch {marker_path}";"',
        "not-real but has spaces",
        'quote"inside',
        "semi;colon",
        "amp&ersand",
        "paren(theses)",
        "back`tick",
        "dollar$(sign)",
        "new\nline",
        "tab\tchar",
    ]


def _assert_marker_absent(marker_path: str) -> None:
    assert not os.path.exists(marker_path), f"Injection payload executed! Marker file was created: {marker_path}"


# ============================================================================
# is_valid_things_id() unit tests
# ============================================================================


@pytest.mark.parametrize(
    "value",
    [
        "2Ukg8I2nLukhyEM7wYiBeb",  # typical ~22-char Things id
        "RLZroza3jz0XPs3uAlynS7",
        "NonExistentTodoID12345",  # alnum-only, used elsewhere in the test suite
        "fake-todo-id-12345",  # alnum + hyphens, used elsewhere in the test suite
        "12345678-1234-1234-1234-123456789012",  # RFC4122-style, also valid
        "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        "some_id_with_underscores",
        "a",
    ],
)
def test_is_valid_things_id_accepts_well_formed_ids(value):
    assert is_valid_things_id(value) is True


@pytest.mark.parametrize(
    "value",
    [
        'x" & (do shell script "touch /tmp/pwned") & "',
        "has space",
        'quote"inside',
        "semi;colon",
        "amp&ersand",
        "paren(theses)",
        "back`tick",
        "dollar$(sign)",
        "new\nline",
        "tab\tchar",
        "",
        "a" * 101,  # exceeds the length cap
    ],
)
def test_is_valid_things_id_rejects_unsafe_input(value):
    assert is_valid_things_id(value) is False


# ============================================================================
# update_todo / update_project - required `id` is validated up front
# ============================================================================


def test_update_todo_rejects_injection_in_id(tmp_path):
    marker = str(tmp_path / f"pwned-{generate_random_string(8)}")
    for payload in _injection_payloads(marker):
        result = update_todo(id=payload, title="Should not apply")
        assert isinstance(result, str), f"Should return a string for payload: {payload!r}"
        assert result.startswith("Error:"), f"Malformed id should be rejected: {payload!r} -> {result!r}"
        _assert_marker_absent(marker)


def test_update_project_rejects_injection_in_id(tmp_path):
    marker = str(tmp_path / f"pwned-{generate_random_string(8)}")
    for payload in _injection_payloads(marker):
        result = update_project(id=payload, title="Should not apply")
        assert isinstance(result, str), f"Should return a string for payload: {payload!r}"
        assert result.startswith("Error:"), f"Malformed id should be rejected: {payload!r} -> {result!r}"
        _assert_marker_absent(marker)


# ============================================================================
# add_todo / update_todo - optional `list_id` is validated and safely ignored
# ============================================================================


def test_add_todo_ignores_injection_in_list_id(tmp_path, test_namespace):
    marker = str(tmp_path / f"pwned-{generate_random_string(8)}")
    title = f"{test_namespace}-Injection Test {generate_random_string(5)}"
    todo_id = None
    try:
        todo_id = add_todo(title=title, list_id=f'x" & (do shell script "touch {marker}") & "')
        # Creation should still succeed; the malformed list_id is simply ignored.
        assert todo_id, "Todo creation should succeed even with a malformed list_id"
        _assert_marker_absent(marker)
    finally:
        if todo_id:
            delete_todo_by_id(todo_id)


def test_update_todo_ignores_injection_in_list_id(tmp_path, test_namespace):
    marker = str(tmp_path / f"pwned-{generate_random_string(8)}")
    title = f"{test_namespace}-Injection Test {generate_random_string(5)}"
    todo_id = add_todo(title=title)
    assert todo_id, "Failed to create test todo"

    try:
        result = update_todo(id=todo_id, list_id=f'x" & (do shell script "touch {marker}") & "')
        assert isinstance(result, str)
        assert "true" in result.lower(), f"Update should still succeed with malformed list_id ignored: {result!r}"
        _assert_marker_absent(marker)
    finally:
        delete_todo_by_id(todo_id)


# ============================================================================
# add_project / update_project - optional `area_id` is validated and safely ignored
# ============================================================================


def test_add_project_ignores_injection_in_area_id(tmp_path, test_namespace):
    marker = str(tmp_path / f"pwned-{generate_random_string(8)}")
    title = f"{test_namespace}-Injection Test {generate_random_string(5)}"
    project_id = None
    try:
        project_id = add_project(title=title, area_id=f'x" & (do shell script "touch {marker}") & "')
        assert project_id, "Project creation should succeed even with a malformed area_id"
        _assert_marker_absent(marker)
    finally:
        if project_id:
            delete_project_by_id(project_id)


def test_update_project_ignores_injection_in_area_id(tmp_path, test_namespace):
    marker = str(tmp_path / f"pwned-{generate_random_string(8)}")
    title = f"{test_namespace}-Injection Test {generate_random_string(5)}"
    project_id = add_project(title=title)
    assert project_id, "Failed to create test project"

    try:
        result = update_project(id=project_id, area_id=f'x" & (do shell script "touch {marker}") & "')
        assert isinstance(result, str)
        assert "true" in result.lower(), f"Update should still succeed with malformed area_id ignored: {result!r}"
        _assert_marker_absent(marker)
    finally:
        delete_project_by_id(project_id)


# ============================================================================
# fast_server.py MCP tool boundary - defense in depth
# ============================================================================


def test_mcp_update_todo_rejects_injection_in_id_without_calling_bridge(tmp_path):
    marker = str(tmp_path / f"pwned-{generate_random_string(8)}")
    payload = f'x" & (do shell script "touch {marker}") & "'

    result = update_task(id=payload, title="Should not apply")
    assert isinstance(result, str)
    assert "invalid id format" in result.lower(), f"Should reject malformed id at the tool boundary: {result!r}"
    _assert_marker_absent(marker)


def test_mcp_update_project_rejects_injection_in_id_without_calling_bridge(tmp_path):
    marker = str(tmp_path / f"pwned-{generate_random_string(8)}")
    payload = f'x" & (do shell script "touch {marker}") & "'

    result = update_existing_project(id=payload, title="Should not apply")
    assert isinstance(result, str)
    assert "invalid id format" in result.lower(), f"Should reject malformed id at the tool boundary: {result!r}"
    _assert_marker_absent(marker)


def test_mcp_add_task_ignores_injection_in_list_id(tmp_path, test_namespace):
    marker = str(tmp_path / f"pwned-{generate_random_string(8)}")
    title = f"{test_namespace}-MCP Injection Test {generate_random_string(5)}"

    result = add_task(title=title, list_id=f'x" & (do shell script "touch {marker}") & "')
    assert isinstance(result, str)
    assert "✅" in result, f"Should still create the todo despite the malformed list_id: {result!r}"
    _assert_marker_absent(marker)

    import re

    match = re.search(r"ID: ([^)]+)\)", result)
    if match:
        delete_todo_by_id(match.group(1))


def test_mcp_add_new_project_ignores_injection_in_area_id(tmp_path, test_namespace):
    marker = str(tmp_path / f"pwned-{generate_random_string(8)}")
    title = f"{test_namespace}-MCP Injection Test {generate_random_string(5)}"

    result = add_new_project(title=title, area_id=f'x" & (do shell script "touch {marker}") & "')
    assert isinstance(result, str)
    assert "✅" in result, f"Should still create the project despite the malformed area_id: {result!r}"
    _assert_marker_absent(marker)

    import re

    match = re.search(r"ID: ([^)]+)\)", result)
    if match:
        delete_project_by_id(match.group(1))


# ============================================================================
# Regression: legitimate ids keep working end to end
# ============================================================================


def test_update_todo_still_works_with_valid_id(test_namespace):
    title = f"{test_namespace}-Valid ID Regression {generate_random_string(5)}"
    todo_id = add_todo(title=title)
    assert todo_id, "Failed to create test todo"
    assert is_valid_things_id(todo_id), f"Real Things id unexpectedly rejected by validator: {todo_id!r}"

    try:
        result = update_todo(id=todo_id, title=f"{title} (updated)")
        assert "true" in str(result).lower(), f"Update with a valid id should succeed: {result!r}"
    finally:
        delete_todo_by_id(todo_id)


def test_update_project_still_works_with_valid_area_id(test_namespace):
    unique_area_name = f"area-{generate_random_string(8)}"
    area_id = create_test_area(unique_area_name)
    assert area_id, "Failed to create test area"
    assert is_valid_things_id(area_id), f"Real Things id unexpectedly rejected by validator: {area_id!r}"

    title = f"{test_namespace}-Valid Area ID Regression {generate_random_string(5)}"
    project_id = add_project(title=title)
    assert project_id, "Failed to create test project"

    try:
        result = update_project(id=project_id, area_id=area_id)
        assert "true" in str(result).lower(), f"Update with a valid area_id should succeed: {result!r}"
    finally:
        delete_project_by_id(project_id)
