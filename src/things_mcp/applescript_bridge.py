#!/usr/bin/env python3
import subprocess
import logging
import time
import re
from typing import Optional, List, Dict, Any, Union
from .date_converter import update_applescript_with_due_date

logger = logging.getLogger(__name__)

def run_applescript(script: str, timeout: int = 10, retries: int = 3) -> Union[str, bool]:
    """Run an AppleScript command with improved error handling and retry logic.

    Args:
        script: The AppleScript code to execute
        timeout: Timeout in seconds for the operation
        retries: Number of retry attempts

    Returns:
        The result of the AppleScript execution, or False if it failed
    """
    for attempt in range(retries):
        try:
            logger.debug(f"AppleScript attempt {attempt + 1}/{retries}")

            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.returncode != 0:
                logger.warning(f"AppleScript attempt {attempt + 1} failed with return code {result.returncode}: {result.stderr}")
                if attempt < retries - 1:
                    time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    logger.error(f"All AppleScript attempts failed: {result.stderr}")
                    return False

            # Success
            if attempt > 0:
                logger.info(f"AppleScript succeeded on attempt {attempt + 1}")
            return result.stdout.strip()

        except subprocess.TimeoutExpired:
            logger.warning(f"AppleScript attempt {attempt + 1} timed out after {timeout}s")
            if attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            else:
                logger.error("All AppleScript attempts timed out")
                return False
        except Exception as e:
            logger.error(f"AppleScript attempt {attempt + 1} failed with exception: {str(e)}")
            if attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            else:
                return False

    return False

def ensure_things_ready() -> bool:
    """Ensure Things app is ready for AppleScript operations.

    Returns:
        bool: True if Things is ready, False otherwise
    """
    try:
        # First check if Things is running
        check_script = 'tell application "System Events" to (name of processes) contains "Things3"'
        result = run_applescript(check_script, timeout=5, retries=2)

        if not result or result.lower() != 'true':
            logger.warning("Things app is not running")
            return False

        # Then check if Things is responsive
        ping_script = 'tell application "Things3" to return name'
        result = run_applescript(ping_script, timeout=5, retries=2)

        if not result:
            logger.warning("Things app is not responsive")
            return False

        logger.debug("Things app is ready for operations")
        return True

    except Exception as e:
        logger.error(f"Error checking Things readiness: {str(e)}")
        return False

def escape_applescript_string(text: str) -> str:
    """Escape special characters in an AppleScript string with improved handling.

    Args:
        text: The string to escape

    Returns:
        The escaped string
    """
    if not text:
        return ""

    # Replace any "+" with spaces first
    text = text.replace("+", " ")

    # Escape quotes by doubling them (AppleScript style)
    text = text.replace('"', '""')

    # Handle other problematic characters
    text = text.replace('\\', '\\\\')  # Escape backslashes
    text = text.replace('\n', '\\n')   # Escape newlines
    text = text.replace('\r', '\\r')   # Escape carriage returns
    text = text.replace('\t', '\\t')   # Escape tabs

    # Handle other potentially problematic characters
    text = text.replace('&', '\\&')    # Escape ampersands
    text = text.replace('|', '\\|')    # Escape pipes
    text = text.replace(';', '\\;')    # Escape semicolons

    # Remove any null bytes or other problematic characters
    text = text.replace('\x00', '')  # Remove null bytes
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')  # Keep only printable chars

    return text

