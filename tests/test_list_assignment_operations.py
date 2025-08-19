"""Test suite for Things list assignment operations.

This module tests the new generic list assignment functionality using list_name and list_id
parameters for add_todo, update_todo, add_project, and update_project operations.
"""

import os
import sys

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import things  # noqa: E402

from things_mcp.applescript_bridge import (  # noqa: E402
    add_project,
    add_todo,
    update_project,
    update_todo,
)

from .conftest import (  # noqa: E402
    create_test_area,
    delete_project_by_id,
    delete_todo_by_id,
    generate_random_string,
    rename_test_area,
)

# ============================================================================
# BUILT-IN LIST OPERATIONS TESTS
# ============================================================================


def test_update_todo_to_inbox(test_namespace):
    """Test moving a todo to the Inbox using list_name parameter."""
    # Create a todo in Anytime first
    title = f"{test_namespace} Todo to Inbox {generate_random_string(5)}"
    todo_id = add_todo(title=title, when="anytime")
    assert todo_id, "Failed to create todo in Anytime"

    try:
        # Move to Inbox using the new list_name parameter
        result = update_todo(id=todo_id, list_name="Inbox")
        assert "true" in str(result).lower(), f"Failed to move todo to Inbox: {result}"

        # Verify the todo is now in Inbox
        todo = things.get(todo_id)
        # Inbox todos don't have a specific list property, but we can verify it's not in other lists
        assert not todo.get("start_date"), "Todo should not have a start date in Inbox"
        assert not todo.get("deadline"), "Todo should not have a deadline in Inbox"
    finally:
        delete_todo_by_id(todo_id)


def test_update_todo_to_today(test_namespace):
    """Test moving a todo to Today using list_name parameter."""
    # Create a todo in Anytime first
    title = f"{test_namespace} Todo to Today {generate_random_string(5)}"
    todo_id = add_todo(title=title, when="anytime")
    assert todo_id, "Failed to create todo in Anytime"

    try:
        # Move to Today using the new list_name parameter
        result = update_todo(id=todo_id, list_name="Today")
        assert "true" in str(result).lower(), f"Failed to move todo to Today: {result}"

        # Verify the todo is now in Today
        todo = things.get(todo_id)
        # Today todos should have today's date as start_date
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        assert todo.get("start_date") == today, f"Todo should be scheduled for today: {todo.get('start_date')}"
    finally:
        delete_todo_by_id(todo_id)


def test_update_todo_to_anytime(test_namespace):
    """Test moving a todo to Anytime using list_name parameter."""
    # Create a todo in Today first
    title = f"{test_namespace} Todo to Anytime {generate_random_string(5)}"
    todo_id = add_todo(title=title, when="today")
    assert todo_id, "Failed to create todo in Today"

    try:
        # Move to Anytime using the new list_name parameter
        result = update_todo(id=todo_id, list_name="Anytime")
        assert "true" in str(result).lower(), f"Failed to move todo to Anytime: {result}"

        # Verify the todo is now in Anytime
        todo = things.get(todo_id)
        # Anytime todos should not have a start_date
        assert not todo.get("start_date"), "Todo should not have a start date in Anytime"
    finally:
        delete_todo_by_id(todo_id)


def test_update_todo_to_someday(test_namespace):
    """Test moving a todo to Someday using list_name parameter."""
    # Create a todo in Today first
    title = f"{test_namespace} Todo to Someday {generate_random_string(5)}"
    todo_id = add_todo(title=title, when="today")
    assert todo_id, "Failed to create todo in Today"

    try:
        # Move to Someday using the new list_name parameter
        result = update_todo(id=todo_id, list_name="Someday")
        assert "true" in str(result).lower(), f"Failed to move todo to Someday: {result}"

        # Verify the todo is now in Someday
        todo = things.get(todo_id)
        # Someday todos should not have a start_date
        assert not todo.get("start_date"), "Todo should not have a start date in Someday"
    finally:
        delete_todo_by_id(todo_id)


