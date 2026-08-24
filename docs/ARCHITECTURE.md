# Current Architecture

This document describes the current working tree after Phase 5D on 2026-08-24. Closed-loop V2 is the sole formal topology; obsolete one-pass architecture appears only where needed to explain preserved historical evidence.

## Component architecture

```text
Entry scripts / package CLI
        │
        ├── real only: strict readiness manifest + repository/causal binding
        │             (before worker/workspace/license construction)
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
        ├── ArtifactStore + RunStore(SQLite WAL/FULL)
        ├── HarnessCore + authoritative action policy
        ├── SQLiteComparisonCheckpointStore
        └── WorkflowRouter + DeterministicSupervisor
        │
        ▼
closed_loop_graph.py: sole Policy/router LangGraph topology
workflow_runner.py: shared transactional invoke/checkpoint/fencing boundary
        │
        ▼
comparison_nodes.py: state transformations; Tool callbacks submitted to Harness
        │
        ▼
HarnessCore / RunStore
        ├── Run invocation fence + heartbeat
        ├── immutable ExecutionPolicy + approval + atomic budget/action claim
        ├── real-HFSS solve-launch ordinal/ceiling (2) + zero retry
        ├── provider callback outside DB transaction
        ├── strict decode + immutable result publish
        └── action/event/checkpoint receipts before Graph continuation
        │
        ├── OptimizerRequest → supervised optimizer JSON worker
        │                    → effective runtime objective + full candidate set
        └── HFSSCompositeRequest → Builder-attested snapshot
                                  → license lock → supervised Job worker/AEDT
```

There is one formal topology: `closed-loop-agent-v2`. Production, deterministic Offline, and supplied-Tools + MockHFSS entries all compose it. `AppConfig.closed_loop_enabled` still defaults false so only explicit entry composition may enable the graph. Real manifests additionally require the Production composition flag after readiness/causal validation; ordinary V2 composition rejects them before Run/provider admission.

The formal Graph does not directly authorize durable files or provider execution. Baseline/candidate surrogate, optimizer, and both HFSS calls are callbacks inside `HarnessCore.execute`; Graph artifacts use `HarnessCore.record_artifact`; State revisions use the SQLite checkpoint facade. Console presenters remain non-authoritative UI output. The supplied optimizer callback itself launches only a supervised JSON worker. Formal real HFSS uses one supervised composite build→solve→extract worker, but construction of that adapter is unreachable until Readiness Manifest V1 matches the repository, Goal, RunManifest, contracts, providers, passing Calibration Evidence, approval, expiry, and execution policy. After an optimizer/HFSS provider returns, declared native files are frozen and transactionally registered as supporting receipts before the operation can become `SUCCEEDED`.

## State

`ComparisonAgentState` is a strict schema-`2.0`, alias-free graph state. `RunManifestV2` is the sole run/task/context/goal identity. Candidate, evaluation, comparison, diagnosis, artifact, decision, and terminal facts are stored once; queue/current/Best relationships are IDs. Closed-loop manifests additionally carry one typed `ClosedLoopControllerState`; non-closed-loop manifests must have `controller=None`. Legacy `baseline_parameters`, `current_candidate`, `best_candidate`, `best_score`, result histories, diagnosis histories, `next_action`, and `run_metadata` are not persisted duplicate facts. Compatibility helpers derive read-only projections from canonical records.

The principal domain contracts are:

```text
RunManifestV2 → DesignGoal + run/context/provider/config identity
CandidateSnapshot → immutable parameters bound to run/context/parent
EvaluationRecord → typed EvaluationResult evidence + artifact IDs
ComparisonRecord → baseline/candidate evaluation IDs + promotion decision
BestPolicy → current candidate/evaluation/comparison evidence IDs
DecisionOutcome / TerminalOutcome → typed control/terminal fact with evidence IDs
ArtifactRef → context/candidate-bound relative URI + optional SHA-256
```

State validation rejects unknown/missing fields, conflicting duplicate IDs, wrong run/context/candidate relationships, dangling evidence/artifact references, and a Best promotion that lacks an eligible matching `ComparisonRecord`. The baseline seed is the only Best state allowed without comparison evidence.

`domain/canonical_json.py` is the strict serialization boundary. It emits sorted compact JSON and rejects non-finite floats, `Path`, aliases/cycles, duplicate object keys, non-string keys, unsupported values, and schema-unknown fields. Nested JSON arrays are reconstructed through typed `from_dict` methods; evaluation bands and frequency plans regain tuple semantics.

