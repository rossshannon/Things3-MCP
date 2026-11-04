# ClawBridge reference

ClawBridge routes MCP tools to a small signed macOS app that holds the permissions needed for fixed app actions. A bot connects to an app-specific MCP server; the protected binary is a separate execution backend. The MCP process does not automatically receive macOS permissions. Other local clients can use the socket API.

```text
Bot → MCP stdio (optionally over SSH) → authenticated owner-private Unix socket
    → signed fixed-action app / same-executable worker → fixed app API, AppleScript or read-only file
```

Start with the counter, which needs no privacy grant, then choose [Music or read-only SQLite](docs/examples/README.md). The local core uses the Python standard library; MCP is an optional dependency in this standalone export.

The source of truth is [Things3-MCP](https://github.com/rossshannon/Things3-MCP). `scripts/export_clawbridge.py` in that project copies an explicit file list into a fresh directory. `export-manifest.json` records the source revision, whether exported inputs were uncommitted, and the source name, SHA-256 and mode of each exported file. The manifest excludes itself. Retain it with build evidence; hashes establish content identity, not publisher trust. A separate repository's `README.md` is outside this export and remains separately maintained.

## Run the synthetic MCP example

From the standalone export:

```sh
uv sync --locked --group dev --extra mcp
uv run --locked --extra mcp python -m clawbridge.demo --socket "$PWD/tmp/demo/bridge.sock" --token-file "$PWD/tmp/demo/bridge.token"
```

The helper stays in the foreground and creates private runtime state. Use a short absolute checkout path: macOS Unix socket names are limited to 103 bytes. This source example needs no grant. Verify the exact signed candidate and launch chain for real permission attribution.

Configure a local MCP client with absolute operator-controlled paths, substituting your checkout path:

```json
{
  "mcpServers": {
    "counter": {
      "command": "/Users/you/clawbridge/.venv/bin/clawbridge-mcp",
      "args": ["--profile", "counter", "--socket", "/Users/you/clawbridge/tmp/demo/bridge.sock", "--token-file", "/Users/you/clawbridge/tmp/demo/bridge.token"]
    }
  }
}
```

Restart the client, discover the tools and call `counter_read` with `{}` or `counter_increment` with `{"amount":1,"correlation_id":"example-counter-1"}`. With fresh state, `counter_read` returns envelope data `{"value":0}`. The structured content and JSON text retain the bridge response fields; the client may normalise correlation information or produce a transport-failure envelope. A successful increment has `ok: true`, `outcome: "succeeded"`, a `data` object and an `operation_id` identifying that attempt. IDs are generated. An unsuccessful envelope sets MCP `isError`.

The profiles are `counter` (`counter_read`, `counter_echo` with string `text`, and `counter_increment` with integer `amount`), `music` (`music_state`, `music_play`, `music_pause`), and `catalogue` (`catalogue_items`, `catalogue_search` with non-empty string `query`). Each also exposes `bridge_status`, `get_operation` and `list_operations`. Mutations accept an optional `correlation_id`; `get_operation` requires `operation_id`, and `list_operations` accepts an optional `correlation_id` and integer `limit` from 1 to 100 (default 25). Select one profile per client configuration and use its helper's socket and token paths.

For a remote client, SSH can carry stdio to the Mac. This configuration is illustrative and must be checked in your SSH environment. The last argument is one remote-shell command; paths are single-quoted to preserve spaces:

```json
{
  "mcpServers": {
    "counter-remote": {
      "command": "ssh",
      "args": ["-T", "you@your-mac", "'/Users/you/clawbridge/.venv/bin/clawbridge-mcp' --profile counter --socket '/Users/you/Library/Application Support/ClawBridge/bridge.sock' --token-file '/Users/you/Library/Application Support/ClawBridge/bridge.token'"]
    }
  }
}
```

The token stays on the Mac; arguments contain its file path, not its value. Discovery works without the helper; calls read existing credentials and do not create a token or start the helper. SSH does not add per-bot authorisation. A remote network service requires separate authentication and integration.

Mutations are sent once. The MCP exchange waits up to 35 seconds, longer than the worker's 30-second deadline. An unknown outcome includes a correlation label prepared before sending; inspect records and app state before another attempt. Operation IDs identify attempts, not idempotency keys; inspection does not replay writes. A journal warning does not turn known success into failure. If payload retention is enabled, operation lookup can return private payloads, so protect the MCP channel accordingly.

## Direct socket diagnostics

Use uv and the pinned Python in `.python-version`. From the exported directory:

```sh
uv run --locked --extra mcp pytest
```

With the helper running, from another terminal in the same directory:

```sh
curl --unix-socket "$PWD/tmp/demo/bridge.sock" http://localhost/health
curl --unix-socket "$PWD/tmp/demo/bridge.sock" \
  --header "Authorization: Bearer $(cat tmp/demo/bridge.token)" \
  http://localhost/status
curl --unix-socket "$PWD/tmp/demo/bridge.sock" \
  --header "Authorization: Bearer $(cat tmp/demo/bridge.token)" \
  --header 'Content-Type: application/json' \
  --header 'X-Correlation-ID: example-counter-1' \
  --data '{"amount":1}' http://localhost/demo/increment
curl --unix-socket "$PWD/tmp/demo/bridge.sock" \
  --header "Authorization: Bearer $(cat tmp/demo/bridge.token)" \
  'http://localhost/operations?correlation_id=example-counter-1&limit=25'
```

These commands demonstrate a synthetic local credential. Keep actual bearer tokens out of shared command logs and process recordings. `/demo/read` reads the counter; `POST /demo/echo` accepts `{"text":"hello"}`. Every route except the minimal `/health` needs the token. Reusing a correlation label creates a new attempt; it does not deduplicate a mutation. An `outcome_unknown` result requires inspection, never an automatic retry.

## Build and sign a candidate

On macOS with Apple's command-line tools:

```sh
uv sync --locked --no-default-groups --group build --python 3.12.16
scripts/build_bridge_app.sh --output build/example-candidate
scripts/sign_bridge_app.sh --app 'build/example-candidate/ClawBridge Example.app' --profile ad-hoc-test
codesign --verify --deep --strict 'build/example-candidate/ClawBridge Example.app'
```

Exercise the signed example with a fresh, short runtime path:

```sh
uv run --locked --extra mcp python scripts/smoke_example_bridge.py \
  --app 'build/example-candidate/ClawBridge Example.app' \
  --runtime /private/tmp/clawbridge-example-check \
  --result build/example-candidate/smoke.json --mcp
```

Choose fresh runtime state for each run: the socket, token, counter and operation directory must not already exist there. The check accepts only the synthetic `clawbridge.demo` entrypoint. It verifies signatures and entitlements, authentication, exact build/process identity, echo, a counter mutation, operation lookup and private file modes, then stops the app. It checks captured stdout/stderr for synthetic payloads and the token. It does not install a service or access Things. Retain the result with the signed artefact evidence.

The default `packaging/macos/bridge.toml` is the synthetic configuration: `ClawBridge Example`, `org.example.ClawBridgeExample`, and `clawbridge.demo:main`. The build creates a separate, exactly synchronised environment from `uv.lock`. It records source inputs, toolchain, configuration and entitlements. Signing produces separate final artefact evidence. This procedure is repeatable; signed bytes are not promised to be identical.

Ad-hoc signing is for synthetic tests. Use `--profile local --identity 'Your Existing Local Identity'` for an existing local signing identity. Public distribution needs the separate Developer ID profile, hardened runtime, notarisation and final Gatekeeper validation. The scripts do not create identities or grant permissions. Build and signing do not install or launch the app. See [the build and lifecycle guide](docs/bridge-build.md) for explicit installation, backup and rollback behaviour.

## Adapt and validate

Follow [Adapting ClawBridge](docs/adapting-clawbridge.md) and the [security model](docs/security/local-bridge-security.md). Keep the core copied from its source of truth; implement your application's fixed actions in an adapter. This export contains no private fixtures, personal machine paths, Things runtime dependency, signing keys or credentials.

The tests use synthetic data. A passing suite or verified signature does not prove consent attribution, protected app access, locked-session operation or safe recovery after a real application mutation. Record each of those checks separately for your adapter and signed candidate.
