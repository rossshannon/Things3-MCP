"""Read items back from Things through AppleScript, for live-test verification.

Live tests check what a write did by reading the item back. They do that here,
through the same scripting interface the writes use, so the test process needs
the Automation permission and nothing else. It never opens the Things database.

The dictionaries use the field names of the ``things`` package (``uuid``,
``title``, ``status``, ``start_date``, ``deadline``, ``project``, ``area``,
``tags``, ``notes``) so assertions read the same either way.
"""

import re
from typing import Any

from tests import conftest

READ_TIMEOUT_SECONDS = 30
BUILT_IN_LISTS = frozenset({"Inbox", "Today", "Anytime", "Upcoming", "Someday", "Logbook"})

_ITEM_ID = re.compile(r"[A-Za-z0-9-]+")
_SEPARATOR = "\x1f"
_FIELDS = ("type", "title", "status", "tags", "deadline", "start_date", "project", "area", "notes")

_GET_SCRIPT = """
on isoDate(theDate)
    if theDate is missing value then return ""
    set theYear to (year of theDate) as integer
    set theMonth to (month of theDate) as integer
    set theDay to (day of theDate) as integer
    return (theYear as text) & "-" & (text -2 thru -1 of ("0" & theMonth)) & "-" & (text -2 thru -1 of ("0" & theDay))
end isoDate

tell application "Things3"
    set theKind to "project"
    try
        set theItem to project id "ITEM_ID"
        set theName to name of theItem
    on error
        set theKind to "to-do"
        try
            set theItem to to do id "ITEM_ID"
            set theName to name of theItem
        on error
            return "missing"
        end try
    end try
    set theStatus to "incomplete"
    if status of theItem is completed then set theStatus to "completed"
    if status of theItem is canceled then set theStatus to "canceled"
    set theTags to ""
    try
        set theTags to (tag names of theItem) as text
    end try
    set theNotes to ""
    try
        set theNotes to (notes of theItem) as text
    end try
    set theDeadline to my isoDate(due date of theItem)
    set theStart to my isoDate(activation date of theItem)
    set theProject to ""
    try
        set theProject to id of (project of theItem)
    end try
    set theArea to ""
    try
        set theArea to id of (area of theItem)
    end try
    set sep to character id 31
    return "item" & sep & theKind & sep & theName & sep & theStatus & sep & theTags & sep & theDeadline & sep & theStart & sep & theProject & sep & theArea & sep & theNotes & sep & "end"
end tell
"""

_IN_LIST_SCRIPT = """
tell application "Things3"
    if (count of (to dos of list "LIST_NAME" whose id is "ITEM_ID")) > 0 then return "true"
    try
        if (count of (projects of list "LIST_NAME" whose id is "ITEM_ID")) > 0 then return "true"
    end try
    return "false"
end tell
"""


def _checked_id(item_id: Any) -> str | None:
    """Return an id that is safe to place in a script, or ``None`` for anything else."""
    return item_id if isinstance(item_id, str) and _ITEM_ID.fullmatch(item_id) else None


def get(item_id: Any) -> dict[str, Any] | None:
    """Return the to-do or project with this id, or ``None`` when Things has no such item.

    Completed and cancelled items are found too; Things resolves an id wherever the item is.
    """
    checked = _checked_id(item_id)
    if checked is None:
        return None
    output = conftest.run_applescript(_GET_SCRIPT.replace("ITEM_ID", checked), timeout=READ_TIMEOUT_SECONDS)
    if output == "missing":
        return None
    marker, *values, end = output.split(_SEPARATOR)
    if marker != "item" or end != "end" or len(values) != len(_FIELDS):
        raise ValueError(f"Things returned an item record with {len(values)} fields; expected {len(_FIELDS)}")
    item: dict[str, Any] = dict(zip(_FIELDS, values, strict=True))
    item["uuid"] = checked
    item["tags"] = [name.strip() for name in item["tags"].split(",") if name.strip()]
    for optional in ("deadline", "start_date", "project", "area"):
        item[optional] = item[optional] or None
    return item


def in_list(item_id: Any, list_name: str) -> bool:
    """Return whether a to-do or project is shown in one of the built-in lists."""
    if list_name not in BUILT_IN_LISTS:
        raise ValueError(f"Unknown built-in list: {list_name}")
    checked = _checked_id(item_id)
    if checked is None:
        return False
    script = _IN_LIST_SCRIPT.replace("LIST_NAME", list_name).replace("ITEM_ID", checked)
    return conftest.run_applescript(script, timeout=READ_TIMEOUT_SECONDS) == "true"
