# Architectural Decisions

These decisions are reconstructed from current source/configuration and available artifacts. Historical author intent is not invented. Where rationale is inferred from enforcement code, it is marked as such.

## ADR-001 — One shared formal topology with injected providers

- **Status:** ACTIVE
- **Decision:** Offline, supplied-Mock, and real workflows use one `ComparisonAgentState` and the Closed-loop V2 LangGraph topology. Composition injects surrogate, optimizer, HFSS, evaluator, artifacts, checkpoint, and routing services.
- **Evidence level:** WIRED.
- **Evidence:** `composition.py`, `closed_loop_graph.py`, `workflow_runner.py`, and three formal `cli.py` run functions.
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

- **Status:** ACTIVE; WIRED IN WF-001
- **Decision:** S-parameter evaluation requires explicit rules; no rules produce `INVALID` rather than using the older scalar `score` path.
- **Evidence level:** UNIT TESTED.
- **Evidence:** `test_no_rules_is_invalid_and_never_score_fallback`.
- **Consequence:** WF-001 supplies Production Contract v1 and no-rule input remains invalid. Mock workflows use a separate versioned Offline contract and cannot redefine Production rules. Best promotion now consumes `EvaluationComparison` under ADR-015.

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
- **Consequence:** real HFSS comparison remains mandatory. Phase 5C adds mandatory passing Calibration Evidence for real readiness; no accepted current-revision physical evidence exists (ISSUE-009).

## ADR-013 — Checkpoints and artifacts are JSON files owned by the harness

- **Status:** SUPERSEDED FOR FORMAL WRITES BY ADR-023/026; ACTIVE FOR LEGACY READ COMPATIBILITY
- **Decision:** Phase 1 used explicit canonical JSON files rather than LangGraph persistence. Phase 2 retains `JsonComparisonCheckpointStore` only to classify preserved V1/V2 files; new formal checkpoints and artifact receipts use RunStore.
- **Evidence level:** UNIT/INTEGRATION TESTED.
- **Evidence:** legacy migration plus SQLite Graph tests.
- **Consequence:** legacy evidence remains inspectable and unmodified, but file checkpoints are not execution authority.

## ADR-014 — Production Evaluation Contract v1 is explicit and WF-001-only

- **Status:** ACTIVE
- **Decision:** WF-001 loads `config/evaluation_contract.production_v1.json`. Core 6–18 GHz has HARD `S21_dB <= -30 dB` and `S11_dB >= -0.5 dB`; Lower 5–6 GHz and Upper 18–19 GHz use the same targets as SOFT rules. Every rule uses all-points/worst-case evaluation. Vendor phase, worse-frequency, and passivity constraints remain optimizer-internal and are not Production PASS/FAIL rules.
- **Evidence level:** INTEGRATION TESTED on the no-AEDT composition/evaluation/diagnosis/intent boundary; current real execution NOT RUN.
- **Evidence:** contract-loader tests, structured rule-evidence tests, checkpoint round-trip, WF-001 composition capture, and safe Production-band node/Graph probes.
- **Consequence:** WF-001 has one versioned source of evaluation truth. Rule-level evidence remains authoritative; Overall PASS/FAIL is only the hard-rule aggregate. New rule directions use neutral diagnosis types rather than conventional matching/insertion-loss interpretations.

## ADR-015 — EvaluationComparison is the Phase 0 Best-promotion authority

- **Status:** ACTIVE; WIRED / INTEGRATION TESTED
- **Decision:** rule comparison, not legacy scalar `EvaluationResult.improved/score`, decides whether a candidate is eligible to become Best. `EvaluationComparison` owns `promotion_eligible` and `promotion_reason`; Best persistence and CLI summary consume those fields. Candidate/result identity must match before promotion.
- **Reason:** the evaluator's rule evidence already represents the accepted baseline/candidate contract, while the legacy scalar fields were fixed placeholders and contradicted `FULLY_ACHIEVED`.
- **Evidence:** deterministic Offline and safe Production-band Graph tests both promote a `FULLY_ACHIEVED` candidate; degraded candidates retain baseline.
- **Consequence:** one comparison artifact now explains Best selection. A future multi-iteration policy may replace this binary Phase 0 policy, but it must preserve explicit decision evidence.

## ADR-016 — Terminal meaning is a typed outcome, not unconditional completion

- **Status:** ACTIVE; WIRED / UNIT TESTED / INTEGRATION TESTED
- **Decision:** graph finalization emits `TerminalOutcome(status, reason_code, reason)`. Success is only `succeeded_baseline` or `succeeded_candidate`; target non-achievement is `rejected`; invalid evidence, provider/workflow failure, and cancellation are distinct. Historical `completed` remains readable but maps to a non-success process exit.
- **Reason:** a common `completed` label erased whether the target was met, evidence was valid, or a provider failed.
- **Evidence:** terminal-policy and process-exit tests plus full Offline success, gate-rejection, degraded-candidate, and Production-band success routes.
- **Consequence:** scripts, CLI summaries, checkpoints, and operators share one terminal truth. Later loop/ledger states must refine rather than bypass it.

