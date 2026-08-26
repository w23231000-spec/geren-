# Workflow Inventory

Baseline: `FS-2026-08-20`. Classification follows reachable code, not historical documentation.

## Inventory summary

Twenty identifiable entries, harnesses, workers, or callable workflow paths are present. They are not twenty peer workflows:

- **Canonical Production Workflow = 1:** WF-001.
- **Internal Tool Workers = 2:** WF-011 and WF-014. They are implementation details and are not counted as independent Production Workflows.

| ID | Workflow | Classification | Reachable |
|---|---|---|---|
| WF-001 | Real bounded Closed-loop V2 HFSS Agent | PRODUCTION | Code path reachable, execution fail-closed / NOT READY |
| WF-002 | Deterministic Closed-loop V2 Agent | MOCK | Yes, END-TO-END VERIFIED |
| WF-003 | Supplied surrogate/optimizer + MockHFSS V2 Agent | MOCK | Yes, END-TO-END VERIFIED |
| WF-004 | Presentation environment preflight | REGRESSION | Yes, PASS |
| WF-005 | Main pytest suite | TEST ONLY | Yes, PASS |
| WF-006 | Supplied optimizer pytest suite | TEST ONLY | Yes, PASS |
| WF-007 | Supplied Builder standalone unittest | TEST ONLY | Source present; Agent environment collection FAIL |
| WF-008 | HFSS Builder probe | ACTIVE EXPERIMENT | Yes; not run in this reconstruction |
| WF-009 | Standalone nine-parameter HFSS Builder | REFERENCE | Yes with PyAEDT environment |
| WF-010 | Standalone supplied optimizer/check CLI | REFERENCE | Yes |
| WF-011 | PyAEDT JSON composite/stage Worker | INTERNAL PRODUCTION WORKER | Internal-only, reachable from WF-001; not an independent workflow |
| WF-012 | Electrical-equivalent diagnostic mains | REFERENCE | Yes |
| WF-013 | Paired surrogate/HFSS calibration evidence API | LIBRARY / REAL-GATE INPUT | Callable evidence generator; no automatic physical collection entry |
| WF-014 | Supplied optimizer JSON Worker | INTERNAL TOOL WORKER | Reachable from WF-001/WF-003; not an independent workflow |
| WF-015 | Deterministic V2 Closed-loop Agent | MOCK AGENT | Yes, END-TO-END VERIFIED |
| WF-016 | Supplied Tools + MockHFSS V2 Closed-loop Agent | MOCK AGENT | Yes, END-TO-END VERIFIED |
| WF-017 | Authorized three-case real-HFSS Calibration collection | PHYSICAL EVIDENCE | Yes, default-disabled; REAL HFSS VERIFIED / CALIBRATION FAILED |
| WF-018 | Exact Canary readiness issuance | AUTHORITY ISSUER | Yes, but current failing evidence is rejected |
| WF-019 | Versioned physical-model and Calibration policy contracts | CONTRACT LIBRARY | Yes, WIRED / OFFLINE VERIFIED |
| WF-020 | Frozen optimization-outcome HFSS A/B diagnostic | DIAGNOSTIC PHYSICAL EVIDENCE | Code reachable, default-disabled / REAL RUN NOT AUTHORIZED |

No executable `LEGACY` runner, `GOLDEN` workflow, or Golden-data contract exists. The former one-pass characterization is preserved as `tests/legacy_comparison_graph_characterization.py.disabled`; historical checkpoints/runs are evidence/reference artifacts, not runnable workflows.

## Capability matrix by workflow

