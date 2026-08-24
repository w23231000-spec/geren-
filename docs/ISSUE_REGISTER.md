# Issue Register

Baseline: `FS-2026-08-20`. Issues are retained after resolution; status changes require evidence.

## Summary

| ID | Severity | Status | Classification | Title |
|---|---|---|---|---|
| ISSUE-001 | BLOCKER | RESOLVED | BUG / REGRESSION | Undefined `evaluation` crashed optimization-intent output |
| ISSUE-002 | BLOCKER | RESOLVED | INTEGRATION / EVALUATION | WF-001 lacked a Production Evaluation Contract |
| ISSUE-003 | BLOCKER | RESOLVED | BUG / REGRESSION | Candidate comparison called unimported `emit_status` |
| ISSUE-004 | HIGH | RESOLVED | EVALUATION / STATE | Rule comparison could not drive Best update or summary |
| ISSUE-005 | HIGH | RESOLVED | OPTIMIZATION / ARCHITECTURE | Diagnosis objective did not control supplied optimizer |
| ISSUE-006 | HIGH | RESOLVED | STATE / HFSS | Failed/invalid candidate paths could finish as completed |
| ISSUE-007 | HIGH | RESOLVED | MOCK / INTEGRATION | Mock frequency grid conflicted with evaluation plan |
| ISSUE-008 | HIGH | RESOLVED | TEST / REGRESSION | Graph E2E/resume tests failed and traces were stale |
| ISSUE-009 | HIGH | PARTIALLY RESOLVED | EVALUATION / OPTIMIZATION | Calibration gate is wired; no accepted current paired evidence exists |
| ISSUE-010 | HIGH | RESOLVED FOR COLLECTION | HFSS / MODEL | Builder-authoritative model alignment is versioned and approved; physical correlation remains gated by Calibration |
| ISSUE-011 | HIGH | PARTIALLY RESOLVED | REPRODUCIBILITY | New Git baseline exists; original history remains unavailable |
| ISSUE-012 | HIGH | OPEN | VALIDATION | Historical real E2E cannot be attributed to current working tree |
| ISSUE-013 | MEDIUM | PARTIALLY RESOLVED | STATE / RESUME | Action receipts make START replay safe, but saved-node continuation is absent |
| ISSUE-014 | MEDIUM | RESOLVED | ARTIFACT / SAFETY | Formal task containment, immutable publish, and same-Run concurrency are guarded |
| ISSUE-015 | MEDIUM | PARTIALLY RESOLVED | HFSS / CONCURRENCY | License lock ownership may outlive/diverge from Agent PID |
| ISSUE-016 | MEDIUM | PARTIALLY RESOLVED | ARTIFACT | New V2 actions reconcile stale leases; historical V1 runs remain unchanged |
| ISSUE-017 | MEDIUM | PARTIALLY RESOLVED | DOCUMENTATION | README and older architecture/status claims drift from current evidence |
| ISSUE-018 | MEDIUM | RESOLVED OFFLINE | TEST / ENVIRONMENT | Pure Builder parameter mapping tests no longer import PyAEDT |
| ISSUE-019 | MEDIUM | RESOLVED OFFLINE | HFSS / VALIDATION | Shared fail-closed validation checks the full returned grid against the sweep contract |
| ISSUE-020 | LOW | OPEN | DOCUMENTATION / UX | 14 displayed stages do not map one-to-one to 18 graph nodes |
| ISSUE-021 | HIGH | RESOLVED | HFSS / BUILDER | Explicit material SolveInside classification regression |
| ISSUE-022 | HIGH | RESOLVED | HFSS / ARCHITECTURE | Production target-only design and independent project boundary |
| ISSUE-023 | HIGH | RESOLVED | ENVIRONMENT / REPRODUCIBILITY | Package CLI imported a stale installation from another workspace |
| ISSUE-024 | BLOCKER | RESOLVED | SAFETY / ENTRY | Real-HFSS entry was enabled despite NOT READY project status |
| ISSUE-025 | HIGH | RESOLVED | STATE / RESUME | V2 checkpoint restores nested evaluation contract types; V1 is evidence-only |
| ISSUE-026 | HIGH | PARTIALLY RESOLVED | HFSS / PROCESS SAFETY | Cancellation and timeout did not guarantee worker termination |
| ISSUE-027 | MEDIUM | RESOLVED OFFLINE | ARTIFACT / PROVENANCE | Provider-native files were not immutable RunStore artifacts |
| ISSUE-028 | HIGH | PARTIALLY RESOLVED | REPRODUCIBILITY / RESUME | Provider/code fingerprints are optional and may be empty |
| ISSUE-029 | HIGH | RESOLVED OFFLINE | AGENT CONTROL / ROUTING | Candidate queue and diagnosis had no feedback loop |
| ISSUE-030 | HIGH | RESOLVED OFFLINE | RELIABILITY / RECONCILIATION | UNKNOWN/corrupt checkpoints lacked evidence-bound recovery and chaos proof |

| ISSUE-031 | BLOCKER | RESOLVED OFFLINE | CALIBRATION / AUTHORITY | Calibration Evidence 1.1 is policy/cardinality/provider/artifact/recomputation bound |
| ISSUE-032 | BLOCKER | RESOLVED OFFLINE | HFSS / RUNTIME | AEDT 2025 R1 Python 3.10 could not import the isolated worker entry |
| ISSUE-033 | HIGH | RESOLVED FOR NEW RUNS | RELIABILITY / RECONCILIATION | Calibration campaign did not preregister UNKNOWN reconciliation authority |
## Issue details updated by current status

### ISSUE-004 — Rule comparison cannot drive Best update or summary

- **Classification:** EVALUATION / STATE / CAUSAL DISCONNECT
- **Severity / status:** HIGH / RESOLVED on 2026-08-21
- **Location:** `evaluation/evaluator.py::evaluate_sparameters` returns `improved=False, score=0.0`; `comparison_nodes.py::update_hfss_best`; `cli.py::_summary`.
- **Description:** rule improvement is represented in `EvaluationComparison.classification`, while Best and summary read unrelated legacy fields from `EvaluationResult`.
- **Impact before repair:** Optimization result reporting and Best persistence; an improved candidate could not replace baseline under the default evaluator.
- **Trigger:** any valid rule-based candidate comparison.
- **Evidence:** direct return construction and update predicate; the 2026-08-20 safe rule-configured WF-001 Graph now reports comparison `FULLY_ACHIEVED` but finishes with `BEST=baseline` and `update_hfss_best:retained`.
- **Fix:** `EvaluationComparison` now owns `promotion_eligible`/`promotion_reason`; Best validates candidate/result identity and consumes that comparison contract. CLI summary and Best artifact record the same classification rather than legacy scalar fields.
- **Evidence after:** the rule-configured Production-band test route and deterministic Offline E2E both report `FULLY_ACHIEVED`, write `update_hfss_best:updated`, and persist `optimized-001` as Best. Full main suite: 115 passed.
- **Fixed:** yes; real HFSS was not run.