## ADR-017 — Canonical real-HFSS execution is fail-closed

- **Status:** SUPERSEDED BY ADR-036; historical Phase-0 control was OFFLINE VERIFIED
- **Decision:** the Phase-0 control disabled checked-in real execution and required an exact readiness marker plus authorization ID before composition. Phase 5A replaces that interim contract with Readiness Manifest V1; the disabled checked-in default remains.
- **Reason:** a boolean enabled flag had become an accidental high-cost execution permission while project memory explicitly prohibited a run.
- **Evidence:** configuration/interlock/real-composition tests pass; repository defaults are rejected. No AEDT was launched.
- **Consequence:** one-click accidental execution was stopped. Phase 2 added Run-bound approval identity, expiry/revocation validation, budget reservation, and action receipts; ADR-036/037 now own the current readiness and physical-launch contracts.

## ADR-018 — Offline rule evidence uses a separate versioned contract

- **Status:** ACTIVE FOR MOCK WORKFLOWS; INTEGRATION TESTED
- **Decision:** WF-002 and WF-003 load `offline-evaluation-v1`, aligned with deterministic 1–3 GHz Mock data. WF-001 alone continues to load `production-evaluation-v1`.
- **Reason:** empty Mock rules prevented end-to-end decision testing, while reusing the 5–19 GHz Production contract on 1–3 GHz test data would be invalid and would blur physical meaning.
- **Evidence:** contract-loader coverage and full deterministic Offline Graph/CLI tests.
- **Consequence:** Offline workflow validity is test evidence only and never a Production physics claim.

## ADR-019 — State V2 stores immutable facts once and relates them by ID

- **Status:** ACTIVE; WIRED / INTEGRATION TESTED
- **Decision:** `RunManifestV2` owns run/task/context/goal identity. Candidate, evaluation, comparison, diagnosis, artifact, decision, and terminal facts are stored once; current/queue/Best relations use IDs. Compatibility helpers may project legacy-shaped views but may not persist duplicate truth.
- **Reason:** V1 histories and current/Best copies could alias, diverge, or be overwritten during replay.
- **Evidence:** exact-field State tests, alias and wrong-context/candidate regressions, and completed V2 Graph replay.
- **Consequence:** any new State fact requires a versioned schema field and invariant. Open metadata uses immutable `FrozenMap`; mutable aliases are rejected before persistence.

## ADR-020 — Checkpoint and manifest JSON is strict and canonical

- **Status:** ACTIVE; UNIT TESTED
- **Decision:** canonical JSON uses sorted keys, compact deterministic encoding, finite numbers, string keys, and strict exact-field decoding. `Path`, cycles, mutable aliases, duplicate keys, unsupported types, NaN/Infinity, and unknown/missing fields are rejected.
- **Reason:** a checkpoint is executable state and must not silently coerce or discard semantics.
- **Evidence:** canonical codec, domain contract, State, and checkpoint rejection/round-trip tests.
- **Consequence:** callers must convert filesystem locations to explicit relative artifact URIs and evolve schemas deliberately rather than adding ad-hoc fields.

## ADR-021 — V1 checkpoints are evidence, never executable resume state

- **Status:** ACTIVE; UNIT TESTED
- **Decision:** checkpoint reads are dual-version during migration, but all writes are V2. Completed V1 is `HISTORICAL_EVIDENCE_ONLY`; interrupted V1 is `INSUFFICIENT_EVIDENCE / WAITING_RECONCILIATION`. Neither can resume real execution. A V1 `checkpoint.json` is preserved and a new V2 write uses `checkpoint.v2.json`.
- **Reason:** V1 cannot prove nested type fidelity, immutable run context, or whether an interrupted external action completed.
- **Evidence:** completed/interrupted V1 classification, load refusal, source digest, no-overwrite, durable waiting classification, and source-removal regressions.
- **Consequence:** operators must start a fresh V2 run or reconcile externally. Phase 2 persists the non-actionable disposition in SQLite; no migration code may upgrade V1 in place and imply execution continuity.

## ADR-022 — Best is a policy projection over explicit comparison evidence

- **Status:** ACTIVE; UNIT/INTEGRATION TESTED
- **Decision:** baseline seeds `BestPolicy` from its Evaluation record. A candidate can replace Best only through an eligible `ComparisonRecord` whose run/context, candidate, and baseline/candidate evaluation IDs all match State evidence.
- **Reason:** assigning a candidate/result or scalar score directly to Best bypasses the accepted evaluation contract.
- **Evidence:** legitimate promotion, ineligible comparison, wrong candidate/context, and illicit Best mutation regressions plus full Offline Graph.
- **Consequence:** future multi-iteration policies may rank more records, but every Best transition must cite immutable comparison evidence.

## ADR-023 — SQLite RunStore is the formal persistence authority

