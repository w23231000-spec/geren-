# Issue Register

Baseline: `FS-2026-08-20`. Issues are retained after resolution; status changes require evidence.

## Summary

| ID | Severity | Status | Classification | Title |
|---|---|---|---|---|
| ISSUE-001 | BLOCKER | RESOLVED | BUG / REGRESSION | Undefined `evaluation` crashed optimization-intent output |
| ISSUE-002 | BLOCKER | OPEN | INTEGRATION / EVALUATION | Formal entries provide no evaluation rules |
| ISSUE-003 | BLOCKER | OPEN | BUG / REGRESSION | Candidate comparison calls unimported `emit_status` |
| ISSUE-004 | HIGH | OPEN | EVALUATION / STATE | Rule comparison cannot drive Best update or summary |
| ISSUE-005 | HIGH | OPEN | OPTIMIZATION / ARCHITECTURE | Diagnosis objective does not control supplied optimizer |
| ISSUE-006 | HIGH | OPEN | STATE / HFSS | Failed/invalid candidate paths can finish as completed |
| ISSUE-007 | HIGH | OPEN | MOCK / INTEGRATION | Mock frequency grid conflicts with default evaluation plan |
| ISSUE-008 | HIGH | OPEN | TEST / REGRESSION | Current graph E2E and resume tests fail and expected traces are stale |
| ISSUE-009 | HIGH | OPEN | EVALUATION / OPTIMIZATION | Calibration is not wired; historical ranking reversal exists |
| ISSUE-010 | HIGH | OPEN | HFSS / MODEL | Physical model alignment remains unresolved |
| ISSUE-011 | HIGH | PARTIALLY RESOLVED | REPRODUCIBILITY | New Git baseline exists; original history remains unavailable |
| ISSUE-012 | HIGH | OPEN | VALIDATION | Historical real E2E cannot be attributed to current working tree |
| ISSUE-013 | MEDIUM | OPEN | STATE / RESUME | Resume restarts at graph START and can duplicate/overwrite state metadata |
| ISSUE-014 | MEDIUM | OPEN | ARTIFACT / SAFETY | Task ID path containment and same-ID concurrency are unguarded |
| ISSUE-015 | MEDIUM | OPEN | HFSS / CONCURRENCY | License lock ownership may outlive/diverge from Agent PID |
| ISSUE-016 | MEDIUM | OPEN | ARTIFACT | Historical runs remain marked running after process exit |
| ISSUE-017 | MEDIUM | PARTIALLY RESOLVED | DOCUMENTATION | README and older architecture/status claims drift from current evidence |
| ISSUE-018 | MEDIUM | OPEN | TEST / ENVIRONMENT | Standalone Builder test cannot collect under Agent Python |
| ISSUE-019 | MEDIUM | OPEN | HFSS / VALIDATION | HFSS return grid endpoints are not checked against contract |
| ISSUE-020 | LOW | OPEN | DOCUMENTATION / UX | 14 displayed stages do not map one-to-one to 17 graph nodes |
| ISSUE-021 | HIGH | RESOLVED | HFSS / BUILDER | Explicit material SolveInside classification regression |
| ISSUE-022 | HIGH | RESOLVED | HFSS / ARCHITECTURE | Production target-only design and independent project boundary |
| ISSUE-023 | HIGH | RESOLVED | ENVIRONMENT / REPRODUCIBILITY | Package CLI imported a stale installation from another workspace |

## Open and partially resolved issues

### ISSUE-002 — Formal entries provide no evaluation rules

