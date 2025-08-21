"""Test suite for Things scheduling operations.

Tests scheduling functionality for todos and projects including
today, tomorrow, anytime, someday, and specific date scheduling.
"""

import os
import sys
from datetime import datetime, timedelta

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import things  # noqa: E402

from tests.conftest import (  # noqa: E402
    delete_project_by_id,
    delete_todo_by_id,
    generate_random_string,
)
from things3_mcp.applescript_bridge import (  # noqa: E402
    add_project,
    add_todo,
    update_project,
    update_todo,
)


def _get_today_safe():
    """Safe version of things.today() that handles the sorting bug."""
    try:
        return things.today()
    except TypeError as e:
        if "'<' not supported between instances of 'NoneType' and 'str'" in str(e):
            # Replicate the exact logic from things.today() but with safe sorting
            import datetime

            def safe_sort_key(task):
                """Sort key that handles None values safely."""
                today_index = task.get("today_index", 0) or 0
                start_date = task.get("start_date")

                # Convert None to empty string for sorting
                if start_date is None:
                    start_date = ""

                return (today_index, start_date)

            # Get the raw data and filter for today items
            all_todos = things.todos(status="incomplete")
            all_projects = things.projects(status="incomplete")

            result = []
            today = datetime.date.today().strftime("%Y-%m-%d")

            # Filter todos that are scheduled for today
            for todo in all_todos:
                if todo.get("start_date") == today or todo.get("start") == "Today":
                    result.append(todo)

            # Filter projects that are scheduled for today
            for project in all_projects:
                if project.get("start_date") == today or project.get("start") == "Today":
                    result.append(project)

            # Sort safely
            result.sort(key=safe_sort_key)
            return result
        else:
            raise


def verify_todo_in_list(todo_id: str, expected_list: str) -> bool:
    """Verify that a todo appears in the expected list."""
    if not todo_id:
        return False

    # Use things.get() to get todo properties
    todo = things.get(todo_id)
    if not todo:
        return False

    # Check if todo is in the expected list by querying that list
    if expected_list == "Today":
        # Use safe today list retrieval to avoid sorting bug
        today_todos = _get_today_safe()
        return any(t["uuid"] == todo_id for t in today_todos)
    elif expected_list == "Anytime":
        anytime_todos = things.anytime()
        return any(t["uuid"] == todo_id for t in anytime_todos)
    elif expected_list == "Someday":
        someday_todos = things.someday()
        return any(t["uuid"] == todo_id for t in someday_todos)
    return False


def verify_project_in_list(project_id: str, expected_list: str) -> bool:
    """Verify that a project appears in the expected list."""
    if not project_id:
        return False

    # Use things.get() to get project properties
    project = things.get(project_id)
    if not project:
        return False

    # Check if project is in the expected list by querying that list
    if expected_list == "Today":
        # Use safe today list retrieval to avoid sorting bug
        today_projects = _get_today_safe()
        return any(p["uuid"] == project_id for p in today_projects)
    elif expected_list == "Anytime":
        anytime_projects = things.anytime()
        return any(p["uuid"] == project_id for p in anytime_projects)
    elif expected_list == "Someday":
        someday_projects = things.someday()
        return any(p["uuid"] == project_id for p in someday_projects)
    return False


def verify_todo_scheduled_date(todo_id: str, expected_date: str) -> bool:
    """Verify that a todo is scheduled for the expected date."""
    if not todo_id:
        return False

    todo = things.get(todo_id)
    if not todo:
        return False

    # Check if todo has the expected scheduled date
    scheduled_date = todo.get("start_date")
    if scheduled_date:
        # Convert to YYYY-MM-DD format for comparison
        if isinstance(scheduled_date, str):
            return scheduled_date.startswith(expected_date)
    return False


def verify_project_scheduled_date(project_id: str, expected_date: str) -> bool:
    """Verify that a project is scheduled for the expected date."""
    if not project_id:
        return False

    project = things.get(project_id)
    if not project:
        return False

    # Check if project has the expected scheduled date
    scheduled_date = project.get("start_date")
    if scheduled_date:
        # Convert to YYYY-MM-DD format for comparison
        if isinstance(scheduled_date, str):
            return scheduled_date.startswith(expected_date)
    return False


