#!/usr/bin/env python3
"""
Things MCP Server implementation using the FastMCP pattern.
This provides a more modern and maintainable approach to the Things integration.
"""
import logging
import asyncio
import traceback
import json
from typing import Dict, Any, Optional, List, Union
import things

from mcp.server.fastmcp import FastMCP
import mcp.types as types

# Import supporting modules
from .formatters import format_todo, format_project, format_area, format_tag
from .utils import app_state, circuit_breaker, dead_letter_queue, rate_limiter
from .applescript_bridge import add_todo_direct, update_todo_direct, add_project_direct, update_project_direct, ensure_things_ready

# Import and configure enhanced logging
from .logging_config import setup_logging, get_logger, log_operation_start, log_operation_end
# Import caching
from .cache import cached, invalidate_caches_for, get_cache_stats, CACHE_TTL

# Configure enhanced logging
setup_logging(console_level="INFO", file_level="DEBUG", structured_logs=True)
logger = get_logger(__name__)

def preprocess_array_params(**kwargs):
    """Preprocess parameters to handle MCP framework array serialization issues.

    The MCP framework sometimes passes arrays as strings (e.g., '["tag1", "tag2"]')
    instead of actual arrays. This function detects and parses such cases.
    """
    result = {}
    for key, value in kwargs.items():
        if value is None:
            result[key] = None
        elif isinstance(value, str) and value.startswith('[') and value.endswith(']'):
            # Looks like a stringified array, try to parse it
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    result[key] = parsed
                    logger.debug(f"Parsed stringified array for {key}: {value} -> {parsed}")
                else:
                    result[key] = value
            except (json.JSONDecodeError, ValueError):
                # If parsing fails, keep as string
                result[key] = value
                logger.warning(f"Failed to parse potential array parameter {key}: {value}")
        else:
            result[key] = value
    return result

# Create the FastMCP server
mcp = FastMCP(
    "Things",
    description="Interact with the Things task management app",
    version="0.1.1"
)

# LIST VIEWS

@mcp.tool(name="get_inbox")
def get_inbox() -> str:
    """Get todos from Inbox"""
    import time
    start_time = time.time()
    log_operation_start("get-inbox")

    try:
        todos = things.inbox()

        if not todos:
            log_operation_end("get-inbox", True, time.time() - start_time, count=0)
            return "No items found in Inbox"

        formatted_todos = [format_todo(todo) for todo in todos]
        log_operation_end("get-inbox", True, time.time() - start_time, count=len(todos))
        return "\n\n---\n\n".join(formatted_todos)
    except Exception as e:
        log_operation_end("get-inbox", False, time.time() - start_time, error=str(e))
        raise

