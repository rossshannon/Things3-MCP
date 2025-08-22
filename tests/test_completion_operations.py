"""Test suite for Things completion operations.

Tests completion functionality for todos and projects including marking as completed,
canceled, and verifying completion status.
"""

import os
import sys

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tests.conftest import (  # noqa: E402
    delete_project_by_id,
    delete_todo_by_id,
    generate_random_string,
)
from things3_mcp.applescript_bridge import (  # noqa: E402  # noqa: E402
    add_project,
    add_todo,
    get_item,
    list_todos,
    update_project,
    update_todo,
)


def get_item_safely(item_id: str, expected_status: str = None) -> dict:
    """Safely retrieve an item by ID, handling completed/canceled items that might not be found by things.get().

    Args:
        item_id: The ID of the item to retrieve
        expected_status: Expected status of the item (e.g., 'completed', 'canceled')

    Returns:
        The item dict if found, None otherwise
    """
    # First try the direct approach
    item = get_item(item_id)
    if item:
        return item

    # If not found and we have an expected status, try searching by status
    if expected_status:
        if expected_status in ["completed", "canceled"]:
            # Search in todos with the specific status
            items = list_todos()
            for found_item in items:
                if found_item.get("uuid") == item_id:
                    return found_item

            # Also try projects if it might be a project
            # Projects are not needed for current usages here

    return None


def test_mark_todo_as_completed(test_namespace):
    """Test marking a todo as completed."""
    # Create a todo
    title = f"{test_namespace} Todo to Complete {generate_random_string(5)}"
    todo_id = add_todo(title=title)
    assert todo_id, "Failed to create todo"

    # Mark as completed
    result = update_todo(id=todo_id, completed=True)
    assert result, "Failed to mark todo as completed"

    # Verify the todo was marked as completed
    todo = get_item_safely(todo_id, "completed")
    assert todo, "Failed to retrieve todo"
    assert todo.get("status") == "completed", f"Todo status should be 'completed', got {todo.get('status')}"

    # Clean up
    delete_todo_by_id(todo_id)


def test_mark_project_as_completed(test_namespace):
    """Test marking a project as completed."""
    # Create a project
    title = f"{test_namespace} Project to Complete {generate_random_string(5)}"
    project_id = add_project(title=title)
    assert project_id, "Failed to create project"

    # Mark as completed
    result = update_project(id=project_id, completed=True)
    assert result, "Failed to mark project as completed"

    # Verify the project was marked as completed
    project = get_item_safely(project_id, "completed")
    assert project, "Failed to retrieve project"
    assert project.get("status") == "completed", f"Project status should be 'completed', got {project.get('status')}"

    # Clean up
    delete_project_by_id(project_id)


def test_mark_todo_as_canceled(test_namespace):
    """Test marking a todo as canceled."""
    # Create a todo
    title = f"{test_namespace} Todo to Cancel {generate_random_string(5)}"
    todo_id = add_todo(title=title)
    assert todo_id, "Failed to create todo"

    # Mark as canceled
    result = update_todo(id=todo_id, canceled=True)
    assert result, "Failed to mark todo as canceled"

    # Verify the todo was marked as canceled
    todo = get_item_safely(todo_id, "canceled")
    assert todo, "Failed to retrieve todo"
    assert todo.get("status") == "canceled", f"Todo status should be 'canceled', got {todo.get('status')}"

    # Clean up
    delete_todo_by_id(todo_id)


def test_mark_project_as_canceled(test_namespace):
    """Test marking a project as canceled."""
    # Create a project
    title = f"{test_namespace} Project to Cancel {generate_random_string(5)}"
    project_id = add_project(title=title)
    assert project_id, "Failed to create project"

    # Mark as canceled
    result = update_project(id=project_id, canceled=True)
    assert result, "Failed to mark project as canceled"

    # Verify the project was marked as canceled
    project = get_item_safely(project_id, "canceled")
    assert project, "Failed to retrieve project"
    assert project.get("status") == "canceled", f"Project status should be 'canceled', got {project.get('status')}"

    # Clean up
    delete_project_by_id(project_id)