# ============================================================================
# TODO SCHEDULING TESTS
# ============================================================================


def test_add_todo_with_today_scheduling(test_namespace):
    """Test adding a todo with today scheduling."""
    title = f"{test_namespace} Todo Today {generate_random_string(5)}"
    todo_id = add_todo(title=title, when="today")
    assert todo_id, "Failed to create todo with today scheduling"

    try:
        # Verify todo appears in Today list
        assert verify_todo_in_list(todo_id, "Today"), "Todo should appear in Today list"
    finally:
        delete_todo_by_id(todo_id)


def test_add_todo_with_tomorrow_scheduling(test_namespace):
    """Test adding a todo with tomorrow scheduling."""
    title = f"{test_namespace} Todo Tomorrow {generate_random_string(5)}"
    todo_id = add_todo(title=title, when="tomorrow")
    assert todo_id, "Failed to create todo with tomorrow scheduling"

    try:
        # Get tomorrow's date in YYYY-MM-DD format
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert verify_todo_scheduled_date(todo_id, tomorrow), "Todo should be scheduled for tomorrow"
    finally:
        delete_todo_by_id(todo_id)


def test_add_todo_with_anytime_scheduling(test_namespace):
    """Test adding a todo with anytime scheduling."""
    title = f"{test_namespace} Todo Anytime {generate_random_string(5)}"
    todo_id = add_todo(title=title, when="anytime")
    assert todo_id, "Failed to create todo with anytime scheduling"

    try:
        # Verify todo appears in Anytime list
        assert verify_todo_in_list(todo_id, "Anytime"), "Todo should appear in Anytime list"
    finally:
        delete_todo_by_id(todo_id)


def test_add_todo_with_someday_scheduling(test_namespace):
    """Test adding a todo with someday scheduling."""
    title = f"{test_namespace} Todo Someday {generate_random_string(5)}"
    todo_id = add_todo(title=title, when="someday")
    assert todo_id, "Failed to create todo with someday scheduling"

    try:
        # Verify todo appears in Someday list
        assert verify_todo_in_list(todo_id, "Someday"), "Todo should appear in Someday list"
    finally:
        delete_todo_by_id(todo_id)


def test_add_todo_with_specific_date_scheduling(test_namespace):
    """Test adding a todo with specific date scheduling."""
    # Schedule for 3 days from now
    future_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    title = f"{test_namespace} Todo Specific Date {generate_random_string(5)}"
    todo_id = add_todo(title=title, when=future_date)
    assert todo_id, "Failed to create todo with specific date scheduling"

    try:
        # Verify todo is scheduled for the specific date
        assert verify_todo_scheduled_date(todo_id, future_date), f"Todo should be scheduled for {future_date}"
    finally:
        delete_todo_by_id(todo_id)


def test_update_todo_scheduling(test_namespace):
    """Test updating a todo's scheduling."""
    # Create a todo in Anytime
    title = f"{test_namespace} Todo Update Scheduling {generate_random_string(5)}"
    todo_id = add_todo(title=title, when="anytime")
    assert todo_id, "Failed to create todo"

    try:
        # Verify it's in Anytime
        assert verify_todo_in_list(todo_id, "Anytime"), "Todo should be in Anytime initially"

        # Update to Today
        result = update_todo(id=todo_id, when="today")
        assert result, "Failed to update todo scheduling"

        # Verify it's now in Today
        assert verify_todo_in_list(todo_id, "Today"), "Todo should be in Today after update"
    finally:
        delete_todo_by_id(todo_id)