- **Status:** ACTIVE; WIRED / UNIT TESTED / INTEGRATION TESTED
- **Decision:** one SQLite WAL database per artifact root owns immutable Run identity/policy, approvals, operations, attempts, budget reservations, artifact receipts, append-only events, and append-only State-V2 checkpoint revisions. Connections are short-lived, explicitly closed, use foreign keys, busy timeout, and `synchronous=FULL`; provider calls never run inside a database transaction.
- **Reason:** separate JSON checkpoint/artifact writes could not atomically claim an action, reserve budget, or explain a crash between provider completion and Graph commit.
- **Evidence:** concurrency, crash, CAS, Windows handle, Graph replay, and full-suite regressions.
- **Consequence:** formal execution truth comes from RunStore, not file presence. Legacy JSON is input evidence only. A future schema migration must preserve ledger identities and append-only history.

## ADR-024 — Automatic action delivery is at-most-once; UNKNOWN requires reconciliation

- **Status:** ACTIVE; WIRED / INTEGRATION TESTED
- **Decision:** admission atomically creates one RUNNING operation/attempt/reservation before the provider callback. A strictly decoded immutable result is committed SUCCEEDED before Graph State. Known failure becomes FAILED. Lease loss, real structured HFSS failure, or uncertainty after physical execution becomes UNKNOWN; UNKNOWN retains budget, makes the Run `WAITING_RECONCILIATION`, and cannot automatically create another attempt.
- **Reason:** external HFSS/optimizer calls are not generally safe to repeat after ambiguous process/network failure.
- **Evidence:** identical-concurrent request, provider-success/Graph-crash, invalid fresh decoder, expired lease, structured real-HFSS failure, and reopened UNKNOWN tests.
- **Consequence:** availability yields to safety. Retry requires a future explicit reconciliation decision with new evidence; timeout alone is never retry permission.

## ADR-025 — Cost, approval, and semantic idempotency are server-side Run policy

- **Status:** ACTIVE; UNIT/INTEGRATION TESTED
- **Decision:** Run registration freezes allowed operation kinds, integer costs, and required approval scopes. RunStore rejects unknown kinds, caller cost spoofing, and missing/expired/revoked/wrong-scope approvals before attempt/provider start. Real HFSS approval ID must match the RunManifest fingerprint. A semantic operation key deduplicates the same canonical action even when caller idempotency keys differ; reusing one caller key for different content is a conflict.
- **Reason:** caller-supplied cost/scope/key cannot be the authority at a Tool safety boundary.
- **Evidence:** policy-spoof, approval lifecycle, semantic-key, budget-concurrency, and idempotency conflict tests.
- **Consequence:** new Tool kinds require an explicit cost/approval policy. Budgets are conserved integer units; FAILED/UNKNOWN reservations are not automatically refunded.

## ADR-026 — Authoritative artifacts are immutable operation/attempt receipts

- **Status:** ACTIVE; UNIT/INTEGRATION TESTED
- **Decision:** formal JSON artifacts are canonical, path-contained, and bound to full Run/operation/attempt/role identity in SQLite. Publication writes and fsyncs a unique temp file, atomically creates the content-addressed target without replacement, and verifies size/SHA-256 on replay.
- **Reason:** fixed filenames and replace-based writes could collide, escape the root, or leave an authoritative partial file after a crash.
- **Evidence:** traversal, identity, concurrent publish, different-content preservation, tamper, and injected publication-crash regressions.
- **Consequence:** registered receipts are control authority. Phase 5C extends this same invariant to selected provider-native files; original workspaces remain non-authoritative mutable convenience copies. Fixed-path writer methods are compatibility-only and unreachable from the formal Graph.

## ADR-027 — One heartbeated invocation fence owns a Run's Graph writes

- **Status:** ACTIVE; INTEGRATION TESTED
- **Decision:** an ACTIVE Run admits one Graph invocation owner/fence. Followers wait for terminal/release instead of entering the graph. Action admission and checkpoint commits validate the current fence; the owner heartbeats and releases it. ACTIVE→COMPLETED clears the lease atomically, and a completed Run returns its existing terminal checkpoint without ledger mutation.
- **Reason:** action idempotency alone does not prevent two Graphs from racing pure nodes, checkpoints, events, and terminal completion.
- **Evidence:** concurrent full-Graph writer test, checkpoint fencing/CAS, and completed strict no-op with late approval test.
- **Consequence:** same-Run orchestration is serialized while provider callbacks still execute outside SQLite locks. Graph topology still begins at START; ADR-027 does not claim saved-node continuation.

## ADR-028 — Optimizer behavior is authorized by one canonical request

- **Status:** ACTIVE; WIRED / UNIT TESTED / INTEGRATION TESTED
- **Decision:** `OptimizerRequest` binds Run/context, baseline parameters/surrogate evidence, `DesignGoal`, baseline-diagnosis digest, target specification, Agent `OptimizationObjective`, translated `EffectiveObjective`, and provider/config fingerprints. The request and effective objective have canonical digests, and the provider must return both digests unchanged.
- **Reason:** metadata attached after a static vendor run did not make diagnosis or goals causally control optimization.
- **Evidence:** independent Goal/Diagnosis perturbation tests and supplied quick-worker integration.
- **Consequence:** a semantic objective change is a different Tool action. Unsupported Agent semantics must be rejected or explicitly translated; they cannot silently become metadata.