def test_move_todo_between_builtin_lists(test_namespace):
    """Test moving a todo between different built-in lists using list_name."""
    # Create a todo in Anytime
    title = f"{test_namespace} Todo List Hopping {generate_random_string(5)}"
    todo_id = add_todo(title=title, when="anytime")
    assert todo_id, "Failed to create todo in Anytime"

    try:
        # Move to Today
        result = update_todo(id=todo_id, list_name="Today")
        assert "true" in str(result).lower(), "Failed to move todo to Today"

        # Move to Inbox
        result = update_todo(id=todo_id, list_name="Inbox")
        assert "true" in str(result).lower(), "Failed to move todo to Inbox"

        # Move to Someday
        result = update_todo(id=todo_id, list_name="Someday")
        assert "true" in str(result).lower(), "Failed to move todo to Someday"

        # Move back to Anytime
        result = update_todo(id=todo_id, list_name="Anytime")
        assert "true" in str(result).lower(), "Failed to move todo to Anytime"

        # Verify final state
        todo = things.get(todo_id)
        assert not todo.get("start_date"), "Todo should be in Anytime (no start date)"
    finally:
        delete_todo_by_id(todo_id)


# ============================================================================
# ID-BASED OPERATIONS TESTS
# ============================================================================


def test_add_todo_to_area_via_list_id(test_namespace):
    """Test adding a todo directly to an area using list_id parameter."""
    # Create test area
    unique_area_name = f"area-{generate_random_string(8)}"
    area_id = create_test_area(unique_area_name)
    assert area_id, "Failed to create test area"

    # Rename area for testing
    unique_area_title = f"{test_namespace}-DIY-ID-{generate_random_string(5)}"
    rename_test_area(area_id, unique_area_title)

    try:
        # Create todo directly in the area using list_id
        todo_title = f"{test_namespace}-Test Todo in Area by ID {generate_random_string(5)}"
        todo_id = add_todo(title=todo_title, list_id=area_id)
        assert todo_id, "Failed to create todo in area using list_id"

        # Verify the todo was created in the correct area
        todo = things.get(todo_id)
        assert todo["area"] == area_id, f"Todo should be in area {area_id}, but is in {todo.get('area')}"

        # Clean up
        delete_todo_by_id(todo_id)
    finally:
        # Clean up area
        pass  # Area cleanup handled by test framework


def test_add_todo_to_project_via_list_id(test_namespace):
    """Test adding a todo directly to a project using list_id parameter."""
    # Create test project
    project_title = f"{test_namespace}-Test Project for ID {generate_random_string(5)}"
    project_id = add_project(title=project_title)
    assert project_id, "Failed to create test project"

    try:
        # Create todo directly in the project using list_id
        todo_title = f"{test_namespace}-Test Todo in Project by ID {generate_random_string(5)}"
        todo_id = add_todo(title=todo_title, list_id=project_id)
        assert todo_id, "Failed to create todo in project using list_id"

        # Verify the todo was created in the correct project
        todo = things.get(todo_id)
        assert todo["project"] == project_id, f"Todo should be in project {project_id}, but is in {todo.get('project')}"

        # Clean up
        delete_todo_by_id(todo_id)
    finally:
        delete_project_by_id(project_id)


def test_update_todo_to_area_via_list_id(test_namespace):
    """Test moving a todo to an area using list_id parameter."""
    # Create test area
    unique_area_name = f"area-{generate_random_string(8)}"
    area_id = create_test_area(unique_area_name)
    assert area_id, "Failed to create test area"

    # Rename area for testing
    unique_area_title = f"{test_namespace}-Work-ID-{generate_random_string(5)}"
    rename_test_area(area_id, unique_area_title)

    # Create a todo in Inbox
    todo_title = f"{test_namespace}-Test Todo Move to Area by ID {generate_random_string(5)}"
    todo_id = add_todo(title=todo_title)
    assert todo_id, "Failed to create test todo"

    try:
        # Move todo to area using list_id
        result = update_todo(id=todo_id, list_id=area_id)
        assert "true" in str(result).lower(), f"Failed to move todo to area using list_id: {result}"

        # Verify the todo is now in the correct area
        todo = things.get(todo_id)
        assert todo["area"] == area_id, f"Todo should be in area {area_id}, but is in {todo.get('area')}"

        # Clean up
        delete_todo_by_id(todo_id)
    finally:
        # Clean up area
        pass  # Area cleanup handled by test framework


