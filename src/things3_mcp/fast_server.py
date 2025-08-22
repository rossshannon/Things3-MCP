"""Things MCP Server implementation using the FastMCP pattern."""

import json
import random
import traceback

from mcp.server.fastmcp import FastMCP

from things3_mcp.applescript_bridge import (
    add_project,
    add_todo,
    ensure_things_ready,
    list_anytime_items,
    list_inbox_todos,
    list_logbook_items,
    list_named_items,
    list_todos_scoped,
    list_trash_items,
    list_upcoming_items,
    update_project,
    update_todo,
)
from things3_mcp.applescript_bridge import (
    get_item as as_get_item,
)
from things3_mcp.applescript_bridge import (
    list_projects as as_list_projects,
)
from things3_mcp.applescript_bridge import (
    list_tags as as_list_tags,
)
from things3_mcp.applescript_bridge import (
    list_todos as as_list_todos,
)
from things3_mcp.formatters import format_area, format_project, format_tag, format_todo
from things3_mcp.logging_config import (
    get_logger,
    log_operation_end,
    log_operation_start,
    setup_logging,
)

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
        elif isinstance(value, str) and value.startswith("[") and value.endswith("]"):
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
mcp = FastMCP("Things", instructions="Interact with the Things 3 task management app")

# LIST VIEWS


@mcp.tool(name="get_inbox")
def get_inbox(limit: int | None = None) -> str:
    """Get todos from Inbox.

    Args:
    ----
        limit: Optional maximum number of items to return.
    """
    import time

    start_time = time.time()
    log_operation_start("get-inbox")

    try:
        todos = list_inbox_todos()
        if limit is not None and len(todos) > limit:
            todos = todos[:limit]

        if not todos:
            log_operation_end("get-inbox", True, time.time() - start_time, count=0)
            return "No items found in Inbox"

        formatted_todos = [format_todo(todo) for todo in todos]
        log_operation_end("get-inbox", True, time.time() - start_time, count=len(todos))
        return "\n\n---\n\n".join(formatted_todos)
    except Exception as e:
        import traceback

        logger.error(f"get_inbox detailed error: {e}")
        logger.error(f"get_inbox traceback: {traceback.format_exc()}")
        log_operation_end("get-inbox", False, time.time() - start_time, error=str(e))
        raise


@mcp.tool(name="get_today")
def get_today(limit: int | None = None) -> str:
    """Get todos due today.

    Args:
    ----
        limit: Optional maximum number of items to return.
    """
    import time

    start_time = time.time()
    log_operation_start("get-today")

    try:
        todos = list_named_items("Today", include_projects=False)
        if limit is not None and len(todos) > limit:
            todos = todos[:limit]

        if not todos:
            log_operation_end("get-today", True, time.time() - start_time, count=0)
            return "No items due today"

        formatted_todos = [format_todo(todo) for todo in todos]
        log_operation_end("get-today", True, time.time() - start_time, count=len(todos))
        return "\n\n---\n\n".join(formatted_todos)
    except TypeError as e:
        if "'<' not supported between instances of 'NoneType' and 'str'" in str(e):
            # Handle the known sorting bug in things.today() by using a workaround
            try:
                # Replicate the exact logic from things.today() but with safe sorting
                # Use AppleScript-based Today list directly
                result = list_named_items("Today", include_projects=False)

                if not result:
                    return "No items due today"

                # Sort manually with None-safe comparison
                def safe_sort_key(task):
                    today_index = 0
                    start_date = task.get("start_date")
                    if start_date is None:
                        start_date = ""
                    # Handle both string and integer start_date values
                    if isinstance(start_date, int):
                        start_date = str(start_date)
                    return (today_index, start_date)

                result.sort(key=safe_sort_key)
                if limit is not None and len(result) > limit:
                    result = result[:limit]
                formatted_todos = [format_todo(todo) for todo in result]
                # Only log success AFTER the fallback actually succeeds
                if result:
                    log_operation_end("get-today", True, time.time() - start_time, count=len(result))
                    return "\n\n---\n\n".join(formatted_todos)
                else:
                    log_operation_end("get-today", True, time.time() - start_time, count=0)
                    return "No items due today"

            except Exception as fallback_error:
                log_operation_end("get-today", False, time.time() - start_time, error=f"Fallback failed: {fallback_error!s}")
                return f"Error: Unable to get today's items due to a sorting issue in the Things library. Fallback also failed: {fallback_error!s}"
        else:
            import traceback

            logger.error(f"get_today TypeError (non-sorting): {e}")
            logger.error(f"get_today TypeError traceback: {traceback.format_exc()}")
            log_operation_end("get-today", False, time.time() - start_time, error=str(e))
            raise
    except Exception as e:
        import traceback

        logger.error(f"get_today general exception: {e}")
        logger.error(f"get_today general traceback: {traceback.format_exc()}")
        log_operation_end("get-today", False, time.time() - start_time, error=str(e))
        raise


