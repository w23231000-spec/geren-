# Current Architecture

This document describes the current filesystem snapshot reconstructed on 2026-08-20. It intentionally excludes obsolete architectures unless they remain reachable code.

## Component architecture

```text
Entry scripts / package CLI
        │
        ▼
cli.py: state creation and provider selection
        │
        ▼
composition.py: dependency injection
        │
        ├── ParameterValidator
        ├── SParameterInterface implementation
        ├── BatchOptimizerInterface implementation
        ├── HFSSInterface implementation
        ├── DeterministicEvaluator + EvaluationComparator
        ├── DiagnosisNode + intent/objective builders
        ├── ArtifactStore + JsonComparisonCheckpointStore
        └── WorkflowRouter + DeterministicSupervisor
        │
        ▼
comparison_graph.py: one shared LangGraph topology
        │
        ▼
comparison_nodes.py: state transformations and service calls
```

There is one Agent graph topology. Offline, supplied-Mock, and real-HFSS workflows differ through provider injection, not through separate graphs.

## State

`ComparisonAgentState` is the single graph state. It contains identity and target data; baseline/candidate S-parameter, HFSS, evaluation, comparison, and diagnosis results; optimization intent/objective/batch/queue; current and Best candidates; histories; status; route action; errors; metadata; and execution trace.

`comparison_state_to_dict` and `comparison_state_from_dict` provide JSON-safe conversion for dataclasses, complex two-port responses, diagnosis, intent, objective, and histories. State is persisted by `JsonComparisonCheckpointStore`, not by a LangGraph checkpointer.

## Graph and nodes

```text
START
→ initialize_task
→ calculate_baseline_sparameters
→ run_baseline_hfss
→ diagnose_baseline
→ freeze_baseline
→ build_optimization_intent
→ build_optimization_objective
→ [intent ACTIVE?]
   ├─ no  → complete → END
   └─ yes → run_optimizer
           → select_optimized_candidate
           → validate_optimized_candidate
           → recalculate_candidate_sparameters
           → candidate_sparameter_gate
           → [RUN_HFSS?]
              ├─ no  → complete → END
              └─ yes → run_candidate_hfss
                      → compare_hfss_results
                      → diagnose_candidate
                      → update_hfss_best
                      → decide_after_hfss
                      → complete → END
```

The source announces 14 presentation stages, but the graph has 17 nodes and reuses stage numbers for several pairs of nodes.

| Node | Reads | Writes | Service / side effect | Route or termination |
|---|---|---|---|---|
| `initialize_task` | task ID, target | status, metadata, trace | initializes task artifacts | none |
| `calculate_baseline_sparameters` | baseline parameters | baseline result/history | surrogate, artifact, checkpoint | raises on failed result |
| `run_baseline_hfss` | baseline, target | baseline HFSS/evaluation, initial Best | HFSS, evaluator, artifacts | raises on failed baseline HFSS |
| `diagnose_baseline` | baseline evaluation | diagnosis/history | DiagnosisNode | none |
| `freeze_baseline` | both baseline results | trace | checkpoint | raises if baseline missing |
| `build_optimization_intent` | baseline diagnosis | intent | IntentBuilder, artifact, terminal | current blocker at terminal output |
| `build_optimization_objective` | intent, evaluation | objective | ObjectiveBuilder | ACTIVE or complete |
| `run_optimizer` | baseline, surrogate, objective | batch, queue | optimizer; optional surrogate reranking | raises on optimizer failure |
| `select_optimized_candidate` | batch, queue | candidate, queue | artifact | none |
| `validate_optimized_candidate` | candidate | trace | ParameterValidator | raises on invalid values |
| `recalculate_candidate_sparameters` | candidate | candidate result/history | surrogate | failure left to gate |
| `candidate_sparameter_gate` | candidate surrogate | next action | router | RUN_HFSS or complete |
| `run_candidate_hfss` | candidate | candidate HFSS/history | HFSS | failed result does not raise |
| `compare_hfss_results` | baseline/candidate | evaluation/comparison/history | evaluator/comparator | latent missing import |
| `diagnose_candidate` | evaluation/comparison | diagnosis/history | DiagnosisNode | none |
| `update_hfss_best` | evaluation, candidate, Best | optional Best | artifact/checkpoint | semantic disconnect exists |
| `decide_after_hfss` | result/evaluation | next action | router | PASS and STOP both complete |
| `complete` | state | completed status, trace | checkpoint | END |

