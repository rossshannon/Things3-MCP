"""Things MCP Server implementation using the FastMCP pattern."""

import json
import random
import traceback

from mcp.server.fastmcp import FastMCP

from .applescript_bridge import (
    ensure_things_ready,
)
from .formatters import format_area, format_project, format_tag, format_todo
from .logging_config import (
    get_logger,
    log_operation_end,
    log_operation_start,
    setup_logging,
)
from .providers import ProviderError, get_provider

# Configure enhanced logging
setup_logging(console_level="INFO", file_level="DEBUG", structured_logs=True)
logger = get_logger(__name__)

DEFAULT_TRASH_LIMIT = 50
MAX_TRASH_LIMIT = 200


def _provider_error_response(error: ProviderError) -> str:
    """Render provider failures as clear MCP tool output instead of hangs."""
    return str(error)


def _resolve_todo_location(task_id: str) -> str:
    """Look up the new todo's project/area/list via the provider chain.

    Used for the post-create success message ("✅ Successfully created todo:
    Title (ID: …) in Project Foo"). Routed through the provider so this lookup
    shares the bridge's stable identity rather than calling ``things.get()``
    directly from the MCP-server process — otherwise any host without FDA gets
    "in Unknown" silently. On any read failure we still fall back to "Unknown"
    because the create itself already succeeded; the location is decoration.
    """
    try:
        provider = get_provider()
        todo = provider.get(task_id)
        if not todo:
            return "Unknown"
        if todo.get("project"):
            project = provider.get(todo["project"])
            if project:
                return f"Project: {project['title']}"
        if todo.get("area"):
            area = provider.get(todo["area"])
            if area:
                return f"Area: {area['title']}"
        return f"List: {todo.get('start', 'Unknown')}"
    except Exception:  # noqa: BLE001 - location is decorative; never block the create response
        return "Unknown"


def _resolve_project_location(project_id: str) -> str:
    """Same as :func:`_resolve_todo_location` but for the post-create-project response."""
    try:
        provider = get_provider()
        project = provider.get(project_id)
        if not project:
            return "Unknown"
        if project.get("area"):
            area = provider.get(project["area"])
            if area:
                return f"Area: {area['title']}"
        return "List: Inbox"
    except Exception:  # noqa: BLE001 - same reasoning as _resolve_todo_location
        return "Unknown"


def _format_todo_items(items: list[dict], provider) -> str:
    return "\n\n---\n\n".join(format_todo(item, get_item=provider.get) for item in items)


def _sample_items(items: list[dict], count: int) -> list[dict]:
    """Return a random sample without replacement."""
    if count <= 0:
        return []
    if len(items) <= count:
        return items
    return random.sample(items, count)  # nosec B311 - not used for cryptographic purposes


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
def get_inbox() -> str:
    """Get todos from Inbox."""
    import time

    start_time = time.time()
    log_operation_start("get-inbox")

    try:
        provider = get_provider()
        todos = provider.inbox(include_items=True)

        if not todos:
            log_operation_end("get-inbox", True, time.time() - start_time, count=0)
            return "No items found in Inbox"

        log_operation_end("get-inbox", True, time.time() - start_time, count=len(todos))
        return _format_todo_items(todos, provider)
    except ProviderError as e:
        log_operation_end("get-inbox", False, time.time() - start_time, error=str(e))
        return _provider_error_response(e)
    except Exception as e:
        log_operation_end("get-inbox", False, time.time() - start_time, error=str(e))
        raise


@mcp.tool(name="get_today")
def get_today() -> str:
    """Get todos due today."""
    import time

    start_time = time.time()
    log_operation_start("get-today")

    try:
        provider = get_provider()
        todos = provider.today(include_items=True)

        if not todos:
            log_operation_end("get-today", True, time.time() - start_time, count=0)
            return "No items due today"

        log_operation_end("get-today", True, time.time() - start_time, count=len(todos))
        return _format_todo_items(todos, provider)
    except ProviderError as e:
        log_operation_end("get-today", False, time.time() - start_time, error=str(e))
        return _provider_error_response(e)
    except Exception as e:
        log_operation_end("get-today", False, time.time() - start_time, error=str(e))
        raise