def test_move_todo_between_lists(test_namespace):
    """Test moving a todo between different lists."""
    # Create a todo in Someday
    title = f"{test_namespace} Todo Move Lists {generate_random_string(5)}"
    todo_id = add_todo(title=title, when="someday")
    assert todo_id, "Failed to create todo"

    try:
        # Verify it's in Someday
        assert verify_todo_in_list(todo_id, "Someday"), "Todo should be in Someday initially"

        # Move to Anytime
        result = update_todo(id=todo_id, when="anytime")
        assert result, "Failed to move todo to Anytime"
        assert verify_todo_in_list(todo_id, "Anytime"), "Todo should be in Anytime"

        # Move to Today
        result = update_todo(id=todo_id, when="today")
        assert result, "Failed to move todo to Today"
        assert verify_todo_in_list(todo_id, "Today"), "Todo should be in Today"

        # Move to Tomorrow
        result = update_todo(id=todo_id, when="tomorrow")
        assert result, "Failed to move todo to Tomorrow"
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert verify_todo_scheduled_date(todo_id, tomorrow), "Todo should be scheduled for tomorrow"
    finally:
        delete_todo_by_id(todo_id)


# ============================================================================
# PROJECT SCHEDULING TESTS
# ============================================================================


def test_add_project_with_today_scheduling(test_namespace):
    """Test adding a project with today scheduling."""
    title = f"{test_namespace} Project Today {generate_random_string(5)}"
    project_id = add_project(title=title, when="today")
    assert project_id, "Failed to create project with today scheduling"

    try:
        # Verify project appears in Today list
        assert verify_project_in_list(project_id, "Today"), "Project should appear in Today list"
    finally:
        delete_project_by_id(project_id)


def test_add_project_with_tomorrow_scheduling(test_namespace):
    """Test adding a project with tomorrow scheduling."""
    title = f"{test_namespace} Project Tomorrow {generate_random_string(5)}"
    project_id = add_project(title=title, when="tomorrow")
    assert project_id, "Failed to create project with tomorrow scheduling"

    try:
        # Get tomorrow's date in YYYY-MM-DD format
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert verify_project_scheduled_date(project_id, tomorrow), "Project should be scheduled for tomorrow"
    finally:
        delete_project_by_id(project_id)


def test_add_project_with_anytime_scheduling(test_namespace):
    """Test adding a project with anytime scheduling."""
    title = f"{test_namespace} Project Anytime {generate_random_string(5)}"
    project_id = add_project(title=title, when="anytime")
    assert project_id, "Failed to create project with anytime scheduling"

    try:
        # Verify project appears in Anytime list
        assert verify_project_in_list(project_id, "Anytime"), "Project should appear in Anytime list"
    finally:
        delete_project_by_id(project_id)


def test_add_project_with_someday_scheduling(test_namespace):
    """Test adding a project with someday scheduling."""
    title = f"{test_namespace} Project Someday {generate_random_string(5)}"
    project_id = add_project(title=title, when="someday")
    assert project_id, "Failed to create project with someday scheduling"

    try:
        # Verify project appears in Someday list
        assert verify_project_in_list(project_id, "Someday"), "Project should appear in Someday list"
    finally:
        delete_project_by_id(project_id)


def test_add_project_with_specific_date_scheduling(test_namespace):
    """Test adding a project with specific date scheduling."""
    # Schedule for 5 days from now
    future_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
    title = f"{test_namespace} Project Specific Date {generate_random_string(5)}"
    project_id = add_project(title=title, when=future_date)
    assert project_id, "Failed to create project with specific date scheduling"

    try:
        # Verify project is scheduled for the specific date
        assert verify_project_scheduled_date(project_id, future_date), f"Project should be scheduled for {future_date}"
    finally:
        delete_project_by_id(project_id)


def test_update_project_scheduling(test_namespace):
    """Test updating a project's scheduling."""
    # Create a project in Anytime
    title = f"{test_namespace} Project Update Scheduling {generate_random_string(5)}"
    project_id = add_project(title=title, when="anytime")
    assert project_id, "Failed to create project"

    try:
        # Verify it's in Anytime
        assert verify_project_in_list(project_id, "Anytime"), "Project should be in Anytime initially"

        # Update to Today
        result = update_project(id=project_id, when="today")
        assert result, "Failed to update project scheduling"

        # Verify it's now in Today
        assert verify_project_in_list(project_id, "Today"), "Project should be in Today after update"
    finally:
        delete_project_by_id(project_id)


