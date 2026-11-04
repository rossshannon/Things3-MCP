# ClawBridge reference

This is a generated, standalone synthetic example of a local macOS application bridge. Its runtime uses only the Python standard library. It does not import Things, install an MCP server, or require any privacy grant. It echoes text and maintains one counter in its private runtime directory.

The source of truth is [Things3-MCP](https://github.com/rossshannon/Things3-MCP). `scripts/export_clawbridge.py` in that project copies an explicit file list into a fresh directory. `export-manifest.json` records the source revision, whether exported inputs were uncommitted, and the source name, SHA-256 and mode of each exported file. The manifest excludes itself. Retain it with build evidence; hashes establish content identity, not publisher trust. A separate repository's `README.md` is outside this export and remains separately maintained.

## Run the synthetic adapter

Use uv and the pinned Python in `.python-version`. From the exported directory:

```sh
uv sync --locked
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src/clawbridge
uv run --locked bandit -r src/clawbridge -c pyproject.toml
uv run --locked python -m clawbridge.demo --socket "$PWD/tmp/demo/bridge.sock" --token-file "$PWD/tmp/demo/bridge.token"
```

The last command stays in the foreground. Use a short checkout path: macOS Unix socket names are limited to 103 bytes. The server creates the private runtime directory, token and `operations/` journal. In a second terminal, from the same directory:

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
uv sync --locked --group build
scripts/build_bridge_app.sh --output build/example-candidate
scripts/sign_bridge_app.sh --app 'build/example-candidate/ClawBridge Example.app' --profile ad-hoc-test
codesign --verify --deep --strict 'build/example-candidate/ClawBridge Example.app'
```

Exercise the signed example with a fresh, short runtime path:

```sh
uv run --locked python scripts/smoke_example_bridge.py \
  --app 'build/example-candidate/ClawBridge Example.app' \
  --runtime /private/tmp/clawbridge-example-check \
  --result build/example-candidate/smoke.json
```

Choose fresh runtime state for each run: the socket, token, counter and operation directory must not already exist there. The check accepts only the synthetic `clawbridge.demo` entrypoint. It verifies signatures and entitlements, authentication, exact build/process identity, echo, a counter mutation, operation lookup and private file modes, then stops the app. It checks captured stdout/stderr for synthetic payloads and the token. It does not install a service or access Things. Retain the result with the signed artefact evidence.

The default `packaging/macos/bridge.toml` is the synthetic configuration: `ClawBridge Example`, `org.example.ClawBridgeExample`, and `clawbridge.demo:main`. The build creates a separate, exactly synchronised environment from `uv.lock`. It records source inputs, toolchain, configuration and entitlements. Signing produces separate final artefact evidence. This procedure is repeatable; signed bytes are not promised to be identical.

Ad-hoc signing is for synthetic tests. Use `--profile local --identity 'Your Existing Local Identity'` for an existing local signing identity. Public distribution needs the separate Developer ID profile, hardened runtime, notarisation and final Gatekeeper validation. The scripts do not create identities or grant permissions. Build and signing do not install or launch the app. See [the build and lifecycle guide](docs/bridge-build.md) for explicit installation, backup and rollback behaviour.

## Adapt and validate

Follow [Adapting ClawBridge](docs/adapting-clawbridge.md) and the [security model](docs/security/local-bridge-security.md). Keep the core copied from its source of truth; implement your application's fixed actions in an adapter. This export contains no private fixtures, personal machine paths, Things runtime dependency, signing keys or credentials.

The tests use synthetic data. A passing suite or verified signature does not prove consent attribution, protected app access, locked-session operation or safe recovery after a real application mutation. Record each of those checks separately for your adapter and signed candidate.
