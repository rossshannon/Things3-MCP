"""Test suite for error handling and logging improvements.

This module tests the enhanced error handling, logging, and edge cases
introduced to improve the reliability of the Things MCP server.
"""

import io
import logging
import os
import sys
from unittest.mock import patch

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from things3_mcp.applescript_bridge import add_todo  # noqa: E402
from things3_mcp.fast_server import add_task  # noqa: E402

from .conftest import (  # noqa: E402
    delete_todo_by_id,
    generate_random_string,
)


def test_applescript_error_logging_detail():
    """Test that AppleScript errors are logged with proper detail."""
    # Capture log output
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    logger = logging.getLogger("things3_mcp.applescript_bridge")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    try:
        # Test with mocking both the readiness check and the AppleScript execution
        with patch("things3_mcp.applescript_bridge.ensure_things_ready") as mock_ready:
            with patch("things3_mcp.applescript_bridge.run_applescript") as mock_run:
                # Mock Things as ready and AppleScript returning an error
                mock_ready.return_value = True
                mock_run.return_value = "Error: AppleScript timed out"

                result = add_todo(title="Test Todo", list_id="fake-id")

                # Should return False for failed creation
                assert result is False, "Should return False for AppleScript error"

                # Check that the error was logged
                log_output = log_capture.getvalue()
                assert "AppleScript operation failed" in log_output
                assert "Test Todo" not in log_output
                assert "fake-id" not in log_output
                assert "Error: AppleScript timed out" not in log_output

    finally:
        logger.removeHandler(handler)


@pytest.mark.live_things
def test_mcp_server_error_propagation():
    """Test that MCP server properly propagates and formats AppleScript errors."""
    title = f"Error Propagation Test {generate_random_string(5)}"

    # Test with a scenario that should cause an error - use a malformed list_id
    result = add_task(title=title, list_id="definitely-invalid-uuid-format")

    # Should return properly formatted message (either success or graceful error)
    assert isinstance(result, str), "Should return string result"
    # Should either succeed (graceful handling) or return proper error format
    assert "✅" in result or "⚠️" in result, "Should have proper emoji formatting"

    # Should not return raw AppleScript errors
    assert not result.startswith("/var/folders/"), "Should not return temp file paths"
    assert "script error" not in result.lower(), "Should not contain raw AppleScript errors"

    # Clean up if todo was created
    import re

    match = re.search(r"ID: ([^)]+)\)", result)
    if match:
        try:
            delete_todo_by_id(match.group(1))
        except Exception:
            pass  # Ignore cleanup failures


@pytest.mark.live_things
def test_error_message_format_consistency():
    """Test that all error messages follow consistent formatting."""
    title = f"Format Test {generate_random_string(5)}"
    created_todos = []

    # Test with various scenarios that might cause different types of responses
    test_scenarios = [
        {"list_id": "malformed-uuid"},  # Should create successfully (graceful)
        {"list_id": "00000000-0000-0000-0000-000000000000"},  # Should create successfully (graceful)
        {"list_title": "NonExistentProject" + generate_random_string(10)},  # Should create successfully (graceful)
    ]

    for i, scenario in enumerate(test_scenarios):
        result = add_task(title=f"{title}_{i}", **scenario)

        # Check message format
        assert isinstance(result, str), f"Should return string for scenario: {scenario}"
        # Should have proper emoji formatting
        assert "✅" in result or "⚠️" in result, f"Should have proper emoji: {result}"
        # Should not have raw error formats
        assert not result.startswith("Error: Failed"), f"Should not have raw error format: {result}"
        assert not result.startswith("/var/folders/"), f"Should not return temp file paths: {result}"

        # Extract todo ID for cleanup
        import re

        match = re.search(r"ID: ([^)]+)\)", result)
        if match:
            created_todos.append(match.group(1))

    # Clean up created todos
    for todo_id in created_todos:
        try:
            delete_todo_by_id(todo_id)
        except Exception:
            pass  # Ignore cleanup failures


