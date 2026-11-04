"""Diagnostic commands use synthetic paths and never contact a real app."""

import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def diagnostic(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/check_bridge.py"
    spec = importlib.util.spec_from_file_location("bridge_diagnostic", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "APP_BUNDLE", tmp_path / "Synthetic.app")
    monkeypatch.setattr(module, "run_codesign_summary", lambda _bundle: "synthetic signature")
    monkeypatch.setattr(module, "CacheStore", lambda: SimpleNamespace(status=lambda: {"available": False}))
    socket_path, token_path = tmp_path / "bridge.sock", tmp_path / "bridge.token"
    socket_path.touch()
    token_path.write_text("synthetic-test-token")
    monkeypatch.setenv("THINGS3_MCP_BRIDGE_SOCKET", str(socket_path))
    monkeypatch.setenv("THINGS3_MCP_BRIDGE_TOKEN_FILE", str(token_path))
    calls = []

    @contextmanager
    def client(provider):
        def request(method, path, **kwargs):
            calls.append((provider.timeout, method, path, kwargs.get("headers", {})))
            envelope = {"ok": True, "source": "live", "data": {"version": "synthetic"}}
            return SimpleNamespace(json=lambda: envelope)

        yield SimpleNamespace(request=request)

    monkeypatch.setattr(module.BridgeThingsProvider, "_client", client)
    return module, socket_path, token_path, calls


def test_defaults_use_current_timeout_and_configured_paths(diagnostic, capsys, monkeypatch):
    module, socket_path, token_path, calls = diagnostic
    monkeypatch.setattr(sys, "argv", ["check_bridge.py"])
    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["bridge_running"] is True
    assert result["socket_path"] == str(socket_path)
    assert result["token_file"] == str(token_path)
    assert calls[0][0] == 35


def test_invalid_timeout_returns_structured_diagnostics(diagnostic, capsys, monkeypatch):
    module, _, _, calls = diagnostic
    monkeypatch.setattr(sys, "argv", ["check_bridge.py", "--timeout", "20"])
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert "bridge_timeout_invalid" in result["configuration_error"]
    assert result["bridge_running"] is False
    assert calls == []


def test_snapshot_requires_live_read(diagnostic, capsys, monkeypatch):
    module, _, _, calls = diagnostic
    monkeypatch.setattr(sys, "argv", ["check_bridge.py", "--snapshot"])
    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert "live snapshot succeeded" in result["authorization_status"]
    assert calls[-1][2:] == ("/snapshot", {"X-Require-Live": "true"})


def test_snapshot_rejects_cached_response(diagnostic, monkeypatch, capsys):
    module, _, _, _ = diagnostic

    @contextmanager
    def cached_client(_provider):
        yield SimpleNamespace(request=lambda *args, **kwargs: SimpleNamespace(json=lambda: {"ok": True, "source": "cache", "data": {}}))

    monkeypatch.setattr(module.BridgeThingsProvider, "_client", cached_client)
    monkeypatch.setattr(sys, "argv", ["check_bridge.py", "--snapshot"])
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert "live_read_required" in result["snapshot_error"]
    assert "succeeded" not in result["authorization_status"]


def test_missing_socket_does_not_attempt_snapshot(diagnostic, capsys, monkeypatch):
    module, socket_path, _, calls = diagnostic
    socket_path.unlink()
    monkeypatch.setattr(sys, "argv", ["check_bridge.py", "--snapshot"])
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert "not attempted" in result["authorization_status"]
    assert calls == []
