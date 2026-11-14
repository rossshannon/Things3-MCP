# Session: Bridge hardening and whole-project audit

**Date**: 2026-11-14
**Captured**: 22:43 GMT
**Branch**: `claude/project-thread-v8bb9o`, based on `codex/bridge-reference-2.5` (PR 13) at `bf5bc82`
**Status**: Code complete and pushed; live verification against Things still to do (see Live verification)

## Overview

A test report from another session listed six requests that made the installed Things bridge drop the connection without a reply, plus four oddities (a cache fallback that could not serve `last`, `include_items=false` being ignored, a misleading auth-status hint, and a cache snapshot 4.6 days old). The request was to fix those, then read the whole project for anything broken, inconsistent, inefficient, dangerous, insecure, incomplete or no longer needed; fix what was certain; and list the rest.

The first finding shaped everything else: **the crashes belong to the build installed on the Mac, not to the current code**. The installed app was built on 23 October from the `feature/signed-local-bridge` worktree (PR 4). The 4 November rewrite on `codex/bridge-reference-2.5` (PR 13) already had strict request framing, a read deadline and a `last` fallback. So this work is based on PR 13: every reported request is now pinned by a regression test, the remaining gaps are closed, and an audit by five parallel reviewers (MCP server and AppleScript, Things bridge and providers, ClawBridge core, packaging and CI, tests) produced the further fixes and the review list below.

The hermetic suite went from 417 passed to 658 passed (116 live tests skipped), and from about 74 s to about 24 s.

## Goals

- [x] Every request in the report returns an HTTP error envelope, proven by a test
- [x] Fix the reported oddities: periods, `include_items`, cache staleness and how it is shown
- [x] Audit both repositories and fix what is certain, each fix with a regression test
- [x] Separate commits, accumulated as the work went
- [x] Re-export the standalone `clawbridge` repository
- [ ] One live run against Things at the end, with clean-up confirmed (blocked on a macOS permission prompt; see Live verification)
- [x] List everything not fixed for review

## Key Decisions

### Base the work on PR 13, not PR 4 or `main`

The bridge exists only on feature branches. PR 4's code is an ancestor of PR 13's and is the code with the crashes; fixing it there would have meant re-doing a rewrite that already exists. PR 12 (AppleScript identifier injection on `main`) is already closed on this line by `7da6791`.

### A request that fails must say whether it is safe to send again

The envelope's `outcome` field is the contract: `not_started` and `failed` are safe to resend, `outcome_unknown` is not. Several paths got this wrong in both directions:

| Situation | Was | Now |
| --- | --- | --- |
| Write ran, result could not be encoded (NaN) | 400 `not_started` | 500 `outcome_unknown` with the operation id |
| Write ran, worker reply had no valid outcome | handler crashed, journal record left open | `outcome_unknown`, record closed |
| Write sent to a bridge that is not listening | `outcome_unknown` | `bridge_unavailable`, `failed` |
| Header block truncated at the input deadline | acted on without the lost headers | 400 `not_started` |
| Blank title or impossible project destination | AppleScript ran and failed | refused before any script, `failed` |

### A bad request is not an outage

things-py raises `ValueError` for a filter value it does not accept. That was recorded as "database unavailable", after which the read fell through to Apple Events and then the cache. It is now `invalid_request` (or `not_found` for a missing identifier), is not retried through another source, and the database is recorded as available.

### An empty answer must mean "there are none"

The cache snapshot holds open to-dos and projects only. Queries it cannot answer (completed projects, trashed items, headings) now return `cache_miss` instead of an empty list. The same idea applies to the write tools: a `when` value Things cannot use is refused with the list of accepted values, rather than dropped while reporting success.

### Keep the snapshot recent without a scheduler

Nothing refreshed `cache/latest.json` except a manual `--snapshot-once`. After a successful database-backed read, the bridge now renews a snapshot older than an hour in a background thread (`THINGS3_MCP_BRIDGE_SNAPSHOT_REFRESH`, seconds, `0` disables). A successful live read is the cheapest evidence that a full read will also work. Only a database snapshot may replace the file; an Apple Events one carries fewer fields. Cached answers state their age in words and are flagged when older than a day.

### Not done on purpose

- **No rebuild, re-sign or reinstall of the bridge app.** An ad-hoc re-signed bundle can lose its macOS privacy grants, and nobody was at the machine to re-approve them.
- **Design questions were listed, not decided**: see "For review".
- **Code that looks deliberate was kept** even when unused, and listed.

## Changes Made

### New files