## ADR-029 — Supplied optimization is an independently supervised Tool worker

- **Status:** ACTIVE; OFFLINE VERIFIED
- **Decision:** the supplied adapter writes a canonical request and invokes only `optimization.supplied_worker` through the shared process supervisor. The worker creates a request-specific runtime objective CSV, verifies vendor-summary objective equality, and returns every Pareto candidate with objective/constraint/metric evidence and candidate-set digest.
- **Reason:** vendor execution is expensive, stateful, file-producing work and must not share the Agent/Graph process or reduce its output to one unaudited recommendation.
- **Evidence:** actual vendor quick-mode worker integration and digest/candidate-set regressions.
- **Consequence:** the canonical response remains the action result authority; Phase 5C additionally freezes worker/vendor files as supporting immutable evidence before completion.

## ADR-030 — Surrogate ranking is persisted control evidence

- **Status:** ACTIVE; WIRED / INTEGRATION TESTED
- **Decision:** every optimizer candidate reranked by the surrogate records its canonical surrogate result, EvaluationResult, immutable receipt identity/SHA, ObjectiveRank, and optimizer/effective-objective digests. The complete evidence set and digest are stored in the optimization record and a RunStore artifact.
- **Reason:** an ephemeral sort cannot explain selection or prove that resume used the same ranking inputs.
- **Evidence:** Graph candidate-set/ranking assertions and completed-reinvoke no-mutation regression.
- **Consequence:** future multi-candidate iteration must consume these evidence identities rather than recomputing or overwriting ranking truth.

## ADR-031 — Formal HFSS is one Builder-attested composite action

- **Status:** ACTIVE; WIRED / OFFLINE VERIFIED; REAL AEDT NEEDS VERIFICATION
- **Decision:** Production HFSS uses an `HFSSCompositeRequest` for build→solve→extract. Before license acquisition, the backend verifies the Builder source, copies its attested bytes into an attempt snapshot, re-verifies that snapshot, and the worker imports only the snapshot. Request, attestation, and result digests are cross-checked.
- **Reason:** independent unbound stages and a mutable Builder path allow contract drift and ambiguous partial action identity.
- **Evidence:** drift-before-lock, snapshot, composite-protocol, and digest regressions with fake backends.
- **Consequence:** Builder drift fails before consuming a license. Legacy individual stages remain compatibility/test paths, not the formal Production route.

## ADR-032 — Process uncertainty is bounded and quarantined, never guessed

- **Status:** ACTIVE; OFFLINE VERIFIED ON WINDOWS; REAL AEDT NEEDS VERIFICATION
- **Decision:** Windows Tool workers start suspended, are assigned to a kill-on-close Job Object, then resume under heartbeat/deadline/cancel monitoring. Termination and zero-process verification have finite grace. If cleanup or residual state cannot be verified, the action is `UNKNOWN`; HFSS quarantines its lock and no automatic reclaim/retry is allowed.
- **Reason:** timeout is not proof that external work stopped, and releasing a lock after ambiguous cleanup can overlap AEDT/license use.
- **Evidence:** real Windows parent/child timeout and cancel tests plus injected unverifiable-descendant quarantine test.
- **Consequence:** the composite action upper bound is its configured build+solve+extract deadline plus finite termination grace. Real AEDT behavior remains a separate Canary gate; operator reconciliation is still required for quarantine recovery.

## ADR-033 — Closed-loop control is introduced as a separate offline-only topology

- **Status:** SUPERSEDED by ADR-044 on 2026-08-24; historical Phase 4 safety decision
- **Decision:** retain the 18-node one-pass graph as the only Production topology. Add `closed-loop-agent-v2` behind `AppConfig.closed_loop_enabled=False`, separate scripts/package commands, and a bootstrap guard that rejects real manifests before provider execution.
- **Reason:** closed-loop semantics require independent evidence before they can share the real-HFSS risk boundary.
- **Evidence:** feature-flag/default-off test, real-manifest pre-provider rejection, Production import/composition scan, WF-015 and WF-016 E2E tests.
- **Consequence at the time:** offline Agent development proceeded without silently changing WF-001. ADR-044 later adopted V2 for Production after Phases 5A-5D evidence; Canary authorization remains separate.

## ADR-034 — One Policy owns every Closed-loop route

- **Status:** ACTIVE; WIRED / UNIT TESTED / INTEGRATION TESTED
- **Decision:** `ClosedLoopPolicy` is the sole route authority. It writes a typed `ControllerDecision`; the graph's only conditional router reads that action. Every nonterminal node clears the pending action and returns to Policy. Candidate selection consumes the queue, valid non-PASS evidence advances, queue exhaustion may reoptimize from candidate diagnosis, confirmed offline failure may use a new-identity safe retry, and UNKNOWN can only reconcile.
- **Reason:** distributed conditional edges create conflicting routing truth and make boundedness/audit impossible to prove.
- **Evidence:** queue, reoptimization, retry-safe, reconcile, one-router, and decision-history tests.
- **Consequence:** new controller actions must be added to the exhaustive enum, Policy, graph route map, evidence contract, and tests together. Nodes may validate evidence but may not independently choose a continuation.

