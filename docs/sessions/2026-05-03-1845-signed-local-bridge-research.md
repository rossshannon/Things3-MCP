# Research: Process Identity, FDA, and Automation for the Signed Local Bridge

**Date**: 2026-05-03
**Branch**: `feature/signed-local-bridge`
**Status**: Research synthesis (awaiting third agent: prior-art search)
**Trigger**: Codex implementation hit `things_db_timeout` after self-signing + FDA grant. Asked Opus to research the macOS TCC, FDA, and Apple Events attribution model before continuing to code.

## TL;DR (recommended path forward)

1. **Add `AssociatedBundleIdentifiers` to the LaunchAgent plist.** Without it, the bundle ID stored in System Settings → FDA does not reliably attribute to the LaunchAgent-spawned process. This is the single most likely root cause of the timeout. (Apple DTS Q-Forum 766351, 678819.)
2. **Switch `LSBackgroundOnly=true` to `LSUIElement=true`** in `Info.plist`. `LSBackgroundOnly` suppresses Apple Events permission prompts because the process has no UI session to show them in. `LSUIElement` hides the dock icon but still allows alerts. (gridsync#284, micahrl LaunchAgent guide.)
3. **Add `NSAppleEventsUsageDescription`** to `Info.plist`. Mandatory for any Apple Events; without it the event fails with `errAEEventNotPermitted (-1743)` and *no* prompt is shown. (Apple Forum 710896.)
4. **Replace `subprocess(/usr/bin/osascript)` with PyObjC `OSAKit` in-process JXA.** OSAKit runs the script inside the bridge bundle's identity, so Automation grants attach to `com.rossshannon.things3-mcp.bridge` rather than `/usr/bin/osascript`. JXA scripts compile unchanged. (PyObjC `OSAKit` API; mikebian.co JXA-from-Python.)
5. **Inside the bridge worker, allow enumeration of the protected group container.** The deliberate refusal in `db_reader.resolve_things_db_path()` only made sense for the MCP server (which lacks FDA). The bridge worker has FDA — it must enumerate to find `ThingsData-*`.
6. **Stop shipping `--options runtime` (Hardened Runtime).** Not required for FDA; harmful for PyInstaller without entitlements (`cs.allow-jit`, `cs.allow-unsigned-executable-memory`, `cs.disable-library-validation`). Self-signed dev binary doesn't need notarization.
7. **Stabilize the signing identity.** Reuse the same `Things3 MCP Local` certificate across rebuilds. Don't regenerate it on every machine; export and re-import. csreq mismatch from changed identity is the single cause of "looks granted but isn't" plus the remove/re-add dance.

After (1)–(7), the bridge should serve real Things data via the SQLite path with a single one-time FDA grant. The Apple Events fallback (also fixed by 2–4) becomes a robust secondary read mode and the basis for *write* operations later.

## What's blocking the bridge today (concrete diagnosis)

Confirmed locally on `feature/signed-local-bridge` worktree:

- Bundle is signed: `Authority=Things3 MCP Local`, `Identifier=com.rossshannon.things3-mcp.bridge`, `flags=0x0` (no hardened runtime), no entitlements file. CDHash is stable across this session.
- LaunchAgent runs `Contents/MacOS/Things3 MCP Bridge` directly via `ProgramArguments`. No `AssociatedBundleIdentifiers` is set.
- `Info.plist` has `LSBackgroundOnly=true`. No `NSAppleEventsUsageDescription`. No other privacy purpose strings.
- `THINGS3_MCP_DATA_FOLDER` in the installed plist is the empty string `<string></string>` — sed replaced the placeholder with an unset env var.
- Worker hangs for 30 seconds on `--snapshot-once`. Two failure paths inside the worker:
  - **SQLite path**: `resolve_things_db_path()` in `db_reader.py` deliberately refuses to enumerate `~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/` unless `THINGSDB` or `THINGS3_MCP_DATA_FOLDER` is set. Both are unset/empty. So this raises `FileNotFoundError` immediately.
  - **JXA fallback**: spawns `/usr/bin/osascript -l JavaScript`. Apple Events fail. Process hangs 30s waiting for a TCC prompt that never appears (because `LSBackgroundOnly`) or for an event that's silently denied (no `NSAppleEventsUsageDescription`).
- Things3 itself is running (PID 773) and scriptable from a Terminal context (`osascript -l JavaScript -e '...'` returns all 30 lists in <1s). So Things3's scripting interface is fine — the problem is the bridge's identity.

## Q1 — LaunchAgent and FDA inheritance

**Does a LaunchAgent that runs `Contents/MacOS/<binary>` directly inherit the .app's TCC grant?**

Conditionally yes. macOS TCC matches the running process to the `client` row in `TCC.db` by **code identity**, not by enclosing-bundle directory walk. The match works if:

- The Mach-O inside `Contents/MacOS/` has the same `CFBundleIdentifier` as the bundle.
- Its code-signing Designated Requirement validates against the `csreq` column TCC stored when the user granted permission.
- launchd's spawn metadata can tie the running process back to a bundle ID.

The third condition is where the current setup breaks: a `ProgramArguments`-based legacy LaunchAgent invokes the binary via `execv`, with `launchd` as the parent. macOS doesn't auto-discover the enclosing `.app`. **The fix is `AssociatedBundleIdentifiers` in the launchd plist.** Apple DTS (Quinn "the Eskimo"):

> "If you're building a launchd daemon or agent and you find that it's not correctly attributed to your app, add the `AssociatedBundleIdentifiers` property to your launchd property list." — [Forum 678819](https://developer.apple.com/forums/thread/678819)

> "If you do stick with launchd property lists, make sure you set `AssociatedBundleIdentifiers`. That way the system can tie your launchd job to something user visible." — [Forum 766351](https://developer.apple.com/forums/thread/766351)

The fully-modern path is `SMAppService` + `BundleProgram`, which requires registering the agent from a parent `.app` at first run. Overkill for this bridge — `AssociatedBundleIdentifiers` is sufficient.

**Reference launchd plist additions**:

```xml
<key>AssociatedBundleIdentifiers</key>
<array>
    <string>com.rossshannon.things3-mcp.bridge</string>
</array>
```

## Q2 — Code signing requirements

**Self-signed certs are explicitly supported by Apple for stable DR**:

> "Stability is determined through the designated requirement (DR) mechanism, and **does not depend on the nature of the certificate authority used. Self-signed identities and homemade certificate authorities work by default for this case.**" — [Apple Code Signing Guide](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html)

What breaks across rebuilds:

| Change | Effect on TCC grant |
|---|---|
| Different `CFBundleIdentifier` | New `client` row required, old grant orphaned |
| Different signing identity (e.g. ad-hoc → cert) | csreq mismatch, silent deny |
| Regenerated self-signed cert (different keys) | csreq mismatch, silent deny |
| Same cert, same identifier, different code | Validates → grant matches |

Action: keep the `Things3 MCP Local` cert/key pair stable. Export it from Keychain on the dev machine and reimport rather than regenerating. The session note from 18:15 IST confirms it was created with `openssl` and imported — keep that PKCS#12 in a safe place (out of git) so rebuilds use the same key.

**Hardened Runtime (`--options runtime`)**: not required for FDA, harmful for PyInstaller without the `cs.*` entitlements. Drop it for the self-signed dev path. If notarization is ever needed for distribution, add it back along with the entitlements file.

**`--deep` is increasingly inadequate.** PyInstaller's wiki and the Apple `codesign` man page both prefer signing nested code first (libs, then framework, then bundle). For a self-signed `--onedir` PyInstaller build it tends to work, but verify with:

```bash
codesign --verify --deep --strict --verbose=2 ~/Applications/Things3\ MCP\ Bridge.app
```

If that emits any "valid on disk" + "satisfies its Designated Requirement" but warnings about inner components, sign those individually before `--deep` on the bundle.

## Q3 — Subprocess attribution for SQLite/file reads

**Children inherit FDA from the parent, *if* they're the same code identity.**

> "permissions are inherited by child processes. And when a process is about to access some protected resource, the TCC subsystem figures out which process is the responsible one, and uses that as basis for requesting and persisting the result." — [Qt blog](https://www.qt.io/blog/the-curious-case-of-the-responsible-process)

The Claude Code Desktop bug ([anthropics/claude-code#24162](https://github.com/anthropics/claude-code/issues/24162)) is the same shape as this bridge: a parent `.app` had FDA, but a child binary stored *outside* the bundle did not — `auth_value=5` (auto-deny) on `kTCCServiceSystemPolicyAppData`. Fix: keep the child inside the bundle.

**Critical for this bridge**: `subprocess.run([sys.executable, "--worker-action", ...])` re-runs the same PyInstaller bootloader Mach-O. That's good — the worker child is the same code identity as the parent. Inheritance should hold. (Watch for fork-bomb if `_PYI_PARENT_PROCESS_STARTED` env-guard is missing; PyInstaller docs.)

**The new gate: `kTCCServiceSystemPolicyAppData` (macOS 14+).** This is the most likely silent failure. Apple added it in Sonoma to gate access to `~/Library/Group Containers/...` *independently of FDA*:

> "Starting with macOS Sonoma 14.0, Apple has introduced a new TCC category kTCCServiceSystemPolicyAppData to protect the App Container Data." — [jhftss CVE-2023-42929 writeup](https://jhftss.github.io/CVE-2023-42929-Why-Do-We-Need-The-App-Container-Protection/)

This permission is **non-promptable**. Two paths through:
1. The requesting process has FDA, *and* TCC successfully resolves it to the granted identity.
2. The requesting process is signed with the same Team ID as the container's owner (`JLMPQHK86H` for Things — not us).

So self-signed bridge → only path 1 works → must have working FDA attribution → must have `AssociatedBundleIdentifiers` and stable csreq.

## Q4 — Apple Events attribution via `osascript`

**TCC builds an AttributionChain with three roles**:

- REQ (Requester): the receiving daemon (`appleeventsd`).
- ACC (Accessor): the immediate sender.
- RESP (Responsible): the bundle/binary TCC blames and persists in `TCC.db`.

When you spawn `osascript`, RESP is *usually* the parent (your bundle) on modern macOS, but the heuristic is fragile and recent macOS builds sometimes pin RESP to `osascript` itself when the parent is a generic launchd job. (Documented across [scriptingosx.com](https://scriptingosx.com/2020/09/avoiding-applescript-security-and-privacy-requests/), [steipete.me](https://steipete.me/posts/2025/applescript-cli-macos-complete-guide), and Apple Forum 750802.) The result is permission entries against `/usr/bin/osascript` — which Apple-signed and unmovable — instead of against your bundle.

**Definitive fix: send Apple Events in-process via PyObjC `OSAKit`.** The script runs inside the bridge's address space, the AE leaves the bridge's PID, and RESP is unambiguously the bridge bundle.

```python
# requires: pyobjc-framework-OSAKit, pyobjc-framework-Cocoa
import json
from OSAKit import OSAScript, OSALanguage

_JXA = OSALanguage.languageForName_("JavaScript")
_compiled: dict[str, OSAScript] = {}

def run_jxa(name: str, source: str):
    if name not in _compiled:
        script = OSAScript.alloc().initWithSource_language_(source, _JXA)
        ok, err = script.compileAndReturnError_(None)
        if not ok:
            raise RuntimeError(err.objectForKey_("NSLocalizedDescription") if err else "compile failed")
        _compiled[name] = script
    descriptor, err = _compiled[name].executeAndReturnError_(None)
    if err is not None:
        raise RuntimeError(err.objectForKey_("NSLocalizedDescription") if err else "exec failed")
    raw = descriptor.stringValue()
    return json.loads(raw) if raw else None
```

The existing JXA source strings (`_JXA_LISTS`, `_JXA_META`, `_JXA_SIMPLE`) compile unchanged.

**Pre-flight TCC probe** without firing a real event:

```python
# Use AEDeterminePermissionToAutomateTarget(target_descriptor, suite, event_id, ask_user_if_needed)
# to surface the consent dialog once at install time, attributed to the bundle.
```

This is the right primitive for a one-time `Things3-MCP-bridge --authorize-once` command that Ross runs to bring up the prompt with the bundle's own purpose string.

## Q5 — Required Info.plist keys

| Key | Required? | Notes |
|-----|-----------|---|
| `CFBundleIdentifier` | yes | already set; matches `com.rossshannon.things3-mcp.bridge` |
| `CFBundleExecutable` | yes; **no `MacOS/` prefix** | currently `Things3 MCP Bridge` ✓ |
| `NSAppleEventsUsageDescription` | **yes — currently missing** | Apple Events fail silently without it |
| `NSSystemAdministrationUsageDescription` | no | only needed for `System Events` sysadmin tasks |
| `LSUIElement` | recommended | hides Dock icon but allows TCC prompts |
| `LSBackgroundOnly` | **change to false (or remove) — currently `true`** | suppresses TCC prompts |
| `CFBundlePackageType` | yes | `APPL` ✓ |
| `CFBundleShortVersionString` | yes | already set |

**Replacement `Info.plist` patches**:

```xml
<key>NSAppleEventsUsageDescription</key>
<string>Things3 MCP Bridge needs to read your Things data through Things 3 so it can serve up-to-date task and project information to AI assistants on your Mac.</string>
<key>LSUIElement</key>
<true/>
<!-- remove LSBackgroundOnly -->
```

## Q6 — Why the remove/re-add dance, and how to query TCC without prompting

The dance forces TCC to capture a *fresh* `csreq` for the current binary. If the user granted FDA when the bridge was ad-hoc signed, the csreq stored is the ad-hoc one, and it won't validate against the now-self-signed binary. Removing wipes the dead row; adding writes a fresh csreq that matches.

**Diagnostic query** (user TCC.db, no SIP issues for own-user reads):

```bash
sqlite3 ~/Library/Application\ Support/com.apple.TCC/TCC.db \
  "SELECT service, client, client_type, auth_value, auth_reason
   FROM access
   WHERE client = 'com.rossshannon.things3-mcp.bridge'
      OR client LIKE '%Things3 MCP Bridge%';"
```

**`auth_value` interpretation**:

| Value | Meaning |
|---|---|
| 0 | Denied (explicit) |
| 1 | Unknown / not yet decided |
| 2 | Allowed |
| 3 | Limited |
| 5 | Auto-denied (e.g. SystemPolicyAppData with no FDA) |

**Decoding the stored csreq vs current bundle DR**:

```bash
# Extract stored csreq blob, decode:
sqlite3 ~/Library/Application\ Support/com.apple.TCC/TCC.db \
  "SELECT hex(csreq) FROM access WHERE client = 'com.rossshannon.things3-mcp.bridge' LIMIT 1;" \
  | xxd -r -p > /tmp/stored-csreq.bin
csreq -r- -t < /tmp/stored-csreq.bin

# Get current bundle DR:
codesign -d -r- ~/Applications/Things3\ MCP\ Bridge.app 2>&1 | grep -A1 designated
```

If the two requirements differ, the grant is dead and the dance is required.

## Q7 — Things3 AppleScript dictionary capability

The dictionary covers everything needed for cache snapshots:

- Top-level: `to dos`, `projects`, `areas`, `tags`, `lists` (Inbox, Today, Anytime, Upcoming, Someday, Logbook, Trash).
- `to do` properties: `id` (UUID, matches SQLite `uuid`), `name`, `notes`, `tag names`, `status` (open / completed / canceled), `creation date`, `modification date`, `due date`, `activation date`, `completion date`, `cancellation date`, `project`, `area`.

Limits:
- No checklist items (use markdown in `notes` as workaround).
- No heading objects within projects.
- No reminder time-of-day (only the date).
- AppleScript path is **slow on large databases** — single-threaded inside Things, holds it at 100% CPU. Bulk dumps via AppleScript take minutes; SQLite reads are seconds. Use SQLite for snapshots, AppleScript for writes.

Locally confirmed: terminal JXA returns all 30 of Ross's Things lists in <1s.

## Recommended architecture changes (concrete)

### A. Keep
- The bridge bundle / LaunchAgent / Unix-socket transport / cache-fallback architecture.
- The provider abstraction (`direct`, `bridge`, `cache`).
- Self-signed Code Signing identity for the local case.
- PyInstaller `--onedir` (NOT `--onefile` — `--onefile` extracts to a different `/var/folders/...` path each launch, breaking TCC).

### B. Fix immediately (sign-and-install path)
1. `packaging/macos/com.rossshannon.things3-mcp.bridge.plist.template`:
   ```xml
   <key>AssociatedBundleIdentifiers</key>
   <array>
       <string>com.rossshannon.things3-mcp.bridge</string>
   </array>
   ```
2. `packaging/macos/Things3 MCP Bridge.app/Contents/Info.plist.template`:
   - Replace `LSBackgroundOnly=true` with `LSUIElement=true`.
   - Add `NSAppleEventsUsageDescription`.
3. `scripts/build_bridge_app.sh`:
   - Apply the same Info.plist edits to the PyInstaller-generated bundle (`/usr/libexec/PlistBuddy`).
   - Remove the existing `LSBackgroundOnly` add/set lines; add `LSUIElement` and the AE usage description instead.
4. `scripts/sign_bridge_app.sh`:
   - Drop any `--options runtime` if present (currently absent — keep it absent).
   - Document that the cert MUST be reused; add a check that warns if the cert was created very recently (potential identity churn).
5. `scripts/install_bridge_launchagent.sh`:
   - When the bundle is reinstalled, also offer to invoke `tccutil reset SystemPolicyAllFiles com.rossshannon.things3-mcp.bridge && tccutil reset AppleEvents com.rossshannon.things3-mcp.bridge` to clear stale csreq rows. (Document that this requires a re-grant.)
6. `src/things3_mcp_bridge/db_reader.py`:
   - Inside the worker, **allow enumeration** of the protected group container. The worker has FDA. The deliberate refusal applies to the MCP server context, not the bridge worker. Use `glob` against `~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-*/Things Database.thingsdatabase/main.sqlite`.
   - Optionally still honor `THINGSDB` / `THINGS3_MCP_DATA_FOLDER` env hints if present, but don't require them.

### C. Migrate Apple Events to in-process (next PR)
1. Add `pyobjc-framework-OSAKit`, `pyobjc-framework-Cocoa` to `pyproject.toml`.
2. Add a new module `src/things3_mcp_bridge/apple_events.py` that wraps `OSAKit.OSAScript` with a compiled-script cache.
3. Replace `_run_jxa_script(...)` in `db_reader.py` with the OSAKit equivalent. Existing JXA source strings stay the same.
4. Add `--hidden-import OSAKit` (and `Foundation`, `objc`, `CoreServices`) to the PyInstaller invocation in `build_bridge_app.sh`.
5. Add `Things3-MCP-bridge --authorize-once` subcommand that calls `AEDeterminePermissionToAutomateTarget(..., askUserIfNeeded=True)` against `com.culturedcode.ThingsMac` to surface the consent prompt under the bundle's identity.

### D. Verification path (after B + C)
1. `scripts/build_bridge_app.sh && scripts/sign_bridge_app.sh --identity "Things3 MCP Local" && scripts/install_bridge_launchagent.sh`
2. In System Settings → Privacy & Security → Full Disk Access: remove old "Things3 MCP Bridge" entry, drag in `~/Applications/Things3 MCP Bridge.app`, toggle on.
3. `Things3-MCP-bridge --authorize-once` → confirm Automation prompt appears, attributed to the bridge bundle, mentioning Things 3.
4. `log stream --predicate 'subsystem == "com.apple.TCC"'` while running step 5; confirm RESP is the bundle path, not `/usr/bin/osascript`.
5. `Things3-MCP-bridge --snapshot-once` → expect successful live read, `latest.json` written.
6. `mcporter call things.get_inbox` (with `THINGS3_MCP_PROVIDER=auto THINGS3_MCP_ALLOW_DIRECT_FALLBACK=0`) → live or cache data, no prompts on the MCP-server side.

### E. Future writes
With OSAKit in place, write operations can move to the bridge by calling Things' AppleScript `make new to do with properties {...}`, `move`, `schedule`, etc. via the same in-process path. Authorization is one-time. This is a separate PR.

## Prior art

**No project I found ships a signed `.app` LaunchAgent for stable FDA on protected SQLite.** This is genuinely new ground in this niche. The closest analogue is **Carbon Copy Cloner's privileged helper** ([bombich.com/en/kb/ccc/5/granting-full-disk-access-ccc-and-its-helper-tool](https://bombich.com/en/kb/ccc/5/granting-full-disk-access-ccc-and-its-helper-tool)) which solves a different problem (boot-disk cloning) but uses the same architectural primitive — signed helper inside the bundle, FDA grant on the helper, not the parent app. CCC 7.1 (2025) moved to `SMAppService` and registers the helper via Login Items.

**Conflict in the research, resolved**: agent #2 said Group Containers are gated by `kTCCServiceSystemPolicyAppData` (silent-deny path); agent #3 said Group Containers are gated by `kTCCServiceSystemPolicyAllFiles` (FDA, promptable). Reading both citations carefully ([imlzq deep dive](https://imlzq.com/apple/macos/2024/08/24/Unveiling-Mac-Security-A-Comprehensive-Exploration-of-TCC-Sandboxing-and-App-Data-TCC.html) and [Apple xcode/accessing-app-group-containers](https://developer.apple.com/documentation/xcode/accessing-app-group-containers)): App Data TCC primarily gates `~/Library/Containers/*/Data` (sandboxed app containers); Group Containers are gated by FDA. The bridge's path is FDA-gated, not the silent-deny path. This is the more optimistic reading and means the standard FDA grant should suffice once attribution works.

**Things 3 MCP servers surveyed** (5 of them): all rely on FDA on the *host* (terminal/Claude.app) and do not ship a signed bridge:

| Repo | Read path | FDA approach |
|---|---|---|
| hald/things-mcp | SQLite via `things.py` | Documents nothing; relies on host FDA |
| excelsier/things-fastmcp | SQLite via `things.py` + AppleScript | Same |
| stepankuzmin/things-mcp | SQLite via `things.py`, supports `THINGS_DB_PATH` env | Same |
| AlexanderWillner/things-mcp | SQLite via `things.py` | Same |
| drjforrest/mcp-things3 | AppleScript only | No FDA needed |
| jimfilippou/things-mcp | URL scheme only | No FDA needed |

We're already going further than any of them.

**Best-in-class patterns to copy from adjacent ecosystems**:

1. **Doctor subcommand with exact settings path string** — `camfortin/imessage-mcp` and `anipotts/imessage-mcp doctor`. Our `check_bridge.py` is the right shape; expose it as `Things3-MCP-bridge --doctor` with explicit remediation URLs and `tccutil reset` hints.
2. **`readOnlyHint: true` MCP tool annotation** — `anipotts/imessage-mcp` annotates all 26 read tools so MCP clients auto-approve without per-call prompts. Apply to our read tools (`get_inbox`, `get_today`, etc.).
3. **MCP error envelope with `remediation_url` and `settings_path`** ([mcpcat.io](https://mcpcat.io/guides/error-handling-custom-mcp-servers/)):
   ```json
   {"error": {"code": -31001, "message": "...", "data": {
       "settings_path": "Privacy & Security → Full Disk Access → Things3 MCP Bridge",
       "remediation": ["tccutil reset SystemPolicyAllFiles com.rossshannon.things3-mcp.bridge"]
   }}}
   ```
4. **EventKit-style preflight permissions trigger** — `snarris/apple-eventkit-mcp` ships `setup_permissions.py` that calls the system permission dialog up front. We should add `Things3-MCP-bridge --authorize-once` that calls `AEDeterminePermissionToAutomateTarget(..., askUserIfNeeded=True)` to surface the Automation prompt under our bundle's identity.
5. **Copy-database escape hatch for offline forensics** — `osxphotos`, `bagoup`. Worth keeping as a documented fallback if the live bridge ever fails: copy the Things SQLite to a non-protected path with `THINGSDB=` env var.

**Things-specific reuse**: keep `things.py` for the SQLite read (read-only `?mode=ro` URI is already correct). Layer in-process JXA via OSAKit for writes and the Apple Events fallback. Both approaches are battle-tested in their own niches.

**Architectural takeaway**: stick with the legacy `~/Library/LaunchAgents/*.plist` pattern + `AssociatedBundleIdentifiers`. SMAppService migration is a v2 concern — would need a Swift launcher binary or new tooling, no immediate benefit over the legacy pattern with `AssociatedBundleIdentifiers` set.

---

## Final synthesis: what to do, in order

### Phase 0 — Stop the bleeding (low-risk fixes that should make snapshot work)
1. **Plist + signing fixes** — single small PR:
   - `packaging/macos/com.rossshannon.things3-mcp.bridge.plist.template`: add `AssociatedBundleIdentifiers`.
   - `packaging/macos/Things3 MCP Bridge.app/Contents/Info.plist.template`: replace `LSBackgroundOnly` with `LSUIElement`; add `NSAppleEventsUsageDescription`.
   - `scripts/build_bridge_app.sh`: apply the same Info.plist edits to the PyInstaller-generated bundle.
   - Confirm signing flow does not pass `--options runtime` (it doesn't currently — keep it that way).
2. **Worker enumeration** — `src/things3_mcp_bridge/db_reader.py`: relax `resolve_things_db_path()` so the worker (which has FDA) glob-searches the protected group container. Keep `THINGSDB`/`THINGS3_MCP_DATA_FOLDER` env hints as overrides, but don't require them.
3. **Rebuild + reinstall**:
   ```bash
   scripts/build_bridge_app.sh
   scripts/sign_bridge_app.sh --identity "Things3 MCP Local"
   scripts/install_bridge_launchagent.sh
   tccutil reset SystemPolicyAllFiles com.rossshannon.things3-mcp.bridge
   ```
   Then re-add the bundle to FDA in System Settings, toggle on, run `Things3-MCP-bridge --snapshot-once`.

If Phase 0 alone makes snapshots succeed, the SQLite path is now durable. The osascript path is still broken but unused.

### Phase 1 — In-process Apple Events (next PR)
1. Add `pyobjc-framework-OSAKit`, `pyobjc-framework-Cocoa` to `pyproject.toml`.
2. New module `src/things3_mcp_bridge/apple_events.py` wraps `OSAKit.OSAScript` with compiled-script cache.
3. Replace `_run_jxa_script(...)` in `db_reader.py` with the OSAKit equivalent. JXA source strings stay identical.
4. PyInstaller hidden imports: `--hidden-import OSAKit`, `--hidden-import Foundation`, `--hidden-import objc`, `--hidden-import CoreServices`.
5. New `Things3-MCP-bridge --authorize-once` subcommand using `AEDeterminePermissionToAutomateTarget` to surface the Automation prompt under bundle identity.

### Phase 2 — UX polish (small PR, no security impact)
1. Expand `scripts/check_bridge.py` (or expose as `Things3-MCP-bridge --doctor`) with the camfortin-style "exact next step" output: settings path, remediation commands.
2. Add MCP tool annotations: `readOnlyHint: true` on all read tools (in `fast_server.py`).
3. Standardize MCP error envelopes for permission errors with `settings_path` + `remediation` data fields.

### Phase 3 — Bridge writes (separate PR)
With OSAKit in place, route Things writes through the bridge: `make new to do`, `move`, `schedule`, `set tag names`. One-time Automation grant covers this. Documented as the durable AFK-write path.

### Phase 4 — Distribution (future, optional)
- Apple Developer ID signing → notarization → Hardened Runtime + entitlements file.
- `.mcpb` packaging for Claude Desktop one-click install.
- SMAppService migration when there's a tangible UX benefit (e.g., Login Items toggle in System Settings).

## Sources (selected)

- Apple — TN3127 Inside Code Signing: Requirements: https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements
- Apple Forum 678819 — File system permissions / `AssociatedBundleIdentifiers`: https://developer.apple.com/forums/thread/678819
- Apple Forum 766351 — Modern launchd job deployment: https://developer.apple.com/forums/thread/766351
- Apple Forum 710896 — `NSAppleEventsUsageDescription` requirements: https://developer.apple.com/forums/thread/710896
- Apple Forum 750802 — `com.apple.security.automation.apple-events` entitlement: https://developer.apple.com/forums/thread/750802
- Apple Forum 731504 — Responsible process semantics (Quinn): https://developer.apple.com/forums/thread/731504
- Apple Code Signing Guide — DR is stable across self-signed certs: https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/Procedures/Procedures.html
- anthropics/claude-code#24162 — exact same shape as our problem: https://github.com/anthropics/claude-code/issues/24162
- jhftss — kTCCServiceSystemPolicyAppData added in macOS 14: https://jhftss.github.io/CVE-2023-42929-Why-Do-We-Need-The-App-Container-Protection/
- imlzq — App Data TCC deep dive: https://imlzq.com/apple/macos/2024/08/24/Unveiling-Mac-Security-A-Comprehensive-Exploration-of-TCC-Sandboxing-and-App-Data-TCC.html
- scriptingosx — Avoiding AppleScript security requests: https://scriptingosx.com/2020/09/avoiding-applescript-security-and-privacy-requests/
- steipete — AppleScript CLI guide (responsibility_spawnattrs_setdisclaim): https://steipete.me/posts/2025/applescript-cli-macos-complete-guide
- Qt blog — Curious case of the responsible process: https://www.qt.io/blog/the-curious-case-of-the-responsible-process
- mikebian — JXA from Python via OSAKit: https://mikebian.co/scripting-macos-with-javascript-automation/
- pyobjc-framework-OSAKit on PyPI: https://pypi.org/project/pyobjc-framework-OSAKit/
- PyInstaller Recipe-OSX-Code-Signing (deprecated banner): https://github.com/pyinstaller/pyinstaller/wiki/Recipe-OSX-Code-Signing
- PyInstaller #4413 — `CFBundleExecutable=MacOS/...` malforms bundle: https://github.com/pyinstaller/pyinstaller/issues/4413
- PyInstaller #4629 — hardened runtime crashes: https://github.com/pyinstaller/pyinstaller/issues/4629
- pyinstaller runtime info — `_PYI_PARENT_PROCESS_STARTED` env-guard for subprocesses: https://pyinstaller.org/en/stable/runtime-information.html
- Rainforest QA — TCC.db deep dive (auth_value codes, csreq): https://www.rainforestqa.com/blog/macos-tcc-db-deep-dive
- gridsync#284 — `LSUIElement` vs `LSBackgroundOnly`: https://github.com/gridsync/gridsync/issues/284
- micahrl — `.app` for launchd with AppleScript: https://me.micahrl.com/blog/applescript-app-launchd/
- Things AppleScript dictionary: https://culturedcode.com/things/support/articles/4562654/
- Things AppleScript Guide PDF: https://culturedcode.com/things/download/Things3AppleScriptGuide.pdf