- `tests/test_bridge_malformed_requests.py` - each reported request, sent as raw bytes over the real socket; all return 400 and start no worker
- `tests/test_cache_fallback.py` - fallback provenance, age, `include_items`, renewal
- `tests/test_period_handling.py` - period parsing shared by `get_logbook` and `get_recent`
- `tests/test_write_scripts.py` - generated AppleScript for every write path, and tool-level validation
- `tests/test_bridge_read_faults.py` - refused filters, cache gaps, naive timestamps, unwritable snapshots, refused connections
- `tests/test_live_cleanup_helpers.py` - the live-test sweep, against a scripted stand-in for Things
- `tests/test_logging_setup.py` - logging with and without a writable log directory
- `tests/live_reads.py`, `tests/test_live_reads.py` - AppleScript read-back for live tests, and the rules that keep live tests off the database

### Modified files

- `src/clawbridge/server.py` - one JSON reply for every request; routing and execution separated so a fault after dispatch can never read as `not_started`; truncated headers and HTTP/0.9 rejected; storage faults are 503
- `src/clawbridge/worker.py` - worker output with NaN or Infinity is an invalid response
- `src/clawbridge/journal.py` - ignores files it did not write; completion without a valid outcome is `outcome_unknown`
- `src/clawbridge/runtime.py` - token created atomically
- `src/clawbridge/actions.py` - optional `patterns` per text parameter
- `src/clawbridge/packaging.py` - malformed `environment_patterns` is a packaging error
- `src/things3_mcp_bridge/server.py` - snapshot renewal; snapshot write failures reported as `cache_unwritable`; refused reads not answered from cache
- `src/things3_mcp_bridge/db_reader.py` - refused filter values separated from an unavailable database
- `src/things3_mcp_bridge/actions.py` - duration pattern on `last`
- `src/things3_mcp/providers/cache.py` - `include_items` honoured; gaps reported; naive timestamps read as UTC
- `src/things3_mcp/providers/bridge.py` - refused connection is a known failure; period is URL-quoted
- `src/things3_mcp/applescript_bridge.py` - status flags, text passed unaltered, single tag strings, clearing notes and tags, `add_tags`, early refusals, one scheduling helper
- `src/things3_mcp/fast_server.py` - month periods, schedule validation, readable snapshot age, `search_advanced` filters, project location
- `src/things3_mcp/logging_config.py` - log files optional
- `tests/conftest.py` - live-test sweeps rewritten; background snapshot renewal disabled in tests
- `.github/workflows/lint.yml`, `smithery.yaml`, `.pre-commit-config.yaml`, `.envrc`, `pyproject.toml`, `README.md`, `.env.example`, `packaging/macos/bridge.toml` - brought in line with the code and the locked toolchain

### Deleted files

- `test_todo.md` - a completed checklist for the test suite

## Commits

26 code commits on `claude/project-thread-v8bb9o`, `284a248` to `a4d4dbe`, plus this note; `git log bf5bc82..` lists them. In the standalone repository, `7a1d3e1` and `8719651` on the same branch name carry the re-export.

## Live verification

The hermetic suite was run on the Mac in a new, separate worktree (`/Users/ross/Development/Things3-MCP-live-test`, Python 3.12.16): 657 of 658 passed. The one failure was a real difference between Python 3.12 and 3.13: after an HTTP/0.9 request line, 3.12 waits for headers and 3.13 skips them. The request is now refused from the request line alone (`dd2ea51`), and the suite passes on 3.12.3 and 3.13.18 in the container, in both repositories.

**The live run against Things did not happen.** The read-only preflight stopped at its first Apple Event: macOS was asking whether the Claude Code binary may control Things, and nobody was at the machine to answer. Nothing was created in Things, no development bridge was started, and nothing on the Mac changed apart from the new worktree.

What the preflight did establish, from `Things.sdef`: to-dos expose `name`, and no class has a `title` property. That confirms why the old live-test sweeps matched nothing (they read `title`) and relied on a database fallback.

Not yet verified against the real app, and covered only by tests of the generated script:

- `add_tags`, and clearing notes or tags with an empty value
- the rewritten clean-up sweeps in `tests/conftest.py`
- the `in List: Anytime` expectation in `tests/test_list_assignment_operations.py`
- the AppleScript read-back in `tests/live_reads.py` (property names and list membership)

The live tests are split by what they need (see "Update - 2026-11-14 23:50 UTC" below):

1. **Automation only.** `uv run --locked pytest -m "live_things and not things_bridge" --live-things --allow-things-cleanup` (69 tests). The test process writes through AppleScript and reads back through AppleScript (`tests/live_reads.py`). It needs macOS Automation consent for the process that runs it (Claude Code to Things, or a terminal) and nothing else. No bridge is involved and the database is not opened. First check that nothing in Things already starts with `mcp-test`; the sweep would delete it. Run `tests/test_integration.py` on its own first and check for leftovers.
2. **Through the bridge.** `uv run --locked pytest -m things_bridge --live-things --allow-things-cleanup` (47 tests). These call the MCP tools, which go through the bridge, and most of their reads need the database. They need the signed bridge app rebuilt and installed from this line, using that app's own grants. They are not expected to pass against the October build.

