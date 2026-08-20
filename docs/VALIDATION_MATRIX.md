# Validation Matrix

Baseline: `FS-2026-08-20`. This semantic correction uses only existing evidence; no test or HFSS run was performed for the correction. Matrix cells use only `PASS`, `FAIL`, `NOT RUN`, `NOT AVAILABLE`, `STALE`, `UNKNOWN`, or `NEEDS VERIFICATION`. Historical evidence is separated from current-working-tree evidence.

## Status dimensions

- **Capability-local integration:** whether the capability boundary itself has been exercised successfully with its immediate collaborators. It does not inherit the final workflow result.
- **Workflow reachability:** whether the current formal call graph can reach the capability on the relevant route. A node can be reachable and still fail locally; downstream nodes can be unreachable while their unit/local evidence remains valid.
- **Full Offline result:** terminal result of a complete no-AEDT formal workflow, not a summary of every component.
- **Current Real HFSS result:** result of a real HFSS execution on the current filesystem snapshot.
- **E2E result:** terminal result of the entire formal route. A downstream E2E failure does not convert already successful upstream local integration into `FAIL`.

`Code PASS` means relevant implementation is present/importable; it does not prove correct behavior. `NEEDS VERIFICATION` is used where the existing evidence does not isolate the capability from an upstream or downstream failure.

## Current working-tree capability evidence

| Capability | Code | Unit/component | Capability-local integration | Workflow reachability | Evidence boundary |
|---|---|---|---|---|---|
| Baseline surrogate | PASS | PASS | PASS | PASS | Current main integration route executes it before the current downstream blocker |
| Baseline HFSS orchestration | PASS | PASS | PASS | PASS | Fake backend integration passes; baseline stage is reached |
| S-parameter rule evaluation | PASS | PASS | PASS | PASS | WF-001 loads six Production v1 rules; independent hard failures, soft failures, worst evidence, and aggregate status pass targeted tests |
| Baseline diagnosis | PASS | PASS | PASS | PASS | Production-direction S11/S21 hard failures retain neutral issue identities and signed evidence |
| Optimization Intent | PASS | PASS | PASS | PASS | Both Production hard-rule failure types produce ACTIVE CORE_RECOVERY intent |
| Optimization Objective | PASS | PASS | PASS | PASS | Safe WF-001 node/Graph routes produce ACTIVE objective; supplied optimizer behavioral control remains separate ISSUE-005 |
| Supplied surrogate provider | PASS | PASS | NEEDS VERIFICATION | PASS | Formal supplied routes call it before optimizer blockers; current Agent-boundary execution was not isolated |
| Supplied optimizer provider integration / adapter wiring | PASS | PASS | NEEDS VERIFICATION | PASS | Provider call is now upstream of the exposed ISSUE-003; vendor tests pass, but the supplied adapter was not executed in this repair |
| Diagnosis/OptimizationObjective control of supplied optimizer behavior | FAIL | NOT AVAILABLE | FAIL | FAIL | ISSUE-005 causal disconnect: objective is metadata-only after vendor execution |
| Candidate ranking | PASS | PASS | NEEDS VERIFICATION | PASS | Safe Production-band route executes deterministic ranking; supplied adapter still returns one candidate |
| Candidate parameter validation | PASS | PASS | PASS | PASS | Safe Production-band Graph probe reaches candidate validation |
| Candidate surrogate gate | PASS | PASS | PASS | PASS | Safe Production-band Graph probe reaches and passes the candidate gate |
| Candidate HFSS orchestration | PASS | PASS | PASS | PASS | Safe Production-band Graph probe reaches candidate HFSS without AEDT |
| Baseline/candidate comparison | PASS | PASS | FAIL | PASS | Route now enters comparison and exposes ISSUE-003 locally |
| Candidate diagnosis | PASS | PASS | NEEDS VERIFICATION | FAIL | Unit evidence exists; current route does not reach it |
| Best update | PASS | STALE | FAIL | FAIL | ISSUE-004 semantic disconnect is local; current route is also blocked upstream |
| HFSS contract/port/complex conversion | PASS | PASS | PASS | PASS | Fake worker/backend integration passes and baseline HFSS route contains the boundary |
| Target-only Builder | PASS | PASS | PASS | PASS | Stubbed Builder integration passes; real current-tree execution remains NOT RUN |
| Standalone Builder test harness | PASS | FAIL | NOT RUN | NOT AVAILABLE | Collection fails in Agent Python because `ansys` is absent |
| Worker process isolation/timeout | PASS | PASS | PASS | PASS | Child-process fake exercises the boundary; real current-tree execution remains NOT RUN |
| Artifact store | PASS | PASS | PASS | PASS | Upstream artifacts are written before the downstream failure |
| Checkpoint serialization | PASS | PASS | PASS | PASS | Serialization is locally proven and checkpoints are reached before the failure |
| Resume/reuse | PASS | PASS | NEEDS VERIFICATION | PASS | Local serialization/reuse evidence passes; five stale Mock graph tests still do not isolate current WF-001 resume semantics |
| Calibration API | PASS | PASS | NOT AVAILABLE | FAIL | API is not connected to any formal workflow |
| Environment preflight | PASS | NOT AVAILABLE | PASS | PASS | Current preflight result is PASS; it does not launch AEDT or prove a license |
| Package editable import provenance | PASS | PASS | PASS | PASS | Project `.venv`, ordinary import, and module CLI resolve to the current repository `src` |

