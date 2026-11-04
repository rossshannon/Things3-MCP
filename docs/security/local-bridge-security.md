# Local bridge security model

The standalone MCP profiles use the authenticated owner-private socket boundary. Operator configuration selects the profile and absolute socket and token-file paths; clients cannot choose commands, scripts, apps, paths, SQL or executables. The token stays on the Mac and its value is not a command argument. SSH can carry MCP stdio, but adds neither per-bot authorisation nor a public network listener. The MCP process gains no automatic macOS permissions. Treat operation lookup responses as private when retained payloads are enabled.

The bridge gives macOS one signed app identity to authorise and lets local clients request a fixed set of app operations. It improves permission ownership and failure handling. It does not isolate all programs running as the same user, and signing alone does not confine filesystem access.

## Authority and trust

```text
MCP client → Things3-MCP server → Unix socket + bearer token
  → signed bridge → bounded app worker
    → Things database reads / Things Apple Events
    → private cache and operation journal
```

The runtime directory is owner-only; tokens, sockets and private data files use restrictive modes. This blocks access by other Unix users. An unsandboxed process running as the same user may still read the token/cache, call the bridge or alter user-writable files. Token possession authorises the fixed routes. A correlation label is attribution, not a separate identity. There are no per-bot credentials.

The bridge has no TCP listener or public HTTP endpoint. Its authentication does not make it safe to forward the socket to untrusted callers. Remote access belongs in a separately secured client transport. A compromised or prompt-injected authorised client can request the legitimate operations; keep client tool permissions appropriate to the intended use.

The protected assets include app data and mutations, cached task contents, operation metadata, optional payload records, the bearer token, installed bundle and signing key.

## Database access and scripting are separate

| Capability | Authority and limits |
| --- | --- |
| Live SQLite reads | May require Full Disk Access to reach the protected Things group container. Readers open the database read-only; there are no direct database writes. This does not confine the whole process. |
| Apple Events | Automation consent lets the signed bridge control Things. Supported scripting does not require System Events, Accessibility or Screen Recording. |
| Cache | A private copy outside the original app container. Its timestamp, age and original backend must remain visible; it may be stale or have limited scripting coverage. |
| Synthetic adapter | Only echoes text and reads/writes its own counter. It needs no Things dependency or privacy grant. |