@mcp.tool(name="get_today")
def get_today() -> str:
    """Get todos due today"""
    import time
    start_time = time.time()
    log_operation_start("get-today")

    try:
        todos = things.today()

        if not todos:
            log_operation_end("get-today", True, time.time() - start_time, count=0)
            return "No items due today"

        formatted_todos = [format_todo(todo) for todo in todos]
        log_operation_end("get-today", True, time.time() - start_time, count=len(todos))
        return "\n\n---\n\n".join(formatted_todos)
    except TypeError as e:
        if "'<' not supported between instances of 'NoneType' and 'str'" in str(e):
            # Handle the sorting bug in things.today() by using a workaround
            log_operation_end("get-today", True, time.time() - start_time, error="Sorting bug workaround applied")
            try:
                # Replicate the exact logic from things.today() but with safe sorting
                import datetime
                today_str = datetime.date.today().strftime('%Y-%m-%d')

                # Replicate the three categories from things.today():
                # 1. regular_today_tasks: start_date=True (today), start="Anytime", index="todayIndex"
                regular_today_tasks = things.tasks(
                    start_date=True,  # today
                    start="Anytime",
                    index="todayIndex",
                    status="incomplete"
                )

                # 2. unconfirmed_scheduled_tasks: start_date="past", start="Someday", index="todayIndex"
                unconfirmed_scheduled_tasks = things.tasks(
                    start_date="past",
                    start="Someday",
                    index="todayIndex",
                    status="incomplete"
                )

                # 3. unconfirmed_overdue_tasks: start_date=False, deadline="past", deadline_suppressed=False
                unconfirmed_overdue_tasks = things.tasks(
                    start_date=False,
                    deadline="past",
                    deadline_suppressed=False,
                    status="incomplete"
                )

                # Combine all three categories like the original
                result = [
                    *regular_today_tasks,
                    *unconfirmed_scheduled_tasks,
                    *unconfirmed_overdue_tasks,
                ]

                if not result:
                    return "No items due today"

                # Sort manually with None-safe comparison
                def safe_sort_key(task):
                    today_index = task.get("today_index")
                    if today_index is None:
                        today_index = 999999  # Put items without today_index at the end
                    start_date = task.get("start_date")
                    if start_date is None:
                        start_date = ""
                    return (today_index, start_date)

                result.sort(key=safe_sort_key)
                formatted_todos = [format_todo(todo) for todo in result]
                return "\n\n---\n\n".join(formatted_todos)
            except Exception as fallback_error:
                log_operation_end("get-today", False, time.time() - start_time, error=f"Fallback failed: {str(fallback_error)}")
                return f"Error: Unable to get today's items due to a sorting issue in the Things library. Fallback also failed: {str(fallback_error)}"
        else:
            log_operation_end("get-today", False, time.time() - start_time, error=str(e))
            raise
    except Exception as e:
        log_operation_end("get-today", False, time.time() - start_time, error=str(e))
        raise

@mcp.tool(name="get_upcoming")
def get_upcoming() -> str:
    """Get upcoming todos"""
    todos = things.upcoming()

    if not todos:
        return "No upcoming items"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

@mcp.tool(name="get_anytime")
def get_anytime() -> str:
    """Get todos from Anytime list"""
    todos = things.anytime()

    if not todos:
        return "No items in Anytime list"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

@mcp.tool(name="get_someday")
def get_someday() -> str:
    """Get todos from Someday list"""
    todos = things.someday()

    if not todos:
        return "No items in Someday list"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

@mcp.tool(name="get_logbook")
def get_logbook(period: str = "7d", limit: int = 50) -> str:
    """
    Get completed todos from Logbook, defaults to last 7 days

    Args:
        period: Time period to look back (e.g., '3d', '1w', '2m', '1y'). Defaults to '7d'
        limit: Maximum number of entries to return. Defaults to 50
    """
    todos = things.last(period, status='completed')

    if not todos:
        return "No completed items found"

    if todos and len(todos) > limit:
        todos = todos[:limit]

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

@mcp.tool(name="get_trash")
def get_trash() -> str:
    """Get trashed todos"""
    todos = things.trash()

    if not todos:
        return "No items in trash"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

# BASIC TODO OPERATIONS

@mcp.tool(name="get_todos")
def get_todos(project_uuid: Optional[str] = None) -> str:
    """
    Get todos from Things, optionally filtered by project

    Args:
        project_uuid: Optional UUID of a specific project to get todos from
    """
    if project_uuid:
        project = things.get(project_uuid)
        if not project or project.get('type') != 'project':
            return f"Error: Invalid project UUID '{project_uuid}'"

    todos = things.todos(project=project_uuid, start=None)

    if not todos:
        return "No todos found"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

@mcp.tool(name="get_projects")
def get_projects(include_items: bool = False) -> str:
    """
    Get all projects from Things

    Args:
        include_items: Include tasks within projects
    """
    projects = things.projects()

    if not projects:
        return "No projects found"

    formatted_projects = [format_project(project, include_items) for project in projects]
    return "\n\n---\n\n".join(formatted_projects)

@mcp.tool(name="get_areas")
def get_areas(include_items: bool = False) -> str:
    """
    Get all areas from Things

    Args:
        include_items: Include projects and tasks within areas
    """
    areas = things.areas()

    if not areas:
        return "No areas found"

    formatted_areas = [format_area(area, include_items) for area in areas]
    return "\n\n---\n\n".join(formatted_areas)

