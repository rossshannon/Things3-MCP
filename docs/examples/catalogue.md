# Catalogue: a fixed read-only database

This adapter reads a small synthetic SQLite database with `items(id TEXT PRIMARY KEY, title TEXT NOT NULL)`. It demonstrates the file-access variant without opening an app's private library. Read [the adapter](../../src/clawbridge/examples/catalogue.py) and [its configuration](../../packaging/macos/catalogue.toml).

| Request | Parameters | Result |
| --- | --- | --- |
| `GET /catalogue/items` | None | The first 100 items, ordered by ID |
| `POST /catalogue/search` | `{"query":"book"}` | A literal substring search, case-insensitive for ASCII text |

Both return `items` and a `truncated` flag. Search is a read despite using HTTP POST. There are no mutation actions. SQL is fixed, search text is bound as data, and requests cannot select a file, table or SQL statement.

## Fixed path and permissions

The MCP profile `catalogue` exposes `catalogue_items` and `catalogue_search`, plus `bridge_status`, `get_operation` and `list_operations`. Use the client configuration in the standalone `REFERENCE.md`, selecting `--profile catalogue` and the helper's absolute socket and token paths. The default runtime is `~/Library/Application Support/ClawBridgeCatalogueBridge/`; expand `~` in client JSON. The MCP process does not start the helper or gain its permissions.

For example, replace the paths with those on your Mac:

```json
{
  "mcpServers": {
    "catalogue": {
      "command": "/Users/you/clawbridge/.venv/bin/clawbridge-mcp",
      "args": ["--profile", "catalogue", "--socket", "/Users/you/Library/Application Support/ClawBridgeCatalogueBridge/bridge.sock", "--token-file", "/Users/you/Library/Application Support/ClawBridgeCatalogueBridge/bridge.token"]
    }
  }
}
```

The only database path is the account home followed by:

```text
Library/Application Support/ClawBridgeCatalogue/catalogue.sqlite3
```

The account home comes from `pwd.getpwuid(os.getuid())`, not the `HOME` environment variable or a request. This keeps the intended source outside the bridge's own container when a sandbox or launcher changes `HOME`. `--health` reports the resolved path without opening it. The fixture instructions below use the same account lookup. Verify the resolved path on your exact frozen sandbox build before using it with other data.

The adapter rejects symlink components and opens an existing regular file with SQLite `mode=ro` and `PRAGMA query_only=ON`. It never creates a missing database. [SQLite documents read-only URI mode](https://www.sqlite.org/uri.html) and [the query-only setting](https://www.sqlite.org/pragma.html#pragma_query_only).

The supplied fixture needs no Automation or Full Disk Access grant. The experimental sandbox profile grants read-only access to this one catalogue directory; writable bridge state lives separately in its own container. The directory entitlement leaves room for SQLite sidecars, but this simple fixture uses a closed rollback-journal database. Live WAL access and concurrent modification are not established by these tests. Do not add `immutable=1` to an actively changing app database to avoid its locking requirements.

For a real app, first prefer a supported API or explicit export. If you must read a protected database, the exact path and macOS privacy rules determine whether an additional Full Disk Access grant is required. A compiled path does not narrow that grant: it limits the adapter's implementation. Signed App Sandbox restrictions are a separate operating-system boundary, and Full Disk Access does not bypass them. [Apple's explanation](https://developer.apple.com/forums/thread/807142). Neither control protects against every form of same-user tampering; the path checks are not a claim of confinement against a compromised unsandboxed process.

## Create the synthetic fixture

This explicit setup command creates a new database and refuses to replace an existing one. The bridge itself has no write endpoint:

```sh
.venv/bin/python - <<'PY'
import os
import pwd
import sqlite3
from pathlib import Path

path = Path(pwd.getpwuid(os.getuid()).pw_dir) / "Library/Application Support/ClawBridgeCatalogue/catalogue.sqlite3"
path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
os.close(descriptor)
database = sqlite3.connect(path)
try:
    database.execute("CREATE TABLE items (id TEXT PRIMARY KEY, title TEXT NOT NULL)")
    database.executemany("INSERT INTO items VALUES (?, ?)", [("one", "Example book"), ("two", "Example film")])
    database.commit()
finally:
    database.close()
print(path)
PY
```

## Build and read

```sh
scripts/build_bridge_app.sh --config packaging/macos/catalogue.toml --output build/catalogue-candidate
scripts/sign_bridge_app.sh --config packaging/macos/catalogue.toml \
  --app 'build/catalogue-candidate/ClawBridge Catalogue.app' --profile ad-hoc-test
'build/catalogue-candidate/ClawBridge Catalogue.app/Contents/MacOS/ClawBridge Catalogue' --health
'build/catalogue-candidate/ClawBridge Catalogue.app/Contents/MacOS/ClawBridge Catalogue'
```

The last command serves in the foreground. In another terminal, use the [Music guide's token-reading client](music.md#build-and-try-it), with runtime `~/Library/Application Support/ClawBridgeCatalogueBridge` and request `GET /catalogue/items`. For search, use `POST /catalogue/search` and a JSON body such as `{"query":"book"}`. Stop the service with Control-C.

For the experimental sandbox profile, add `--sandbox-experimental` to the build. A foreground run must pass socket and token paths inside `~/Library/Containers/org.example.ClawBridgeCatalogue/Data/`; the installer selects them automatically. The source catalogue stays at the account-home path above. Use a stable signing identity instead of ad-hoc signing before testing privacy consent for a protected real-app path. See [the shared build guide](../bridge-build.md).

## Adapt it

Replace the schema and fixed query with your app's supported export format, and change the compiled relative path and read-only entitlement together. Keep the database path absent from request schemas. For a JSON or text export, replace only the reader; the same fixed-location and permission distinction applies. Validate schema changes, source freshness and the source app's locking requirements before deploying against live data.

The tests stub the account lookup to a temporary fixture. They verify query results, literal search inputs, result bounds, unchanged source bytes, rejected writes, missing-file behaviour and symlink rejection. They do not prove Full Disk Access, sandbox filesystem enforcement or compatibility with any real application's database.
