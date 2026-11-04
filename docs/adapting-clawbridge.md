# Adapting ClawBridge to another Mac app

ClawBridge routes app-specific MCP tools to a small signed macOS app for fixed app operations. An authorised client sends structured requests over a Unix socket; the signed app owns the macOS permissions and executes a bounded worker. The MCP process does not automatically gain those permissions. Things3-MCP 2.5 uses this core, and the synthetic adapter demonstrates it without Things or private data.

The bridge work began in May 2026 to make local app actions reliable while the user was away. Computer use in clients such as Codex and Grok Bot is useful for interfaces that require visual interaction. Repeated app operations benefit from structured parameters, testable results and explicit permission ownership. The bridge supplies that execution layer; it does not supply a remote control service or replace a client's security policy.

Here, “away” means an awake Mac with the user logged in after interactive consent. A locked screen is a distinct state to test. Sleep, logout, FileVault preboot and unattended approval of new permission prompts are outside this contract.

## Export the reference

From a reviewed Things3-MCP checkout:

```sh
.venv/bin/python scripts/export_clawbridge.py /ABSOLUTE/PATH/TO/EMPTY/clawbridge-reference
```

The destination must be absent or empty. The exporter rejects source symlinks and destination symlinks, copies only its explicit allowlist and writes `export-manifest.json`. Unknown files, `.env`, caches, builds, personal fixtures, the Things packages and the source README are excluded. The generic core is copied byte for byte; the synthetic configuration becomes `packaging/macos/bridge.toml`. The standalone package uses the generated `REFERENCE.md` as its readme. Follow that file for setup and a synthetic request.

The manifest has a source revision and per-file source paths, hashes and modes. `source_dirty=true` means the export includes uncommitted allowed inputs; retain the files as well as the revision. Verify hashes before comparison or downstream packaging. This is provenance, not a digital signature or proof of a trusted origin. Re-export to another empty directory and review the difference when updating; do not maintain a second hand-edited copy of the shared core.

## Define an adapter

The standalone `clawbridge-mcp` server provides fixed `counter`, `music` and `catalogue` profiles over stdio. Follow the exported `REFERENCE.md` for client configuration, including SSH. Define an app-specific tool mapping for another app; never accept a caller-selected command, script, app, path, executable or SQL.

Choose [the closest small example](examples/README.md): counter state, Music scripting or a read-only SQLite catalogue. Start from `src/clawbridge/demo.py` for the smallest adapter:

| Part | Responsibility |
| --- | --- |
| [`src/clawbridge_mcp/server.py`](../src/clawbridge_mcp/server.py) | Define fixed MCP tool names, schemas, read-only hints and route mappings. Edit and review this source when adding an app; it is not a dynamic plugin interface. |
| `ACTIONS` | Fixed names, parameter types, required fields and whether each action mutates state. |
| Request handler `resolve()` | Map fixed method/path pairs to those actions; reject unsupported routes and query parameters. |
| `execute()` | Perform one app operation and return structured data. Keep app discovery, script construction and data conversion here. |
| `run_worker()` / `worker_main()` | Run a bounded child; the frozen build respawns its own executable. |
| `create_server()` | Bind the private socket, token, adapter and operation journal. |
| `packaging/macos/bridge.toml` | Declare a unique app name, bundle identifier, fixed entrypoint, runtime paths and permission targets. |

Set `mutation=True` for any action that can change app state. Validate its full input before execution. Never expose a caller-selected Python module, shell command, script body, executable path, bundle identifier or filesystem path. New actions are source changes to review and rebuild, not plugins loaded on demand. Use fixed absolute system helper paths where a native helper is needed.

Keep app-specific libraries out of `clawbridge`; add them only to your adapter's package dependencies and lockfile. Give the adapter synthetic fixtures and a test for rejection before dispatch, successful reads/writes, timeouts, process-tree termination, malformed worker responses and uncertain outcomes. Do not import real app data into tests.

## Choose capabilities separately

| Capability | Permission and design choice |
| --- | --- |
| App scripting | Prefer the app's supported Apple Events dictionary. Name the target bundle identifier and supply an accurate usage description. The user still grants Automation consent. |
| Database reads | Treat filesystem privacy, App Sandbox and database correctness as separate checks. Prefer supported app APIs or explicit exports before reading an undocumented live database. Never add database writes as a convenience. |
| Cache | Store only the intended data in private app state. Report source, snapshot time and age. A cache is not live evidence. |
| GUI automation | A separate capability with different risks and consent. Supported Things scripting does not need Accessibility, Screen Recording or System Events. Do not add them to this reference. |

