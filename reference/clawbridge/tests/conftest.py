"""Load the exported core and keep synthetic tests away from a real home."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in tuple(os.environ):
        if name.startswith("CLAWBRIDGE_"):
            monkeypatch.delenv(name)