## Current full-workflow results

| Workflow | Full Offline result | Current Real HFSS result | Current E2E result | Readiness / evidence |
|---|---|---|---|---|
| WF-001 canonical Production | NOT AVAILABLE | NOT RUN | NOT RUN | FAIL readiness: ISSUE-002 resolved; ISSUE-003 is current first blocker and was exposed by a safe test-only Graph probe |
| WF-002 deterministic Offline | FAIL | NOT AVAILABLE | FAIL | Deprecated Mock path remains empty-rule/1–3 GHz and was deliberately not adapted to the Production contract |
| WF-003 supplied optimizer + MockHFSS | NOT RUN | NOT AVAILABLE | NOT RUN | Deprecated Mock path was not adapted or rerun; Production Contract v1 is WF-001-only |
| WF-004 environment preflight | NOT AVAILABLE | NOT RUN | NOT AVAILABLE | PASS for its own read-only preflight scope only |

Interpretation:

- Upstream capability-local `PASS` rows remain `PASS` even though WF-002 terminates with `FAIL` downstream.
- `Workflow reachability FAIL` on downstream rows records masking/blocking, not a failure of their unit tests.
- WF-001 has readiness `FAIL`, but its actual current real-HFSS and E2E results are `NOT RUN`; readiness is not substituted for an execution result.

## Executed validation commands

### ISSUE-002 Production Evaluation Contract v1

- **Date:** 2026-08-20
- **Targeted command:** `.venv\Scripts\python.exe -m pytest tests/test_production_evaluation_contract.py tests/test_sparameter_evaluator.py tests/test_diagnosis.py tests/test_optimization_intent.py tests/test_comparison_models.py -q`
- **Result:** `PASS` — 40 passed.
- **Evidence:** exact six-rule contract/FrequencyPlan, independent S21/S11 hard failures, both hard PASS, Lower/Upper soft failures without Overall FAIL, worst value/frequency, signed margin, violation intervals, neutral Diagnosis → ACTIVE Intent, checkpoint JSON round-trip, WF-001 composition loading, and test-only node reachability through ACTIVE objective.
- **Full main suite:** `FAIL` — 106 collected, 100 passed, 6 failed. The same one WF-002 CLI and five stale Mock graph/checkpoint/resume failures remain; no new failure was introduced.
- **Safe full-Graph probe:** entered `compare_hfss_results` after optimizer, candidate gate, and candidate HFSS, then reproduced ISSUE-003 `NameError: name 'emit_status' is not defined`. ISSUE-003 was recorded and not repaired.
- **Vendor optimizer suite:** `PASS` — 7 passed.
- **HFSS/AEDT:** NOT RUN.

### Main suite