# TAG OPERATIONS

@mcp.tool(name="get_tags")
def get_tags(include_items: bool = False) -> str:
    """
    Get all tags

    Args:
        include_items: Include items tagged with each tag
    """
    tags = things.tags()

    if not tags:
        return "No tags found"

    formatted_tags = [format_tag(tag, include_items) for tag in tags]
    return "\n\n---\n\n".join(formatted_tags)

@mcp.tool(name="get_tagged_items")
def get_tagged_items(tag: str) -> str:
    """
    Get items with a specific tag

    Args:
        tag: Tag title to filter by
    """
    todos = things.todos(tag=tag)

    if not todos:
        return f"No items found with tag '{tag}'"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

# SEARCH OPERATIONS

@mcp.tool(name="search_todos")
def search_todos(query: str) -> str:
    """
    Search todos by title or notes

    Args:
        query: Search term to look for in todo titles and notes
    """
    todos = things.search(query)

    if not todos:
        return f"No todos found matching '{query}'"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)

@mcp.tool(name="search_advanced")
def search_advanced(
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    deadline: Optional[str] = None,
    tag: Optional[str] = None,
    area: Optional[str] = None,
    type: Optional[str] = None
) -> str:
    """
    Advanced todo search with multiple filters

    Args:
        status: Filter by todo status (incomplete/completed/canceled)
        start_date: Filter by start date (YYYY-MM-DD)
        deadline: Filter by deadline (YYYY-MM-DD)
        tag: Filter by tag
        area: Filter by area UUID
        type: Filter by item type (to-do/project/heading)
    """
    # Build filter parameters
    kwargs = {}

    # Add filters that are provided
    if status:
        kwargs['status'] = status
    if deadline:
        kwargs['deadline'] = deadline
    if start_date:
        kwargs['start'] = start_date
    if tag:
        kwargs['tag'] = tag
    if area:
        kwargs['area'] = area
    if type:
        kwargs['type'] = type

    # Execute search with applicable filters
    try:
        todos = things.todos(**kwargs)

        if not todos:
            return "No items found matching your search criteria"

        formatted_todos = [format_todo(todo) for todo in todos]
        return "\n\n---\n\n".join(formatted_todos)
    except Exception as e:
        return f"Error in advanced search: {str(e)}"

# MODIFICATION OPERATIONS

