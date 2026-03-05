"""AppleScript-based read operations for Things 3.

Uses JXA (JavaScript for Automation) for clean JSON serialization.
Replaces things-py (SQLite) reads with accurate results matching the Things UI.
"""

import json
import logging
import os
import subprocess  # nosec B404 - Required for running JXA scripts
import tempfile
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ── JXA runner ──────────────────────────────────────────────────────────────


def _run_jxa(script: str, timeout: int = 30) -> str | None:
    """Run a JXA script via osascript and return stdout, or None on error."""
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(script)
            tmp = f.name

        proc = subprocess.Popen(  # nosec B603 B607
            ["osascript", "-l", "JavaScript", tmp],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        os.unlink(tmp)

        if proc.returncode != 0:
            err = stderr.decode("utf-8").strip() if stderr else "Unknown error"
            logger.error(f"JXA error (rc={proc.returncode}): {err}")
            return None

        return stdout.decode("utf-8").strip()

    except subprocess.TimeoutExpired:
        proc.kill()
        logger.error(f"JXA timed out after {timeout}s")
        return None
    except Exception as e:
        logger.error(f"JXA runner error: {e}")
        return None


def _jxa_json(script: str, timeout: int = 30) -> list | dict | None:
    """Run JXA and parse JSON output."""
    raw = _run_jxa(script, timeout)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"JXA JSON parse error: {e} — raw[:200]={raw[:200]!r}")
        return None


# ── JXA helper functions (injected into every script) ───────────────────────

_HELPERS = r"""
function fmtDate(d) {
    if (!d) return null;
    return d.getFullYear() + "-" +
        String(d.getMonth()+1).padStart(2,"0") + "-" +
        String(d.getDate()).padStart(2,"0");
}
function fmtDateTime(d) {
    if (!d) return null;
    return fmtDate(d) + " " +
        String(d.getHours()).padStart(2,"0") + ":" +
        String(d.getMinutes()).padStart(2,"0") + ":" +
        String(d.getSeconds()).padStart(2,"0");
}
function mapSt(s) { return s === "open" ? "incomplete" : s; }
function splitTags(s) {
    if (!s) return [];
    return s.split(", ").filter(function(t){ return t.length > 0; });
}

// Per-item serializer (used for single items and small lists)
function todoDict(t) {
    var o = {title:t.name(), uuid:t.id(), type:"to-do", status:mapSt(t.status())};
    var n = t.notes(); if (n) o.notes = n;
    var tg = t.tagNames(); if (tg) o.tags = splitTags(tg);
    var dd = t.dueDate(); if (dd) o.deadline = fmtDate(dd);
    var ad = t.activationDate(); if (ad) o.start_date = fmtDate(ad);
    var cd = t.completionDate(); if (cd) o.stop_date = fmtDate(cd);
    var crd = t.creationDate(); if (crd) o.creation_date = fmtDateTime(crd);
    var md = t.modificationDate(); if (md) o.modification_date = fmtDateTime(md);
    try { var p = t.project(); if (p) { o.project = p.id(); o.project_title = p.name(); } } catch(e){}
    try { var a = t.area(); if (a) { o.area = a.id(); o.area_title = a.name(); } } catch(e){}
    return o;
}

// Batch serializer — uses bulk property access (one Apple Event per property)
// Much faster for large collections (3s vs 17s for 1660 items)
function batchTodoDicts(ref) {
    var n = ref.length;
    if (n === 0) return [];
    var names = ref.name();
    var ids = ref.id();
    var statuses = ref.status();
    var notesList = ref.notes();
    var tagsList = ref.tagNames();
    var dueDates = ref.dueDate();
    var actDates = ref.activationDate();
    var compDates = ref.completionDate();
    var creDates = ref.creationDate();
    var modDates = ref.modificationDate();
    var result = [];
    for (var i = 0; i < n; i++) {
        var o = {title:names[i], uuid:ids[i], type:"to-do", status:mapSt(statuses[i])};
        if (notesList[i]) o.notes = notesList[i];
        if (tagsList[i]) o.tags = splitTags(tagsList[i]);
        if (dueDates[i]) o.deadline = fmtDate(dueDates[i]);
        if (actDates[i]) o.start_date = fmtDate(actDates[i]);
        if (compDates[i]) o.stop_date = fmtDate(compDates[i]);
        if (creDates[i]) o.creation_date = fmtDateTime(creDates[i]);
        if (modDates[i]) o.modification_date = fmtDateTime(modDates[i]);
        result.push(o);
    }
    return result;
}

function batchProjDicts(ref) {
    var n = ref.length;
    if (n === 0) return [];
    var names = ref.name();
    var ids = ref.id();
    var statuses = ref.status();
    var notesList = ref.notes();
    var tagsList = ref.tagNames();
    var dueDates = ref.dueDate();
    var result = [];
    for (var i = 0; i < n; i++) {
        var o = {title:names[i], uuid:ids[i], type:"project", status:mapSt(statuses[i])};
        if (notesList[i]) o.notes = notesList[i];
        if (tagsList[i]) o.tags = splitTags(tagsList[i]);
        if (dueDates[i]) o.deadline = fmtDate(dueDates[i]);
        result.push(o);
    }
    return result;
}

function projDict(p) {
    var o = {title:p.name(), uuid:p.id(), type:"project", status:mapSt(p.status())};
    var n = p.notes(); if (n) o.notes = n;
    var tg = p.tagNames(); if (tg) o.tags = splitTags(tg);
    try { var a = p.area(); if (a) { o.area = a.id(); o.area_title = a.name(); } } catch(e){}
    var dd = p.dueDate(); if (dd) o.deadline = fmtDate(dd);
    return o;
}
function areaDict(a) {
    return {title:a.name(), uuid:a.id(), type:"area"};
}
function tagDict(t) {
    var o = {title:t.name(), uuid:t.id()};
    try { var sc = t.shortcut(); if (sc) o.shortcut = sc; } catch(e){}
    return o;
}
"""