- **Classification:** INTEGRATION / EVALUATION
- **Severity / status:** BLOCKER / OPEN
- **Blocking order:** **CURRENT FIRST BLOCKER / exposed after ISSUE-001**. ISSUE-001 no longer aborts presentation; the empty evaluation contract now prevents an ACTIVE optimization route.
- **Location:** `core/config.py::EvaluationConfig.rules=()`; all three run functions in `cli.py`; `evaluator.py::evaluate_sparameters`.
- **Description:** no entry supplies rules, while the evaluator intentionally marks no-rules input `INVALID` and forbids legacy score fallback.
- **Impact:** baseline diagnosis becomes invalid; optimization intent/objective cannot become ACTIVE; optimizer and candidate HFSS are skipped if ISSUE-001 is removed; misleading completion is possible.
- **Trigger:** every formal Agent workflow with current configuration.
- **Evidence:** unit test `test_no_rules_is_invalid_and_never_score_fallback`; failing E2E output shows `Baseline Evaluation INVALID`.
- **Workaround:** none configured.
- **Fixed:** no.
- **Needs verification:** define a versioned evaluation contract and prove real and Mock frequency coverage.
- **Suggested next action:** add explicit rules/FrequencyPlan through configuration/composition before enabling a real run.

### ISSUE-003 — Candidate comparison calls unimported `emit_status`

- **Classification:** BUG / REGRESSION
- **Severity / status:** BLOCKER / OPEN
- **Blocking order:** **LATENT BLOCKER / currently masked by ISSUE-002**. It becomes reachable only after the intent/evaluation route can proceed through optimizer and candidate HFSS comparison.
- **Location:** `agent/comparison_nodes.py` import list and `compare_hfss_results` lines 320/324.
- **Description:** `emit_status` is called but not imported.
- **Impact:** candidate comparison, Offline E2E, supplied-Mock E2E, real candidate E2E.
- **Trigger:** a valid route reaches comparison and produces an `EvaluationComparison`.
- **Evidence:** static source inspection; currently masked by ISSUE-001/002.
- **Workaround:** none.
- **Fixed:** no.
- **Needs verification:** must be exercised by a rule-configured comparison test.
- **Suggested next action:** import/test after ISSUE-001/002 integration design is settled.

### ISSUE-004 — Rule comparison cannot drive Best update or summary

- **Classification:** EVALUATION / STATE / CAUSAL DISCONNECT
- **Severity / status:** HIGH / OPEN
- **Location:** `evaluation/evaluator.py::evaluate_sparameters` returns `improved=False, score=0.0`; `comparison_nodes.py::update_hfss_best`; `cli.py::_summary`.
- **Description:** rule improvement is represented in `EvaluationComparison.classification`, while Best and summary read unrelated legacy fields from `EvaluationResult`.
- **Impact:** Optimization result reporting and Best persistence; an improved candidate cannot replace baseline under the default evaluator.
- **Trigger:** any valid rule-based candidate comparison.
- **Evidence:** direct return construction and update predicate; no passing integration test reaches the new semantics.
- **Workaround:** custom evaluator could populate legacy fields, but no formal entry injects one.
- **Fixed:** no.
- **Suggested next action:** choose one authoritative comparison/score contract and update state, summary, Best, and tests together.

### ISSUE-005 — Diagnosis objective does not control supplied optimizer

- **Classification:** OPTIMIZATION / ARCHITECTURE / CAUSAL DISCONNECT
- **Severity / status:** HIGH / OPEN
- **Location:** `optimization/supplied_optimizer_adapter.py::optimize`.
- **Description:** vendor `execute` runs from static TOML/CSV before `optimization_objective` is merely copied into batch metadata. The adapter returns one recommended candidate, so graph reranking cannot select among Pareto candidates.
- **Impact:** the advertised diagnosis-driven optimization path is only partially wired; Production optimization behavior is unchanged by diagnosis focus.
- **Trigger:** every supplied optimizer Agent run.
- **Evidence:** actual call order and returned batch shape; historical optimizer summary.
- **Workaround:** manually edit vendor objective/constraint configuration, which is outside dynamic diagnosis behavior.
- **Fixed:** no.
- **Suggested next action:** either translate the Agent objective into optimizer inputs/return multiple candidates, or explicitly redefine the feature as post-run annotation.

### ISSUE-006 — Failed/invalid candidate paths can finish as completed