Test items end up in the Things Trash; that is expected.

### Update - 2026-11-14 23:50 UTC

**Summary**: live tests no longer open the Things database, so the part that drives Things directly runs with the Automation permission alone.

Project rule: test processes and coding agents are not given Full Disk Access or any other access to the Things database, and it is not to be suggested as a fix. That access belongs to the signed bridge app only.

The live tests did not fit that rule. They checked the result of each write by reading the item with the `things` package, which opens the database from the test process (55 call sites in six files), and one test pinned the provider to `direct`. Changes:

- `tests/live_reads.py` reads a to-do or project back through AppleScript (`get`, `in_list`), returning the same field names the assertions already used. The six files use it in place of `things.get`, `things.today` and the rest. Completed and cancelled items resolve by id, so the status-search workaround in `test_completion_operations.py` went away, as did the `things.today()` sorting workaround in `test_scheduling_operations.py`.
- A `things_bridge` marker separates the 47 live tests that call an MCP tool (all of `test_list_operations.py` and eight others) from the 69 that only use AppleScript. An autouse fixture makes an unmarked live test fail if it reaches `fast_server.get_provider`, and `tests/test_live_reads.py` checks the marking statically.
- `test_search_advanced_empty_results` no longer pins the `direct` provider. A refused filter now comes back through the bridge as a search error (see "A bad request is not an outage"), which is what the test asserts.

Question from Ross, paraphrased: is the live run still possible with Automation only? Yes for the 69 AppleScript tests, which cover every write path changed in this work and the clean-up sweeps. The 47 bridge tests need a bridge built from this code with its own database access, which means the rebuilt signed app; a bridge started from a Claude session would hold no database access and should not be used for them.

## For review

Nothing in this list was changed. Items are grouped by what they need from you.

### Needs you at the Mac

1. **The installed bridge is still the October build.** `~/Applications/Things3 MCP Bridge.app` (0.1.0 build 1) comes from `.worktrees/signed-local-bridge`. Rebuild, sign and install from this line once merged (`scripts/build_bridge_app.sh`, `sign_bridge_app.sh`, `install_bridge_launchagent.sh`), then re-approve the bridge app's own permissions if macOS asks (they belong to the app, not to any client).
2. **Cache permissions before the first start of the new build.** The old build created `cache/` as 0755 and `latest.json` as 0644; the new code refuses both as unsafe (`cache_unreadable`). Either `chmod 700 ~/Library/Application\ Support/Things3-MCP/cache && chmod 600 .../cache/latest.json`, or delete the file and let it be renewed. The installer only fixes the parent directory.
3. **MCP clients run the old code too.** Claude desktop, Cursor and `~/.claude.json` start `~/.venvs/things3-mcp-env/bin/Things3-MCP-server`, an editable install of that same worktree.
4. **Pull requests.** PR 4 is superseded by PR 13. PR 12's fix is already on this line.

### Design decisions

- **Live tests sweep by name.** Anything in Things whose name starts with `mcp-test` is deleted at the start and end of a live run, and nothing checks that the library is disposable. A per-run random token, or deleting tracked identifiers only, would remove the risk.
- **`/auth-status` cannot say "known".** Database access is never recorded as `denied`, and Automation is only observed on writes, so `authorization_known` stays false while reads work; `authorized` is always null and `app_process` always `unknown`.
- **Staleness policy.** There is no age beyond which a snapshot is refused, no refresh for a bridge that receives no reads, and a failed renewal is visible only in `bridge.err.log`.
- **Cache coverage.** `get()` returns nothing for items that are not open; search covers to-dos only; `last` and the Trash cannot be answered (the snapshot has no creation index and no trashed items).
- **Apple Events fallback.** It has no `search` or `last` (they return `apple_events_unsupported`, then `cache_miss`), uses English list names, shows cancelled to-dos as open, does not filter projects, and has an 8 s deadline.
- **Raw `GET /things/projects|areas|tags` defaults to `include_items=true`**, where the providers default to false.
- **Concurrent writes are rejected** (503 `bridge_busy`) rather than queued.
- **Fail-closed start-up.** A journal record that fails validation, or an empty token file, stops every start with no repair command. The token rule is pinned by an existing test, so it was kept.
- **Symlinked ancestors are refused** for runtime directories and for the MCP client's token path, which rules out `/tmp` and `/var` on macOS.
- **Durability.** `fsync` on macOS without `F_FULLFSYNC`; shutdown waits for handlers without a limit.
- **AppleScript semantics.** `(current date) + N * days` keeps the time of day; a past `when` date becomes today; list names are English; one 8 s deadline covers a project with many to-dos; `update_todo(list_name="Trash" | "Logbook")` deletes or completes without saying so in the tool description.
- **MCP tool surface.** Five different error string formats and `isError` is never set; outputs are unbounded; the tools are synchronous and block the event loop; FastMCP turns `notes="null"` into no value; identifiers are not checked against a format.
- **Efficiency.** `include_items` on projects, areas and tags issues one query per row; `/status` and `/auth-status` parse the whole snapshot (3 MB) each time.
- **Timeouts.** The client refuses any timeout at or below 30 s regardless of the worker's setting, and `THINGS3_MCP_BRIDGE_WORKER_TIMEOUT` is not on the LaunchAgent's allow-list.
- **`pytest --cov` does not work** under the hermetic guard, and the worker deadline test fails under coverage.