| ID | Formal CLI/VS Code | Real HFSS | Modifies AEDT | Surrogate | Optimizer | Evaluator | Checkpoint/resume |
|---|---|---:|---:|---:|---:|---:|---:|
| WF-001 | `RUN_REAL_HFSS.py`, blocked Canary launch 3 | Yes, only after separate authorization | Yes | supplied | supplied | Production Evaluation Contract v1 | V2 controller + SQLite RunStore/action receipts |
| WF-002 | `RUN_OFFLINE.py`, `offline-demo`, launch 1 | No | No | deterministic Mock | deterministic Mock | Offline Evaluation Contract v1 | V2 controller + SQLite RunStore/action receipts |
| WF-003 | `RUN_SUPPLIED_WITH_MOCK_HFSS.py`, `supplied-mock-demo`, launch 2 | No | No | supplied | supplied | Offline Evaluation Contract v1 | V2 controller + SQLite RunStore/action receipts |
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
| WF-014 | module CLI invoked by adapter | No | No | supplied vendor model | supplied | vendor objectives/constraints/metrics | canonical request/response + vendor result directory |
| WF-015 | `RUN_CLOSED_LOOP_OFFLINE.py`, `closed-loop-offline-demo`, launch 2A | No | No | deterministic Mock | deterministic Mock | Offline Evaluation Contract v1 | RunStore + typed controller/checkpoints |
| WF-016 | `RUN_CLOSED_LOOP_SUPPLIED_MOCK.py`, `closed-loop-supplied-mock-demo`, launch 2B | No | No | supplied | supervised supplied worker | Offline Evaluation Contract v1 | RunStore + typed controller/checkpoints |
| WF-017 | `PREPARE_HFSS_CALIBRATION.py` + `RUN_HFSS_CALIBRATION.py` | Yes, separately authorized | Yes | supplied | No | Calibration policy | RunStore + 15 immutable receipts |
| WF-018 | `PREPARE_REAL_HFSS_CANARY.py` | No | No | Reads evidence | No | Recomputes Calibration | Emits short-lived authority only |
| WF-019 | Strict contract loaders | No | No | No | No | Model-alignment/Calibration contracts | No execution state |
| WF-020 | `PREPARE_HFSS_OPTIMIZATION_DIAGNOSTIC.py` + `RUN_HFSS_OPTIMIZATION_DIAGNOSTIC.py` | Yes, separately authorized | Yes | supplied/frozen | Reads completed full run | Baseline-versus-candidate outcome metrics | RunStore + 10 immutable receipts |

## WF-001 — Real baseline–optimize–candidate HFSS Agent

- **Entry:** `RUN_REAL_HFSS.py` → `run_real_supplied_demo`; VS Code launch 3 is labelled blocked until separately authorized. There is no equivalent package CLI subcommand. The checked-in config has no manifest; a future explicit invocation must supply the external path in `HFSS_REAL_READINESS_MANIFEST`.
- **Call chain:** disabled/manifest check → strict readiness + passing Calibration Evidence → exact repository/Goal/contracts/providers/Production-policy digest → Production V2 controller composition → fenced bootstrap baseline → sole Policy router → prepare/optimize/queue/screen → at most one candidate HFSS → compare/diagnose/Best → next/reoptimize/reconcile or typed finalization → structured final manifest → atomic completed checkpoint. RunStore independently limits physical HFSS launches to two with zero automatic retries.
- **Inputs:** runtime JSON, short-lived Readiness Manifest V1.1 containing passing recomputable `calibration-evidence/1.1`, exact clean Git revision, versioned model alignment/policy, Production Evaluation Contract v1, nine-parameter baseline/schema, HFSS contract, vendor optimizer/config, vendor Builder, and PyAEDT interpreter bytes.
- **Outputs:** SQLite action/event/checkpoint ledger; immutable canonical Tool/evaluation/comparison/terminal/final-manifest artifacts; immutable registered copies of provider request/response/report, AEDT project, journal, and Touchstone files when reached. Mutable workspaces are convenience copies only.
- **Recovery control plane:** checkpoint identity/integrity is checked before provider admission. UNKNOWN recovery uses an exact evidence-bound operator reconciliation API; it is not a runnable workflow entry and never calls the provider.
- **Reachability:** the V2 call graph is reachable, but the checked-in formal entry stops before composition because current config is disabled and has no manifest. The dirty tree independently fails exact-HEAD readiness. Drift and policy-digest regressions prove invalid bindings cannot reach real worker composition/workspace creation. A safe no-AEDT Production-band V2 test promotes the `FULLY_ACHIEVED` candidate and emits `succeeded_candidate`. Current real execution is NOT RUN.
- **Verification:** `HISTORICALLY VERIFIED` for run `real-vscode-20260818-101711`; current tree real route `NOT RUN / NOT READY`. Readiness, exact formal identity, two-launch/no-retry admission, approval, budget, UNKNOWN, receipt replay, evidence-bound reconciliation, checkpoint corruption handling, and Run fencing are `OFFLINE VERIFIED` with test doubles only.
- **Known issues:** ISSUE-001/002/003/004/005/006/014/024/025/027/029 resolved offline; ISSUE-009 is partial because no accepted current paired evidence exists; ISSUE-010/011/012/013/019 remain open/partial; ISSUE-015/026 remain partial pending real AEDT, while ISSUE-028 is partial domain-wide. V1 checkpoints are explicit non-actionable evidence only.
- **Relation:** same V2 Policy topology as WF-002/WF-003; real HFSS is delegated to WF-011 and supplied optimization to WF-014.