## ADR-035 — Every closed loop is budget-bounded and has typed NO_SOLUTION

- **Status:** ACTIVE; OFFLINE END-TO-END VERIFIED
- **Decision:** canonical controller State carries maxima and counters for controller iterations, optimizer calls, candidate screenings, candidate HFSS calls, reoptimizations, safe retries, and stagnation. The final admitted controller turn is forced to finalization. Exhausted search produces `WorkflowStatus.NO_SOLUTION`, distinct from failure, rejection, and success.
- **Reason:** no provider sequence, including adversarial fake outputs, may create an unbounded Agent run or disguise exhausted search as technical failure.
- **Evidence:** per-budget tests, parameterized arbitrary-result iteration-bound tests, strict controller JSON round-trip, and deterministic/supplied-Mock E2E.
- **Consequence:** budgets are part of immutable run/controller evidence. Raising one requires an explicit composition choice; RunStore physical cost budgets remain an additional independent enforcement layer.

## ADR-036 — Real execution authority is a short-lived exact readiness manifest

- **Status:** ACTIVE; WIRED / OFFLINE VERIFIED
- **Decision:** the checked-in repository contains no executable real authority. A future operator must supply an external strict-canonical Readiness Manifest V1 through `HFSS_REAL_READINESS_MANIFEST`. It fixes task/run/workflow, creation/expiry, clean exact Git HEAD, Agent source, Goal and RunManifest digests, HFSS/Evaluation contract bytes, exact Agent/optimizer/surrogate/Builder/PyAEDT/protocol fingerprints, approval ID/scope, and the execution policy. Repository evidence is checked before runtime/provider composition; all causal bindings are checked before `compose_pyaedt_hfss` or task-workspace creation.
- **Reason:** a boolean readiness marker and free authorization string could not prove which code, goal, contracts, providers, or physical budget the user approved.
- **Evidence:** strict-field/canonical/expiry/not-before/dirty/HEAD/source/policy regressions, exact formal binding integration, and drift-before-worker test.
- **Consequence:** a modified or uncommitted tree cannot run a Canary even if a stale manifest path is supplied. The manifest is not generated or activated automatically; Phase 6 still requires separate explicit user authorization after Phase 5 gates.

## ADR-037 — RunStore owns the two-solve/no-retry physical envelope

- **Status:** ACTIVE; UNIT TESTED / INTEGRATION TESTED
- **Decision:** `ExecutionPolicy(max_hfss_solve_launches=2, automatic_solve_retries=0)` is immutable Run identity. Real Run registration rejects any other policy. For each new `real_hfss` action, the same `BEGIN IMMEDIATE` admission transaction counts all previously authorized real solve actions and rejects ordinal 3 or later before inserting an attempt or returning provider ownership. Existing idempotent/semantic operations are resolved first and do not consume another launch. Authorization is counted conservatively even if the process crashes before callback entry.
- **Reason:** graph topology and a general cost budget are not an authoritative physical launch ceiling; later routing changes must not silently create a third solve or an automatic retry.
- **Evidence:** three-way concurrent distinct-request regression admits exactly two callbacks/attempts, rejects one, persists count/policy, and replays an existing receipt without increment. Full RunStore and Graph suites pass.
- **Consequence:** a crash can leave unused conservative capacity, but cannot exceed the approved physical ceiling. Reclaiming or changing a launch allowance requires explicit reconciliation/new authority, not retry logic.

## ADR-038 — Passing paired Calibration Evidence is mandatory real-run identity

- **Status:** ACTIVE; WIRED / OFFLINE VERIFIED; CURRENT PHYSICAL EVIDENCE ABSENT
- **Decision:** the original Phase-5C gate is superseded by `calibration-evidence/1.1`: exact structured paired cases, approved policy/report, comparison context, complete provider fingerprints, mandatory immutable source receipts, recomputed pass status, and canonical digest. Readiness Manifest V1.1 embeds passing evidence; workflow binding and RunStore independently verify its digest, context, provider, model/policy/artifact identity before worker/action admission.
- **Reason:** a surrogate ranking is not physical evidence, and a free-form report or stale calibration cannot authorize expensive real optimization.
- **Evidence:** strict round-trip/identity-drift tests; failing/provider-drifted readiness rejection; formal real-composition binding; RunStore rejection; full offline suite.
- **Consequence:** no current-revision passing paired evidence means no Canary authority can be issued. Calibration data collection is not automatic and requires separately reviewed physical solve authority. Historical ranking reversal remains failing evidence under ISSUE-009.

## ADR-039 — Native provider evidence completes in the same Tool transaction

- **Status:** ACTIVE; WIRED / OFFLINE VERIFIED; REAL AEDT NOT RUN
- **Decision:** after provider return and before `SUCCEEDED`, Harness freezes every declared native file into an operation/attempt/content-addressed immutable object. RunStore identity-checks and inserts the primary result and all supporting receipts in one fenced transaction. Replay verifies size/SHA for all receipts. Missing, changing, unreadable, or unpublishable files after provider completion make the action ambiguous/`UNKNOWN`.
- **Reason:** a canonical JSON result cannot prove the bytes of `.aedt`, Touchstone, journal, worker request/response, or vendor reports used by a decision.
- **Evidence:** fake `.aedt` source-mutation/replay, concurrent Touchstone publish, supplied-worker/Graph integration, and full main suite.
- **Consequence:** original workspaces may remain mutable, but they are never audit authority. A real provider that cannot release/read its outputs cannot be reported as known success. Historical workspaces are not retroactively rewritten.

