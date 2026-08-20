# Workflow Inventory

Baseline: `FS-2026-08-20`. Classification follows reachable code, not historical documentation.

## Inventory summary

Thirteen identifiable entries, harnesses, workers, or callable workflow paths are present. They are not thirteen peer workflows:

- **Canonical Production Workflow = 1:** WF-001.
- **Internal Production Worker = 1:** WF-011. It is an implementation detail invoked by WF-001 and is not counted as an independent Production Workflow.

| ID | Workflow | Classification | Reachable |
|---|---|---|---|
| WF-001 | Real baseline–optimize–candidate HFSS Agent | PRODUCTION | Yes, but BROKEN |
| WF-002 | Deterministic offline Agent | MOCK | Yes, but BROKEN |
| WF-003 | Supplied surrogate/optimizer + MockHFSS Agent | MOCK | Yes, but BROKEN |
| WF-004 | Presentation environment preflight | REGRESSION | Yes, PASS |
| WF-005 | Main pytest suite | TEST ONLY | Yes, FAIL |
| WF-006 | Supplied optimizer pytest suite | TEST ONLY | Yes, PASS |
| WF-007 | Supplied Builder standalone unittest | TEST ONLY | Source present; Agent environment collection FAIL |
| WF-008 | HFSS Builder probe | ACTIVE EXPERIMENT | Yes; not run in this reconstruction |
| WF-009 | Standalone nine-parameter HFSS Builder | REFERENCE | Yes with PyAEDT environment |
| WF-010 | Standalone supplied optimizer/check CLI | REFERENCE | Yes |
| WF-011 | PyAEDT JSON stage Worker | INTERNAL PRODUCTION WORKER | Internal-only, reachable from WF-001; not an independent workflow |
| WF-012 | Electrical-equivalent diagnostic mains | REFERENCE | Yes |
| WF-013 | Paired surrogate/HFSS calibration API | DEAD / UNREACHABLE | Callable API, unreachable from formal entries |

No current `LEGACY` runner, `GOLDEN` workflow, or Golden-data contract was identified. Historical `runs/` are evidence/reference artifacts, not runnable workflows.

## Capability matrix by workflow

| ID | Formal CLI/VS Code | Real HFSS | Modifies AEDT | Surrogate | Optimizer | Evaluator | Checkpoint/resume |
|---|---|---:|---:|---:|---:|---:|---:|
| WF-001 | `RUN_REAL_HFSS.py`, launch 3 | Yes | Yes | supplied | supplied | deterministic rules | Yes |
| WF-002 | `RUN_OFFLINE.py`, `offline-demo`, launch 1 | No | No | deterministic Mock | deterministic Mock | deterministic rules | Yes |
| WF-003 | `RUN_SUPPLIED_WITH_MOCK_HFSS.py`, `supplied-mock-demo`, launch 2 | No | No | supplied | supplied | deterministic rules | Yes |
| WF-004 | `VERIFY_PRESENTATION.py`, launch 0 | No | No | No | No | No | Reads lock only |
| WF-005 | `pytest`, launch 4 | No real HFSS | No AEDT | Mixed test doubles | Mixed | Yes | Tests stores |
| WF-006 | explicit pytest path | No | No | supplied | supplied quick | vendor metrics | No Agent checkpoint |
| WF-007 | explicit unittest/pytest path | No intended | imports PyAEDT Builder | No | No | No | No |
| WF-008 | `tools/probe_hfss_builder.py` | Builds only | Yes | No | No | No | No |
| WF-009 | `vendor/hfss_builder/nine_parameter_builder.py` | Builds only | Yes | No | No | No | No |
| WF-010 | `vendor/optimizer/app/run.py` | No | No | supplied | supplied | vendor metrics/constraints | Vendor result directory |
| WF-011 | module CLI invoked by backend | Yes | Yes | No | No | No | Worker request/response + journal |
| WF-012 | module `__main__` entries | No | No | electrical model only | No | No | No |
| WF-013 | Python API only | Reads paired results | No | paired result input | No | calibration evaluator | Optional writer exists but not called |

## WF-001 — Real baseline–optimize–candidate HFSS Agent