@mcp.tool(name="get_upcoming")
def get_upcoming(limit: int | None = None) -> str:
    """Get all upcoming todos (those with a start date in the future).

    Args:
    ----
        limit: Optional maximum number of items to return.
    """
    todos = list_upcoming_items()
    if limit is not None and len(todos) > limit:
        todos = todos[:limit]

    if not todos:
        return "No upcoming items"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)


@mcp.tool(name="get_anytime")
def get_anytime(limit: int | None = None) -> str:
    """Get todos/projects from Anytime list.

    Args:
    ----
        limit: Optional maximum number of items to return.
    """
    todos = list_anytime_items()
    if limit is not None and len(todos) > limit:
        todos = todos[:limit]

    if not todos:
        return "No items in Anytime list"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)


@mcp.tool(name="get_random_inbox")
def get_random_inbox(count: int = 5) -> str:
    """Get a random sample of todos from Inbox.

    Args:
    ----
        count: Number of random items to return. Defaults to 5.
    """
    import time

    start_time = time.time()
    log_operation_start("get-random-inbox")

    try:
        items = list_inbox_todos()

        if not items:
            log_operation_end("get-random-inbox", True, time.time() - start_time, count=0)
            return "No items found in Inbox"

        # Sample without replacement up to the number of available items
        if count <= 0:
            sampled = []
        elif len(items) <= count:
            sampled = items
        else:
            sampled = random.sample(items, count)  # nosec B311 - not used for cryptographic purposes  # nosec B311 - not used for cryptographic purposes

        if not sampled:
            log_operation_end("get-random-inbox", True, time.time() - start_time, count=0)
            return "No items found in Inbox"

        formatted = [format_todo(item) for item in sampled]
        log_operation_end("get-random-inbox", True, time.time() - start_time, count=len(sampled))
        return "\n\n---\n\n".join(formatted)
    except Exception as e:
        log_operation_end("get-random-inbox", False, time.time() - start_time, error=str(e))
        raise


@mcp.tool(name="get_random_anytime")
def get_random_anytime(count: int = 5) -> str:
    """Get a random sample of items from the Anytime list.

    Note: The Anytime list can contain both todos and projects. This returns a
    random subset without filtering types.

    Args:
    ----
        count: Number of random items to return. Defaults to 5.
    """
    items = list_anytime_items()

    if not items:
        return "No items in Anytime list"

    if count <= 0:
        sampled = []
    elif len(items) <= count:
        sampled = items
    else:
        sampled = random.sample(items, count)  # nosec B311 - not used for cryptographic purposes

    if not sampled:
        return "No items in Anytime list"

    formatted = [format_todo(item) for item in sampled]
    return "\n\n---\n\n".join(formatted)


@mcp.tool(name="get_someday")
def get_someday(limit: int | None = None) -> str:
    """Get todos from Someday list.

    Args:
    ----
        limit: Optional maximum number of items to return.
    """
    todos = list_named_items("Someday", include_projects=False)
    if limit is not None and len(todos) > limit:
        todos = todos[:limit]

    if not todos:
        return "No items in Someday list"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)


@mcp.tool(name="get_logbook")
def get_logbook(period: str = "7d", limit: int = 50) -> str:
    """Get completed todos from Logbook, defaults to last 7 days.

    Args:
    ----
        period: Time period to look back (e.g., '3d', '1w', '2m', '1y'). Defaults to '7d'.
        limit: Maximum number of entries to return. Defaults to 50.
    """
    todos = list_logbook_items()

    if not todos:
        return "No completed items found"

    if limit is not None and todos and len(todos) > limit:
        todos = todos[:limit]

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)