### ISSUE-005 — Diagnosis objective does not control supplied optimizer

- **Classification:** OPTIMIZATION / ARCHITECTURE / CAUSAL DISCONNECT
- **Severity / status:** HIGH / RESOLVED on 2026-08-21
- **Location before repair:** `optimization/supplied_optimizer_adapter.py::optimize`.
- **Description before repair:** vendor `execute` ran from static TOML/CSV before `optimization_objective` was copied into metadata, and the adapter returned only one recommendation.
- **Resolution:** Phase 3 adds canonical `OptimizerRequest`/`EffectiveObjective`. Goal, diagnosis, intent priority/penalty, baseline evidence, and fingerprints contribute to request identity. The supplied worker materializes a request-specific vendor objective CSV before `execute`, verifies the vendor summary used exactly that objective, and returns the full Pareto candidate set with evidence/digests.
- **Evidence:** independent Goal and Diagnosis perturbation regressions change the request digest; actual supplied quick-worker integration returns the effective-objective digest and multiple auditable Pareto candidates; Graph persists per-candidate surrogate ranking evidence. Full main suite passes offline.
- **Residual boundary:** the current graph consumes one selected candidate and has no feedback iteration; calibration remains ISSUE-009. Those are not a continuation of this causal-disconnect defect.
- **Fixed:** yes for the formal supplied optimizer path on 2026-08-21; real HFSS was not run.

### ISSUE-006 — Failed/invalid candidate paths can finish as completed

- **Classification:** STATE / HFSS / ERROR HANDLING
- **Severity / status:** HIGH / OPEN
- **Location:** `run_candidate_hfss`, candidate gate, `decide_after_hfss`, and `complete` in `comparison_nodes.py`.
- **Description before repair:** candidate provider failure, invalid evaluation, and gate/target STOP all flowed to unconditional `WorkflowStatus.COMPLETED`.
- **Impact before repair:** Production/Demo status could report success without a valid candidate comparison.
- **Trigger:** candidate provider failure, gate rejection, invalid evaluation, or target not passed.
- **Evidence:** graph edges and unconditional complete node.
- **Fix:** added first-class `TerminalOutcome` plus `succeeded_baseline`, `succeeded_candidate`, `rejected`, `invalid`, `failed`, and `cancelled`; formal entry exit codes consume the same status. Historical `completed` maps to failure exit code and is not emitted by current graph completion.
- **Evidence after:** unit terminal-policy/exit-code tests plus Offline Graph success, gate rejection, degraded candidate, and Production-band success routes pass.
- **Fixed:** yes; cancellation lifecycle itself remains separate ISSUE-026.

### ISSUE-007 — Mock frequency grid conflicts with default evaluation plan

- **Classification:** MOCK / INTEGRATION
- **Severity / status:** HIGH / RESOLVED on 2026-08-21
- **Location:** `cli.py` MockHFSS grids `(1,2,3)` GHz; `FrequencyPlan` defaults to core 6–18 GHz with 5–19 GHz margins.
- **Description before repair:** empty rules and a Production-default 5–19 GHz plan made the 1–3 GHz Mock route invalid and unable to exercise rule comparison.
- **Impact before repair:** Offline and supplied-Mock verification could not provide a coherent no-AEDT rule-evaluation path.
- **Trigger:** configure current intended rules without changing Mock grids.
- **Evidence:** source configuration and evaluator range validation.
- **Fix:** added explicit `offline-evaluation-v1` with 1–3 GHz hard/soft bands and deterministic baseline-relative Mock curves. It is Mock-only and does not redefine Production Contract v1.
- **Evidence after:** deterministic Offline E2E reaches valid baseline/candidate rule comparison; full main suite passes.
- **Fixed:** yes for WF-002 and shared Mock contract; WF-003 formal E2E was not run in Phase 0.

### ISSUE-008 — Current graph E2E and resume tests fail and expected traces are stale

- **Classification:** TEST / REGRESSION
- **Severity / status:** HIGH / RESOLVED on 2026-08-21
- **Location:** `tests/test_cli.py`, `tests/test_comparison_graph.py`.
- **Description before repair:** six tests used empty rules and pre-diagnosis traces, so they stopped before candidate stages.
- **Impact before repair:** current Offline E2E, checkpoint, and completed-run reuse could not be claimed.
- **Trigger:** main test suite.
- **Evidence before:** 2026-08-20 post-ISSUE-003 suite: 107 collected, 101 passed / 6 failed.
- **Fix/evidence after:** fixtures now load the explicit Offline contract, traces include all 18 nodes on the full route, and completed-checkpoint reuse is asserted. 2026-08-21 main suite: 115 passed.
- **Fixed:** yes for the stale tests and completed-run reuse. At Phase 0 close, mid-run semantic resume remained ISSUE-025; Phase 1 subsequently resolved its V2 type-fidelity defect and made V1 evidence-only.

### ISSUE-009 — Calibration gate is wired; no accepted current paired evidence exists

- **Classification:** EVALUATION / OPTIMIZATION / MODEL
- **Severity / status:** HIGH / PARTIALLY RESOLVED on 2026-08-22
- **Location:** `evaluation/calibration.py`, `domain/contracts.py::CalibrationEvidence`, `harness/real_hfss_safety.py`, `harness/run_store.py`; historical run `real-vscode-20260818-101711`.
- **Description before Phase 5C:** the calibration API existed but Production never gated on it. A reconstruction-only calculation from the historical paired run found mean complex RMSE 0.07320, mean dB RMSE 3.327 dB, and pairwise ranking agreement 0.0. Surrogate predicted candidate improvement while HFSS worsened.
- **Impact:** Optimization/physical conclusions; surrogate recommendation is not trustworthy as a performance claim.
- **Trigger:** use surrogate ranking as evidence of HFSS improvement.
- **Phase 5C resolution:** added strict canonical `calibration-evidence/1.0` binding paired cases, policy/report, context, provider fingerprints, source artifact IDs, pass status, and digest. A real Readiness Manifest must embed passing evidence; readiness workflow binding and RunStore registration independently reject failing, context-mismatched, digest-drifted, or provider-drifted evidence before worker/action admission.
- **Evidence after:** canonical round-trip/drift tests, readiness rejection tests, formal real-composition binding test, and full main suite pass offline. No HFSS/AEDT was launched.
- **Current residual:** no accepted calibration evidence exists yet for the current exact code/provider/model combination. The historical evidence remains a calibration failure and cannot authorize a Canary. ISSUE-031 is resolved offline; ISSUE-009 remains the physical-data gate until the authorized three-case campaign passes.
- **Workaround:** keep physical claims blocked and create reviewed paired evidence under separately authorized solve/data collection.
- **Fixed:** partially; authority enforcement and collection are `OFFLINE VERIFIED`, while current physical calibration remains absent until the authorized campaign executes.
- **Suggested next action:** after clean exact-revision offline verification, collect baseline plus two deterministic candidates and issue a matching Canary manifest only if it passes.