Cultured Code supports its automation interfaces rather than direct live database integrations. Read-only SQLite remains an unsupported integration with an undocumented schema. Apple Events fallback has limited fields and coverage. Do not equate its snapshot with a complete SQLite snapshot. See [Things integration guidance](https://culturedcode.com/things/support/articles/2967034/) and [third-party AI guidance](https://culturedcode.com/things/support/articles/5510170/).

A failed database read does not establish failed Automation permission, and a failed write does not establish that Full Disk Access is missing. Status reports observed capability results and leaves untested permissions unknown. A running app, an authenticated status response and a successful live operation are different evidence.

## Code restrictions and OS confinement

The compiled action table, parameter validation and fixed helper paths limit the interface exposed to callers. They do not constrain arbitrary code after a process compromise. Do not expose arbitrary script bodies, shell commands, Python imports, executable paths or caller-selected app identifiers.

The default app is **unsandboxed**. Full Disk Access is broad and must not be described as a grant only for Things. An explicit signed App Sandbox profile can narrow filesystem access even when the user also grants Full Disk Access: FDA does not bypass sandbox checks. [Apple DTS explains this distinction](https://developer.apple.com/forums/thread/807142).

The experimental Things profile names only the Things group-container directory for read-only filesystem access, Things as its Apple Events target, and app-owned container state. Normal sandbox resources still exist; this is not access to only one directory. Restricting the target app does not create an OS-enforced create-only or read-only scripting role. The adapter's operation policy remains necessary. [Apple documents path and Apple Events exceptions](https://developer.apple.com/library/archive/documentation/Miscellaneous/Reference/EntitlementKeyReference/Chapters/AppSandboxTemporaryExceptionEntitlements.html).

A native synthetic probe demonstrated denied writes to read-only files and denied private sibling/symlink access in the parent and child. Unix IPC worked inside the probe's own sandbox container without network entitlements; the same socket failed in an external state directory. That is evidence for the native probe only. Frozen Python, real Things data, FDA interaction, intended-client TCC attribution and locked-session operation require their own tests.

An explicit file picker and security-scoped bookmark may suit another adapter, but do not automatically bypass protected app containers. The reference does not implement bookmark storage or worker handoff. Validate the exact target and restart lifecycle before claiming narrower consent. [Apple describes the file-access constraints](https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox).

## Signing and build trust

A local code-signing identity can give macOS a stable subject between builds. It does not provide notarisation, Apple review or third-party provenance, and a successful signature check does not prove that macOS retained consent. Ad-hoc signing is for tests. Developer ID distribution adds hardened runtime and requires a separate notarisation/Gatekeeper workflow.

Code signatures seal bundled code and resources. Protect the local signing key: someone who can modify the source and sign it again with the trusted identity can undermine the original trust decision. Same-user token theft can also invoke the legitimate bridge without modifying the bundle.

Build from reviewed source and the committed lockfile. The build uses a fresh exactly synchronised environment, records input/toolchain hashes and rejects changing source inputs. Final signing proceeds inside out; final hashes and signature details are separate evidence. Retain export provenance when building an extracted source tree. These measures aid review; they do not make a compromised source or dependency trustworthy. See [the build and lifecycle guide](../bridge-build.md).

Installation verifies the candidate and staged copy, retains the old app/plist, and checks the installed build identity, process ID and executable through authenticated status. Failed readiness triggers rollback; failed rollback is reported separately. The installer does not grant permissions, edit TCC, create signing identities or publish an app.

## Mutation outcomes and recovery data

A mutation is durably recorded before dispatch. If it cannot obtain a worker slot or journal capacity, execution does not start. A timeout or malformed response after dispatch can leave the app changed. The result then remains `outcome_unknown`; do not automatically retry or switch to direct AppleScript.

In 2.5, automatic provider mode uses the bridge only for writes. Explicit `direct` mode retains the legacy path and its separate permission/timeout risks. Cache-only mode refuses writes. `THINGS3_MCP_ALLOW_DIRECT_FALLBACK=1` affects automatic reads only.

Authenticated `/operations/<id>` and `/operations?correlation_id=...&limit=25` provide inspection, also exposed through MCP tools. A reused correlation label creates a new attempt. No journal entry is automatically replayed. Reconcile the app's actual state before deliberately issuing another request.

The private `operations/` directory beside the socket has seven-day age retention, a 1,000-record limit and a 10 MiB budget. Inactive records are pruned on access or admission; active records are never pruned. This is not a timed erasure promise while the service is idle or stopped. Metadata includes action, outcome, timestamps, caller label and a bounded result identifier when available. Even metadata can be sensitive.

Payload capture is off by default. Set `THINGS3_MCP_BRIDGE_JOURNAL_PAYLOADS=1` for Things or `CLAWBRIDGE_JOURNAL_PAYLOADS=1` for the synthetic adapter in the server environment to retain request bodies. The matching installer persists an explicit `0` or `1` when supplied for a new LaunchAgent. `.env` is not loaded automatically. Payloads can contain titles and notes; single-record inspection may return them, while list responses omit them. Disabling capture affects new records only.

The cache holds app contents separately from the journal. It is not covered by journal age/count/byte limits. New LaunchAgents send stdout/stderr to `/dev/null`, avoiding an unbounded process-output log. Existing logs, old state and installation backups are preserved; inspect them before sharing diagnostics or retiring a machine.

## Operating boundary

Use the bridge only where you trust the local account, reviewed app/dependencies, signing-key custody and authorised clients. Keep clients that need only existing snapshots in cache mode. Do not grant broad access to general Python, Node, a terminal or a bot as a workaround for an unverified bridge configuration.

“Away” means an awake Mac and a logged-in user after interactive consent. Locked-session results must name the exact signed candidate, client and grants. Sleep, logout, FileVault preboot and approval of new dialogs are outside the guarantee. Unit tests, native sandbox probes, frozen signatures and real locked-session operations are separate evidence.

For another application, start with [the adaptation guide](../adapting-clawbridge.md) and choose its scripting and data capabilities explicitly.

## Further references

- Apple: [code signing requirements](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements) and [code signing hashes](https://developer.apple.com/documentation/technotes/tn3126-inside-code-signing-hashes).
- Apple: [inside-out signing](https://developer.apple.com/library/archive/technotes/tn2206/) and [notarisation workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow).
- Apple: [LaunchAgent lifecycle](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).