@mcp.tool(name="get_upcoming")
def get_upcoming() -> str:
    """Get all upcoming todos (those with a start date in the future)."""
    try:
        provider = get_provider()
        todos = provider.upcoming(include_items=True)
    except ProviderError as e:
        return _provider_error_response(e)

    if not todos:
        return "No upcoming items"

    return _format_todo_items(todos, provider)


@mcp.tool(name="get_anytime")
def get_anytime() -> str:
    """Get all todos from Anytime list. Note that this will return an extensive list of tasks. It is generally recommended to use get_todos with filters or search_todos instead."""
    try:
        provider = get_provider()
        todos = provider.anytime(include_items=True)
    except ProviderError as e:
        return _provider_error_response(e)

    if not todos:
        return "No items in Anytime list"

    return _format_todo_items(todos, provider)


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
        provider = get_provider()
        items = provider.inbox(include_items=True)

        if not items:
            log_operation_end("get-random-inbox", True, time.time() - start_time, count=0)
            return "No items found in Inbox"

        # Sample without replacement up to the number of available items
        sampled = _sample_items(items, count)

        if not sampled:
            log_operation_end("get-random-inbox", True, time.time() - start_time, count=0)
            return "No items found in Inbox"

        formatted = [format_todo(item, get_item=provider.get) for item in sampled]
        log_operation_end("get-random-inbox", True, time.time() - start_time, count=len(sampled))
        return "\n\n---\n\n".join(formatted)
    except ProviderError as e:
        log_operation_end("get-random-inbox", False, time.time() - start_time, error=str(e))
        return _provider_error_response(e)
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
    try:
        provider = get_provider()
        items = provider.anytime(include_items=True)
    except ProviderError as e:
        return _provider_error_response(e)

    if not items:
        return "No items in Anytime list"

    sampled = _sample_items(items, count)
    if not sampled:
        return "No items in Anytime list"

    formatted = [format_todo(item, get_item=provider.get) for item in sampled]
    return "\n\n---\n\n".join(formatted)


@mcp.tool(name="get_someday")
def get_someday() -> str:
    """Get todos from Someday list."""
    try:
        provider = get_provider()
        todos = provider.someday(include_items=True)
    except ProviderError as e:
        return _provider_error_response(e)

    if not todos:
        return "No items in Someday list"

    return _format_todo_items(todos, provider)


@mcp.tool(name="get_logbook")
def get_logbook(period: str = "7d", limit: int = 50) -> str:
    """Get completed todos from Logbook, defaults to last 7 days.

    Args:
    ----
        period: Time period to look back (e.g., '3d', '1w', '2m', '1y'). Defaults to '7d'.
        limit: Maximum number of entries to return. Defaults to 50.
    """
    import time
    from datetime import datetime, timedelta

    start_time = time.time()
    log_operation_start("get-logbook")

    try:
        # Parse period (e.g., "1d", "7d", "2w", "1m", "1y")
        if not period or period[-1] not in ["d", "w", "m", "y"]:
            log_operation_end("get-logbook", False, time.time() - start_time, error=f"Invalid period format: {period}")
            return f"Error: Invalid period format '{period}'. Expected format: '3d', '1w', '2m', '1y'"

        number = int(period[:-1])
        unit = period[-1]

        # Calculate start date based on period
        if unit == "d":
            start_date = (datetime.now() - timedelta(days=number)).strftime("%Y-%m-%d")
        elif unit == "w":
            start_date = (datetime.now() - timedelta(weeks=number)).strftime("%Y-%m-%d")
        elif unit == "m":
            start_date = (datetime.now() - timedelta(days=number * 30)).strftime("%Y-%m-%d")
        elif unit == "y":
            start_date = (datetime.now() - timedelta(days=number * 365)).strftime("%Y-%m-%d")

        logger.debug(f"Logbook query: period={period}, start_date>={start_date}")

        try:
            provider = get_provider()
            # stop_date filter selects by completion date — fixes the historical
            # bug where items were filtered by creation date instead.
            todos = provider.tasks(status="completed", stop_date=f">={start_date}", include_items=True)
        except ProviderError as e:
            log_operation_end("get-logbook", False, time.time() - start_time, error=str(e))
            return _provider_error_response(e)

        if not todos:
            log_operation_end("get-logbook", True, time.time() - start_time, count=0)
            return "No completed items found"

        # Sort by completion date, newest first; tolerate None values.
        todos.sort(key=lambda x: x.get("stop_date") or "", reverse=True)

        if len(todos) > limit:
            todos = todos[:limit]

        log_operation_end("get-logbook", True, time.time() - start_time, count=len(todos))
        return _format_todo_items(todos, provider)

    except ValueError as e:
        log_operation_end("get-logbook", False, time.time() - start_time, error=str(e))
        return f"Error: Invalid period format '{period}'. Expected format: '3d', '1w', '2m', '1y'"
    except Exception as e:
        log_operation_end("get-logbook", False, time.time() - start_time, error=str(e))
        raise