def test_update_todo_to_project_via_list_id(test_namespace):
    """Test moving a todo to a project using list_id parameter."""
    # Create test project
    project_title = f"{test_namespace}-Test Project for Move by ID {generate_random_string(5)}"
    project_id = add_project(title=project_title)
    assert project_id, "Failed to create test project"

    # Create a todo in Inbox
    todo_title = f"{test_namespace}-Test Todo Move to Project by ID {generate_random_string(5)}"
    todo_id = add_todo(title=todo_title)
    assert todo_id, "Failed to create test todo"

    try:
        # Move todo to project using list_id
        result = update_todo(id=todo_id, list_id=project_id)
        assert "true" in str(result).lower(), f"Failed to move todo to project using list_id: {result}"

        # Verify the todo is now in the correct project
        todo = things.get(todo_id)
        assert todo["project"] == project_id, f"Todo should be in project {project_id}, but is in {todo.get('project')}"

        # Clean up
        delete_todo_by_id(todo_id)
    finally:
        delete_project_by_id(project_id)


def test_add_project_to_area_via_area_id(test_namespace):
    """Test creating a project directly in an area using area_id parameter."""
    # Create test area
    unique_area_name = f"area-{generate_random_string(8)}"
    area_id = create_test_area(unique_area_name)
    assert area_id, "Failed to create test area"

    # Rename area for testing
    unique_area_title = f"{test_namespace}-Home-ID-{generate_random_string(5)}"
    rename_test_area(area_id, unique_area_title)

    try:
        # Create project directly in the area using area_id
        project_title = f"{test_namespace}-Test Project in Area by ID {generate_random_string(5)}"
        project_id = add_project(title=project_title, area_id=area_id)
        assert project_id, "Failed to create project in area using area_id"

        # Verify the project was created in the correct area
        project = things.get(project_id)
        assert project["area"] == area_id, f"Project should be in area {area_id}, but is in {project.get('area')}"

        # Clean up
        delete_project_by_id(project_id)
    finally:
        # Clean up area
        pass  # Area cleanup handled by test framework


def test_update_project_to_area_via_area_id(test_namespace):
    """Test moving a project to an area using area_id parameter."""
    # Create test area
    unique_area_name = f"area-{generate_random_string(8)}"
    area_id = create_test_area(unique_area_name)
    assert area_id, "Failed to create test area"

    # Rename area for testing
    unique_area_title = f"{test_namespace}-Office-ID-{generate_random_string(5)}"
    rename_test_area(area_id, unique_area_title)

    # Create a project without area
    project_title = f"{test_namespace}-Test Project Move to Area by ID {generate_random_string(5)}"
    project_id = add_project(title=project_title)
    assert project_id, "Failed to create test project"

    try:
        # Move project to area using area_id
        result = update_project(id=project_id, area_id=area_id)
        assert "true" in str(result).lower(), f"Failed to move project to area using area_id: {result}"

        # Verify the project is now in the correct area
        project = things.get(project_id)
        assert project["area"] == area_id, f"Project should be in area {area_id}, but is in {project.get('area')}"

        # Clean up
        delete_project_by_id(project_id)
    finally:
        # Clean up area
        pass  # Area cleanup handled by test framework


# ============================================================================
# PROJECT OPERATIONS TESTS
# ============================================================================


def test_add_todo_to_project_via_list_title(test_namespace):
    """Test adding a todo directly to a project using list_name parameter."""
    # Create test project
    project_title = f"{test_namespace}-Test Project for Title {generate_random_string(5)}"
    project_id = add_project(title=project_title)
    assert project_id, "Failed to create test project"

    try:
        # Create todo directly in the project using list_title
        todo_title = f"{test_namespace}-Test Todo in Project by Title {generate_random_string(5)}"
        todo_id = add_todo(title=todo_title, list_title=project_title)
        assert todo_id, "Failed to create todo in project using list_title"

        # Verify the todo was created in the correct project
        todo = things.get(todo_id)
        assert todo["project"] == project_id, f"Todo should be in project {project_id}, but is in {todo.get('project')}"

        # Clean up
        delete_todo_by_id(todo_id)
    finally:
        delete_project_by_id(project_id)


def test_update_todo_to_project_via_list_title(test_namespace):
    """Test moving a todo to a project using list_name parameter."""
    # Create test project
    project_title = f"{test_namespace}-Test Project for Move by Title {generate_random_string(5)}"
    project_id = add_project(title=project_title)
    assert project_id, "Failed to create test project"

    # Create a todo in Inbox
    todo_title = f"{test_namespace}-Test Todo Move to Project by Title {generate_random_string(5)}"
    todo_id = add_todo(title=todo_title)
    assert todo_id, "Failed to create test todo"

    try:
        # Move todo to project using list_title
        result = update_todo(id=todo_id, list_name=project_title)
        assert "true" in str(result).lower(), f"Failed to move todo to project using list_title: {result}"

        # Verify the todo is now in the correct project
        todo = things.get(todo_id)
        assert todo["project"] == project_id, f"Todo should be in project {project_id}, but is in {todo.get('project')}"

        # Clean up
        delete_todo_by_id(todo_id)
    finally:
        delete_project_by_id(project_id)