- **Classification:** STATE / HFSS / ERROR HANDLING
- **Severity / status:** HIGH / OPEN
- **Location:** `run_candidate_hfss`, candidate gate, `decide_after_hfss`, and `complete` in `comparison_nodes.py`.
- **Description:** unlike baseline HFSS, candidate HFSS does not raise on `success=False`; invalid evaluation or STOP still flows to unconditional `WorkflowStatus.COMPLETED`. Candidate surrogate failure also gates to complete.
- **Impact:** Production/Demo status may report completion without a valid candidate comparison.
- **Trigger:** candidate provider failure, gate rejection, invalid evaluation, or target not passed.
- **Evidence:** graph edges and unconditional complete node.
- **Workaround:** inspect candidate result, evaluation status, and next action rather than summary status alone.
- **Fixed:** no.
- **Suggested next action:** define terminal statuses (`failed`, `invalid`, `rejected`, `completed`) and test each route.

### ISSUE-007 — Mock frequency grid conflicts with default evaluation plan

- **Classification:** MOCK / INTEGRATION
- **Severity / status:** HIGH / OPEN
- **Location:** `cli.py` MockHFSS grids `(1,2,3)` GHz; `FrequencyPlan` defaults to core 6–18 GHz with 5–19 GHz margins.
- **Description:** adding the intended plan-aligned rules would make MockHFSS candidate evaluation invalid because the Mock data does not cover those bands. Supplied surrogate uses 0.1–20 GHz, producing inconsistent provider coverage within WF-003.
- **Impact:** Offline and supplied-Mock verification cannot represent Production rule evaluation.
- **Trigger:** configure current intended rules without changing Mock grids.
- **Evidence:** source configuration and evaluator range validation.
- **Workaround:** none currently wired.
- **Fixed:** no.
- **Suggested next action:** define a shared test frequency contract and generate Mock curves over it.

### ISSUE-008 — Current graph E2E and resume tests fail and expected traces are stale

- **Classification:** TEST / REGRESSION
- **Severity / status:** HIGH / OPEN
- **Location:** `tests/test_cli.py`, `tests/test_comparison_graph.py`.
- **Description:** after ISSUE-001 resolution, six tests still fail because empty rules produce INVALID intent/objective and skip all candidate stages. Their expected traces also describe the pre-diagnosis graph and omit diagnosis/intent/objective nodes.
- **Impact:** Offline, E2E, checkpoint, and resume verification cannot be claimed for current graph.
- **Trigger:** main test suite.
- **Evidence:** 2026-08-20 post-fix suite: 94 collected, 88 pass / 6 fail; no ISSUE-001 NameError remains. Test files predate 2026-08-19 graph changes.
- **Workaround:** component-level tests still provide partial evidence.
- **Fixed:** no.
- **Suggested next action:** after behavior is explicitly decided, update integration fixtures/expectations and prove every conditional route.

### ISSUE-009 — Calibration is not wired; historical ranking reversal exists

- **Classification:** EVALUATION / OPTIMIZATION / MODEL
- **Severity / status:** HIGH / OPEN
- **Location:** `evaluation/calibration.py`, unused `ArtifactStore.write_calibration_report`, no graph caller; historical run `real-vscode-20260818-101711`.
- **Description:** the calibration API exists but Production never executes or gates on it. A reconstruction-only calculation from the historical paired run found mean complex RMSE 0.07320, mean dB RMSE 3.327 dB, and pairwise ranking agreement 0.0. Surrogate predicted candidate improvement while HFSS worsened.
- **Impact:** Optimization/physical conclusions; surrogate recommendation is not trustworthy as a performance claim.
- **Trigger:** use surrogate ranking as evidence of HFSS improvement.
- **Evidence:** historical baseline/candidate complex results and calibration API; no `calibration/report.json` exists.
- **Workaround:** always perform paired HFSS review and call results uncalibrated.
- **Fixed:** no.
- **Suggested next action:** establish calibration policy/data and wire report/gating before physical optimization claims.

### ISSUE-010 — Physical model alignment remains unresolved