@mcp.tool(name="get_trash")
def get_trash(limit: int = DEFAULT_TRASH_LIMIT, offset: int = 0) -> str:
    """Get trashed todos.

    Args:
    ----
        limit: Maximum number of trashed items to return. Defaults to 50 and is capped at 200.
        offset: Zero-based offset for paging through large Trash lists.
    """
    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError):
        return "Error: limit and offset must be integers"

    if limit < 1:
        return "Error: limit must be at least 1"
    if offset < 0:
        return "Error: offset must be at least 0"

    requested_limit = limit
    limit = min(limit, MAX_TRASH_LIMIT)

    try:
        provider = get_provider()
        # Trash can be huge. Pull the lightweight shape and avoid formatter
        # relation lookups, otherwise one MCP call can fan out into thousands
        # of /things/get requests.
        todos = provider.trash(include_items=False)
    except ProviderError as e:
        return _provider_error_response(e)

    if not todos:
        return "No items in trash"

    total = len(todos)
    if offset >= total:
        return f"No trash items at offset {offset}. Trash contains {total} items."

    page = todos[offset : offset + limit]
    formatted = [format_todo(todo, get_item=lambda _uuid: None) for todo in page]
    start = offset + 1
    end = offset + len(page)
    footer_parts = [f"Showing trashed items {start}-{end} of {total}."]
    if requested_limit > MAX_TRASH_LIMIT:
        footer_parts.append(f"Requested limit {requested_limit} was capped at {MAX_TRASH_LIMIT}.")
    if end < total:
        footer_parts.append(f"Next page: call get_trash(limit={limit}, offset={end}).")
    return "\n\n---\n\n".join(formatted) + "\n\n" + " ".join(footer_parts)


@mcp.tool(name="get_todos")
def get_todos(project_uuid: str | None = None) -> str:
    """Get todos from Things, optionally filtered by project.

    Args:
    ----
        project_uuid: Optional UUID of a specific project to get todos from.
    """
    try:
        provider = get_provider()
        if project_uuid:
            project = provider.get(project_uuid)
            if not project or project.get("type") != "project":
                return f"Error: Invalid project UUID '{project_uuid}'"

        todos = provider.todos(project=project_uuid, start=None, include_items=True)
    except ProviderError as e:
        return _provider_error_response(e)

    if not todos:
        return "No todos found"

    return _format_todo_items(todos, provider)


@mcp.tool(name="get_random_todos")
def get_random_todos(project_uuid: str | None = None, count: int = 5) -> str:
    """Get a random sample of todos, optionally filtered by project.

    Args:
    ----
        project_uuid: Optional UUID of a specific project to draw todos from.
        count: Number of todos to return. Defaults to 5.
    """
    try:
        provider = get_provider()
        if project_uuid:
            project = provider.get(project_uuid)
            if not project or project.get("type") != "project":
                return f"Error: Invalid project UUID '{project_uuid}'"

        items = provider.todos(project=project_uuid, start=None, include_items=True)
    except ProviderError as e:
        return _provider_error_response(e)

    if not items:
        return "No todos found"

    sampled = _sample_items(items, count)
    if not sampled:
        return "No todos found"

    return _format_todo_items(sampled, provider)


@mcp.tool(name="get_projects")
def get_projects(include_items: bool = False) -> str:
    """Get all projects from Things.

    Args:
    ----
        include_items: Include tasks within projects.
    """
    try:
        provider = get_provider()
        projects = provider.projects(include_items=include_items)
    except ProviderError as e:
        return _provider_error_response(e)

    if not projects:
        return "No projects found"

    formatted_projects = [format_project(project, include_items, get_item=provider.get, get_todos=provider.todos) for project in projects]
    return "\n\n---\n\n".join(formatted_projects)