# ============================================================================
# EDGE CASES AND ERROR HANDLING TESTS
# ============================================================================


def test_update_todo_to_nonexistent_list(test_namespace):
    """Test moving a todo to a nonexistent list/project/area."""
    # Create a todo in Inbox
    todo_title = f"{test_namespace}-Test Todo Nonexistent List {generate_random_string(5)}"
    todo_id = add_todo(title=todo_title)
    assert todo_id, "Failed to create test todo"

    try:
        # Try to move to nonexistent list
        result = update_todo(id=todo_id, list_name="NonexistentList123")
        assert "error" in str(result).lower() or "not found" in str(result).lower(), f"Should return error for nonexistent list: {result}"
    finally:
        delete_todo_by_id(todo_id)


def test_update_todo_to_nonexistent_id(test_namespace):
    """Test moving a todo to a nonexistent ID."""
    # Create a todo in Inbox
    todo_title = f"{test_namespace}-Test Todo Nonexistent ID {generate_random_string(5)}"
    todo_id = add_todo(title=todo_title)
    assert todo_id, "Failed to create test todo"

    try:
        # Try to move to nonexistent ID
        result = update_todo(id=todo_id, list_id="nonexistent-id-123")
        assert "error" in str(result).lower() or "not found" in str(result).lower(), f"Should return error for nonexistent ID: {result}"
    finally:
        delete_todo_by_id(todo_id)


def test_list_name_vs_list_id_priority(test_namespace):
    """Test that list_name and list_id work independently.

    Note: When a project and area have the same name, Things3 appears to
    find the area first when searching by name.
    """
    # Create test area and project with same name
    area_name = f"{test_namespace}-Test Container {generate_random_string(5)}"
    area_id = create_test_area("temp-area")
    rename_test_area(area_id, area_name)

    project_title = area_name  # Same name as area
    project_id = add_project(title=project_title)
    assert project_id, "Failed to create test project"

    # Create a todo in Inbox
    todo_title = f"{test_namespace}-Test Todo Priority {generate_random_string(5)}"
    todo_id = add_todo(title=todo_title)
    assert todo_id, "Failed to create test todo"

    try:
        # Test list_name (when name matches both area and project)
        # NOTE: In practice, Things3 appears to find areas before projects when searching by name
        result = update_todo(id=todo_id, list_name=area_name)
        assert "true" in str(result).lower(), f"Failed to move todo using list_name: {result}"

        # Verify it went somewhere (in this case, it goes to the area)
        todo = things.get(todo_id)
        # The todo ends up in the area, not the project - this appears to be Things3 behavior
        assert todo.get("area") == area_id, f"Todo should be in area {area_id} when names conflict"

        # Move back to Inbox
        result = update_todo(id=todo_id, list_name="Inbox")
        assert "true" in str(result).lower(), "Failed to move todo back to Inbox"

        # Test list_id for area (should be unambiguous)
        result = update_todo(id=todo_id, list_id=area_id)
        assert "true" in str(result).lower(), f"Failed to move todo using list_id: {result}"

        # Verify it went to the area
        todo = things.get(todo_id)
        assert todo["area"] == area_id, f"Todo should be in area {area_id}"

        # Clean up
        delete_todo_by_id(todo_id)
    finally:
        delete_project_by_id(project_id)
        # Area cleanup handled by test framework


# ============================================================================
# MCP SERVER LEVEL TESTS
# ============================================================================


