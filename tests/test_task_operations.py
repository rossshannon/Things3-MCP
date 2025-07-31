"""Test suite for Things task (todo) operations.

Tests various todo operations including creation, updates, tag management,
and moving between areas/projects. Parallel to test_project_operations.py
which handles project-specific tests.
"""

import os
import random
import string
import sys
import time
from collections.abc import Generator

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402
import things  # noqa: E402

from things_mcp.applescript_bridge import (  # noqa: E402
    add_project,
    add_todo,
    ensure_things_ready,
    update_project,
    update_todo,
)

from .conftest import (  # noqa: E402
    create_test_area,
    create_test_tag,
    delete_project_by_id,
    delete_todo_by_id,
    rename_test_area,
)


def generate_random_string(length: int = 10) -> str:
    """Generate a random string for testing."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


@pytest.fixture(scope="session", autouse=True)
def _check_things_ready():
    """Ensure Things is ready before running any tests."""
    assert ensure_things_ready(), "Things app is not ready for testing"


@pytest.fixture()
def test_todo(test_namespace) -> Generator[str, None, None]:
    """Create a test todo and clean it up after the test."""
    todo_id = add_todo(title=f"{test_namespace} Test Todo {generate_random_string(5)}")
    assert todo_id, "Failed to create test todo"
    yield todo_id
    # Clean up
    delete_todo_by_id(todo_id)


@pytest.fixture()
def test_project(test_namespace) -> Generator[str, None, None]:
    """Create a test project and clean it up after the test."""
    project_id = add_project(title=f"{test_namespace} Test Project {generate_random_string(5)}")
    assert project_id, "Failed to create test project"
    yield project_id
    # Clean up
    delete_project_by_id(project_id)


def test_add_todo_simple(test_namespace):
    """Test adding a todo with simple title."""
    title = f"{test_namespace} Test Todo {generate_random_string(5)}"
    result = add_todo(title=title)
    assert result, "Failed to create simple todo"
    # Clean up
    delete_todo_by_id(result)


def test_add_todo_special_chars(test_namespace):
    """Test adding a todo with special characters."""
    title = f"{test_namespace} Test Todo with special chars: & | ; \" ' {generate_random_string(5)}"
    notes = 'Test notes with\nnewlines and "quotes"'
    result = add_todo(title=title, notes=notes)
    assert result, "Failed to create todo with special characters"
    # Clean up
    delete_todo_by_id(result)


def test_update_todo_simple(test_todo, test_namespace):
    """Test simple todo update."""
    result = update_todo(id=test_todo, title=f"{test_namespace} Updated Todo {generate_random_string(5)}", notes="Updated notes")
    assert result, "Failed to update todo"


def test_update_todo_tags(test_todo, test_namespace):
    """Test updating todo tags."""
    # Create test tags first
    test_tags = ["test", "reliability", "mcp"]
    for tag in test_tags:
        create_test_tag(tag)

    result = update_todo(id=test_todo, tags=[f"{test_namespace}-{tag}" for tag in test_tags])
    assert result, "Failed to update todo tags"


def test_add_project_with_todos(test_namespace):
    """Test adding a project with initial todos."""
    title = f"{test_namespace} Test Project {generate_random_string(5)}"
    result = add_project(title=title, notes="Test project notes", todos=[f"{test_namespace} Initial todo 1", f"{test_namespace} Initial todo 2"])
    assert result, "Failed to create project with todos"
    # Clean up
    delete_project_by_id(result)


def test_update_project_simple(test_project):
    """Test simple project update."""
    result = update_project(id=test_project, title=f"Updated Project {generate_random_string(5)}", notes="Updated project notes")
    assert "true" in str(result).lower(), "Failed to update project"


def test_concurrent_operations(test_namespace):
    """Test multiple operations in quick succession."""
    results = []
    for i in range(5):
        title = f"{test_namespace} Concurrent Todo {i} {generate_random_string(3)}"
        result = add_todo(title=title)
        results.append(result)
        time.sleep(0.1)  # Small delay between operations

        if result:  # Clean up successful todos
            delete_todo_by_id(result)

    success_count = sum(1 for r in results if r)
    assert success_count >= 4, f"Concurrent operations success rate too low: {success_count}/5"


def test_invalid_todo_id_update():
    """Test updating non-existent todo."""
    fake_id = "NonExistentTodoID12345"
    success = update_todo(id=fake_id, title="Should Fail")
    assert success.startswith("Error:"), "Updating non-existent todo should fail"


def test_empty_title_todo():
    """Test todo creation with empty title."""
    # This should fail gracefully
    todo_id = add_todo(title="")
    # We expect this to return False for empty title
    assert todo_id is False, "Empty title should be rejected"


def test_very_long_content(cleanup_tracker, test_namespace):
    """Test handling of very long titles and notes."""
    long_title = f"{test_namespace} Very Long Title " + "X" * 500 + " 🎯"
    long_notes = "Very long notes content.\n" * 100

    todo_id = add_todo(title=long_title, notes=long_notes)
    if todo_id:  # Only track if creation succeeded
        cleanup_tracker.add_todo(todo_id)

    # We don't assert success here as Things may have limits
    # But if it succeeds, verify the content
    if todo_id:
        todo = things.get(todo_id)
        assert len(todo["title"]) > 500, "Long title should be preserved"


def test_move_todo_between_areas(test_todo, test_namespace):
    """Test moving a todo between areas with simple and complex names."""
    # Create test areas
    area1_id = create_test_area("area1")
    area2_id = create_test_area("area2")
    area3_id = create_test_area("area3")

    assert area1_id, "Failed to create test area 1"
    assert area2_id, "Failed to create test area 2"
    assert area3_id, "Failed to create test area 3"

    # Rename areas for testing
    rename_test_area(area1_id, f"{test_namespace}-Family")
    rename_test_area(area2_id, f"{test_namespace}-AI & Automation")
    rename_test_area(area3_id, f"{test_namespace}-🏃🏽‍♂️ Fitness")

    # Move to first area
    result = update_todo(id=test_todo, area_title=f"{test_namespace}-Family")
    assert result, "Failed to move todo to Family area"

    # Move to area with special characters
    result = update_todo(id=test_todo, area_title=f"{test_namespace}-AI & Automation")
    assert result, "Failed to move todo to AI & Automation area"

    # Move to area with emoji
    result = update_todo(id=test_todo, area_title=f"{test_namespace}-🏃🏽‍♂️ Fitness")
    assert result, "Failed to move todo to emoji area"


def test_move_todo_to_nonexistent_area(test_todo):
    """Test moving a todo to a nonexistent area."""
    result = update_todo(id=test_todo, area_title="NonexistentArea123")
    assert "area not found" in str(result).lower(), "Should return appropriate error message"


def test_area_move_with_other_updates(test_todo, test_namespace):
    """Test moving a todo to an area while also updating other properties."""
    # Create test area and tags
    area_id = create_test_area("area1")
    assert area_id, "Failed to create test area"

    test_tags = ["test", "area-move"]
    for tag in test_tags:
        create_test_tag(tag)

    result = update_todo(id=test_todo, area_title=f"{test_namespace}-area1", title=f"Updated Title {generate_random_string(5)}", notes="Updated notes", tags=[f"{test_namespace}-{tag}" for tag in test_tags])
    assert result, "Failed to move todo with other updates"


def test_move_todo_between_areas_and_projects(test_todo, test_namespace):
    """Test moving a todo between areas and projects."""
    # Create test areas
    area1_id = create_test_area("area1")
    area2_id = create_test_area("area2")

    assert area1_id, "Failed to create test area 1"
    assert area2_id, "Failed to create test area 2"

    # Rename areas for testing
    rename_test_area(area1_id, f"{test_namespace}-Family")
    rename_test_area(area2_id, f"{test_namespace}-AI & Automation")

    # First move to an area
    result = update_todo(id=test_todo, area_title=f"{test_namespace}-Family")
    assert result, "Failed to move todo to Family area"

    # Create a project and move todo to it (should clear area)
    project_title = f"Test Project {generate_random_string(5)}"
    project_id = add_project(title=project_title)
    assert project_id, "Failed to create test project"

    result = update_todo(id=test_todo, project=project_title)
    assert result, "Failed to move todo to project"

    # Move back to an area
    result = update_todo(id=test_todo, area_title=f"{test_namespace}-AI & Automation")
    assert result, "Failed to move todo to new area"

    # Clean up project
    delete_project_by_id(project_id)