def add_todo_direct(title: str, notes: Optional[str] = None, when: Optional[str] = None,
                   tags: Optional[List[str]] = None, list_title: Optional[str] = None,
                   deadline: Optional[str] = None) -> str:
    """Add a todo to Things directly using AppleScript with improved reliability.

    This bypasses URL schemes entirely to avoid encoding issues.

    Args:
        title: Title of the todo
        notes: Notes for the todo
        when: When to schedule the todo (today, tomorrow, evening, anytime, someday)
        tags: Tags to apply to the todo
        list_title: Name of project/area to add to
        deadline: Deadline for the todo (YYYY-MM-DD format)

    Returns:
        ID of the created todo if successful, False otherwise
    """
    # Validate input
    if not title or not title.strip():
        logger.error("Title cannot be empty")
        return False

    # Ensure Things is ready
    if not ensure_things_ready():
        logger.error("Things app is not ready for operations")
        return False

    # Build a simpler, more reliable AppleScript command
    script_parts = [
        'tell application "Things3"',
        'try'
    ]

    # Create the todo with basic properties first
    properties = [f'name:"{escape_applescript_string(title)}"']
    if notes:
        properties.append(f'notes:"{escape_applescript_string(notes)}"')

    # Create in Inbox first (simplest approach)
    script_parts.append(f'set newTodo to make new to do with properties {{{", ".join(properties)}}} at beginning of list "Inbox"')

    # Handle scheduling with simple approach
    if when:
        if when == 'today':
            script_parts.append('schedule newTodo for current date')
        elif when == 'tomorrow':
            script_parts.append('schedule newTodo for (current date) + 1 * days')
        elif when == 'anytime':
            # Already in Inbox, no action needed
            pass
        elif when == 'someday':
            script_parts.append('move newTodo to list "Someday"')

    # Add tags if provided (simplified)
    if tags and len(tags) > 0:
        # Add each tag individually
        for tag in tags:
            escaped_tag = escape_applescript_string(tag)
            script_parts.append(f'add tag "{escaped_tag}" to newTodo')

    # Handle deadline using the date converter (BEFORE return statement)
    if deadline:
        update_applescript_with_due_date(script_parts, deadline, "newTodo")

    # Handle project/area assignment
    if list_title:
        escaped_list = escape_applescript_string(list_title)
        script_parts.append(f'set project of newTodo to project "{escaped_list}"')

    # Get the ID of the created todo
    script_parts.append('return id of newTodo')
    script_parts.append('on error errMsg')
    script_parts.append('  log "Error creating todo: " & errMsg')
    script_parts.append('  return false')
    script_parts.append('end try')
    script_parts.append('end tell')

    # Execute the script
    script = '\n'.join(script_parts)
    logger.debug(f"Executing simplified AppleScript: {script}")

    result = run_applescript(script, timeout=8, retries=3)
    if result and result != "false":
        logger.info(f"Successfully created todo via AppleScript with ID: {result}")
        return result
    else:
        logger.error("Failed to create todo")
        return False

def update_todo_direct(id: str, title: Optional[str] = None, notes: Optional[str] = None,
                     when: Optional[str] = None, deadline: Optional[str] = None,
                     tags: Optional[Union[List[str], str]] = None, add_tags: Optional[Union[List[str], str]] = None,
                     completed: Optional[bool] = None, canceled: Optional[bool] = None,
                     project: Optional[str] = None) -> bool:
    """Update a todo directly using AppleScript with improved reliability.

    This bypasses URL schemes entirely to avoid authentication issues.

    Args:
        id: The ID of the todo to update
        title: New title for the todo
        notes: New notes for the todo
        when: New schedule for the todo (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD)
        deadline: New deadline for the todo (YYYY-MM-DD)
        tags: New tags for the todo (replaces existing tags)
        add_tags: Tags to add to the todo (preserves existing tags)
        completed: Mark as completed
        canceled: Mark as canceled
        project: Name of project to move the todo into

    Returns:
        True if successful, False otherwise
    """
    # Ensure Things is ready
    if not ensure_things_ready():
        logger.error("Things app is not ready for operations")
        return False

    # Build the AppleScript command to find and update the todo
    script_parts = ['tell application "Things3"']
    script_parts.append('try')
    script_parts.append(f'    set theTodo to to do id "{id}"')

    # Update properties one at a time (simplified)
    if title:
        script_parts.append(f'    set name of theTodo to "{escape_applescript_string(title)}"')

    if notes:
        script_parts.append(f'    set notes of theTodo to "{escape_applescript_string(notes)}"')

    # Handle simple scheduling
    if when:
        if when == 'today':
            script_parts.append('    move theTodo to list "Today"')
        elif when == 'tomorrow':
            script_parts.append('    schedule theTodo for (current date) + 1 * days')
        elif when == 'anytime':
            script_parts.append('    move theTodo to list "Anytime"')
        elif when == 'someday':
            script_parts.append('    move theTodo to list "Someday"')

    # Handle deadline using the new converter
    if deadline:
        update_applescript_with_due_date(script_parts, deadline, "theTodo")

    # Handle tags (simplified)
    if tags is not None:
        if isinstance(tags, str):
            tags = [tags]
        if tags:
            # Set all tags at once using comma-separated string
            tag_string = ", ".join([escape_applescript_string(tag) for tag in tags])
            script_parts.append(f'    set tag names of theTodo to "{tag_string}"')

    # Handle project assignment
    if project:
        escaped_project = escape_applescript_string(project)
        script_parts.append(f'    set project of theTodo to project "{escaped_project}"')

    # Handle completion status
    if completed is not None:
        if completed:
            script_parts.append('    set status of theTodo to completed')
        else:
            script_parts.append('    set status of theTodo to open')

    # Return true on success
    script_parts.append('    return true')
    script_parts.append('on error errMsg')
    script_parts.append('    log "Error updating todo: " & errMsg')
    script_parts.append('    return false')
    script_parts.append('end try')
    script_parts.append('end tell')

    # Execute the script
    script = '\n'.join(script_parts)
    logger.info(f"Executing AppleScript for update_todo_direct: \n{script}")

    result = run_applescript(script, timeout=8, retries=3)

    if result == "true":
        logger.info(f"Successfully updated todo with ID: {id}")
        return True
    else:
        logger.error(f"AppleScript update_todo_direct failed: {result}")
        return False

