"""
Test suite for Things task (todo) operations.

Tests various todo operations including creation, updates, tag management,
and moving between areas/projects. Parallel to test_project_operations.py
which handles project-specific tests.
"""
import random
import string
import time
from collections.abc import Generator

import pytest
from things_mcp.applescript_bridge import (
    add_project_direct,
    add_todo_direct,
    ensure_things_ready,
    run_applescript,
    update_project_direct,
    update_todo_direct,
)

# Test namespace for tags and areas
TEST_NAMESPACE = "mcp-test"


def create_test_tag(tag_name: str) -> bool:
    """Create a test tag with the MCP namespace."""
    full_tag_name = f"{TEST_NAMESPACE}-{tag_name}"
    script = f"""
    tell application "Things3"
        set newTag to make new tag with properties {{name:"{full_tag_name}"}}
        return id of newTag
    end tell
    """
    result = run_applescript(script)
    return result and "error" not in result.lower()


def delete_test_tags():
    """Delete all test tags with the MCP namespace."""
    script = f"""
    tell application "Things3"
        try
            set tagList to {{}}
            repeat with theTag in tags
                if name of theTag starts with "{TEST_NAMESPACE}-" then
                    set end of tagList to id of theTag
                end if
            end repeat

            repeat with tagId in tagList
                try
                    set theTag to first tag whose id is tagId
                    delete theTag
                on error
                    -- Tag might already be deleted, continue
                end try
            end repeat

            return "success"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)
    if result and "error" not in result.lower():
        print("✅ Successfully cleaned up test tags")
    else:
        print(f"⚠️  Tag cleanup result: {result}")


def create_test_area(area_name: str) -> str:
    """Create a test area with the MCP namespace."""
    full_area_name = f"{TEST_NAMESPACE}-{area_name}"
    script = f"""
    tell application "Things3"
        set newArea to make new area with properties {{name:"{full_area_name}"}}
        return id of newArea
    end tell
    """
    result = run_applescript(script)
    if result and "error" not in result.lower():
        return result
    return None


def delete_test_areas():
    """Delete all test areas with the MCP namespace."""
    script = f"""
    tell application "Things3"
        try
            set areaList to {{}}
            repeat with theArea in areas
                if name of theArea starts with "{TEST_NAMESPACE}-" then
                    set end of areaList to id of theArea
                end if
            end repeat

            repeat with areaId in areaList
                try
                    set theArea to first area whose id is areaId
                    delete theArea
                on error
                    -- Area might already be deleted, continue
                end try
            end repeat

            return "success"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)
    if result and "error" not in result.lower():
        print("✅ Successfully cleaned up test areas")
    else:
        print(f"⚠️  Area cleanup result: {result}")


def delete_test_todos():
    """Delete all test todos with the MCP namespace."""
    script = f"""
    tell application "Things3"
        try
            set todoList to {{}}

            -- Check inbox specifically (most common location for test todos)
            repeat with theTodo in to dos of list "Inbox"
                try
                    if title of theTodo starts with "{TEST_NAMESPACE}" then
                        set end of todoList to id of theTodo
                        log "Found test todo in inbox: " & title of theTodo
                    end if
                on error
                    -- Skip items that can't be accessed
                end try
            end repeat



            -- Delete collected todos
            repeat with todoId in todoList
                try
                    set theTodo to first to do whose id is todoId
                    log "Deleting todo: " & title of theTodo
                    delete theTodo
                on error
                    -- Todo might already be deleted, continue
                    log "Error deleting todo: " & todoId
                end try
            end repeat

            return "Successfully cleaned up " & (count of todoList) & " test todos from inbox"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)
    if result and "error" not in result.lower():
        print("✅ Successfully cleaned up test todos")
    else:
        print(f"⚠️  Todo cleanup result: {result}")


def delete_test_projects():
    """Delete all test projects with the MCP namespace."""
    script = f"""
    tell application "Things3"
        try
            set projectList to {{}}

            -- Check inbox
            repeat with theProject in projects
                try
                    if title of theProject starts with "{TEST_NAMESPACE}" then
                        set end of projectList to id of theProject
                    end if
                on error
                    -- Skip items that can't be accessed
                end try
            end repeat

                        -- Check today
            repeat with theProject in projects of list "Today"
                try
                    if title of theProject starts with "{TEST_NAMESPACE}" then
                        set end of projectList to id of theProject
                    end if
                on error
                    -- Skip items that can't be accessed
                end try
            end repeat

            -- Check anytime
            repeat with theProject in projects of list "Anytime"
                try
                    if title of theProject starts with "{TEST_NAMESPACE}" then
                        set end of projectList to id of theProject
                    end if
                on error
                    -- Skip items that can't be accessed
                end try
            end repeat

            -- Check upcoming
            repeat with theProject in projects of list "Upcoming"
                try
                    if title of theProject starts with "{TEST_NAMESPACE}" then
                        set end of projectList to id of theProject
                    end if
                on error
                    -- Skip items that can't be accessed
                end try
            end repeat

            -- Check someday
            repeat with theProject in projects of list "Someday"
                try
                    if title of theProject starts with "{TEST_NAMESPACE}" then
                        set end of projectList to id of theProject
                    end if
                on error
                    -- Skip items that can't be accessed
                end try
            end repeat

            -- Check logbook
            repeat with theProject in projects of list "Logbook"
                try
                    if title of theProject starts with "{TEST_NAMESPACE}" then
                        set end of projectList to id of theProject
                    end if
                on error
                    -- Skip items that can't be accessed
                end try
            end repeat

            -- Delete collected projects
            repeat with projectId in projectList
                try
                    set theProject to first project whose id is projectId
                    delete theProject
                on error
                    -- Project might already be deleted, continue
                end try
            end repeat

            return "success"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)
    if result and "error" not in result.lower():
        print("✅ Successfully cleaned up test projects")
    else:
        print(f"⚠️  Project cleanup result: {result}")