- **Date:** 2026-08-20
- **Command:** `.venv\Scripts\python.exe -m pytest -q`
- **Post-ISSUE-002 result:** `FAIL` — 106 collected, 100 passed, 6 failed.
- **Failures:** one CLI E2E and five comparison graph/checkpoint/resume tests.
- **Current failure boundary:** the one WF-002 CLI and five Mock graph/checkpoint/resume tests retain empty-rule/1–3 GHz fixtures and stale expectations under ISSUE-008. Production ISSUE-002 is resolved; no failure is newly introduced by its tests.
- **Secondary stale evidence:** graph trace expectations predate diagnosis/intent/objective nodes.

### ISSUE-001 targeted regression

- **Before:** existing `tests\test_cli.py::test_offline_cli_returns_zero_and_creates_complete_artifacts` failed in `build_optimization_intent → emit_optimization_intent` with `NameError: name 'evaluation' is not defined`.
- **After direct:** `tests\test_terminal_output.py::test_optimization_intent_presenter_uses_explicit_evaluation_contract` — `PASS` (1 passed).
- **After presenter file:** `tests\test_terminal_output.py` — `PASS` (8 passed).
- **After original Agent boundary:** the CLI test no longer raises NameError; it fails later because deprecated WF-002 still has empty rules and produces no candidate artifact.

### Current-source Offline route

- **Command:** `.venv\Scripts\python.exe RUN_OFFLINE.py`.
- **Result:** process exits normally; checkpoint trace reaches `build_optimization_objective` and then `complete` with `optimization_intent=INVALID`, `optimization_objective=INVALID`, and no candidate.
- **Interpretation:** this is the deprecated WF-002 formal Offline result. It was deliberately not given the WF-001-only Production contract and remains `FAIL` under ISSUE-008 cleanup scope.

### Package CLI import-origin check

- **Command:** `.venv\Scripts\python.exe -m hfss_optimization_agent ...` plus module `__file__` inspection.
- **Before:** `FAIL / ENVIRONMENT MISMATCH`; import resolved to the old `C:\Users\82074\Documents\Codex\2026-08-12\...\HFSS_Optimization_Agent_VSCode\src` editable path.
- **Repair:** current-repository `uv sync --frozen --inexact --cache-dir .uv-cache`; `uv.lock` unchanged.
- **After import:** `PASS`; package resolves to `D:\Agent_Workspace\HFSS_Optimization_Agent_VSCode\src\hfss_optimization_agent\__init__.py`.
- **After module Offline CLI:** `PASS` for import/current-graph provenance; its deprecated WF-002 command reaches objective and completes INVALID with its unchanged empty-rule fixture.
- **Regression:** `.venv\Scripts\python.exe -m pytest -q tests\test_import_provenance.py` — `PASS` (1 passed).
- **Tracking:** ISSUE-023 RESOLVED; the package CLI command remains WF-002 rather than the WF-001 Production entry.

### Supplied optimizer suite

- **Command:** `.venv\Scripts\python.exe -m pytest -q vendor\optimizer\tests`
- **Result:** `PASS` — 7 passed.
- **Scope limitation:** proves vendor config/model/constraints/quick optimizer, not Agent integration.

### Standalone supplied Builder test

- **Command:** `.venv\Scripts\python.exe -m pytest -q vendor\hfss_builder\test_nine_parameter_builder.py`
- **Result:** `FAIL` during collection — `ModuleNotFoundError: ansys` in Agent Python.
- **Scope limitation:** PyAEDT is installed in a separate interpreter; the main suite's stubbed Builder tests still pass.

### Environment preflight

- **Command:** `.venv\Scripts\python.exe VERIFY_PRESENTATION.py`
- **Result:** `PASS` for Agent Python, LangGraph, PyAEDT interpreter/package 0.18.1, AEDT 2025.1 executable, Builder, optimizer, contract, UI flag, artifact parent, and idle Agent lock.
- **Scope limitation:** does not start AEDT or prove license availability.

### Syntax compilation

- **Command:** `.venv\Scripts\python.exe -m compileall -q src tests tools vendor`
- **Result:** `PASS`.
- **Scope limitation:** compile success cannot find runtime undefined-name paths. It may refresh generated `__pycache__` bytecode; no source was changed.