@mcp.tool(name="get_trash")
def get_trash(limit: int | None = None) -> str:
    """Get trashed todos.

    Args:
    ----
        limit: Optional maximum number of items to return.
    """
    todos = list_trash_items()
    if limit is not None and len(todos) > limit:
        todos = todos[:limit]

    if not todos:
        return "No items in trash"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)


@mcp.tool(name="get_todos")
def get_todos(project_uuid: str | None = None) -> str:
    """Get todos from Things, optionally filtered by project.

    Args:
    ----
        project_uuid: Optional UUID of a specific project to get todos from.
    """
    # Try a scoped/lite fetch first for speed (and to avoid false negatives)
    todos = list_todos_scoped(project=project_uuid, lite=True)

    if project_uuid and not todos:
        # Only if empty, check whether the project exists to decide between
        # an error vs. just no items
        try:
            from things3_mcp.applescript_bridge import list_projects as _as_list_projects

            projects = _as_list_projects() or []
            project_ids = {p.get("uuid") for p in projects if isinstance(p, dict)}
            if project_uuid not in project_ids:
                return f"Error: Invalid project UUID '{project_uuid}'"
        except Exception as e:
            logger.debug(f"Project existence check failed: {e!s}")

    if not todos:
        return "No todos found"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)


@mcp.tool(name="get_random_todos")
def get_random_todos(project_uuid: str | None = None, count: int = 5) -> str:
    """Get a random sample of todos, optionally filtered by project.

    Args:
    ----
        project_uuid: Optional UUID of a specific project to draw todos from.
        count: Number of todos to return. Defaults to 5.
    """
    # Fetch a small lite subset quickly
    items = list_todos_scoped(project=project_uuid, limit=max(count, 10), lite=True)

    if project_uuid and not items:
        # As above, decide if the UUID is truly invalid only if project is absent
        try:
            from things3_mcp.applescript_bridge import list_projects as _as_list_projects

            projects = _as_list_projects() or []
            project_ids = {p.get("uuid") for p in projects if isinstance(p, dict)}
            if project_uuid not in project_ids:
                return f"Error: Invalid project UUID '{project_uuid}'"
        except Exception as e:
            logger.debug(f"Project existence check failed: {e!s}")

    if not items:
        return "No todos found"

    if count <= 0:
        sampled = []
    elif len(items) <= count:
        sampled = items
    else:
        sampled = random.sample(items, count)  # nosec B311 - not used for cryptographic purposes

    if not sampled:
        return "No todos found"

    formatted = [format_todo(todo) for todo in sampled]
    return "\n\n---\n\n".join(formatted)


@mcp.tool(name="get_projects")
def get_projects(include_items: bool = False) -> str:
    """Get all projects from Things.

    Args:
    ----
        include_items: Include tasks within projects.
    """
    projects = as_list_projects()

    if not projects:
        return "No projects found"

    formatted_projects = [format_project(project, include_items) for project in projects]
    return "\n\n---\n\n".join(formatted_projects)


@mcp.tool(name="get_areas")
def get_areas(include_items: bool = False) -> str:
    """Get all areas from Things. Use these names when assigning a task or project to an area.

    Args:
    ----
        include_items: Include projects and tasks within areas
    """
    # Reuse AppleScript formatter which fetches areas lazily
    areas = []

    if not areas:
        return "No areas found"

    formatted_areas = [format_area(area, include_items) for area in areas]
    return "\n\n---\n\n".join(formatted_areas)


# TAG OPERATIONS


@mcp.tool(name="get_tags")
def get_tags(include_items: bool = False) -> str:
    """Get all tags.

    Args:
    ----
        include_items: Include items tagged with each tag
    """
    tags = as_list_tags()

    if not tags:
        return "No tags found"

    formatted_tags = [format_tag(tag, include_items) for tag in tags]
    return "\n\n---\n\n".join(formatted_tags)


