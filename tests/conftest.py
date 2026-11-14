#!/usr/bin/env python3
"""Shared test fixtures and utilities for Things MCP tests."""

import os
import random
import string
import sys
import warnings
from pathlib import Path
from urllib.parse import unquote, urlsplit

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from things3_mcp.applescript_bridge import (  # noqa: E402
    ensure_things_ready,
)
from things3_mcp.applescript_bridge import (
    run_applescript as _run_applescript,
)

# Install the guard before test collection, including import-time app discovery.
_live_cleanup_allowed = False


def pytest_addoption(parser):
    group = parser.getgroup("Things live tests")
    group.addoption("--live-things", action="store_true", help="Run tests against a disposable Things library")
    group.addoption("--allow-things-cleanup", action="store_true", help="Acknowledge creation and deletion of live test data")


def pytest_configure(config):
    global _live_cleanup_allowed
    live = config.getoption("--live-things")
    cleanup = config.getoption("--allow-things-cleanup")
    if live != cleanup:
        raise pytest.UsageError("Live Things tests require both --live-things and --allow-things-cleanup; use a disposable library.")
    _live_cleanup_allowed = live and cleanup


def pytest_sessionstart(session):
    if _live_cleanup_allowed:
        return

    temporary_root = session.config._tmp_path_factory.getbasetemp().resolve()
    environment = pytest.MonkeyPatch()
    session.config.add_cleanup(environment.undo)
    for name in tuple(os.environ):
        if name == "THINGSDB" or name.startswith("THINGS3_MCP_"):
            environment.delenv(name)
    isolated_home = temporary_root / "home"
    isolated_home.mkdir(exist_ok=True)
    environment.setenv("HOME", str(isolated_home))

    def fixture_path(value):
        if not isinstance(value, str | bytes | os.PathLike):
            return None
        path = os.fsdecode(value)
        if path.startswith("file:"):
            path = unquote(urlsplit(path).path)
        return Path(path).expanduser().resolve()

    def is_temporary(value):
        path = fixture_path(value)
        return path is not None and path.is_relative_to(temporary_root)

    def denied(operation):
        # pytest.fail is not an Exception: production fallback handlers cannot
        # swallow the guard and turn forbidden access into a passing test.
        pytest.fail(f"Hermetic test blocked {operation}; mock the boundary or use a temporary fixture.", pytrace=False)

    def audit(event, args):
        if event == "sqlite3.connect":
            database = os.fsdecode(args[0])
            if database != ":memory:" and not is_temporary(database):
                denied("database access outside pytest temporary files")
        elif event in {"open", "os.listdir", "os.scandir"} and args:
            path = fixture_path(args[0])
            if path is not None and not path.is_relative_to(temporary_root):
                if "/Library/Group Containers/" in str(path) or "/Library/Application Support/Things3-MCP" in str(path) or ".thingsdatabase" in str(path):
                    denied("personal Things data access")
        elif event in {"subprocess.Popen", "os.posix_spawn"}:
            executable, argv = args[:2]
            command = [os.fsdecode(executable), *(os.fsdecode(arg) for arg in argv)] if isinstance(argv, list | tuple) else [os.fsdecode(executable), os.fsdecode(argv)]
            blocked = {"osascript", "tccutil", "sqlite3", "things-cli", "thingscli", "Things3-MCP-bridge"}
            if any(
                Path(arg).name in blocked or any(module in arg for module in ("things3_mcp_bridge.db_reader", "things3_mcp_bridge.server", "clawbridge.examples.music", "clawbridge.examples.catalogue"))
                for arg in command
            ):
                denied("AppleScript, live worker, or permission command")
        elif event == "os.system":
            denied("shell command")
        elif event == "socket.connect" and isinstance(args[1], str | bytes):
            if not is_temporary(args[1]):
                denied("a socket outside pytest temporary files")

    # Audit hooks remain installed for the process lifetime. Disable this one
    # when pytest finishes, including pytest.main() users in other test suites.
    active = True

    def guard(event, args):
        if active:
            audit(event, args)

    def deactivate():
        nonlocal active
        active = False

    session.config.add_cleanup(deactivate)
    sys.addaudithook(guard)


@pytest.fixture(autouse=True)
def _no_background_snapshot_refresh(monkeypatch):
    """Keep bridge servers under test from renewing a cache snapshot unless a test opts in."""
    monkeypatch.setenv("THINGS3_MCP_BRIDGE_SNAPSHOT_REFRESH", "0")


