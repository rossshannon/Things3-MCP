"""Test suite for Things deadline operations.

Tests deadline functionality for todos and projects including creation,
updates, validation, and edge cases.
"""

import os
import sys
from datetime import datetime, timedelta

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tests.conftest import (  # noqa: E402
    delete_project_by_id,
    delete_todo_by_id,
    generate_random_string,
)
from things3_mcp.applescript_bridge import (  # noqa: E402
    add_project,
    add_todo,
    get_item,  # noqa: E402
    update_project,
    update_todo,
)


def test_add_todo_with_deadline(test_namespace):
    """Test adding a todo with a deadline."""
    # Test with tomorrow's date
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    title = f"{test_namespace} Todo with Deadline {generate_random_string(5)}"

    todo_id = add_todo(title=title, deadline=tomorrow)
    assert todo_id, "Failed to create todo with deadline"

    # Verify the deadline was set by retrieving the todo
    todo = get_item(todo_id)
    assert todo, "Failed to retrieve created todo"
    assert todo.get("deadline"), "Deadline was not set on todo"
    assert todo["deadline"] == tomorrow, f"Deadline mismatch: expected {tomorrow}, got {todo['deadline']}"

    # Clean up
    delete_todo_by_id(todo_id)


def test_update_todo_deadline(test_namespace):
    """Test updating a todo's deadline."""
    # Create a todo without deadline
    title = f"{test_namespace} Todo for Deadline Update {generate_random_string(5)}"
    todo_id = add_todo(title=title)
    assert todo_id, "Failed to create todo"

    # Update with a deadline
    new_deadline = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    result = update_todo(id=todo_id, deadline=new_deadline)
    assert result, "Failed to update todo deadline"

    # Verify the deadline was updated
    todo = get_item(todo_id)
    assert todo.get("deadline"), "Deadline was not set on todo"
    assert todo["deadline"] == new_deadline, f"Deadline mismatch: expected {new_deadline}, got {todo['deadline']}"

    # Clean up
    delete_todo_by_id(todo_id)


def test_add_project_with_deadline(test_namespace):
    """Test adding a project with a deadline."""
    # Test with a future date
    future_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    title = f"{test_namespace} Project with Deadline {generate_random_string(5)}"

    project_id = add_project(title=title, deadline=future_date)
    assert project_id, "Failed to create project with deadline"

    # Verify the deadline was set
    project = get_item(project_id)
    assert project, "Failed to retrieve created project"
    assert project.get("deadline"), "Deadline was not set on project"
    assert project["deadline"] == future_date, f"Deadline mismatch: expected {future_date}, got {project['deadline']}"

    # Clean up
    delete_project_by_id(project_id)


def test_update_project_deadline(test_namespace):
    """Test updating a project's deadline."""
    # Create a project without deadline
    title = f"{test_namespace} Project for Deadline Update {generate_random_string(5)}"
    project_id = add_project(title=title)
    assert project_id, "Failed to create project"

    # Update with a deadline
    new_deadline = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")
    result = update_project(id=project_id, deadline=new_deadline)
    assert result, "Failed to update project deadline"

    # Verify the deadline was updated
    project = get_item(project_id)
    assert project.get("deadline"), "Deadline was not set on project"
    assert project["deadline"] == new_deadline, f"Deadline mismatch: expected {new_deadline}, got {project['deadline']}"

    # Clean up
    delete_project_by_id(project_id)


def test_deadline_edge_cases(test_namespace):
    """Test deadline edge cases and validation."""
    title = f"{test_namespace} Deadline Edge Cases {generate_random_string(5)}"

    # Test with today's date
    today = datetime.now().strftime("%Y-%m-%d")
    todo_id = add_todo(title=f"{title} - Today", deadline=today)
    assert todo_id, "Failed to create todo with today's deadline"
    delete_todo_by_id(todo_id)

    # Test with past date (should still work, Things allows this)
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    todo_id = add_todo(title=f"{title} - Yesterday", deadline=yesterday)
    assert todo_id, "Failed to create todo with past deadline"
    delete_todo_by_id(todo_id)

    # Test with far future date
    far_future = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    todo_id = add_todo(title=f"{title} - Far Future", deadline=far_future)
    assert todo_id, "Failed to create todo with far future deadline"
    delete_todo_by_id(todo_id)


def test_invalid_deadline_format(test_namespace):
    """Test handling of invalid deadline formats."""
    title = f"{test_namespace} Invalid Deadline {generate_random_string(5)}"

    # Test with invalid date formats
    invalid_deadlines = [
        "2024/01/01",  # Wrong separator
        "01-01-2024",  # Wrong order
        "2024-13-01",  # Invalid month
        "2024-01-32",  # Invalid day
        "not-a-date",  # Completely invalid
        "",  # Empty string
    ]

    for invalid_deadline in invalid_deadlines:
        todo_id = add_todo(title=f"{title} - {invalid_deadline}", deadline=invalid_deadline)
        # We expect this to either fail gracefully or create without deadline
        if todo_id:
            todo = get_item(todo_id)
            # If it was created, it should not have a deadline set
            if todo and "deadline" in todo:
                assert not todo["deadline"], f"Invalid deadline '{invalid_deadline}' was incorrectly set"
            delete_todo_by_id(todo_id)