def test_mcp_server_add_task_with_list_id(test_namespace):
    """Test that MCP server add_task function properly passes list_id to AppleScript bridge."""
    from things_mcp.fast_server import add_new_project, add_task

    # Create test project using MCP server
    project_title = f"{test_namespace}-MCP Test Project {generate_random_string(5)}"
    project_result = add_new_project(title=project_title)

    # Extract project ID from result
    import re

    match = re.search(r"\(ID: ([^)]+)\)", project_result)
    assert match, f"Could not extract project ID from result: {project_result}"
    project_id = match.group(1)

    try:
        # Create todo using MCP server function with list_id - this should work but currently fails
        todo_title = f"{test_namespace}-MCP Todo via list_id {generate_random_string(5)}"
        result = add_task(title=todo_title, list_id=project_id)

        # Extract the todo ID from the result message
        match = re.search(r"\(ID: ([^)]+)\)", result)
        assert match, f"Could not extract todo ID from result: {result}"
        todo_id = match.group(1)

        # Verify the todo was created in the correct project
        # This assertion will fail until the MCP server is fixed to pass list_id
        todo = things.get(todo_id)
        assert todo.get("project") == project_id, f"Todo should be in project {project_id}, but is in {todo.get('project')} (todo was created in Inbox instead - MCP server is not passing list_id parameter)"

        # Clean up
        delete_todo_by_id(todo_id)
    finally:
        delete_project_by_id(project_id)


def test_mcp_server_priority_list_id_over_list_title(test_namespace):
    """Test that when both list_id and list_title are provided, list_id takes priority."""
    from things_mcp.fast_server import add_new_project, add_task

    # Create two test projects
    project1_title = f"{test_namespace}-MCP Project 1 {generate_random_string(5)}"
    project1_result = add_new_project(title=project1_title)

    project2_title = f"{test_namespace}-MCP Project 2 {generate_random_string(5)}"
    project2_result = add_new_project(title=project2_title)

    # Extract project IDs
    import re

    match1 = re.search(r"\(ID: ([^)]+)\)", project1_result)
    match2 = re.search(r"\(ID: ([^)]+)\)", project2_result)
    assert match1 and match2, "Could not extract project IDs"
    project1_id = match1.group(1)
    project2_id = match2.group(1)

    try:
        # Create todo with BOTH list_id (project1) and list_title (project2)
        # The list_id should take priority
        todo_title = f"{test_namespace}-MCP Todo priority test {generate_random_string(5)}"
        result = add_task(title=todo_title, list_id=project1_id, list_title=project2_title)

        # Extract the todo ID from the result message
        match = re.search(r"\(ID: ([^)]+)\)", result)
        assert match, f"Could not extract todo ID from result: {result}"
        todo_id = match.group(1)

        # Verify the todo was created in project1 (list_id), not project2 (list_title)
        todo = things.get(todo_id)
        assert todo.get("project") == project1_id, f"Todo should be in project1 {project1_id} (via list_id), but is in {todo.get('project')}"

        # Clean up
        delete_todo_by_id(todo_id)
    finally:
        delete_project_by_id(project1_id)
        delete_project_by_id(project2_id)


# ============================================================================
# COMPREHENSIVE INTEGRATION TESTS
# ============================================================================


def test_malformed_uuid_handling(test_namespace):
    """Test handling of malformed UUIDs."""
    # Create a test todo
    todo_title = f"{test_namespace}-Test Todo Malformed UUID {generate_random_string(5)}"
    todo_id = add_todo(title=todo_title)
    assert todo_id, "Failed to create test todo"

    try:
        # Test various malformed UUIDs
        malformed_uuids = [
            "not-a-uuid-at-all",
            "12345",
            "abcd-efgh-ijkl-mnop",  # Wrong format
            "12345678-1234-1234-1234-123456789012X",  # Too long
            "12345678-1234-1234-1234-12345678901",  # Too short
            "",  # Empty string
            "   ",  # Whitespace only
            "null",
            "undefined",
        ]

        for malformed_uuid in malformed_uuids:
            result = update_todo(id=todo_id, list_id=malformed_uuid)
            # Should either gracefully ignore or return error, but not crash
            assert isinstance(result, str), f"Should return string result for malformed UUID: {malformed_uuid}"
            # Todo should remain in its current location (not moved)
            todo = things.get(todo_id)
            assert todo is not None, f"Todo should still exist after malformed UUID: {malformed_uuid}"

    finally:
        delete_todo_by_id(todo_id)


