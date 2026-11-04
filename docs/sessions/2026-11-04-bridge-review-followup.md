# Bridge review follow-up

Review run `20261104-161834-f8881209` assessed commit `1cfb4634370decfa610cd1df051efefd4668dbc9` and the subsequent comment-only simplification. The immutable local report is at `/private/tmp/compound-engineering-501/ce-code-review/20261104-161834-f8881209/review.json`.

Nine findings were confirmed. Findings 2, 3 and 4 have confidence 100. Findings 5 and 9 have confidence 75 and agreement from two review personas. An additional independent correctness review corroborated findings 1, 6, 7 and 8 at their existing confidence 75. It confirmed these are bounded repairs of the existing plan contracts, including graceful termination for finding 6. This record supplements the original report without changing its scores or evidence.

| Finding | Repair | Progress |
| --- | --- | --- |
| 1 | Block current and legacy Things worker launches in default tests | Regression failed before repair; all 18 safety tests now pass |
| 2 | Share the diagnostic timeout and report configuration failures | Five failing diagnostic regressions now pass; configured paths and live-only snapshots also verified |
| 3 | Accept an unknown cache timestamp with truthful provenance | Nullable timestamp accepted; other metadata remains strict |
| 4 | Preserve supported relation and date filter meanings | Boolean presence and exact start/deadline dates supported; unsupported date forms return explicit errors |
| 5 | Serialise installation and removal before taking rollback snapshots | Fourteen pre-fix regression failures resolved; private shared lock retained through rollback |
| 6 | Retain runtime ownership through orderly worker completion | Close-during-write and subprocess SIGTERM regressions failed before repair and now pass |
| 7 | Reuse supplied parent titles and per-response lookups | Supplied titles need no lookup; fallback results and failures cached once per response |
| 8 | Preserve completion-record warnings through MCP responses | Both success and failure retain the warning; known success stays successful |
| 9 | Report missing completed-task cache coverage explicitly | Completed, cancelled and all-status requests report missing snapshot coverage |

Review used independent in-process personas. The optional external Claude review could not authenticate. Automatic approval review rejected the proposed Grok code disclosure before any job started; the in-process adversarial review supplied that lens instead. No external peer result is claimed.

Ross explicitly requested repeating the full verification after fixes. He also requested multiple simplified adapters; the bounded work source is [the examples addendum](../plans/2026-11-04-clawbridge-examples-addendum.md). The implementation builds on PR #4; its head `f00de5a2780429b2a44ddeffdee8496b0078fc49` is an ancestor of this branch, and PR #4 remains unchanged.

The integrated post-fix suite passed 315 tests and skipped 116 live tests in 19.48 seconds. Ruff lint and formatting passed for 54 files, mypy passed for 28 source files including the diagnostic command, configured Bandit reported no issues (existing comment-parser warnings remain), four shell wrappers passed shellcheck, both CI workflows passed actionlint, and lock and whitespace checks passed. Provider changes added 63 regression cases; the worker observed pre-fix failures, excluding two initial test naming mistakes from proof. Further checks on the added examples and final signed bundles remain pending.
