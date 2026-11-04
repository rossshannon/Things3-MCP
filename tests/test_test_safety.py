"""Exercise pytest safety in disposable projects with a synthetic app boundary."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def isolated_suite(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    calls = project / "app-calls.txt"
    stub = f"""
import pathlib
import sys
import types

_calls = pathlib.Path({str(calls)!r})
def _record_call(*args, **kwargs):
    with _calls.open("a") as handle:
        handle.write("app call\\n")
    return "success"

_app = types.ModuleType("things3_mcp.applescript_bridge")
_app.ensure_things_ready = _record_call
_app.run_applescript = _record_call
sys.modules["things3_mcp.applescript_bridge"] = _app
"""
    source = Path(__file__).with_name("conftest.py").read_text()
    (project / "conftest.py").write_text(stub + source)
    (project / "pytest.ini").write_text("[pytest]\nmarkers =\n    live_things: uses a disposable Things library\n")

    def run(source, *args, env=None):
        (project / "test_probe.py").write_text(source)
        child_env = os.environ.copy()
        child_env.pop("THINGS3_MCP_SKIP_THINGS_TEST_SETUP", None)
        child_env.pop("PYTEST_ADDOPTS", None)
        if env:
            child_env.update(env)
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--basetemp", str(project / "pytest-tmp"), "test_probe.py", *args],
            cwd=project,
            env=child_env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    return project, calls, run


def test_default_run_does_not_set_up_or_clean_up_things(isolated_suite):
    _, calls, run = isolated_suite
    result = run("def test_mocked():\n    assert 1 + 1 == 2\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert not calls.exists(), "Default pytest invoked the synthetic app setup or cleanup"


def test_live_tests_skip_before_their_fixtures(isolated_suite):
    _, calls, run = isolated_suite
    result = run("""
import pytest
pytestmark = pytest.mark.live_things
@pytest.fixture(autouse=True)
def live_fixture():
    pytest.fail("live fixture was executed")
def test_live():
    pytest.fail("live test was executed")
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 skipped" in result.stdout
    assert not calls.exists()


@pytest.mark.parametrize("option", ["--live-things", "--allow-things-cleanup"])
def test_live_access_requires_both_acknowledgements(isolated_suite, option):
    _, calls, run = isolated_suite
    result = run("def test_nothing(): pass\n", option)
    assert result.returncode == 4
    assert "require both --live-things and --allow-things-cleanup" in result.stderr
    assert not calls.exists()


def test_explicit_live_run_can_set_up_and_clean_up_the_synthetic_app(isolated_suite):
    _, calls, run = isolated_suite
    result = run(
        f"""
import pathlib
import pytest
@pytest.mark.live_things
def test_live(cleanup_tracker):
    with pathlib.Path({str(calls)!r}).open("a") as handle:
        handle.write("test body\\n")
    cleanup_tracker.add_todo("synthetic-id")
""",
        "--live-things",
        "--allow-things-cleanup",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    before, after = calls.read_text().split("test body")
    assert "app call" in before
    assert "app call" in after


def test_cleanup_fixture_cannot_mutate_the_default_library(isolated_suite):
    _, calls, run = isolated_suite
    result = run("def test_accidental_cleanup(cleanup_tracker): pass\n")
    assert result.returncode == 1
    assert "Things setup and cleanup require" in result.stdout
    assert not calls.exists()


def test_direct_cleanup_helpers_require_live_authorisation(isolated_suite):
    _, calls, run = isolated_suite
    result = run("""
import pytest
from conftest import CleanupTracker, delete_test_tags

def test_cleanup_helpers():
    for cleanup in (CleanupTracker().cleanup, delete_test_tags):
        with pytest.raises(pytest.fail.Exception, match="Things setup and cleanup require"):
            cleanup()
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not calls.exists()


@pytest.mark.parametrize("executable", ["osascript", "tccutil", "things-cli", "Things3-MCP-bridge"])
def test_app_and_permission_commands_fail_before_execution(isolated_suite, executable):
    project, calls, run = isolated_suite
    command = project / executable
    sentinel = project / "launched"
    # This is a harmless stand-in even if the guard regresses.
    command.write_text(f"#!/bin/sh\nprintf launched > '{sentinel}'\n")
    command.chmod(0o700)
    result = run(f"""
import subprocess

def test_accidental_command():
    subprocess.run([{str(command)!r}], check=True)
""")
    assert result.returncode == 1
    assert "Hermetic test blocked" in result.stdout
    assert not sentinel.exists()
    assert not calls.exists()


@pytest.mark.parametrize("module, arguments", [("db_reader", []), ("server", ["--worker-action", "add_task"])])
def test_live_worker_launch_fails_before_execution(isolated_suite, module, arguments):
    project, _, run = isolated_suite
    package = project / "things3_mcp_bridge"
    package.mkdir()
    (package / "__init__.py").write_text("")
    sentinel = project / "worker-launched"
    (package / f"{module}.py").write_text(f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n")
    result = run(f"""
import subprocess
import sys

def test_accidental_worker():
    subprocess.run([sys.executable, "-m", "things3_mcp_bridge.{module}", *{arguments!r}], check=True)
""")
    assert result.returncode == 1
    assert "Hermetic test blocked" in result.stdout
    assert not sentinel.exists()


@pytest.mark.parametrize("uri", [False, True])
def test_database_outside_pytest_temporary_files_is_blocked(isolated_suite, uri):
    project, _, run = isolated_suite
    database = project / "untouched.sqlite"
    location = database.as_uri() if uri else str(database)
    result = run(f"""
import sqlite3

def test_accidental_database():
    sqlite3.connect({location!r}, uri={uri!r})
""")
    assert result.returncode == 1
    assert "Hermetic test blocked database access" in result.stdout
    assert not database.exists()


def test_synthetic_sqlite_fixtures_remain_available(isolated_suite):
    _, _, run = isolated_suite
    result = run("""
import sqlite3

def test_fixture_database(tmp_path):
    for database in (":memory:", (tmp_path / "fixture.sqlite").as_uri()):
        with sqlite3.connect(database, uri=True) as connection:
            assert connection.execute("select 42").fetchone() == (42,)
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_personal_data_paths_and_symlinks_are_blocked(isolated_suite):
    project, _, run = isolated_suite
    library = project / "Library" / "Group Containers" / "synthetic.things"
    library.mkdir(parents=True)
    database = library / "main.sqlite"
    database.write_text("synthetic private content")
    result = run(f"""
from pathlib import Path
import pytest

def test_accidental_read(tmp_path):
    private = Path({str(database)!r})
    link = tmp_path / "looks-safe.sqlite"
    link.symlink_to(private)
    for path in (private, link):
        with pytest.raises(pytest.fail.Exception, match="personal Things data access"):
            path.read_text()
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_inherited_app_configuration_is_isolated_before_collection(isolated_suite):
    project, _, run = isolated_suite
    result = run(
        """
import os
from pathlib import Path

assert "THINGSDB" not in os.environ
assert "THINGS3_MCP_BRIDGE_URL" not in os.environ
assert "THINGS3_MCP_CACHE_FILE" not in os.environ

def test_home(tmp_path_factory):
    assert Path.home().is_relative_to(tmp_path_factory.getbasetemp())
""",
        env={
            "THINGSDB": str(project / "private.sqlite"),
            "THINGS3_MCP_BRIDGE_URL": "http://127.0.0.1:65535",
            "THINGS3_MCP_CACHE_FILE": str(project / "private.json"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
