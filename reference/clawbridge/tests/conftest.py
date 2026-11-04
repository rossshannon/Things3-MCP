"""Load the exported core and keep synthetic tests away from a real home."""

import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def pytest_sessionstart(session):
    """Block unmocked app workers and reads outside temporary database fixtures."""
    temporary_root = session.config._tmp_path_factory.getbasetemp().resolve()
    active = True

    def guard(event, args):
        if not active:
            return
        if event in {"subprocess.Popen", "os.posix_spawn"}:
            executable, argv = args[:2]
            command = [os.fsdecode(executable), *(os.fsdecode(arg) for arg in argv)] if isinstance(argv, list | tuple) else [os.fsdecode(executable), os.fsdecode(argv)]
            if any(Path(arg).name in {"osascript", "tccutil", "sqlite3"} or any(module in arg for module in ("clawbridge.examples.music", "clawbridge.examples.catalogue")) for arg in command):
                pytest.fail("Hermetic test blocked a live app command or worker; mock the boundary.", pytrace=False)
        elif event == "os.system":
            pytest.fail("Hermetic test blocked a shell command.", pytrace=False)
        elif event == "sqlite3.connect":
            location = os.fsdecode(args[0])
            if location == ":memory:":
                return
            path = unquote(urlsplit(location).path) if location.startswith("file:") else location
            if not Path(path).expanduser().resolve().is_relative_to(temporary_root):
                pytest.fail("Hermetic test blocked database access outside temporary fixtures.", pytrace=False)

    def deactivate():
        nonlocal active
        active = False

    session.config.add_cleanup(deactivate)
    sys.addaudithook(guard)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in tuple(os.environ):
        if name.startswith("CLAWBRIDGE_"):
            monkeypatch.delenv(name)