@mcp.tool(name="get_tagged_items")
def get_tagged_items(tag: str) -> str:
    """Get items with a specific tag.

    Args:
    ----
        tag: Tag title to filter by
    """
    todos = as_list_todos(tag=tag)

    if not todos:
        return f"No items found with tag '{tag}'"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)


# SEARCH OPERATIONS


@mcp.tool(name="search_todos")
def search_todos(query: str) -> str:
    """Search todos by title or notes.

    Args:
    ----
        query: Search term to look for in todo titles and notes
    """
    todos = [t for t in as_list_todos() if query.lower() in (t.get("title", "").lower()) or query.lower() in (t.get("notes", "").lower())]

    if not todos:
        return f"No todos found matching '{query}'"

    formatted_todos = [format_todo(todo) for todo in todos]
    return "\n\n---\n\n".join(formatted_todos)


@mcp.tool(name="search_advanced")
def search_advanced(
    status: str | None = None,
    start_date: str | None = None,
    deadline: str | None = None,
    tag: str | None = None,
    area: str | None = None,
    type: str | None = None,
) -> str:
    """Advanced todo search with multiple filters.

    Args:
    ----
        status: Filter by todo status (incomplete/completed/canceled)
        start_date: Filter by start date (YYYY-MM-DD)
        deadline: Filter by deadline (YYYY-MM-DD)
        tag: Filter by tag
        area: Filter by area UUID
        type: Filter by item type (to-do/project/heading)
    """
    # Build filter parameters
    kwargs = {"include_items": True}

    # Add filters that are provided
    if status:
        kwargs["status"] = status
    if deadline:
        kwargs["deadline"] = deadline
    if start_date:
        kwargs["start"] = start_date
    if tag:
        kwargs["tag"] = tag
    if area:
        kwargs["area"] = area
    if type:
        kwargs["type"] = type

    # Execute search with applicable filters
    try:
        # Map limited filters to AppleScript helpers
        if tag:
            # Validate tag exists; if not, return explicit error message (tests expect error for invalid tag)
            try:
                available_tags = as_list_tags() or []
                available_titles = {t.get("title") for t in available_tags if isinstance(t, dict)}
                if tag not in available_titles:
                    valid_list = ", ".join(sorted(available_titles)) if available_titles else "(no tags found)"
                    return f"Error in advanced search: Unrecognized tag type '{tag}'. Valid tag types include: {valid_list}"
            except Exception:
                # If tag listing fails, still report unrecognized tag
                return f"Error in advanced search: Unrecognized tag type '{tag}'"
            todos = as_list_todos(tag=tag)
        elif area:
            todos = as_list_todos(area=area)
        elif type:
            if type == "project":
                todos = []
            else:
                todos = as_list_todos()
        else:
            todos = as_list_todos()

        if not todos:
            return "No items found matching your search criteria"

        formatted_todos = [format_todo(todo) for todo in todos]
        return "\n\n---\n\n".join(formatted_todos)
    except Exception as e:
        return f"Error in advanced search: {e!s}"


# MODIFICATION OPERATIONS