### ISSUE-010 — Physical model alignment is versioned for collection

- **Classification:** HFSS / MODEL
- **Severity / status:** HIGH / RESOLVED FOR COLLECTION on 2026-08-24
- **Location:** `config/model_alignment.hfss_builder_v1.json`, `config/hfss_contract.pa_multi_2025_1.json`, Builder materials, equivalent model formulas.
- **Resolution:** the user designated the existing HFSS Builder as physical-model authority. A strict versioned alignment binds the exact HFSS contract ID, `interposer_temple4`, the 200-point 0.1–20 GHz comparison grid, input/output ports, 50 ohms, PI 3.5/0.02, SiO2 4.0, and surrogate PI 3.5. The HFSS material contract records the approved Builder value. Empirical `Gsub`, `Rlf1`, and `alpha` terms are explicitly accepted only if the paired Calibration policy passes, rather than silently claimed as physically validated.
- **Impact:** surrogate/HFSS comparison and any physical conclusion.
- **Trigger:** treating automated completion as calibrated model validation.
- **Evidence:** current config/source and historical ranking reversal.
- **Evidence:** strict loader rejects unknown/drifted fields and binds the current HFSS contract/context; focused policy/alignment/readiness tests pass offline. The changed tree has not yet run HFSS.
- **Fixed:** yes for the prerequisite decision/versioning gap. Physical correlation remains ISSUE-009 and can only become `REAL HFSS VERIFIED` through the exact authorized Calibration campaign.

### ISSUE-011 — New Git baseline exists; original history remains unavailable

- **Classification:** REPRODUCIBILITY / PROJECT STATE
- **Severity / status:** HIGH / PARTIALLY RESOLVED
- **Location:** current project root; new `.git` created after provenance audit.
- **Description:** original branch, commits, remote, staged state, and historical lineage could not be recovered. A new repository now provides prospective traceability from the reconstructed filesystem baseline only.
- **Impact:** future change review and rollback are now possible from the new anchor; historical validation attribution remains unavailable.
- **Trigger:** any claim that the new root commit recovers or represents the original repository history.
- **Evidence:** root commit `52dc0dea34df0f85e53e43ca91bdf56cacf7b0ff` on `master`, message `baseline: reconstructed project state before integration fixes`; no remote configured. Pre-initialization audit found no credible original `.git` copy or remote.
- **Workaround:** call the root commit `NEW REPOSITORY BASELINE`, retain `FS-2026-08-20` hashes, and never describe it as recovered original history.
- **Fixed:** partially; prospective Git traceability is established, original provenance is still unknown.
- **Suggested next action:** preserve atomic commits from this anchor; configure a remote only under separate explicit authorization.

### ISSUE-012 — Historical real E2E cannot be attributed to current working tree

- **Classification:** VALIDATION / REPRODUCIBILITY
- **Severity / status:** HIGH / OPEN
- **Location:** `runs/real-vscode-20260818-101711`, core files modified 2026-08-19.
- **Description:** historical task metadata has no Agent/Builder commit or source hash. Current graph/node/evaluator/diagnosis/intent/terminal files postdate the run.
- **Impact:** real baseline, candidate, and Full E2E status for current tree.
- **Trigger:** using the 2026-08-18 run to claim current real verification.
- **Evidence:** artifact and file timestamps; the historical run contains no source manifest, and the new Git history begins afterward at `52dc0de`. Vendor optimizer hashes match, but Agent/Builder equivalence remains unknown.
- **Workaround:** label evidence `HISTORICALLY VERIFIED` only.
- **Fixed:** no.
- **Suggested next action:** add full source/commit manifest to future run metadata after blockers are closed.

### ISSUE-013 — Resume restarts at graph START

- **Classification:** STATE / RESUME
- **Severity / status:** MEDIUM / PARTIALLY RESOLVED on 2026-08-21
- **Location:** `workflow_runner.py::ComparisonWorkflowRunner.invoke`, Closed-loop V2 node reuse checks.
- **Description:** V2 state is still reinvoked from START rather than a saved LangGraph node. Phase 2 makes external-action replay receipt-driven and at-most-once, but it is not true node continuation.
- **Impact:** Resume, audit history, artifact consistency.
- **Trigger:** invoke a runner with loaded checkpoint.
- **Phase 1 fix:** State V2 stores immutable facts once, uses IDs instead of duplicate histories/current/Best values, reuses immutable facts, and rejects conflicts. Legacy V1 is never resumed as execution.
- **Phase 2 fix:** SQLite action receipts commit canonical decoded provider results before Graph checkpoints. A crash after provider success replays the `SUCCEEDED` receipt without another physical call; `RUNNING` lease loss becomes `UNKNOWN`, keeps budget, moves the Run to `WAITING_RECONCILIATION`, and is never automatically retried. Run invocation fencing serializes Graph writers. Completed Runs return their existing terminal checkpoint without ledger mutation.
- **Phase 4/5D improvement:** the V2 controller and its budgets/decision history are canonical checkpoint State and are now the sole formal Production/Mock topology. Re-entry from START reuses evidence/receipts and the bounded graph can continue queue/reoptimization decisions without repeating completed physical callbacks.
- **Phase 5B improvement:** `operation-reconciliation/1.0` plus the RunStore reconciliation ledger now accepts one short-lived, pre-registered, exact Run/operation/attempt authority. Confirmed success requires a recovered strict result receipt; confirmed failure forbids one. Neither creates an attempt, refunds budget, or authorizes automatic retry.
- **Evidence:** every action/checkpoint crash boundary, two simultaneous receipt resumes, persistent UNKNOWN, operator success/failure/conflict/expiry/revocation, completed strict no-op, controller round-trip, bounded-loop E2E, and the final Phase 5D 205-test full-suite pass offline.
- **Residual risk:** LangGraph execution still begins at START rather than the saved node. Reconciliation repairs ledger truth and safe replay, not LangGraph program-counter continuation.
- **Fixed:** partially; external-action duplication and explicit UNKNOWN resolution are addressed, saved-node continuation is not.
- **Suggested next action:** evaluate true saved-node continuation only as a separate reliability enhancement; Phase 5D removed the manual/legacy Graph route without changing the real readiness boundary.

### ISSUE-014 — Task ID path containment and same-ID concurrency are unguarded

