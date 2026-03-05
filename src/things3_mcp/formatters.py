"""Formatters for converting Things objects to human-readable strings.

This module provides functions to format todos, projects, areas, and tags
into consistent, readable string representations for display to users.
"""

import logging

from . import applescript_reader

logger = logging.getLogger(__name__)


def format_todo(todo: dict) -> str:
    """Helper function to format a single todo into a readable string."""
    logger.debug(f"Formatting todo: {todo}")
    todo_text = f"Title: {todo['title']}"

    # Add UUID for reference
    todo_text += f"\nUUID: {todo['uuid']}"

    # Add type
    todo_text += f"\nType: {todo['type']}"

    # Add status if present
    if todo.get("status"):
        todo_text += f"\nStatus: {todo['status']}"

    # Add start/list location
    if todo.get("start"):
        todo_text += f"\nList: {todo['start']}"

    # Add dates
    if todo.get("start_date"):
        todo_text += f"\nStart Date: {todo['start_date']}"
    if todo.get("deadline"):
        todo_text += f"\nDeadline: {todo['deadline']}"
    if todo.get("stop_date"):  # Completion date
        todo_text += f"\nCompleted: {todo['stop_date']}"

    # Add notes if present
    if todo.get("notes"):
        todo_text += f"\nNotes: {todo['notes']}"

    # Add project info if present
    if todo.get("project_title"):
        todo_text += f"\nProject: {todo['project_title']}"
    elif todo.get("project"):
        try:
            project = applescript_reader.get_by_id(todo["project"])
            if project:
                todo_text += f"\nProject: {project['title']}"
        except Exception:  # nosec B110 - Ignore missing project info
            pass

    # Add area info if present
    if todo.get("area_title"):
        todo_text += f"\nArea: {todo['area_title']}"
    elif todo.get("area"):
        try:
            area = applescript_reader.get_by_id(todo["area"])
            if area:
                todo_text += f"\nArea: {area['title']}"
        except Exception:  # nosec B110 - Ignore missing area info
            pass

    # Add tags if present
    if todo.get("tags"):
        todo_text += f"\nTags: {', '.join(todo['tags'])}"

    # Add checklist if present and contains items
    if isinstance(todo.get("checklist"), list):
        todo_text += "\nChecklist:"
        for item in todo["checklist"]:
            status = "✓" if item["status"] == "completed" else "□"
            todo_text += f"\n  {status} {item['title']}"

    return todo_text


def format_project(project: dict, include_items: bool = False) -> str:
    """Helper function to format a single project."""
    project_text = f"Title: {project['title']}\nUUID: {project['uuid']}"

    if project.get("area_title"):
        project_text += f"\nArea: {project['area_title']}"
    elif project.get("area"):
        try:
            area = applescript_reader.get_by_id(project["area"])
            if area:
                project_text += f"\nArea: {area['title']}"
        except Exception:  # nosec B110 - Ignore missing area info
            pass

    if project.get("notes"):
        project_text += f"\nNotes: {project['notes']}"

    if include_items:
        todos = applescript_reader.get_todos(project_uuid=project["uuid"])
        if todos:
            project_text += "\n\nTasks:"
            for todo in todos:
                project_text += f"\n- {todo['title']}"

    return project_text


def format_area(area: dict, include_items: bool = False) -> str:
    """Helper function to format a single area."""
    area_text = f"Title: {area['title']}\nUUID: {area['uuid']}"

    if area.get("notes"):
        area_text += f"\nNotes: {area['notes']}"

    if include_items:
        projects = applescript_reader.get_projects(area_uuid=area["uuid"])
        if projects:
            area_text += "\n\nProjects:"
            for project in projects:
                area_text += f"\n- {project['title']}"

        todos = applescript_reader.get_todos(area_uuid=area["uuid"])
        if todos:
            area_text += "\n\nTasks:"
            for todo in todos:
                area_text += f"\n- {todo['title']}"

    return area_text


def format_list(items: list[dict], list_name: str, include_items: bool = False) -> str:
    """Format a list of Things items with a count header.

    Automatically picks the right formatter based on item type.
    """
    _formatters = {
        "to-do": lambda item: format_todo(item),
        "project": lambda item: format_project(item, include_items),
        "area": lambda item: format_area(item, include_items),
    }

    formatted = []
    for item in items:
        item_type = item.get("type")
        formatter = _formatters.get(item_type)
        if formatter:
            formatted.append(formatter(item))
        else:
            # Fallback for tags or unknown types
            formatted.append(format_tag(item, include_items))

    header = f"You have {len(formatted)} items in {list_name}"
    return header + "\n\n---\n\n" + "\n\n---\n\n".join(formatted)


def format_tag(tag: dict, include_items: bool = False) -> str:
    """Helper function to format a single tag."""
    tag_text = f"Title: {tag['title']}\nUUID: {tag['uuid']}"

    if tag.get("shortcut"):
        tag_text += f"\nShortcut: {tag['shortcut']}"

    if include_items:
        todos = applescript_reader.get_tagged_items(tag["title"])
        if todos:
            tag_text += "\n\nTagged Items:"
            for todo in todos:
                tag_text += f"\n- {todo['title']}"

    return tag_text