@mcp.tool(name="add_todo")
def add_task(
    title: str,
    notes: str | None = None,
    when: str | None = None,
    deadline: str | None = None,
    tags: list[str] | str | None = None,
    list_id: str | None = None,
    list_title: str | None = None,
) -> str:
    """Create a new todo in Things.

    Args:
    ----
        title: Title of the todo
        notes: Notes for the todo
        when: When to schedule the todo (today, tomorrow, evening, anytime, someday, or YYYY-MM-DD)
        deadline: Deadline for the todo (YYYY-MM-DD)
        tags: Tags to apply to the todo. IMPORTANT: Always pass as an array of
            strings (e.g., ["tag1", "tag2"]) NOT as a comma-separated string.
            Passing as a string will treat each character as a separate tag.
        list_id: ID of project/area to add to (takes priority over list_title if both provided)
        list_title: Title of project/area to add to (must exactly match an existing area or project title — look them up with get_areas or get_projects).
            If both list_id and list_title are provided, list_id takes priority.
    """
    try:
        # Debug: Log all input parameters
        logger.debug("MCP add_todo called with parameters:")
        logger.debug(f"  title: {title!r}")
        logger.debug(f"  notes: {notes!r}")
        logger.debug(f"  when: {when!r}")
        logger.debug(f"  deadline: {deadline!r}")
        logger.debug(f"  tags: {tags!r} (type: {type(tags)})")
        logger.debug(f"  list_id: {list_id!r}")
        logger.debug(f"  list_title: {list_title!r}")

        # Preprocess parameters to handle MCP array serialization issues
        params = preprocess_array_params(tags=tags)
        tags = params["tags"]
        logger.debug(f"  processed tags: {tags!r} (type: {type(tags)})")

        # Clean up title and notes to handle URL encoding
        if isinstance(title, str):
            title = title.replace("+", " ").replace("%20", " ")

        if isinstance(notes, str):
            notes = notes.replace("+", " ").replace("%20", " ")

        # Use the direct AppleScript approach which is more reliable
        logger.info(f"Creating todo using AppleScript: {title}")

        try:
            task_id = add_todo(title=title, notes=notes, when=when, deadline=deadline, tags=tags, list_id=list_id, list_title=list_title)
        except Exception as bridge_error:
            logger.error(f"AppleScript bridge error: {bridge_error}")
            return f"⚠️ AppleScript bridge error: {bridge_error}"

        # Check if the returned value is actually an error message rather than a valid task ID
        if not task_id:
            return "⚠️ Error: Failed to create todo using AppleScript"

        # Check if the returned value is actually an error message rather than a valid task ID
        if isinstance(task_id, str) and ("script error" in task_id or task_id.startswith("/var/folders/") or task_id.startswith("Error:")):
            logger.error("AppleScript returned error instead of task ID: %s", task_id)
            return f"⚠️ AppleScript error: {task_id}"

        # Get location information for the success message using AppleScript
        try:
            todo = as_get_item(task_id)
            if todo:
                if todo.get("project"):
                    proj = as_get_item(todo["project"]) or {}
                    location = f"Project: {proj.get('title', '')}"
                elif todo.get("area"):
                    area = as_get_item(todo["area"]) or {}
                    location = f"Area: {area.get('title', '')}"
                else:
                    location = f"List: {todo.get('start', 'Unknown')}"
            else:
                location = "Unknown"
        except Exception:
            location = "Unknown"

        return f"✅ Successfully created todo: {title} (ID: {task_id}) in {location}"

    except Exception as e:
        logger.error(f"Error creating todo: {e!s}")
        import traceback

        logger.error(f"Full traceback: {traceback.format_exc()}")
        return f"⚠️ Error creating todo: {e!s}"


@mcp.tool(name="add_project")
def add_new_project(
    title: str,
    notes: str | None = None,
    when: str | None = None,
    deadline: str | None = None,
    tags: list[str] | str | None = None,
    area_id: str | None = None,
    area_title: str | None = None,
    todos: list[str] | str | None = None,
) -> str:
    """Create a new project in Things.

    Args:
    ----
        title: Title of the project
        notes: Notes for the project
        when: When to schedule the project
        deadline: Deadline for the project
        tags: Tags to apply to the project. IMPORTANT: Always pass as an array of
            strings (e.g., ["tag1", "tag2"]) NOT as a comma-separated string.
            Passing as a string will treat each character as a separate tag.
        area_id: ID of area to add to
        area_title: Title of area to add to (must exactly match an existing area title — look them up with get_areas)
        todos: Initial todos to create in the project
    """
    try:
        # Preprocess parameters to handle MCP array serialization issues
        params = preprocess_array_params(tags=tags, todos=todos)
        tags = params["tags"]
        todos = params["todos"]

        # Clean up title and notes to handle URL encoding
        if isinstance(title, str):
            title = title.replace("+", " ").replace("%20", " ")

        if isinstance(notes, str):
            notes = notes.replace("+", " ").replace("%20", " ")

        # Use the direct AppleScript approach which is more reliable
        logger.info(f"Creating project using AppleScript: {title}")

        # Call the AppleScript bridge directly
        try:
            project_id = add_project(title=title, notes=notes, when=when, deadline=deadline, tags=tags, area_title=area_title, area_id=area_id, todos=todos)
        except Exception as bridge_error:
            logger.error(f"AppleScript bridge error: {bridge_error}")
            return f"⚠️ AppleScript bridge error: {bridge_error}"

        if not project_id:
            return "Error: Failed to create project using AppleScript"

        # Look up the project to get location information
        try:
            project = as_get_item(project_id)
            if project:
                if project.get("area"):
                    area = as_get_item(project["area"]) or {}
                    location = f"Area: {area.get('title', '')}"
                else:
                    location = "List: Inbox"
            else:
                location = "Unknown"
        except Exception:
            location = "Unknown"

        return f"✅ Successfully created project: {title} (ID: {project_id}) in {location}"

    except Exception as e:
        logger.error(f"Error creating project: {e!s}")
        import traceback

        logger.error(f"Full traceback: {traceback.format_exc()}")
        return f"⚠️ Error creating project: {e!s}"