## WF-002 — Deterministic offline Agent

- **Entry:** `RUN_OFFLINE.py`; package CLI `offline-demo`; VS Code launch 1.
- **Call chain:** `run_offline_demo` delegates to the deterministic Closed-loop V2 composition and bounded Policy.
- **Inputs:** optional task/artifact root; built-in baseline, 1/2/3 GHz Mock grids, and versioned `offline-evaluation-v1`.
- **Outputs:** SQLite Run/action/event/checkpoint ledger, immutable canonical JSON artifacts, and CLI summary; no AEDT.
- **Reachability:** formal and reachable through bootstrap, sole controller router, bounded candidate loop, and typed END.
- **Verification:** `END-TO-END VERIFIED` offline; CLI returns zero only for `succeeded_candidate`/`succeeded_baseline`.
- **Known issues:** completed reinvocation is a strict no-op, crash replay does not duplicate provider calls, and UNKNOWN has evidence-bound reconciliation; resume still begins at graph START under ISSUE-013.
- **Relation:** safest V2 Agent regression path and should pass before WF-001.

## WF-003 — Supplied surrogate/optimizer + MockHFSS Agent

- **Entry:** `RUN_SUPPLIED_WITH_MOCK_HFSS.py`; package CLI `supplied-mock-demo`; VS Code launch 2.
- **Call chain:** vendor surrogate/config → canonical OptimizerRequest → supervised WF-014 → full candidate set/ranking → bounded Policy queue consumption → MockHFSS/evaluation → typed END.
- **Inputs:** `vendor/optimizer` configuration/code, Agent baseline, MockHFSS 1/2/3 GHz, and `offline-evaluation-v1`.
- **Outputs:** RunStore receipts, immutable canonical Agent artifacts, immutable registered copies of supplied-worker/vendor files, structured final manifest, plus non-authoritative mutable workspace copies.
- **Reachability:** formal and reachable through the canonical V2 composition.
- **Verification:** actual supplied worker plus MockHFSS reaches typed END: `END-TO-END VERIFIED` offline.
- **Known issues:** ISSUE-009 accepted physical calibration evidence and ISSUE-013 START-replay semantics. V1 checkpoints are not executable. Formal native output provenance is resolved offline.
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
- **Scope:** Domain Contract/State V2/canonical codec, sole Closed-loop V2 Policy/router, Production policy/budget binding, controller/Tool/stagnation budgets, queue/reoptimization/retry/reconcile/typed finalization, structured decision/final-manifest evidence, evaluation/diagnosis/intent/objective, Calibration Evidence/real gate, supervised Tools/process safety, exact readiness/two-solve admission, RunStore/Harness concurrency/chaos/reconciliation, immutable artifacts, explicit historical checkpoint classification, and terminal semantics.
- **Outputs:** test report and temporary artifacts; no real AEDT.
- **Verification:** final 213 PASS in 45.71 s on 2026-08-24 after ISSUE-019 closure. Sixteen obsolete one-pass tests are preserved disabled; current V2 reliability and full frequency-grid contract coverage are collected.
- **Known boundary:** this suite uses no real AEDT. Actual AEDT termination/readability, saved-node continuation, and current physical calibration evidence remain unverified/absent; the frequency-grid rule itself is offline verified.
- **Relation:** does not automatically include WF-006 or WF-007.