## Historical real HFSS evidence

Historical status is not current-working-tree validation.

| Capability | Historical evidence | Evidence level |
|---|---|---|
| Baseline Builder | `real-vscode-20260818-101711` baseline journal completed | HISTORICALLY VERIFIED |
| Baseline Solve | baseline journal completed | HISTORICALLY VERIFIED |
| Baseline complex extraction/Touchstone | structured JSON and `.s2p` exist | HISTORICALLY VERIFIED |
| Supplied quick optimizer | optimizer summary completed, 192 evaluations | HISTORICALLY VERIFIED |
| Candidate Builder | candidate `P0001` journal completed | HISTORICALLY VERIFIED |
| Candidate Solve | candidate journal completed | HISTORICALLY VERIFIED |
| Candidate complex extraction/Touchstone | structured JSON and `.s2p` exist | HISTORICALLY VERIFIED |
| Full baseline→optimizer→candidate graph | checkpoint status completed with full old trace | HISTORICALLY VERIFIED |
| Current-tree equivalence | core files postdate run; historical artifact has no Git/source manifest; new Git baseline `52dc0de` was created afterward | UNKNOWN / INSUFFICIENT EVIDENCE |

The historical run selected baseline as Best because HFSS candidate score was worse. Reconstruction-only paired analysis produced:

| Metric | Value |
|---|---:|
| Baseline surrogate worst S11 magnitude | 0.0850343 |
| Candidate surrogate worst S11 magnitude | 0.0841731 (surrogate predicts better) |
| Baseline HFSS worst S11 magnitude | 0.0871267 |
| Candidate HFSS worst S11 magnitude | 0.0881037 (HFSS is worse) |
| Mean complex RMSE | 0.0731982 |
| Mean magnitude-dB RMSE | 3.32705 dB |
| Pairwise ranking agreement | 0.0 |

No calibration policy was applied in Production and no calibration report artifact exists; these values are audit evidence, not a pass/fail calibration declaration.

## Historical failure evidence

- One earlier baseline solve returned `analyze_setup('Setup1') == False`.
- Four earlier builds exited with Windows code `3221226505` without structured detail.
- One earlier build failed on missing explicit material SolveInside classification.
- Four interrupted checkpoints/journals remain marked `running`.
- A later full historical run succeeded, which proves later historical recovery but not the current working tree.

## Baseline environment and dependency evidence

| Item | Value |
|---|---|
| Agent Python | 3.12.13 |
| Platform | Windows 11, build reported as 10.0.26200 |
| LangGraph | 1.2.11 |
| pytest | 8.4.2 |
| numpy / scipy | 2.5.2 / 1.18.0 |
| jax / jaxlib | 0.11.0 / 0.11.0 |
| matplotlib / pymoo | 3.11.1 / 0.6.2 |
| PyAEDT | 0.18.1 in separate interpreter |
| Agent `.venv` pip | NOT AVAILABLE (`No module named pip`) |

Selected `FS-2026-08-20` SHA-256 fingerprints:

| File | SHA-256 |
|---|---|
| `pyproject.toml` | `37ABF71BC6F544804330743384A076E49ECB01468E144B1EE3C38FFD4B35008E` |
| `uv.lock` | `B08FB7C61BD35B5F0BE49F88DC210A6B9769480BF35E7619FECC032D58C623C6` |
| `runtime_config.json` | `C003ED41026D36361D59DB1EBA33588D125790DCA8ADC26063A4C458150AC7F4` |
| `comparison_graph.py` | `58EE9670AE6891A676C97119B5852A341331DA2422C9A696085E6F955AF6B78A` |
| `comparison_nodes.py` | `6922B82394861F2B1C7010EA2961854D5E9D8CE3D717257746CFD570AEB1ABA5` |
| `terminal.py` | `117C2B05E5F6162EF39344A6C063511E375D8B40696A2F48CDA197487081DC1A` |

Current vendor optimizer source, surrogate, and five config hashes match those embedded in the historical successful optimizer summary. This is component equivalence only; no corresponding Agent/Builder manifest exists.