## Authoritative Closed-loop Agent graph

```text
START → bootstrap baseline → controller
                            │
                            ├─ prepare optimization ─┐
                            ├─ optimize ─────────────┤
                            ├─ select next candidate ┤
                            ├─ screen candidate ─────┤
                            ├─ run/evaluate HFSS ────┤
                            ├─ consume next ─────────┤
                            ├─ reoptimize ───────────┤
                            └─ retry-safe ───────────┘
                            │
                            ├─ reconcile → END (waiting)
                            └─ typed finalize → END
```

`ClosedLoopPolicy.decide` is the sole decision authority. The LangGraph has exactly one conditional router, attached to `controller`; the router only reads the typed `pending_action` emitted by the Policy. Every nonterminal action clears it and returns to `controller`. Node-local conditions may validate or gather evidence but cannot choose the next graph branch.

The controller stores an append-only decision history and seven independent bounds: total controller iterations, optimizer calls, candidate screenings, candidate HFSS calls, reoptimizations, safe retries, and stagnation. The final admitted controller turn is forced to typed finalization, so no fake provider result sequence can exceed `max_controller_iterations`.

Candidate selection removes one ID from the authoritative queue. Screen rejection or valid non-PASS HFSS evidence consumes the current candidate and returns for another decision. When the queue is empty, Policy may rebuild intent/objective from the last candidate diagnosis and issue a new optimizer iteration. A confirmed offline provider failure may use `RETRY_SAFE`, which creates a new candidate/action identity; UNKNOWN physical outcomes are never retried and route only to reconciliation. Baseline PASS produces `SUCCEEDED_BASELINE`, promoted candidate PASS produces `SUCCEEDED_CANDIDATE`, and exhausted bounded search produces `NO_SOLUTION`.

The feature flag is `AppConfig.closed_loop_enabled`, default `False`. Formal CLI functions set it explicitly. Offline composition rejects real manifests before Run/provider execution. `RUN_REAL_HFSS.py` may set `allow_real_execution=True` only after repository/readiness/Goal/contract/provider/policy binding succeeds. Its Production controller uses `bounded-production-policy-v1`, one candidate-HFSS allowance, zero safe retries, and the independent `ExecutionPolicy(2, 0)` physical ceiling.

## RunStore and Harness control plane

One SQLite database at `<artifact_root>/.runstore/runstore.sqlite3` is authoritative for:

```text
runs
├── immutable manifest identity + task/context
├── immutable per-kind operation cost / required approval policy
├── immutable ExecutionPolicy(max_hfss_solve_launches=2, automatic_solve_retries=0)
├── budget limit + latest checkpoint revision
├── ACTIVE | WAITING_RECONCILIATION | COMPLETED
└── heartbeated invocation owner/fence

operations ── attempts ── budget_reservations
     │             │
     ├── semantic operation key + caller idempotency key
     ├── RUNNING | SUCCEEDED | FAILED | UNKNOWN
     └── canonical result + immutable ArtifactReceipt

approvals      artifacts      append-only events      checkpoint revisions      reconciliations
```

Admission uses a short `BEGIN IMMEDIATE` transaction. It verifies the Run/fence, server-side action kind/cost, required non-revoked/non-expired approval, semantic/idempotency identity, and remaining budget. For a new action requiring `real_hfss`, the same transaction counts all prior authorized real solve actions and rejects ordinal 3 or later under the immutable policy; an existing semantic/idempotent action is returned before this check and does not consume another launch. The transaction then inserts exactly one operation, attempt, reservation, and start-authorization event and commits before the provider callback, so SQLite locks are never held across optimizer/HFSS execution. Counting authorization rather than callback entry is conservative across a crash between DB commit and process creation.

`RUNNING` means durable physical-start authorization exists; there is no persisted PREPARED interval. The callback runs under an operation heartbeat. A fresh result is canonicalized, decoded through the same strict codec used for replay, published immutably, and committed `SUCCEEDED` before Graph State is checkpointed. A Graph crash in the following window reuses that receipt. A lost callback/lease or post-provider commit uncertainty becomes `UNKNOWN`, retains budget, moves the Run to `WAITING_RECONCILIATION`, and cannot create another attempt automatically. Known `FAILED` actions also are not automatically retried. Phase 5B adds a separate one-row-per-operation reconciliation ledger: a short-lived pre-registered `reconcile_unknown` approval binds exact Run/operation/attempt/evidence. Confirmed success requires a recovered strictly decoded result receipt; confirmed failure forbids one. Neither conclusion creates an attempt or refunds budget, and conflicting conclusions are rejected.

