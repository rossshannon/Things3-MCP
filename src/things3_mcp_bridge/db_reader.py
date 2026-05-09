# ruff: noqa: E501
"""Killable live Things read worker.

The bridge parent process invokes this module in a child process with a hard
timeout. It first attempts the historical SQLite-backed ``things-py`` reader,
then falls back to Things' Apple Events scripting model when macOS blocks the
protected app-group container.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import subprocess  # nosec B404 - required for invoking the read worker and osascript
import sys
import tempfile
from pathlib import Path
from typing import Any

SNAPSHOT_ACTIONS = ("inbox", "today", "upcoming", "anytime", "someday", "todos", "projects", "areas", "tags")

DEFAULT_THINGS_BUNDLE_ID = "com.culturedcode.ThingsMac"
CULTURED_CODE_TEAM_ID = "JLMPQHK86H"
DEFAULT_THINGS_GROUP_CONTAINER = f"{CULTURED_CODE_TEAM_ID}.{DEFAULT_THINGS_BUNDLE_ID}"
DATA_FOLDER_ENV = "THINGS3_MCP_DATA_FOLDER"
THINGSCLI_ENV = "THINGS3_MCP_THINGSCLI"
THINGSCLI_DEFAULTS_TIMEOUT_SECONDS = float(os.environ.get("THINGS3_MCP_THINGSCLI_TIMEOUT", "3"))

DB_PATTERNS = (
    f"~/Library/Group Containers/{DEFAULT_THINGS_GROUP_CONTAINER}/ThingsData-*/Things Database.thingsdatabase/main.sqlite",
    f"~/Library/Group Containers/{DEFAULT_THINGS_GROUP_CONTAINER}/Things Database.thingsdatabase/main.sqlite",
)

JXA_TIMEOUT_SECONDS = float(os.environ.get("THINGS3_MCP_JXA_TIMEOUT", "8"))

# Compact one-line-JXA for simple list reads (fast list enumeration)
_JXA_SIMPLE = r"""
function run(argv) {
  const app = Application('Things3');
  function v(fn, fallback) { try { const r = fn(); return r===undefined ? fallback : (r instanceof Date&&isNaN(r.getTime())?fallback:r); } catch(e) { return fallback; } }
  function s(todo) { return { uuid: v(()=>todo.id(),null), title: v(()=>todo.name(),''), type:'to-do', status: String(v(()=>todo.status(),'open'))==='completed'?'completed':'incomplete', notes: v(()=>todo.notes(),'')||'', project: null, project_title: null, area: null, area_title: null, tags: null, tag_titles: [], tag_names: '' }; }
  const action = argv[0];
  if (action==='inbox') { const l=app.lists().find(x=>String(v(()=>x.name(),'')).toLowerCase()==='inbox'); return JSON.stringify(l?l.toDos().map(s):[]); }
  if (action==='today') { const l=app.lists().find(x=>String(v(()=>x.name(),'')).toLowerCase()==='today'); return JSON.stringify(l?l.toDos().map(s):[]); }
  if (action==='upcoming') { const l=app.lists().find(x=>String(v(()=>x.name(),'')).toLowerCase()==='upcoming'); return JSON.stringify(l?l.toDos().map(s):[]); }
  if (action==='anytime') { const l=app.lists().find(x=>String(v(()=>x.name(),'')).toLowerCase()==='anytime'); return JSON.stringify(l?l.toDos().map(s):[]); }
  if (action==='someday') { const l=app.lists().find(x=>String(v(()=>x.name(),'')).toLowerCase()==='someday'); return JSON.stringify(l?l.toDos().map(s):[]); }
  if (action==='areas') { return JSON.stringify(app.areas().map(a=>({uuid:v(()=>a.id(),null),title:v(()=>a.name(),'')}))); }
  if (action==='tags') { return JSON.stringify(app.tags().map(t=>({uuid:v(()=>t.id(),null),title:v(()=>t.name(),''),name:v(()=>t.name(),'')}))); }
  if (action==='projects') { return JSON.stringify(app.projects().map(p=>({uuid:v(()=>p.id(),null),title:v(()=>p.name(),''),type:'project'}))); }
  throw new Error('Unknown action: '+action);
}
"""

# Parallelised snapshot JXA split into two phases to avoid osascript hangs
_JXA_LISTS = r"""
function run(argv) {
  const app = Application('Things3');
  function v(fn, fallback) { try { const r = fn(); return r===undefined ? fallback : (r instanceof Date&&isNaN(r.getTime())?fallback:r); } catch(e) { return fallback; } }
  function s(todo) {
    return {
      uuid: v(()=>todo.id(),null),
      title: v(()=>todo.name(),''),
      type: 'to-do',
      status: String(v(()=>todo.status(),'open'))==='completed'?'completed':'incomplete',
      notes: v(()=>todo.notes(),'')||'',
      project: null,
      project_title: null,
      area: null,
      area_title: null,
      tags: null,
      tag_titles: [],
      tag_names: '',
    };
  }
  function todosForList(name) {
    const lower = name.toLowerCase();
    const list = app.lists().find(x=>String(v(()=>x.name(),'')).toLowerCase()===lower);
    return list ? list.toDos().map(s) : [];
  }
  const inbox = todosForList('Inbox');
  const today = todosForList('Today');
  const upcoming = todosForList('Upcoming');
  const anytime = todosForList('Anytime');
  const someday = todosForList('Someday');
  const seen = new Set(), todos = [];
  for (const listTodos of [inbox, today, upcoming, anytime, someday]) {
    for (const t of listTodos) {
      const uuid = t.uuid;
      if (uuid && !seen.has(uuid)) { seen.add(uuid); todos.push(t); }
    }
  }
  return JSON.stringify({
    inbox: inbox,
    today: today,
    upcoming: upcoming,
    anytime: anytime,
    someday: someday,
    todos: todos
  });
}
"""

_JXA_META = r"""
function run(argv) {
  const app = Application('Things3');
  function v(fn, fallback) { try { const r = fn(); return r===undefined ? fallback : (r instanceof Date&&isNaN(r.getTime())?fallback:r); } catch(e) { return fallback; } }
  function projectProps(p) { return { uuid: v(()=>p.id(),null), title: v(()=>p.name(),''), type: 'project' }; }
  function areaProps(a) { const tagNames=String(v(()=>a.tagNames(),'')||'').split(',').map(x=>x.trim()).filter(Boolean); return { uuid: v(()=>a.id(),null), title: v(()=>a.name(),''), type: 'area', tags: tagNames.length?1:null, tag_titles: tagNames, tag_names: tagNames.join(', ') }; }
  function tagProps(t) { return { uuid: v(()=>t.id(),null), title: v(()=>t.name(),''), name: v(()=>t.name(),''), keyboard_shortcut: v(()=>t.keyboardShortcut(),null) }; }
  return JSON.stringify({ projects: app.projects().map(projectProps), areas: app.areas().map(areaProps), tags: app.tags().map(tagProps) });
}
"""


def _can_open_sqlite(path: Path) -> bool:
    """Return whether ``path`` is a readable SQLite database.

    Keep this check inside the worker process. Spawning ``/usr/bin/sqlite3``
    makes the system SQLite binary the process touching the protected Things
    group container, which can bypass the bridge app's Full Disk Access grant.
    """
    try:
        uri = f"{path.expanduser().absolute().as_uri()}?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True, timeout=1) as connection:
            connection.execute("select 1").fetchone()
        return True
    except Exception:  # noqa: BLE001 - path probing should be best-effort
        return False


def _valid_sqlite_path(candidate: str | Path | None) -> str | None:
    """Normalise and validate a candidate Things SQLite path."""
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    return str(path) if _can_open_sqlite(path) else None


def _split_env_list(name: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    """Read a comma-separated env override while preserving safe defaults."""
    raw = os.environ.get(name)
    if not raw:
        return defaults
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    return values or defaults


def _things_bundle_ids() -> tuple[str, ...]:
    """Return Things bundle IDs to probe, overridable for beta/custom installs."""
    return _split_env_list("THINGS3_MCP_APP_BUNDLE_IDS", (DEFAULT_THINGS_BUNDLE_ID,))


def _things_group_containers() -> tuple[str, ...]:
    """Return Things group-container names to probe."""
    defaults = tuple(f"{CULTURED_CODE_TEAM_ID}.{bundle_id}" for bundle_id in _things_bundle_ids())
    return _split_env_list("THINGS3_MCP_GROUP_CONTAINERS", defaults)


def _db_patterns() -> tuple[str, ...]:
    """Return Things SQLite glob patterns for all configured group containers."""
    patterns: list[str] = []
    for container in _things_group_containers():
        base = f"~/Library/Group Containers/{container}"
        patterns.extend(
            (
                f"{base}/ThingsData-*/Things Database.thingsdatabase/main.sqlite",
                f"{base}/Things Database.thingsdatabase/main.sqlite",
            )
        )
    return tuple(patterns)


def _sqlite_path_for_data_folder(container: str, data_folder: str) -> Path:
    """Build the expected SQLite path for a known Things data folder."""
    return Path.home() / "Library/Group Containers" / container / data_folder / "Things Database.thingsdatabase/main.sqlite"


def _validated_path_for_data_folder(data_folder: str) -> str | None:
    """Validate a ThingsData-* folder name against configured group containers."""
    folder = data_folder.strip().strip('"').strip("'")
    if not folder:
        return None
    for container in _things_group_containers():
        validated = _valid_sqlite_path(_sqlite_path_for_data_folder(container, folder))
        if validated:
            return validated
    return None


def _candidate_thingscli_paths() -> tuple[Path, ...]:
    """Return likely paths for Things' bundled ``thingscli`` helper."""
    configured = os.environ.get(THINGSCLI_ENV)
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            Path("/Applications/Things3.app/Contents/MacOS/thingscli"),
            Path.home() / "Applications/Things3.app/Contents/MacOS/thingscli",
        ]
    )
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return tuple(unique)


