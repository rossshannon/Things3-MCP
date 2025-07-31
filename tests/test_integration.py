#!/usr/bin/env python3
"""
Integration tests for Things MCP.
Tests complex workflows and interactions between different operations.
"""
import os
import sys

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import things  # noqa: E402
from things_mcp.applescript_bridge import (  # noqa: E402
    add_project_direct,
    add_todo_direct,
    update_project_direct,
    update_todo_direct,
)


def test_integration_workflow(cleanup_tracker, test_namespace):
    """Test a complete workflow: create, update, and verify consistency"""

    # Create test tags first
    initial_tags = ["integration", "test"]
    new_project_tags = ["integration", "test", "updated", "boost"]
    new_todo_tags = ["integration", "test", "updated", "priority"]

    all_tags = list(set(initial_tags + new_project_tags + new_todo_tags))
    for tag in all_tags:
        # Use the create_test_tag from cleanup_tracker's context
        result = add_todo_direct(title=f"{test_namespace}-{tag}")
        if result:
            cleanup_tracker.add_todo(result)  # Track the todo for cleanup
            cleanup_tracker.add_tag(tag)  # Also track the tag

    # 1. Create a project and todos
    project_title = f"{test_namespace} Integration Test Project 🔄"
    project_id = add_project_direct(title=project_title, notes="Initial project notes", tags=[f"{test_namespace}-{tag}" for tag in initial_tags])
    cleanup_tracker.add_project(project_id)

    # Create todos and add them to the project
    todo_titles = [f"{test_namespace} Setup task", f"{test_namespace} Development task", f"{test_namespace} Testing task"]
    for todo_title in todo_titles:
        todo_id = add_todo_direct(
            title=todo_title,
            list_title=project_title,  # This will add it to the project
        )
        if todo_id:
            cleanup_tracker.add_todo(todo_id)

    assert project_id is not False, "Project creation should succeed"

    # 2. Create a standalone todo
    todo_title = f"{test_namespace} Integration Test Todo 📋"
    todo_id = add_todo_direct(title=todo_title, notes="Initial todo notes", tags=[f"{test_namespace}-{tag}" for tag in initial_tags])
    cleanup_tracker.add_todo(todo_id)

    assert todo_id is not False, "Todo creation should succeed"

    # 3. Update both with new information
    project_success = update_project_direct(id=project_id, notes="Updated project notes with more details ✨", tags=[f"{test_namespace}-{tag}" for tag in new_project_tags])

    todo_success = update_todo_direct(id=todo_id, notes="Updated todo notes with more details 🎯", tags=[f"{test_namespace}-{tag}" for tag in new_todo_tags])

    assert project_success == "true", "Project update should succeed"
    assert todo_success == "true", "Todo update should succeed"

    # 4. Verify final state
    project = things.get(project_id)
    todo = things.get(todo_id)

    # Extract tag names from response
    def extract_tag_names(tags_data):
        tag_names = []
        for tag in tags_data:
            if isinstance(tag, dict):
                tag_names.append(tag.get("title", ""))
            else:
                tag_names.append(str(tag))
        return tag_names

    project_tag_titles = extract_tag_names(project.get("tags", []))
    todo_tag_titles = extract_tag_names(todo.get("tags", []))

    for tag in new_project_tags:
        expected_tag = f"{test_namespace}-{tag}"
        assert expected_tag in project_tag_titles, f"Project should have tag '{expected_tag}'"

    for tag in new_todo_tags:
        expected_tag = f"{test_namespace}-{tag}"
        assert expected_tag in todo_tag_titles, f"Todo should have tag '{expected_tag}'"

    assert "Updated project notes" in project["notes"], "Project notes should be updated"
    assert "Updated todo notes" in todo["notes"], "Todo notes should be updated"