def add_project_direct(title: str, notes: Optional[str] = None, when: Optional[str] = None,
                      tags: Optional[List[str]] = None, area_title: Optional[str] = None,
                      deadline: Optional[str] = None, todos: Optional[List[str]] = None) -> str:
    """Add a project to Things directly using AppleScript with improved reliability.

    This bypasses URL schemes entirely to avoid encoding issues.

    Args:
        title: Title of the project
        notes: Notes for the project
        when: When to schedule the project (today, tomorrow, evening, anytime, someday)
        tags: Tags to apply to the project
        area_title: Name of area to add to
        deadline: Deadline for the project (YYYY-MM-DD format)
        todos: Initial todos to create in the project

    Returns:
        ID of the created project if successful, False otherwise
    """
    # Validate input
    if not title or not title.strip():
        logger.error("Title cannot be empty")
        return False

    # Ensure Things is ready
    if not ensure_things_ready():
        logger.error("Things app is not ready for operations")
        return False

    # Build the AppleScript command
    script_parts = ['tell application "Things3"']

    # Build properties for the project
    properties = [f'name:"{escape_applescript_string(title)}"']

    if notes:
        properties.append(f'notes:"{escape_applescript_string(notes)}"')

    # Handle deadline
    if deadline:
        import re
        if re.match(r'^\d{4}-\d{2}-\d{2}$', deadline):
            year, month, day = deadline.split('-')
            properties.append(f'due date:(date "{deadline}")')
        else:
            logger.warning(f"Invalid deadline format: {deadline}. Expected YYYY-MM-DD")

    # Determine target list and scheduling
    target_list = "Projects"
    schedule_script = None

    if when:
        if when == 'today':
            target_list = "Projects"
            schedule_script = 'schedule newProject for current date'
        elif when == 'tomorrow':
            target_list = "Projects"
            schedule_script = 'schedule newProject for (current date) + 1 * days'
        elif when == 'anytime':
            target_list = "Projects"
        elif when == 'someday':
            target_list = "Projects"
        elif when == 'evening':
            target_list = "Projects"
            schedule_script = 'schedule newProject for current date'
        else:
            # Try to parse as a date for custom scheduling
            try:
                import datetime
                schedule_date = datetime.datetime.strptime(when, '%Y-%m-%d')
                current_date = datetime.datetime.now()
                days_diff = (schedule_date.date() - current_date.date()).days

                if days_diff <= 0:
                    target_list = "Projects"
                    schedule_script = 'schedule newProject for current date'
                else:
                    target_list = "Projects"
                    schedule_script = f'schedule newProject for (current date) + {days_diff} * days'
            except ValueError:
                logger.warning(f"Invalid date format '{when}', expected YYYY-MM-DD")

    # Create the project
    script_parts.append(f'set newProject to make new project with properties {{{", ".join(properties)}}}')

    # Handle special scheduling
    if schedule_script:
        script_parts.append(schedule_script)

    # Add tags if provided
    if tags and len(tags) > 0:
        # Add each tag individually
        for tag in tags:
            escaped_tag = escape_applescript_string(tag)
            script_parts.append(f'add tag "{escaped_tag}" to newProject')

    # Add to a specific area if specified
    if area_title:
        script_parts.append(f'set area_name to "{escape_applescript_string(area_title)}"')
        script_parts.append('try')
        script_parts.append('  set target_area to first area whose name is area_name')
        script_parts.append('  set area of newProject to target_area')
        script_parts.append('on error')
        script_parts.append('  -- Area not found, project will remain unassigned')
        script_parts.append('end try')

    # Add initial todos if provided
    if todos and len(todos) > 0:
        for todo in todos:
            todo_title = escape_applescript_string(todo)
            script_parts.append(f'tell newProject to make new to do with properties {{name:"{todo_title}"}}')

    # Get the ID of the created project
    script_parts.append('return id of newProject')

    # Close the tell block
    script_parts.append('end tell')

    # Execute the script
    script = '\n'.join(script_parts)
    logger.debug(f"Executing AppleScript: {script}")

    result = run_applescript(script, timeout=8, retries=3)
    if result and result != "false":
        logger.info(f"Successfully created project via AppleScript with ID: {result}")
        return result
    else:
        logger.error("Failed to create project")
        return False

