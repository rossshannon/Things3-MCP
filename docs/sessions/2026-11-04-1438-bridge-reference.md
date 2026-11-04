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
