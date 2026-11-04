# Things3-MCP 2.5 bridge reference

## Goals

Integrate the signed local bridge as the Things3-MCP 2.5 reference and provide a reproducible ClawBridge extraction for other app developers. Apply only necessary app-specific permissions and document repeatable build, signing and installation procedures.

## Scope and authority

The implementation runs in an isolated worktree from `7481ab0`. Existing development checkouts and the installed bridge are preserved. LFG covers implementation, review and pull-request preparation; live replacement, new privacy grants, merge and release remain separate actions. Prior task recovery was completed independently; no recovery payloads belong in this repository.

## Decisions

- Preserve the current MCP major and established Things tools.
- Separate generic local transport/lifecycle from Things data and scripting.
- Remove System Events from readiness checks and distinguish scripting from database permissions.
- Keep ordinary logs free of task content; provide bounded, opt-in payload recovery records.
- Treat compiled path restrictions as application controls, distinct from App Sandbox enforcement.
- Use constructive change descriptions: improving, hardening and adding capabilities. Do not disparage earlier code or attribute it to a model.

## Plan

See [the implementation plan](../plans/2026-11-04-1438-feat-bridge-reference-plan.md).

## Validation and progress

Research covers current source, Apple permission/signing documentation, PyInstaller packaging, client parity and recovery flows. Six independent plan reviewers returned no findings. The additional Claude review could not authenticate; it supplied no review evidence. The existing mocked provider baseline passed 52 tests. Default tests now isolate user configuration, require explicit live opt-in and protect setup/cleanup. The full default suite passed 72 tests and skipped 118 live cases; Ruff and formatting passed for all test files. Signed artifact and locked-session evidence will be recorded separately.

Ross requested a GPT-6.1 Terra draft of the standalone README, with the repository private until his review. The initial README explains the concept, the May 2026 origins, app-specific permissions, Computer Use alternatives and planned implementation boundaries. It was reviewed, uploaded and read back byte-for-byte in the private `rossshannon/clawbridge` repository at commit `915b841058f157f2b524fee495c5d157d94438d4`. GitHub visibility was verified as private after upload. The private draft is not part of this public source tree.

Additional Apple guidance confirms that Full Disk Access does not bypass App Sandbox. A synthetic signed probe will test static read-only path constraints and child/socket behaviour without reading Things data or changing privacy settings. This experiment does not establish actual Things access or locked-session operation.

### Update — 4 November, 15:22 GMT

The synthetic native sandbox experiment completed. Parent and respawned child processes could read the allowed private fixture and append to private state. Read-only writes, sibling access and symlink escapes were denied. A local-only `osascript` child had the same file-read restrictions; it sent no Apple Events. A Unix socket worked inside the app's own container without network entitlements. A matched relative-path control failed in the external state directory. All four signatures verified, and 181 assertions over the saved observations passed. Independent review found no substantive measurement defect.

This is native synthetic evidence only. Frozen Python, actual Things data, SQLite/WAL, Full Disk Access interaction, real MCP-client attribution and locked-session operation remain unverified. The packaging implementation therefore exposes sandboxing as an experimental profile, without changing the installed app or its permissions.

Parallel implementation is in progress across the generic core, Things capabilities and packaging. The core worker reports passing focused transport/journal/worker checks; authoritative integrated checks are still pending. The package metadata now includes the reusable core and locked source-build inputs. A dedicated build group pins PyInstaller 6.20.0 and hooks 2026.4. The lock refresh changed only group metadata and lock format; existing package versions and hashes stayed unchanged. Offline resolution lacked cached registry metadata, so the successful refresh used the registry.

The ClawBridge repository remains private, verified again after cloning. Its initial README remains on `main`; `codex/reference-implementation` is prepared for reviewable extracted code. A managed-worktree request did not return a result and was stopped; the clean clone is used explicitly while any late worktree result remains to be reconciled. No implementation has been pushed yet.

The Things branch is `codex/bridge-reference-2.5`. Two commits precede the current implementation: `473b296` records the plan, and `1dd2bed` makes live Things tests explicitly opt-in. Current changes cover the new core and packaging modules, Things providers and diagnostics, app scripts/configuration, focused tests and package metadata. Final checks, extraction, version integration and independent code review remain outstanding.

