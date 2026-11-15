"""Logging is configured when the server module is imported, so it must never stop the import."""

import logging

import pytest

from things3_mcp import logging_config


@pytest.fixture
def root_logger():
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield root
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def test_log_files_are_written_under_the_log_directory(tmp_path, monkeypatch, root_logger):
    monkeypatch.setattr(logging_config, "LOGS_DIR", tmp_path / "state" / "logs")
    logging_config.setup_logging()
    assert sorted(path.name for path in (tmp_path / "state" / "logs").iterdir()) == ["things3_mcp.log", "things3_mcp_errors.log", "things3_mcp_structured.json"]
    assert len(root_logger.handlers) == 4


def test_an_unwritable_home_leaves_console_logging_and_does_not_raise(tmp_path, monkeypatch, root_logger):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    monkeypatch.setattr(logging_config, "LOGS_DIR", blocker / "logs")
    logging_config.setup_logging()
    assert [type(handler) for handler in root_logger.handlers] == [logging.StreamHandler]
