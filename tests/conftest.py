#!/usr/bin/env python3
"""Shared test fixtures and utilities for Things MCP tests."""

import os
import random
import string
import sys
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
            if any(Path(arg).name in blocked or any(module in arg for module in ("things3_mcp_bridge.db_reader", "things3_mcp_bridge.server")) for arg in command):
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
    script = f"""
    tell application "Things3"
        try
            set tagList to {{}}
            repeat with theTag in tags
                if name of theTag starts with "{TEST_NAMESPACE}-" then
                    set end of tagList to id of theTag
                end if
            end repeat

            repeat with tagId in tagList
                try
                    set theTag to first tag whose id is tagId
                    delete theTag
                on error
                    -- Tag might already be deleted, continue
                end try
            end repeat

            return "success"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)
    if result and "error" not in result.lower():
        print("✅ Successfully cleaned up test tags")
    else:
        print(f"⚠️  Tag cleanup result: {result}")


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


def verify_cleanup():
    """Verify that all test items have been cleaned up."""
    script = f"""
    tell application "Things3"
        try
            set foundItems to {{}}

            -- Check all todos
            set allTodos to to dos
            repeat with theTodo in allTodos
                try
                    if title of theTodo starts with "{TEST_NAMESPACE}" then
                        set end of foundItems to "Todo: " & title of theTodo & " (ID: " & id of theTodo & ")"
                    end if
                end try
            end repeat

            -- Check all projects
            set allProjects to projects
            repeat with theProject in allProjects
                try
                    if title of theProject starts with "{TEST_NAMESPACE}" then
                        set end of foundItems to "Project: " & title of theProject & " (ID: " & id of theProject & ")"
                    end if
                end try
            end repeat

            -- Check all areas
            set allAreas to areas
            repeat with theArea in allAreas
                try
                    if name of theArea starts with "{TEST_NAMESPACE}-" then
                        set end of foundItems to "Area: " & name of theArea & " (ID: " & id of theArea & ")"
                    end if
                end try
            end repeat

            -- Check all tags
            set allTags to tags
            repeat with theTag in allTags
                try
                    if name of theTag starts with "{TEST_NAMESPACE}-" then
                        set end of foundItems to "Tag: " & name of theTag & " (ID: " & id of theTag & ")"
                    end if
                end try
            end repeat

            if (count of foundItems) > 0 then
                set itemList to ""
                repeat with item in foundItems
                    set itemList to itemList & item & linefeed
                end repeat
                return "Found test items:" & linefeed & itemList
            else
                return "success"
            end if
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)
    if result != "success":
        print("⚠️  Cleanup verification failed:")
        print(result)
        return False
    print("✅ Verified: All test items cleaned up")
    return True


def delete_test_areas():
    """Delete all test areas with the MCP namespace."""
    script = f"""
    tell application "Things3"
        try
            set areaList to {{}}
            repeat with theArea in areas
                if name of theArea starts with "{TEST_NAMESPACE}-" then
                    set end of areaList to id of theArea
                end if
            end repeat

            repeat with areaId in areaList
                try
                    set theArea to first area whose id is areaId
                    delete theArea
                on error
                    -- Area might already be deleted, continue
                end try
            end repeat

            return "success"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)
    if result and "error" not in result.lower():
        print("✅ Successfully cleaned up test areas")
    else:
        print(f"⚠️  Area cleanup result: {result}")


def delete_test_todos():
    """Delete all test todos with the MCP namespace from all lists."""
    # First try the AppleScript approach
    script = f"""
    tell application "Things3"
        try
            set todoList to {{}}

            -- Get all todos from everywhere
            set allTodos to every to do
            repeat with theTodo in allTodos
                try
                    if title of theTodo starts with "{TEST_NAMESPACE}" then
                        set end of todoList to id of theTodo
                        log "Found test todo: " & title of theTodo
                    end if
                on error errMsg
                    log "Error checking todo: " & errMsg
                end try
            end repeat

            -- Also check todos in projects
            set allProjects to every project
            repeat with theProject in allProjects
                try
                    set projectTodos to to dos of theProject
                    repeat with theTodo in projectTodos
                        try
                            if title of theTodo starts with "{TEST_NAMESPACE}" then
                                set end of todoList to id of theTodo
                                log "Found test todo in project: " & title of theTodo
                            end if
                        on error errMsg
                            log "Error checking project todo: " & errMsg
                        end try
                    end repeat
                on error errMsg
                    log "Error accessing project: " & errMsg
                end try
            end repeat

            -- And check todos in areas
            set allAreas to every area
            repeat with theArea in allAreas
                try
                    set areaTodos to to dos of theArea
                    repeat with theTodo in areaTodos
                        try
                            if title of theTodo starts with "{TEST_NAMESPACE}" then
                                set end of todoList to id of theTodo
                                log "Found test todo in area: " & title of theTodo
                            end if
                        on error errMsg
                            log "Error checking area todo: " & errMsg
                        end try
                    end repeat
                on error errMsg
                    log "Error accessing area: " & errMsg
                end try
            end repeat

            -- Delete collected todos
            repeat with todoId in todoList
                try
                    set theTodo to first to do whose id is todoId
                    log "Deleting todo: " & title of theTodo
                    -- Check if todo is completed
                    if status of theTodo is "completed" then
                        -- For completed todos, we need to uncomplete them first
                        set status of theTodo to "open"
                    end if
                    delete theTodo
                on error errMsg
                    log "Error deleting todo: " & errMsg
                end try
            end repeat

            return "Successfully cleaned up " & (count of todoList) & " test todos"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)

    # If AppleScript cleanup didn't work, try Python-based cleanup as fallback
    if not result or "error" in result.lower() or "0" in result:
        try:
            import things

            all_todos = things.todos()
            test_todos = [t for t in all_todos if t.get("title", "").startswith(TEST_NAMESPACE)]

            if test_todos:
                print(f"⚠️  AppleScript cleanup found 0 todos, but Python found {len(test_todos)}. Using Python cleanup...")
                for todo in test_todos:
                    try:
                        delete_todo_by_id(todo["uuid"])
                    except Exception as e:
                        print(f"⚠️  Failed to delete todo {todo.get('title', 'unknown')}: {e}")
                print(f"✅ Python cleanup completed for {len(test_todos)} todos")
            else:
                print("✅ No test todos found via Python")
        except Exception as e:
            print(f"⚠️  Python cleanup failed: {e}")
    else:
        print("✅ Successfully cleaned up test todos via AppleScript")