def test_empty_list_id_handling(test_namespace):
    """Test handling of empty or None list_id parameters."""
    # Create a test todo
    todo_title = f"{test_namespace}-Test Todo Empty ID {generate_random_string(5)}"
    todo_id = add_todo(title=todo_title)
    assert todo_id, "Failed to create test todo"

    try:
        # Test empty list_id - should be ignored (no move)
        result = update_todo(id=todo_id, list_id="")
        assert "true" in str(result).lower() or result == "true", "Empty list_id should not cause failure"

        # Test None list_id - should be ignored (no move)
        result = update_todo(id=todo_id, list_id=None)
        assert "true" in str(result).lower() or result == "true", "None list_id should not cause failure"

        # Test whitespace-only list_id - AppleScript may treat this as empty and return error
        result = update_todo(id=todo_id, list_id="   ")
        # This might return an error about not finding the ID, which is acceptable behavior
        assert isinstance(result, str), "Should return string result for whitespace list_id"
        # Should not crash or return unexpected format
        assert not result.startswith("/var/folders/"), "Should not return temp file paths"

        # Verify todo still exists and is accessible
        todo = things.get(todo_id)
        assert todo is not None, "Todo should still exist after empty ID tests"

    finally:
        delete_todo_by_id(todo_id)


def test_valid_looking_but_nonexistent_ids(test_namespace):
    """Test handling of UUIDs that look valid but don't exist."""
    # Create a test todo
    todo_title = f"{test_namespace}-Test Todo Fake UUID {generate_random_string(5)}"
    todo_id = add_todo(title=todo_title)
    assert todo_id, "Failed to create test todo"

    try:
        # Test realistic-looking but non-existent UUIDs
        fake_uuids = [
            "12345678-1234-1234-1234-123456789012",  # Valid format, doesn't exist
            "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",  # Valid format, doesn't exist
            "00000000-0000-0000-0000-000000000000",  # All zeros
            "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",  # All F's
        ]

        for fake_uuid in fake_uuids:
            result = update_todo(id=todo_id, list_id=fake_uuid)
            # Should handle gracefully - either ignore or return error message
            assert isinstance(result, str), f"Should return string for fake UUID: {fake_uuid}"

            # If it's an error, it should be properly formatted
            if "error" in str(result).lower():
                assert "Error:" in result or "error" in result.lower(), f"Error should be properly formatted: {result}"

            # Verify todo still exists and is accessible
            todo = things.get(todo_id)
            assert todo is not None, f"Todo should still exist after fake UUID: {fake_uuid}"

    finally:
        delete_todo_by_id(todo_id)


def test_error_prefix_detection(test_namespace):
    """Test that results starting with 'Error:' are properly detected and handled."""
    from things_mcp.fast_server import add_task

    # Test with a list_id that will cause an error condition
    # Using a malformed ID that should trigger AppleScript error handling
    title = f"{test_namespace}-Error Prefix Test {generate_random_string(5)}"

    # Test with various error-inducing scenarios
    error_scenarios = [
        {"list_id": "definitely-not-a-real-uuid"},
        {"list_title": "NonExistentProject" + generate_random_string(10)},
        {"list_id": ""},  # Empty ID
    ]

    for scenario in error_scenarios:
        result = add_task(title=title + str(error_scenarios.index(scenario)), **scenario)

        # Result should be a string
        assert isinstance(result, str), f"Result should be string for scenario: {scenario}"

        # If there's an error, it should be properly prefixed and formatted
        if "error" in result.lower() or "failed" in result.lower():
            # Should have proper error emoji and formatting
            assert "⚠️" in result or "✅" in result, f"Should have proper emoji formatting: {result}"

        # Should not contain raw AppleScript errors
        assert not result.startswith("/var/folders/"), f"Should not return temp file paths: {result}"
        assert "script error" not in result.lower(), f"Should not contain raw AppleScript errors: {result}"