- **Classification:** ARTIFACT / SAFETY
- **Severity / status:** MEDIUM / RESOLVED for the formal Phase 2 workflow on 2026-08-21
- **Location:** `harness/artifacts.py::ArtifactStore`, `harness/run_store.py`, `HarnessCore.run_invocation`.
- **Description before repair:** `root / task_id` was not resolved/validated under root. Concurrent identical task IDs shared artifact and temporary paths.
- **Impact:** Artifact overwrite/collision; CLI path escape within process permissions.
- **Trigger:** crafted/absolute task ID or two same-ID launches.
- **Fix:** task/path segments are validated and resolved under the configured root; authoritative JSON artifacts use operation/attempt/content identities, unique fully-fsynced temporary files, and create-once hard-link publication; digest/size are verified on replay. Run invocation fencing serializes same-Run Graph writers and semantic operation keys deduplicate equivalent actions even when caller keys differ.
- **Evidence:** path escape, tamper, concurrent same-content publish, different-content retention, injected pre-publication crash, duplicate-action concurrency, and concurrent same-Run Graph regressions pass offline.
- **Residual boundary:** legacy fixed-path compatibility writers are not called by the formal Graph. Phase 5C subsequently resolved selected provider-native file immutability for formal Harness paths under ISSUE-027.
- **Fixed:** yes for formal authoritative artifacts and same-Run workflow concurrency.

### ISSUE-015 — License lock ownership may diverge from actual AEDT work

- **Classification:** HFSS / CONCURRENCY
- **Severity / status:** MEDIUM / PARTIALLY RESOLVED on 2026-08-21
- **Location:** `harness/license_lock.py`, subprocess Worker lifecycle.
- **Description before Phase 3:** lock payload recorded Agent PID. If Agent died while Worker/AEDT survived, a later Agent could reclaim the lock after seeing the parent PID dead.
- **Impact:** license contention and concurrent HFSS safety.
- **Trigger:** abrupt Agent termination while a Worker child survives.
- **Phase 3/5B mitigation:** the formal worker is assigned to a kill-on-close Windows Job before resume. Heartbeat/deadline/cancel paths terminate the Job and require verified zero active processes. Any unverified HFSS descendant state becomes `UNKNOWN` and atomically quarantines the held lock; a quarantine can only be archived through an accepted exact reconciliation attesting an empty process tree and marker bytes/token.
- **Evidence:** real Windows parent+child timeout/cancel and abrupt supervisor-parent-death regressions prove no residual test processes; injected kill-verification/unverified-descendant paths prove `UNKNOWN`, retained quarantine, reacquire rejection, and evidence-bound idempotent archive. Windows PID liveness checks `STILL_ACTIVE`.
- **Residual:** no current-tree real AEDT process was launched, so actual AEDT descendant enrollment/termination and license behavior remain `NEEDS VERIFICATION`.
- **Fixed:** partially; offline lifecycle and quarantine contract are verified, real AEDT remains blocked.

### ISSUE-016 — Historical runs remain marked running after process exit

- **Classification:** ARTIFACT / STATE
- **Severity / status:** MEDIUM / PARTIALLY RESOLVED on 2026-08-21
- **Location:** several `runs/real-vscode-*` checkpoints/journals from 2026-08-17.
- **Description:** four checkpoints and journals remain `running` at build/release stages despite no active lock. No terminal reconciliation marks interrupted runs.
- **Impact:** run inventory, monitoring, restart decisions, audit accuracy.
- **Trigger:** forced process termination.
- **Evidence:** parsed checkpoint/journal inventory.
- **Phase 2 behavior for new V2 Runs:** action and Run invocation leases heartbeat while owned. An expired `RUNNING` action atomically becomes `UNKNOWN`, retains its budget, and moves the Run to `WAITING_RECONCILIATION`; it cannot be automatically retried. Interrupted V1/V2-without-ledger checkpoints are durably classified and remain blocked even if the source file is later removed.
- **Evidence:** operation-heartbeat, expired-attempt, durable V1 classification, and waiting-checkpoint crash regressions pass offline.
- **Residual:** historical pre-RunStore directories are intentionally not rewritten or retroactively upgraded. The new operator workflow applies only to RunStore operations with exact attempt/approval evidence.
- **Fixed:** partially for new V2 RunStore executions; historical evidence remains unchanged.

### ISSUE-017 — Documentation drift

- **Classification:** DOCUMENTATION
- **Severity / status:** MEDIUM / PARTIALLY RESOLVED
- **Location:** root README, `VSCode_使用说明.md`, vendor READMEs, previous `docs/ARCHITECTURE.md`.
- **Description:** older docs claim a runnable complete demo, omit diagnosis/intent/objective, say full real Solve/candidate validation is still pending, and describe vendor files (`frontend.py`, root `run.py`, two designs) that are absent or no longer Production behavior.
- **Impact:** handoff, run safety, architecture understanding.
- **Trigger:** following old docs without checking current memory files.
- **Evidence:** source/entry comparison and historical artifacts.
- **Workaround:** use the 2026-08-20 memory documents as current source of status truth.
- **Fixed:** partially: project-memory docs now record drift; older user-facing docs remain unchanged by this baseline-only task.
- **Needs verification:** future documentation update must not conceal open code issues.
- **Suggested next action:** after code stabilization, reconcile README/usage docs with authoritative memory files.

### ISSUE-018 — Standalone Builder parameter test is PyAEDT-independent

- **Classification:** TEST / ENVIRONMENT
- **Severity / status:** MEDIUM / RESOLVED OFFLINE on 2026-08-24
- **Location:** `vendor/hfss_builder/parameter_mapping.py`, `nine_parameter_builder.py`, and `test_nine_parameter_builder.py`.
- **Description:** explicit test collection under project `.venv` fails because PyAEDT is installed only in the separate interpreter.
- **Impact:** current standalone Builder-test verification; main suite still tests Builder units through stubs.
- **Trigger:** pytest collecting the vendor Builder test under Agent Python.
- **Evidence:** 2026-08-20 collection error `ModuleNotFoundError: ansys`.
- **Resolution:** exact-nine validation and metre-to-mm Builder mapping moved to a pure module with no `ansys` import. The actual build function still imports the audited PyAEDT Builder only when a build is requested.
- **Evidence:** standalone Builder mapping suite passes under the Agent `.venv` without importing or constructing AEDT; main tests also pass this boundary.
- **Fixed:** yes offline. This does not claim a real project build.

### ISSUE-019 — HFSS return grid endpoints are not checked against contract

