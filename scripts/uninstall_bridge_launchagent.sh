#!/usr/bin/env bash
set -euo pipefail

PLIST_TARGET="${HOME}/Library/LaunchAgents/com.rossshannon.things3-mcp.bridge.plist"
APP_TARGET="${HOME}/Applications/Things3 MCP Bridge.app"

if [[ -f "${PLIST_TARGET}" ]]; then
  launchctl unload "${PLIST_TARGET}" >/dev/null 2>&1 || true
  rm -f "${PLIST_TARGET}"
fi

rm -rf "${APP_TARGET}"
echo "Uninstalled Things3 MCP Bridge LaunchAgent and app bundle. Cache/token files were left in Application Support."