## ADR-040 — Decisions and terminal evidence have an explicit immutable ledger cutoff

- **Status:** ACTIVE; WIRED / INTEGRATION TESTED
- **Decision:** Closed-loop Policy appends an idempotent `policy_decision` event containing input checkpoint revision/hash, policy version, evidence IDs, reason, action, and next step before committing the resulting State. Every typed terminal path publishes `final-run-manifest/1.0` with terminal outcome, Run/code identity, policy versions, decisions, event trace, artifact receipts, calibration summary, pre-final State digest, and the exact ledger sequence immediately before the manifest publishes itself. Final State references the manifest receipt.
- **Reason:** an audit must answer why a decision occurred and which immutable facts it saw; a manifest cannot truthfully claim to include its own publication event without a declared cutoff.
- **Evidence:** closed-loop terminal manifest assertions, strict manifest reconstruction, completed-Run no-op, and full main suite. The earlier one-pass integration evidence is historical and superseded by V2 integration under ADR-044.
- **Consequence:** the final manifest is a reproducible cutoff snapshot, not a claim that later completion metadata is recursively contained. Phase 5B subsequently supplied operator reconciliation and systematic every-boundary chaos evidence.

## ADR-041 - UNKNOWN reconciliation records evidence; it never retries work

- **Status:** ACTIVE; WIRED / OFFLINE VERIFIED
- **Decision:** an UNKNOWN operation may reach a known conclusion only through a strict `operation-reconciliation/1.0` request backed by a pre-registered, short-lived `reconcile_unknown` approval for the exact Run, operation, attempt, evidence digest, and conclusion. Confirmed success requires a strictly decoded recovered result receipt; confirmed failure forbids one. Reconciliation creates no attempt, invokes no provider, refunds no budget, and rejects conflicting conclusions.
- **Reason:** UNKNOWN means physical outcome is uncertain. Retrying or editing the original attempt would erase evidence and can duplicate an external side effect.
- **Evidence:** success/failure, expiry, revocation, wrong identity, conflict, replay, attempt-count, budget, and provider-call regressions.
- **Consequence:** an operator conclusion repairs ledger truth only. A new physical action requires separately authorized identity and policy; LangGraph saved-node continuation remains outside this decision.

## ADR-042 - Crash injection and corrupt-state handling are explicit fail-closed boundaries

- **Status:** ACTIVE; WIRED / OFFLINE VERIFIED
- **Decision:** default-off one-shot crash points surround action claim/provider/artifact/receipt and checkpoint pre/post commit boundaries. Checkpoint load verifies canonical bytes, stored digest, manifest identity, State V2 schema, and expected workflow identity before provider admission. Nonterminal corrupt state moves the Run to `WAITING_RECONCILIATION` without overwriting evidence; completed corrupt state is raised and left immutable.
- **Reason:** recovery claims are credible only when both sides of each durable boundary and incompatible/corrupt resume inputs have deterministic outcomes.
- **Evidence:** the Phase 5B action/checkpoint chaos matrix, double-resume, completed no-op, byte/digest/manifest/schema corruption, and graph-version incompatibility regressions.
- **Consequence:** fault injection is inert unless explicitly armed for tests. Corruption never becomes a missing checkpoint or permission to restart work.

## ADR-043 - A quarantined lock can be released only by exact accepted evidence

- **Status:** ACTIVE; OFFLINE VERIFIED ON WINDOWS; REAL AEDT NEEDS VERIFICATION
- **Decision:** lock quarantine is never cleared automatically. Release requires an accepted operation reconciliation plus evidence of an empty process tree bound to the exact lock token and original marker SHA. The marker is archived with reconciliation identity/digest rather than deleted; exact replay is idempotent and conflicting evidence fails closed.
- **Reason:** an UNKNOWN worker or AEDT tree may still hold external resources. Deleting an ambiguous marker would permit overlapping execution without an audit trail.
- **Evidence:** injected kill-verification failure, actual ordinary-process parent-death cleanup, exact-marker archive/replay/conflict, and reacquisition regressions.
- **Consequence:** offline process evidence does not generalize to AEDT. Real lock/process behavior remains a separately authorized Canary gate.

## ADR-044 - Closed-loop V2 is the sole formal topology