One Run invocation lease/fencing token serializes Graph writers. A follower waits for the owner to finish or lose its lease; terminal Runs return the existing checkpoint. Checkpoint writes enforce manifest identity, invocation fence, expected revision, latest-digest-only idempotence, and an atomic ACTIVE→COMPLETED transition with no RUNNING/UNKNOWN operations.

Default-off `CrashPoint` hooks are present after action claim, provider return, artifact freeze, receipt commit, and before/after checkpoint commit. `InjectedProcessCrash` bypasses normal exception repair to model abrupt host loss. Byte/noncanonical/digest/manifest corruption is rejected by RunStore; canonical but schema-invalid State V2 is rejected by the checkpoint adapter. Nonterminal corruption becomes audited `WAITING_RECONCILIATION`; a corrupt terminal checkpoint is not mutated. Runner identity must match its exact workflow ID before Run registration or provider admission.

| Node | Reads | Writes | Service / side effect | Route or termination |
|---|---|---|---|---|
| `initialize_task` | manifest, baseline snapshot | status, artifact refs, trace | initializes task + canonical manifest artifacts | none |
| `calculate_baseline_sparameters` | baseline snapshot | baseline S-parameter fact | surrogate, artifact, checkpoint | raises on failed result |
| `run_baseline_hfss` | baseline, goal | baseline HFSS/EvaluationRecord, seeded BestPolicy | HFSS, evaluator, artifacts | raises on failed baseline HFSS |
| `diagnose_baseline` | baseline evaluation | stage-keyed diagnosis fact | DiagnosisNode | none |
| `freeze_baseline` | both baseline results | trace | checkpoint | raises if baseline missing |
| `build_optimization_intent` | baseline diagnosis | intent | IntentBuilder, artifact, terminal | Production hard failures produce ACTIVE neutral focus |
| `build_optimization_objective` | intent, evaluation | objective | ObjectiveBuilder | ACTIVE or complete |
| `run_optimizer` | manifest goal, baseline diagnosis/surrogate, objective, provider/config fingerprints | canonical OptimizerRequest, full candidate snapshots/ID queue, surrogate-ranking evidence/digest | supervised optimizer worker; receipt-wrapped surrogate reranking; immutable ranking artifact | raises on request/digest/provider failure |
| `select_optimized_candidate` | candidate IDs/queue | current candidate ID, queue | artifact | none |
| `validate_optimized_candidate` | candidate | trace | ParameterValidator | raises on invalid values |
| `recalculate_candidate_sparameters` | candidate | candidate S-parameter fact | surrogate | failure left to gate |
| `candidate_sparameter_gate` | candidate surrogate | DecisionOutcome | router | RUN_HFSS or complete |
| `run_candidate_hfss` | candidate | candidate HFSS fact | HFSS | failed result does not raise |
| `compare_hfss_results` | baseline/candidate | EvaluationRecord + ComparisonRecord | evaluator/comparator/status presenter | comparison completes on rule-configured safe route |
| `diagnose_candidate` | evaluation/comparison | stage-keyed diagnosis fact | DiagnosisNode | none |
| `update_hfss_best` | ComparisonRecord and its evaluation/candidate IDs | optional BestPolicy | artifact/checkpoint | promotes only with eligible matching comparison evidence |
| `decide_after_hfss` | result/evaluation | DecisionOutcome | router | records PASS/STOP; topology still always proceeds to complete |
| `complete` | complete state | typed terminal outcome/status, trace | checkpoint | classifies success/rejected/invalid/failed then END |

## Provider variants

| Boundary | Offline | Supplied Mock | Production real |
|---|---|---|---|
| Surrogate | `DeterministicSurrogate` | `SuppliedSurrogateAdapter` | `SuppliedSurrogateAdapter` |
| Optimizer | in-process `DeterministicBatchOptimizer` | supervised `SuppliedBatchOptimizerAdapter` JSON worker | supervised `SuppliedBatchOptimizerAdapter` JSON worker |
| HFSS | `MockHFSS` | `MockHFSS` | `GuardedHFSSAdapter` |
| Evaluator | `DeterministicEvaluator` + `offline-evaluation-v1` | same Mock contract | `production-evaluation-v1` |
| Graph | shared | shared | shared |