def _data_folder_from_thingscli_defaults() -> str | None:
    """Read Things' current ``ThingsData-*`` folder from its bundled CLI."""
    for thingscli in _candidate_thingscli_paths():
        if not thingscli.exists():
            continue
        try:
            completed = subprocess.run(  # noqa: S603 # nosec B603 - fixed argv, no shell
                [str(thingscli), "defaults"],
                capture_output=True,
                text=True,
                timeout=THINGSCLI_DEFAULTS_TIMEOUT_SECONDS,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001 - resolver fallback should stay best-effort
            print(f"thingscli defaults failed for {thingscli}: {exc}", file=sys.stderr)
            continue
        if completed.returncode != 0:
            continue
        for line in completed.stdout.splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "THCDataFolderCurrentDataFolderPath":
                folder = value.strip().strip(";").strip()
                if folder.startswith("ThingsData-"):
                    return folder
    return None


def _enumerate_db_patterns() -> list[str]:
    """Glob the protected Things group container for SQLite candidates.

    Only safe to call from inside the bridge worker, which holds Full Disk Access.
    ``ThingsData-*`` folder names are random alphanumeric hashes — lexicographic
    sort doesn't reflect recency. Sort by the SQLite file's mtime so a fresh
    data folder takes precedence over a stale sibling left behind by an old
    install or sync.
    """
    matches: list[str] = []
    for pattern in _db_patterns():
        expanded = os.path.expanduser(pattern)
        for candidate in glob.glob(expanded):
            validated = _valid_sqlite_path(candidate)
            if validated and validated not in matches:
                matches.append(validated)
    return sorted(matches, key=lambda p: os.path.getmtime(p))


def resolve_things_db_path() -> str:
    """Resolve the current Things SQLite path.

    Env-var hints (``THINGSDB``, ``THINGS3_MCP_DATA_FOLDER``) are honored first
    so tests and non-default Things data layouts can override discovery. When
    both are unset/empty, fall back to globbing the protected group container —
    this is the bridge worker's job and the reason it holds Full Disk Access.
    """
    configured = os.environ.get("THINGSDB")
    if configured:
        validated = _valid_sqlite_path(configured)
        if validated:
            return validated
        raise FileNotFoundError(f"Configured THINGSDB is not a readable SQLite database: {configured}")

    configured_folder = os.environ.get(DATA_FOLDER_ENV)
    if configured_folder:
        validated = _validated_path_for_data_folder(configured_folder)
        if validated:
            return validated
        raise FileNotFoundError(f"Configured {DATA_FOLDER_ENV} did not resolve to a readable Things SQLite database")

    thingscli_folder = _data_folder_from_thingscli_defaults()
    if thingscli_folder:
        validated = _validated_path_for_data_folder(thingscli_folder)
        if validated:
            return validated

    matches = _enumerate_db_patterns()
    if matches:
        return matches[-1]

    raise FileNotFoundError(
        "Could not find a readable Things SQLite database in the expected group container. Ensure Things 3 has been launched at least once and that the bridge bundle has Full Disk Access in System Settings."
    )


def _fda_probe() -> dict[str, Any]:
    """Attempt to list a few FDA-gated directories.

    This lets us tell whether the running process actually has Full Disk Access
    attributed to it.
    Each probe is run in its own thread with a 2-second hard cap so we can
    distinguish "fast deny" (errno=1 EPERM) from "tccd queued the syscall"
    (timeout — the bundle has a UI grant but tccd isn't matching it).
    """
    import threading

    def listdir_with_timeout(path: str) -> dict[str, Any]:
        result: dict[str, Any] = {"path": path}

        def _runner() -> None:
            try:
                entries = sorted(os.listdir(path))
                result["ok"] = True
                result["count"] = len(entries)
                result["first"] = entries[:3]
            except OSError as exc:
                result["ok"] = False
                result["errno"] = exc.errno
                result["error"] = str(exc)

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join(timeout=2.0)
        if thread.is_alive():
            result["ok"] = False
            result["error"] = "syscall did not return within 2s (likely tccd-queued without prompt)"
            result["timed_out"] = True
        return result

    return {
        label: listdir_with_timeout(path)
        for label, path in (
            ("home_library_mail", os.path.expanduser("~/Library/Mail")),
            ("home_library_messages", os.path.expanduser("~/Library/Messages")),
            ("home_group_containers", os.path.expanduser("~/Library/Group Containers")),
            ("things_group_container", os.path.expanduser(f"~/Library/Group Containers/{DEFAULT_THINGS_GROUP_CONTAINER}")),
        )
    }


def things_process_running() -> bool:
    """Return whether Things.app is currently running.

    The bridge can be healthy and the SQLite read path can work even when
    Things.app is closed. Writes still need Things.app to be running because
    they go through AppleScript, so expose this process check in diagnostics.
    """
    try:
        completed = subprocess.run(  # noqa: S603 # nosec B603 - fixed executable and script
            [
                "/usr/bin/osascript",
                "-e",
                'tell application "System Events" to exists process "Things3"',
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:  # noqa: BLE001 - diagnostics must not fail the whole diagnose path
        return False
    return completed.returncode == 0 and completed.stdout.strip().lower() == "true"


def diagnose_access() -> dict[str, Any]:
    """Return local DB-path diagnostics from the bridge identity.

    Runs inside the worker, so it can glob the protected group container.
    """
    patterns: list[dict[str, Any]] = []
    things_running = things_process_running()
    for pattern in _db_patterns():
        expanded = os.path.expanduser(pattern)
        try:
            matches = glob.glob(expanded)
        except OSError as exc:
            patterns.append({"pattern": expanded, "matches": None, "error": str(exc)})
            continue
        patterns.append({"pattern": expanded, "matches": sorted(matches)})
    fda_probe = _fda_probe()
    try:
        path = resolve_things_db_path()
        exists = Path(path).exists()
        readable = os.access(path, os.R_OK)
        sqlite_ok = False
        sqlite_error = None
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                connection.execute("select 1").fetchone()
                sqlite_ok = True
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            sqlite_error = str(exc)
        return {
            "ok": True,
            "path": path,
            "exists": exists,
            "readable": readable,
            "sqlite_ok": sqlite_ok,
            "sqlite_error": sqlite_error,
            "things_process_running": things_running,
            "patterns": patterns,
            "fda_probe": fda_probe,
            "data_folder_env": os.environ.get(DATA_FOLDER_ENV),
            "thingsdb_env": os.environ.get("THINGSDB"),
        }
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        return {
            "ok": False,
            "error": str(exc),
            "things_process_running": things_running,
            "patterns": patterns,
            "fda_probe": fda_probe,
            "data_folder_env": os.environ.get(DATA_FOLDER_ENV),
            "thingsdb_env": os.environ.get("THINGSDB"),
        }


def direct_provider() -> Any:
    """Load the direct provider only after pinning THINGSDB to the resolved path."""
    os.environ["THINGSDB"] = resolve_things_db_path()
    from things3_mcp.providers.direct import DirectThingsProvider

    return DirectThingsProvider()


def _run_jxa_script(script_content: str, action: str, params: dict[str, Any] | None = None) -> str:
    """Execute JXA from a temp file and return stdout."""
    params = params or {}
    with tempfile.NamedTemporaryFile(suffix=".jxa", mode="w", delete=False) as f:
        f.write(script_content)
        script_path = f.name
    try:
        completed = subprocess.run(  # noqa: S603 # nosec B603 - fixed executable, no shell
            ["/usr/bin/osascript", "-l", "JavaScript", script_path, action, json.dumps(params)],
            capture_output=True,
            text=True,
            timeout=JXA_TIMEOUT_SECONDS,
            check=False,
        )
        if completed.returncode != 0:
            msg = completed.stderr.strip() or completed.stdout.strip() or f"osascript rc={completed.returncode}"
            raise RuntimeError(msg)
        return completed.stdout.strip()
    finally:
        os.unlink(script_path)


def run_jxa_action(action: str, params: dict[str, Any] | None = None) -> Any:
    """Read Things through its Apple Events scripting interface."""
    params = params or {}
    if action == "snapshot":
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            lists_future = executor.submit(_run_jxa_script, _JXA_LISTS, "_snapshot_lists", {})
            meta_future = executor.submit(_run_jxa_script, _JXA_META, "_snapshot_meta", {})
            lists_raw = lists_future.result(timeout=JXA_TIMEOUT_SECONDS)
            meta_raw = meta_future.result(timeout=JXA_TIMEOUT_SECONDS)

        lists_data: dict[str, Any] = json.loads(lists_raw)
        meta_data: dict[str, Any] = json.loads(meta_raw)
        inbox = lists_data.get("inbox", [])
        today = lists_data.get("today", [])
        upcoming = lists_data.get("upcoming", [])
        anytime = lists_data.get("anytime", [])
        someday = lists_data.get("someday", [])
        todos = lists_data.get("todos")
        if not isinstance(todos, list):
            todos = []
            seen: set[str] = set()
            for item in [*inbox, *today, *upcoming, *anytime, *someday]:
                uuid = item.get("uuid") if isinstance(item, dict) else None
                if uuid and uuid not in seen:
                    seen.add(uuid)
                    todos.append(item)
        return {
            "inbox": inbox,
            "today": today,
            "upcoming": upcoming,
            "anytime": anytime,
            "someday": someday,
            "todos": todos,
            "projects": meta_data.get("projects", []),
            "areas": meta_data.get("areas", []),
            "tags": meta_data.get("tags", []),
        }

    output = _run_jxa_script(_JXA_SIMPLE, action, params)
    return json.loads(output)


def run_sqlite_action(action: str, params: dict[str, Any] | None = None) -> Any:
    """Run a read action against the direct Things SQLite provider."""
    params = params or {}
    provider = direct_provider()
    if action == "snapshot":
        return {
            "inbox": provider.inbox(include_items=True),
            "today": provider.today(include_items=True),
            "upcoming": provider.upcoming(include_items=True),
            "anytime": provider.anytime(include_items=True),
            "someday": provider.someday(include_items=True),
            "todos": provider.todos(include_items=True),
            "projects": provider.projects(include_items=False),
            "areas": provider.areas(include_items=False),
            "tags": provider.tags(include_items=False),
        }
    if action == "search":
        return provider.search(params.get("query", ""), include_items=bool(params.get("include_items", True)))
    if action == "get":
        return provider.get(params["uuid"])
    if action in {"tasks", "todos"}:
        return getattr(provider, action)(**params)
    if action == "trash":
        return provider.trash(include_items=bool(params.get("include_items", True)))
    if action == "last":
        period = params.get("period")
        if not period:
            raise ValueError("'last' action requires a 'period' parameter (e.g. '7d', '1w')")
        return provider.last(period, include_items=bool(params.get("include_items", True)))
    if action in SNAPSHOT_ACTIONS:
        include_items = bool(params.pop("include_items", True))
        return getattr(provider, action)(include_items=include_items, **params)
    raise ValueError(f"Unsupported Things bridge action: {action}")


def _trace(stage: str, detail: str = "") -> None:
    """Emit a worker-progress marker on stderr so the parent bridge log can show stages."""
    suffix = f" {detail}" if detail else ""
    print(f"[worker:{os.getpid()}] {stage}{suffix}", file=sys.stderr, flush=True)


WRITE_ACTIONS = {"add_task", "update_task", "add_project", "update_project"}

# Marker prefixes that applescript_bridge functions return when an operation
# fails. Match the pattern used by the existing MCP server in fast_server.py.
_ERROR_MARKERS = ("error:", "applescript error", "⚠️", "failed", "exception")


def _coerce_write_result(result: Any, op_desc: str) -> dict[str, Any]:
    """Normalize an applescript_bridge return value into a worker envelope.

    The legacy AppleScript helpers return either:
      - ``True``/``"true"`` for success without a UUID (e.g. updates)
      - a UUID string (e.g. add_todo)
      - ``False`` or an "Error: …" string on failure

    We surface the UUID when present so the bridge HTTP response can include it,
    and raise :class:`RuntimeError` for failures so the parent worker emits a
    clean error envelope.
    """
    if isinstance(result, bool):
        if result:
            return {"ok": True}
        raise RuntimeError(f"AppleScript reported failure on {op_desc}")
    if isinstance(result, str):
        stripped = result.strip()
        lowered = stripped.lower()
        if lowered == "true":
            return {"ok": True}
        if any(marker in lowered for marker in _ERROR_MARKERS):
            raise RuntimeError(f"AppleScript error on {op_desc}: {stripped}")
        # Looks like a UUID or other success identifier.
        return {"ok": True, "id": stripped}
    raise RuntimeError(f"Unexpected AppleScript result type on {op_desc}: {type(result).__name__}")


def run_write_action(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a write action to applescript_bridge from inside the worker.

    Importing applescript_bridge lazily keeps the read path free of its
    transitive dependencies (date_converter, etc.) and lets unit tests mock it
    cleanly without import-time side effects.
    """
    from things3_mcp import applescript_bridge as ab

    if action == "add_task":
        return _coerce_write_result(ab.add_todo(**params), "create todo")
    if action == "update_task":
        uuid = params.pop("uuid", None)
        if not uuid:
            raise ValueError("update_task requires 'uuid' in params")
        return _coerce_write_result(ab.update_todo(id=uuid, **params), f"update todo {uuid}")
    if action == "add_project":
        return _coerce_write_result(ab.add_project(**params), "create project")
    if action == "update_project":
        uuid = params.pop("uuid", None)
        if not uuid:
            raise ValueError("update_project requires 'uuid' in params")
        return _coerce_write_result(ab.update_project(id=uuid, **params), f"update project {uuid}")
    raise ValueError(f"Unsupported write action: {action}")


def run_action(action: str, params: dict[str, Any] | None = None) -> Any:
    """Run a read or write action against Things.

    Reads prefer SQLite and fall back to Apple Events. Writes go straight to
    AppleScript — there is no SQLite write path (the DB is opened read-only by
    design) and Things has no other public mutation API beyond AppleScript /
    URL scheme.
    """
    params = params or {}
    if action == "diagnose":
        return diagnose_access()
    if action in WRITE_ACTIONS:
        _trace("write-attempt", action)
        try:
            result = run_write_action(action, params)
            _trace("write-ok", action)
            return result
        except Exception as exc:
            _trace("write-failed", repr(exc)[:200])
            raise
    _trace("sqlite-attempt", action)
    try:
        result = run_sqlite_action(action, params)
        _trace("sqlite-ok", action)
        return result
    except Exception as sqlite_exc:  # noqa: BLE001 - fallback path preserves both failures in diagnostics
        _trace("sqlite-failed", repr(sqlite_exc)[:200])
        _trace("jxa-attempt", action)
        try:
            data = run_jxa_action(action, params)
            _trace("jxa-ok", action)
        except Exception as jxa_exc:  # noqa: BLE001
            _trace("jxa-failed", repr(jxa_exc)[:200])
            raise RuntimeError(f"SQLite read failed ({sqlite_exc}); Apple Events read failed ({jxa_exc})") from jxa_exc
        if isinstance(data, dict):
            data.setdefault("_source", "apple_events")
        return data


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for child worker reads."""
    parser = argparse.ArgumentParser(description="Things3 MCP bridge read worker")
    parser.add_argument("action")
    parser.add_argument("--params", default="{}")
    args = parser.parse_args(argv)

    try:
        params = json.loads(args.params)
        result = run_action(args.action, params)
        print(json.dumps({"ok": True, "data": result}))
        return 0
    except Exception as exc:  # noqa: BLE001 - serialize worker failures to parent
        print(json.dumps({"ok": False, "error_code": "things_read_unavailable", "message": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