## WF-006 — Supplied optimizer pytest suite

- **Entry:** explicit `pytest vendor/optimizer/tests`.
- **Call chain:** vendor configs/model/surrogate → geometry constraints or quick optimizer → vendor result artifacts.
- **Verification:** 7 PASS on 2026-08-22 after Phase 5C (4.67 s).
- **Relation:** proves vendor optimizer internals, not Agent adapter/graph integration.

## WF-007 — Supplied Builder standalone parameter-mapping unittest

- **Entry:** `vendor/hfss_builder/test_nine_parameter_builder.py`.
- **Scope:** pure exact-nine validation and metre-to-mm parameter mapping; intentionally no PyAEDT project construction.
- **Reachability:** formal standalone test under the Agent `.venv`; `parameter_mapping.py` has no `ansys` import.
- **Verification:** `UNIT TESTED` — 3 passed under Agent Python; ISSUE-018 resolved offline.
- **Known boundary:** actual Builder execution remains WF-009/WF-011 and requires the declared PyAEDT interpreter.

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
- **Relation:** standalone reference only. Formal Agent calls use WF-014, which creates a request-derived objective CSV before calling vendor `execute` and verifies the vendor summary.

## WF-011 — PyAEDT JSON composite/stage Worker

- **Entry:** `python -m hfss_optimization_agent.hfss.pyaedt_worker --stage composite|build|solve|extract`; invoked only by `JsonSubprocessHFSSBackend` in Production. Formal attested execution uses `composite`; individual stages remain compatibility/test paths.
- **Classification:** `INTERNAL PRODUCTION WORKER`. It is a subprocess boundary inside WF-001, not a second canonical Production Workflow and not an independently counted Production entry.
- **Call chain:** Builder attestation and snapshot before license → composite request JSON → Job-assigned worker plus Job-contained native-call heartbeat companion → snapshot Builder import → build → solve → extract complex data → validate the full returned grid against the sweep contract → Touchstone/structured export → digest-bound response JSON.
- **Side effects:** launches/controls AEDT and writes projects/exports.
- **Verification:** composite protocol, attestation drift, full returned-grid validation, native-call heartbeat independence, timeout/cancel upper bound, descendant termination, parent-death cleanup, residual-process UNKNOWN, and evidence-bound lock archival pass offline. The configured AEDT 2025 R1 Python 3.10 imports both the companion and worker CLI. The seventh physical campaign verified exact target build through Solve submission; completed Solve/extraction remains pending.
- **Known issues:** accepted physical output remains unverified. Unverified cleanup is fail-closed as `UNKNOWN` with a quarantined lock; release is explicit, evidence-bound, and archives rather than deletes the marker.

## WF-012 — Electrical-equivalent diagnostic mains

- **Entries:** `_main` in `parameter_calculator.py`, `circuit_topology.py`, and `s_parameter_simulator.py`.
- **Call chain:** built-in/example geometry → component/topology calculation → optional simulation/print.
- **Classification reason:** developer reference diagnostics, not called by Agent entries. Production surrogate reaches the same model through `SurrogateAdapter`, not these mains.
- **Verification:** underlying model is covered by vendor optimizer tests; standalone mains not run.

## WF-013 — Paired surrogate/HFSS Calibration evidence API

- **Entry:** callable `assess_calibration(cases, policy)` plus `create_calibration_evidence(...)`; physical collection is WF-017 and remains default-disabled.
- **Call chain:** paired candidate/surrogate/HFSS data → compatibility/error/rank checks → report → strict context/provider/policy/source-bound evidence.
- **Inputs/outputs:** at least three paired results/two comparable pairs and the approved policy produce `calibration-evidence/1.1`, including structured cases, report, full provider identity, and five immutable receipts per case.
- **Reachability:** generation is an explicit library workflow; its output is a mandatory semantic input to WF-001 readiness and RunStore real registration.
- **Verification:** unit/integration tests cover compatible/reversed/context/grid cases, canonical round-trip, policy/provider/artifact/semantic/report drift, and full readiness recomputation. ISSUE-031 is resolved offline. Historical ranking agreement remains 0.0.
- **Known issue:** ISSUE-009 remains partial because no passing current physical dataset has yet been collected.