## Phase 3 Tool contracts and process boundary

`OptimizerRequest` is the only formal optimizer input. It binds Run/context, baseline parameters and surrogate result, `DesignGoal`, baseline-diagnosis digest, target specification, Agent `OptimizationObjective`, its translated `EffectiveObjective`, and provider/config fingerprints. Both request and effective objective have canonical digests. The vendor worker materializes a request-specific objective CSV, verifies the vendor summary used exactly those objective rows, and returns the entire Pareto set with per-candidate evidence plus a candidate-set digest. A Goal or diagnosis perturbation therefore changes the request identity and the optimizer runtime input, rather than metadata after execution.

Surrogate reranking is control evidence, not an ephemeral local sort. Each candidate's canonical surrogate result, EvaluationResult, immutable receipt identity/SHA, `ObjectiveRank`, optimizer-request digest, and effective-objective digest are persisted in the optimization record and a RunStore artifact. Receipt replay and completed-Run replay reuse the same evidence digest.

Formal Production HFSS creates an `HFSSCompositeRequest` bound to candidate, execution contract, and `BuilderAttestation`. Before taking the license lock, the backend verifies the original Builder bytes, copies the attested Python source into the attempt workspace, re-verifies the snapshot, and later imports only that snapshot. Drift therefore fails before license acquisition and the snapshot closes the preflight/import time-of-check/time-of-use window. The worker performs build, solve, and extract in one process boundary; legacy individual stages remain compatibility/test paths.

`SupervisedProcessRunner` is the common optimizer/HFSS subprocess controller. On Windows it creates the child suspended, assigns it to a kill-on-close Job Object, then resumes it. Heartbeat loss, deadline, cancel, keyboard interruption, nonzero exit, and residual Job processes all use a finite terminate/verify path. Timeout/cancel upper bounds are the configured action deadline plus finite termination grace; the composite HFSS action deadline is the sum of configured build/solve/extract budgets. If zero descendants cannot be verified, the result is `UNKNOWN`, the Run waits for reconciliation, and HFSS quarantines the license lock instead of releasing/reclaiming it. Parent-death and injected kill-verification failure are now offline-tested. A quarantine is never automatically cleared: `reconcile_quarantined_lock` requires an accepted operation reconciliation whose evidence attests `verified_no_processes=true` and binds the exact marker bytes/token, then atomically archives the marker. These lifecycle claims are `OFFLINE VERIFIED` with ordinary Windows processes; AEDT-specific behavior is `NEEDS VERIFICATION`.

Authoritative request/result/ranking/candidate JSON and selected provider-native files are immutable. Original vendor/HFSS workspaces remain mutable convenience copies, but worker request/response/report files, projects, Touchstone, journals, and approved selected workspace files are copied into content-addressed attempt artifacts before `SUCCEEDED`. Cached replay verifies every primary and supporting receipt.

## Module inventory