def test_applescript_timeout_error_detection():
    """Test detection and handling of AppleScript timeout errors."""
    # Test various timeout-related error messages
    timeout_errors = [
        "Error: AppleScript timed out",
        "Error: timeout",
        "Error: Process timed out after 8 seconds",
    ]

    for timeout_error in timeout_errors:
        with patch("things3_mcp.applescript_bridge.ensure_things_ready", return_value=True), patch("things3_mcp.applescript_bridge.run_applescript") as mock_run:
            mock_run.return_value = timeout_error

            result = add_todo(title="Timeout Test", list_id="some-id")

            # Should return False for timeout
            assert result is False, f"Should return False for timeout: {timeout_error}"


def test_applescript_temp_file_error_detection():
    """Test detection and handling of AppleScript temp file path errors."""
    # Test various temp file path errors (indication of AppleScript failure)
    temp_file_errors = [
        "/var/folders/sj/abc123/T/tempfile.applescript",
        "/var/folders/xyz/def456/TemporaryItems/script.txt",
        "/private/tmp/applescript_temp_123.txt",  # Use /private/tmp instead of /tmp
    ]

    for temp_error in temp_file_errors:
        with patch("things3_mcp.applescript_bridge.ensure_things_ready", return_value=True), patch("things3_mcp.applescript_bridge.run_applescript") as mock_run:
            mock_run.return_value = temp_error

            result = add_todo(title="Temp Error Test", list_id="some-id")

            # Should return False for temp file path error
            assert result is False, f"Should return False for temp file error: {temp_error}"


def test_error_logging_includes_context(monkeypatch, caplog):
    """Operation logs remain useful without retaining parameters or error payloads."""
    from things3_mcp import fast_server
    from things3_mcp.providers import ProviderError

    class FailingProvider:
        def add_task(self, params):
            assert params["title"] == "private-title-canary"
            raise ProviderError("outcome_unknown", "private-error-canary", outcome="outcome_unknown", correlation_id="safe-correlation")

    monkeypatch.setattr(fast_server, "get_provider", lambda: FailingProvider())
    with caplog.at_level(logging.DEBUG):
        result = fast_server.add_task(title="private-title-canary", notes="private-note-canary", list_id="private-id-canary")
    assert "safe-correlation" in result
    assert "Things add_task failed" in caplog.text
    assert "private-" not in caplog.text


@pytest.mark.live_things
def test_success_logging_includes_location():
    """Successful add_task results include the destination list/area/project.

    Historically this asserted on log lines from ``things3_mcp.applescript_bridge``,
    but with writes routed through the bridge worker subprocess those logs no
    longer surface in the test process. The MCP tool's return value still
    carries the location ("in <List>"), which is the user-facing contract.
    """
    created_todos = []

    try:
        title = f"Success Logging Test {generate_random_string(5)}"

        result = add_task(title=title)

        assert "✅" in result, f"Should be successful: {result}"
        assert "(ID: " in result, f"Should include the new todo's UUID: {result}"
        assert " in " in result, f"Should include location information: {result}"

        # Extract the UUID for cleanup.
        import re

        match = re.search(r"ID: ([^)]+)\)", result)
        if match:
            created_todos.append(match.group(1))

    finally:
        for todo_id in created_todos:
            try:
                delete_todo_by_id(todo_id)
            except Exception:
                pass  # Ignore cleanup failures


def test_edge_case_parameter_logging(monkeypatch, caplog):
    """Empty parameters keep their behaviour without logging task content."""
    from things3_mcp import fast_server

    captured = {}

    class Provider:
        def add_task(self, params):
            captured.update(params)
            return {"id": "synthetic-id"}

        def get(self, _uuid):
            return {"start": "Inbox"}

    monkeypatch.setattr(fast_server, "get_provider", Provider)
    with caplog.at_level(logging.DEBUG):
        result = fast_server.add_task(title="private-title-canary", list_id="", list_title=None, tags=[], notes="")
    assert "✅" in result
    assert "in List: Inbox" in result
    assert captured == {"title": "private-title-canary", "list_id": "", "tags": [], "notes": ""}
    assert "MCP create todo requested" in caplog.text
    assert "private-title-canary" not in caplog.text