def delete_test_projects():
    """Delete all test projects with the MCP namespace."""
    # First try the AppleScript approach
    script = f"""
    tell application "Things3"
        try
            set projectList to {{}}

            -- Get all projects from everywhere
            set allProjects to every project
            repeat with theProject in allProjects
                try
                    if title of theProject starts with "{TEST_NAMESPACE}" then
                        set end of projectList to id of theProject
                        log "Found test project: " & title of theProject
                    end if
                on error errMsg
                    log "Error checking project: " & errMsg
                end try
            end repeat

            -- Delete collected projects
            repeat with projectId in projectList
                try
                    set theProject to first project whose id is projectId
                    log "Deleting project: " & title of theProject
                    -- Check if project is completed
                    if status of theProject is "completed" then
                        -- For completed projects, we need to uncomplete them first
                        set status of theProject to "open"
                    end if
                    delete theProject
                on error errMsg
                    log "Error deleting project: " & errMsg
                end try
            end repeat

            return "Successfully cleaned up " & (count of projectList) & " test projects"
        on error errMsg
            return "Error: " & errMsg
        end try
    end tell
    """
    result = run_applescript(script)

    # If AppleScript cleanup didn't work, try Python-based cleanup as fallback
    if not result or "error" in result.lower() or "0" in result:
        try:
            import things

            all_projects = things.projects()
            test_projects = [p for p in all_projects if p.get("title", "").startswith(TEST_NAMESPACE)]

            if test_projects:
                print(f"⚠️  AppleScript cleanup found 0 projects, but Python found {len(test_projects)}. Using Python cleanup...")
                for project in test_projects:
                    try:
                        delete_project_by_id(project["uuid"])
                    except Exception as e:
                        print(f"⚠️  Failed to delete project {project.get('title', 'unknown')}: {e}")
                print(f"✅ Python cleanup completed for {len(test_projects)} projects")
            else:
                print("✅ No test projects found via Python")
        except Exception as e:
            print(f"⚠️  Python cleanup failed: {e}")
    else:
        print("✅ Successfully cleaned up test projects via AppleScript")


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

        # Clean up all test tags and areas (these are cleaned up globally)
        delete_test_todos()  # Catch any remaining todos
        delete_test_projects()  # Catch any remaining projects
        delete_test_areas()  # Clean up areas after todos/projects
        delete_test_tags()  # Clean up tags last
        verify_cleanup()  # Verify everything was cleaned up


@pytest.fixture(scope="session", autouse=True)
def _setup_test_environment(request):
    """Set up test environment and clean up after all tests."""
    if not _live_cleanup_allowed or not any(item.get_closest_marker("live_things") for item in request.session.items):
        yield
        return

    _require_live_cleanup()

    # Ensure Things is ready
    assert ensure_things_ready(), "Things app is not ready for testing"

    # Clean up any existing test data before starting
    delete_test_todos()  # Clean up todos first
    delete_test_projects()  # Then projects
    delete_test_areas()  # Then areas
    delete_test_tags()  # Then tags
    verify_cleanup()  # Verify initial cleanup

    yield

    # Clean up all test data after all tests complete
    delete_test_todos()  # Clean up todos first
    delete_test_projects()  # Then projects
    delete_test_areas()  # Then areas
    delete_test_tags()  # Then tags
    verify_cleanup()  # Verify final cleanup


@pytest.fixture()
def cleanup_tracker():
    """Fixture to provide cleanup tracking"""
    _require_live_cleanup()
    tracker = CleanupTracker()
    yield tracker
    tracker.cleanup()
    verify_cleanup()  # Verify cleanup after each test


def extract_tag_names(tags_data):
    """Helper function to extract tag names from Things API response"""
    tag_names = []
    for tag in tags_data:
        if isinstance(tag, dict):
            tag_names.append(tag.get("title", ""))
        else:
            tag_names.append(str(tag))
    return tag_names