- **Entry:** `RUN_REAL_HFSS.py` → `run_real_supplied_demo`; VS Code launch 3. There is no equivalent package CLI subcommand.
- **Call chain:** runtime config/contract checks → state creation → real/supplied provider composition → shared LangGraph → real baseline HFSS → evaluation/diagnosis/intent/objective → supplied optimizer → candidate gate → real candidate HFSS → comparison/Best/artifacts.
- **Inputs:** runtime JSON, nine-parameter baseline/schema, HFSS contract, vendor optimizer/config, vendor Builder, PyAEDT interpreter.
- **Outputs:** task/checkpoint/baseline/optimizer/candidate/Best JSON, independent AEDT projects, journals, structured complex S parameters, two Touchstone files when fully reached.
- **Reachability:** formal and reachable. Current run reaches an expensive baseline HFSS before ISSUE-001.
- **Verification:** `HISTORICALLY VERIFIED` for run `real-vscode-20260818-101711`; current tree `BROKEN / NOT RUN`.
- **Known issues:** ISSUE-001 through ISSUE-006, ISSUE-009 through ISSUE-015, ISSUE-019.
- **Relation:** same graph as WF-002/WF-003; real HFSS is delegated to WF-011.

## WF-002 — Deterministic offline Agent

- **Entry:** `RUN_OFFLINE.py`; package CLI `offline-demo`; VS Code launch 1.
- **Call chain:** `run_offline_demo` → deterministic surrogate/optimizer/MockHFSS injection → shared graph/artifacts.
- **Inputs:** optional task/artifact root; built-in baseline and 1/2/3 GHz Mock grids.
- **Outputs:** Agent JSON artifacts/checkpoint and CLI summary; no AEDT.
- **Reachability:** formal and reachable; currently fails at optimization-intent terminal output.
- **Verification:** current test-backed `FAIL`; older run directories are `HISTORICALLY VERIFIED` only.
- **Known issues:** ISSUE-001, ISSUE-002, ISSUE-003, ISSUE-004, ISSUE-007, ISSUE-008.
- **Relation:** safest graph regression path and should pass before WF-001.

## WF-003 — Supplied surrogate/optimizer + MockHFSS Agent

- **Entry:** `RUN_SUPPLIED_WITH_MOCK_HFSS.py`; package CLI `supplied-mock-demo`; VS Code launch 2.
- **Call chain:** vendor surrogate frequency/config load → supplied adapters + MockHFSS → shared graph → vendor result directory.
- **Inputs:** `vendor/optimizer` configuration and code, Agent baseline, MockHFSS 1/2/3 GHz.
- **Outputs:** Agent artifacts plus vendor optimizer report/plots/CSV.
- **Reachability:** formal and reachable; shares current graph blockers.
- **Verification:** vendor optimizer components pass; current Agent E2E `BROKEN`; historical supplied-Mock runs exist.
- **Known issues:** ISSUE-001 through ISSUE-005, ISSUE-007 through ISSUE-009.
- **Relation:** validates real surrogate/optimizer without AEDT.

## WF-004 — Presentation environment preflight

- **Entry:** `VERIFY_PRESENTATION.py`; VS Code launch 0.
- **Call chain:** config load → interpreter/AEDT/module/contract/artifact checks → read-only lock owner check → PyAEDT version subprocess.
- **Inputs/outputs:** runtime config and filesystem; console result/exit code only.
- **Reachability:** formal and reachable; does not import PyAEDT into Agent or launch AEDT.
- **Verification:** PASS on 2026-08-20.
- **Known issue:** cannot prove actual license availability; deliberately outside scope.

## WF-005 — Main pytest suite

- **Entry:** `python -m pytest`; VS Code launch 4; `pyproject.toml` restricts `testpaths` to `tests`.
- **Scope:** Agent state/models, graph, evaluation, diagnosis, intent/objective, parameters, mocks, Builder units, HFSS guards/worker protocol, artifacts/checkpoint, terminal.
- **Outputs:** test report and temporary artifacts; no real AEDT.
- **Verification:** 93 collected; 87 PASS, 6 FAIL on 2026-08-20.
- **Known issues:** integration/CLI/resume tests are stale relative to the new graph and expose current blockers (ISSUE-001/008).
- **Relation:** does not automatically include WF-006 or WF-007.

## WF-006 — Supplied optimizer pytest suite

- **Entry:** explicit `pytest vendor/optimizer/tests`.
- **Call chain:** vendor configs/model/surrogate → geometry constraints or quick optimizer → vendor result artifacts.
- **Verification:** 7 PASS on 2026-08-20.
- **Relation:** proves vendor optimizer internals, not Agent adapter/graph integration.