@mcp.tool(name="get_areas")
def get_areas(include_items: bool = False) -> str:
    """Get all areas from Things. Use these names when assigning a task or project to an area.

    Args:
    ----
        include_items: Include projects and tasks within areas
    """
    try:
        provider = get_provider()
        areas = provider.areas(include_items=include_items)
    except ProviderError as e:
        return _provider_error_response(e)

    if not areas:
        return "No areas found"

    formatted_areas = [format_area(area, include_items, get_projects=provider.projects, get_todos=provider.todos) for area in areas]
    return "\n\n---\n\n".join(formatted_areas)


# TAG OPERATIONS


@mcp.tool(name="get_tags")
def get_tags(include_items: bool = False) -> str:
    """Get all tags.

    Args:
    ----
        include_items: Include items tagged with each tag
    """
    try:
        provider = get_provider()
        tags = provider.tags(include_items=include_items)
    except ProviderError as e:
        return _provider_error_response(e)

    if not tags:
        return "No tags found"

    formatted_tags = [format_tag(tag, include_items, get_todos=provider.todos) for tag in tags]
    return "\n\n---\n\n".join(formatted_tags)


@mcp.tool(name="get_tagged_items")
def get_tagged_items(tag: str) -> str:
    """Get items with a specific tag.

    Args:
    ----
        tag: Tag title to filter by
    """
    try:
        provider = get_provider()
        todos = provider.todos(tag=tag, include_items=True)
    except ProviderError as e:
        return _provider_error_response(e)

    if not todos:
        return f"No items found with tag '{tag}'"

    return _format_todo_items(todos, provider)


# SEARCH OPERATIONS