| Module/capability | Implementation status | Verification status | Production relation |
|---|---|---|---|
| Domain contracts + State V2 | WIRED / ALIAS-FREE | UNIT/INTEGRATION TESTED | Shared by all Agent workflows |
| Strict canonical JSON codec | WIRED | UNIT TESTED | State/manifest/checkpoint boundary |
| Closed-loop LangGraph topology | WIRED / BOUNDED BACK EDGES / ONE ROUTER | Fake-HFSS and supplied-Mock E2E PASS | Sole formal Production/Mock topology |
| Closed-loop Policy/controller contracts | WIRED / STRICT JSON / PRODUCTION DIGEST BOUND | UNIT/INTEGRATION TESTED | Queue, retry, reconcile, iteration/stagnation/action budgets |
| Workflow nodes | WIRED | Offline integration PASS | Shared Production behavior under Policy |
| Composition root | WIRED / V2 ONLY | Formal construction/readiness tests PASS | Selects Production/Mock providers; old root deleted |
| Interfaces | ACTIVE | UNIT TESTED with doubles | Provider boundary |
| Nine-parameter schema/validator | WIRED | UNIT TESTED | Production input contract |
| Deterministic surrogate | ACTIVE MOCK | Component and Offline E2E PASS | Offline only |
| Supplied surrogate adapter | WIRED | Vendor runtime tested; historical real use | Production |
| Deterministic optimizer | ACTIVE MOCK | Component and Offline E2E PASS | Offline only |
| Supplied optimizer provider integration / adapter wiring | WIRED / SUPERVISED WORKER | Actual vendor quick-worker integration PASS | Production provider boundary |
| Diagnosis/OptimizationObjective behavioral control of supplied optimizer | WIRED TO CANONICAL REQUEST/RUNTIME CSV | Goal/Diagnosis perturbation + vendor summary verification PASS | Production objective causally changes optimizer runtime input |
| Optimization intent | WIRED | UNIT/INTEGRATION TESTED | Production request input |
| Optimization objective | WIRED TO EFFECTIVE VENDOR OBJECTIVE | UNIT/INTEGRATION TESTED | Production request/runtime contract |
| Candidate ranking | WIRED WITH PERSISTED EVIDENCE | INTEGRATION TESTED | Full Pareto set, per-candidate ranking evidence and replay digest |
| Typed `NO_SOLUTION` finalization | WIRED | END-TO-END VERIFIED offline | Exhausted queue/controller/Tool budgets |
| HFSS gate/router/supervisor | WIRED | Windows process/descendant integration PASS; real AEDT NEEDS VERIFICATION | Production control |
| HFSS contract/converter | WIRED | UNIT TESTED | Production boundary |
| Guarded HFSS adapter | WIRED | INTEGRATION TESTED with fake backend | Production |
| JSON worker backend | WIRED / COMPOSITE / ATTESTED | INTEGRATION TESTED with fake backend | Production |
| PyAEDT Worker | WIRED / JOB-SUPERVISED | Contract tested; current real execution NOT RUN | Production internal |
| Nine-parameter Builder | WIRED / SNAPSHOT-ATTESTED | Drift-before-lock integration PASS; historical real use only | Production build stage |
| MockHFSS | ACTIVE MOCK | UNIT TESTED; Offline E2E PASS | Offline/supplied-Mock |
| Rule evaluator | WIRED WITH EXPLICIT CONTRACTS | UNIT/INTEGRATION TESTED | Offline and Production use distinct versioned contracts |
| Evaluation comparator | AUTHORITATIVE FOR PROMOTION | UNIT/INTEGRATION TESTED | Production/Mock shared decision evidence |
| Diagnosis | WIRED | UNIT TESTED | Production node |
| Best update | WIRED TO `ComparisonRecord` EVIDENCE | Unit/integration PASS with no-AEDT providers | Production node |
| Calibration Evidence | WIRED AS REAL ADMISSION GATE | OFFLINE VERIFIED | Schema 1.1 is approved-policy/cardinality/provider/immutable-artifact/recomputation bound; no current physical evidence accepted yet |
| SQLite RunStore | WIRED / AUTHORITATIVE | Concurrency, crash, CAS, identity, budget, approval, terminal no-op PASS | All formal Agent workflows |
| Harness action/event ledger | WIRED | Unit/integration and Graph crash-window PASS | Every formal provider call and authoritative durable write |
| Artifact store | WIRED / IMMUTABLE JSON + NATIVE FILES | Containment, concurrent publish, mutable-source, tamper, and replay verification PASS | All Agent workflows; real AEDT files NOT RUN |
| Structured decision trace + final manifest | WIRED / APPEND-ONLY CUTOFF | Policy decision identity/replay and terminal manifest integration PASS | All typed terminal Agent workflows |
| SQLite checkpoint V2 | WIRED / CANONICAL / APPEND-ONLY | Round-trip, CAS, fencing, historical-digest rejection, Graph integration PASS | All Agent workflows |
| V1/V2 historical import | EXPLICIT READER / EVIDENCE-ONLY | V1 interrupted/completed classification and source-preservation tests PASS | Not reachable from formal invoke |
| Resume | PARTIALLY WIRED / ACTION-SAFE | Receipt replay/no-repeat and completed no-op PASS; still starts graph at START (ISSUE-013) | Programmatic only |
| Readiness Manifest V1 + Run approval | FAIL-CLOSED FOR REAL ENTRY/ACTION | Canonical schema, expiry, dirty/HEAD/source/Goal/Run/contracts/provider drift, pre-composition failure, approval, and two-launch concurrency tests PASS; real run NOT RUN | Short-lived external manifest plus transactional Run approval/ExecutionPolicy |
| Package CLI | ACTIVE | Offline CLI PASS with typed exit code | No real-HFSS subcommand |
| VS Code launches | ACTIVE | Real launch explicitly labelled blocked | User-facing entry set |
| Regression preflight | ACTIVE | PASS | Read-only environment check |
| Thermal model | PRESENT CONFIG ROW / NOT CONNECTED | NOT VERIFIED | Not Production |
| Reliability model | PRESENT CONFIG ROW / NOT CONNECTED | NOT VERIFIED | Not Production |
| `UnavailableHFSSBackend` | PRESENT BUT UNUSED | NOT VERIFIED | Reference/failure placeholder |
| `metric_deltas` helper | PRESENT BUT UNUSED | NOT VERIFIED | No current caller identified |