- **Classification:** HFSS / VALIDATION
- **Severity / status:** MEDIUM / RESOLVED OFFLINE
- **Location:** `pyaedt_worker.py::_extract`, `hfss/converter.py`, `ComplexSParameters` validation.
- **Description:** The authoritative converter and PyAEDT Worker now share `validate_sweep_frequency_grid`. It requires finite strictly increasing frequencies, exact point count, and point-by-point agreement with linear/log contract grids using 1 Hz absolute plus `1e-12` relative tolerance. An explicit sweep fails closed because the current contract cannot declare its intermediate points.
- **Impact:** evaluation and surrogate/HFSS comparability.
- **Trigger:** HFSS returns an unexpected but monotonic equal-length grid.
- **Evidence:** focused fake/contract suite `PASS` (33); endpoint, interior, count, unit drift, explicit fail-closed, and Guarded Adapter pre-acceptance failure regressions pass; full offline suite `PASS` (213). Real AEDT remains `NOT RUN`.
- **Workaround:** no longer required for the formal path; provider-native output remains supporting evidence.
- **Fixed:** yes, `RESOLVED OFFLINE`; current AEDT behavior is still `NEEDS VERIFICATION`, not `REAL HFSS VERIFIED`.
- **Suggested next action:** preserve this rule in a separately authorized current-revision calibration/Canary and retain the returned native grid as immutable evidence.

### ISSUE-020 — Displayed stage count differs from graph-node count

- **Classification:** DOCUMENTATION / UX
- **Severity / status:** LOW / OPEN
- **Location:** `ComparisonWorkflowNodes._announce` calls and README stage claims.
- **Description:** 18 nodes share 14 displayed numbers. The real order also announces `build_optimization_objective` as stage 6 before `run_optimizer` announces stage 5, so numbering can move backward and is not a unique execution trace.
- **Impact:** operator diagnosis and presentation clarity only.
- **Trigger:** any workflow run.
- **Evidence:** graph/node mapping.
- **Workaround:** use `execution_trace` and artifacts for exact progression.
- **Fixed:** no.
- **Suggested next action:** document substeps or assign stable unique stage identifiers.

### ISSUE-024 — Real-HFSS entry was enabled despite NOT READY project status

- **Classification:** SAFETY / ENTRY / CONFIGURATION
- **Severity / status:** BLOCKER / RESOLVED on 2026-08-21
- **Location before repair:** `runtime_config.json`, `RUN_REAL_HFSS.py`, VS Code launch 3.
- **Description before repair:** repository configuration had `real_hfss_enabled=true`, and the formal wrapper converted that boolean directly into `execute_real_hfss=True` despite project memory saying NOT READY. It did not require a readiness decision or authorization identity.
- **Impact before repair:** the user-facing formal entry could start two high-cost real HFSS solves while known blockers remained.
- **Fix:** default config is disabled and blocked; canonical entry validates enabled flag, exact `AUTHORIZED_CANARY` readiness marker, and non-empty authorization ID before checking/composing external providers. The VS Code launch is labelled blocked until separately authorized. The callable real composition retains its explicit acknowledgement and now also requires an authorization ID.
- **Evidence:** four fail-closed configuration tests and real-composition acknowledgement tests pass; current repository configuration is rejected by the validator.
- **Phase 2 strengthening:** real `hfss` actions now require a Run-bound approval identity matching the manifest fingerprint, authoritative nonzero cost, action receipt, and fail-closed ambiguity policy. Missing/expired/revoked/mismatched approvals are rejected before attempt/budget/provider start.
- **Phase 5A strengthening:** the interim marker/string was replaced by strict short-lived Readiness Manifest V1 with clean exact-HEAD, Goal/Run/contracts/providers/PyAEDT, expiry, approval, and two-launch/no-retry binding. Drift fails before worker composition, and RunStore transactionally rejects a third real solve authorization.
- **Fixed:** yes for the entry interlock, exact formal readiness identity, and per-Run action approval/budget/solve-ceiling boundary. No manifest is checked in or automatically issued.
- **HFSS/AEDT:** NOT RUN.

### ISSUE-025 — Checkpoint JSON does not preserve nested evaluation contract types

- **Classification:** STATE / RESUME / SERIALIZATION
- **Severity / status:** HIGH / RESOLVED for State V2 on 2026-08-21
- **Location before repair:** V1 `comparison_state_from_dict`, strict `EvaluationComparator._same_rules`, frequency-plan comparison.
- **Description before repair:** JSON converted nested tuples to lists and V1 reconstruction passed them directly into `EvaluationResult`; equal contracts could compare as `INVALID` after resume.
- **Resolution:** `EvaluationRecord.from_dict` strictly reconstructs the evaluation contract and `to_result()` restores tuple semantics. The canonical codec and exact-field contract reject malformed values before checkpoint. V1 is dual-read only as historical evidence or waiting reconciliation and cannot resume execution.
- **Migration safety:** new writes are V2 only. An existing V1 `checkpoint.json` is preserved; V2 is written to `checkpoint.v2.json`.
- **Evidence:** tuple/list semantic regression, State/Manifest round-trip, V1 completed/interrupted classification, V1 no-overwrite, and Graph checkpoint integration all pass.
- **Phase 2 migration strengthening:** interrupted and completed V1 classifications are persisted to SQLite as non-actionable evidence/waiting state; deleting the source afterward does not make the Run executable. Legacy V2 import requires full manifest identity equality.
- **Residual boundary:** saved-node continuation remains ISSUE-013.
- **Fixed:** yes for the reported type-fidelity defect and unsafe V1 execution resume.

### ISSUE-026 — Cancellation and timeout do not guarantee worker termination

- **Classification:** HFSS / PROCESS SAFETY / CONCURRENCY
- **Severity / status:** HIGH / PARTIALLY RESOLVED on 2026-08-21
- **Location:** `hfss/worker_backend.py` subprocess cancellation, timeout, and close paths.
- **Description before repair:** KeyboardInterrupt/cancellation could leave a local worker/AEDT process alive while the adapter released its lock. Timeout cleanup ignored `taskkill` outcome and then performed an unbounded wait.
- **Impact:** orphan AEDT processes, license/lock divergence, overlapping real work, and ambiguous retry safety.
- **Phase 3/5B resolution:** optimizer and HFSS subprocesses use one bounded supervisor. Windows starts suspended, assigns a kill-on-close Job Object, resumes, monitors heartbeat/deadline/cancel, terminates the whole Job, and verifies zero active processes within finite grace. There is no unbounded `wait()` or ignored `taskkill` path. Keyboard interruption follows the same bounded cleanup path; Job close on abrupt supervisor-parent death is now exercised.
- **Evidence:** offline Windows parent+descendant timeout, cancellation, and parent-death tests finish within asserted bounds and leave test PIDs dead. Injected termination-verification failure becomes `UNKNOWN`; explicit quarantine release requires accepted empty-process evidence.
- **Residual:** real AEDT was not launched. The composite action has a strict total upper bound (build + solve + extract configured budgets plus termination grace), but separate per-stage deadlines inside that one worker are not claimed.
- **Fixed:** partially: generic Windows process contract is `OFFLINE VERIFIED`; real AEDT lifecycle is `NEEDS VERIFICATION`.