- **Classification:** HFSS / MODEL
- **Severity / status:** HIGH / OPEN
- **Location:** `docs/MODEL_RISKS.md`, `config/model_alignment.example.json`, Builder materials, equivalent model formulas.
- **Description:** PI relative permittivity differs (3.5 vs 3.9); SiO2 thickness mapping is not shared; fixed 10 GHz-derived elements are used over 0.1–20 GHz; Gsub units and Rlf1 dimensions are uncertain; `alpha_eff` is unused.
- **Impact:** surrogate/HFSS comparison and any physical conclusion.
- **Trigger:** treating automated completion as calibrated model validation.
- **Evidence:** current config/source and historical ranking reversal.
- **Workaround:** label results `uncalibrated` and avoid physical claims.
- **Fixed:** no.
- **Suggested next action:** obtain model-author decisions and fill a versioned alignment contract before calibration.

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
- **Severity / status:** MEDIUM / OPEN
- **Location:** `ComparisonWorkflowRunner.invoke`, `build_comparison_graph`, node reuse checks.
- **Description:** JSON-loaded state is reinvoked from START; initialization, diagnosis, intent, and other deterministic stages may rerun, rewrite timestamps/artifacts, and append trace/history. This is idempotent replay, not true node continuation.
- **Impact:** Resume, audit history, artifact consistency.
- **Trigger:** invoke a runner with loaded checkpoint.
- **Evidence:** topology and node reuse implementation; current resume test fails before completion.
- **Workaround:** expensive provider results are reused when present, limiting cost.
- **Fixed:** no.
- **Suggested next action:** define resume semantics and test replay idempotence/history invariants.

### ISSUE-014 — Task ID path containment and same-ID concurrency are unguarded

- **Classification:** ARTIFACT / SAFETY
- **Severity / status:** MEDIUM / OPEN
- **Location:** `harness/artifacts.py::ArtifactStore`, CLI `--task-id`, fixed `.tmp` sibling names.
- **Description:** `root / task_id` is not resolved/validated under root. Concurrent identical task IDs share artifact and temporary paths. `RUN_REAL_HFSS.py` uses second-resolution IDs.
- **Impact:** Artifact overwrite/collision; CLI path escape within process permissions.
- **Trigger:** crafted/absolute task ID or two same-ID launches.
- **Evidence:** direct path construction and write implementation.
- **Workaround:** autogenerated UUID-based IDs in programmatic defaults; avoid user-supplied separators and concurrent launches.
- **Fixed:** no.
- **Suggested next action:** validate containment and use collision-resistant IDs/unique atomic temp names.

### ISSUE-015 — License lock ownership may diverge from actual AEDT work

- **Classification:** HFSS / CONCURRENCY
- **Severity / status:** MEDIUM / OPEN
- **Location:** `harness/license_lock.py`, subprocess Worker lifecycle.
- **Description:** lock payload records Agent PID. If Agent dies while Worker/AEDT remains alive, a later Agent can reclaim the lock after seeing the parent PID dead, potentially overlapping actual AEDT work.
- **Impact:** license contention and concurrent HFSS safety.
- **Trigger:** abrupt Agent termination while a Worker child survives.
- **Evidence:** PID ownership design; historical stale `running` journals show interrupted executions, though overlap is not proven.
- **Workaround:** operator verifies AEDT processes before rerun; preflight only checks Agent lock.
- **Fixed:** no.
- **Suggested next action:** bind ownership/heartbeat to active worker/AEDT lifecycle or require explicit stale recovery audit.

### ISSUE-016 — Historical runs remain marked running after process exit

- **Classification:** ARTIFACT / STATE
- **Severity / status:** MEDIUM / OPEN
- **Location:** several `runs/real-vscode-*` checkpoints/journals from 2026-08-17.
- **Description:** four checkpoints and journals remain `running` at build/release stages despite no active lock. No terminal reconciliation marks interrupted runs.
- **Impact:** run inventory, monitoring, restart decisions, audit accuracy.
- **Trigger:** forced process termination.
- **Evidence:** parsed checkpoint/journal inventory.
- **Workaround:** manually interpret old timestamps/process state; do not treat `running` as active.
- **Fixed:** no.
- **Suggested next action:** add read-only reconciliation/status model for abandoned runs.

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