A code allowlist controls the operations exposed by this service. It does not confine compromised native or Python code. The default build is unsandboxed; Full Disk Access is broad. An explicit signed App Sandbox profile can restrict filesystem access even when Full Disk Access is also granted. Those are separate macOS checks. [Apple DTS explains their interaction](https://developer.apple.com/forums/thread/807142).

Use `sandbox_read_only_home` for the smallest supported read-only app directory. Where an app declares scripting access groups, use `scripting_targets` to name the required groups; the Music example uses only `com.apple.Music.playback`. Otherwise, `apple_event_targets` declares specific applications. Whole-target restrictions do not enforce create-only or read-only verbs inside that app; that policy remains in the adapter. Scripting groups constrain only the capabilities the target places in those groups, and Automation consent remains separate. See [Apple's entitlement reference](https://developer.apple.com/library/archive/documentation/Miscellaneous/Reference/EntitlementKeyReference/Chapters/AppSandboxTemporaryExceptionEntitlements.html).

User-selected files and security-scoped bookmarks are an option to investigate, not an automatic bypass for another app's protected container. The reference does not implement a picker or bookmark lifecycle. Validate the actual target path, worker and restart behaviour before claiming that this avoids Full Disk Access. [Apple documents the separate file-access constraints](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox).

## Client contract and uncertain writes

The only listener is a local Unix socket. Its token is a local bearer credential, shared by authorised callers; there is no per-client identity or OAuth. A remote bot must use an independently secured connection to its local client. Do not forward the privileged socket or turn this service into a public HTTP listener.

`GET /health` reveals minimal liveness without authentication. Authenticated `/status` reports identity and observations; it does not grant permissions. `/operations/<operation_id>` inspects one mutation. `/operations?correlation_id=example&limit=25` lists recent records, with a limit from 1 to 100. `X-Correlation-ID` accepts 1–128 ASCII characters from `A–Z`, `a–z`, `0–9`, `.`, `_`, `:`, `-`. It is caller attribution, not authentication or an idempotency key.

Each mutation receives a distinct operation ID. Outcomes distinguish `not_started`, `succeeded`, `failed` and `outcome_unknown`. A worker can mutate the app before its response is lost or its deadline expires. After an unknown outcome, inspect the operation record and app state before making a deliberate new request. The service never replays stored requests and does not retry via another provider. Report `failed` only when the adapter can establish failure; do not turn ambiguous exceptions into a claim that nothing happened.

The journal is `operations/` beside the socket. It defaults to metadata only, seven days, 1,000 records and 10 MiB. Retention runs on access or admission, not a background deletion timer. Capacity pressure prunes the oldest inactive records; active records are retained. If admission cannot fit a durable record, execution is rejected before dispatch. `CLAWBRIDGE_JOURNAL_PAYLOADS=1` opts the synthetic server into retaining request payloads; Things uses `THINGS3_MCP_BRIDGE_JOURNAL_PAYLOADS=1`. Set these in the server's process environment, not the MCP client's. Supplying the matching variable as `1` when running `scripts/install_bridge_launchagent.sh` persists that opt-in in the installed LaunchAgent; `0` disables new payload capture on a later install without erasing old records. `.env.example` documents names but is not loaded automatically. Lists omit payloads; a single-record lookup can return them when capture was enabled. Keep tokens, titles and notes out of ordinary logs.

For Things reads, `X-Require-Live: true` rejects cache fallback. Read output identifies SQLite, limited Apple Events, direct or cached results and preserves the original backend and snapshot age. Do not present a limited scripting snapshot as a complete database snapshot. The synthetic adapter has no cache and no protected database.

## Build evidence and runtime evidence

Follow [the build guide](bridge-build.md) for locked fresh build environments, local signing, Developer ID distribution, experimental sandboxing, and explicit install/rollback steps. Keep signing keys in Keychain. Building and signing do not install the app or change privacy grants.

Record these results separately:

- Source tests: fixed routes, validation, worker deadlines, journal retention and rollback fixtures.
- Build and signature: exact revision and input hashes, lockfile, Python/tool versions, architecture, entitlements, signer and final bundle hashes.
- Synthetic sandbox: allowed read/state write; denied read-only write, private sibling and symlink access in both parent and worker; real client/socket connection without unnecessary network entitlements.
- Real application: supported reads/writes and the app identity receiving each consent decision. Inspect actual returned data, not just a running process.
- Away operation: exact signed candidate, awake/logged-in/locked state, existing grants, restart and read/create/update results.

A native synthetic experiment demonstrated filesystem denials in the parent and child and Unix IPC inside its own sandbox container without network entitlements. The same socket failed in an external state directory despite a filesystem exception. A separate signed synthetic PyInstaller build passed the frozen worker, authentication, counter mutation, journal and external Unix-client checks in its own container. Neither experiment establishes Things access, Full Disk Access interaction, fresh-client consent or locked-session behaviour. The experimental packaging profile uses the app container and checks the socket pathname limit; validate your exact frozen candidate before adoption.

The reference deliberately omits public HTTP/OAuth, per-bot credentials, arbitrary plugins/scripts, automatic replay, database writes and a FastMCP major upgrade. Add a separate design and evidence before expanding those boundaries.