- **Status:** ACTIVE; WIRED / OFFLINE VERIFIED; REAL HFSS NOT RUN
- **Decision:** `closed-loop-agent-v2` is the only graph composed by Production, deterministic Offline, and supplied-Tools + MockHFSS formal entries. The old 18-node one-pass builder and `compose_comparison_workflow` root are deleted. Shared transactional invocation behavior lives in `workflow_runner.py`. Real manifests remain rejected unless the exact readiness-bound Production root explicitly enables them.
- **Reason:** retaining two executable topologies would leave queue, diagnosis feedback, finalization, and reliability semantics dependent on entry choice and would make Phase 6 evidence ambiguous.
- **Evidence:** formal call-chain scan, sole-router graph test, Production fake-composition binding, Offline/supplied-Mock E2E, V2 completed no-op and concurrent-writer regressions, and the Phase 5D full offline suite.
- **Consequence:** new formal control behavior must be implemented and proven in V2. The Production policy/budget digest is readiness identity; offline defaults cannot authorize real execution. The disabled historical one-pass test is evidence only, not a compatibility promise.

## ADR-045 - Historical file checkpoints are explicit evidence, never implicit resume input

- **Status:** ACTIVE; WIRED / UNIT TESTED / OFFLINE VERIFIED
- **Decision:** formal composition uses only `SQLiteComparisonCheckpointStore` with no legacy path or file probe. `JsonComparisonCheckpointStore` remains an explicit parser for preserved V1/V2 files: completed V1 is historical evidence only, interrupted V1 is insufficient evidence/waiting, and writes never overwrite V1. No normal runner imports a file checkpoint into an executable Run.
- **Reason:** implicit discovery of `checkpoint.json` mixed evidence migration with execution authority and allowed directory contents to influence a new formal invocation.
- **Evidence:** strict V1 completed/interrupted/source-preservation tests; reachability scan proving absence of `legacy_json_path` and `read_legacy`; current SQLite checkpoint/CAS/chaos tests.
- **Consequence:** any future bulk importer must be a separate reviewed tool with explicit source, target Run identity, evidence disposition, and authority. Historical evidence cannot resume physical actions or bypass reconciliation/readiness.

## ADR-046 - Calibration authority is recomputed from immutable physical source receipts

- **Status:** ACTIVE; WIRED / OFFLINE VERIFIED; REAL CALIBRATION NOT YET RUN
- **Decision:** a passing flag or aggregate report is never sufficient for real admission. Calibration Evidence 1.1 must bind at least three cases/two comparable pairs, the approved policy and full causal providers, and exactly candidate/surrogate/HFSS/`.aedt`/`.s2p` receipts per case. Readiness re-hashes and strictly decodes those bytes and reruns the assessment.
- **Reason:** canonical but fabricated or vacuous formal data must not authorize physical work.
- **Evidence:** ISSUE-031 regression matrix rejects policy/provider/cardinality/receipt/semantic/aggregate drift offline.
- **Consequence:** evidence publication is larger and source artifacts must remain available under the immutable artifact root; any missing, tampered, or semantically inconsistent receipt blocks Canary issuance.

## ADR-047 - Existing HFSS Builder is the versioned physical-model authority

- **Status:** ACTIVE; APPROVED FOR COLLECTION; PHYSICAL CORRELATION PENDING
- **Decision:** the user-approved existing Builder defines the physical reference for `interposer_temple4`. The exact contract/context/grid/ports/impedance/materials are captured in `model_alignment.hfss_builder_v1.json`; surrogate PI is aligned to 3.5. Empirical equivalent-model terms are accepted only through passing paired Calibration.
- **Reason:** collection thresholds and model assumptions must be fixed before observing physical results.
- **Evidence:** strict alignment/contract binding tests and source/config fingerprints.
- **Consequence:** this resolves the alignment decision needed to collect evidence but does not itself prove physical correlation; ISSUE-009 remains until Calibration passes.

## ADR-048 - Calibration and Canary use separate short-lived solve envelopes

- **Status:** ACTIVE; OFFLINE VERIFIED; REAL EXECUTION AUTHORIZED BUT NOT YET STARTED
- **Decision:** physical Calibration is a default-disabled Harness workflow with deterministic baseline plus two candidates and exactly `ExecutionPolicy(3,0)`. Production Canary is separately issued only from passing evidence and remains `ExecutionPolicy(2,0)`. Neither workflow changes checked-in enable flags or can invoke the other automatically.
- **Reason:** evidence acquisition and product verification have different purposes and budgets; separating authority prevents Calibration solves from silently expanding Canary scope.
- **Evidence:** offline manifest/budget/default-disable/fake-campaign/readiness binding tests.
- **Consequence:** a clean exact commit is mandatory before issuance. Calibration failure, UNKNOWN, timeout, or residual process terminates the sequence; there is no solve retry.

## ADR-049 - The AEDT Python worker has an import-light Python 3.10 boundary

- **Status:** ACTIVE; OFFLINE VERIFIED ON CONFIGURED AEDT 2025 R1 PYTHON
- **Decision:** root/HFSS package exports are lazy and shared string enums use a local Python-3.10-compatible shim. The isolated `pyaedt_worker` entry must not eagerly import Agent/Harness composition intended for the Python-3.12 Agent runtime.
- **Reason:** `python -m package.submodule` executes package initializers first; the first authorized worker probe exposed a pre-AEDT `StrEnum` import failure.
- **Evidence:** configured PyAEDT/AEDT Python executes the worker CLI help path with exit 0; focused imports/tests pass without launching AEDT.
- **Consequence:** any future worker dependency must remain compatible with the declared embedded interpreter or be kept beyond the worker boundary.