def test_completion_with_other_updates(test_namespace):
    """Test marking items as completed while also updating other properties."""
    # Create a todo
    title = f"{test_namespace} Todo for Multi-Update {generate_random_string(5)}"
    todo_id = add_todo(title=title)
    assert todo_id, "Failed to create todo"

    # Mark as completed while updating other properties
    new_title = f"{test_namespace} Updated and Completed Todo {generate_random_string(5)}"
    result = update_todo(
        id=todo_id,
        title=new_title,
        notes="Updated notes and completed",
        completed=True,
    )
    assert result, "Failed to update and complete todo"

    # Verify all updates were applied
    todo = get_item_safely(todo_id, "completed")
    assert todo, "Failed to retrieve todo"
    assert todo.get("status") == "completed", "Todo should be completed"
    assert todo.get("title") == new_title, "Todo title should be updated"
    assert todo.get("notes") == "Updated notes and completed", "Todo notes should be updated"

    # Clean up
    delete_todo_by_id(todo_id)


def test_completion_edge_cases(test_namespace):
    """Test completion edge cases and validation."""
    # Test completing a todo that's already completed
    title = f"{test_namespace} Already Completed Todo {generate_random_string(5)}"
    todo_id = add_todo(title=title)
    assert todo_id, "Failed to create todo"

    try:
        # Mark as completed first time
        result = update_todo(id=todo_id, completed=True)
        assert result, "Failed to mark todo as completed"

        # Try to complete again (should still work)
        result = update_todo(id=todo_id, completed=True)
        assert result, "Failed to mark already completed todo as completed again"

        # Verify still completed - use the helper function to safely retrieve completed items
        todo = get_item_safely(todo_id, "completed")
        assert todo, f"Completed todo with ID {todo_id} not found"
        assert todo.get("status") == "completed", "Todo should still be completed"
    finally:
        # Clean up
        delete_todo_by_id(todo_id)


def test_completion_status_verification(test_namespace):
    """Test comprehensive verification of completion status."""
    # Create both a todo and project
    todo_title = f"{test_namespace} Status Test Todo {generate_random_string(5)}"
    project_title = f"{test_namespace} Status Test Project {generate_random_string(5)}"

    todo_id = add_todo(title=todo_title)
    project_id = add_project(title=project_title)
    assert todo_id, "Failed to create todo"
    assert project_id, "Failed to create project"

    try:
        # Verify initial status is incomplete
        todo = get_item_safely(todo_id, "incomplete")
        project = get_item_safely(project_id, "incomplete")
        assert todo.get("status") == "incomplete", "New todo should be incomplete"
        assert project.get("status") == "incomplete", "New project should be incomplete"

        # Mark todo as completed
        result = update_todo(id=todo_id, completed=True)
        assert result, "Failed to mark todo as completed"

        # Mark project as canceled
        result = update_project(id=project_id, canceled=True)
        assert result, "Failed to mark project as canceled"

        # Verify final statuses
        todo = get_item_safely(todo_id, "completed")
        project = get_item_safely(project_id, "canceled")
        assert todo.get("status") == "completed", "Todo should be completed"
        assert project.get("status") == "canceled", "Project should be canceled"
    finally:
        # Clean up
        delete_todo_by_id(todo_id)
        delete_project_by_id(project_id)


def test_invalid_completion_operations(test_namespace):
    """Test handling of invalid completion operations."""
    # Test completing a non-existent todo
    fake_id = "fake-todo-id-12345"
    result = update_todo(id=fake_id, completed=True)
    assert "error" in str(result).lower(), "Completing non-existent todo should return error"

    # Test completing a non-existent project
    fake_project_id = "fake-project-id-12345"
    result = update_project(id=fake_project_id, completed=True)
    assert "error" in str(result).lower(), "Completing non-existent project should return error"
