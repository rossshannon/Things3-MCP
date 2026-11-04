# Signed Local Bridge — Working on macOS Tahoe

**Date**: 2026-05-05 08:34 UTC
**Branch**: `feature/signed-local-bridge`
**Status**: Live SQLite reads working end-to-end via signed bundle

## TL;DR

The signed-local-bridge architecture works on macOS 26 Tahoe with a self-signed
Code Signing certificate. No Apple Developer ID required, no notarization
required. The path that worked:

1. Self-sign the PyInstaller `.app` with a local cert (`Things3 MCP Local`).
2. LaunchAgent plist with `AssociatedBundleIdentifiers`, `THINGS3_MCP_NO_DISCLAIM=1`.
3. Bundle Info.plist with `LSUIElement`, `NSAppleEventsUsageDescription`.
4. Reboot the Mac to clear Tahoe's TCC responsibility cache.
5. Bootstrap the LaunchAgent post-reboot from a clean shell (Warp / Terminal.app
   / iTerm — anything not running OpenClaw's Bun daemon).
6. Grant Full Disk Access to the bundle in System Settings.
7. SQLite reads succeed; cache populates with real Things data.

Verified data flow end-to-end:
- `inbox`: 39 items
- `today`: 27 items
- `anytime`: 1524 items
- `projects`: 141, `areas`: 21, `tags`: 316
- Cache file: `~/Library/Application Support/Things3-MCP/cache/latest.json` (2.9 MB)

## Dead-end attempts (documented to save future debugging)

### 1. `responsibility_spawnattrs_setdisclaim()` — broken on Tahoe

We added `src/things3_mcp_bridge/_disclaim.py` with ctypes wrappers for
`posix_spawn` + `responsibility_spawnattrs_setdisclaim` to make the worker
its own TCC responsible code regardless of parent poisoning. The function is
documented (Apple DTS forum threads, Mojave-era articles, the disclaim repo at
github.com/torarnv/disclaim) but on Tahoe it returns `EINVAL` (errno 22)
unconditionally — confirmed by a pure-C reproducer (`/tmp/disclaim_test.c`).

The module is retained but gated on `THINGS3_MCP_NO_DISCLAIM=1` (set by default
in the LaunchAgent plist). If Apple ever fixes the Tahoe regression, removing
the env var re-enables disclaim without other changes.

### 2. Broader cert trust (`security add-trusted-cert -p basic`)

`spctl --assess` rejected the bundle on Tahoe even with the cert added as a
trusted root in both user and admin domains, with `-p codeSign` and `-p basic`.
The 6–9 second `spctl` time suggested an online notarization check that
self-signed code can't pass. This was a red herring — `spctl --assess` is
distribution-policy validation, not what TCC uses for runtime attribution.
TCC matches on bundle identity / DR / csreq, which a self-signed cert satisfies
fine once the responsibility chain is clean.

### 3. Tahoe TCC responsibility caching

Before the reboot, `tcc.db` and/or `launchd` had cached "the bridge's
responsibility = Bun (OpenClaw daemon, `pid=7254`)" — confirmed by
`AUTHREQ_ATTRIBUTION` log lines showing `responsible_path=/opt/homebrew/Cellar/bun/1.3.6/bin/bun`
during every snapshot attempt. Killing the OpenClaw daemon and re-bootstrapping
the bridge was insufficient to clear this; only a full reboot wiped the cache.
Post-reboot, the bridge correctly self-attributes to its own bundle code identity,
matches the FDA grant, and reads succeed.

## What's wired up now

- `packaging/macos/com.rossshannon.things3-mcp.bridge.plist.template`
  - `AssociatedBundleIdentifiers` → `com.rossshannon.things3-mcp.bridge`
  - `THINGS3_MCP_NO_DISCLAIM=1` (so the broken disclaim path is bypassed)
- `packaging/macos/Things3 MCP Bridge.app/Contents/Info.plist.template`
  - `LSUIElement=true` (replaces `LSBackgroundOnly` so TCC prompts can surface)
  - `NSAppleEventsUsageDescription` (required for any future Apple Events use)
- `scripts/install_bridge_launchagent.sh`
  - Refuses to install if the calling shell tree contains a literal Bun runtime
    (`bun server.ts`–style invocation). Heuristic — won't catch Bun-compiled
    binaries like `claude`. Override with `THINGS3_MCP_INSTALL_FORCE=1`.
  - Uses `launchctl bootout` + `launchctl bootstrap` instead of legacy
    `unload`/`load` for cleaner re-registration.
- `src/things3_mcp_bridge/db_reader.py`
  - Worker enumerates the protected Things group container directly (it has FDA).
  - `thingscli defaults` discovery path provides a fast hint for the
    `ThingsData-XXXX` folder name without needing FDA on the calling process.
  - Stage-by-stage stderr traces (`sqlite-attempt`, `sqlite-ok`, `jxa-attempt`,
    `jxa-failed`) flow into `bridge.err.log` for diagnosis.
- `src/things3_mcp_bridge/server.py`
  - Worker stderr passes through to bridge stderr (was previously captured).
  - `THINGS3_MCP_NO_DISCLAIM` env var honored.
  - `/diagnose` endpoint exposes the worker's `diagnose_access()` output
    over the bridge socket.
- `scripts/seed_cache.py` — bypasses the bridge entirely; runs Apple Events
  directly from the calling terminal (which already has Automation grant) and
  writes a snapshot to the cache file. Useful escape hatch if the signed bridge
  ever breaks again.

## Operational rules (write these into the README)

1. **Never `launchctl bootstrap` the bridge from OpenClaw, Claude Desktop, or
   any other Bun-running daemon.** The bridge inherits Bun as its TCC
   responsible code and silently fails. Always install/reinstall from
   Terminal.app, Warp, iTerm, or another non-Bun shell.

2. **If the bridge starts silently failing (worker hangs at `sqlite-attempt`),
   check `tccd` log for `responsible_path`.** If it shows Bun or any
   non-bridge identity, you've been re-poisoned. The fix is a reboot followed
   by a fresh bootstrap.

3. **Don't enable Hardened Runtime** (`codesign --options runtime`) unless you
   also generate an entitlements file with `com.apple.security.cs.allow-jit`,
   `cs.allow-unsigned-executable-memory`, `cs.disable-library-validation`.
   Self-signed PyInstaller bundles crash under Hardened Runtime without these.

4. **Don't run `tccutil reset SystemPolicyAllFiles com.rossshannon.things3-mcp.bridge`
   casually.** It removes the bundle from FDA, requiring a re-toggle in
   System Settings. Reserve for csreq mismatch debugging.

## Validation done in this session

- `uv run --locked pytest tests/test_provider_bridge_cache.py` → 11 passed
- `uv run --locked ruff check .` → All checks passed!
- `uv run --locked ruff format --check .` → 31 files already formatted
- `uv run --locked mypy src/` → Success: no issues found in 18 source files
- Bridge `/snapshot` → `{"ok": true, "source": "live", ...}` (live SQLite read)
- Bridge `/things/inbox` → 39 items, real UUIDs and titles
- Bridge `/things/today` → 27 items, real area/tag/project metadata
- Cache file written to `~/Library/Application Support/Things3-MCP/cache/latest.json` (2.9 MB)
- TCC log during success: zero `responsible_path` entries — clean code-identity
  match against the bundle's FDA grant, no responsibility-chain walking needed

## Next steps (not blocking)

1. **Bridge writes** via Apple Events. The `NSAppleEventsUsageDescription`
   purpose string is in place; first AE call from the bridge will prompt for
   Automation grant. Then move existing AppleScript write helpers to run
   inside the bridge worker so writes are also AFK-safe.

2. **Pre-flight prompt** subcommand. `Things3-MCP-bridge --authorize-once`
   that calls `AEDeterminePermissionToAutomateTarget(..., askUserIfNeeded=True)`
   to surface the Automation prompt under the bundle's identity, before the
   first MCP call needs it.

3. **`Things3-MCP-bridge --doctor`** subcommand exposing `check_bridge.py`-like
   diagnostics with exact remediation strings (e.g. "Open System Settings →
   Privacy & Security → Full Disk Access → toggle Things3 MCP Bridge.app on").

4. **MCP tool `readOnlyHint: true`** annotations so Claude Desktop and other
   clients auto-approve read calls without per-tool prompts.

5. **Strip the disclaim module** if it's confirmed not needed for any rollback
   scenario. Until then, leaving it in place gated on the env var costs
   nothing.

## Key files touched in this PR

- `src/things3_mcp_bridge/server.py` — disclaim wiring, env-var gating, diagnose endpoint, stderr flow-through
- `src/things3_mcp_bridge/db_reader.py` — worker glob enumeration, thingscli defaults, FDA probe, stage tracing
- `src/things3_mcp_bridge/_disclaim.py` — new ctypes wrapper for posix_spawn + disclaim (currently disabled)
- `src/things3_mcp_bridge/cache.py` — unchanged
- `scripts/build_bridge_app.sh` — Info.plist patches (LSUIElement, NSAppleEventsUsageDescription)
- `scripts/sign_bridge_app.sh` — unchanged
- `scripts/install_bridge_launchagent.sh` — Bun-shell guard, bootout/bootstrap modernization
- `scripts/seed_cache.py` — new escape-hatch for cache priming
- `packaging/macos/com.rossshannon.things3-mcp.bridge.plist.template` — AssociatedBundleIdentifiers, NO_DISCLAIM env
- `packaging/macos/Things3 MCP Bridge.app/Contents/Info.plist.template` — LSUIElement, AE purpose string
- `tests/test_provider_bridge_cache.py` — updated to reflect worker-glob-allowed semantics

---

## Update — 2026-05-05 10:41 IST: Phase B (writes) + Phase C (remaining reads)

After confirming the architecture worked end-to-end for live SQLite reads, I
extended the same pattern to writes (Phase B) and the 8 read tools that were
still bypassing the provider (Phase C). All 18 MCP tools that talk to Things
now route through the same `AutoThingsProvider` chain.

### What shipped in Phase B

**Write API on the provider:**
- `WriteThingsProvider` protocol + `WriteUnsupportedError` in `providers/base.py`
- `BridgeThingsProvider.add_task` / `update_task` / `add_project` / `update_project`
  POST and PATCH over the Unix socket with the same JSON envelope as reads
- `CacheThingsProvider` raises `WriteUnsupportedError` for any write — cache
  cannot satisfy mutations and silent fallback would lose data
- `DirectThingsProvider` write methods preserved as opt-in fallback when
  `THINGS3_MCP_ALLOW_DIRECT_FALLBACK=1`. They call the existing
  `applescript_bridge` from inside the MCP server process — same as the old
  pre-bridge behaviour, so the fallback path is identical to historical
  semantics
- `AutoThingsProvider._call_write` chains bridge → optional direct, **never
  cache**. Writes that can't reach Things must surface as errors.

**Bridge HTTP write endpoints:**
- `POST /things/todo` → `run_worker("add_task", body)`
- `PATCH /things/todo/{uuid}` → `run_worker("update_task", body+uuid)`
- `POST /things/project` → `run_worker("add_project", body)`
- `PATCH /things/project/{uuid}` → `run_worker("update_project", body+uuid)`
- New `do_PATCH` HTTP handler with auth + body parsing
- `_run_write` helper deliberately omits cache fallback

**Worker write dispatch in `db_reader.py`:**
- `WRITE_ACTIONS = {"add_task", "update_task", "add_project", "update_project"}`
- `run_write_action()` lazily imports `applescript_bridge` and dispatches
- `_coerce_write_result()` normalises legacy AppleScript return values
  (UUID strings, `"true"`, `False`, `"Error: …"` markers) into clean envelopes
- `run_action()` recognises write actions before the SQLite/JXA branches
- Stage tracing `[worker:PID] write-attempt {action}` → `write-ok` / `write-failed`

**MCP routing:**
- `fast_server.add_task`, `add_new_project`, `update_task`, `update_existing_project`
  now call `get_provider().add_task(...)` etc. instead of importing
  `applescript_bridge` directly. Removed unused imports.

### What shipped in Phase C

**Two new methods on `ThingsProvider`:**
- `trash(include_items)` — wraps `things.trash()`
- `last(period, include_items)` — wraps `things.last(period)`

These were the only things-py top-level functions not already covered by the
existing protocol; everything else fits `tasks(**kwargs)` or `todos(**kwargs)`.

**New bridge endpoints:**
- `GET /things/trash`
- `GET /things/last/{period}` — period segment lifted from URL path

**Worker dispatcher (`run_sqlite_action`)** handles `trash` and `last`
explicitly because their kwargs shapes differ from the other read actions.

**MCP routing for the 8 lifted tools:**
- `get_logbook` → `provider.tasks(status="completed", stop_date=…)`
- `get_trash` → `provider.trash()`
- `get_todos` → `provider.todos(project=…)` and `provider.get(uuid)`
- `get_random_todos` → same, plus `_sample_items`
- `get_tagged_items` → `provider.todos(tag=…)`
- `search_advanced` → `provider.todos(**filters)`
- `search_all_items` → `provider.search(query)`
- `get_recent` → `provider.last(period)`

All catch `ProviderError` and route through `_provider_error_response`. All
use `_format_todo_items(todos, provider)` for output.

### New tests added

| Phase | Count | Coverage |
|---|---|---|
| B | 9 | Bridge HTTP write client, cache refusal, auto-provider write chain, worker write dispatch, applescript-bridge return-value coercion |
| C | 16 | All 8 lifted MCP tools route through provider, period validation, provider write/read protocol surface for `trash`/`last`, worker dispatch for `trash`/`last`, cache empty-list semantics |

Total: **36 unit tests passing** (was 11).

### End-to-end smoke tests done in this session

All against the user's real Things database:

| Operation | Endpoint | Result |
|---|---|---|
| Create todo | `POST /things/todo` | new UUID `Ua8DgKsHcWJGUwQrYSQcNk` |
| Read it back | `GET /things/get/{uuid}` | SQLite returned correct title/notes |
| Update title + notes | `PATCH /things/todo/{uuid}` | `{"ok": true}` |
| Cancel | `PATCH /things/todo/{uuid}` `{"canceled":true}` | `{"ok": true}` |
| List trash | `GET /things/trash` | Real trashed items returned |
| Recent items | `GET /things/last/7d` | Real recent activity returned |
| Live snapshot | `POST /snapshot` | 39 inbox / 27 today / 1524 anytime / 141 projects |

Worker traces showed every operation flowing as `write-attempt` → `write-ok`
or `sqlite-attempt` → `sqlite-ok`. No TCC prompts were needed for writes
because Automation had already been granted to the bundle from earlier JXA
testing in this session.

### Updated lessons learned

7. **`spctl --assess` rejection is not the same as TCC denial.** Apple DTS
   warns that spctl is a distribution-policy check (notarization, Developer
   ID), not the runtime trust evaluation TCC actually uses. Self-signed code
   that spctl rejects can still pass TCC csreq matching just fine. We chased
   this red herring for an hour before pivoting.

8. **`responsibility_spawnattrs_setdisclaim` is broken on Tahoe.** A pure-C
   reproducer (`/tmp/disclaim_test.c`) confirms `EINVAL` even with the
   correct calling convention (`posix_spawnattr_t` by value, not by
   pointer). The dead-end is preserved in `_disclaim.py` and gated off via
   `THINGS3_MCP_NO_DISCLAIM=1` in the LaunchAgent plist.

9. **macOS Tahoe (26+) caches per-bundle-ID launchd responsibility.** The
   bridge was originally bootstrapped from an OpenClaw (Bun) context, which
   stamped its responsibility chain. Killing OpenClaw and re-bootstrapping
   was insufficient — the cache survived. Only a reboot cleared it. After
   reboot, the bridge auto-loaded with a clean responsibility chain and has
   stayed clean across re-installs from various shells.

10. **Reboot was the actual fix, not Developer ID.** We had a strong
    hypothesis that self-signed code couldn't get FDA on Tahoe and were
    about to recommend $99/yr Developer ID. The empirical evidence said
    otherwise once we cleared the responsibility cache.

11. **Writes intentionally don't cache-fall-back.** `AutoThingsProvider`'s
    write chain is `bridge → optional direct`, never cache. Silent fallback
    to a stale cache for mutations would lose data — clear `ProviderError`
    surfacing is correct.

12. **`spctl --assess` takes 6–9 seconds because it's making a network call.**
    Likely OCSP / CRL revocation against Apple's servers. Useful timing
    fingerprint for diagnosing whether it's hitting the network vs failing
    locally.

### Validation in this update

```
uv run --locked pytest tests/test_provider_bridge_cache.py  → 36 passed
uv run --locked ruff check .                                 → All checks passed!
uv run --locked ruff format --check .                        → 31 files already formatted
uv run --locked mypy src/                                    → no issues found in 18 source files
pre-commit hooks (ruff/format/mypy/bandit/whitespace/eof)    → all passed
```

### Commits added in this session

| Commit | Scope |
|---|---|
| `e4ed992` | Add bridge write API and resolve Tahoe TCC attribution |
| `63443e8` | Route remaining 8 read tools through the bridge provider |

### Final state

Every TCC-protected Things operation in the MCP server now flows through
`com.rossshannon.things3-mcp.bridge` — the single signed bundle that holds
FDA + Automation grants. Whatever transient runtime hosts the MCP server
(Claude Desktop, OpenClaw, terminal-launched, Codex), it inherits no
responsibility for Things data access; the bridge does the work under its
stable identity.

| Layer | Tools | Routed through bridge |
|---|---|---|
| MCP read tools | 19 | 19/19 ✓ |
| MCP write tools | 4 | 4/4 ✓ |
| Bridge endpoints | 17 (GET + POST + PATCH) | live + cache fallback (reads only) |
| Provider chain | bridge → cache (reads) / bridge → direct (writes) | yes |

### Architectural seam: cache fallback masks validation errors

While turning the integration suite green, `test_search_advanced_empty_results`
exposed a subtle interaction between `live_or_cache` and parameter validation
in things-py.

**The seam:**

1. `provider.todos(tag="travl")` (typo for "travel") goes through the bridge.
2. The live worker calls `things.todos(tag="travl")`, which raises
   `ValueError: Unrecognized tag type: 'travl'\nValid tag types are [...]`.
3. The worker catches the exception, falls through to JXA fallback (which
   doesn't implement `todos`), then returns
   `{"ok": false, "error_code": "things_db_unreadable", "message": "<details>"}`.
4. `live_or_cache` sees the live failure and tries the cache provider.
5. `CacheThingsProvider.todos(tag="travl")` iterates the cached snapshot,
   filtering by tag. No items match → returns `[]`.
6. `live_or_cache` returns `{"ok": true, "source": "cache", "data": [],
   "live_error": {<the original ValueError>}}`.
7. `BridgeThingsProvider.todos` sees `ok=true` → returns `[]`.
8. `fast_server` formats `[]` as "No items found with tag 'travl'" — user
   sees a *no-results* outcome instead of a *validation error*.

The information is not lost — `live_error` carries the original message — but
the MCP-tool layer doesn't surface it. The user's typo gets silently
swallowed.

**Audit of where this can bite:**

| Provider call site | Things-py behaviour | Vulnerable? |
|---|---|---|
| `tasks(status="completed", stop_date=…)` in `get_logbook` | status is hardcoded valid | safe |
| `trash()` in `get_trash` | no parameters | safe |
| `todos(project=…)` in `get_todos`, `get_random_todos` | no validation (returns `[]`); `fast_server` pre-validates the UUID anyway | safe |
| **`todos(tag=tag)` in `get_tagged_items`** | raises `ValueError` for unknown tags | **vulnerable** |
| `search(query)` in `search_todos`, `search_all_items` | no validation | safe |
| **`todos(**kwargs)` in `search_advanced`** | raises `ValueError` for unknown `status`/`tag`/`start`/`type` | **vulnerable** (test now pinned to direct provider) |
| `last(period)` in `get_recent` | pre-validated in `fast_server` | safe |
| `get(uuid)` everywhere | returns `None` for unknown | safe |

Empirical map of which things-py kwargs raise vs return empty:
- **Raise `ValueError`**: `tag`, `status`, `start`, `type`, `last("period")`.
- **Return empty list**: `project=<uuid>`, `area=<uuid>`, `get(uuid)`,
  `search(query)`.

**Mitigation options (none implemented yet — out of scope for this PR):**

1. **Worker error-code distinction** — emit `things_validation_error` for
   `ValueError`/`TypeError` from things-py, vs `things_db_unreadable` for
   transient runtime issues. `live_or_cache` would skip cache fallback for
   validation errors and propagate them as ProviderError.
2. **Pre-validation in fast_server** — `get_tagged_items` could call
   `provider.tags()` first and check membership before calling `todos(tag=…)`.
   Same idea for `search_advanced`'s `status`/`tag`/`start`/`type`. Adds a
   round-trip but surfaces typos cleanly.
3. **Surface `live_error` in BridgeThingsProvider** — when the bridge
   response includes `live_error`, log a warning and optionally append
   "(live attempt failed: <message>)" to the result. Visible to the user but
   doesn't change the overall response shape.

For the current PR, only `search_advanced` is covered (the test pins
`THINGS3_MCP_PROVIDER=direct` so it exercises the strict path). `get_tagged_items`
inherits the seam: a typo'd tag with a populated cache returns "No items
found with tag 'travl'" instead of a tag-validation error. Documented as a
known limitation; option 1 above is the right architectural fix when there's
appetite for it.

### Updated next steps (still non-blocking)

1. **`Things3-MCP-bridge --authorize-once` preflight** — call
   `AEDeterminePermissionToAutomateTarget(..., askUserIfNeeded=True)` so the
   first-time Automation prompt happens explicitly rather than on the first
   write attempt. Still relevant; not done.
2. **`--doctor` subcommand** — wrap `check_bridge.py` with exact-remediation
   strings (settings paths, `tccutil reset` commands, `launchctl bootout`
   guidance). Still relevant; not done.
3. **`readOnlyHint: true` MCP annotations** — auto-approval in Claude Desktop
   for the 19 read tools. Still relevant; not done.
4. **`_disclaim.py` removed** — done in the review-fix commit (`9eba9c5`).
   The C reproducer confirmed Tahoe rejects the API; gated dead code wasn't
   earning its keep. Session note retains the trail in case Apple ever
   un-breaks it.
5. **Mark integration tests with `@pytest.mark.integration`** — the ~70
   tests that modify real Things data should be opt-in via `pytest -m
   integration`. Currently they run by default, which we deliberately avoid.
6. **Distinguish validation errors from transient errors in the worker** —
   see the "Architectural seam" section. Have the worker emit
   `things_validation_error` for `ValueError`/`TypeError` from things-py
   (unknown tag, status, start, type, malformed last-period); have
   `live_or_cache` skip cache fallback for that error code so typos surface
   to the user instead of being masked as "no results". Affects
   `get_tagged_items` and `search_advanced` directly; cleanest single fix
   for both.
7. **Cleanup**: the smoke-test todo `bridge-write-smoke-test (updated, delete
   me)` (UUID `Ua8DgKsHcWJGUwQrYSQcNk`) is marked canceled in your Things
   logbook. Empty trash to remove permanently.

### Update - 2026-05-05 12:51 IST: README Refresh and Snapshot Verification Fix

Follow-up after the branch review found one documentation drift and one
diagnostic false-positive:

- `README.md` now describes the current write routing accurately: write tools
  use the bridge first, never fall back to cache, and only use direct
  AppleScript as the `auto` compatibility fallback when the bridge is
  unavailable.
- The provider-mode section now distinguishes read fallback
  (`bridge -> cache -> optional direct`) from write fallback
  (`bridge -> direct`).
- The `THINGS3_MCP_DATA_FOLDER` troubleshooting text now matches the actual
  worker behaviour: the authorised bridge worker can enumerate the Things group
  container, but a folder hint is still useful when TCC attribution or multiple
  data folders make discovery unreliable.
- `scripts/check_bridge.py --snapshot` no longer exits 0 when the bridge socket
  or token is missing. It records a `snapshot_error`, marks the live snapshot as
  not attempted, and exits non-zero.
- Added a unit regression test in `tests/test_provider_bridge_cache.py` for the
  missing socket/token `--snapshot` case.

### Update - 2026-05-05 13:09 IST: Direct Fallback Timeout Clarification

Ross asked whether `THINGS3_MCP_ALLOW_DIRECT_FALLBACK=1` is protected by the
same timeout boundaries as the bridge. The answer is no:

- Bridge reads/writes go through the HTTP client timeout and the bridge's
  killable worker subprocess timeout.
- Direct read fallback still calls the legacy `things-py` path inside the MCP
  process. That matches pre-bridge read behaviour and is not safely killable if
  macOS TCC queues the access behind an unanswered prompt.
- Pre-bridge AppleScript writes did have the existing `run_applescript`
  subprocess timeout, but the direct `things-py` read calls did not.

Documentation now says this explicitly in the provider-mode section.

Also fixed the earlier `get_recent` formatter bypass: project items now pass
`get_item=provider.get` into `format_project`, so a project-area lookup stays on
the selected provider instead of falling back to raw `things.get()`.

### Update - 2026-05-05 13:18 IST: Bridge Lifecycle Clarification

Clarified in `README.md` that the LaunchAgent starts the bridge immediately on
install and again at user login after reboot because the plist has `RunAtLoad`
and `KeepAlive`. The MCP client does not lazily launch the bridge; it only
connects to the existing socket. The long-running bridge process creates the
token/socket and waits; protected Things access only begins when a live
snapshot/read/diagnose/write endpoint spawns the timeout-bounded worker.

### Update - 2026-05-05 13:31 IST: Trash Paging Fix

OpenClaw found a live-data AFK failure: Ross's Trash has roughly 3,891 items.
The raw bridge endpoint returned live data, but MCP `get_trash` then timed out
while formatting and enriching the full list, fanning out into many
`/things/get/...` calls.

Fixed `get_trash` as a bounded list view:

- Default `limit=50`, hard cap `MAX_TRASH_LIMIT=200`, and `offset` paging.
- Requests `provider.trash(include_items=False)` to keep the raw payload light.
- Formats Trash items without project/area enrichment, so a page does not
  trigger per-item provider lookups.
- README now documents the paging behaviour.

### Update - 2026-05-05 13:45 IST: New User Bridge Setup Instructions

Ross asked whether the README gives a new source user enough information to
build, sign, install, and authorise the bridge. It already had the core flow,
but the setup section now makes the assumptions explicit:

- Prerequisites: macOS, Things 3, `uv`, and a source checkout.
- Build output: `build/macos/Things3 MCP Bridge.app`.
- Install behaviour: copies the signed bundle to `~/Applications`, writes the
  LaunchAgent, and bootstraps it.
- Warning to run the install step from a normal terminal rather than a
  Bun-rooted Claude/OpenClaw shell because Tahoe can misattribute TCC
  responsibility.
- Separate Automation instructions for first write approval, because Full Disk
  Access only covers live reads/cache snapshots.

### Update - 2026-05-05 14:10 IST: Bridge Security Trade-Off Documentation

Ross clarified the product intent after the security review: the bridge should
remain an explicit trade-off that users enter with their eyes open. It should
not be documented as "local therefore safe" or as a blanket security
improvement over direct access. The correct framing is:

- The bridge improves reliability by giving macOS a stable local app identity
  for Full Disk Access and Automation.
- That concentrates trust in a per-user local service that can exercise those
  grants through a Unix socket and bearer token.
- Owner-only token/socket/cache permissions protect against other Unix users,
  but they are not a sandbox boundary against unsandboxed processes running as
  the same macOS user.
- Self-signing is a local supply-chain trust decision, not notarisation or
  third-party provenance.

Changes made:

- Added `docs/security/local-bridge-security.md` with the threat model, assets,
  trust boundaries, self-signing side effects, main risks, mitigations, safer
  operating modes, and "when not to enable the bridge" guidance.
- Added a concise `README.md` "Security Model and Trade-Offs" section in the
  bridge setup flow, linking to the detailed security note.
- Added warnings to `scripts/sign_bridge_app.sh` and
  `scripts/install_bridge_launchagent.sh` so the trade-off is visible during
  signing and before granting macOS privacy access.

### Update - 2026-05-05 14:22 IST: Self-Signed Bundle Mutation Caveat

Ross asked the important follow-up: since the bridge is "just Python code",
could an attacker give it Full Disk Access and then change the Python being
executed?

Clarified the nuance in the docs:

- Simple post-signing edits to the app bundle should break the code signature,
  and macOS privacy grants are tied to code identity rather than just a path.
- The sharper risk is a same-user attacker who can use the same local signing
  identity/private key to modify and re-sign the bundle, or who can steer the
  signed bridge into running attacker-controlled external helpers.
- The simpler same-user attack remains reading the bridge token and calling the
  legitimate bridge.

Updated `README.md`, `docs/security/local-bridge-security.md`,
`scripts/sign_bridge_app.sh`, and `scripts/install_bridge_launchagent.sh` to
call out the signing-key caveat explicitly. Added Apple code-signing references
to the security doc.

### Update - 2026-05-05 17:33 IST: Bridge App Icon

Added a branded macOS icon to the bridge app so the installed bundle is less of
a generic PyInstaller/developer-mode artefact in Finder/System Settings.

Changes made:

- Added `packaging/macos/Things3MCPBridge.icns`, generated from the existing
  `docs/images/Things3-MCP-logo.png` logo as a square macOS ICNS asset.
- Updated `scripts/build_bridge_app.sh` to require the icon asset, pass it to
  PyInstaller with `--icon`, copy it into `Contents/Resources`, and set
  `CFBundleIconFile=Things3MCPBridge.icns`.
- Updated `packaging/macos/Things3 MCP Bridge.app/Contents/Info.plist.template`
  with the same `CFBundleIconFile` value.

Verification:

- `file packaging/macos/Things3MCPBridge.icns` reports a macOS icon with PNG
  chunks.
- `iconutil --convert iconset ... packaging/macos/Things3MCPBridge.icns`
  succeeds, confirming macOS can parse the asset.
- `scripts/build_bridge_app.sh` rebuilt the app bundle successfully.
- The built `Info.plist` reports `CFBundleIconFile=Things3MCPBridge.icns`.
- The built app contains
  `Contents/Resources/Things3MCPBridge.icns`.
- `build/macos/Things3 MCP Bridge.app/Contents/MacOS/Things3 MCP Bridge --health`
  returned bridge/cache status without touching live Things data.

### Update - 2026-05-06 08:16 IST: Clawbridge Things Icon Rebuild

Ross supplied `~/Downloads/clawbridge-things.png` as the bridge app artwork.
Replaced the generated `packaging/macos/Things3MCPBridge.icns` asset with an
ICNS built from that square PNG, keeping the same bundle resource name so the
existing build script and plist changes continue to apply cleanly.

Rebuilt `build/macos/Things3 MCP Bridge.app` with `scripts/build_bridge_app.sh`.
The rebuilt bundle now embeds the refreshed `Things3MCPBridge.icns` resource and
sets `CFBundleIconFile=Things3MCPBridge.icns`.

Verification:

- `iconutil --convert iconset ... packaging/macos/Things3MCPBridge.icns`
  succeeds and extracts 7 icon sizes.
- `bash -n scripts/build_bridge_app.sh` passes.
- `scripts/build_bridge_app.sh` rebuilt the app bundle successfully.
- The rebuilt app contains
  `Contents/Resources/Things3MCPBridge.icns`.
- `build/macos/Things3 MCP Bridge.app/Contents/MacOS/Things3 MCP Bridge --health`
  returned `ok: true`.

### Update - 2026-05-06 09:55 IST: Streaks-Style Icon Packaging and Skill

Ross pointed out that the Streaks bridge app in
`/Users/ross/Development/Streaks-Agent-Scripts` already had a working icon for
the same PyInstaller bridge pattern. The durable fix was to mirror that approach
instead of continuing to debug `iconutil`/LaunchServices behaviour in isolation.

Changes made:

- Regenerated `packaging/macos/Things3MCPBridge.icns` with the same PNG-backed
  ICNS chunk pattern used by Streaks (`icp4`, `icp5`, `icp6`, `ic07`, `ic08`,
  `ic09`, `ic10`).
- Updated `scripts/build_bridge_app.sh` to define `PLIST_TEMPLATE` and copy the
  checked-in plist template over PyInstaller's generated `Info.plist`, matching
  the Streaks build script shape.
- Updated
  `packaging/macos/Things3 MCP Bridge.app/Contents/Info.plist.template` so
  `CFBundleExecutable` is `Things3 MCP Bridge` and `CFBundleIconFile` is the
  basename `Things3MCPBridge`.
- Rebuilt, re-signed, reinstalled, and restarted the installed bridge app.
- Created the reusable skill
  `/Users/ross/AI/ross-system-prompts/.claude/skills/pyinstaller-macos-app-icons`
  with a helper script for generating the Streaks-style ICNS file.

Verification:

- `scripts/build_bridge_app.sh` rebuilt the app successfully.
- `scripts/sign_bridge_app.sh --identity "Things3 MCP Local"` signed the rebuilt
  bundle and `codesign --verify --deep --strict --verbose=2` passed.
- `scripts/install_bridge_launchagent.sh` installed and bootstrapped the
  LaunchAgent successfully after the Streaks-style packaging change.
- Installed plist reports `CFBundleExecutable=Things3 MCP Bridge` and
  `CFBundleIconFile=Things3MCPBridge`.
- Installed icon resource reports a macOS icon beginning with `icp4`.
- `uv run --locked python scripts/check_bridge.py --snapshot --timeout 60`
  succeeded through the installed bridge and refreshed the live cache at
  `2026-05-06T08:51:06.191525+00:00`.
- `pyinstaller-macos-app-icons` passed `quick_validate.py`, and its
  `scripts/make_icns.py` helper successfully generated and inspected a test
  ICNS from `~/Downloads/clawbridge-things.png`.

### Update - 2026-05-06 10:05 IST: Bridge Pathway Validation

Validated the installed, signed bridge pathways after the icon/re-sign/reinstall
work and Ross's latest whitelisting pass.

Runtime checks:

- `uv run --locked python scripts/check_bridge.py --timeout 5` reported the
  installed bridge running, socket reachable, token file present, non-ad-hoc
  code signature, and readable live cache.
- `launchctl print gui/$(id -u)/com.rossshannon.things3-mcp.bridge` showed the
  LaunchAgent running `/Users/ross/Applications/Things3 MCP Bridge.app`.
- `codesign -dv --verbose=4 "$HOME/Applications/Things3 MCP Bridge.app"`
  reported authority `Things3 MCP Local` and identifier
  `com.rossshannon.things3-mcp.bridge`.
- Installed `Info.plist` reports `CFBundleIconFile=Things3MCPBridge`, matching
  the working Streaks-style packaging.
- `uv run --locked python scripts/check_bridge.py --snapshot --timeout 60`
  succeeded through the installed bridge and refreshed the cache at
  `2026-05-06T08:59:36.902999+00:00`.

Provider and MCP-surface checks:

- `THINGS3_MCP_PROVIDER=bridge` read inbox, today, upcoming, anytime, someday,
  todos, projects, areas, tags, and search successfully through the bridge.
- `THINGS3_MCP_PROVIDER=cache` returned matching read counts from the JSON cache
  and refused `add_task` with `writes_unsupported`.
- `THINGS3_MCP_PROVIDER=auto` returned matching read counts with direct fallback
  disabled.
- Forced auto fallback with `THINGS3_MCP_BRIDGE_SOCKET=/tmp/things3-mcp-missing-bridge.sock`
  served inbox/today/projects from cache, proving the bridge-down cache pathway.
- MCP-facing functions `get_inbox`, `get_today`, `get_projects`, `get_areas`,
  `get_tags`, and `search_todos` passed under bridge, cache, and forced
  auto-cache-fallback modes. Bridge-only `get_trash(limit=5)` and
  `get_recent("1d")` also passed.
- Bridge HTTP `/diagnose` through the running LaunchAgent sees Full Disk Access
  and the Things database. Running the bundled executable directly from
  Terminal with `--worker-action diagnose` does not see the same FDA grant, so
  permission-sensitive validation should go through the installed LaunchAgent
  route.
- `THINGS3_MCP_PROVIDER=direct` failed in this environment with
  `sqlite3.OperationalError: unable to open database file`, matching the known
  TCC-fragility of the legacy direct read path.

Automated tests:

- Initial `uv run --locked pytest tests/test_provider_bridge_cache.py -q`
  failed before tests ran because the global test fixture's AppleScript
  readiness probe returned macOS error `-10827`.
- Re-running with `THINGS3_MCP_SKIP_THINGS_TEST_SETUP=1` inside the sandbox gave
  `33 passed, 16 failed`; all 16 failures were `PermissionError` opening
  `/Users/ross/.things-mcp/logs/things3_mcp_structured.json` during
  `fast_server` import.
- Re-running the same focused suite outside the sandbox with
  `THINGS3_MCP_SKIP_THINGS_TEST_SETUP=1` passed: `49 passed in 0.44s`.

Not run:

- The Automation write pathway was not exercised because it requires creating or
  updating a real Things item. Use a deliberately named test todo/project if
  Ross approves a mutating validation pass.