def _script(body: str) -> str:
    """Wrap a JXA function body with helpers."""
    return _HELPERS + "\nfunction run() {\n" + body + "\n}\n"


def _escape_js(s: str) -> str:
    """Escape a string for embedding in a JavaScript string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")


# ── Public API ──────────────────────────────────────────────────────────────


def get_list(list_name: str) -> list[dict]:
    """Get all to-dos from a Things list.

    Args:
        list_name: One of Inbox, Today, Upcoming, Anytime, Someday, Logbook, Trash.

    Returns:
        List of todo dicts.
    """
    valid = ("Inbox", "Today", "Upcoming", "Anytime", "Someday", "Logbook", "Trash")
    if list_name not in valid:
        raise ValueError(f"Invalid list: {list_name}. Must be one of {valid}")

    result = _jxa_json(_script(f'''
    var things = Application("Things3");
    var ref = things.lists["{list_name}"].toDos;
    return JSON.stringify(batchTodoDicts(ref));
    '''), timeout=60)
    return result if isinstance(result, list) else []


def get_by_id(uuid: str) -> dict | None:
    """Get a single item by UUID (to-do, project, or area)."""
    safe = _escape_js(uuid)
    result = _jxa_json(_script(f'''
    var things = Application("Things3");
    var uid = "{safe}";
    try {{
        var todos = things.toDos.whose({{id: uid}})();
        if (todos.length > 0) return JSON.stringify(todoDict(todos[0]));
    }} catch(e) {{}}
    try {{
        var projs = things.projects.whose({{id: uid}})();
        if (projs.length > 0) return JSON.stringify(projDict(projs[0]));
    }} catch(e) {{}}
    try {{
        var areas = things.areas.whose({{id: uid}})();
        if (areas.length > 0) return JSON.stringify(areaDict(areas[0]));
    }} catch(e) {{}}
    return "null";
    '''))
    return result if isinstance(result, dict) else None


def get_todos(project_uuid: str | None = None, area_uuid: str | None = None) -> list[dict]:
    """Get incomplete to-dos, optionally filtered by project or area.

    Args:
        project_uuid: Filter to a specific project.
        area_uuid: Filter to a specific area.
    """
    if project_uuid:
        safe = _escape_js(project_uuid)
        body = f'''
        var things = Application("Things3");
        var projs = things.projects.whose({{id: "{safe}"}})();
        if (projs.length === 0) return "[]";
        var ref = projs[0].toDos;
        return JSON.stringify(batchTodoDicts(ref));
        '''
    elif area_uuid:
        safe = _escape_js(area_uuid)
        body = f'''
        var things = Application("Things3");
        var areas = things.areas.whose({{id: "{safe}"}})();
        if (areas.length === 0) return "[]";
        var ref = areas[0].toDos;
        return JSON.stringify(batchTodoDicts(ref));
        '''
    else:
        body = '''
        var things = Application("Things3");
        var ref = things.toDos;
        return JSON.stringify(batchTodoDicts(ref));
        '''

    result = _jxa_json(_script(body), timeout=60)
    return result if isinstance(result, list) else []


def get_projects(area_uuid: str | None = None) -> list[dict]:
    """Get all open projects, optionally filtered by area.

    Args:
        area_uuid: Filter to a specific area.
    """
    if area_uuid:
        safe = _escape_js(area_uuid)
        body = f'''
        var things = Application("Things3");
        var areas = things.areas.whose({{id: "{safe}"}})();
        if (areas.length === 0) return "[]";
        var ref = areas[0].projects;
        return JSON.stringify(batchProjDicts(ref));
        '''
    else:
        body = '''
        var things = Application("Things3");
        var ref = things.projects;
        return JSON.stringify(batchProjDicts(ref));
        '''

    result = _jxa_json(_script(body), timeout=60)
    return result if isinstance(result, list) else []


def get_areas() -> list[dict]:
    """Get all areas."""
    result = _jxa_json(_script('''
    var things = Application("Things3");
    var areas = things.areas();
    return JSON.stringify(areas.map(areaDict));
    '''))
    return result if isinstance(result, list) else []


def get_tags() -> list[dict]:
    """Get all tags."""
    result = _jxa_json(_script('''
    var things = Application("Things3");
    var tags = things.tags();
    return JSON.stringify(tags.map(tagDict));
    '''))
    return result if isinstance(result, list) else []


def get_tagged_items(tag: str) -> list[dict]:
    """Get all to-dos with a specific tag.

    Args:
        tag: Tag name to filter by.
    """
    safe = _escape_js(tag)
    result = _jxa_json(_script(f'''
    var things = Application("Things3");
    var tags = things.tags.whose({{name: "{safe}"}})();
    if (tags.length === 0) return "[]";
    var ref = tags[0].toDos;
    return JSON.stringify(batchTodoDicts(ref));
    '''), timeout=60)
    return result if isinstance(result, list) else []


def search(query: str) -> list[dict]:
    """Search to-dos by title or notes.

    Args:
        query: Search term (case-insensitive substring match).
    """
    safe = _escape_js(query)
    result = _jxa_json(_script(f'''
    var things = Application("Things3");
    var q = "{safe}";
    var byName = things.toDos.whose({{name: {{_contains: q}}}})();
    var byNotes = things.toDos.whose({{notes: {{_contains: q}}}})();
    var seen = {{}};
    var result = [];
    function add(list) {{
        for (var i = 0; i < list.length; i++) {{
            var id = list[i].id();
            if (!seen[id]) {{
                seen[id] = true;
                result.push(todoDict(list[i]));
            }}
        }}
    }}
    add(byName);
    add(byNotes);
    return JSON.stringify(result);
    '''), timeout=60)
    return result if isinstance(result, list) else []


def get_recent(period: str) -> list[dict]:
    """Get items created within the given period.

    Args:
        period: e.g. "3d", "1w", "2m", "1y"
    """
    if not period or period[-1] not in "dwmy":
        raise ValueError(f"Invalid period: {period}")

    num = int(period[:-1])
    unit = period[-1]

    if unit == "d":
        delta = timedelta(days=num)
    elif unit == "w":
        delta = timedelta(weeks=num)
    elif unit == "m":
        delta = timedelta(days=num * 30)
    else:  # y
        delta = timedelta(days=num * 365)

    cutoff = datetime.now() - delta
    cutoff_ms = int(cutoff.timestamp() * 1000)

    result = _jxa_json(_script(f'''
    var things = Application("Things3");
    var cutoff = new Date({cutoff_ms});
    var ref = things.toDos;
    var n = ref.length;
    var creDates = ref.creationDate();
    var names = ref.name();
    var ids = ref.id();
    var statuses = ref.status();
    var notesList = ref.notes();
    var tagsList = ref.tagNames();
    var dueDates = ref.dueDate();
    var actDates = ref.activationDate();
    var modDates = ref.modificationDate();
    var result = [];
    for (var i = 0; i < n; i++) {{
        if (creDates[i] && creDates[i] >= cutoff) {{
            var o = {{title:names[i], uuid:ids[i], type:"to-do", status:mapSt(statuses[i])}};
            if (notesList[i]) o.notes = notesList[i];
            if (tagsList[i]) o.tags = splitTags(tagsList[i]);
            if (dueDates[i]) o.deadline = fmtDate(dueDates[i]);
            if (actDates[i]) o.start_date = fmtDate(actDates[i]);
            if (creDates[i]) o.creation_date = fmtDateTime(creDates[i]);
            if (modDates[i]) o.modification_date = fmtDateTime(modDates[i]);
            result.push(o);
        }}
    }}
    return JSON.stringify(result);
    '''), timeout=60)
    return result if isinstance(result, list) else []


def get_logbook(start_date: str) -> list[dict]:
    """Get completed to-dos from the Logbook since a given date.

    Args:
        start_date: YYYY-MM-DD format.
    """
    safe = _escape_js(start_date)
    result = _jxa_json(_script(f'''
    var things = Application("Things3");
    var cutoff = new Date("{safe}T00:00:00");
    var ref = things.lists["Logbook"].toDos;
    var n = ref.length;
    if (n === 0) return "[]";
    var compDates = ref.completionDate();
    var names = ref.name();
    var ids = ref.id();
    var statuses = ref.status();
    var notesList = ref.notes();
    var tagsList = ref.tagNames();
    var dueDates = ref.dueDate();
    var creDates = ref.creationDate();
    var result = [];
    for (var i = 0; i < n; i++) {{
        if (compDates[i] && compDates[i] >= cutoff) {{
            var o = {{title:names[i], uuid:ids[i], type:"to-do", status:mapSt(statuses[i])}};
            if (notesList[i]) o.notes = notesList[i];
            if (tagsList[i]) o.tags = splitTags(tagsList[i]);
            if (dueDates[i]) o.deadline = fmtDate(dueDates[i]);
            if (compDates[i]) o.stop_date = fmtDate(compDates[i]);
            if (creDates[i]) o.creation_date = fmtDateTime(creDates[i]);
            result.push(o);
        }}
    }}
    result.sort(function(a, b) {{
        return (b.stop_date || "").localeCompare(a.stop_date || "");
    }});
    return JSON.stringify(result);
    '''), timeout=60)
    return result if isinstance(result, list) else []