### ISSUE-018 — Standalone Builder test cannot collect under Agent Python

- **Classification:** TEST / ENVIRONMENT
- **Severity / status:** MEDIUM / OPEN
- **Location:** `vendor/hfss_builder/test_nine_parameter_builder.py`; import chain reaches `ansys.aedt.core`.
- **Description:** explicit test collection under project `.venv` fails because PyAEDT is installed only in the separate interpreter.
- **Impact:** current standalone Builder-test verification; main suite still tests Builder units through stubs.
- **Trigger:** pytest collecting the vendor Builder test under Agent Python.
- **Evidence:** 2026-08-20 collection error `ModuleNotFoundError: ansys`.
- **Workaround:** run in the PyAEDT environment or isolate mapping imports from PyAEDT imports; neither was done this round.
- **Fixed:** no.
- **Suggested next action:** define the intended test interpreter and make collection behavior explicit.

### ISSUE-019 — HFSS return grid endpoints are not checked against contract

- **Classification:** HFSS / VALIDATION
- **Severity / status:** MEDIUM / OPEN
- **Location:** `pyaedt_worker.py::_extract`, `hfss/converter.py`, `ComplexSParameters` validation.
- **Description:** Worker checks point count and later code checks monotonicity, but no check proves first/last/intermediate frequencies match contract start/stop/spacing. A shifted grid of equal length could be accepted.
- **Impact:** evaluation and surrogate/HFSS comparability.
- **Trigger:** HFSS returns an unexpected but monotonic equal-length grid.
- **Evidence:** source inspection; calibration could catch mismatch but is not wired.
- **Workaround:** inspect structured export or call calibration manually.
- **Fixed:** no.
- **Suggested next action:** validate full grid against contract with a defined tolerance.

### ISSUE-020 — Displayed stage count differs from graph-node count

- **Classification:** DOCUMENTATION / UX
- **Severity / status:** LOW / OPEN
- **Location:** `ComparisonWorkflowNodes._announce` calls and README stage claims.
- **Description:** 17 nodes share 14 numbers, so terminal numbering is not a unique execution trace.
- **Impact:** operator diagnosis and presentation clarity only.
- **Trigger:** any workflow run.
- **Evidence:** graph/node mapping.
- **Workaround:** use `execution_trace` and artifacts for exact progression.
- **Fixed:** no.
- **Suggested next action:** document substeps or assign stable unique stage identifiers.

## Resolved issues retained for history

### ISSUE-023 — Package CLI imported a stale installation from another workspace

- **Classification:** ENVIRONMENT / REPRODUCIBILITY
- **Severity / status:** HIGH / RESOLVED
- **Location:** project `.venv` editable-install metadata used by ordinary imports and `.venv\Scripts\python.exe -m hfss_optimization_agent`.
- **Root cause:** the copied/moved `.venv` retained an absolute editable path in `__editable__.hfss_optimization_agent-0.1.0.pth` and `direct_url.json`, both pointing to `C:\Users\82074\Documents\Codex\2026-08-12\langgraph-state-interface-adapter-checkpoint-best-2\HFSS_Optimization_Agent_VSCode`. The current `uv.lock` was already correct with `source = { editable = "." }`; the new workspace had not re-synchronized its editable install.
- **Resolution:** ran `uv sync --frozen --inexact --cache-dir .uv-cache` from the current repository. uv uninstalled only the stale project editable and installed `hfss-optimization-agent==0.1.0` from `file:///D:/Agent_Workspace/HFSS_Optimization_Agent_VSCode`; no lock, global Python, global `PYTHONPATH`, old workspace, or business source was changed.
- **Evidence:** ordinary import, `.pth`, `direct_url.json`, and `uv pip show` now resolve to the current repository. The new subprocess regression passes. The package Offline CLI executes the current graph through `build_optimization_objective`, then exposes unchanged ISSUE-002.
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
- **Remaining boundary:** ISSUE-002 is now the current first blocker; ISSUE-003 remains latent.

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
