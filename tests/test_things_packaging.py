from pathlib import Path

import pytest

from clawbridge import packaging


def test_default_things_configuration_preserves_identity_and_paths():
    root = Path(__file__).resolve().parents[1]
    config = packaging.load_config(root / "packaging/macos/bridge.toml")
    assert config.name == "Things3 MCP Bridge"
    assert config.bundle_id == "com.rossshannon.things3-mcp.bridge"
    assert config.entrypoint == "things3_mcp_bridge.server:main"
    assert config.state_directory == "Library/Application Support/Things3-MCP"
    assert config.socket_name == "bridge.sock"
    assert config.token_name == "bridge.token"  # noqa: S105 -- preserves a filename, not a credential
    assert config.apple_event_targets == ("com.culturedcode.ThingsMac",)
    plist = packaging.info_plist(config, "2.5.0")
    assert plist["CFBundleVersion"] == plist["CFBundleShortVersionString"] == "2.5.0"
    assert "reads" in plist["NSAppleEventsUsageDescription"]
    assert "updates" in plist["NSAppleEventsUsageDescription"]


@pytest.mark.parametrize("filename,setting", [("bridge.toml", "THINGS3_MCP_BRIDGE_JOURNAL_PAYLOADS"), ("example.toml", "CLAWBRIDGE_JOURNAL_PAYLOADS")])
def test_installed_journal_payload_opt_in_is_explicit(filename, setting, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    config = packaging.load_config(root / "packaging/macos" / filename)
    home = Path("/Users/example")
    target = home / "Applications" / f"{config.name}.app"
    monkeypatch.delenv(setting, raising=False)
    assert setting not in packaging.launchagent(config, home, target, False)["EnvironmentVariables"]
    monkeypatch.setenv(setting, "1")
    assert packaging.launchagent(config, home, target, False)["EnvironmentVariables"][setting] == "1"
    monkeypatch.setenv(setting, "2")
    with pytest.raises(packaging.PackagingError, match="Invalid value"):
        packaging.launchagent(config, home, target, False)