@mcp.tool(name="add_todo")
def add_task(
    title: str,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[Union[List[str], str]] = None,
    list_id: Optional[str] = None,
    list_title: Optional[str] = None,
) -> str:
    """Create a new todo in Things.

    Args:
        title: Title of the todo
        notes: Notes for the todo
        when: When to schedule the todo (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD)
        deadline: Deadline for the todo (YYYY-MM-DD)
        tags: Tags to apply to the todo. IMPORTANT: Always pass as an array of strings (e.g., ["tag1", "tag2"]) NOT as a comma-separated string. Passing as a string will treat each character as a separate tag.
        list_id: ID of project/area to add to
        list_title: Title of project/area to add to
    """
    try:
        # Preprocess parameters to handle MCP array serialization issues
        params = preprocess_array_params(
            tags=tags
        )
        tags = params['tags']

        # Clean up title and notes to handle URL encoding
        if isinstance(title, str):
            title = title.replace("+", " ").replace("%20", " ")

        if isinstance(notes, str):
            notes = notes.replace("+", " ").replace("%20", " ")

        # Use the direct AppleScript approach which is more reliable
        logger.info(f"Creating todo using AppleScript: {title}")

        # Simple direct call to test
        try:
            task_id = add_todo_direct(title=title, notes=notes, when=when, deadline=deadline, tags=tags, list_title=list_title)
        except Exception as bridge_error:
            logger.error(f"AppleScript bridge error: {bridge_error}")
            return f"⚠️ AppleScript bridge error: {bridge_error}"

        if not task_id:
            return "Error: Failed to create todo using AppleScript"

        # Invalidate relevant caches after creating a todo
        invalidate_caches_for(["get-inbox", "get-today", "get-upcoming", "get-todos"])

        return f"✅ Successfully created todo: {title} (ID: {task_id})"

    except Exception as e:
        logger.error(f"Error creating todo: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return f"⚠️ Error creating todo: {str(e)}"

@mcp.tool(name="add_project")
def add_new_project(
    title: str,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[Union[List[str], str]] = None,
    area_id: Optional[str] = None,
    area_title: Optional[str] = None,
    todos: Optional[Union[List[str], str]] = None
) -> str:
    """
    Create a new project in Things

    Args:
        title: Title of the project
        notes: Notes for the project
        when: When to schedule the project
        deadline: Deadline for the project
        tags: Tags to apply to the project. IMPORTANT: Always pass as an array of strings (e.g., ["tag1", "tag2"]) NOT as a comma-separated string. Passing as a string will treat each character as a separate tag.
        area_id: ID of area to add to
        area_title: Title of area to add to
        todos: Initial todos to create in the project
    """
    try:
        # Preprocess parameters to handle MCP array serialization issues
        params = preprocess_array_params(
            tags=tags,
            todos=todos
        )
        tags = params['tags']
        todos = params['todos']

        # Clean up title and notes to handle URL encoding
        if isinstance(title, str):
            title = title.replace("+", " ").replace("%20", " ")

        if isinstance(notes, str):
            notes = notes.replace("+", " ").replace("%20", " ")

        # Use the direct AppleScript approach which is more reliable
        logger.info(f"Creating project using AppleScript: {title}")

        # Call the AppleScript bridge directly
        try:
            project_id = add_project_direct(
                title=title,
                notes=notes,
                when=when,
                deadline=deadline,
                tags=tags,
                area_title=area_title,
                todos=todos
            )
        except Exception as bridge_error:
            logger.error(f"AppleScript bridge error: {bridge_error}")
            return f"⚠️ AppleScript bridge error: {bridge_error}"

        if not project_id:
            return "Error: Failed to create project using AppleScript"

        # Invalidate relevant caches after creating a project
        invalidate_caches_for(["get-projects", "get-areas"])

        return f"✅ Successfully created project: {title} (ID: {project_id})"

    except Exception as e:
        logger.error(f"Error creating project: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return f"⚠️ Error creating project: {str(e)}"

@mcp.tool(name="update_todo")
def update_task(
    id: str,
    title: Optional[str] = None,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[Union[List[str], str]] = None,
    completed: Optional[bool] = None,
    canceled: Optional[bool] = None,
    project: Optional[str] = None,
    area_title: Optional[str] = None
) -> str:
    """
    Update an existing todo in Things

    Args:
        id: ID of the todo to update
        title: New title
        notes: New notes
        when: When to schedule the todo (today, tomorrow, anytime, someday, or YYYY-MM-DD)
        deadline: New deadline (YYYY-MM-DD)
        tags: New tags. IMPORTANT: Always pass as an array of strings (e.g., ["tag1", "tag2"]) NOT as a comma-separated string. Passing as a string will treat each character as a separate tag.
        completed: Mark as completed
        canceled: Mark as canceled
        project: Project name to move the todo to
        area_title: Title of the area to move the todo to
    """
    try:
        # Preprocess parameters to handle MCP array serialization issues
        params = preprocess_array_params(
            tags=tags
        )
        tags = params['tags']

        # Clean up string parameters to handle URL encoding
        if isinstance(title, str):
            title = title.replace("+", " ").replace("%20", " ")
        if isinstance(notes, str):
            notes = notes.replace("+", " ").replace("%20", " ")
        if isinstance(project, str):
            project = project.replace("+", " ").replace("%20", " ")
        if isinstance(area_title, str):
            area_title = area_title.replace("+", " ").replace("%20", " ")

        # Use the direct AppleScript approach which is more reliable
        logger.info(f"Updating todo using AppleScript: {id}")

        # Call the AppleScript bridge directly
        try:
            success = update_todo_direct(
                id=id,
                title=title,
                notes=notes,
                when=when,
                deadline=deadline,
                tags=tags,
                completed=completed,
                canceled=canceled,
                project=project,
                area_title=area_title
            )
            logger.debug(f"AppleScript bridge returned: {success!r} (type: {type(success)})")

            # Handle various success cases
            if "true" in str(success).lower():
                logger.debug("Success case matched: 'true' in result")
                # Invalidate relevant caches after updating a todo
                invalidate_caches_for(["get-todos", "get-projects", "get-areas"])
                return f"✅ Successfully updated todo with ID: {id}"
            elif success.startswith("Error:"):
                logger.error(f"AppleScript error: {success}")
                return success
            else:
                logger.error(f"AppleScript update failed with result: {success!r}")
                return f"Error: Failed to update todo using AppleScript. Result: {success}"

        except Exception as bridge_error:
            logger.error(f"AppleScript bridge error: {bridge_error}")
            logger.error(f"Full bridge error traceback: {traceback.format_exc()}")
            return f"⚠️ AppleScript bridge error: {bridge_error}"

    except Exception as e:
        logger.error(f"Error updating todo: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return f"⚠️ Error updating todo: {str(e)}"

@mcp.tool(name="update_project")
def update_existing_project(
    id: str,
    title: Optional[str] = None,
    notes: Optional[str] = None,
    when: Optional[str] = None,
    deadline: Optional[str] = None,
    tags: Optional[Union[List[str], str]] = None,
    completed: Optional[bool] = None,
    canceled: Optional[bool] = None,
    list_name: Optional[str] = None,
    area_title: Optional[str] = None
) -> str:
    """
    Update an existing project in Things

    Args:
        id: ID of the project to update
        title: New title
        notes: New notes
        when: New schedule (today, tomorrow, anytime, someday, or YYYY-MM-DD)
        deadline: New deadline (YYYY-MM-DD)
        tags: New tags. IMPORTANT: Always pass as an array of strings (e.g., ["tag1", "tag2"]) NOT as a comma-separated string. Passing as a string will treat each character as a separate tag.
        completed: Mark as completed
        canceled: Mark as canceled
        list_name: Move project directly to a built-in list. Must be one of:
                  - "Today": Move to Today list
                  - "Upcoming": Move to Upcoming list
                  - "Anytime": Move to Anytime list
                  - "Someday": Move to Someday list
                  - "Trash": Move to trash
                  Note: Projects cannot be moved to Inbox or Logbook. To move a project
                  to Logbook, mark it as completed instead.
        area_title: Title of the area to move the project to
    """
    try:
        # Log all input parameters for debugging
        logger.info("Raw input parameters for update_project:")
        for param_name, param_value in locals().items():
            if param_name != 'self':  # Skip self parameter
                logger.info(f"  {param_name}: {param_value!r}")

        # Preprocess only the tags parameter
        params = preprocess_array_params(tags=tags)
        tags = params['tags']

        # Clean up string parameters to handle URL encoding
        if isinstance(title, str):
            title = title.replace("+", " ").replace("%20", " ")
        if isinstance(notes, str):
            notes = notes.replace("+", " ").replace("%20", " ")
        if isinstance(area_title, str):
            area_title = area_title.replace("+", " ").replace("%20", " ")
            logger.info(f"Cleaned area_title: {area_title!r}")

        # Use the direct AppleScript approach which is more reliable
        logger.info(f"Updating project using AppleScript: {id}")

        # Call the AppleScript bridge directly
        try:
            success = update_project_direct(
                id=id,
                title=title,
                notes=notes,
                when=when,
                deadline=deadline,
                tags=tags,
                completed=completed,
                canceled=canceled,
                list_name=list_name,
                area_title=area_title
            )
            logger.debug(f"AppleScript bridge returned: {success!r} (type: {type(success)})")

            # Handle various success cases
            if "true" in str(success).lower():
                logger.debug("Success case matched: 'true' in result")
                # Invalidate relevant caches after updating a project
                invalidate_caches_for(["get-projects", "get-areas", "get-todos"])
                return f"✅ Successfully updated project with ID: {id}"
            elif success.startswith("Error:"):
                logger.error(f"AppleScript error: {success}")
                return success
            else:
                logger.error(f"AppleScript update failed with result: {success!r}")
                return f"Error: Failed to update project using AppleScript. Result: {success}"

        except Exception as bridge_error:
            logger.error(f"AppleScript bridge error: {bridge_error}")
            logger.error(f"Full bridge error traceback: {traceback.format_exc()}")
            return f"⚠️ AppleScript bridge error: {bridge_error}"

    except Exception as e:
        logger.error(f"Error updating project: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return f"⚠️ Error updating project: {str(e)}"

@mcp.tool(name="show_item")
def show_item(
    id: str,
    query: Optional[str] = None,
    filter_tags: Optional[List[str]] = None
) -> str:
    """
    Show a specific item or list in Things

    Args:
        id: ID of item to show, or one of: inbox, today, upcoming, anytime, someday, logbook
        query: Optional query to filter by
        filter_tags: Optional tags to filter by. IMPORTANT: Always pass as an array of strings (e.g., ["tag1", "tag2"]) NOT as a comma-separated string. Passing as a string will treat each character as a separate tag.
    """
    try:
        # Ensure Things app is running
        if not ensure_things_ready():
            return "Error: Unable to connect to Things app"

        # For now, just return a message indicating the item would be shown
        # This functionality can be implemented in AppleScript if needed later
        return f"Note: Show functionality removed. Item '{id}' would be displayed in Things."
    except Exception as e:
        logger.error(f"Error showing item: {str(e)}")
        return f"Error showing item: {str(e)}"

@mcp.tool(name="search_items")
def search_all_items(query: str) -> str:
    """
    Search for items in Things

    Args:
        query: Search query
    """
    try:
        # Ensure Things app is running
        if not ensure_things_ready():
            return "Error: Unable to connect to Things app"

        # For now, just return a message indicating the search would be performed
        # This functionality can be implemented in AppleScript if needed later
        return f"Note: Search functionality removed. Would search for '{query}' in Things."
    except Exception as e:
        logger.error(f"Error searching: {str(e)}")
        return f"Error searching: {str(e)}"

@mcp.tool(name="get_recent")
def get_recent(period: str) -> str:
    """
    Get recently created items

    Args:
        period: Time period (e.g., '3d', '1w', '2m', '1y')
    """
    try:
        # Check if period format is valid
        if not period or not any(period.endswith(unit) for unit in ['d', 'w', 'm', 'y']):
            return "Error: Period must be in format '3d', '1w', '2m', '1y'"

        # Get recent items
        items = things.last(period)

        if not items:
            return f"No items found in the last {period}"

        formatted_items = []
        for item in items:
            if item.get('type') == 'to-do':
                formatted_items.append(format_todo(item))
            elif item.get('type') == 'project':
                formatted_items.append(format_project(item, include_items=False))

        return "\n\n---\n\n".join(formatted_items)
    except Exception as e:
        logger.error(f"Error getting recent items: {str(e)}")
        return f"Error getting recent items: {str(e)}"

@mcp.tool(name="get_cache_stats")
def get_cache_statistics() -> str:
    """Get cache performance statistics"""
    stats = get_cache_stats()

    return f"""Cache Statistics:
- Total entries: {stats['entries']}
- Cache hits: {stats['hits']}
- Cache misses: {stats['misses']}
- Hit rate: {stats['hit_rate']}
- Total requests: {stats['total_requests']}"""



# Main entry point
def run_things_mcp_server():
    """Run the Things MCP server"""
    # Check if Things app is available
    if ensure_things_ready():
        logger.info("Things app is running and ready for operations")
    else:
        logger.warning("Things app is not running at startup. Operations will attempt to connect when needed.")

    # Run the MCP server
    mcp.run()

if __name__ == "__main__":
    run_things_mcp_server()