### Update — 4 November, integrated implementation checks

The generic core, Things integration and packaging implementation are now integrated. All 24 existing MCP tool names and signatures are retained, with three read-only diagnostic tools added. The core implements fixed action schemas, private Unix transport, bounded worker process groups and recovery records without replay. Things writes make one bridge attempt by default; explicit direct mode remains available. Reads retain per-call freshness and their original backend. Scripts and request values use stdin; ordinary logs also filter third-party request payloads. Cache reads reject unsafe files, and concurrent refreshes use separate private atomic files.

Build, signing and lifecycle scripts use declarative app configuration. Signing profiles are explicit; installation verifies the candidate before replacement and checks its authenticated identity, launchd process and executable. Recovery files remain available. The package, runtime and registry metadata now agree on candidate version 2.5.0; nothing has been released.

Authoritative integrated checks passed: 217 tests passed and 116 live tests were skipped; Ruff lint and formatting passed across the repository; mypy passed for 27 source files; configured Bandit found no issues, with existing comment-parser warnings; all four shell wrappers passed shellcheck; and the diff passed whitespace checks. The initial core test run inside Codex's outer sandbox could not bind temporary Unix sockets. The same synthetic tests passed when run outside that restriction. No live Things access or privacy change occurred.

Proof-first cases covered payloads in worker arguments, unsafe token paths, readiness/write-policy behaviour, cache concurrency and symlinks, and installation recovery. The standalone export, actual frozen bundle, full independent code review and final CI evidence remain outstanding. Real Things permissions, clean-client attribution and locked-session operation remain separate release acceptance gates.

### Update — 4 November, standalone and frozen verification

Commit `7da679122e1417b63c7e8f8988cb8b37da1bc1e2` integrates the reusable core, Things capabilities and packaging. Five independent simplification reviewers identified a shared write-result conversion and avoidable journal-list copying; these were consolidated without changing public results. Three redundant comments were removed. Proof tests were preserved. The LaunchAgent now accepts the documented payload-journal opt-in through a validated `0` or `1` installation variable; two tests first demonstrated the missing configuration and then passed.

The default source suite now passes 230 tests and skips 116 live tests. Ruff checks and formatting pass for 52 files, mypy passes for 27 source files, configured Bandit reports no findings, and all four shell wrappers pass shellcheck. The standalone export passes its 68 synthetic tests, Ruff, formatting, mypy for nine source files and configured Bandit. Both projects build wheels and source archives; archive inspection confirms locked build inputs and the standalone wheel contains no Things package. The exporter copies 33 explicit files plus a manifest, with no private README or recovery records.

The normal synthetic frozen app was built from clean `7da6791`: build identifier `0c5c20f1063b4d3888e0d8fcddb444ef`, executable SHA-256 `0eb2461ff879ca9f33d59d98ee5b9624c1709d06f58e3f80e91e33bdfa87d0fd`. A separate experimental sandbox build used `7da6791` with recorded uncommitted input hashes: build identifier `796540ea10b04ef2b55f136f46e87c77`, executable SHA-256 `5b1adca80f9195649a60f1cbd18339d354f1c6986438419af17928d2a2b0967e`. Both passed strict signature verification, exact process/build identity, authentication, Unicode echo, counter mutation, operation lookup, private file modes and output-leak checks. The sandboxed bundle and frozen worker ran inside their own container without network or Apple Events entitlements. Both were stopped after the checks; neither was installed as a service.

The reusable `scripts/smoke_example_bridge.py` performs those synthetic checks with fresh private state. CI now has an independent macOS build/sign/smoke job, and the standalone template has its own Linux and macOS workflow. CI has not yet run. The independently exported project also built and ran its synthetic frozen app successfully: build identifier `79110806c5704d439cc82ee4137dc69c`, executable SHA-256 `527cd08f502fc61e96e2244a2a5c929d6192ce2e79226117a4b9471a02d0de34`, with source revision and dirty input hashes retained. Workflow validation identified the obsolete setup-python v4 runtime; both workflows now use v6 and pass actionlint. Final review remains in progress. Live Things, Full Disk Access interaction, consent retention, locked-session checks, notarisation and deployment remain unperformed.
