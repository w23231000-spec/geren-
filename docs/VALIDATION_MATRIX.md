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
| S-parameter rule evaluation | PASS | PASS | PASS | PASS | Evaluator is called and correctly returns INVALID for empty rules; configuration remains ISSUE-002 |
| Baseline diagnosis | PASS | PASS | PASS | PASS | It consumes the observed INVALID evaluation |
| Optimization Intent | PASS | PASS | PASS | PASS | Explicit presenter contract regression passes; current source route no longer raises ISSUE-001 |
| Optimization Objective | PASS | PASS | PASS | PASS | Current source Offline route executes it with INVALID input; ACTIVE behavior remains blocked by ISSUE-002 |
| Supplied surrogate provider | PASS | PASS | NEEDS VERIFICATION | PASS | Formal supplied routes call it before optimizer blockers; current Agent-boundary execution was not isolated |
| Supplied optimizer provider integration / adapter wiring | PASS | PASS | NEEDS VERIFICATION | FAIL | Provider call is wired and vendor tests pass, but current Agent route is blocked before invocation |
| Diagnosis/OptimizationObjective control of supplied optimizer behavior | FAIL | NOT AVAILABLE | FAIL | FAIL | ISSUE-005 causal disconnect: objective is metadata-only after vendor execution |
| Candidate ranking | PASS | PASS | NEEDS VERIFICATION | FAIL | Generic unit behavior passes; supplied adapter returns one candidate and current route does not reach it |
| Candidate parameter validation | PASS | PASS | NEEDS VERIFICATION | FAIL | Existing full-route evidence is masked by ISSUE-002 |
| Candidate surrogate gate | PASS | PASS | NEEDS VERIFICATION | FAIL | Component behavior exists; current formal route does not reach it |
| Candidate HFSS orchestration | PASS | PASS | PASS | FAIL | Fake-backend boundary passes; current formal route is blocked upstream |
| Baseline/candidate comparison | PASS | PASS | FAIL | FAIL | ISSUE-003 is a local integration defect and is currently masked upstream |
| Candidate diagnosis | PASS | PASS | NEEDS VERIFICATION | FAIL | Unit evidence exists; current route does not reach it |
| Best update | PASS | STALE | FAIL | FAIL | ISSUE-004 semantic disconnect is local; current route is also blocked upstream |
| HFSS contract/port/complex conversion | PASS | PASS | PASS | PASS | Fake worker/backend integration passes and baseline HFSS route contains the boundary |
| Target-only Builder | PASS | PASS | PASS | PASS | Stubbed Builder integration passes; real current-tree execution remains NOT RUN |
| Standalone Builder test harness | PASS | FAIL | NOT RUN | NOT AVAILABLE | Collection fails in Agent Python because `ansys` is absent |
| Worker process isolation/timeout | PASS | PASS | PASS | PASS | Child-process fake exercises the boundary; real current-tree execution remains NOT RUN |
| Artifact store | PASS | PASS | PASS | PASS | Upstream artifacts are written before the downstream failure |
| Checkpoint serialization | PASS | PASS | PASS | PASS | Serialization is locally proven and checkpoints are reached before the failure |
| Resume/reuse | PASS | PASS | NEEDS VERIFICATION | PASS | Resume invokes the workflow, but current tests now stop on the ISSUE-002 route before isolating resume semantics |
| Calibration API | PASS | PASS | NOT AVAILABLE | FAIL | API is not connected to any formal workflow |
| Environment preflight | PASS | NOT AVAILABLE | PASS | PASS | Current preflight result is PASS; it does not launch AEDT or prove a license |

## Current full-workflow results

| Workflow | Full Offline result | Current Real HFSS result | Current E2E result | Readiness / evidence |
|---|---|---|---|---|
| WF-001 canonical Production | NOT AVAILABLE | NOT RUN | NOT RUN | FAIL readiness: ISSUE-002 current first blocker, with ISSUE-003 latent |
| WF-002 deterministic Offline | FAIL | NOT AVAILABLE | FAIL | Current source reaches objective, then exits INVALID without candidate because of ISSUE-002 |
| WF-003 supplied optimizer + MockHFSS | NOT RUN | NOT AVAILABLE | NOT RUN | FAIL readiness from shared ISSUE-002 route; it was not separately rerun |
| WF-004 environment preflight | NOT AVAILABLE | NOT RUN | NOT AVAILABLE | PASS for its own read-only preflight scope only |

Interpretation:

- Upstream capability-local `PASS` rows remain `PASS` even though WF-002 terminates with `FAIL` downstream.
- `Workflow reachability FAIL` on downstream rows records masking/blocking, not a failure of their unit tests.
- WF-001 has readiness `FAIL`, but its actual current real-HFSS and E2E results are `NOT RUN`; readiness is not substituted for an execution result.

## Executed validation commands

### Main suite

- **Date:** 2026-08-20
- **Command:** `.venv\Scripts\python.exe -m pytest -q`
- **Post-ISSUE-001 result:** `FAIL` — 94 collected, 88 passed, 6 failed.
- **Failures:** one CLI E2E and five comparison graph/checkpoint/resume tests.
- **Current first proven cause:** ISSUE-002 empty rules produce INVALID intent/objective, so candidate stages are not reached. No failure contains the ISSUE-001 NameError.
- **Secondary stale evidence:** graph trace expectations predate diagnosis/intent/objective nodes.

### ISSUE-001 targeted regression

- **Before:** existing `tests\test_cli.py::test_offline_cli_returns_zero_and_creates_complete_artifacts` failed in `build_optimization_intent → emit_optimization_intent` with `NameError: name 'evaluation' is not defined`.
- **After direct:** `tests\test_terminal_output.py::test_optimization_intent_presenter_uses_explicit_evaluation_contract` — `PASS` (1 passed).
- **After presenter file:** `tests\test_terminal_output.py` — `PASS` (8 passed).
- **After original Agent boundary:** the CLI test no longer raises NameError; it fails later because no candidate artifact is produced under ISSUE-002.

### Current-source Offline route

- **Command:** `.venv\Scripts\python.exe RUN_OFFLINE.py`.
- **Result:** process exits normally; checkpoint trace reaches `build_optimization_objective` and then `complete` with `optimization_intent=INVALID`, `optimization_objective=INVALID`, and no candidate.
- **Interpretation:** ISSUE-001 is repaired; Full Offline remains `FAIL` because ISSUE-002 prevents the optimization/candidate half of the workflow.

### Package CLI import-origin check

- **Command:** `.venv\Scripts\python.exe -m hfss_optimization_agent ...` plus module `__file__` inspection.
- **Result:** `FAIL / ENVIRONMENT MISMATCH`; it imports a stale package from another workspace and its completed old trace is not current-tree evidence.
- **Tracking:** ISSUE-023; no environment modification was made.

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
