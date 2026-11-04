# Tests

## Default automated tests

Use the locked development environment from the repository root:

```bash
uv sync --locked --group dev
uv run --locked pytest
```

The default suite runs mocked and synthetic tests on macOS and Linux. It needs
neither Things nor an operating-system privacy grant. Tests marked `live_things`
are skipped before their fixtures run.

Before collection, the test configuration sets `HOME` to a directory inside
pytest's temporary root and removes inherited `THINGSDB` and `THINGS3_MCP_*`
settings. Default tests must supply their own data, cache, token and socket
fixtures. They must not depend on the installed bridge or a personal library.

A test-process audit guard fails before AppleScript, known live worker commands,
`os.system` calls, or permission tools execute. It also rejects SQLite connections
outside pytest's temporary root, personal Things data paths (including symlinks),
and Unix sockets outside that root. Mocked process calls, temporary SQLite files,
and in-memory databases remain available. Trusted packaging tests can run shell
fixtures with synthetic executables and temporary installation paths. These guards prevent accidental live
access; they are not a sandbox for arbitrary or malicious test code.

Run the focused safety and provider checks with:

```bash
uv run --locked pytest tests/test_test_safety.py tests/test_provider_bridge_cache.py
```

The safety tests launch pytest in disposable projects. Their app boundary is a
synthetic recorder, including the tests of live opt-in and cleanup. They never
contact Things or change privacy settings.

## Live acceptance tests

Live tests read and change the Things library available to the current macOS
user. Use a separate macOS account with a disposable Things library and no
personal sync account. Launch Things and arrange any required app permissions
manually in that account before running the tests.

Both options are required:

```bash
uv run --locked pytest -m live_things --live-things --allow-things-cleanup
```

`--allow-things-cleanup` acknowledges that the historical fixtures create items,
delete tracked item IDs, and scan for and delete names beginning with `mcp-test`.
An unrelated item with that prefix can also be deleted. The shared setup and
cleanup helpers reject calls without both options. Enabling live tests disables
the default isolation, so do not use these options in CI or a personal account.
The old `THINGS3_MCP_SKIP_THINGS_TEST_SETUP` environment variable is no longer an
access control or a prerequisite for safe tests.

The operations modules are live tests. The error-handling module marks its live
writes separately so its mocked tests still run by default. Add `live_things`
explicitly to each new test that needs the real app; use temporary data and mocked
app boundaries for normal coverage.

A passing default suite does not establish live Things behaviour, locked-session
access, privacy permissions, signing, or installed-app identity. Record those
acceptance checks separately; unperformed checks remain unverified.
