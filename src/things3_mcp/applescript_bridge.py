#!/usr/bin/env python3
"""AppleScript bridge for interacting with Things.app.

This module provides a reliable interface for executing AppleScript commands
to interact with the Things task management application on macOS. It handles
all the complexities of string escaping and error handling.
"""

import logging
import subprocess  # nosec B404 - Required for running AppleScript commands
import tempfile
from datetime import datetime

from .date_converter import update_applescript_with_due_date

logger = logging.getLogger(__name__)


def run_applescript(script: str, timeout: int = 8) -> str:
    """Run an AppleScript command and return its output."""
    logger.debug(f"Running AppleScript:\n{script}")

    try:
        # Handle special characters by writing to a temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".applescript", delete=False) as f:
            f.write(script)
            script_path = f.name

        logger.info(f"Running script from file: {script_path}")

        # Run the AppleScript from the file
        process = subprocess.Popen(["osascript", script_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # nosec B607 B603
        stdout, stderr = process.communicate(timeout=timeout)

        # Clean up the temporary file
        import os

        os.unlink(script_path)

        # Log the results
        logger.debug(f"AppleScript return code: {process.returncode}")
        logger.debug(f"AppleScript stdout: {stdout.decode('utf-8') if stdout else 'None'}")
        logger.debug(f"AppleScript stderr: {stderr.decode('utf-8') if stderr else 'None'}")

        # Check for errors
        if process.returncode != 0:
            error_msg = stderr.decode("utf-8") if stderr else "Unknown error"
            logger.error(f"AppleScript error: {error_msg}")
            return error_msg

        # Return the output
        output = stdout.decode("utf-8").strip()
        logger.debug(f"AppleScript output (raw): {output!r}")

        # Convert boolean responses to consistent string format
        if output.lower() == "true":
            logger.debug("Converting 'true' response")
            return "true"
        elif output.lower() == "false":
            logger.debug("Converting 'false' response")
            return "false"
        else:
            logger.debug("Returning raw output")
            return output

    except subprocess.TimeoutExpired:
        logger.error(f"AppleScript timed out after {timeout} seconds")
        process.kill()
        return "Error: AppleScript timed out"
    except Exception as e:
        logger.error(f"Error running AppleScript: {e!s}")
        return f"Error: {e!s}"


# ------------------------------------------------------------
# AppleScript → Python data helpers (query/read APIs)
# ------------------------------------------------------------

# Use ASCII control chars as safe separators that are unlikely to appear in user text
_FIELD_SEP = "\x1f"  # Unit Separator
_ITEM_SEP = "\x1e"   # Record Separator


def _parse_items(output: str, fields: list[str]) -> list[dict]:
    """Parse AppleScript-encoded list of records into list of dicts.

    The AppleScript should return a single string where records are separated
    by ITEM_SEP and fields inside each record by FIELD_SEP.
    """
    if not output:
        return []
    # Treat AppleScript error outputs as empty result sets for list queries
    lowered = output.lower()
    if output.startswith("Error:") or "script error" in lowered or output.startswith("/var/folders/"):
        return []
    items: list[dict] = []
    for raw_item in output.split(_ITEM_SEP):
        if not raw_item:
            continue
        parts = raw_item.split(_FIELD_SEP)
        # Pad or trim to expected length for robustness
        if len(parts) < len(fields):
            parts = parts + [""] * (len(fields) - len(parts))
        elif len(parts) > len(fields):
            parts = parts[: len(fields)]
        item = {field: parts[idx] for idx, field in enumerate(fields)}
        items.append(item)
    return items


def _build_date_iso_script(as_var: str) -> list[str]:
    """Return AppleScript snippet lines to convert a date to YYYY-MM-DD in variable as_var.

    Expects a variable holding a date value (or missing value). Produces a text
    variable with name as_var & "_iso".
    """
    return [
        f"set {as_var}_iso to \"\"",
        f"if {as_var} is not missing value then",
        f"  set _y to year of {as_var} as integer",
        f"  set _m to month of {as_var} as integer",
        f"  set _d to day of {as_var} as integer",
        "  set _m2 to text -2 thru -1 of ((\"0\" & _m) as text)",
        "  set _d2 to text -2 thru -1 of ((\"0\" & _d) as text)",
        f"  set {as_var}_iso to (_y as text) & \"-\" & _m2 & \"-\" & _d2",
        "end if",
    ]


def _make_list_items_script(list_name: str, include_projects: bool = False) -> str:
    """Build AppleScript to dump items from a Things list into a delimited string.

    Fields per record (todos):
      id, title, notes, status, due_iso, project_id, project_name, area_id, area_name, tag_names

    If include_projects=True, also append projects from the same list with:
      id, title, notes, status, due_iso, "", "", area_id, area_name, tag_names
    and an extra field type ("to-do" or "project").
    """
    lines: list[str] = []
    lines.append(f'set _FIELD_SEP to "{_FIELD_SEP}"')
    lines.append(f'set _ITEM_SEP to "{_ITEM_SEP}"')
    lines.append('set _out to ""')
    lines.append('tell application "Things3"')
    # Todos in the list
    lines.append(f'  set _todos to to dos of list "{list_name}"')
    lines.append('  repeat with t in _todos')
    lines.append('    set _id to id of t')
    lines.append('    set _title to name of t')
    lines.append('    set _notes to notes of t')
    lines.append('    set _status to status of t as text')
    lines.append('    set _start to activation date of t')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_start')])
    lines.append('    set _due to due date of t')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_due')])
    # Project/Area
    lines.append('    set _proj_id to ""')
    lines.append('    set _proj_name to ""')
    lines.append('    try')
    lines.append('      set _proj_id to id of project of t')
    lines.append('      set _proj_name to name of project of t')
    lines.append('    end try')
    lines.append('    set _area_id to ""')
    lines.append('    set _area_name to ""')
    lines.append('    try')
    lines.append('      set _area_id to id of area of t')
    lines.append('      set _area_name to name of area of t')
    lines.append('    end try')
    # Tags as comma-separated
    lines.append('    set _tags to ""')
    lines.append('    try')
    lines.append('      set _tags to tag names of t as text')
    lines.append('    end try')
    # Build record (type = to-do)
    lines.append('    set _rec to _id & _FIELD_SEP & _title & _FIELD_SEP & _notes & _FIELD_SEP & _status & _FIELD_SEP & _start_iso & _FIELD_SEP & _due_iso & _FIELD_SEP & _proj_id & _FIELD_SEP & _proj_name & _FIELD_SEP & _area_id & _FIELD_SEP & _area_name & _FIELD_SEP & _tags & _FIELD_SEP & "to-do"')
    lines.append('    if _out is "" then')
    lines.append('      set _out to _rec')
    lines.append('    else')
    lines.append('      set _out to _out & _ITEM_SEP & _rec')
    lines.append('    end if')
    lines.append('  end repeat')

    if include_projects:
        lines.append(f'  set _projects to projects of list "{list_name}"')
        lines.append('  repeat with p in _projects')
        lines.append('    set _id to id of p')
        lines.append('    set _title to name of p')
        lines.append('    set _notes to notes of p')
        lines.append('    set _status to status of p as text')
        lines.append('    set _start to activation date of p')
        lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_start')])
        lines.append('    set _due to due date of p')
        lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_due')])
        lines.append('    set _area_id to ""')
        lines.append('    set _area_name to ""')
        lines.append('    try')
        lines.append('      set _area_id to id of area of p')
        lines.append('      set _area_name to name of area of p')
        lines.append('    end try')
        # tags
        lines.append('    set _tags to ""')
        lines.append('    try')
        lines.append('      set _tags to tag names of p as text')
        lines.append('    end try')
        lines.append('    set _rec to _id & _FIELD_SEP & _title & _FIELD_SEP & _notes & _FIELD_SEP & _status & _FIELD_SEP & _start_iso & _FIELD_SEP & _due_iso & _FIELD_SEP & "" & _FIELD_SEP & "" & _FIELD_SEP & _area_id & _FIELD_SEP & _area_name & _FIELD_SEP & _tags & _FIELD_SEP & "project"')
        lines.append('    if _out is "" then')
        lines.append('      set _out to _rec')
        lines.append('    else')
        lines.append('      set _out to _out & _ITEM_SEP & _rec')
        lines.append('    end if')
        lines.append('  end repeat')

    lines.append('end tell')
    lines.append('return _out')
    return "\n".join(lines)


def _make_all_todos_script() -> str:
    """AppleScript to dump all todos everywhere as delimited lines."""
    lines: list[str] = []
    lines.append(f'set _FIELD_SEP to "{_FIELD_SEP}"')
    lines.append(f'set _ITEM_SEP to "{_ITEM_SEP}"')
    lines.append('set _out to ""')
    lines.append('tell application "Things3"')
    lines.append('  set _todos to every to do')
    lines.append('  repeat with t in _todos')
    lines.append('    set _id to id of t')
    lines.append('    set _title to name of t')
    lines.append('    set _notes to notes of t')
    lines.append('    set _status to status of t as text')
    lines.append('    set _start to activation date of t')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_start')])
    lines.append('    set _due to due date of t')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_due')])
    lines.append('    set _proj_id to ""')
    lines.append('    set _proj_name to ""')
    lines.append('    try')
    lines.append('      set _proj_id to id of project of t')
    lines.append('      set _proj_name to name of project of t')
    lines.append('    end try')
    lines.append('    set _area_id to ""')
    lines.append('    set _area_name to ""')
    lines.append('    try')
    lines.append('      set _area_id to id of area of t')
    lines.append('      set _area_name to name of area of t')
    lines.append('    end try')
    lines.append('    set _tags to ""')
    lines.append('    try')
    lines.append('      set _tags to tag names of t as text')
    lines.append('    end try')
    lines.append('    set _rec to _id & _FIELD_SEP & _title & _FIELD_SEP & _notes & _FIELD_SEP & _status & _FIELD_SEP & _start_iso & _FIELD_SEP & _due_iso & _FIELD_SEP & _proj_id & _FIELD_SEP & _proj_name & _FIELD_SEP & _area_id & _FIELD_SEP & _area_name & _FIELD_SEP & _tags & _FIELD_SEP & "to-do"')
    lines.append('    if _out is "" then')
    lines.append('      set _out to _rec')
    lines.append('    else')
    lines.append('      set _out to _out & _ITEM_SEP & _rec')
    lines.append('    end if')
    lines.append('  end repeat')
    lines.append('end tell')
    lines.append('return _out')
    return "\n".join(lines)


def list_inbox_todos() -> list[dict]:
    """Return todos in Inbox as list of dicts (AppleScript-based)."""
    script = _make_list_items_script("Inbox", include_projects=False)
    output = run_applescript(script, timeout=20)
    fields = [
        "uuid",
        "title",
        "notes",
        "status",
        "start_date",
        "deadline",
        "project",
        "project_title",
        "area",
        "area_title",
        "tags",
        "type",
    ]
    items = _parse_items(output, fields)
    for it in items:
        if it.get("tags"):
            it["tags"] = [s.strip() for s in it["tags"].split(",") if s.strip()]
    return items


def list_today_items() -> list[dict]:
    """Return todos and projects in Today."""
    script = _make_list_items_script("Today", include_projects=True)
    output = run_applescript(script, timeout=20)
    fields = [
        "uuid",
        "title",
        "notes",
        "status",
        "start_date",
        "deadline",
        "project",
        "project_title",
        "area",
        "area_title",
        "tags",
        "type",
    ]
    items = _parse_items(output, fields)
    for it in items:
        if it.get("tags"):
            it["tags"] = [s.strip() for s in it["tags"].split(",") if s.strip()]
    return items


def list_named_items(list_name: str, include_projects: bool = False) -> list[dict]:
    """Generic list reader for a built-in Things list by name."""
    script = _make_list_items_script(list_name, include_projects=include_projects)
    output = run_applescript(script, timeout=20)
    fields = [
        "uuid",
        "title",
        "notes",
        "status",
        "start_date",
        "deadline",
        "project",
        "project_title",
        "area",
        "area_title",
        "tags",
        "type",
    ]
    items = _parse_items(output, fields)
    for it in items:
        if it.get("tags"):
            it["tags"] = [s.strip() for s in it["tags"].split(",") if s.strip()]
    return items


def list_anytime_items() -> list[dict]:
    """Return items from the Anytime list (todos only for stability/perf)."""
    return list_named_items("Anytime", include_projects=False)


def list_someday_items() -> list[dict]:
    """Return items from the Someday list (todos only for stability/perf)."""
    return list_named_items("Someday", include_projects=False)


def list_upcoming_items() -> list[dict]:
    """Return items from the Upcoming list (future-scheduled, todos only)."""
    return list_named_items("Upcoming", include_projects=False)


def list_trash_items() -> list[dict]:
    """Return trashed todos (skip projects for stability/perf)."""
    return list_named_items("Trash", include_projects=False)


def list_logbook_items() -> list[dict]:
    """Return completed items from the Logbook (todos and projects)."""
    return list_named_items("Logbook", include_projects=True)


def list_projects(area: str | None = None) -> list[dict]:
    """Return all projects, optionally filtered by area id."""
    lines: list[str] = []
    lines.append(f'set _FIELD_SEP to "{_FIELD_SEP}"')
    lines.append(f'set _ITEM_SEP to "{_ITEM_SEP}"')
    lines.append('set _out to ""')
    lines.append('tell application "Things3"')
    if area:
        lines.append(f'  set _projects to projects of area id "{area}"')
    else:
        lines.append('  set _projects to every project')
    lines.append('  repeat with p in _projects')
    lines.append('    set _id to id of p')
    lines.append('    set _title to name of p')
    lines.append('    set _notes to notes of p')
    lines.append('    set _status to status of p as text')
    lines.append('    set _due to due date of p')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_due')])
    lines.append('    set _area_id to ""')
    lines.append('    set _area_name to ""')
    lines.append('    try')
    lines.append('      set _area_id to id of area of p')
    lines.append('      set _area_name to name of area of p')
    lines.append('    end try')
    lines.append('    set _tags to ""')
    lines.append('    try')
    lines.append('      set _tags to tag names of p as text')
    lines.append('    end try')
    lines.append('    set _rec to _id & _FIELD_SEP & _title & _FIELD_SEP & _notes & _FIELD_SEP & _status & _FIELD_SEP & _due_iso & _FIELD_SEP & _area_id & _FIELD_SEP & _area_name & _FIELD_SEP & _tags')
    lines.append('    if _out is "" then')
    lines.append('      set _out to _rec')
    lines.append('    else')
    lines.append('      set _out to _out & _ITEM_SEP & _rec')
    lines.append('    end if')
    lines.append('  end repeat')
    lines.append('end tell')
    lines.append('return _out')
    output = run_applescript("\n".join(lines), timeout=25)
    fields = ["uuid", "title", "notes", "status", "deadline", "area", "area_title", "tags"]
    items = _parse_items(output, fields)
    for it in items:
        it["type"] = "project"
        if it.get("tags"):
            it["tags"] = [s.strip() for s in it["tags"].split(",") if s.strip()]
    return items


def list_areas() -> list[dict]:
    """Return all areas."""
    script = "\n".join(
        [
            f'set _FIELD_SEP to "{_FIELD_SEP}"',
            f'set _ITEM_SEP to "{_ITEM_SEP}"',
            'set _out to ""',
            'tell application "Things3"',
            '  set _areas to every area',
            '  repeat with a in _areas',
            '    set _id to id of a',
            '    set _title to name of a',
            '    set _notes to notes of a',
            '    set _rec to _id & _FIELD_SEP & _title & _FIELD_SEP & _notes',
            '    if _out is "" then set _out to _rec else set _out to _out & _ITEM_SEP & _rec',
            '  end repeat',
            'end tell',
            'return _out',
        ]
    )
    output = run_applescript(script, timeout=20)
    fields = ["uuid", "title", "notes"]
    items = _parse_items(output, fields)
    for it in items:
        it["type"] = "area"
    return items


def list_tags() -> list[dict]:
    """Return all tags."""
    script = "\n".join(
        [
            f'set _FIELD_SEP to "{_FIELD_SEP}"',
            f'set _ITEM_SEP to "{_ITEM_SEP}"',
            'set _out to ""',
            'tell application "Things3"',
            '  set _tags to every tag',
            '  repeat with tg in _tags',
            '    set _id to id of tg',
            '    set _title to name of tg',
            '    set _shortcut to ""',
            '    try set _shortcut to shortcut of tg as text end try',
            '    set _rec to _id & _FIELD_SEP & _title & _FIELD_SEP & _shortcut',
            '    if _out is "" then set _out to _rec else set _out to _out & _ITEM_SEP & _rec',
            '  end repeat',
            'end tell',
            'return _out',
        ]
    )
    output = run_applescript(script, timeout=20)
    fields = ["uuid", "title", "shortcut"]
    items = _parse_items(output, fields)
    return items


def list_todos(project: str | None = None, area: str | None = None, tag: str | None = None) -> list[dict]:
    """Return todos filtered by project id, area id, or tag title.

    Optimized to avoid "every to do" when filters are provided. Supports a
    lightweight mode (no notes/tags) via lite parameter and a limit to stop early.
    """
    return list_todos_scoped(project=project, area=area, tag=tag, limit=None, lite=False)


def list_todos_scoped(project: str | None = None, area: str | None = None, tag: str | None = None, limit: int | None = None, lite: bool = False) -> list[dict]:
    """Return todos with optional scoping and performance flags.

    - project: Things project id to scope within
    - area: Things area id to scope within
    - tag: Tag name to filter items by
    - limit: If provided, stop after emitting this many items
    - lite: If True, omit notes and tags for speed
    """
    lines: list[str] = []
    lines.append(f'set _FIELD_SEP to "{_FIELD_SEP}"')
    lines.append(f'set _ITEM_SEP to "{_ITEM_SEP}"')
    lines.append('set _out to ""')
    lines.append('set _count to 0')
    lines.append('tell application "Things3"')
    # Resolve scope source list
    if project:
        lines.append(f'  set _source to to dos of project id "{project}"')
    elif area:
        lines.append(f'  set _source to to dos of area id "{area}"')
    elif tag:
        # Tag scoping: iterate all todos of tag
        # Note: Things AppleScript allows "to dos of tag \"Name\""
        escaped_tag = tag.replace('"', '\\"')
        lines.append(f'  set _source to to dos of tag "{escaped_tag}"')
    else:
        lines.append('  set _source to every to do')
    lines.append('  repeat with t in _source')
    lines.append('    set _id to id of t')
    lines.append('    set _title to name of t')
    lines.append('    set _status to status of t as text')
    lines.append('    set _start to activation date of t')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_start')])
    lines.append('    set _due to due date of t')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_due')])
    if lite:
        lines.append('    set _notes to ""')
        lines.append('    set _tags to ""')
    else:
        lines.append('    set _notes to notes of t')
        lines.append('    set _tags to ""')
        lines.append('    try')
        lines.append('      set _tags to tag names of t as text')
        lines.append('    end try')
    lines.append('    set _proj_id to ""')
    lines.append('    set _proj_name to ""')
    lines.append('    try')
    lines.append('      set _proj_id to id of project of t')
    lines.append('      set _proj_name to name of project of t')
    lines.append('    end try')
    lines.append('    set _area_id to ""')
    lines.append('    set _area_name to ""')
    lines.append('    try')
    lines.append('      set _area_id to id of area of t')
    lines.append('      set _area_name to name of area of t')
    lines.append('    end try')
    lines.append('    set _rec to _id & _FIELD_SEP & _title & _FIELD_SEP & _notes & _FIELD_SEP & _status & _FIELD_SEP & _start_iso & _FIELD_SEP & _due_iso & _FIELD_SEP & _proj_id & _FIELD_SEP & _proj_name & _FIELD_SEP & _area_id & _FIELD_SEP & _area_name & _FIELD_SEP & _tags & _FIELD_SEP & "to-do"')
    lines.append('    if _out is "" then set _out to _rec else set _out to _out & _ITEM_SEP & _rec')
    lines.append('    set _count to _count + 1')
    lines.append('    if ' + ("false" if limit is None else f'_count ≥ {limit}') + ' then')
    lines.append('      exit repeat')
    lines.append('    end if')
    lines.append('  end repeat')
    lines.append('end tell')
    lines.append('return _out')
    output = run_applescript("\n".join(lines), timeout=20 if (project or area or tag) else 30)
    fields = [
        "uuid",
        "title",
        "notes",
        "status",
        "start_date",
        "deadline",
        "project",
        "project_title",
        "area",
        "area_title",
        "tags",
        "type",
    ]
    items = _parse_items(output, fields)
    for it in items:
        if it.get("tags"):
            it["tags"] = [s.strip() for s in it["tags"].split(",") if s.strip()]
    return items


def get_item(item_id: str) -> dict | None:
    """Fetch a Things item (to-do, project, or area) by id via AppleScript."""
    lines: list[str] = []
    lines.append(f'set _FIELD_SEP to "{_FIELD_SEP}"')
    lines.append('tell application "Things3"')
    # Try to-do
    lines.append('  try')
    lines.append('    set t to missing value')
    lines.append('    repeat with i from 1 to 10')
    lines.append('      try')
    lines.append(f'        set t to to do id "{item_id}"')
    lines.append('        exit repeat')
    lines.append('      on error')
    lines.append('        delay 0.2')
    lines.append('      end try')
    lines.append('    end repeat')
    lines.append('    if t is missing value then error number -1728')
    lines.append('    set _id to id of t')
    lines.append('    set _title to name of t')
    lines.append('    set _notes to notes of t')
    lines.append('    set _status to status of t as text')
    lines.append('    set _start to activation date of t')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_start')])
    lines.append('    set _due to due date of t')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_due')])
    lines.append('    set _proj_id to ""')
    lines.append('    set _proj_name to ""')
    lines.append('    try')
    lines.append('      set _proj_id to id of project of t')
    lines.append('      set _proj_name to name of project of t')
    lines.append('    end try')
    lines.append('    set _area_id to ""')
    lines.append('    set _area_name to ""')
    lines.append('    try')
    lines.append('      set _area_id to id of area of t')
    lines.append('      set _area_name to name of area of t')
    lines.append('    end try')
    lines.append('    set _tags to ""')
    lines.append('    try')
    lines.append('      set _tags to tag names of t as text')
    lines.append('    end try')
    lines.append('    return "to-do" & _FIELD_SEP & _id & _FIELD_SEP & _title & _FIELD_SEP & _notes & _FIELD_SEP & _status & _FIELD_SEP & _start_iso & _FIELD_SEP & _due_iso & _FIELD_SEP & _proj_id & _FIELD_SEP & _proj_name & _FIELD_SEP & _area_id & _FIELD_SEP & _area_name & _FIELD_SEP & _tags')
    lines.append('  end try')
    # Fallback: some contexts temporarily fail direct id addressing; use a whose query
    lines.append('  try')
    lines.append('    set t to missing value')
    lines.append('    repeat with i from 1 to 10')
    lines.append('      try')
    lines.append(f'        set t to first to do whose id is "{item_id}"')
    lines.append('        exit repeat')
    lines.append('      on error')
    lines.append('        delay 0.2')
    lines.append('      end try')
    lines.append('    end repeat')
    lines.append('    if t is missing value then error number -1728')
    lines.append('    set _id to id of t')
    lines.append('    set _title to name of t')
    lines.append('    set _notes to notes of t')
    lines.append('    set _status to status of t as text')
    lines.append('    set _start to activation date of t')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_start')])
    lines.append('    set _due to due date of t')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_due')])
    lines.append('    set _proj_id to ""')
    lines.append('    set _proj_name to ""')
    lines.append('    try')
    lines.append('      set _proj_id to id of project of t')
    lines.append('      set _proj_name to name of project of t')
    lines.append('    end try')
    lines.append('    set _area_id to ""')
    lines.append('    set _area_name to ""')
    lines.append('    try')
    lines.append('      set _area_id to id of area of t')
    lines.append('      set _area_name to name of area of t')
    lines.append('    end try')
    lines.append('    set _tags to ""')
    lines.append('    try')
    lines.append('      set _tags to tag names of t as text')
    lines.append('    end try')
    lines.append('    return "to-do" & _FIELD_SEP & _id & _FIELD_SEP & _title & _FIELD_SEP & _notes & _FIELD_SEP & _status & _FIELD_SEP & _start_iso & _FIELD_SEP & _due_iso & _FIELD_SEP & _proj_id & _FIELD_SEP & _proj_name & _FIELD_SEP & _area_id & _FIELD_SEP & _area_name & _FIELD_SEP & _tags')
    lines.append('  end try')
    # Try project
    lines.append('  try')
    lines.append(f'    set p to project id "{item_id}"')
    lines.append('    set _id to id of p')
    lines.append('    set _title to name of p')
    lines.append('    set _notes to notes of p')
    lines.append('    set _status to status of p as text')
    lines.append('    set _due to due date of p')
    lines.extend([f'    {script_line}' for script_line in _build_date_iso_script('_due')])
    lines.append('    set _area_id to ""')
    lines.append('    set _area_name to ""')
    lines.append('    try')
    lines.append('      set _area_id to id of area of p')
    lines.append('      set _area_name to name of area of p')
    lines.append('    end try')
    lines.append('    set _tags to ""')
    lines.append('    try')
    lines.append('      set _tags to tag names of p as text')
    lines.append('    end try')
    lines.append('    return "project" & _FIELD_SEP & _id & _FIELD_SEP & _title & _FIELD_SEP & _notes & _FIELD_SEP & _status & _FIELD_SEP & _due_iso & _FIELD_SEP & "" & _FIELD_SEP & "" & _FIELD_SEP & _area_id & _FIELD_SEP & _area_name & _FIELD_SEP & _tags')
    lines.append('  end try')
    # Try area
    lines.append('  try')
    lines.append(f'    set a to area id "{item_id}"')
    lines.append('    set _id to id of a')
    lines.append('    set _title to name of a')
    lines.append('    set _notes to notes of a')
    lines.append('    return "area" & _FIELD_SEP & _id & _FIELD_SEP & _title & _FIELD_SEP & _notes')
    lines.append('  end try')
    lines.append('end tell')
    script = "\n".join(lines)
    logger.info(f"Generated AppleScript for get_item id={item_id}:\n{script}")
    # Retry to tolerate brief reindexing after moves/scheduling
    output = None
    import time as _pytime
    for _attempt in range(15):
        output = run_applescript(script, timeout=20)
        logger.info(f"get_item output (attempt {_attempt+1}): {output!r}")
        if output and not output.lower().startswith("error") and "script error" not in output.lower():
            break
        _pytime.sleep(0.2)
    if not output:
        return None
    parts = output.split(_FIELD_SEP)
    if not parts:
        return None
    if parts[0] == "to-do" and len(parts) >= 12:
        _, uuid, title, notes, status, start_date, deadline, project, project_title, area, area_title, tags = parts[:12]
        item = {
            "type": "to-do",
            "uuid": uuid,
            "title": title,
            "notes": notes,
            "status": status,
            "start_date": start_date,
            "deadline": deadline,
            "project": project,
            "project_title": project_title,
            "area": area,
            "area_title": area_title,
            "tags": [s.strip() for s in tags.split(",") if s.strip()] if tags else [],
        }
        return item
    if parts[0] == "project" and len(parts) >= 11:
        _, uuid, title, notes, status, deadline, _empty1, _empty2, area, area_title, tags = parts[:11]
        item = {
            "type": "project",
            "uuid": uuid,
            "title": title,
            "notes": notes,
            "status": status,
            "deadline": deadline,
            "area": area,
            "area_title": area_title,
            "tags": [s.strip() for s in tags.split(",") if s.strip()] if tags else [],
        }
        return item
    if parts[0] == "area" and len(parts) >= 4:
        _, uuid, title, notes = parts[:4]
        return {"type": "area", "uuid": uuid, "title": title, "notes": notes}
    return None


def search_items(query: str) -> list[dict]:
    """Case-insensitive search across all todos' titles and notes."""
    if not query:
        return []
    items = list_todos()
    q = query.lower()
    return [it for it in items if q in (it.get("title", "").lower()) or q in (it.get("notes", "").lower())]


def ensure_things_ready() -> bool:
    """Ensure Things app is ready for AppleScript operations.

    Returns:
    -------
        bool: True if Things is ready, False otherwise
    """
    try:
        # First check if Things is running
        check_script = 'tell application "System Events" to (name of processes) contains "Things3"'
        result = run_applescript(check_script, timeout=5)

        if not result or result.lower() != "true":
            logger.warning("Things app is not running")
            return False

        # Then check if Things is responsive
        ping_script = 'tell application "Things3" to return name'
        result = run_applescript(ping_script, timeout=5)

        if not result:
            logger.warning("Things app is not responsive")
            return False

        logger.debug("Things app is ready for operations")
        return True

    except Exception as e:
        logger.error(f"Error checking Things readiness: {e!s}")
        return False


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
    text = text.replace("+", " ")

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
        logger.error("Things app is not ready for operations")
        return False

    # Build the AppleScript command
    script_parts = ['tell application "Things3"', "try"]

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
        script_parts.append(f'  set target_project to first project whose id is "{list_id}"')
        script_parts.append("  set project of newTodo to target_project")
        script_parts.append("on error")
        script_parts.append("  try")
        script_parts.append("    -- Try to find as area by ID")
        script_parts.append(f'    set target_area to first area whose id is "{list_id}"')
        script_parts.append("    set area of newTodo to target_area")
        script_parts.append("  on error")
        script_parts.append("    -- Neither project nor area found with ID, will create todo without assignment")
        script_parts.append("  end try")
        script_parts.append("end try")

    # Get the ID of the created todo
    script_parts.append("return id of newTodo")
    script_parts.append("on error errMsg")
    script_parts.append('  log "Error creating todo: " & errMsg')
    script_parts.append("  return false")
    script_parts.append("end try")
    script_parts.append("end tell")

    # Execute the script
    script = "\n".join(script_parts)
    logger.debug(f"Executing simplified AppleScript: {script}")

    result = run_applescript(script, timeout=8)
    if result and result != "false" and "script error" not in result and not result.startswith("/var/folders/") and not result.startswith("Error:"):
        # Log success
        logger.info(f"Successfully created todo via AppleScript with ID: {result}")
        return result
    else:
        logger.error(f"Failed to create todo: {result}")
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

    logger.info(f"Handling scheduling: when='{when}', item_ref='{item_ref}'")

    # Check if it's a valid date format first
    is_date_format = is_valid_date_format(when)

    if when == "today":
        # Schedule for today (don’t move; Today is schedule-driven)
        script_parts.append(f"    schedule {item_ref} for (current date)")
        script_parts.append("    delay 0.3")
    elif when == "tomorrow":
        # Schedule for tomorrow
        script_parts.append(f"    schedule {item_ref} for (current date) + 1 * days")
    elif when == "anytime":
        # Move to Anytime list
        script_parts.append(f'    move {item_ref} to list "Anytime"')
        script_parts.append("    delay 0.3")
    elif when == "someday":
        # Move to Someday list
        script_parts.append(f'    move {item_ref} to list "Someday"')
        script_parts.append("    delay 0.3")
    elif is_date_format:
        # Schedule for specific date
        try:
            target_date = datetime.strptime(when, "%Y-%m-%d").date()
            current_date = datetime.now().date()
            days_diff = (target_date - current_date).days
            logger.debug(f"Date calculation: target={target_date}, current={current_date}, diff={days_diff} days")

            if days_diff <= 0:
                script_parts.append(f"    schedule {item_ref} for (current date)")
            else:
                script_parts.append(f"    schedule {item_ref} for (current date) + {days_diff} * days")
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
            logger.warning(f"Invalid date format '{when}', expected YYYY-MM-DD")
    else:
        logger.warning(f"Unsupported when value: {when}")


def _handle_project_when_scheduling(script_parts: list[str], when: str | None, project_ref: str) -> None:
    """Handle when/scheduling specifically for projects."""
    if not when:
        return

    logger.info(f"Handling project scheduling: when='{when}', project_ref='{project_ref}'")

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
            logger.debug(f"Project date calculation: target={target_date}, current={current_date}, diff={days_diff} days")

            if days_diff <= 0:
                script_parts.append(f"    schedule {project_ref} for (current date)")
            else:
                script_parts.append(f"    schedule {project_ref} for (current date) + {days_diff} * days")
        except ValueError as e:
            logger.error(f"Project date parsing error: {e}")
            logger.warning(f"Invalid date format '{when}', expected YYYY-MM-DD")
    else:
        logger.warning(f"Unsupported when value for project: {when}")


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
        logger.error("Things app is not ready for operations")
        return "Error: Things app is not ready"

    # Build the AppleScript command to find and update the todo
    script_parts = ['tell application "Things3"']
    script_parts.append("try")
    script_parts.append(f'    set theTodo to first to do whose id is "{id}"')

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
        lower_name = (list_name or "").lower()
        builtin_map = {
            "inbox": "Inbox",
            "today": "Today",
            "anytime": "Anytime",
            "someday": "Someday",
            "trash": "Trash",
            "logbook": "Logbook",
        }
        if lower_name in builtin_map:
            target = builtin_map[lower_name]
            if target == "Today":
                # Today is schedule-driven; do not move
                script_parts.append("    schedule theTodo for (current date)")
                script_parts.append('    delay 0.3')
            else:
                script_parts.append(f'    move theTodo to list "{target}"')
                script_parts.append('    delay 0.3')
        else:
            escaped_list = escape_applescript_string(list_name)
            script_parts.append("    try")
            # Try project by name
            script_parts.append(f"        set targetProject to first project whose name is {escaped_list}")
            script_parts.append("        set project of theTodo to targetProject")
            script_parts.append('        delay 0.3')
            script_parts.append("    on error")
            script_parts.append("        try")
            # Try area by name
            script_parts.append(f"            set targetArea to first area whose name is {escaped_list}")
            script_parts.append("            set area of theTodo to targetArea")
            script_parts.append('            delay 0.3')
            script_parts.append("        on error")
            script_parts.append(f'            return "Error: List/Project/Area not found - {list_name}"')
            script_parts.append("        end try")
            script_parts.append("    end try")

    # Handle list assignment by ID (projects or areas only)
    if list_id:
        script_parts.append("    try")
        # Try to find as project by ID
        script_parts.append(f'        set targetProject to first project whose id is "{list_id}"')
        script_parts.append("        set project of theTodo to targetProject")
        script_parts.append('        delay 0.3')
        script_parts.append("    on error")
        script_parts.append("        try")
        # Try to find as area by ID
        script_parts.append(f'            set targetArea to first area whose id is "{list_id}"')
        script_parts.append("            set area of theTodo to targetArea")
        script_parts.append('            delay 0.3')
        script_parts.append("        on error")
        script_parts.append(f'            return "Error: Project/Area not found with ID - {list_id}"')
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
    script_parts.append("on error errMsg")
    script_parts.append('    return "Error: " & errMsg')
    script_parts.append("end try")
    script_parts.append("end tell")

    # Execute the script
    script = "\n".join(script_parts)
    logger.info(f"Generated AppleScript for update_todo:\n{script}")
    print("--- update_todo AppleScript ---\n" + script + "\n--- end ---")
    result = run_applescript(script)
    logger.debug(f"AppleScript result: {result!r}")
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
        logger.error("Things app is not ready for operations")
        return False

    # Build the AppleScript command
    script_parts = ['tell application "Things3"']

    # Handle area assignment BEFORE creating the project
    if area_id or area_title:
        if area_id:
            # Try to find area by ID first
            script_parts.append(f'set area_id to "{area_id}"')
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
    logger.debug(f"Executing AppleScript: {script}")

    result = run_applescript(script, timeout=8)
    if result and result != "false" and "script error" not in result and not result.startswith("/var/folders/") and not result.startswith("Error:"):
        logger.info(f"Successfully created project via AppleScript with ID: {result}")
        return result
    else:
        logger.error(f"Failed to create project: {result}")
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
        logger.warning(f"Invalid list name: {list_name}. Must be one of: {', '.join(valid_lists)}")
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
    logger.info(f"Updating project {id} with title={title}, notes={notes}, when={when}, deadline={deadline}, tags={tags}, completed={completed}, canceled={canceled}, list_name={list_name}, area_title={area_title}")

    script_parts = ['tell application "Things3"']
    script_parts.append("try")
    script_parts.append(f'    set theProject to project id "{id}"')

    # Handle list moves first
    if list_name:
        if list_name in ["Inbox", "Logbook"]:
            error_msg = "Projects cannot be moved to Inbox or Logbook. To move to Logbook, mark the project as completed instead."
            logger.error(error_msg)
            return f"Error: {error_msg}"
        if not move_project_to_list(script_parts, list_name, "theProject"):
            error_msg = f"Invalid list name: {list_name}"
            logger.error(error_msg)
            return f"Error: {error_msg}"
    elif when:
        _handle_project_when_scheduling(script_parts, when, "theProject")

    # Handle area changes
    if area_id:
        # Use area_id if provided (takes precedence over area_title)
        script_parts.append("    try")
        script_parts.append(f'        set targetArea to first area whose id is "{area_id}"')
        script_parts.append("        set area of theProject to targetArea")
        script_parts.append("    on error")
        script_parts.append(f'        return "Error: Area not found with ID - {area_id}"')
        script_parts.append("    end try")
    elif area_title:
        escaped_area = escape_applescript_string(area_title)
        script_parts.append("    try")
        script_parts.append(f"        set targetArea to first area whose name is {escaped_area}")
        script_parts.append("        set area of theProject to targetArea")
        script_parts.append("    on error")
        script_parts.append(f'        return "Error: Area not found - {area_title}"')
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
    script_parts.append("on error errMsg")
    script_parts.append('    return "Error: " & errMsg')
    script_parts.append("end try")
    script_parts.append("end tell")

    # Execute the script
    script = "\n".join(script_parts)
    logger.debug(f"Generated AppleScript:\n{script}")
    result = run_applescript(script)
    logger.debug(f"AppleScript result: {result!r}")
    return result