## WF-014 — Supplied optimizer JSON Worker

- **Entry:** `python -m hfss_optimization_agent.optimization.supplied_worker`; invoked only by `SuppliedBatchOptimizerAdapter`.
- **Classification:** `INTERNAL TOOL WORKER`; it is a supervised Tool subprocess inside WF-001/WF-003, not an independent Agent workflow.
- **Call chain:** canonical OptimizerRequest JSON → heartbeat → request-derived effective-objective CSV → vendor `execute` → vendor-summary objective verification → parse every Pareto row/evidence → digest-bound canonical response.
- **Outputs:** full auditable candidate set/digests plus immutable registered copies of worker request/response/vendor artifacts.
- **Verification:** actual quick vendor execution through the independent worker passes offline. Timeout/cancel supervision shares the Windows Job boundary; formal WF-003 E2E remains `NEEDS VERIFICATION`.

## WF-015 — Deterministic V2 Closed-loop Agent

- **Entry:** compatibility alias `RUN_CLOSED_LOOP_OFFLINE.py`; package alias `closed-loop-offline-demo`; canonical formal aliases are WF-002 entries.
- **Classification:** `MOCK AGENT` using the sole formal V2 topology. Real manifests are rejected before provider execution.
- **Call chain:** baseline observe/evaluate/diagnose → sole Policy router → prepare/optimize → queue select/screen → fake HFSS evaluate/diagnose/Best → next candidate, reoptimize, or typed finalization.
- **Control contract:** strict controller decision history plus controller/optimizer/screen/HFSS/reoptimization/retry/stagnation budgets; one conditional router; every nonterminal action returns to Policy.
- **Verification:** `END-TO-END VERIFIED` offline for baseline PASS, screen fail→next, improved non-PASS→next/reoptimize, PASS→Best/success, safe retry, budget/stagnation exhaustion→NO_SOLUTION, reconciliation route, and arbitrary-sequence iteration bound.
- **Relation:** compatibility naming for the same implementation used by WF-002 and WF-001.

## WF-016 — Supplied Tools + MockHFSS V2 Closed-loop Agent

- **Entry:** compatibility alias `RUN_CLOSED_LOOP_SUPPLIED_MOCK.py`; package alias `closed-loop-supplied-mock-demo`; canonical formal aliases are WF-003 entries.
- **Classification:** `MOCK AGENT` using the sole formal V2 topology; real HFSS/AEDT is structurally rejected.
- **Call chain:** supplied surrogate → canonical request → WF-014 supervised quick optimizer/full candidate set → persisted ranking → bounded Policy queue consumption → MockHFSS → typed terminal.
- **Outputs:** RunStore action/event/checkpoint evidence, structured decisions/budgets, immutable canonical/native artifacts, and `final-run-manifest/1.0`.
- **Verification:** actual supplied worker plus MockHFSS reaches a typed END in the Phase 4 test suite: `END-TO-END VERIFIED` offline. No AEDT/HFSS license/process is involved.
- **Known boundary:** Production adoption is complete offline; current physical calibration evidence and Phase 6 Canary authorization remain absent.

## WF-017 — Authorized three-case real-HFSS Calibration collection

