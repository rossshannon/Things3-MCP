#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${ROOT}/build/macos/Things3 MCP Bridge.app"
IDENTITY="Things3 MCP Local"
ADHOC=0

usage() {
  cat <<'EOF'
Sign the local Things3 MCP Bridge.app bundle.

macOS privacy permissions are attached to code identity. The point of this
bridge is to give Full Disk Access to one stable local app, instead of repeatedly
granting access to changing Python, Node, Claude, or terminal binaries.

Recommended:
  scripts/sign_bridge_app.sh
  scripts/sign_bridge_app.sh --identity "Things3 MCP Local"

Development-only fallback:
  scripts/sign_bridge_app.sh --adhoc

Ad-hoc signing is useful for quick tests, but each rebuild can look like a new
app to macOS privacy controls. For reliable AFK access, use a local Code Signing
certificate.

Security trade-off:
  Self-signing gives macOS a stable local identity for this bridge, but it is not
  notarisation or third-party provenance. Only sign code and dependencies you
  trust. After Full Disk Access or Automation is granted, the bridge can read
  Things data and perform supported Things writes through a local token/socket.
  Protect the local signing identity/private key; code re-signed with that same
  identity may be treated as the same app by macOS privacy checks.
  Read docs/security/local-bridge-security.md before granting privacy access.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --identity)
      IDENTITY="${2:?missing signing identity after --identity}"
      shift 2
      ;;
    --adhoc)
      IDENTITY="-"
      ADHOC=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "${APP}" ]]; then
  echo "App bundle not found: ${APP}. Run scripts/build_bridge_app.sh first." >&2
  exit 1
fi

if [[ "${ADHOC}" -eq 0 ]] && ! security find-identity -v -p codesigning 2>/dev/null | grep -Fq "\"${IDENTITY}\""; then
  cat >&2 <<EOF
No valid code-signing identity named "${IDENTITY}" was found.

Create one locally:
  1. Open Keychain Access.
  2. Choose Keychain Access -> Certificate Assistant -> Create a Certificate...
  3. Name: ${IDENTITY}
  4. Identity Type: Self Signed Root
  5. Certificate Type: Code Signing
  6. Create it in your login keychain.
  7. If it still does not appear in the command below, open the certificate,
     expand Trust, and set Code Signing to "Always Trust".

Verify:
  security find-identity -v -p codesigning

Then re-run:
  scripts/sign_bridge_app.sh --identity "${IDENTITY}"

For short-lived development testing only:
  scripts/sign_bridge_app.sh --adhoc
EOF
  exit 2
fi

if [[ "${ADHOC}" -eq 1 ]]; then
  cat >&2 <<'EOF'
Signing ad-hoc. This is only recommended for quick development testing; use a
local Code Signing certificate before granting Full Disk Access for real use.
EOF
fi

cat >&2 <<'EOF'
Security reminder: signing is the first half of the bridge trust decision. The
second half is granting macOS privacy access to the installed app. Do not grant
Full Disk Access or Automation unless you trust this checkout, its dependencies,
the local signing identity, and the MCP clients that will be allowed to call the
bridge.
EOF

codesign --force --deep --sign "${IDENTITY}" "${APP}"
codesign --verify --deep --strict --verbose=2 "${APP}"
codesign -dv --verbose=4 "${APP}"
echo "Signed ${APP} with identity: ${IDENTITY}"