## Provider variants

| Boundary | Offline | Supplied Mock | Production real |
|---|---|---|---|
| Surrogate | `DeterministicSurrogate` | `SuppliedSurrogateAdapter` | `SuppliedSurrogateAdapter` |
| Optimizer | `DeterministicBatchOptimizer` | `SuppliedBatchOptimizerAdapter` | `SuppliedBatchOptimizerAdapter` |
| HFSS | `MockHFSS` | `MockHFSS` | `GuardedHFSSAdapter` |
| Evaluator | `DeterministicEvaluator` | same | same |
| Graph | shared | shared | shared |

## Module inventory

| Module/capability | Implementation status | Verification status | Production relation |
|---|---|---|---|
| State and serialization | WIRED | UNIT TESTED | Shared by all Agent workflows |
| LangGraph topology | WIRED / BROKEN | Current integration FAIL | Shared Production topology |
| Workflow nodes | WIRED / BROKEN | Current integration FAIL | Shared Production behavior |
| Composition root | WIRED | Component construction tested | Selects Production/Mock providers |
| Interfaces | ACTIVE | UNIT TESTED with doubles | Provider boundary |
| Nine-parameter schema/validator | WIRED | UNIT TESTED | Production input contract |
| Deterministic surrogate | ACTIVE MOCK | Component tested; E2E FAIL | Offline only |
| Supplied surrogate adapter | WIRED | Vendor runtime tested; historical real use | Production |
| Deterministic optimizer | ACTIVE MOCK | Component tested; E2E FAIL | Offline only |
| Supplied optimizer provider integration / adapter wiring | WIRED / NEEDS VERIFICATION | Vendor tests PASS; current Agent route does not reach provider | Production provider boundary |
| Diagnosis/OptimizationObjective behavioral control of supplied optimizer | NOT WIRED / CAUSAL DISCONNECT | Static source evidence; ISSUE-005 OPEN | Production objective is metadata-only after vendor execution |
| Optimization intent | WIRED / BROKEN ROUTE | UNIT TESTED | Production node; terminal blocker |
| Optimization objective | WIRED / NOT CURRENTLY REACHED | UNIT TESTED | Production node |
| Candidate ranking | PARTIALLY WIRED | UNIT TESTED | Single supplied candidate limits effect |
| HFSS gate/router/supervisor | WIRED | Older integration evidence STALE | Production control |
| HFSS contract/converter | WIRED | UNIT TESTED | Production boundary |
| Guarded HFSS adapter | WIRED | INTEGRATION TESTED with fake backend | Production |
| JSON worker backend | WIRED | INTEGRATION TESTED | Production |
| PyAEDT Worker | WIRED | Contract tested; HISTORICALLY VERIFIED | Production internal |
| Nine-parameter Builder | WIRED | Unit tested; HISTORICALLY VERIFIED | Production build stage |
| MockHFSS | ACTIVE MOCK | UNIT TESTED; E2E FAIL | Offline/supplied-Mock |
| Rule evaluator | WIRED BUT UNCONFIGURED | UNIT TESTED | Production node, no entry rules |
| Evaluation comparator | WIRED | UNIT TESTED; latent integration error | Production node |
| Diagnosis | WIRED | UNIT TESTED | Production node |
| Best update | WIRED / SEMANTICALLY BROKEN | Integration FAIL | Production node |
| Calibration | PRESENT BUT UNUSED | UNIT TESTED | NOT WIRED INTO PRODUCTION |
| Artifact store | WIRED | UNIT TESTED | All Agent workflows |
| JSON checkpoint | WIRED | UNIT TESTED; resume E2E FAIL | All Agent workflows |
| Resume | PARTIALLY WIRED | Current E2E FAIL | Programmatic only |
| Runtime configuration | ACTIVE / INCOMPLETE | Preflight PASS | Missing evaluation contract |
| Package CLI | ACTIVE / PARTIAL | Offline CLI FAIL | No real-HFSS subcommand |
| VS Code launches | ACTIVE | Preflight PASS; workflow launches not current PASS | User-facing entry set |
| Regression preflight | ACTIVE | PASS | Read-only environment check |
| Thermal model | PRESENT CONFIG ROW / NOT CONNECTED | NOT VERIFIED | Not Production |
| Reliability model | PRESENT CONFIG ROW / NOT CONNECTED | NOT VERIFIED | Not Production |
| `UnavailableHFSSBackend` | PRESENT BUT UNUSED | NOT VERIFIED | Reference/failure placeholder |
| `metric_deltas` helper | PRESENT BUT UNUSED | NOT VERIFIED | No current caller identified |