## HFSS boundary

```text
GuardedHFSSAdapter
→ sanitized unique workspace
→ verify Builder attestation + create/reverify attempt snapshot
→ FileLicenseLock
→ JsonSubprocessHFSSBackend + HFSSCompositeRequest
   → one Job-assigned heartbeated worker
      → snapshot nine_parameter_builder → interposer_temple4 project
      → validate design/Setup1 → analyze_setup
      → complex 2×2 S parameters + Touchstone + JSON
→ contract conversion and validation
→ HFSSResult and journal
```

The formal composite action has a finite total deadline equal to configured build+solve+extract budgets, plus finite termination grace. Baseline and candidate use new workspaces. The shared `validate_sweep_frequency_grid` acceptance rule checks finite strictly increasing values, exact point count, and every linear/log point against the contract with 1 Hz absolute plus `1e-12` relative tolerance. The converter applies it before any backend result is accepted, and the PyAEDT Worker applies it before provider-native exports are published. Because the current `SweepContract` has no explicit intermediate-frequency field, `spacing="explicit"` fails closed instead of accepting an unverifiable grid. The Worker also checks exact parameter names, design identity, Setup presence, port order, representation, impedance, composite-request digest, and Builder-attestation digest.

## Optimization boundary

The graph constructs one canonical `OptimizerRequest` from manifest goal, baseline diagnosis/surrogate evidence, Agent objective, and provider/config fingerprints. `EffectiveObjective` translates supported focus/priority/penalty semantics to vendor metric expressions and bands. The supplied adapter launches a supervised JSON worker; that worker writes a request-specific objective CSV before `vendor/optimizer/app/run.py::execute`, verifies the summary used those rows, and returns the full Pareto set with evidence/digests. ISSUE-005 is resolved for the formal supplied path.

The graph evaluates every returned candidate through receipt-wrapped surrogate calls, persists the complete `ObjectiveRank` evidence set, and selects from those immutable facts. Candidate iteration after one selection is still absent from the graph.

## Evaluation and diagnosis boundary

`DeterministicEvaluator.evaluate_sparameters` evaluates explicit S11/S21 hard/soft band rules. WF-001 loads versioned `production-evaluation-v1`: Core 6–18 GHz HARD `S21_dB <= -30 dB` and `S11_dB >= -0.5 dB`, with identical SOFT targets on 5–6 and 18–19 GHz. All use all-points/worst-case evaluation. Vendor phase/passivity constraints are not Production PASS/FAIL rules. `EvaluationComparator` compares baseline and candidate rule artifacts. `DiagnosisNode` consumes only `EvaluationResult`; the Production directions use neutral S11/S21 rule-not-met issue/focus values.

WF-001 supplies the Production contract and safe no-AEDT evidence completes candidate comparison and downstream graph nodes. `EvaluationComparison` is the authoritative promotion source: it carries `promotion_eligible` and `promotion_reason`; Best and CLI summary consume it rather than legacy `EvaluationResult.improved/score`. A `FULLY_ACHIEVED` candidate is now persisted as Best. ISSUE-004 is resolved.

## Calibration boundary

`evaluation/calibration.py` validates paired frequency grids, ports, impedance, context, complex RMSE, dB RMSE, and ranking agreement. `calibration-evidence/1.1` freezes at least three structured cases/two comparable pairs, the pre-approved versioned policy, complete surrogate/Builder/PyAEDT/protocol identity, report, context, and exactly five immutable receipt roles per case. Domain construction recomputes case metrics, aggregate means, comparable-pair/ranking evidence, and pass status. Readiness then reopens receipt bytes, strictly decodes candidate/surrogate/HFSS results, reconstructs every case, and reruns the assessment; native `.aedt`/`.s2p` hashes are also mandatory. ISSUE-031 is resolved offline.