### ISSUE-027 — Provider-native files were not immutable RunStore artifacts

- **Classification:** ARTIFACT / PROVENANCE
- **Severity / status:** MEDIUM / RESOLVED OFFLINE on 2026-08-22
- **Location:** supplied optimizer output directories; `GuardedHFSSAdapter` workspaces/journals/projects/Touchstone; worker request/response files.
- **Description before Phase 5C:** RunStore protected canonical Tool results, but provider-native request/response/report, `.aedt`, Touchstone, and journal bytes remained mutable workspaces outside the receipt transaction.
- **Impact:** cached control decisions are protected, but a later audit cannot use the canonical result receipt alone to prove that each `.aedt`, `.s2p`, plot, or worker response is byte-identical.
- **Phase 5C resolution:** `HarnessCore.execute` now freezes provider-declared files after provider completion and before operation commit. `ArtifactStore.write_immutable_file` uses a stable-source check, fsynced unique temporary file, content-addressed create-once publication, size/SHA receipt, and media type. RunStore registers the primary JSON receipt and every supporting receipt in the same fenced `SUCCEEDED` transaction. Cached reuse verifies all receipts. HFSS project/artifact paths and supplied optimizer worker/request/response/vendor paths are wired to this boundary; selected directory scans are bounded to 256 approved files.
- **Evidence:** fake `.aedt` immutable-copy/mutable-source/replay regression, concurrent Touchstone publication, supplied-worker and Graph integration, and 195-test full-suite pass. Freeze/publish failure after provider completion is conservatively `UNKNOWN`.
- **Residual evidence boundary:** no real AEDT was launched, so actual `.aedt` lock/release/readability is `NOT RUN`; if a real provider file cannot be frozen, the action will not become known `SUCCEEDED`. Original workspaces remain mutable convenience copies and are never authority.
- **Fixed:** yes for formal Harness provider paths at `OFFLINE VERIFIED`; historical run directories are not retroactively rewritten.

### ISSUE-028 — Provider/code fingerprints are optional and may be empty

- **Classification:** REPRODUCIBILITY / RESUME / IDENTITY
- **Severity / status:** HIGH / PARTIALLY RESOLVED on 2026-08-21
- **Location:** `RunManifestV2.provider_fingerprints`, `code_revision`, CLI state creation, operation request payload.
- **Description:** Run/operation identity includes manifest/provider/config fingerprint fields, but the general contracts still permit empty provider fingerprints and a missing code revision.
- **Impact:** cross-version resume reproducibility and real-Canary traceability.
- **Phase 3 mitigation:** formal supplied and real CLI compositions now fingerprint optimizer/surrogate sources and configuration. Real composition also fingerprints the Builder and composite protocol; the exact Builder attestation is carried through preflight, snapshot, worker request, and result. Optimizer operations carry request/effective-objective digests.
- **Evidence:** request perturbation/digest tests, Builder drift-before-lock test, snapshot/composite digest test, and supplied-worker effective-objective verification pass offline.
- **Phase 5A mitigation:** Readiness Manifest V1 binds clean exact Git HEAD, Agent source, Goal, RunManifest identity, HFSS/Evaluation contract bytes, optimizer/surrogate/Builder source, PyAEDT executable bytes, worker protocol, approval, expiry, and execution policy. Formal real composition validates these before worker construction, and RunStore rejects any real Run missing mandatory revision/provider/readiness/contract identity.
- **Evidence:** canonical/unknown/expiry/dirty-tree/HEAD/source/policy tests; exact successful formal binding; causal-drift-before-worker regression; real-Run registration rejection; full offline suite pass.
- **Residual:** the general `RunManifestV2` domain type intentionally still permits sparse fingerprints for Mock/non-real programmatic workflows. Phase 5C resolves formal native provider artifact bytes offline under ISSUE-027. Actual real AEDT evidence remains NOT RUN.
- **Fixed:** partially domain-wide; resolved for formal actionable real Runs at `OFFLINE VERIFIED` evidence level.

### ISSUE-029 — Candidate queue and diagnosis had no feedback loop

- **Classification:** AGENT CONTROL / ROUTING / BOUNDEDNESS
- **Severity / status:** HIGH / RESOLVED OFFLINE on 2026-08-21
- **Location before repair:** deleted one-pass `comparison_graph.py`, `candidate_queue`, candidate diagnosis, and unconditional `decide_after_hfss → complete` edge.
- **Description before repair:** only one recommended candidate was selected; screen rejection terminated the workflow, valid non-PASS HFSS evidence terminated the workflow, remaining candidates were never consumed, candidate diagnosis could not change a later optimizer request, and there was no controller iteration bound because there was no loop.
- **Resolution:** Phase 4 added `closed-loop-agent-v2`; Phase 5D adopted it as the sole formal topology and deleted the one-pass builder/root. One `ClosedLoopPolicy` owns the sole conditional router, consumes the queue, may rebuild intent/objective from diagnosis, supports new-identity safe retry and reconciliation-only UNKNOWN handling, and enforces all controller/Tool/stagnation budgets.
- **Typed terminal:** baseline PASS → `SUCCEEDED_BASELINE`; promoted candidate PASS → `SUCCEEDED_CANDIDATE`; bounded search exhaustion → `NO_SOLUTION`; UNKNOWN remains `WAITING_RECONCILIATION`.
- **Evidence:** fake-HFSS exit-condition tests, arbitrary-result iteration-bound tests, strict controller JSON round-trip, feature-flag test, deterministic closed-loop E2E, and actual supplied-worker + MockHFSS E2E pass offline.
- **Safety boundary:** `AppConfig.closed_loop_enabled` defaults false. Offline composition rejects real manifests; only the readiness-bound Production root may admit one. Production Policy digest/budget and RunStore `ExecutionPolicy(2,0)` are independently enforced.
- **Residual:** operator reconciliation resolves exact UNKNOWN receipts without retry, but no accepted current physical calibration evidence exists; Production closed-loop physical behavior and real HFSS remain `NOT RUN`.
- **Fixed:** yes at `OFFLINE VERIFIED` for formal control topology; real physical verification is not claimed.

### ISSUE-030 — UNKNOWN/corrupt checkpoints lacked evidence-bound recovery and chaos proof

