"""Prove the exported test harness rejects real application boundaries."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("boundary", ["osascript", "music", "catalogue", "database"])
def test_standalone_harness_blocks_real_boundaries(tmp_path, boundary):
    root = Path(__file__).resolve().parents[1]
    harness = root / "reference/clawbridge/tests/conftest.py"
    if not harness.exists():
        harness = root / "tests/conftest.py"
    project = tmp_path / "probe"
    project.mkdir()
    (project / "conftest.py").write_bytes(harness.read_bytes())
    (project / "pytest.ini").write_text("[pytest]\n")
    sentinel = project / "launched"
    if boundary == "database":
        body = f"import sqlite3\ndef test_probe():\n    sqlite3.connect({str(sentinel)!r})\n"
    else:
        if boundary == "osascript":
            command = project / "osascript"
            command.write_text(f"#!/bin/sh\nprintf launched > '{sentinel}'\n")
            command.chmod(0o700)
            argv = [str(command)]
        else:
            package = project / "clawbridge/examples"
            package.mkdir(parents=True)
            (package.parent / "__init__.py").write_text("")
            (package / "__init__.py").write_text("")
            (package / f"{boundary}.py").write_text(f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n")
            argv = [sys.executable, "-m", f"clawbridge.examples.{boundary}", "--worker-action", "read"]
        body = f"import subprocess\ndef test_probe():\n    subprocess.run({argv!r}, check=True)\n"
    (project / "test_probe.py").write_text(body)
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTEST_ADDOPTS", "PYTHONPATH"}}
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--basetemp", str(project / "pytest-tmp")], cwd=project, env=environment, text=True, capture_output=True, timeout=30, check=False)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Hermetic test blocked" in result.stdout
    assert not sentinel.exists()