# ============================================================================
# EDGE CASES & ERROR HANDLING TESTS
# ============================================================================


def test_invalid_scheduling_values(test_namespace):
    """Test handling of invalid scheduling values."""
    title = f"{test_namespace} Todo Invalid Scheduling {generate_random_string(5)}"

    # Test with unsupported value "evening"
    todo_id = add_todo(title=title, when="evening")
    assert todo_id, "Should still create todo even with invalid scheduling"

    try:
        # The todo should be created but not scheduled (should be in Inbox)
        todo = things.get(todo_id)
        assert todo, "Failed to retrieve created todo"
        # Note: We can't easily verify it's in Inbox without additional API calls
    finally:
        delete_todo_by_id(todo_id)


def test_scheduling_with_other_properties(test_namespace):
    """Test scheduling combined with other properties."""
    title = f"{test_namespace} Todo Scheduling Properties {generate_random_string(5)}"
    notes = "Test notes for scheduling"
    tags = ["test-tag-1", "test-tag-2"]

    todo_id = add_todo(title=title, notes=notes, when="today", tags=tags)
    assert todo_id, "Failed to create todo with scheduling and other properties"

    try:
        # Verify scheduling works
        assert verify_todo_in_list(todo_id, "Today"), "Todo should be in Today list"

        # Verify other properties are preserved
        todo = things.get(todo_id)
        assert todo, "Failed to retrieve todo"
        assert todo.get("notes") == notes, "Notes should be preserved"
        # Note: Tag verification would require additional API calls
    finally:
        delete_todo_by_id(todo_id)


def test_scheduling_edge_cases(test_namespace):
    """Test scheduling edge cases."""
    # Test past date
    past_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    title = f"{test_namespace} Todo Past Date {generate_random_string(5)}"
    todo_id = add_todo(title=title, when=past_date)
    assert todo_id, "Should handle past date gracefully"

    try:
        # Should be scheduled for today (current date) when past date is provided
        today = datetime.now().strftime("%Y-%m-%d")
        assert verify_todo_scheduled_date(todo_id, today), "Past date should be converted to today"
    finally:
        delete_todo_by_id(todo_id)

    # Test far future date
    future_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
    title = f"{test_namespace} Todo Far Future {generate_random_string(5)}"
    todo_id = add_todo(title=title, when=future_date)
    assert todo_id, "Should handle far future date"

    try:
        assert verify_todo_scheduled_date(todo_id, future_date), "Far future date should be scheduled correctly"
    finally:
        delete_todo_by_id(todo_id)


def test_scheduling_verification(test_namespace):
    """Test comprehensive scheduling verification."""
    # Test all scheduling types for todos
    scheduling_tests = [
        ("today", "Today"),
        ("anytime", "Anytime"),
        ("someday", "Someday"),
    ]

    created_todos = []

    try:
        for when_value, expected_list in scheduling_tests:
            title = f"{test_namespace} Todo {when_value.title()} {generate_random_string(5)}"
            todo_id = add_todo(title=title, when=when_value)
            assert todo_id, f"Failed to create todo with {when_value} scheduling"
            created_todos.append(todo_id)

            # Verify it's in the correct list
            assert verify_todo_in_list(todo_id, expected_list), f"Todo should be in {expected_list} list"

        # Test date-based scheduling
        future_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        title = f"{test_namespace} Todo Date {generate_random_string(5)}"
        todo_id = add_todo(title=title, when=future_date)
        assert todo_id, "Failed to create todo with date scheduling"
        created_todos.append(todo_id)

        assert verify_todo_scheduled_date(todo_id, future_date), f"Todo should be scheduled for {future_date}"

    finally:
        # Clean up all created todos
        for todo_id in created_todos:
            delete_todo_by_id(todo_id)
