#!/usr/bin/env python3
"""AppleScript bridge for interacting with Things.app.

This module provides a reliable interface for executing AppleScript commands
to interact with the Things task management application on macOS. It handles
all the complexities of string escaping and error handling.
"""

import logging
import re
import subprocess  # nosec B404 - Required for running AppleScript commands
from datetime import datetime

from .date_converter import update_applescript_with_due_date
from .providers.base import ProviderError

logger = logging.getLogger(__name__)


class AppleScriptError(ProviderError):
    """A sanitised app-operation failure with a conservative mutation outcome."""


def _script_error(raw_error: str) -> AppleScriptError:
    # Raw app errors can contain task content. Use them only for classification.
    if "-1743" in raw_error or "not authorized to send apple events" in raw_error.lower():
        return AppleScriptError("automation_denied", "Things Automation access was denied", authorization_hint="Allow this bridge to control Things in System Settings > Privacy & Security > Automation.", outcome="outcome_unknown")
    return AppleScriptError("applescript_failed", "Things did not confirm completion; the operation may have changed some items", outcome="outcome_unknown")


def run_applescript(script: str, timeout: int = 8) -> str:
    """Execute a script over stdin without retaining its content in a file."""
    process = None
    try:
        process = subprocess.Popen(["/usr/bin/osascript", "-"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # nosec B603
        stdout, stderr = process.communicate(input=script.encode("utf-8"), timeout=timeout)
        if process.returncode != 0:
            raise _script_error(stderr.decode("utf-8", errors="replace"))
        output = stdout.decode("utf-8").strip()
        if output.lower().startswith("error:"):
            raise _script_error(output)
        logger.debug("AppleScript execution completed")
        return output.lower() if output.lower() in {"true", "false"} else output
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            process.kill()
            process.communicate()
        logger.error("AppleScript execution timed out")
        raise AppleScriptError("applescript_timeout", "Things did not confirm completion before the deadline", outcome="outcome_unknown") from exc
    except AppleScriptError:
        logger.error("AppleScript execution failed")
        raise
    except Exception as exc:
        logger.error("AppleScript execution failed")
        raise AppleScriptError("applescript_unavailable", "The local AppleScript process failed", outcome="outcome_unknown" if process is not None else "failed") from exc


def ensure_things_ready() -> bool:
    """Observe process state without launching Things or requesting consent."""
    return run_applescript('application id "com.culturedcode.ThingsMac" is running', timeout=5).lower() == "true"


def escape_applescript_string(text: str) -> str:
    """Escape special characters in an AppleScript string.

    AppleScript doesn't support traditional quote escaping. Instead, we handle
    quotes by breaking the string and using ASCII character codes.

    Args:
    ----
        text: The string to escape

    Returns:
    -------
        The escaped string ready for AppleScript concatenation
    """
    if not text:
        return '""'

    # Replace any "+" with spaces (URL decoding)
    text = text.replace("+", " ").replace("\\", "\\\\")

    # Handle carriage returns and tabs that can break AppleScript syntax
    # Preserve newlines as they're valid in AppleScript strings
    text = text.replace("\r", " ")  # Replace carriage returns with spaces
    text = text.replace("\t", " ")  # Replace tabs with spaces

    # Handle quotes by breaking the string and using ASCII character 34
    if '"' in text:
        # Split on quotes and rebuild with ASCII character concatenation
        parts = text.split('"')
        # Join parts with quote character (ASCII 34)
        result_parts = []
        for i, part in enumerate(parts):
            if i > 0:  # Add quote character before each part (except first)
                result_parts.append("(ASCII character 34)")
            if part:  # Only add non-empty parts as quoted strings
                result_parts.append(f'"{part}"')

        if result_parts:
            return " & ".join(result_parts)
        else:
            return '""'
    else:
        # No quotes, just return the quoted string
        return f'"{text}"'


def add_todo(  # noqa: PLR0913
    title: str,
    notes: str | None = None,
    when: str | None = None,
    deadline: str | None = None,
    tags: list[str] | None = None,
    list_id: str | None = None,
    list_title: str | None = None,
) -> str | bool:
    """Add a todo to Things directly using AppleScript with improved reliability.

    This bypasses URL schemes entirely to avoid encoding issues.

    Args:
    ----
        title: Title of the todo
        notes: Notes for the todo
        when: When to schedule the todo (today, tomorrow, anytime, someday, or YYYY-MM-DD)
        deadline: Deadline for the todo (YYYY-MM-DD format)
        tags: Tags to apply to the todo
        list_id: ID of project/area to add to
        list_title: Name of project/area to add to

    Returns:
    -------
        ID of the created todo if successful, False otherwise
    """
    # Validate input
    if not title or not title.strip():
        logger.error("Title cannot be empty")
        return False

    # Ensure Things is ready
    if not ensure_things_ready():
        raise AppleScriptError("app_not_running", "Things is not running; open Things before requesting a mutation", outcome="failed")

    # Build the AppleScript command
    script_parts = ['tell application id "com.culturedcode.ThingsMac"', "try"]

    # Create the todo with basic properties first
    properties = [f"name:{escape_applescript_string(title)}"]
    if notes:
        properties.append(f"notes:{escape_applescript_string(notes)}")

    # Create in Inbox first (simplest approach)
    script_parts.append(f'set newTodo to make new to do with properties {{{", ".join(properties)}}} at beginning of list "Inbox"')

    # Handle scheduling using the standardized helper
    _handle_when_scheduling(script_parts, when, "newTodo")

    # Add tags if provided
    if tags and len(tags) > 0:
        # Tags should be set as a comma-separated string according to Things documentation
        tag_string = ", ".join(tags)
        escaped_tag_string = escape_applescript_string(tag_string)
        script_parts.append(f"set tag names of newTodo to {escaped_tag_string}")

    # Handle deadline using the date converter
    if deadline:
        update_applescript_with_due_date(script_parts, deadline, "newTodo")

    # Handle project/area assignment by title
    if list_title:
        escaped_list = escape_applescript_string(list_title)
        script_parts.append(f"set list_name to {escaped_list}")
        script_parts.append("try")
        script_parts.append("  -- Try to find as project first")
        script_parts.append("  set target_project to first project whose name is list_name")
        script_parts.append("  set project of newTodo to target_project")
        script_parts.append("on error")
        script_parts.append("  try")
        script_parts.append("    -- Try to find as area")
        script_parts.append("    set target_area to first area whose name is list_name")
        script_parts.append("    set area of newTodo to target_area")
        script_parts.append("  on error")
        script_parts.append("    -- Neither project nor area found, will create todo without assignment")
        script_parts.append("  end try")
        script_parts.append("end try")

    # Handle project/area assignment by ID
    if list_id:
        script_parts.append("try")
        script_parts.append("  -- Try to find as project by ID")
        script_parts.append(f'  set target_project to first project whose id is {escape_applescript_string(list_id)}')
        script_parts.append("  set project of newTodo to target_project")
        script_parts.append("on error")
        script_parts.append("  try")
        script_parts.append("    -- Try to find as area by ID")
        script_parts.append(f'    set target_area to first area whose id is {escape_applescript_string(list_id)}')
        script_parts.append("    set area of newTodo to target_area")
        script_parts.append("  on error")
        script_parts.append("    -- Neither project nor area found with ID, will create todo without assignment")
        script_parts.append("  end try")
        script_parts.append("end try")

    # Get the ID of the created todo
    script_parts.append("return id of newTodo")
    script_parts.append("on error errMsg number errNum")
    script_parts.append("  error errMsg number errNum")

    script_parts.append("end try")
    script_parts.append("end tell")

    # Execute the script
    script = "\n".join(script_parts)
    logger.debug("AppleScript operation progress")

    result = run_applescript(script, timeout=8)
    if result and result.lower() not in {"true", "false"} and re.fullmatch(r"[A-Za-z0-9_-]+", result):
        logger.info("Successfully created todo via AppleScript")
        return result
    else:
        logger.error("AppleScript operation failed")
        return False


def is_valid_date_format(date_string: str) -> bool:
    """Check if a string matches YYYY-MM-DD date format."""
    try:
        datetime.strptime(date_string, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _handle_when_scheduling(script_parts: list[str], when: str | None, item_ref: str) -> None:
    """Handle when/scheduling for todos and projects with consistent approach."""
    if not when:
        return

    logger.info("AppleScript operation progress")

    # Check if it's a valid date format first
    is_date_format = is_valid_date_format(when)

    if when == "today":
        # Move to Today list
        script_parts.append(f'    move {item_ref} to list "Today"')
    elif when == "tomorrow":
        # Schedule for tomorrow
        script_parts.append(f"    schedule {item_ref} for (current date) + 1 * days")
    elif when == "anytime":
        # Move to Anytime list
        script_parts.append(f'    move {item_ref} to list "Anytime"')
    elif when == "someday":
        # Move to Someday list
        script_parts.append(f'    move {item_ref} to list "Someday"')
    elif is_date_format:
        # Schedule for specific date
        try:
            target_date = datetime.strptime(when, "%Y-%m-%d").date()
            current_date = datetime.now().date()
            days_diff = (target_date - current_date).days
            logger.debug("AppleScript operation progress")

            if days_diff <= 0:
                script_parts.append(f"    schedule {item_ref} for (current date)")
            else:
                script_parts.append(f"    schedule {item_ref} for (current date) + {days_diff} * days")
        except ValueError:
            logger.error("AppleScript operation failed")
            logger.warning("AppleScript operation progress")
    else:
        logger.warning("AppleScript operation progress")


def _handle_project_when_scheduling(script_parts: list[str], when: str | None, project_ref: str) -> None:
    """Handle when/scheduling specifically for projects."""
    if not when:
        return

    logger.info("AppleScript operation progress")

    # Check if it's a valid date format first
    is_date_format = is_valid_date_format(when)

    if when == "today":
        # Move project to Today list
        move_project_to_list(script_parts, "Today", project_ref)
    elif when == "tomorrow":
        # Schedule project for tomorrow
        script_parts.append(f"    schedule {project_ref} for (current date) + 1 * days")
    elif when == "anytime":
        # Move project to Anytime list
        move_project_to_list(script_parts, "Anytime", project_ref)
    elif when == "someday":
        # Move project to Someday list
        move_project_to_list(script_parts, "Someday", project_ref)
    elif is_date_format:
        # Schedule project for specific date
        try:
            target_date = datetime.strptime(when, "%Y-%m-%d").date()
            current_date = datetime.now().date()
            days_diff = (target_date - current_date).days
            logger.debug("AppleScript operation progress")

            if days_diff <= 0:
                script_parts.append(f"    schedule {project_ref} for (current date)")
            else:
                script_parts.append(f"    schedule {project_ref} for (current date) + {days_diff} * days")
        except ValueError:
            logger.error("AppleScript operation failed")
            logger.warning("AppleScript operation progress")
    else:
        logger.warning("AppleScript operation progress")


def update_todo(
    id: str,
    title: str | None = None,
    notes: str | None = None,
    when: str | None = None,
    deadline: str | None = None,
    tags: list[str] | str | None = None,
    add_tags: list[str] | str | None = None,
    completed: bool | None = None,
    canceled: bool | None = None,
    list_id: str | None = None,
    list_name: str | None = None,
) -> str:
    """Update a todo directly using AppleScript with improved reliability.

    This bypasses URL schemes entirely to avoid authentication issues.

    Args:
    ----
        id: The ID of the todo to update
        title: New title for the todo
        notes: New notes for the todo
        when: When to schedule the todo (today, tomorrow, anytime, someday, or YYYY-MM-DD)
        deadline: New deadline for the todo (YYYY-MM-DD)
        tags: New tags for the todo (replaces existing tags)
        add_tags: Tags to add to the todo (preserves existing tags)
        completed: Mark as completed
        canceled: Mark as canceled
        list_id: ID of project/area to move the todo to
        list_name: Name of built-in list, project, or area to move the todo to

    Returns:
    -------
        "true" if successful, error message if failed
    """
    # Ensure Things is ready
    if not ensure_things_ready():
        raise AppleScriptError("app_not_running", "Things is not running; open Things before requesting a mutation", outcome="failed")

    # Build the AppleScript command to find and update the todo
    script_parts = ['tell application id "com.culturedcode.ThingsMac"']
    script_parts.append("try")
    script_parts.append(f'    set theTodo to to do id {escape_applescript_string(id)}')

    # Update properties one at a time (simplified)
    if title:
        script_parts.append(f"    set name of theTodo to {escape_applescript_string(title)}")

    if notes:
        script_parts.append(f"    set notes of theTodo to {escape_applescript_string(notes)}")

    # Handle scheduling using the standardized helper
    _handle_when_scheduling(script_parts, when, "theTodo")

    # Handle deadline using the new converter
    if deadline:
        update_applescript_with_due_date(script_parts, deadline, "theTodo")

    # Handle tags (simplified)
    if tags is not None:
        if isinstance(tags, str):
            tags = [tags]
        if tags:
            # Set all tags at once using comma-separated string
            tag_string = ", ".join(tags)
            escaped_tag_string = escape_applescript_string(tag_string)
            script_parts.append(f"    set tag names of theTodo to {escaped_tag_string}")

    # Handle list assignment (built-in lists, projects, or areas)
    if list_name:
        escaped_list = escape_applescript_string(list_name)
        script_parts.append("    try")
        # First try to find as built-in list
        script_parts.append(f"        set targetList to list {escaped_list}")
        script_parts.append("        move theTodo to targetList")
        script_parts.append("    on error")
        script_parts.append("        try")
        # Then try to find as project
        script_parts.append(f"            set targetProject to first project whose name is {escaped_list}")
        script_parts.append("            set project of theTodo to targetProject")
        script_parts.append("        on error")
        script_parts.append("            try")
        # Finally try to find as area
        script_parts.append(f"                set targetArea to first area whose name is {escaped_list}")
        script_parts.append("                set area of theTodo to targetArea")
        script_parts.append("            on error")
        script_parts.append('                return "Error: Destination not found"')
        script_parts.append("            end try")
        script_parts.append("        end try")
        script_parts.append("    end try")

    # Handle list assignment by ID (projects or areas only)
    if list_id:
        script_parts.append("    try")
        # Try to find as project by ID
        script_parts.append(f'        set targetProject to first project whose id is {escape_applescript_string(list_id)}')
        script_parts.append("        set project of theTodo to targetProject")
        script_parts.append("    on error")
        script_parts.append("        try")
        # Try to find as area by ID
        script_parts.append(f'            set targetArea to first area whose id is {escape_applescript_string(list_id)}')
        script_parts.append("            set area of theTodo to targetArea")
        script_parts.append("        on error")
        script_parts.append('                return "Error: Destination not found"')
        script_parts.append("        end try")
        script_parts.append("    end try")

    # Handle completion status
    if completed is not None:
        if completed:
            script_parts.append("    set status of theTodo to completed")
        else:
            script_parts.append("    set status of theTodo to open")

    # Handle canceled status
    if canceled is not None:
        if canceled:
            script_parts.append("    set status of theTodo to canceled")
        else:
            script_parts.append("    set status of theTodo to open")

    # Return true on success
    script_parts.append("    return true")
    script_parts.append("on error errMsg number errNum")
    script_parts.append("    error errMsg number errNum")
    script_parts.append("end try")
    script_parts.append("end tell")

    # Execute the script
    script = "\n".join(script_parts)
    logger.debug("AppleScript operation progress")
    result = run_applescript(script)
    logger.debug("AppleScript operation progress")
    return result


def add_project(
    title: str,
    notes: str | None = None,
    when: str | None = None,
    tags: list[str] | None = None,
    area_title: str | None = None,
    area_id: str | None = None,
    deadline: str | None = None,
    todos: list[str] | None = None,
) -> str:
    """Add a project to Things directly using AppleScript with improved reliability.

    This bypasses URL schemes entirely to avoid encoding issues.

    Args:
    ----
        title: Title of the project
        notes: Notes for the project
        when: When to schedule the project (today, tomorrow, anytime, someday, or YYYY-MM-DD)
        tags: Tags to apply to the project
        area_title: Name of area to add to
        area_id: ID of area to add to
        deadline: Deadline for the project (YYYY-MM-DD format)
        todos: Initial todos to create in the project

    Returns:
    -------
        ID of the created project if successful, False otherwise
    """
    # Validate input
    if not title or not title.strip():
        logger.error("Title cannot be empty")
        return False

    # Ensure Things is ready
    if not ensure_things_ready():
        raise AppleScriptError("app_not_running", "Things is not running; open Things before requesting a mutation", outcome="failed")

    # Build the AppleScript command
    script_parts = ['tell application id "com.culturedcode.ThingsMac"']

    # Handle area assignment BEFORE creating the project
    if area_id or area_title:
        if area_id:
            # Try to find area by ID first
            script_parts.append(f'set area_id to {escape_applescript_string(area_id)}')
            script_parts.append("try")
            script_parts.append("  set target_area to first area whose id is area_id")
            script_parts.append("  set area_ref to target_area")
            script_parts.append("on error")
            script_parts.append("  -- Area not found by ID, will create project without area")
            script_parts.append("  set area_ref to missing value")
            script_parts.append("end try")
        else:
            # Find area by title
            script_parts.append(f"set area_name to {escape_applescript_string(area_title)}")
            script_parts.append("try")
            script_parts.append("  set target_area to first area whose name is area_name")
            script_parts.append("  set area_ref to target_area")
            script_parts.append("on error")
            script_parts.append("  -- Area not found, will create project without area")
            script_parts.append("  set area_ref to missing value")
            script_parts.append("end try")

    # Build properties for the project
    properties = [f"name:{escape_applescript_string(title)}"]
    if notes:
        properties.append(f"notes:{escape_applescript_string(notes)}")

    # Add area to properties if found
    if area_id or area_title:
        script_parts.append("if area_ref is not missing value then")
        script_parts.append("  set area_property to {area:area_ref}")
        script_parts.append("else")
        script_parts.append("  set area_property to {}")
        script_parts.append("end if")
        script_parts.append(f"set newProject to make new project with properties {{{', '.join(properties)}}} & area_property")
    else:
        # Create the project without area
        script_parts.append(f"set newProject to make new project with properties {{{', '.join(properties)}}}")

    # Handle scheduling using the project-specific helper
    _handle_project_when_scheduling(script_parts, when, "newProject")

    # Add tags if provided
    if tags and len(tags) > 0:
        # Tags should be set as a comma-separated string according to Things documentation
        tag_string = ", ".join(tags)
        escaped_tag_string = escape_applescript_string(tag_string)
        script_parts.append(f"set tag names of newProject to {escaped_tag_string}")

    # Handle deadline
    if deadline:
        update_applescript_with_due_date(script_parts, deadline, "newProject")

    # Add initial todos if provided
    if todos and len(todos) > 0:
        for todo in todos:
            todo_title = escape_applescript_string(todo)
            script_parts.append(f"tell newProject to make new to do with properties {{name:{todo_title}}}")

    # Get the ID of the created project
    script_parts.append("return id of newProject")

    # Close the tell block
    script_parts.append("end tell")

    # Execute the script
    script = "\n".join(script_parts)
    logger.debug("AppleScript operation progress")

    result = run_applescript(script, timeout=8)
    if result and result.lower() not in {"true", "false"} and re.fullmatch(r"[A-Za-z0-9_-]+", result):
        logger.info("Successfully created project via AppleScript")
        return result
    else:
        logger.error("AppleScript operation failed")
        return False


def move_project_to_list(script_parts: list[str], list_name: str, project_ref: str) -> bool:
    """Handle moving a project to a specific built-in list.

    Args:
    ----
        script_parts: List of AppleScript commands being built
        list_name: Name of the built-in list to move to (must be one of: "Today", "Anytime", "Someday", "Trash")
        project_ref: AppleScript reference to the project (e.g., "newProject" or "theProject")

    Note:
    ----
        Projects cannot be moved to Inbox (projects are never in Inbox).
        Projects cannot be moved to Logbook directly (mark as completed instead).

    Returns:
    -------
        bool: True if the list name is valid and the move command was added, False otherwise
    """
    valid_lists = ["Today", "Anytime", "Someday", "Trash"]
    if list_name not in valid_lists:
        logger.warning("AppleScript operation progress")
        return False

    # Move using the 'move' command instead of setting container
    script_parts.append(f'    move {project_ref} to list "{list_name}"')
    return True


def update_project(
    id: str,
    title: str | None = None,
    notes: str | None = None,
    when: str | None = None,
    deadline: str | None = None,
    tags: list[str] | None = None,
    completed: bool | None = None,
    canceled: bool | None = None,
    list_name: str | None = None,
    area_title: str | None = None,
    area_id: str | None = None,
) -> str:
    """Update an existing project in Things.

    Args:
    ----
        id: ID of the project to update
        title: New title
        notes: New notes
        when: When to schedule the project (today, tomorrow, anytime, someday, or YYYY-MM-DD)
        deadline: New deadline for the project (YYYY-MM-DD)
        tags: New tags for the project
        completed: Mark as completed
        canceled: Mark as canceled
        list_name: Move project directly to a built-in list. Must be one of:
                  - "Today": Move to Today list
                  - "Anytime": Move to Anytime list
                  - "Someday": Move to Someday list
                  - "Trash": Move to trash
                  Note: Projects cannot be moved to Inbox or Logbook. To move a project
                  to Logbook, mark it as completed instead.
        area_title: Title of the area to move the project to
        area_id: ID of the area to move the project to

    Returns:
    -------
        "true" if successful, error message if failed
    """
    logger.info("Updating project via AppleScript")
    if not ensure_things_ready():
        raise AppleScriptError("app_not_running", "Things is not running; open Things before requesting a mutation", outcome="failed")

    script_parts = ['tell application id "com.culturedcode.ThingsMac"']
    script_parts.append("try")
    script_parts.append(f'    set theProject to project id {escape_applescript_string(id)}')

    # Handle list moves first
    if list_name:
        if list_name in ["Inbox", "Logbook"]:
            error_msg = "Projects cannot be moved to Inbox or Logbook. To move to Logbook, mark the project as completed instead."
            logger.error("Invalid project destination")
            return f"Error: {error_msg}"
        if not move_project_to_list(script_parts, list_name, "theProject"):
            error_msg = f"Invalid list name: {list_name}"
            logger.error("Invalid project destination")
            return f"Error: {error_msg}"
    elif when:
        _handle_project_when_scheduling(script_parts, when, "theProject")

    # Handle area changes
    if area_id:
        # Use area_id if provided (takes precedence over area_title)
        script_parts.append("    try")
        script_parts.append(f'        set targetArea to first area whose id is {escape_applescript_string(area_id)}')
        script_parts.append("        set area of theProject to targetArea")
        script_parts.append("    on error")
        script_parts.append('                return "Error: Destination not found"')
        script_parts.append("    end try")
    elif area_title:
        escaped_area = escape_applescript_string(area_title)
        script_parts.append("    try")
        script_parts.append(f"        set targetArea to first area whose name is {escaped_area}")
        script_parts.append("        set area of theProject to targetArea")
        script_parts.append("    on error")
        script_parts.append('                return "Error: Destination not found"')
        script_parts.append("    end try")

    # Handle other property updates
    if title:
        script_parts.append(f"    set name of theProject to {escape_applescript_string(title)}")
    if notes:
        script_parts.append(f"    set notes of theProject to {escape_applescript_string(notes)}")
    if tags is not None:
        if tags:
            tag_string = ", ".join(tags)
            escaped_tag_string = escape_applescript_string(tag_string)
            script_parts.append(f"    set tag names of theProject to {escaped_tag_string}")
        else:
            script_parts.append('    set tag names of theProject to ""')
    if deadline:
        update_applescript_with_due_date(script_parts, deadline, "theProject")
    if completed is not None:
        script_parts.append("    set status of theProject to completed")
    if canceled is not None:
        script_parts.append("    set status of theProject to canceled")

    script_parts.append("    return true")
    script_parts.append("on error errMsg number errNum")
    script_parts.append("    error errMsg number errNum")
    script_parts.append("end try")
    script_parts.append("end tell")

    # Execute the script
    script = "\n".join(script_parts)
    logger.debug("AppleScript operation progress")
    result = run_applescript(script)
    logger.debug("AppleScript operation progress")
    return result