@mcp.tool(name="search_todos")
def search_todos(query: str) -> str:
    """Search todos by title or notes.

    Args:
    ----
        query: Search term to look for in todo titles and notes
    """
    try:
        provider = get_provider()
        todos = provider.search(query, include_items=True)
    except ProviderError as e:
        return _provider_error_response(e)

    if not todos:
        return f"No todos found matching '{query}'"

    return _format_todo_items(todos, provider)


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

    # Execute search with applicable filters via the provider chain.
    # Preserve the legacy "Error in advanced search:" contract — callers (and
    # tests) rely on this prefix to distinguish search failures from no-results
    # outcomes. ProviderError gets unwrapped to its underlying message so
    # things-py's ValueErrors (e.g. "Unrecognized tag type: '...'") surface
    # with their original wording.
    try:
        provider = get_provider()
        todos = provider.todos(**kwargs)
    except ProviderError as e:
        return f"Error in advanced search: {e.message}"
    except Exception as e:
        return f"Error in advanced search: {e!s}"

    if not todos:
        return "No items found matching your search criteria"

    return _format_todo_items(todos, provider)


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

        logger.info(f"Creating todo through provider: {title}")

        try:
            params = {"title": title, "notes": notes, "when": when, "deadline": deadline, "tags": tags, "list_id": list_id, "list_title": list_title}
            # Drop None values so the provider doesn't pass them as kwargs to applescript_bridge.
            params = {k: v for k, v in params.items() if v is not None}
            result = get_provider().add_task(params)
        except ProviderError as bridge_error:
            logger.error(f"Provider error creating todo: {bridge_error}")
            return f"⚠️ Provider error: {bridge_error}"

        task_id = result.get("id") if isinstance(result, dict) else None
        if not task_id:
            return "⚠️ Error: Failed to create todo (no ID returned)"

        # Resolve location info for the success message via the provider so we
        # don't bypass the bridge's stable identity here. On any read failure
        # the location stays "Unknown" — the create itself already succeeded.
        location = _resolve_todo_location(task_id)

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

        logger.info(f"Creating project through provider: {title}")

        try:
            params = {"title": title, "notes": notes, "when": when, "deadline": deadline, "tags": tags, "area_title": area_title, "area_id": area_id, "todos": todos}
            params = {k: v for k, v in params.items() if v is not None}
            result = get_provider().add_project(params)
        except ProviderError as bridge_error:
            logger.error(f"Provider error creating project: {bridge_error}")
            return f"⚠️ Provider error: {bridge_error}"

        project_id = result.get("id") if isinstance(result, dict) else None
        if not project_id:
            return "Error: Failed to create project (no ID returned)"

        # Resolve location via the provider chain — see _resolve_todo_location.
        location = _resolve_project_location(project_id)

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

        logger.info(f"Updating todo through provider: {id}")

        try:
            params = {
                "title": title,
                "notes": notes,
                "when": when,
                "deadline": deadline,
                "tags": tags,
                "completed": completed,
                "canceled": canceled,
                "list_id": list_id,
                "list_name": list_name,
            }
            params = {k: v for k, v in params.items() if v is not None}
            get_provider().update_task(id, params)
            return f"✅ Successfully updated todo with ID: {id}"
        except ProviderError as bridge_error:
            logger.error(f"Provider error updating todo: {bridge_error}")
            return f"⚠️ Provider error: {bridge_error}"

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

        logger.info(f"Updating project through provider: {id}")

        try:
            params = {
                "title": title,
                "notes": notes,
                "when": when,
                "deadline": deadline,
                "tags": tags,
                "completed": completed,
                "canceled": canceled,
                "list_name": list_name,
                "area_title": area_title,
                "area_id": area_id,
            }
            params = {k: v for k, v in params.items() if v is not None}
            get_provider().update_project(id, params)
            return f"✅ Successfully updated project with ID: {id}"
        except ProviderError as bridge_error:
            logger.error(f"Provider error updating project: {bridge_error}")
            return f"⚠️ Provider error: {bridge_error}"

    except Exception as e:
        logger.error(f"Error updating project: {e!s}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return f"⚠️ Error updating project: {e!s}"


@mcp.tool(name="show_item")
def show_item(id: str, query: str | None = None, filter_tags: list[str] | None = None) -> str:
    """Show a specific item or list in Things.

    Args:
    ----
        id: ID of item to show, or one of: inbox, today, upcoming, anytime, someday, logbook
        query: Optional query to filter by
        filter_tags: Optional tags to filter by. IMPORTANT: Always pass as an
        array of strings (e.g., ["tag1", "tag2"]) NOT as a comma-separated
        string. Passing as a string will treat each character as a separate tag.
    """
    try:
        # For built-in lists, return the appropriate data
        if id == "inbox":
            return get_inbox()
        elif id == "today":
            return get_today()
        elif id == "upcoming":
            return get_upcoming()
        elif id == "anytime":
            return get_anytime()
        elif id == "someday":
            return get_someday()
        elif id == "logbook":
            return get_logbook()
        elif id == "trash":
            return get_trash()
        else:
            # For specific item IDs, route through the provider chain.
            try:
                provider = get_provider()
                item = provider.get(id)
                if item:
                    if item.get("type") == "to-do":
                        return format_todo(item, get_item=provider.get)
                    elif item.get("type") == "project":
                        return format_project(item, include_items=True, get_item=provider.get, get_todos=provider.todos)
                    elif item.get("type") == "area":
                        return format_area(item, include_items=True, get_projects=provider.projects, get_todos=provider.todos)
                    else:
                        return f"Found item: {item}"
                else:
                    return f"No item found with ID: {id}"
            except ProviderError as e:
                return _provider_error_response(e)
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
        provider = get_provider()
        todos = provider.search(query, include_items=True)
    except ProviderError as e:
        return _provider_error_response(e)
    except Exception as e:
        logger.error(f"Error searching: {e!s}")
        return f"Error searching: {e!s}"

    if not todos:
        return f"No items found matching '{query}'"

    return _format_todo_items(todos, provider)


@mcp.tool(name="get_recent")
def get_recent(period: str) -> str:
    """Get recently created items.

    Args:
    ----
        period: Time period (e.g., '3d', '1w', '2m', '1y')
    """
    if not period or not any(period.endswith(unit) for unit in ["d", "w", "m", "y"]):
        return "Error: Period must be in format '3d', '1w', '2m', '1y'"

    try:
        provider = get_provider()
        items = provider.last(period, include_items=True)
    except ProviderError as e:
        return _provider_error_response(e)
    except Exception as e:
        logger.error(f"Error getting recent items: {e!s}")
        return f"Error getting recent items: {e!s}"

    if not items:
        return f"No items found in the last {period}"

    formatted_items = []
    for item in items:
        if item.get("type") == "to-do":
            formatted_items.append(format_todo(item, get_item=provider.get))
        elif item.get("type") == "project":
            formatted_items.append(format_project(item, include_items=False, get_item=provider.get, get_todos=provider.todos))

    return "\n\n---\n\n".join(formatted_items)


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
