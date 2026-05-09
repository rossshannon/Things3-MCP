# Local Bridge Security Model

This document explains the security trade-off behind the signed/self-signed Things3 MCP Bridge.

The short version: the bridge improves reliability by giving macOS one stable local app identity to authorise, but it also creates a local service that can exercise that authorised access on behalf of anything that can successfully call it.

## Why the Bridge Exists

macOS privacy controls attach Full Disk Access and Automation decisions to code identity. Without the bridge, Things access can come from changing executables such as Claude Desktop, `node`, virtualenv Python, Terminal, or `/usr/bin/osascript`. That causes repeated prompts and unattended failures.

The bridge changes the boundary:

```text
MCP client
  -> Things3-MCP server
     -> local Unix socket plus bearer token
        -> signed Things3 MCP Bridge.app
           -> Things SQLite database
           -> Things AppleScript Automation
           -> JSON cache
```

This is a convenience and reliability trade-off, not a claim that the bridge makes local Things access risk-free.

## Assets

The bridge can expose or affect:

- Things task, project, area, tag, and note contents.
- The JSON cache at `~/Library/Application Support/Things3-MCP/cache/latest.json`.
- Bridge token and socket files under `~/Library/Application Support/Things3-MCP/`.
- Bridge logs under `~/Library/Logs/Things3-MCP/`.
- Things writes made through Automation, such as creating or updating todos and projects.
- The local Code Signing identity used to sign `Things3 MCP Bridge.app`.

## Trust Boundaries

The bridge protects against other Unix users by using owner-only permissions for the socket, token, cache directory, and cache file.

The bridge does not protect against all code running as the same macOS user. Any unsandboxed process with the same user privileges may be able to read the token file, inspect the cache, call the socket, or replace files in user-writable locations. If a same-user attacker already exists, the bridge may give that attacker a simpler path through macOS TCC to Things data.

Treat the bridge token as a local bearer credential. Possession of the token authorises bridge calls.

## What Self-Signing Changes

Self-signing creates or uses a local Code Signing identity, commonly named `Things3 MCP Local`, and signs the app bundle so macOS can identify it consistently between rebuilds.

Self-signing does not provide notarisation, Apple review, malware scanning, or third-party provenance. It only says: "this local machine has signed this code with this local identity".

The important side effects are:

- Full Disk Access is granted to a stable app identity rather than a transient Python or Node binary.
- Automation permission is granted to that app identity when writes are used.
- Re-signing different code with the same local identity can preserve the privacy subject that macOS recognises.
- Misuse of the local signing identity/private key can undermine the trust decision because an attacker may be able to sign other code as the bridge identity.

For that reason, only sign code and dependencies you trust.

### Can Someone Change the Python After FDA Is Granted?

In the intended flow, no: the bridge is built into an app bundle and then signed. macOS code signing is meant to detect changes to signed code and bundled resources after signing. macOS privacy grants are also recorded against the app's code identity, not against the plain path alone. If someone simply edits or replaces files inside the signed app bundle, the signature should no longer validate as the same approved app.

The real risk is adjacent:

- If a same-user attacker can use the same local Code Signing identity/private key, they may be able to modify the bundle, re-sign it with the same identity and bundle identifier, and satisfy the privacy requirement macOS recorded for the original bridge.
- If the bridge launches external helpers through user-writable paths, PATH lookup, or environment overrides, an attacker may not need to modify the signed bundle; they may be able to influence what the authorised bridge executes.
- If a same-user attacker can read the bridge token, they can call the legitimate bridge without modifying it at all.

So the risk is not "Python source is inherently mutable after signing"; the risk is "a self-signed, user-installed bridge is only as trustworthy as the local signing key, installed bundle, helper execution paths, and same-user process environment".

Mitigations:

- Keep the local Code Signing private key protected in Keychain. Do not import it with broad always-allow access for arbitrary processes.
- Rebuild and re-sign only from a trusted checkout and lockfile.
- Prefer absolute system paths for external helpers and avoid user-writable PATH lookup.
- Consider installing the final app in a less casually mutable location, such as `/Applications`, for higher-assurance local setups.
- Re-run `codesign --verify --deep --strict --verbose=2 ~/Applications/Things3\ MCP\ Bridge.app` after rebuilds or if the bundle may have been touched.