Physical collection is a separate default-disabled Harness workflow, not a Graph shortcut. `PREPARE_HFSS_CALIBRATION.py` can issue only a clean exact-HEAD, eight-hour authority for deterministic baseline plus two interior candidates and `ExecutionPolicy(3,0)`. `RUN_HFSS_CALIBRATION.py` validates that authority before composing providers; each candidate, surrogate result, HFSS result, `.aedt`, and `.s2p` is frozen through the same action/attempt/budget/idempotency ledger. No automatic solve retry exists. Only passing evidence can be consumed by `PREPARE_REAL_HFSS_CANARY.py`, which reconstructs the exact Production State identity and self-validates an eight-hour `ExecutionPolicy(2,0)` readiness manifest without launching AEDT.

The model basis is also versioned before data collection: the user approved the current HFSS Builder as physical authority. `model_alignment.hfss_builder_v1.json` binds the exact HFSS contract/context, 200-point comparison grid, ports, impedance, and materials. The surrogate PI constant now matches 3.5; empirical equivalent-model terms remain acceptable only if the real paired Calibration threshold passes. This resolves the decision/versioning portion of ISSUE-010 without pre-claiming physical correlation.

## Artifact flow

```text
runs/
├── .runstore/
│   └── runstore.sqlite3                 # authoritative ledgers/checkpoints
└── <task_id>/
    ├── artifacts/
    │   └── <operation>/<attempt>/
    │       ├── <role>.<content-hash>.json
    │       └── native_NNN.<content-hash>.<source-extension>
    ├── optimizer_runs/                  # mutable provider workspace; selected files frozen above
    └── hfss_workspaces/                 # mutable provider workspace; selected files frozen above
        ├── baseline/<unique-run>/
        └── <candidate>/<unique-run>/
```

Authoritative JSON and selected native files are content-addressed. A fully written/fsynced unique temporary file is published create-once; an existing target must have identical bytes. Native copy verifies that source size/mtime did not change while freezing. The primary canonical result and all supporting receipts are identity-checked and inserted in the same fenced completion transaction. Receipt replay verifies size and SHA-256 for every file. Safe path segments and resolved containment reject absolute/traversal/symlink escape. State carries run/context/candidate-bound `ArtifactRef` identities. Formal execution does not create or probe a fixed-path `checkpoint.json`.

Every typed terminal path publishes `final-run-manifest/1.0`. It records the pre-final State digest, typed terminal outcome, immutable Run identity, code revision, policy versions, structured decisions, event ledger, artifact receipts, calibration summary, and the precise ledger cutoff sequence immediately before the manifest publishes itself. This explicit cutoff avoids impossible/self-referential completeness claims; the final State carries the manifest receipt.

## Checkpoint and resume

`SQLiteComparisonCheckpointStore` is the only formal checkpoint reader/writer. It appends canonical State-V2 revisions to RunStore and applies revision/run-fence/manifest CAS. It has no legacy path parameter or file-probe method. `JsonComparisonCheckpointStore` remains an explicit historical parser outside normal composition.

Completed V1 parses only as `HISTORICAL_EVIDENCE_ONLY`; interrupted V1 parses only as `INSUFFICIENT_EVIDENCE / WAITING_RECONCILIATION`. V1 save never overwrites its source and produces a separate V2 file. No file-form V1/V2 State can be resumed by the formal runner; an explicit migration tool would need its own reviewed import authority.

Resume still invokes LangGraph from `START`, not a saved node. Action receipts make this safe for physical calls: `SUCCEEDED` is replayed, `RUNNING` is waited/expired to UNKNOWN, `FAILED` is terminal for that operation, and `UNKNOWN` is non-retriable. Completed Run reinvocation is a strict logical no-op. Explicit reconciliation can attach authoritative success/failure evidence and reactivate a Run without repeating the operation; true saved-node continuation remains ISSUE-013. The old 18-node builder and its implicit legacy-import branch are deleted.

## Phase 0 real-execution safety boundary

`RUN_REAL_HFSS.py` is fail-closed before provider composition. The checked-in repository is disabled and has `real_hfss_readiness_manifest=null`. A future separately authorized invocation must supply `HFSS_REAL_READINESS_MANIFEST`; its file must be strict canonical JSON with exact fields. Repository validation requires an unexpired/not-future manifest, a clean worktree, matching Git HEAD, and matching Agent source digest. The formal composition then calculates—but does not launch—Builder, optimizer, surrogate, PyAEDT executable, HFSS/Evaluation contract, Goal, and RunManifest identities and validates every value before calling `compose_pyaedt_hfss` or creating a task workspace.

