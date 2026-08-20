# Repository operating rules

This repository uses the Markdown files under `docs/` as its long-term project memory. Code, tests, configuration, run artifacts, and these documents must not silently diverge.

## Required reading before any task

1. Read `docs/PROJECT_STATUS.md`.
2. Read the documents relevant to the task:
   - architecture or module changes: `docs/ARCHITECTURE.md`;
   - workflow or entry-point changes: `docs/WORKFLOW_INVENTORY.md`;
   - bugs, risks, or regressions: `docs/ISSUE_REGISTER.md`;
   - test or verification claims: `docs/VALIDATION_MATRIX.md`;
   - long-lived design constraints: `docs/DECISIONS.md`;
   - recent work: the latest entries in `docs/WORK_LOG.md`.
3. Check whether Git metadata is available and inspect branch, HEAD, staged, unstaged, and untracked state. If Git metadata is unavailable, record `UNKNOWN / INSUFFICIENT EVIDENCE`; do not infer a commit.
4. Confirm the current Production Workflow from source and entry-point evidence, not from file names or older documentation.
5. Confirm related open issues and the current verification level before changing code.

## Evidence rules

Every capability or status claim must use one of these evidence levels:

- `PLANNED`
- `CODE PRESENT`
- `IMPLEMENTED`
- `WIRED`
- `UNIT TESTED`
- `INTEGRATION TESTED`
- `OFFLINE VERIFIED`
- `REAL HFSS VERIFIED`
- `END-TO-END VERIFIED`
- `HISTORICALLY VERIFIED`
- `NEEDS VERIFICATION`
- `BROKEN`

Do not use unqualified words such as `DONE`, `COMPLETE`, or `WORKS`. Code presence is not test evidence. A historical HFSS run is not evidence for a later working tree unless the exact code revision is traceable and identical.

Fact priority is:

1. current source;
2. current reachable call graph;
3. current tests and their actual result;
4. current configuration;
5. available Git state;
6. run artifacts and logs;
7. documentation;
8. comments, TODOs, and historical descriptions.

When evidence conflicts, preserve the conflict and use `UNKNOWN`, `NEEDS VERIFICATION`, or `INSUFFICIENT EVIDENCE`. Do not edit code merely to make documentation appear consistent.

## Production and HFSS safety

- The Production entry is currently `RUN_REAL_HFSS.py`, but readiness must always be rechecked in `docs/PROJECT_STATUS.md` and `docs/ISSUE_REGISTER.md`.
- Never infer permission to run the real HFSS Full Workflow from a request to inspect, document, test, or fix code.
- Before a real run, require passing current offline/E2E tests, a cleanly defined evaluation contract, and closure or explicit acceptance of all real-run blockers.
- Preserve the target-design-only boundary (`interposer_temple4`), independent baseline/candidate workspaces, worker-process isolation, hard timeouts, and the AEDT license lock unless a reviewed architectural decision changes them.
- Do not treat surrogate improvement as physical improvement without paired HFSS calibration evidence.

## Required updates before finishing a task

1. Update `docs/PROJECT_STATUS.md` when current status, blockers, readiness, or next step changes.
2. Update the relevant entries in `docs/ISSUE_REGISTER.md`; do not delete resolved issues.
3. Update `docs/VALIDATION_MATRIX.md` with tests actually run and their results.
4. Update `docs/WORKFLOW_INVENTORY.md` if an entry, route, provider, or reachability changes.
5. Update `docs/ARCHITECTURE.md` if state, graph, service, boundary, data flow, or artifact flow changes.
6. Update `docs/DECISIONS.md` only for long-lived architectural decisions.
7. Append a dated entry to `docs/WORK_LOG.md`. Never rewrite previous work-log entries except to correct a factual transcription error, which must itself be noted.

Code must not change while project-memory documents still describe the old behavior. If a task cannot update the evidence documents, report that limitation explicitly.

## Document ownership

- `PROJECT_STATUS.md`: concise current-state snapshot.
- `ARCHITECTURE.md`: current implementation only.
- `WORKFLOW_INVENTORY.md`: every identifiable runnable or internal workflow, including Mock, Test, Reference, and unreachable paths.
- `ISSUE_REGISTER.md`: open, partially resolved, resolved, and verification-needed issues with evidence.
- `VALIDATION_MATRIX.md`: capability-by-capability proof level.
- `DECISIONS.md`: durable architectural decisions and their evidence.
- `WORK_LOG.md`: append-only chronological task history.