## ADR-050 - UNKNOWN reconciliation authority is preregistered, never retrofitted

- **Status:** ACTIVE; OFFLINE VERIFIED FOR NEW CALIBRATION RUNS
- **Decision:** every Calibration Run registers an expiring `reconcile_unknown` grant at creation together with its physical grant. No approval can be added after the Run becomes `WAITING_RECONCILIATION`; no code auto-applies the grant.
- **Reason:** reconciliation must be possible after an indeterminate action without weakening the rule that authority cannot be invented after observing an outcome.
- **Evidence:** fake campaign proves both approvals; Phase-5B tests prove exact, one-time, evidence-bound failure/success resolution with no new attempt/refund/retry.
- **Consequence:** the pre-fix UNKNOWN Run remains immutable unresolved evidence; replacement physical work requires a new clean revision and new campaign rather than resume.

## ADR-051 - Real AEDT heartbeat loss is bounded at 120 seconds

- **Status:** SUPERSEDED IN PART BY ADR-054; HISTORICAL
- **Decision:** Production/Calibration PyAEDT composition uses a 120-second heartbeat-loss threshold. The solve/action deadline remains 7200 seconds and termination verification remains separately bounded; test workers may use shorter injected thresholds.
- **Reason:** AEDT 2025 R1 cold Desktop initialization can block the embedded Python heartbeat thread for more than the generic 15-second worker threshold even though the process is progressing.
- **Evidence:** the second authorized probe reached PyAEDT Desktop initialization; the seventh proved that a 120-second bound alone still falsely terminates a blocking native solve when its emitter is a same-process Python thread.
- **Consequence:** the finite stale threshold remains active, but PyAEDT heartbeat emission now follows ADR-054.

## ADR-052 - PyAEDT gRPC design recovery is exact-name-only and bounded

- **Status:** ACTIVE; PHYSICAL TARGET BUILD VERIFIED; SOLVE RESULT PENDING
- **Decision:** when PyAEDT 0.18.1 receives `bool`/`None` and the current gRPC proxy cannot see the inserted design, the worker may recreate the PyAEDT application proxy once, reacquire only the exact original project, and retry exact design resolution for at most 30 seconds. Exact project/design equality remains mandatory.
- **Reason:** the fifth probe reported an empty top-design list after repeated activation, proving proxy staleness rather than a naming delay. PyAEDT already uses `recreate_application(True)` for supported multi-desktop/release transitions.
- **Evidence:** immutable reconciliation evidence for the third through fifth probes plus unit tests for exact-project refresh, bool acknowledgement, delayed activation, and wrong-name rejection.
- **Consequence:** the compatibility path never creates/selects `huitu`, a placeholder, or another design; target-only safety remains intact. Timeout/mismatch still fails the action without retry.

## ADR-053 - Legitimate license authority is a physical evidence prerequisite

- **Status:** ACTIVE; OPERATIONAL CHECKOUT FAILURE NOT REPRODUCED; AUTHORITY REVIEW OPEN
- **Decision:** AEDT process/gRPC startup alone does not satisfy readiness. Calibration and Canary require a reachable, legitimately provisioned ANSYS/organization license authority that can check out the required HFSS feature. Unverified third-party license sources are outside the execution boundary.
- **Reason:** four campaign batch logs show the shell can start while `hfss_gui` fails with FlexNet `-15,10`; downstream empty-design/PyAEDT symptoms are not independently attributable.
- **Evidence:** exact sixth-campaign reconciliation `art_8094c55489184ab113e28b033d7a21b1` and matching earlier logs preserve the historical failure; the seventh campaign had no `-15,10`, completed the build, and submitted Solve.
- **Consequence:** an operator must still explicitly accept/confirm entitlement provenance for any physical run, but ISSUE-036 is not used to explain the seventh stop. Failed Runs are never resumed; each replacement campaign binds a fresh clean HEAD and short-lived authority.

## ADR-054 - Native-call PyAEDT heartbeat uses a Job-contained companion process

- **Status:** ACTIVE; OFFLINE VERIFIED; REAL RERUN PENDING
- **Decision:** the PyAEDT worker emits liveness from a separate companion process while ordinary supervised Python workers retain the thread emitter. The companion records the parent worker PID, inherits the same kill-on-close Windows Job, and is stopped with bounded cleanup. Heartbeat staleness does not replace the independent 7200-second hard action timeout.
- **Reason:** synchronous native `analyze_setup` can starve all Python threads in its caller for longer than the finite heartbeat bound; a liveness signal inside that interpreter is not independent.
- **Evidence:** the seventh campaign reached Solve and then lost only the in-process heartbeat; native-call starvation, hard-timeout, parent-death, lock, worker-contract, and Calibration regressions pass offline.
- **Consequence:** active native Solve can continue to its hard deadline while the supervisor still detects worker death, companion death, cancellation, timeout, and unverifiable cleanup. UNKNOWN remains fail-closed and never auto-retries.