- **Entries:** `PREPARE_HFSS_CALIBRATION.py` issues authority without AEDT; `RUN_HFSS_CALIBRATION.py` configures UTF-8 console output and executes only when `HFSS_CALIBRATION_MANIFEST` is explicitly supplied.
- **Admission:** checked-in defaults are disabled. Issuance requires a clean exact HEAD and binds Agent/optimizer/surrogate/Builder/PyAEDT/protocol/policy bytes, exact HFSS contract and model alignment, expiry, three deterministic candidate snapshots (baseline plus two interior points), and `ExecutionPolicy(3,0)`.
- **Call chain:** validate authority before composition → Harness/RunStore registration → for each case freeze candidate → supplied surrogate receipt → one composite real HFSS action → freeze result, exact `.aedt`, and exact `.s2p` → assess approved policy → publish strict immutable Calibration Evidence.
- **Safety:** every physical action is approval-, budget-, attempt-, idempotency-, and ambiguity-bound; no automatic retry. Any UNKNOWN/timeout/residual process stops normal progress.
- **Verification:** fake three-case end-to-end campaign passes with 15 typed source receipts; manifest drift/default-disable/budget tests pass offline. Current physical campaign `hfss-calibration-20260825-082540` at exact revision `d5642979...` completed all three target-only build/Solve/extraction operations and froze all 15 required receipts. The generated strict evidence is valid but failed approved accuracy/ranking thresholds, so WF-017 is `REAL HFSS VERIFIED / CALIBRATION FAILED`, not passing readiness evidence.

## WF-018 — Exact Canary readiness issuance

- **Entry:** `PREPARE_REAL_HFSS_CANARY.py`; never constructs a worker or launches AEDT.
- **Admission:** requires a clean exact HEAD and a passing immutable WF-017 evidence JSON. It rebinds current policy/alignment/contracts/provider bytes, constructs the exact Production State/RunManifest identity, writes an eight-hour `real-hfss-readiness/1.1` manifest with `ExecutionPolicy(2,0)`, then validates the complete manifest and Calibration source artifacts before returning it.
- **Output:** ignored short-lived authority under `runs/authorizations`; no checked-in enable flag is changed.
- **Verification:** syntax and the underlying readiness/binding/recomputation suite pass offline; the current failing physical evidence is intentionally ineligible, so no Canary manifest may be generated from it.

## WF-019 — Versioned physical-model and Calibration policy contracts

- **Entries:** strict loaders for `config/model_alignment.hfss_builder_v1.json` and `config/calibration_policy.paired_surrogate_hfss_v1.json`.
- **Authority:** user-approved existing HFSS Builder; PI 3.5/0.02 and the exact HFSS contract/context/grid/ports/impedance are fixed before observing Calibration results. Empirical surrogate terms are conditionally accepted only by passing physical evidence.
- **Verification:** strict field/content/contract/digest checks are wired into WF-017/WF-018/WF-001 and pass offline.

## WF-020 — Frozen optimization-outcome real-HFSS A/B diagnostic

- **Entries:** `PREPARE_HFSS_OPTIMIZATION_DIAGNOSTIC.py` issues authority without AEDT; `RUN_HFSS_OPTIMIZATION_DIAGNOSTIC.py` runs only when `HFSS_OPTIMIZATION_DIAGNOSTIC_MANIFEST` is explicitly supplied.
- **Purpose:** answer whether the one recommendation produced by the current complete surrogate optimization improves real HFSS performance relative to the unchanged baseline. It is diagnostic evidence, not Calibration and not the formal Production Canary.
- **Admission:** checked-in defaults are disabled. The issuer requires a clean exact HEAD, completed non-quick optimizer summary, one unique recommendation with predicted worst-S11 and mean-reflected-power improvement, exact provider/source/contract identities, eight-hour expiry, and `ExecutionPolicy(2,0)`.
- **Call chain:** validate authority before composition → freeze baseline and `optimized_P0028` → one surrogate and one composite HFSS result for each case → freeze candidate/result/`.aedt`/`.s2p` receipts → compute physical before/after metrics and an explicit `formal_canary_authorized=false` report.
- **Safety:** exactly two physical launches, independent workspaces, target design `interposer_temple4`, hard deadlines, process isolation, license lock, zero automatic retries, and evidence-bound UNKNOWN reconciliation.
- **Verification:** focused fake campaign 5 PASS; full main suite 238 PASS; complete vendor optimization and vendor suite 7 PASS; environment preflight PASS. Default execution and dirty-tree issuance both fail closed. Real HFSS is `NOT RUN`; no manifest has been issued.