## WF-007 — Supplied Builder standalone unittest

- **Entry:** `vendor/hfss_builder/test_nine_parameter_builder.py`.
- **Scope:** nine-parameter mapping/Builder boundary.
- **Reachability:** source is present, but collection under Agent Python imports `ansys.aedt` and fails because that interpreter lacks `ansys`.
- **Verification:** `FAIL / ENVIRONMENT MISMATCH`; top-level Builder tests use stubs and pass separately.
- **Known issue:** ISSUE-018.

## WF-008 — HFSS Builder probe

- **Entry:** `tools/probe_hfss_builder.py` with request/output/builder-root and `foundation|full` scope.
- **Call chain:** request JSON → map nine parameters → `build_project` milestone/full → save AEDT → close; never solves.
- **Classification reason:** explicit troubleshooting tool, not a formal launch or Production node.
- **Side effects:** creates a real AEDT project and may launch visible/non-graphical AEDT.
- **Verification:** code present; not run during baseline reconstruction.

## WF-009 — Standalone nine-parameter HFSS Builder

- **Entry:** `vendor/hfss_builder/nine_parameter_builder.py` CLI or `build_from_nine_parameters` API.
- **Call chain:** exact-nine input validation → metre-to-mm mapping → `pa_multi_builder.build_project` → target design project; no solve.
- **Inputs/outputs:** JSON nine parameters and new `.aedt` path; refuses overwrite.
- **Verification:** Builder units pass in main suite; historically exercised by WF-001; current standalone environment test is not verified.
- **Relation:** WF-011 build stage imports this API.

## WF-010 — Standalone supplied optimizer/check CLI

- **Entry:** `python vendor/optimizer/app/run.py [--check|--quick|--debug]` or `execute` API.
- **Call chain:** config/catalog/parameter/objective/constraint load → surrogate/model suite → baseline check or NSGA-III/MOPSO/MOSA → Pareto/recommendation → JSON/CSV/plots.
- **Inputs/outputs:** vendor TOML/CSV and result directory; no HFSS despite README language about later HFSS review.
- **Verification:** 7 current tests pass; current hashes match the historical real-E2E optimizer hashes.
- **Relation:** Agent supplied optimizer adapter calls `execute`; Agent optimization intent does not alter its inputs.

## WF-011 — PyAEDT JSON stage Worker

- **Entry:** `python -m hfss_optimization_agent.hfss.pyaedt_worker --stage build|solve|extract`; invoked only by `JsonSubprocessHFSSBackend` in Production.
- **Classification:** `INTERNAL PRODUCTION WORKER`. It is a subprocess boundary inside WF-001, not a second canonical Production Workflow and not an independently counted Production entry.
- **Call chain:** request JSON → one isolated stage → response JSON; build imports WF-009, solve calls `analyze_setup`, extract exports complex data and Touchstone.
- **Side effects:** launches/controls AEDT and writes projects/exports.
- **Verification:** protocol/timeout unit integration passes; all three stages are historically real verified for baseline and candidate.
- **Known issues:** historical build crashes/solve failure, current version traceability gap, frequency endpoint validation gap.

## WF-012 — Electrical-equivalent diagnostic mains

- **Entries:** `_main` in `parameter_calculator.py`, `circuit_topology.py`, and `s_parameter_simulator.py`.
- **Call chain:** built-in/example geometry → component/topology calculation → optional simulation/print.
- **Classification reason:** developer reference diagnostics, not called by Agent entries. Production surrogate reaches the same model through `SurrogateAdapter`, not these mains.
- **Verification:** underlying model is covered by vendor optimizer tests; standalone mains not run.

## WF-013 — Paired surrogate/HFSS calibration API

- **Entry:** no CLI/graph node; callable `assess_calibration(cases, policy)` only.
- **Call chain:** paired candidate/surrogate/HFSS data → compatibility checks → complex and dB errors → pairwise rank agreement → `CalibrationReport`.
- **Inputs/outputs:** in-memory paired results/report; `ArtifactStore.write_calibration_report` exists but no caller connects them.
- **Reachability:** unreachable from every formal entry: `NOT WIRED INTO PRODUCTION`.
- **Verification:** unit tests pass. A reconstruction-only read of the historical real run found ranking agreement 0.0; no production report exists.
- **Known issues:** ISSUE-009.
