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

Research covers current source, Apple permission/signing documentation, PyInstaller packaging, client parity and recovery flows. Implementation has not begun. Default tests will be made hermetic before broader execution; signed artifact and locked-session evidence will be recorded separately.
