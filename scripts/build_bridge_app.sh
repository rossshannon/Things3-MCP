#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Things3 MCP Bridge"
BUILD_DIR="${ROOT}/build/macos"
APP_DIR="${BUILD_DIR}/${APP_NAME}.app"
PLIST_TEMPLATE="${ROOT}/packaging/macos/Things3 MCP Bridge.app/Contents/Info.plist.template"
ICON_FILE="${ROOT}/packaging/macos/Things3MCPBridge.icns"
ICON_RESOURCE_NAME="Things3MCPBridge.icns"

if [[ ! -f "${ICON_FILE}" ]]; then
  echo "Bridge icon not found: ${ICON_FILE}" >&2
  exit 1
fi

mkdir -p "${BUILD_DIR}"
rm -rf "${APP_DIR}" "${BUILD_DIR}/pyinstaller-work"

ENTRYPOINT="${BUILD_DIR}/bridge_entry.py"
cat > "${ENTRYPOINT}" <<'PY'
from things3_mcp_bridge.server import main

if __name__ == "__main__":
    raise SystemExit(main())
PY

uv run --locked pyinstaller \
  --clean \
  --noconfirm \
  --onedir \
  --windowed \
  --name "${APP_NAME}" \
  --icon "${ICON_FILE}" \
  --osx-bundle-identifier com.rossshannon.things3-mcp.bridge \
  --distpath "${BUILD_DIR}" \
  --workpath "${BUILD_DIR}/pyinstaller-work" \
  --collect-submodules things \
  --collect-submodules things3_mcp \
  --collect-submodules things3_mcp_bridge \
  "${ENTRYPOINT}" >/dev/null

cp "${PLIST_TEMPLATE}" "${APP_DIR}/Contents/Info.plist"
cp "${ICON_FILE}" "${APP_DIR}/Contents/Resources/${ICON_RESOURCE_NAME}"

/usr/libexec/PlistBuddy -c "Delete :LSBackgroundOnly" "${APP_DIR}/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "${APP_DIR}/Contents/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "${APP_DIR}/Contents/Info.plist"

echo "Built ${APP_DIR}"
cat <<'EOF'

Next:
  scripts/sign_bridge_app.sh --identity "Things3 MCP Local"

If you do not have that local signing identity yet, run:
  scripts/sign_bridge_app.sh --help
EOF