### Packaging and release

- `publish-trusted.yml` publishes from one job holding both `id-token` and `contents` write, installs `twine` unpinned, pins third-party actions by tag, and runs no tests or tag-versus-version check first.
- `.claude/settings.local.json` is tracked and pre-approves broad commands (`python`, `twine upload`, `git push`). Untracking it would delete your local copy on the next pull, so it was left.
- The wheel installs top-level `clawbridge` and `clawbridge_mcp` packages, which collide with `clawbridge-reference` if both are installed.
- There are two `dev` dependency definitions that have drifted apart.
- `docs/bridge-build.md` names the Things app but is exported to the standalone repository.
- Session notes in a public repository contain `/Users/ross/...` paths.

### Probably unused, kept

- `things_fast_server.py` (root launcher; older client configurations may still point at it)
- `scripts/seed_cache.py` (a workaround from when the bundle could not read; now labels its snapshot correctly)
- `UnavailableThingsProvider`, the `ensure_token` wrapper in `things3_mcp_bridge.server`, `_trace` (its output is discarded by the worker), `op_desc` parameters, unused keyword arguments on `log_operation_*`, the identical `search_todos` and `search_items` tools, unreachable branches and an inaccurate docstring in `date_converter.py`, `.cursor/rules/packaging-releases.md`, the `slow`, `integration` and `unit` pytest markers
- Around 30 live read tests that assert only that a string came back, and mocks in `tests/test_error_handling_and_logging.py` that return strings `run_applescript` no longer produces

## Lessons Learned

1. **Check what is actually running before reading the report as a bug list.** Traceback line numbers in `bridge.err.log` identified the installed build's source tree in minutes.
2. **`outcome` is the part of the protocol that matters most**, and the easiest to get wrong in an `except` clause: `JournalError` and `RuntimeSafetyError` subclass `ValueError`, so a broad `except ValueError` turned storage faults and post-dispatch faults into "invalid request, safe to resend".
3. **A timer that half-closes a socket looks like end-of-headers** to `BaseHTTPRequestHandler`. Remembering the last line read is enough to tell a complete header block from a truncated one.
4. **Background work in a server needs an off switch for tests.** Snapshot renewal would have written test data into a real cache during a live run; an autouse fixture disables it.
5. **`serve_forever()` polls every 0.5 s.** Passing `poll_interval=0.01` in test fixtures cut the suite by 50 s.
6. **Run the suite on every Python the project supports.** The container defaults to 3.13 (`UV_PYTHON=3.13`, because `.python-version` pins 3.12.16, which is not installed there), the Mac and the frozen app use 3.12, and `http.server` differs between them. `UV_PYTHON=3.12` with a separate `UV_PROJECT_ENVIRONMENT` reproduces the Mac's result in the container.
7. **Things' AppleScript dictionary has `name`, not `title`.** `title of theTodo` compiles, fails at run time, and inside a `try` block fails silently.
8. **A test that checks through a different door than the product needs permissions the product does not.** The writes needed only Automation; it was the tests' own verification reads that needed the database. Reading back through the interface under test removed the requirement.

## References

- Pull requests: Things3-MCP PR 13 (base of this work), PR 4 (superseded), PR 12 (already fixed here)
- Earlier notes: `docs/sessions/2026-11-04-1438-bridge-reference.md`, `docs/sessions/2026-11-04-bridge-review-followup.md`
- Export: `scripts/export_clawbridge.py`, `export-manifest.json` in the standalone repository

## Next Steps

- [ ] Allow Automation (Claude Code to Things) on the Mac, then run the Automation-only live tests
- [ ] After the bridge is rebuilt from this line, run the `things_bridge` live tests against it
- [ ] Review and merge PR 13 and this branch; close PR 4
- [ ] Rebuild, sign and install the bridge; fix cache permissions first
- [ ] Repoint the MCP client virtual environment at the merged code
- [ ] Decide the items under "Design decisions", starting with the live-test sweep and `/auth-status`