def rename_test_area(area_id: str, new_name: str) -> bool:
    """Rename a test area (for emoji testing)."""
    script = f"""
    tell application "Things3"
        set theArea to first area whose id is "{area_id}"
        set name of theArea to "{new_name}"
    end tell
    """
    result = run_applescript(script)
    return result and "error" not in result.lower()


def generate_random_string(length: int = 10) -> str:  # noqa: S311
    """Generate a random string for testing."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment and clean up after all tests."""
    # Ensure Things is ready
    assert ensure_things_ready(), "Things app is not ready for testing"

    # Clean up any existing test data before starting
    delete_test_tags()
    delete_test_areas()
    delete_test_todos()
    delete_test_projects()

    yield

    # Clean up all test data after all tests complete
    delete_test_tags()
    delete_test_areas()
    delete_test_todos()
    delete_test_projects()


@pytest.fixture(scope="session", autouse=True)
def check_things_ready():
    """Ensure Things is ready before running any tests."""
    assert ensure_things_ready(), "Things app is not ready for testing"


@pytest.fixture
def test_todo() -> Generator[str, None, None]:
    """Create a test todo and clean it up after the test."""
    todo_id = add_todo_direct(title=f"{TEST_NAMESPACE} Test Todo {generate_random_string(5)}")
    assert todo_id, "Failed to create test todo"
    yield todo_id
    # Clean up by marking as canceled
    update_todo_direct(id=todo_id, canceled=True)


@pytest.fixture
def test_project() -> Generator[str, None, None]:
    """Create a test project and clean it up after the test."""
    project_id = add_project_direct(title=f"{TEST_NAMESPACE} Test Project {generate_random_string(5)}")
    assert project_id, "Failed to create test project"
    yield project_id
    # Clean up by moving to trash
    update_project_direct(id=project_id, list_name="Trash")


def test_add_todo_simple():
    """Test adding a todo with simple title."""
    title = f"{TEST_NAMESPACE} Test Todo {generate_random_string(5)}"
    result = add_todo_direct(title=title)
    assert result, "Failed to create simple todo"
    # Clean up
    update_todo_direct(id=result, canceled=True)


def test_add_todo_special_chars():
    """Test adding a todo with special characters."""
    title = f"{TEST_NAMESPACE} Test Todo with special chars: & | ; \" ' {generate_random_string(5)}"
    notes = 'Test notes with\nnewlines and "quotes"'
    result = add_todo_direct(title=title, notes=notes)
    assert result, "Failed to create todo with special characters"
    # Clean up
    update_todo_direct(id=result, canceled=True)


def test_update_todo_simple(test_todo):
    """Test simple todo update."""
    result = update_todo_direct(id=test_todo, title=f"{TEST_NAMESPACE} Updated Todo {generate_random_string(5)}", notes="Updated notes")
    assert result, "Failed to update todo"


def test_update_todo_tags(test_todo):
    """Test updating todo tags."""
    # Create test tags first
    test_tags = ["test", "reliability", "mcp"]
    for tag in test_tags:
        create_test_tag(tag)

    result = update_todo_direct(id=test_todo, tags=[f"{TEST_NAMESPACE}-{tag}" for tag in test_tags])
    assert result, "Failed to update todo tags"


def test_add_project_with_todos():
    """Test adding a project with initial todos."""
    title = f"{TEST_NAMESPACE} Test Project {generate_random_string(5)}"
    result = add_project_direct(title=title, notes="Test project notes", todos=[f"{TEST_NAMESPACE} Initial todo 1", f"{TEST_NAMESPACE} Initial todo 2"])
    assert result, "Failed to create project with todos"
    # Clean up
    update_project_direct(id=result, list_name="Trash")


def test_update_project_simple(test_project):
    """Test simple project update."""
    result = update_project_direct(id=test_project, title=f"Updated Project {generate_random_string(5)}", notes="Updated project notes")
    assert "true" in str(result).lower(), "Failed to update project"