- **Classification:** RELIABILITY / RECONCILIATION / STATE SAFETY
- **Severity / status:** HIGH / RESOLVED OFFLINE on 2026-08-24
- **Location before repair:** `HarnessCore.execute`, `RunStore`, `SQLiteComparisonCheckpointStore`, `ComparisonWorkflowRunner`, license quarantine operations.
- **Description before Phase 5B:** UNKNOWN was safely non-retriable but had no accepted operator resolution; checkpoint content was not re-verified against stored digest/manifest on every load; action/checkpoint crash coverage was sampled rather than systematic; lock quarantine had no evidence-bound release path.
- **Resolution:** strict `ReconciliationRequest` and append-only reconciliation ledger bind a pre-registered short-lived approval to exact Run/operation/attempt/evidence and one conclusion. Default-off crash hooks cover all action and checkpoint commit boundaries. RunStore/checkpoint loading rejects byte, digest, manifest, and State-schema corruption; runner workflow identity is checked before Run/provider admission. Quarantine release archives the exact marker only after an accepted reconciliation attests an empty process tree.
- **Evidence:** operator success/failure/expiry/revocation/wrong identity/conflict/idempotency tests; six crash points across normal and terminal checkpoints; double resume; byte and semantic corruption; incompatible Graph identity; bounded kill-verification failure; Windows parent death; quarantine archive/replay; full suite 215 PASS.
- **Safety boundary:** reconciliation is not retry. It creates no attempt, refunds no budget, cannot exceed the two-solve authorization envelope, and cannot make historical V1 executable. Actual AEDT lifecycle remains `NEEDS VERIFICATION` under ISSUE-015/026.
- **Fixed:** yes for new formal RunStore/Harness executions at `OFFLINE VERIFIED`.
## Resolved issues retained for history

### ISSUE-003 — Candidate comparison called unimported `emit_status`

- **Classification:** BUG / REGRESSION
- **Severity / status:** BLOCKER / RESOLVED
- **Historical blocking order:** CURRENT FIRST BLOCKER after ISSUE-002.
- **Root cause:** `compare_hfss_results` called `emit_status` with the existing presenter contract but omitted it from the `harness.terminal` import list.
- **Resolution:** imported the existing `emit_status`; no comparison, evaluation, status-model, or Best-update logic changed.
- **Evidence before:** the rule-configured safe WF-001 route reached comparison after candidate HFSS and raised `NameError: name 'emit_status' is not defined`.
- **Evidence after:** the dedicated Graph regression passes; the safe 5–19 GHz route completes comparison with `FULLY_ACHIEVED` and reaches `complete`.
- **Fixed:** yes, 2026-08-20.
- **Historical remaining boundary at 2026-08-20 completion:** ISSUE-004 became the first blocker; Phase 0 later resolved it on 2026-08-21.

### ISSUE-002 — WF-001 lacked a Production Evaluation Contract

- **Classification:** INTEGRATION / EVALUATION
- **Severity / status:** BLOCKER / RESOLVED
### ISSUE-031 — Readiness accepts structurally valid but insufficient Calibration Evidence

- **Classification:** CALIBRATION / AUTHORITY / PROVENANCE
- **Severity / status:** BLOCKER / RESOLVED OFFLINE on 2026-08-24
- **Location:** `evaluation/calibration.py`, `domain/contracts.py::CalibrationEvidence`, `harness/real_hfss_safety.py::RealHFSSReadinessManifestV1`.
- **Description:** the schema requires non-empty unique case IDs and some provider fingerprints, but it permits one case, arbitrary policy version/thresholds, any non-empty provider subset, and empty `source_artifact_ids`. `_ranking_agreement` returns 1.0 when there is no comparable pair. Readiness trusts the embedded `passed` report and checks only the provider keys supplied by the evidence.
- **Impact:** a canonical, digest-stable object can be structurally valid without proving an approved policy, ranking evidence, the complete HFSS/surrogate causal identity, or immutable physical source artifacts. Such an object must not authorize Phase 6.
- **Trigger:** construct passing evidence with one/non-comparable case, lenient thresholds, partial provider bindings, or no source receipts.
- **Evidence:** current source inspection plus existing tests that deliberately construct accepted evidence with incomplete policy fields and no source artifact IDs; the full suite proves current behavior rather than sufficiency. No real tool was run.
- **Resolution:** schema `calibration-evidence/1.1` requires the versioned recommended policy, at least three cases and two comparable pairs, complete surrogate/Builder/PyAEDT/protocol provider identity, and exactly five typed immutable receipts per case. The domain object recomputes per-case complex/dB errors, aggregate means, comparable-pair count, ranking agreement, and pass from structured case data. Real readiness separately reopens and hashes every receipt, strictly decodes candidate/surrogate/HFSS results, reconstructs `CalibrationCase`, reruns `assess_calibration`, and requires byte-identical report semantics.
- **Evidence:** focused regressions reject one-case/vacuous ranking, arbitrary policy/policy digest drift, missing providers, empty/missing/role-duplicate receipts, byte tamper, forged wrong-candidate semantic artifacts, and aggregate/report drift. Relevant safety/calibration/Production set passed 73 tests; final full-suite evidence is recorded in `VALIDATION_MATRIX.md`.
- **Fixed:** yes at `OFFLINE VERIFIED`. The mandatory authority gap is closed; absence or failure of actual current physical Calibration remains ISSUE-009 and cannot be risk-accepted.
- **Canary disposition:** no longer a blocker after the exact committed implementation passes offline validation. Readiness still cannot be issued without real passing evidence.

### ISSUE-032 — AEDT 2025 R1 Python 3.10 could not import the isolated worker

- **Classification:** HFSS / RUNTIME / COMPATIBILITY
- **Severity / status:** BLOCKER / RESOLVED OFFLINE on 2026-08-24; physical rerun pending
- **Trigger/evidence:** the first authorized Calibration baseline action launched the supervised worker, which exited in about 0.1 s before AEDT/model construction with `ImportError: cannot import name 'StrEnum'` from Python 3.10. No `ansysedt` process, project, solve, extraction, residual process, or lock remained. Harness conservatively recorded the action `UNKNOWN`.
- **Root cause:** `python -m hfss_optimization_agent.hfss.pyaedt_worker` executes package `__init__` files first. They eagerly imported Agent/Harness modules requiring Python 3.11+ even though the isolated PyAEDT worker is designed to run in AEDT 2025 R1's Python 3.10.
- **Resolution:** package and HFSS exports are lazy; all shared string enums use a small Python-3.10-compatible `StrEnum` shim. AEDT/PyAEDT Python can now execute the worker CLI import path without importing/launching AEDT.
- **Evidence after:** configured PyAEDT/AEDT Python executes `-m hfss_optimization_agent.hfss.pyaedt_worker --help` with exit 0; focused worker/Calibration/import suite passes. A full physical rerun is required before real verification.
- **Fixed:** offline import boundary yes; `REAL HFSS VERIFIED` not yet claimed.

### ISSUE-033 — Calibration UNKNOWN lacked preregistered reconciliation authority