@pytest.fixture(autouse=True)
def _bridge_only_where_marked(request, monkeypatch):
    """Keep a live test that is not marked ``things_bridge`` away from the bridge.

    Such a test runs with the Automation permission alone. The MCP tools go
    through the bridge, which is where database access lives, so a test that
    calls one has to say so with the marker.
    """
    if request.node.get_closest_marker("live_things") and not request.node.get_closest_marker("things_bridge"):
        from things3_mcp import fast_server

        def refuse():
            pytest.fail("This live test calls an MCP tool, which goes through the bridge; mark it things_bridge.", pytrace=False)

        monkeypatch.setattr(fast_server, "get_provider", refuse)


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live-things"):
        skip = pytest.mark.skip(reason="Live Things tests require --live-things --allow-things-cleanup and a disposable library")
        for item in items:
            if item.get_closest_marker("live_things"):
                item.add_marker(skip)


def _require_live_cleanup():
    if not _live_cleanup_allowed:
        pytest.fail("Things setup and cleanup require --live-things --allow-things-cleanup.", pytrace=False)


def run_applescript(script, *args, **kwargs):
    """Protect every shared live setup and cleanup helper, including direct calls."""
    _require_live_cleanup()
    return _run_applescript(script, *args, **kwargs)


# Test namespace for tags and areas - centralized here for all tests
TEST_NAMESPACE = "mcp-test"


def generate_random_string(length: int = 10) -> str:
    """Generate a random string for testing.

    Args:
        length: The length of the random string to generate.

    Returns:
        A random string containing letters and digits.
    """
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


@pytest.fixture()
def test_namespace():
    """Fixture to provide the test namespace to all tests."""
    return TEST_NAMESPACE


def create_test_tag(tag_name: str) -> bool:
    """Create a test tag with the MCP namespace."""
    full_tag_name = f"{TEST_NAMESPACE}-{tag_name}"
    script = f"""
    tell application "Things3"
        set newTag to make new tag with properties {{name:"{full_tag_name}"}}
        return id of newTag
    end tell
    """
    result = run_applescript(script)
    return result and "error" not in result.lower()


def delete_test_tags():
    """Delete all test tags with the MCP namespace."""
    return _sweep("tag")


def create_test_area(area_name: str) -> str:
    """Create a test area with the MCP namespace."""
    full_area_name = f"{TEST_NAMESPACE}-{area_name}"
    script = f"""
    tell application "Things3"
        set newArea to make new area with properties {{name:"{full_area_name}"}}
        return id of newArea
    end tell
    """
    result = run_applescript(script)
    if result and "error" not in result.lower():
        return result
    return None


def rename_test_area(area_id: str, new_name: str) -> bool:
    """Rename a test area."""
    script = f"""
    tell application "Things3"
        try
            set theArea to first area whose id is "{area_id}"
            set name of theArea to "{new_name}"
            return "success"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)
    return result and "error" not in result.lower()


def delete_todo_by_id(todo_id: str) -> bool:
    """Delete a specific todo by ID."""
    script = f"""
    tell application "Things3"
        try
            set theTodo to first to do whose id is "{todo_id}"
            delete theTodo
            return "success"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)
    return result and "error" not in result.lower()