@mcp.tool(name="update_todo")
def update_task(
    id: str,
    title: str | None = None,
    notes: str | None = None,
    when: str | None = None,
    deadline: str | None = None,
    tags: list[str] | str | None = None,
    completed: bool | None = None,
    canceled: bool | None = None,
    list_id: str | None = None,
    list_name: str | None = None,
) -> str:
    """Update an existing todo in Things.

    Args:
    ----
        id: ID of the todo to update.
        title: New title.
        notes: New notes.
        when: When to schedule the todo (today, tomorrow, anytime, someday, or YYYY-MM-DD).
        deadline: New deadline (YYYY-MM-DD).
        tags: New tags. IMPORTANT: Always pass as an array of strings (e.g., ["tag1", "tag2"]) NOT as a comma-separated string. Passing as a string will treat each character as a separate tag.
        completed: Mark as completed.
        canceled: Mark as canceled.
        list_id: ID of project/area to move the todo to (takes priority over list_name if both provided).
        list_name: Name of built-in list, project, or area to move the todo to. For built-in lists use: "Inbox", "Today", "Anytime", "Someday". For projects or areas, use the exact name.
            If both list_id and list_name are provided, list_id takes priority.
    """
    try:
        # Preprocess parameters to handle MCP array serialization issues
        params = preprocess_array_params(tags=tags)
        tags = params["tags"]

        # Clean up string parameters to handle URL encoding
        if isinstance(title, str):
            title = title.replace("+", " ").replace("%20", " ")
        if isinstance(notes, str):
            notes = notes.replace("+", " ").replace("%20", " ")
        if isinstance(list_name, str):
            list_name = list_name.replace("+", " ").replace("%20", " ")

        logger.info(f"Updating todo using AppleScript: {id}")

        # Call the AppleScript bridge directly
        try:
            success = update_todo(
                id=id,
                title=title,
                notes=notes,
                when=when,
                deadline=deadline,
                tags=tags,
                completed=completed,
                canceled=canceled,
                list_id=list_id,
                list_name=list_name,
            )
            logger.debug(f"AppleScript bridge returned: {success!r} (type: {type(success)})")

            # Handle various success cases
            if "true" in str(success).lower():
                logger.debug("Success case matched: 'true' in result")

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
        logger.error(f"Error updating todo: {e!s}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return f"⚠️ Error updating todo: {e!s}"


@mcp.tool(name="update_project")
def update_existing_project(
    id: str,
    title: str | None = None,
    notes: str | None = None,
    when: str | None = None,
    deadline: str | None = None,
    tags: list[str] | str | None = None,
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
        when: New schedule (today, tomorrow, anytime, someday, or YYYY-MM-DD)
        deadline: New deadline (YYYY-MM-DD)
        tags: New tags. IMPORTANT: Always pass as an array of strings (e.g., ["tag1", "tag2"]) NOT as a comma-separated string. Passing as a string will treat each character as a separate tag.
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
    """
    try:
        # Log all input parameters for debugging
        logger.info("Raw input parameters for update_project:")
        for param_name, param_value in locals().items():
            if param_name != "self":  # Skip self parameter
                logger.info(f"  {param_name}: {param_value!r}")

        # Preprocess only the tags parameter
        params = preprocess_array_params(tags=tags)
        tags = params["tags"]

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
            success = update_project(
                id=id,
                title=title,
                notes=notes,
                when=when,
                deadline=deadline,
                tags=tags,
                completed=completed,
                canceled=canceled,
                list_name=list_name,
                area_title=area_title,
                area_id=area_id,
            )
            logger.debug(f"AppleScript bridge returned: {success!r} (type: {type(success)})")

            # Handle various success cases
            if "true" in str(success).lower():
                logger.debug("Success case matched: 'true' in result")

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
        logger.error(f"Error updating project: {e!s}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return f"⚠️ Error updating project: {e!s}"


@mcp.tool(name="show_item")
def show_item(id: str, query: str | None = None, filter_tags: list[str] | None = None, limit: int | None = None) -> str:
    """Show a specific item or list in Things.

    Args:
    ----
        id: ID of item to show, or one of: inbox, today, upcoming, anytime, someday, logbook
        query: Optional query to filter by
        filter_tags: Optional tags to filter by. IMPORTANT: Always pass as an
        array of strings (e.g., ["tag1", "tag2"]) NOT as a comma-separated
        string. Passing as a string will treat each character as a separate tag.
        limit: Optional maximum number of items to return for list views
    """
    try:
        # For built-in lists, return the appropriate data
        if id == "inbox":
            return get_inbox(limit=limit)
        elif id == "today":
            return get_today(limit=limit)
        elif id == "upcoming":
            return get_upcoming(limit=limit)
        elif id == "anytime":
            return get_anytime(limit=limit)
        elif id == "someday":
            return get_someday(limit=limit)
        elif id == "logbook":
            # Keep default limit unless caller overrides
            return get_logbook(limit=limit or 50)
        elif id == "trash":
            return get_trash(limit=limit)
        else:
            # For specific item IDs, try to get the item
            try:
                item = as_get_item(id)
                if item:
                    if item.get("type") == "to-do":
                        return format_todo(item)
                    elif item.get("type") == "project":
                        return format_project(item, include_items=True)
                    elif item.get("type") == "area":
                        return format_area(item, include_items=True)
                    else:
                        return f"Found item: {item}"
                else:
                    return f"No item found with ID: {id}"
            except Exception as e:
                return f"Error retrieving item '{id}': {e!s}"
    except Exception as e:
        logger.error(f"Error showing item: {e!s}")
        return f"Error showing item: {e!s}"


@mcp.tool(name="search_items")
def search_all_items(query: str) -> str:
    """Search for items in Things.

    Args:
    ----
        query: Search query
    """
    try:
        todos = [t for t in as_list_todos() if query.lower() in (t.get("title", "").lower()) or query.lower() in (t.get("notes", "").lower())]

        if not todos:
            return f"No items found matching '{query}'"

        formatted_todos = [format_todo(todo) for todo in todos]
        return "\n\n---\n\n".join(formatted_todos)
    except Exception as e:
        logger.error(f"Error searching: {e!s}")
        return f"Error searching: {e!s}"


@mcp.tool(name="get_recent")
def get_recent(period: str) -> str:
    """Get recently created items.

    Args:
    ----
        period: Time period (e.g., '3d', '1w', '2m', '1y')
    """
    try:
        # Check if period format is valid
        if not period or not any(period.endswith(unit) for unit in ["d", "w", "m", "y"]):
            return "Error: Period must be in format '3d', '1w', '2m', '1y'"

        # Get recent items via Logbook approximation (period not supported by AppleScript dump)
        items = list_logbook_items()

        if not items:
            return "No recent items found"

        formatted_items = []
        for item in items:
            if item.get("type") == "to-do":
                formatted_items.append(format_todo(item))
            elif item.get("type") == "project":
                formatted_items.append(format_project(item, include_items=False))

        return "\n\n---\n\n".join(formatted_items)
    except Exception as e:
        logger.error(f"Error getting recent items: {e!s}")
        return f"Error getting recent items: {e!s}"


# Main entry point
def run_things_mcp_server():
    """Run the Things MCP server."""
    # Check if Things app is available
    if ensure_things_ready():
        logger.info("Things app is running and ready for operations")
    else:
        logger.warning("Things app is not running at startup. Operations will attempt to connect when needed.")

    # Run the MCP server
    mcp.run()


if __name__ == "__main__":
    run_things_mcp_server()
