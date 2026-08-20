# Architectural Decisions

These decisions are reconstructed from current source/configuration and available artifacts. Historical author intent is not invented. Where rationale is inferred from enforcement code, it is marked as such.

## ADR-001 — One shared comparison graph with injected providers

- **Status:** ACTIVE
- **Decision:** Offline, supplied-Mock, and real workflows use one `ComparisonAgentState` and one LangGraph topology. Composition injects surrogate, optimizer, HFSS, evaluator, artifacts, checkpoint, and routing services.
- **Evidence level:** WIRED.
- **Evidence:** `composition.py`, `comparison_graph.py`, three `cli.py` run functions.
- **Consequence:** topology regressions affect every workflow; Mock runs are required before real HFSS.

## ADR-002 — Real HFSS requires explicit acknowledgement and a dedicated entry

- **Status:** ACTIVE
- **Decision:** `run_real_supplied_demo` rejects execution unless `execute_real_hfss=True`; the package CLI exposes only offline and supplied-Mock commands. `RUN_REAL_HFSS.py` checks a runtime enable flag.
- **Evidence level:** UNIT TESTED.
- **Evidence:** `test_real_workflow_requires_explicit_execution_acknowledgement`.
- **Consequence:** library construction is inert; a caller must deliberately cross the real-HFSS boundary.

## ADR-003 — Production builds and solves only `interposer_temple4`

- **Status:** ACTIVE
- **Decision:** contract design must equal `interposer_temple4` and metadata must require `target_design_only`; Production no longer constructs a duplicate `huitu` design.
- **Evidence level:** UNIT TESTED / HISTORICALLY VERIFIED.
- **Evidence:** real run guards, Builder project test, historical successful projects.
- **Consequence:** historical Builder documentation about two designs is reference history, not current Production behavior.

## ADR-004 — Baseline and candidate use new independent projects

- **Status:** ACTIVE
- **Decision:** every HFSS call creates a sanitized candidate directory plus unique run directory. Builder refuses to overwrite an existing project.
- **Evidence level:** UNIT TESTED / HISTORICALLY VERIFIED.
- **Evidence:** `GuardedHFSSAdapter._workspace`, `build_from_nine_parameters`, two historical workspaces/projects.
- **Consequence:** user/source projects are not mutated; disk usage accumulates and abandoned workspaces are preserved.

## ADR-005 — PyAEDT runs only in isolated stage workers

- **Status:** ACTIVE
- **Decision:** the Agent process does not import PyAEDT for Production. Build, solve, and extract run as separate JSON-protocol subprocesses with hard timeouts; backend process isolation is mandatory.
- **Evidence level:** INTEGRATION TESTED / HISTORICALLY VERIFIED.
- **Evidence:** worker/backend tests and historical stage responses.
- **Consequence:** failures are isolated and time-bounded; cross-stage AEDT sessions are reopened rather than shared.

## ADR-006 — Serialize configured AEDT access with a file lock

- **Status:** ACTIVE
- **Decision:** a per-AEDT-version atomic file lock surrounds build/solve/extract for one candidate.
- **Evidence level:** UNIT TESTED.
- **Evidence:** lock contention and stale-owner tests.
- **Consequence:** normal Agent concurrency is prevented; abrupt-parent lifecycle risk remains ISSUE-015.

## ADR-007 — Use an exact nine-parameter SI contract

- **Status:** ACTIVE
- **Decision:** upstream candidate values use metres, must contain exactly nine names, and map to nine unique AEDT variables. Display/config values use micrometres with explicit scale.
- **Evidence level:** UNIT TESTED / HISTORICALLY VERIFIED.
- **Evidence:** schema, contract, Builder mapping, validator tests, historical projects.
- **Consequence:** adding or renaming a parameter requires coordinated schema, optimizer, contract, and Builder changes.

## ADR-008 — Candidate variation belongs to the Agent optimizer

- **Status:** ACTIVE
- **Decision:** the Builder creates Setup1 and Sweep but no Optimetrics candidate sweep. The Agent selects candidates and builds independent projects.
- **Evidence level:** UNIT TESTED.
- **Evidence:** Builder analysis test and current `analysis.py`.
- **Consequence:** there is one candidate-state owner; HFSS frequency sweep remains inside the HFSS contract.

## ADR-009 — Preserve full complex two-port data and comparison metadata

- **Status:** ACTIVE
- **Decision:** exports retain S11/S12/S21/S22 complex real/imag matrices, frequency grid, physical/HFSS port order, 50-ohm reference, and comparison-context ID, plus Touchstone.
- **Evidence level:** UNIT TESTED / HISTORICALLY VERIFIED.
- **Evidence:** model/contract/worker tests and historical exports.
- **Consequence:** calibration can compare physics rather than scalar plot summaries; frequency endpoint gap remains ISSUE-019.

## ADR-010 — Rule evaluation is deterministic and refuses no-rule score fallback

- **Status:** ACTIVE BUT INTEGRATION BROKEN
- **Decision:** S-parameter evaluation requires explicit rules; no rules produce `INVALID` rather than using the older scalar `score` path.
- **Evidence level:** UNIT TESTED.
- **Evidence:** `test_no_rules_is_invalid_and_never_score_fallback`.
- **Consequence:** every formal entry must provide a rule contract. They currently do not (ISSUE-002), and legacy Best fields remain disconnected (ISSUE-004).

## ADR-011 — Diagnosis consumes Evaluation artifacts, not raw curves

- **Status:** ACTIVE
- **Decision:** `DiagnosisNode` derives issue type, band location, priority, migration, and optimization focus exclusively from `EvaluationResult` and optional comparison/baseline diagnosis.
- **Evidence level:** UNIT TESTED.
- **Evidence:** diagnosis tests and node signature.
- **Consequence:** evaluation validity and rule semantics are prerequisites for meaningful diagnosis.

## ADR-012 — Uncalibrated surrogate results are not physical validation

- **Status:** ACTIVE BOUNDARY, ENFORCEMENT PARTIAL
- **Decision:** supplied surrogate/optimizer results carry `uncalibrated` or `surrogate_only` status, and physical discrepancies are documented rather than automatically corrected.
- **Evidence level:** CODE PRESENT / HISTORICALLY SUPPORTED.
- **Evidence:** metadata, model-risk document, historical rank reversal.
- **Consequence:** real HFSS comparison remains mandatory. Calibration enforcement is not wired (ISSUE-009).

## ADR-013 — Checkpoints and artifacts are JSON files owned by the harness

- **Status:** ACTIVE
- **Decision:** the graph uses an explicit JSON checkpoint store and deterministic artifact directory rather than LangGraph persistence.
- **Evidence level:** UNIT TESTED; current resume E2E BROKEN.
- **Evidence:** harness tests and graph runner.
- **Consequence:** state is inspectable and portable, but resume is replay from START and has ISSUE-013/014 consistency risks.

