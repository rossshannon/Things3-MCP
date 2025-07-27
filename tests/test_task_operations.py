"""
Test suite for Things task (todo) operations.

Tests various todo operations including creation, updates, tag management,
and moving between areas/projects. Parallel to test_project_operations.py
which handles project-specific tests.
"""
import pytest
import time
from typing import Generator
import random
import string

from things_mcp.applescript_bridge import (
    ensure_things_ready,
    add_todo_direct,
    update_todo_direct,
    add_project_direct,
    update_project_direct
)

def generate_random_string(length: int = 10) -> str:
    """Generate a random string for testing."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

@pytest.fixture(scope="session", autouse=True)
def check_things_ready():
    """Ensure Things is ready before running any tests."""
    assert ensure_things_ready(), "Things app is not ready for testing"

@pytest.fixture
def test_todo() -> Generator[str, None, None]:
    """Create a test todo and clean it up after the test."""
    todo_id = add_todo_direct(
        title=f"Test Todo {generate_random_string(5)}"
    )
    assert todo_id, "Failed to create test todo"
    yield todo_id
    # Clean up by marking as canceled
    update_todo_direct(id=todo_id, canceled=True)

@pytest.fixture
def test_project() -> Generator[str, None, None]:
    """Create a test project and clean it up after the test."""
    project_id = add_project_direct(
        title=f"Test Project {generate_random_string(5)}"
    )
    assert project_id, "Failed to create test project"
    yield project_id
    # Clean up by moving to trash
    update_project_direct(id=project_id, list_name="Trash")

def test_add_todo_simple():
    """Test adding a todo with simple title."""
    title = f"Test Todo {generate_random_string(5)}"
    result = add_todo_direct(title=title)
    assert result, "Failed to create simple todo"
    # Clean up
    update_todo_direct(id=result, canceled=True)

def test_add_todo_special_chars():
    """Test adding a todo with special characters."""
    title = f"Test Todo with special chars: & | ; \" ' {generate_random_string(5)}"
    notes = "Test notes with\nnewlines and \"quotes\""
    result = add_todo_direct(title=title, notes=notes)
    assert result, "Failed to create todo with special characters"
    # Clean up
    update_todo_direct(id=result, canceled=True)

def test_update_todo_simple(test_todo):
    """Test simple todo update."""
    result = update_todo_direct(
        id=test_todo,
        title=f"Updated Todo {generate_random_string(5)}",
        notes="Updated notes"
    )
    assert result, "Failed to update todo"

def test_update_todo_tags(test_todo):
    """Test updating todo tags."""
    result = update_todo_direct(
        id=test_todo,
        tags=["test", "reliability", "mcp"]
    )
    assert result, "Failed to update todo tags"

def test_add_project_with_todos():
    """Test adding a project with initial todos."""
    title = f"Test Project {generate_random_string(5)}"
    result = add_project_direct(
        title=title,
        notes="Test project notes",
        todos=["Initial todo 1", "Initial todo 2"]
    )
    assert result, "Failed to create project with todos"
    # Clean up
    update_project_direct(id=result, list_name="Trash")

def test_update_project_simple(test_project):
    """Test simple project update."""
    result = update_project_direct(
        id=test_project,
        title=f"Updated Project {generate_random_string(5)}",
        notes="Updated project notes"
    )
    assert "true" in str(result).lower(), "Failed to update project"

def test_concurrent_operations():
    """Test multiple operations in quick succession."""
    results = []
    for i in range(5):
        title = f"Concurrent Todo {i} {generate_random_string(3)}"
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
    title = "Test with null byte \x00 and other special chars \x1F"
    result = add_todo_direct(title=title)
    assert result, "Failed to handle special characters properly"
    # Clean up
    if result:
        update_todo_direct(id=result, canceled=True)

def test_move_todo_between_areas(test_todo):
    """Test moving a todo between areas with simple and complex names."""
    # Move to first area
    result = update_todo_direct(id=test_todo, area_title="HTMLSource")
    assert result, "Failed to move todo to HTMLSource area"

    # Move to area with special characters
    result = update_todo_direct(id=test_todo, area_title="AI & Automation")
    assert result, "Failed to move todo to AI & Automation area"

    # Move to area with emoji
    result = update_todo_direct(id=test_todo, area_title="🏃🏽‍♂️ Fitness")
    assert result, "Failed to move todo to emoji area"

def test_move_todo_to_nonexistent_area(test_todo):
    """Test moving a todo to a nonexistent area."""
    result = update_todo_direct(id=test_todo, area_title="NonexistentArea123")
    assert "area not found" in str(result).lower(), "Should return appropriate error message"

def test_area_move_with_other_updates(test_todo):
    """Test moving a todo to an area while also updating other properties."""
    result = update_todo_direct(
        id=test_todo,
        area_title="HTMLSource",
        title=f"Updated Title {generate_random_string(5)}",
        notes="Updated notes",
        tags=["test", "area-move"]
    )
    assert result, "Failed to move todo with other updates"

def test_move_todo_between_areas_and_projects(test_todo):
    """Test moving a todo between areas and projects."""
    # First move to an area
    result = update_todo_direct(id=test_todo, area_title="HTMLSource")
    assert result, "Failed to move todo to area"

    # Create a project and move todo to it (should clear area)
    project_title = f"Test Project {generate_random_string(5)}"
    project_id = add_project_direct(title=project_title)
    assert project_id, "Failed to create test project"

    result = update_todo_direct(id=test_todo, project=project_title)
    assert result, "Failed to move todo to project"

    # Move back to an area
    result = update_todo_direct(id=test_todo, area_title="AI & Automation")
    assert result, "Failed to move todo to new area"

    # Clean up project
    update_project_direct(id=project_id, list_name="Trash")