def test_concurrent_operations():
    """Test multiple operations in quick succession."""
    results = []
    for i in range(5):
        title = f"{TEST_NAMESPACE} Concurrent Todo {i} {generate_random_string(3)}"
        result = add_todo_direct(title=title)
        results.append(result)
        time.sleep(0.1)  # Small delay between operations

        if result:  # Clean up successful todos
            update_todo_direct(id=result, canceled=True)

    success_count = sum(1 for r in results if r)
    assert success_count >= 4, f"Concurrent operations success rate too low: {success_count}/5"


def test_error_recovery_invalid_id():
    """Test error recovery with invalid ID."""
    result = update_todo_direct(id="invalid-id-12345", title="Should fail")
    assert "error" in str(result).lower(), "Should return error message for invalid ID"
    # Print the actual error message for debugging
    error_msg = str(result).lower()
    print(f"\nActual error message: {error_msg!r}")
    assert "get to do id" in error_msg, "Should indicate specific error about invalid ID"


def test_error_recovery_empty_title():
    """Test error recovery with empty title."""
    result = add_todo_direct(title="")
    assert not result, "Should fail with empty title"


def test_error_recovery_special_chars():
    """Test error recovery with problematic special characters."""
    title = f"{TEST_NAMESPACE} Test with null byte \x00 and other special chars \x1F"
    result = add_todo_direct(title=title)
    assert result, "Failed to handle special characters properly"
    # Clean up
    if result:
        update_todo_direct(id=result, canceled=True)


def test_move_todo_between_areas(test_todo):
    """Test moving a todo between areas with simple and complex names."""
    # Create test areas
    area1_id = create_test_area("area1")
    area2_id = create_test_area("area2")
    area3_id = create_test_area("area3")

    assert area1_id, "Failed to create test area 1"
    assert area2_id, "Failed to create test area 2"
    assert area3_id, "Failed to create test area 3"

    # Rename areas for testing
    rename_test_area(area1_id, f"{TEST_NAMESPACE}-Family")
    rename_test_area(area2_id, f"{TEST_NAMESPACE}-AI & Automation")
    rename_test_area(area3_id, f"{TEST_NAMESPACE}-🏃🏽‍♂️ Fitness")

    # Move to first area
    result = update_todo_direct(id=test_todo, area_title=f"{TEST_NAMESPACE}-Family")
    assert result, "Failed to move todo to Family area"

    # Move to area with special characters
    result = update_todo_direct(id=test_todo, area_title=f"{TEST_NAMESPACE}-AI & Automation")
    assert result, "Failed to move todo to AI & Automation area"

    # Move to area with emoji
    result = update_todo_direct(id=test_todo, area_title=f"{TEST_NAMESPACE}-🏃🏽‍♂️ Fitness")
    assert result, "Failed to move todo to emoji area"


def test_move_todo_to_nonexistent_area(test_todo):
    """Test moving a todo to a nonexistent area."""
    result = update_todo_direct(id=test_todo, area_title="NonexistentArea123")
    assert "area not found" in str(result).lower(), "Should return appropriate error message"


def test_area_move_with_other_updates(test_todo):
    """Test moving a todo to an area while also updating other properties."""
    # Create test area and tags
    area_id = create_test_area("area1")
    assert area_id, "Failed to create test area"

    test_tags = ["test", "area-move"]
    for tag in test_tags:
        create_test_tag(tag)

    result = update_todo_direct(id=test_todo, area_title=f"{TEST_NAMESPACE}-area1", title=f"Updated Title {generate_random_string(5)}", notes="Updated notes", tags=[f"{TEST_NAMESPACE}-{tag}" for tag in test_tags])
    assert result, "Failed to move todo with other updates"


def test_move_todo_between_areas_and_projects(test_todo):
    """Test moving a todo between areas and projects."""
    # Create test areas
    area1_id = create_test_area("area1")
    area2_id = create_test_area("area2")

    assert area1_id, "Failed to create test area 1"
    assert area2_id, "Failed to create test area 2"

    # Rename areas for testing
    rename_test_area(area1_id, f"{TEST_NAMESPACE}-Family")
    rename_test_area(area2_id, f"{TEST_NAMESPACE}-AI & Automation")

    # First move to an area
    result = update_todo_direct(id=test_todo, area_title=f"{TEST_NAMESPACE}-Family")
    assert result, "Failed to move todo to Family area"

    # Create a project and move todo to it (should clear area)
    project_title = f"Test Project {generate_random_string(5)}"
    project_id = add_project_direct(title=project_title)
    assert project_id, "Failed to create test project"

    result = update_todo_direct(id=test_todo, project=project_title)
    assert result, "Failed to move todo to project"

    # Move back to an area
    result = update_todo_direct(id=test_todo, area_title=f"{TEST_NAMESPACE}-AI & Automation")
    assert result, "Failed to move todo to new area"

    # Clean up project
    update_project_direct(id=project_id, list_name="Trash")