- **Classification:** RELIABILITY / RECONCILIATION / CALIBRATION
- **Severity / status:** HIGH / RESOLVED FOR NEW RUNS on 2026-08-24
- **Trigger/evidence:** the failed ISSUE-032 attempt correctly became `WAITING_RECONCILIATION`, but the campaign had registered only `real_hfss` approval. Reconciliation policy correctly refuses authority added after a Run becomes non-active, so this historical Run remains preserved as unresolved evidence rather than being rewritten.
- **Resolution:** every new Calibration Run preregisters a short-lived, campaign-derived `reconcile_unknown` grant alongside the physical grant, with the same manifest expiry. It does not auto-reconcile or retry; it only makes the existing reviewed Phase-5B operator path usable if UNKNOWN occurs.
- **Evidence after:** fake three-case campaign asserts both grants are durably present; reconciliation unit suite remains authoritative for resolution behavior.
- **Residual:** `run:hfss-calibration-20260824-100309` remains `WAITING_RECONCILIATION` with one conservatively authorized action but zero observed AEDT/solve starts. It is never resumed or used as Calibration evidence.

- **Historical blocking order:** CURRENT FIRST BLOCKER after ISSUE-001.
- **Root cause:** WF-001 constructed `EvaluationConfig` with empty rules, while the evaluator correctly treats no-rule input as `INVALID` and refuses legacy scalar-score fallback.
- **Authoritative contract:** `production-evaluation-v1`; Core 6–18 GHz HARD `S21_dB <= -30 dB` and `S11_dB >= -0.5 dB`; Lower 5–6 GHz and Upper 18–19 GHz use the same targets as SOFT rules; worst-case/all-points semantics; vendor phase/passivity constraints excluded from Production PASS/FAIL.
- **Fix:** added a versioned JSON contract and loader, injected it only into WF-001, preserved existing rule-level evidence, and added direction-neutral `CORE_S11_RULE_NOT_MET` / `CORE_S21_RULE_NOT_MET` diagnosis and focus paths.
- **Evidence:** targeted suite 40 PASS; WF-001 composition test captures six loaded rules; checkpoint round-trip preserves rule evidence; safe Production-band node chain produces ACTIVE intent/objective.
- **Reachability after fix:** a full test-only Graph probe passes optimizer, candidate gate, and candidate HFSS, then exposes unchanged ISSUE-003 at `compare_hfss_results`.
- **Scope exclusions preserved:** no Comparator/Best/vendor-objective/terminal-status redesign; WF-002/WF-003 were not adapted; HFSS/AEDT not run.
- **Fixed:** yes.

### ISSUE-023 — Package CLI imported a stale installation from another workspace

- **Classification:** ENVIRONMENT / REPRODUCIBILITY
- **Severity / status:** HIGH / RESOLVED
- **Location:** project `.venv` editable-install metadata used by ordinary imports and `.venv\Scripts\python.exe -m hfss_optimization_agent`.
- **Root cause:** the copied/moved `.venv` retained an absolute editable path in `__editable__.hfss_optimization_agent-0.1.0.pth` and `direct_url.json`, both pointing to `C:\Users\82074\Documents\Codex\2026-08-12\langgraph-state-interface-adapter-checkpoint-best-2\HFSS_Optimization_Agent_VSCode`. The current `uv.lock` was already correct with `source = { editable = "." }`; the new workspace had not re-synchronized its editable install.
- **Resolution:** ran `uv sync --frozen --inexact --cache-dir .uv-cache` from the current repository. uv uninstalled only the stale project editable and installed `hfss-optimization-agent==0.1.0` from `file:///D:/Agent_Workspace/HFSS_Optimization_Agent_VSCode`; no lock, global Python, global `PYTHONPATH`, old workspace, or business source was changed.
- **Evidence:** ordinary import, `.pth`, `direct_url.json`, and `uv pip show` now resolve to the current repository. The subprocess regression passes. The package Offline CLI executes the deprecated WF-002 path; it is not Production Evaluation evidence.
- **Fixed:** yes, 2026-08-20.
- **Regression boundary:** `tests/test_import_provenance.py` launches the project `.venv` without `PYTHONPATH` and requires the imported package file to reside under the current repository `src` directory.

### ISSUE-001 — Undefined `evaluation` crashed optimization-intent output

- **Classification:** BUG / REGRESSION
- **Severity / status:** BLOCKER / RESOLVED
- **Historical blocking order:** CURRENT FIRST BLOCKER before this fix.
- **Root cause:** `emit_optimization_intent` accepted only `intent` but referenced a nonlocal, undefined `evaluation`; `frequency_margin` actually belongs to the baseline `EvaluationResult` already held by the caller state.
- **Resolution:** presenter contract now explicitly accepts `evaluation`, and `build_optimization_intent` passes `state["baseline_evaluation"]`; no dummy, fallback, hard-coded margin, evaluation-rule, or objective behavior was introduced.
- **Evidence:** original current-source CLI test reproduced `NameError`; direct regression passed; all 8 terminal presenter tests passed; post-fix main suite has 88 pass / 6 downstream failures without the NameError; current-source Offline route reaches `build_optimization_objective`.
- **Fixed:** yes, 2026-08-20.
- **Historical remaining boundary at completion:** ISSUE-002 became the next blocker. ISSUE-002/003 were subsequently resolved, and Phase 0 resolved ISSUE-004 on 2026-08-21.

### ISSUE-021 — Explicit material SolveInside classification regression

- **Classification:** HFSS / BUILDER
- **Severity / status:** HIGH / RESOLVED
- **Location:** historical run `real-vscode-20260818-100434`; current native primitive/material tests.
- **Description:** an earlier build failed because solder material lacked an explicit SolveInside rule.
- **Impact at occurrence:** blocked baseline build.
- **Evidence of resolution:** current material classification tests pass; later run `real-vscode-20260818-101711` built/solved/exported both projects successfully.
- **Residual verification:** current working-tree real execution is not verified because of ISSUE-012, but the specific classification implementation is unit tested.

### ISSUE-022 — Production target-only design and independent project boundary

- **Classification:** HFSS / ARCHITECTURE
- **Severity / status:** HIGH / RESOLVED
- **Location:** contract checks, Builder project implementation, Worker workspaces, tests, historical real run.
- **Description:** prior documentation/history referenced duplicate `huitu` construction and possible shared-project mutation. Current Production explicitly permits only `interposer_temple4`, creates new baseline/candidate workspaces, and refuses Builder overwrite.
- **Evidence of resolution:** target-only unit tests; two distinct historical `.aedt` projects and `.s2p` exports; runtime contract enforcement.
- **Residual risk:** task/artifact collision and current-tree verification remain separate ISSUE-014/012.