## HFSS boundary

```text
GuardedHFSSAdapter
→ sanitized unique workspace
→ FileLicenseLock
→ JsonSubprocessHFSSBackend
   → build worker → vendor nine_parameter_builder → interposer_temple4 project
   → solve worker → validate design/Setup1 → analyze_setup
   → extract worker → complex 2×2 S parameters + Touchstone + JSON
→ contract conversion and validation
→ HFSSResult and journal
```

Each stage has a process timeout. Baseline and candidate use new workspaces. The Worker checks exact parameter names, design identity, Setup presence, point count, port order, representation, and impedance. It does not compare returned frequency endpoints with contract endpoints; see ISSUE-019.

## Optimization boundary

The supplied adapter validates baseline parameters, then calls `vendor/optimizer/app/run.py::execute` using static TOML/CSV configuration. It returns the single recommended Pareto point as the Agent batch.

The graph passes `optimization_objective` into the adapter, but the adapter records it only in batch metadata after the vendor run; it does not translate it into vendor objectives or constraints. Graph reranking has no choice when the adapter returns one candidate. This is the `CAUSAL DISCONNECT` in ISSUE-005.

## Evaluation and diagnosis boundary

`DeterministicEvaluator.evaluate_sparameters` evaluates explicit S11/S21 hard/soft band rules. `EvaluationComparator` compares baseline and candidate rule artifacts. `DiagnosisNode` consumes only `EvaluationResult`.

No entry supplies rules, so current Production evaluation is invalid. Rule evaluation also does not populate the legacy `improved`/`score` fields used by Best update. See ISSUE-002 and ISSUE-004.

## Calibration boundary

`evaluation/calibration.py` validates paired frequency grids, ports, impedance, context, complex RMSE, dB RMSE, and ranking agreement. It is exported and unit tested, and `ArtifactStore` has a calibration writer. No Production node calls either: `PRESENT BUT UNUSED / NOT WIRED INTO PRODUCTION`.

## Artifact flow

```text
runs/<task_id>/
├── task.json
├── checkpoint.json
├── run.log
├── baseline/
├── optimization/
├── candidate/
├── best/
└── hfss_workspaces/
    ├── baseline/<unique-run>/
    └── <candidate>/<unique-run>/
```

JSON writes use a sibling temporary file followed by `replace`. Task ID containment is not validated, and same-ID concurrent writes share fixed temporary names; see ISSUE-014.

## Checkpoint and resume

Completed expensive stages can reuse results already in State. Resume loads JSON and invokes the graph again from `START`; it is not a node-level LangGraph continuation. Initialization and deterministic nodes run again and can overwrite metadata or duplicate trace/history. Current resume E2E tests fail before proving the new route. See ISSUE-013.

## Production and non-Production boundary

- Canonical Production Workflow: exactly one, WF-001 via `RUN_REAL_HFSS.py`.
- Internal Production Worker: WF-011 PyAEDT JSON stage Worker, invoked by WF-001 and not counted as an independent Production Workflow.
- Mock: `RUN_OFFLINE.py`, `RUN_SUPPLIED_WITH_MOCK_HFSS.py`, package CLI commands.
- Regression/preflight: `VERIFY_PRESENTATION.py`, pytest suites.
- Active diagnostic experiment: `tools/probe_hfss_builder.py`.
- Reference: vendor optimizer CLI, vendor Builder CLI, electrical-equivalent diagnostic mains.
- Not Production-wired: calibration execution, `UnavailableHFSSBackend`, `metric_deltas`, thermal/reliability rows.
- No explicit Golden workflow or Golden-data contract was identified.
