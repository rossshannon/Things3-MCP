from pathlib import Path

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