def delete_project_by_id(project_id: str) -> bool:
    """Delete a specific project by ID."""
    script = f"""
    tell application "Things3"
        try
            set theProject to first project whose id is "{project_id}"
            delete theProject
            return "success"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)
    return result and "error" not in result.lower()


SWEEP_TIMEOUT_SECONDS = 120
# Areas and tags are only ever created as "mcp-test-<name>"; to-dos and projects also as "mcp-test <name>".
SWEEP_PREFIXES = {"to do": TEST_NAMESPACE, "project": TEST_NAMESPACE, "area": f"{TEST_NAMESPACE}-", "tag": f"{TEST_NAMESPACE}-"}


def live_test_items(kind: str) -> list[tuple[str, str]]:
    """Return ``(id, name)`` of every item of one kind left by a live test, ignoring the Trash.

    Things filters by name itself, so this is one round trip however large the
    library is, and items already in the Trash are not swept again.
    """
    prefix = SWEEP_PREFIXES[kind]
    script = f"""
    tell application "Things3"
        set trashedIds to {{}}
        try
            set trashedIds to id of (every to do of list "Trash" whose name starts with "{prefix}")
        end try
        set foundIds to id of (every {kind} whose name starts with "{prefix}")
        set foundNames to name of (every {kind} whose name starts with "{prefix}")
        set output to ""
        repeat with position from 1 to count of foundIds
            set itemId to (item position of foundIds) as text
            if trashedIds does not contain itemId then
                set output to output & itemId & tab & (item position of foundNames) & linefeed
            end if
        end repeat
        return output
    end tell
    """
    found = run_applescript(script, timeout=SWEEP_TIMEOUT_SECONDS)
    # AppleScript compares text without regard to case; only the exact lower-case prefix is ours.
    return [(item_id, name) for item_id, _, name in (line.partition("\t") for line in found.splitlines()) if item_id and name.startswith(prefix)]


def _sweep(kind: str) -> int:
    """Delete what live tests left behind of one kind and return how many items that was."""
    removed = 0
    for item_id, _name in live_test_items(kind):
        script = f"""
        tell application "Things3"
            delete (first {kind} whose id is "{item_id}")
        end tell
        """
        try:
            run_applescript(script, timeout=SWEEP_TIMEOUT_SECONDS)
            removed += 1
        except (RuntimeError, ValueError, OSError) as error:
            print(f"⚠️  Could not delete test {kind} {item_id}: {type(error).__name__}")
    return removed


def sweep_live_test_items() -> list[str]:
    """Remove everything live tests created, then return a description of anything still present.

    Each kind is swept on its own, so one failure cannot leave the others behind:
    to-dos first, then projects, then the areas and tags they used.
    """
    problems = []
    for kind in SWEEP_PREFIXES:
        try:
            _sweep(kind)
        except (RuntimeError, ValueError, OSError) as error:
            problems.append(f"sweep of {kind}s failed: {type(error).__name__}")
    for kind in SWEEP_PREFIXES:
        try:
            problems.extend(f"{kind} left behind: {name} (ID: {item_id})" for item_id, name in live_test_items(kind))
        except (RuntimeError, ValueError, OSError) as error:
            problems.append(f"could not check for leftover {kind}s: {type(error).__name__}")
    return problems


def verify_cleanup():
    """Verify that all test items have been cleaned up."""
    leftovers = []
    for kind in SWEEP_PREFIXES:
        leftovers.extend(f"{kind}: {name} (ID: {item_id})" for item_id, name in live_test_items(kind))
    if leftovers:
        print("⚠️  Cleanup verification failed:")
        print("\n".join(leftovers))
        return False
    print("✅ Verified: All test items cleaned up")
    return True


def delete_test_areas():
    """Delete all test areas with the MCP namespace."""
    return _sweep("area")


def delete_test_todos():
    """Delete all test todos with the MCP namespace."""
    return _sweep("to do")


def delete_test_projects():
    """Delete all test projects with the MCP namespace."""
    return _sweep("project")


class CleanupTracker:
    """Enhanced helper class to track and clean up test items, tags, and areas"""

    def __init__(self: "CleanupTracker") -> None:
        self.test_todos: list[str] = []
        self.test_projects: list[str] = []
        self.test_areas: list[str] = []
        self.test_tags_created: list[str] = []

    def add_todo(self: "CleanupTracker", todo_id: str) -> None:
        """Track a todo for cleanup"""
        if todo_id:
            self.test_todos.append(todo_id)

    def add_project(self: "CleanupTracker", project_id: str) -> None:
        """Track a project for cleanup"""
        if project_id:
            self.test_projects.append(project_id)

    def add_area(self: "CleanupTracker", area_id: str) -> None:
        """Track an area for cleanup"""
        if area_id:
            self.test_areas.append(area_id)

    def add_tag(self: "CleanupTracker", tag_name: str) -> None:
        """Track a tag for cleanup"""
        if tag_name:
            self.test_tags_created.append(tag_name)

    def cleanup(self: "CleanupTracker") -> None:
        """Clean up all test items, tags, and areas"""
        _require_live_cleanup()
        # Clean up todos first
        for todo_id in self.test_todos:
            try:
                delete_todo_by_id(todo_id)
            except (RuntimeError, ValueError, OSError) as e:
                print(f"Failed to clean up todo {todo_id}: {e}")

        # Then clean up projects
        for project_id in self.test_projects:
            try:
                delete_project_by_id(project_id)
            except (RuntimeError, ValueError, OSError) as e:
                print(f"Failed to clean up project {project_id}: {e}")

        # Anything a test created without tracking it is still found by name.
        self.problems = sweep_live_test_items()
        for problem in self.problems:
            print(f"⚠️  {problem}")


@pytest.fixture(scope="session", autouse=True)
def _setup_test_environment(request):
    """Set up test environment and clean up after all tests."""
    if not _live_cleanup_allowed or not any(item.get_closest_marker("live_things") for item in request.session.items):
        yield
        return

    _require_live_cleanup()

    # Ensure Things is ready
    assert ensure_things_ready(), "Things app is not ready for testing"

    # Start from a library with no test data in it.
    leftovers = sweep_live_test_items()
    assert not leftovers, f"Things still holds test data from an earlier run: {leftovers}"

    yield

    leftovers = sweep_live_test_items()
    if leftovers:
        # Shown in the summary even without -s, so leftovers in a real library are not missed.
        warnings.warn(pytest.PytestWarning("Live test data was left in Things:\n" + "\n".join(leftovers)), stacklevel=1)


@pytest.fixture()
def cleanup_tracker():
    """Fixture to provide cleanup tracking"""
    _require_live_cleanup()
    tracker = CleanupTracker()
    yield tracker
    tracker.cleanup()


def extract_tag_names(tags_data):
    """Helper function to extract tag names from Things API response"""
    tag_names = []
    for tag in tags_data:
        if isinstance(tag, dict):
            tag_names.append(tag.get("title", ""))
        else:
            tag_names.append(str(tag))
    return tag_names