## Main Risks

### Same-User Token Use

The token is stored with mode `0600`, and its parent directory is `0700`, which blocks other Unix users. That still leaves same-user processes. A hostile process running as the user may read the token and call the bridge.

Impact: read task data, refresh/read cache-backed data, diagnose access, or request supported Things writes.

Mitigations:

- Only run the bridge on a machine/user account where you trust same-user processes.
- Avoid installing untrusted MCP servers or developer tooling under the same account.
- Keep the socket and token on the default owner-only path.
- Rotate the token by stopping the LaunchAgent, deleting `bridge.token`, and reinstalling/restarting the bridge.

### Prompt Injection Through MCP Clients

An LLM or MCP client with access to the Things MCP server can request reads and writes. The bridge makes those operations more reliable while AFK, which is the point, but it also means a bad prompt/tool chain can succeed more consistently.

Impact: exfiltration of task context through the client, or unwanted task/project mutations.

Mitigations:

- Give Things MCP access only to MCP clients you trust.
- Keep write tools disabled or use `THINGS3_MCP_PROVIDER=cache` in contexts that should be read-only.
- Review MCP client permissions and tool-call approval settings.

### Cache and Log Persistence

The bridge cache contains task and project data. Logs may include task titles, parameters, IDs, diagnostics, and error text.

Impact: sensitive task content persists outside Things' own app container.

Mitigations:

- Keep cache and log paths owner-only.
- Clear cache/logs before sharing diagnostics or machines.
- Avoid logging full notes or generated AppleScript in production use.

### Build-Time Supply Chain

The bridge app bundle is built from this checkout and Python dependencies. Signing the app and granting Full Disk Access means build-time compromise can become privacy-granted code.

Impact: malicious dependency or modified source gets signed and authorised.

Mitigations:

- Build from a trusted checkout.
- Use the checked-in lockfile.
- Rebuild only after reviewing meaningful dependency/source changes.
- Prefer Developer ID signing and notarisation for public binary distribution.

### Path and Helper Execution

Any external helper launched by the bridge inherits the practical risk of the bridge context. The implementation should use absolute system paths for platform tools and avoid user-writable PATH lookup.

Impact: helper hijacking can execute unexpected code in the bridge's privacy context.

Mitigations:

- Use absolute paths such as `/usr/bin/osascript`.
- Keep LaunchAgent PATH minimal.
- Verify any app-bundled helper before executing it.

## Safer Operating Modes

- `THINGS3_MCP_PROVIDER=cache`: read-only, no live bridge calls, no writes.
- `THINGS3_MCP_PROVIDER=bridge`: live bridge required for reads and writes.
- `THINGS3_MCP_PROVIDER=auto` with `THINGS3_MCP_ALLOW_DIRECT_FALLBACK=0`: bridge for live reads, cache fallback for reads, bridge/direct chain for writes.
- Avoid `THINGS3_MCP_ALLOW_DIRECT_FALLBACK=1` for unattended use because it can reintroduce direct Things database access from transient processes.

## When Not to Enable the Bridge

Do not enable or authorise the bridge if:

- You do not trust this source checkout or dependencies.
- You regularly run untrusted local code as the same macOS user.
- You cannot accept Things data being cached outside Things' own container.
- You want a hard sandbox boundary between MCP clients and Things data.
- You need a distributable binary security model. Use Developer ID signing and notarisation for that.

## User-Facing Decision

The bridge is a reasonable trade-off for a personal Mac where the user wants reliable local AI access to Things and already trusts their local account, source checkout, and MCP clients.

It is a poor trade-off if the user expects it to isolate Things data from other same-user processes or untrusted LLM/tooling workflows. In that case, prefer cache-only mode or skip the bridge.

## References

- Apple, [Code Signing Services](https://developer.apple.com/documentation/security/code-signing-services)
- Apple, [Applying Code Requirements](https://developer.apple.com/documentation/security/applying-code-requirements)
- Apple, [TN3127: Inside Code Signing: Requirements](https://developer.apple.com/documentation/Technotes/tn3127-inside-code-signing-requirements)
- Apple, [TN3126: Inside Code Signing: Hashes](https://developer.apple.com/documentation/technotes/tn3126-inside-code-signing-hashes)