def update_project_direct(id: str, title: Optional[str] = None, notes: Optional[str] = None,
                         when: Optional[str] = None, deadline: Optional[str] = None,
                         tags: Optional[Union[List[str], str]] = None, completed: Optional[bool] = None,
                         canceled: Optional[bool] = None) -> bool:
    """Update a project directly using AppleScript with improved reliability.

    This bypasses URL schemes entirely to avoid authentication issues.

    Args:
        id: The ID of the project to update
        title: New title for the project
        notes: New notes for the project
        when: New schedule for the project (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD)
        deadline: New deadline for the project (YYYY-MM-DD)
        tags: New tags for the project (replaces existing tags)
        completed: Mark as completed
        canceled: Mark as canceled

    Returns:
        True if successful, False otherwise
    """
    # Ensure Things is ready
    if not ensure_things_ready():
        logger.error("Things app is not ready for operations")
        return False

    # Build the AppleScript command to find and update the project
    script_parts = ['tell application "Things3"']
    script_parts.append('try')
    script_parts.append(f'    set theProject to project id "{id}"')

    # Update properties one at a time
    if title:
        script_parts.append(f'    set name of theProject to "{escape_applescript_string(title)}"')

    if notes:
        script_parts.append(f'    set notes of theProject to "{escape_applescript_string(notes)}"')

    # Handle date-related properties
    if when:
        # Check if when is a date in YYYY-MM-DD format
        is_date_format = re.match(r'^\d{4}-\d{2}-\d{2}$', when)

        # Simple mapping of common 'when' values to AppleScript commands
        if when == 'today':
            script_parts.append('    schedule theProject for current date')
        elif when == 'tomorrow':
            script_parts.append('    schedule theProject for ((current date) + (1 * days))')
        elif when == 'evening':
            script_parts.append('    schedule theProject for current date')
        elif when == 'anytime':
            script_parts.append('    set activation date of theProject to missing value')
        elif when == 'someday':
            script_parts.append('    set activation date of theProject to missing value')
        elif is_date_format:
            # Handle YYYY-MM-DD format dates
            year, month, day = when.split('-')
            script_parts.append(f'''
    -- Set activation date with direct date string
    set dateString to "{when}"
    set newDate to date dateString
    set activation date of theProject to newDate
''')
        else:
            # For other formats, just log a warning and don't try to set it
            logger.warning(f"Schedule format '{when}' not directly supported in this simplified version")

    # Handle deadline using the new converter
    if deadline:
        update_applescript_with_due_date(script_parts, deadline, "theProject")

    # Handle tags (adding new ones)
    if tags is not None:
        # Convert string tags to list if needed
        if isinstance(tags, str):
            tags = [tags]

        if tags:
            # Set all tags at once using comma-separated string
            tag_string = ", ".join([escape_applescript_string(tag) for tag in tags])
            script_parts.append(f'    set tag names of theProject to "{tag_string}"')

    # Handle completion status
    if completed is not None:
        if completed:
            script_parts.append('    set status of theProject to completed')
        else:
            script_parts.append('    set status of theProject to open')

    # Handle canceled status
    if canceled is not None:
        if canceled:
            script_parts.append('    set status of theProject to canceled')
        else:
            script_parts.append('    set status of theProject to open')

    # Return true on success
    script_parts.append('    return true')
    script_parts.append('on error errMsg')
    script_parts.append('    log "Error updating project: " & errMsg')
    script_parts.append('    return false')
    script_parts.append('end try')
    script_parts.append('end tell')

    # Execute the script
    script = '\n'.join(script_parts)
    logger.info(f"Executing AppleScript for update_project_direct: \n{script}")

    result = run_applescript(script, timeout=8, retries=3)

    if result == "true":
        logger.info(f"Successfully updated project with ID: {id}")
        return True
    else:
        logger.error(f"AppleScript update_project_direct failed: {result}")
        return False