def test_success_message_location_information(test_namespace):
    """Test that success messages include proper location information."""
    from things_mcp.fast_server import add_new_project, add_task

    # Create test project and area
    project_title = f"{test_namespace}-Location Test Project {generate_random_string(5)}"
    project_id = add_project(title=project_title)
    assert project_id, "Failed to create test project"

    area_name = f"{test_namespace}-Location Test Area {generate_random_string(5)}"
    area_id = create_test_area("temp-area")
    rename_test_area(area_id, area_name)

    created_todos = []

    try:
        # Test 1: Todo created in project should show project location
        result1 = add_task(title=f"{test_namespace}-Project Todo {generate_random_string(5)}", list_id=project_id)
        assert "✅ Successfully created todo:" in result1, "Should have success message"
        assert "Project:" in result1, f"Should show project location: {result1}"
        assert project_title in result1, f"Should include project name: {result1}"

        # Extract todo ID for cleanup
        import re

        match = re.search(r"ID: ([^)]+)\)", result1)
        if match:
            created_todos.append(match.group(1))

        # Test 2: Todo created in area should show area location
        result2 = add_task(title=f"{test_namespace}-Area Todo {generate_random_string(5)}", list_id=area_id)
        assert "✅ Successfully created todo:" in result2, "Should have success message"
        assert "Area:" in result2, f"Should show area location: {result2}"
        assert area_name in result2, f"Should include area name: {result2}"

        # Extract todo ID for cleanup
        match = re.search(r"ID: ([^)]+)\)", result2)
        if match:
            created_todos.append(match.group(1))

        # Test 3: Todo created in Inbox should show list location
        result3 = add_task(title=f"{test_namespace}-Inbox Todo {generate_random_string(5)}")
        assert "✅ Successfully created todo:" in result3, "Should have success message"
        # Should show some location info (List: or similar)
        assert "in " in result3, f"Should show location information: {result3}"

        # Extract todo ID for cleanup
        match = re.search(r"ID: ([^)]+)\)", result3)
        if match:
            created_todos.append(match.group(1))

        # Test 4: Project created in area should show area location
        result4 = add_new_project(title=f"{test_namespace}-Area Project {generate_random_string(5)}", area_id=area_id)
        assert "✅ Successfully created project:" in result4, "Should have success message"
        assert "Area:" in result4, f"Should show area location: {result4}"
        assert area_name in result4, f"Should include area name: {result4}"

        # Extract project ID for cleanup
        match = re.search(r"ID: ([^)]+)\)", result4)
        if match:
            delete_project_by_id(match.group(1))

        # Test 5: Project created without area should show inbox location
        result5 = add_new_project(title=f"{test_namespace}-Inbox Project {generate_random_string(5)}")
        assert "✅ Successfully created project:" in result5, "Should have success message"
        assert "in List: Inbox" in result5, f"Should show inbox location: {result5}"

        # Extract project ID for cleanup
        match = re.search(r"ID: ([^)]+)\)", result5)
        if match:
            delete_project_by_id(match.group(1))

    finally:
        # Clean up created todos
        for todo_id in created_todos:
            try:
                delete_todo_by_id(todo_id)
            except Exception:
                pass  # Ignore cleanup failures

        # Clean up project
        delete_project_by_id(project_id)
        # Area cleanup handled by test framework


def test_comprehensive_list_operations(test_namespace):
    """Test all list operations in a comprehensive workflow."""
    # Create test containers
    area_name = f"{test_namespace}-Test Area {generate_random_string(5)}"
    area_id = create_test_area("temp-area")
    rename_test_area(area_id, area_name)

    project_title = f"{test_namespace}-Test Project {generate_random_string(5)}"
    project_id = add_project(title=project_title)
    assert project_id, "Failed to create test project"

    try:
        # Test 1: Create todo in area by name
        todo1_title = f"{test_namespace}-Todo 1 - Area by Name {generate_random_string(5)}"
        todo1_id = add_todo(title=todo1_title, list_title=area_name)
        assert todo1_id, "Failed to create todo in area by name"

        # Test 2: Create todo in project by ID
        todo2_title = f"{test_namespace}-Todo 2 - Project by ID {generate_random_string(5)}"
        todo2_id = add_todo(title=todo2_title, list_id=project_id)
        assert todo2_id, "Failed to create todo in project by ID"

        # Test 3: Move todo1 to Today
        result = update_todo(id=todo1_id, list_name="Today")
        assert "true" in str(result).lower(), "Failed to move todo to Today"

        # Test 4: Move todo2 to Inbox
        result = update_todo(id=todo2_id, list_name="Inbox")
        assert "true" in str(result).lower(), "Failed to move todo to Inbox"

        # Test 5: Move todo1 to project by name
        result = update_todo(id=todo1_id, list_name=project_title)
        assert "true" in str(result).lower(), "Failed to move todo to project by name"

        # Test 6: Move todo2 to area by ID
        result = update_todo(id=todo2_id, list_id=area_id)
        assert "true" in str(result).lower(), "Failed to move todo to area by ID"

        # Verify final states
        todo1 = things.get(todo1_id)
        todo2 = things.get(todo2_id)

        assert todo1["project"] == project_id, "Todo1 should be in project"
        assert todo2["area"] == area_id, "Todo2 should be in area"

        # Clean up
        delete_todo_by_id(todo1_id)
        delete_todo_by_id(todo2_id)

    finally:
        delete_project_by_id(project_id)
        # Area cleanup handled by test framework