Readiness Manifest V1.1 fixes task/run/workflow identity, creation/expiry, Git HEAD, Agent source, RunManifest and Goal digests, HFSS/Evaluation contract byte digests, exact Agent/optimizer/surrogate/Builder/PyAEDT/protocol fingerprints, approved model-alignment/policy/artifact-manifest digests, passing recomputable Calibration Evidence, approval ID/scope, and `ExecutionPolicy(2, 0)`. The real State repeats these causal identities and calibration payload/digest in `RunManifestV2.config_fingerprints`; RunStore rejects a real Run lacking any mandatory revision/provider/readiness/contract/calibration identity. Registration requires the matching expiring `real_hfss` grant. Every new real HFSS action requires that grant, authoritative cost, fail-closed ambiguity policy, remaining budget, and remaining solve-launch allowance. Missing, expired, revoked, wrong-scope, cost-spoofed, calibration/provider/context/artifact-drifted, or third-launch authority fails before attempt/provider start.

Phase 3 places optimizer and HFSS workers behind `SupervisedProcessRunner`. Phase 5B adds bounded kill-verification-failure and Windows parent-death proof, plus explicit evidence-bound quarantine archival. Job assignment still occurs before worker resume; unverified cleanup remains UNKNOWN and quarantined. This is offline verified with ordinary Windows child processes; actual AEDT lifecycle remains a Canary gate under ISSUE-015/026.

The PyAEDT worker runs on AEDT 2025 R1's embedded Python 3.10 while the Agent runtime remains Python 3.12+. Root and `hfss` package exports are therefore lazy, and shared enum contracts use `_compat.StrEnum`; the isolated worker import path must not eagerly traverse Agent/Harness composition. A configured-interpreter `--help` regression proves this boundary without importing or launching AEDT. New physical Calibration Runs also preregister an expiring `reconcile_unknown` grant at Run creation. This does not weaken UNKNOWN or add retry: it only permits the exact evidence-bound Phase-5B operator resolution if an indeterminate action occurs.

Real PyAEDT composition uses a finite 120-second heartbeat-loss threshold because AEDT cold-start calls can block the embedded Python heartbeat thread longer than the generic 15-second worker default. This is independent of the 7200-second solve deadline and 5-second termination-verification grace. Test workers may override the threshold downward to exercise bounded failure; Production has no heartbeat-triggered retry.

PyAEDT 0.18.1 on AEDT 2025 R1 gRPC may acknowledge `SetActiveDesign` with `True`/`None` rather than the design object that its own constructor expects, and insertion visibility can lag the first activation request. The worker applies a narrow target-only compatibility hook: for at most 30 seconds it repeats `SetActiveDesign(exact_name)` and queries `GetDesign(exact_name)`/`GetActiveDesign()`, accepting only exact `GetName()` equality. A terminal error includes the normalized top-design list. Wrong/missing designs fail; no `huitu` or placeholder design is selected or created. This preserves the `interposer_temple4` target-only contract rather than relaxing Builder identity.

## Production and non-Production boundary

- Canonical Production Workflow: exactly one, WF-001 via `RUN_REAL_HFSS.py`.
- Opt-in offline Closed-loop Agent workflows: WF-015 deterministic fake Tools and WF-016 supplied Tools + MockHFSS.
- Internal Tool Workers: WF-011 PyAEDT JSON composite/stage Worker and WF-014 supplied optimizer JSON Worker; neither is counted as an independent Production Workflow.
- Mock: `RUN_OFFLINE.py`, `RUN_SUPPLIED_WITH_MOCK_HFSS.py`, package CLI commands.
- Regression/preflight: `VERIFY_PRESENTATION.py`, pytest suites.
- Active diagnostic experiment: `tools/probe_hfss_builder.py`.
- Reference: vendor optimizer CLI, vendor Builder CLI, electrical-equivalent diagnostic mains.
- Separately authorized physical evidence workflow: WF-017 Calibration collection; never automatically reached from Production or an offline Graph.
- Not Production-wired: `UnavailableHFSSBackend`, `metric_deltas`, thermal/reliability rows.
- No explicit Golden workflow or Golden-data contract was identified.
