#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SOURCE="${ROOT}/build/macos/Things3 MCP Bridge.app"
APP_TARGET="${HOME}/Applications/Things3 MCP Bridge.app"
PLIST_TEMPLATE="${ROOT}/packaging/macos/com.rossshannon.things3-mcp.bridge.plist.template"
PLIST_TARGET="${HOME}/Library/LaunchAgents/com.rossshannon.things3-mcp.bridge.plist"
LOG_DIR="${HOME}/Library/Logs/Things3-MCP"
DATA_FOLDER="${THINGS3_MCP_DATA_FOLDER:-}"

if [[ ! -d "${APP_SOURCE}" ]]; then
  echo "App bundle not found: ${APP_SOURCE}. Run build/sign scripts first." >&2
  exit 1
fi

# Detect Bun-rooted shells. macOS 26 Tahoe's TCC attributes the bridge's
# responsibility to whichever process spawns the launchctl bootstrap call.
# If that's a Bun runtime (OpenClaw, Claude Desktop, Claude Code), the bridge
# inherits Bun as its responsible code; tccd then asks "does Bun have FDA?"
# instead of "does the bridge have FDA?", and silently denies. Refuse to
# install from such a context — the user must run from Terminal.app, Warp,
# iTerm, or any non-Bun shell. Set THINGS3_MCP_INSTALL_FORCE=1 to override.
detect_bun_in_chain() {
  local pid="$1"
  while [[ "${pid}" -gt 1 ]]; do
    local cmd
    cmd="$(ps -o command= -p "${pid}" 2>/dev/null || true)"
    if [[ "${cmd}" == *"/bun"* || "${cmd}" == *" bun "* ]]; then
      return 0
    fi
    pid="$(ps -o ppid= -p "${pid}" 2>/dev/null | tr -d ' ' || true)"
    [[ -z "${pid}" ]] && break
  done
  return 1
}
if [[ -z "${THINGS3_MCP_INSTALL_FORCE:-}" ]] && detect_bun_in_chain "$$"; then
  cat >&2 <<'EOF'
Refusing to install: this shell's process tree contains a Bun runtime.

macOS 26 Tahoe's TCC attributes the bridge's responsible process to whatever
launches the launchctl bootstrap call. If that's Bun (OpenClaw, Claude Desktop,
Claude Code), the bridge inherits Bun as its responsible code and TCC silently
denies access to your Things database — even if the bundle is granted Full Disk
Access in System Settings.

Open Terminal.app, Warp, or iTerm directly (Cmd+Space -> "Terminal" -> Enter)
and re-run this script from there. To bypass this check anyway, set
THINGS3_MCP_INSTALL_FORCE=1.
EOF
  exit 2
fi

SIGNATURE="$(codesign -dv "${APP_SOURCE}" 2>&1 || true)"
if ! grep -Fq "Identifier=com.rossshannon.things3-mcp.bridge" <<<"${SIGNATURE}"; then
  echo "The bridge app is not signed with the expected bundle identifier." >&2
  echo "Run scripts/sign_bridge_app.sh before installing." >&2
  exit 1
fi

if grep -Fq "Signature=adhoc" <<<"${SIGNATURE}"; then
  cat >&2 <<'EOF'
Warning: installing an ad-hoc signed bridge app.

This can work for quick testing, but it is not the recommended Full Disk Access
setup. For reliable repeated access, sign with a local Code Signing certificate:
  scripts/sign_bridge_app.sh --identity "Things3 MCP Local"
EOF
fi

cat >&2 <<'EOF'
Security trade-off:
  This installs a per-user LaunchAgent for a local bridge service. If you grant
  Full Disk Access, the bridge can read Things data and maintain a JSON cache. If
  you grant Automation, it can ask Things 3 to create or update items. The socket,
  token, cache, and logs are owner-only, but they are not a sandbox boundary
  against other unsandboxed processes running as your macOS user. Protect the
  local signing identity/private key; code re-signed with that same identity may
  be treated as the same app by macOS privacy checks.

  Continue only if you trust this checkout, its dependencies, the local signing
  identity, and the MCP clients allowed to call the bridge.
  Details: docs/security/local-bridge-security.md
EOF

if [[ -n "${DATA_FOLDER}" && ! "${DATA_FOLDER}" =~ ^ThingsData-[A-Za-z0-9_-]+$ ]]; then
  echo "Invalid THINGS3_MCP_DATA_FOLDER=${DATA_FOLDER}" >&2
  echo "Expected a folder name like ThingsData-ABC123." >&2
  exit 1
fi

mkdir -p "${HOME}/Applications" "${HOME}/Library/LaunchAgents" "${LOG_DIR}"
rm -rf "${APP_TARGET}"
cp -R "${APP_SOURCE}" "${APP_TARGET}"
sed \
  -e "s#__HOME__#${HOME}#g" \
  -e "s#__THINGS3_MCP_DATA_FOLDER__#${DATA_FOLDER}#g" \
  "${PLIST_TEMPLATE}" > "${PLIST_TARGET}"
launchctl bootout "gui/$(id -u)/com.rossshannon.things3-mcp.bridge" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_TARGET}"
echo "Installed LaunchAgent at ${PLIST_TARGET}"
if [[ -n "${DATA_FOLDER}" ]]; then
  echo "Configured LaunchAgent THINGS3_MCP_DATA_FOLDER=${DATA_FOLDER}"
fi
cat <<EOF

Now grant macOS privacy access to the installed app:
  ${APP_TARGET}

Security note:
  Granting Full Disk Access and Automation is a local capability grant to the
  bridge. It improves AFK reliability, but any same-user process that obtains
  the bridge token may be able to use that granted access.

System Settings -> Privacy & Security -> Full Disk Access:
  1. Remove any older Things3 MCP Bridge entry.
  2. Add ${APP_TARGET}.
  3. Toggle it on.
  4. Restart the LaunchAgent by re-running this install script.

Then verify:
  uv run python scripts/check_bridge.py --snapshot
EOF
