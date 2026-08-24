# Validation Matrix

Baseline: `FS-2026-08-20`. Matrix cells use only `PASS`, `FAIL`, `NOT RUN`, `NOT AVAILABLE`, `STALE`, `UNKNOWN`, or `NEEDS VERIFICATION`. Historical evidence is separated from current-working-tree evidence.

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
| Optimization Objective | PASS | PASS | PASS | PASS | Goal/diagnosis/objective form a canonical OptimizerRequest and request-specific vendor runtime objective |
| Supplied surrogate provider | PASS | PASS | PASS | PASS | Graph reranking persists canonical surrogate/evaluation/receipt/rank evidence for every candidate |
| Supplied optimizer provider integration / adapter wiring | PASS | PASS | PASS | PASS | Actual vendor quick optimizer executes through the independent supervised JSON worker |
| Diagnosis/OptimizationObjective control of supplied optimizer behavior | PASS | PASS | PASS | PASS | Goal and diagnosis perturbations change OptimizerRequest; worker/vendor summary echo the effective-objective digest |
| Candidate ranking | PASS | PASS | PASS | PASS | Full Pareto set is returned with evidence; ranking evidence/digest is persisted and unchanged on completed replay |
| Closed-loop sole Policy/router | PASS | PASS | PASS | PASS | WF-015/016 have one conditional router; every nonterminal action returns to typed Policy decision |
| Candidate queue consumption | PASS | PASS | PASS | PASS | Screen-failed and valid non-PASS candidates are consumed; the next queued candidate is selected |
| Candidate-diagnosis reoptimization | PASS | PASS | PASS | PASS | Queue exhaustion rebuilds intent/objective from candidate diagnosis and changes optimizer iteration/action identity |
| Retry-safe/reconcile routes | PASS | PASS | PASS | PASS | Confirmed fake failure gets new candidate/action identity within budget; UNKNOWN selects reconcile only |
| Controller/Tool/stagnation budgets | PASS | PASS | PASS | PASS | Controller, optimizer, screen, fake-HFSS, reoptimization, retry, and stagnation bounds are enforced |
| Typed NO_SOLUTION finalization | PASS | PASS | PASS | PASS | Exhausted bounded search is distinct from rejected/failed/success and has exit code 6 |
| Closed-loop Production admission | PASS | PASS | PASS | PASS | Flag defaults off; Offline rejects real manifests; only exact readiness-bound Production composition may enable real V2 before provider construction |
| Candidate parameter validation | PASS | PASS | PASS | PASS | Safe Production-band Graph probe reaches candidate validation |
| Candidate surrogate gate | PASS | PASS | PASS | PASS | Safe Production-band Graph probe reaches and passes the candidate gate |
| Candidate HFSS orchestration | PASS | PASS | PASS | PASS | Safe Production-band Graph probe reaches candidate HFSS without AEDT |
| Baseline/candidate comparison | PASS | PASS | PASS | PASS | Existing presenter contract is imported; dedicated regression and safe Graph complete `FULLY_ACHIEVED` comparison |
| Candidate diagnosis | PASS | PASS | PASS | PASS | Safe rule-configured Graph reaches candidate diagnosis after comparison |
| Best update | PASS | PASS | PASS | PASS | `BestPolicy` seeds from baseline Evaluation evidence and promotes only through a matching eligible `ComparisonRecord` |
| Authoritative terminal outcome/exit code | PASS | PASS | PASS | PASS | Baseline/candidate success, NO_SOLUTION, rejected, invalid, failed, cancelled, waiting, and historical completed mappings are explicitly tested |
| Real-entry fail-closed interlock | PASS | PASS | PASS | PASS | Checked-in config has no manifest; boolean-only, missing/noncanonical/expired/drifted readiness fails before worker composition/workspace creation |
| Readiness causal identity | PASS | PASS | PASS | PASS | Git/source/Goal/Run/contracts/approval/policy/cardinality/provider/source-receipt bindings and semantic recomputation pass offline; no passing physical Calibration exists under ISSUE-009/037 |
| Real HFSS solve-launch ceiling | PASS | PASS | PASS | PASS | Concurrent distinct approved actions admit at most two; ordinal 3 is rejected transactionally, cached replay consumes no new launch, automatic retries are fixed at zero |
| SQLite RunStore schema/lifecycle | PASS | PASS | PASS | PASS | Run/operation/attempt/reservation/artifact/event/checkpoint identities and lifecycle transitions pass file-backed SQLite tests |
| Action receipt crash recovery | PASS | PASS | PASS | PASS | Provider success is durable before Graph checkpoint; injected checkpoint crash resumes without repeating baseline HFSS callback |
| Action idempotency/concurrency | PASS | PASS | PASS | PASS | Same concurrent request and same semantic request with different caller keys create one operation/attempt/physical callback |
| Atomic budget reservation | PASS | PASS | PASS | PASS | Simultaneous distinct cost-6 requests under budget 10 admit one; crash/UNKNOWN retains reservation and never exceeds limit |
| Approval authority | PASS | PASS | PASS | PASS | Missing scope/grant, expired/revoked grant, real-manifest mismatch, unknown kind, and caller cost spoof are rejected before attempt/provider |
| UNKNOWN/no-auto-retry policy | PASS | PASS | PASS | PASS | Callback ambiguity, stale lease, invalid fresh decode, and structured real HFSS failure persist UNKNOWN/waiting and never auto-retry |
| Operator reconciliation | PASS | PASS | PASS | PASS | Short-lived pre-registered exact authority resolves one UNKNOWN as evidence-backed success/failure; no attempt/retry/refund; conflicts, expiry, revocation, wrong identity, and replay are tested |
| Action/checkpoint chaos matrix | PASS | PASS | PASS | PASS | Claim/provider/freeze/receipt and checkpoint pre/post commit crashes, including terminal completion and two resumes, have deterministic conservative outcomes |
| Checkpoint/Graph compatibility | PASS | PASS | PASS | PASS | Noncanonical bytes, digest/manifest drift, schema-invalid State V2, and wrong workflow identity fail before provider continuation |
| Run invocation fencing | PASS | PASS | PASS | PASS | Concurrent full V2 invocations have one physical workflow; action admission/checkpoint uses fence and follower returns the same terminal State |
| Event ledger / structured decision trace | PASS | PASS | PASS | PASS | Lifecycle events are sequenced and append-only; idempotent Policy events bind input revision/hash, evidence, policy, reason, action, and next step |
| HFSS contract/port/complex conversion | PASS | PASS | PASS | PASS | Fake worker/backend integration passes and baseline HFSS route contains the boundary |
| Target-only Builder | PASS | PASS | PASS | PASS | Stubbed integration passes; the seventh campaign physically created exact `interposer_temple4` and completed the Builder path through Solve submission |
| Standalone Builder test harness | PASS | FAIL | NOT RUN | NOT AVAILABLE | Collection fails in Agent Python because `ansys` is absent |
| Builder attestation/drift boundary | PASS | PASS | PASS | PASS | Builder drift and wrong snapshot digest fail before license-lock acquisition; worker imports only the attested snapshot |
| HFSS composite request | PASS | PASS | PASS | PASS | Fake request/response is digest-bound; real AEDT verified build and Solve submission, but no accepted Solve/extraction response exists |
| Windows worker process isolation/timeout/cancel/parent death | PASS | PASS | PASS | PASS | Real Windows tests plus seventh-campaign Job termination prove bounded cleanup; native-call companion is OFFLINE VERIFIED and awaits physical rerun |
| Residual-process UNKNOWN/lock quarantine | PASS | PASS | PASS | PASS | Injected kill-verification/unverified descendant becomes UNKNOWN; quarantine release requires accepted empty-process evidence bound to exact marker bytes/token and archives audit evidence |
| Artifact store | PASS | PASS | PASS | PASS | Canonical JSON and provider-native file publish/replay pass containment, concurrency, mutable-source, tamper, and receipt verification; supporting artifacts commit with the Tool result |
| Final Run Manifest | PASS | PASS | PASS | PASS | Typed terminal paths emit a strict immutable manifest with ledger cutoff, decisions/events/artifacts, policy versions, terminal outcome, Run identity, and calibration summary |
| Domain/State V2 contract | PASS | PASS | PASS | PASS | Exact fields, run/context/candidate bindings, evidence references, alias rejection, and illicit Best update regressions pass |
| Canonical JSON/checkpoint V2 | PASS | PASS | PASS | PASS | Semantic round-trip and Path/NaN/alias/unknown/duplicate-key rejection pass; nested evaluation tuple semantics are restored |
| V1/V2 historical checkpoint boundary | PASS | PASS | PASS | PASS | Explicit reader classifies completed/interrupted V1 evidence and preserves source; formal SQLite composition has no legacy path/probe and cannot resume file checkpoints |
| SQLite checkpoint CAS | PASS | PASS | PASS | PASS | Revision/fence/manifest CAS, historical-digest replay rejection, terminal no-op, and Windows connection-close regressions pass |
| Resume/reuse | PASS | PASS | PASS | PASS | Receipt replay, evidence-bound UNKNOWN resolution, double resume, waiting recovery, and completed strict no-op pass; saved-node continuation remains absent under ISSUE-013 |
| Calibration Evidence / real gate | PASS | PASS | PASS | PASS | Calibration Evidence 1.1 authority/recomputation passes offline; current paired physical evidence is absent because the seventh campaign stopped during baseline Solve under ISSUE-037 |
| HFSS returned frequency-grid contract | PASS | PASS | PASS | PASS | Count, finite/monotonic values, endpoints, every linear/log point, unit drift, and fail-closed behavior pass offline; real extraction was not reached |
| Environment preflight | PASS | PASS | PASS | PASS | Agent/PyAEDT/AEDT/headless/lock preflight passed and the campaign reached Solve submission; entitlement provenance remains an external review item |
| Package editable import provenance | PASS | PASS | PASS | PASS | Project `.venv`, ordinary import, and module CLI resolve to the current repository `src` |

## Current full-workflow results

| Workflow | Full Offline result | Current Real HFSS result | Current E2E result | Readiness / evidence |
|---|---|---|---|---|
| WF-001 canonical Production | NOT AVAILABLE | NOT RUN | NOT RUN | FAIL readiness: ISSUE-009 has no passing physical Calibration; ISSUE-037 repair is offline verified but has not completed a fresh manual campaign |
| WF-002 deterministic Offline | PASS | NOT AVAILABLE | PASS | Test-backed full route uses explicit Offline Contract v1, promotes candidate, and emits typed success |
| WF-003 supplied optimizer + MockHFSS | PASS | NOT AVAILABLE | PASS | Formal entry delegates to supplied-Tools Closed-loop V2; actual supervised optimizer worker + MockHFSS reaches typed END |
| WF-004 environment preflight | NOT AVAILABLE | NOT RUN | NOT AVAILABLE | PASS for its own read-only preflight scope only |
| WF-015 deterministic Closed-loop Agent | PASS | NOT AVAILABLE | PASS | END-TO-END VERIFIED with fake surrogate/optimizer/HFSS; bounded typed success/NO_SOLUTION routes |
| WF-016 supplied + MockHFSS Closed-loop Agent | PASS | NOT AVAILABLE | PASS | END-TO-END VERIFIED with actual supervised supplied optimizer worker and MockHFSS |

Interpretation:

- Upstream capability-local `PASS` does not imply Production readiness or real-HFSS verification.
- WF-002 `PASS` is deterministic Mock evidence only; it is not a physical-performance claim.
- WF-001 has readiness `FAIL`, but its actual current real-HFSS and E2E results are `NOT RUN`; readiness is not substituted for an execution result.

## Executed validation commands
### Committed revision Calibration and Canary review

- **Date:** 2026-08-24.
- **Reviewed implementation revision:** `cd29846aef5cdf99b36aa74fda717231bcd3450e`; repository was clean when causal source/provider/contract identities were collected.
- **Data inventory:** no current `calibration-evidence/1.0` artifact exists. The historical paired run has no attributable Agent/Builder revision, its optimizer identity differs, and its reconstructed ranking agreement is 0.0.
- **Authority review:** `FAIL` — current contracts permit vacuous one-case ranking, arbitrary policy, partial provider bindings, and empty source-artifact receipts (ISSUE-031).
- **Blocker result:** ISSUE-009/010/031 `BLOCK`; ISSUE-013 and ISSUE-015/026 are recommended only for explicit conditional Canary acceptance; ISSUE-018 should close before Canary.
- **Output:** exact identity inventory and evidence-collection requirements are recorded in `docs/CALIBRATION_AND_CANARY_REVIEW.md`.
- **HFSS/AEDT/ADS:** `NOT RUN`.

### ISSUE-019 HFSS returned-grid contract

- **Date:** 2026-08-24.
- **Focused command:** `.venv\Scripts\python.exe -m pytest -q tests/test_hfss_guarded_adapter.py tests/test_pyaedt_worker_contract.py tests/test_hfss_worker_backend.py` — `PASS`, 33 passed in 0.67 s.
- **Related safety/Closed-loop/chaos selection:** Production safety, process safety, Phase 4, and all Phase 5B suites passed.
- **Final full main suite:** `.venv\Scripts\python.exe -m pytest -q` — `PASS`, 213 passed in 45.71 s, explicit exit code 0.
- **Proven:** the shared rule rejects count, start, stop, intermediate, unit, and unverifiable explicit-grid drift; the Guarded Adapter returns structured failure before acceptance; exact Production linear grids pass.
- **Evidence boundary:** fake/contract data only. No HFSS/AEDT/ADS process, solve, extraction, license action, or Canary ran.


### Phase 5D Closed-loop V2 Production convergence and cleanup

- **Date:** 2026-08-24.
- **Starting Git evidence:** branch `master`, HEAD `08f001e84f463936b2bacc7ff90d77d18b7887a6`; all Phase 0-5C work was unstaged/uncommitted and preserved; no staged files or commit were created.
- **Pre-change characterization:** `tests/test_phase4_closed_loop.py tests/test_real_hfss_safety.py tests/test_production_evaluation_contract.py tests/test_run_store.py tests/test_cli.py` — `PASS`, 62 passed in 40.42 s.
- **Production binding focus:** readiness/PyAEDT-contract/formal-V2/policy tests — `PASS`, 29 passed. CLI + supplied-Mock V2 focus — `PASS`, 2 passed in 23.07 s.
- **Migration focus:** migrated Phase 5B chaos, Production evaluation contract, and Closed-loop V2 tests — all passed after correcting the future-workflow fixture to exclude a V2-only controller.
- **V2 reliability replacement:** completed V2 reinvocation returns identical State with zero provider calls; two concurrent V2 compositions/invocations return the same terminal State and execute one physical workflow. The test exposed a concurrent SQLite WAL-initialization lock; bounded retry was added and the focused set passed, 3 passed in 1.65 s.
- **Reachability cleanup:** source/formal-entry scan contains no `compose_comparison_workflow`, `build_comparison_graph`, `legacy_json_path`, or `read_legacy`. The only old-root text is the preserved `.disabled` historical characterization.
- **Full main suite before the two added V2 reliability tests:** `.venv\Scripts\python.exe -m pytest -q` — `PASS`, 203 passed in 50.69 s, explicit exit code 0.
- **Final full main suite:** same command after V2 reliability and documentation synchronization — `PASS`, 205 passed in 53.33 s, explicit exit code 0.
- **Final hygiene:** changed source/tests/all formal entries compile; `runtime_config.json` parses; all eight project-memory Markdown files decode as strict UTF-8; `git diff --check` exits 0 with expected LF/CRLF notices only; old-symbol reachability scan returns no current matches; staged diff is empty.
- **Evidence boundary:** all tests use deterministic/supplied Mock/fake backends or ordinary Windows processes. No HFSS/AEDT/ADS process, project, solve, license action, or Canary ran. Current calibration/AEDT blockers and dirty-tree exact-HEAD failure make Phase 6 `NO-GO`.

### Phase 5B reconciliation and chaos

- **Date:** 2026-08-24.
- **Starting Git evidence:** branch `master`, HEAD `08f001e84f463936b2bacc7ff90d77d18b7887a6`; authorized Phase 0–5A/5C changes were unstaged/uncommitted and preserved. No staged files and no commit were created.
- **Pre-change characterization:** `tests/test_run_store.py tests/test_checkpoint_v2.py tests/test_phase3_process_safety.py tests/test_phase4_closed_loop.py` — `PASS` before implementation.
- **New Phase 5B suite:** `tests/test_phase5b_reconciliation.py tests/test_phase5b_chaos.py tests/test_phase5b_checkpoint_chaos.py tests/test_phase5b_process_lock_chaos.py` — `PASS`, 20 passed in 1.56 s.
- **Related regression groups:** reconciliation + RunStore — `PASS`, 24 passed in 1.09 s; semantic/terminal checkpoint + Graph — `PASS`, 30 passed in 5.67 s; process/lock + Phase 3 safety + all initial chaos — `PASS`, 21 passed in 1.71 s.
- **Full main suite:** `.venv\Scripts\python.exe -m pytest -q` — `PASS`, 215 passed in 38.95 s, explicit exit code 0.
- **Final post-documentation rerun:** same full command - `PASS`, 215 passed in 55.63 s, explicit exit code 0.
- **Supplied optimizer vendor suite:** first run produced 6 PASS + one pytest system-temp setup `PermissionError` before the affected test. Rerun with exact project-local `--basetemp` — `PASS`, 7 passed in 5.40 s, explicit exit code 0; the temporary directory was verified under the workspace and removed.
- **Compilation/diff hygiene:** Phase 5B source/test `compileall` passed. Black/Ruff are not installed and therefore were `NOT AVAILABLE`, not silently claimed. Final `git diff --check` is recorded after documentation synchronization.
- **Final handoff hygiene:** source/test/all-entry `compileall` - `PASS`; runtime JSON parsed with `real_hfss_enabled=false` and no readiness manifest; `git diff --check` - `PASS` with expected Windows line-ending notices only; staged diff empty.
- **Proven:** strict reconciliation round-trip and authority; success/failure/conflict/expiry/revocation/wrong identity/idempotency; no new attempt/budget refund/provider retry; all six action/checkpoint crash points including terminal completion; two resume; byte/digest/manifest/State-schema corruption; Graph identity pre-admission rejection; bounded kill-verification UNKNOWN; real Windows parent-death cleanup; exact evidence-bound quarantine archive/replay.
- **Evidence boundary:** all actions are Mock/ordinary child processes. Real AEDT, real license behavior, and real HFSS remain `NOT RUN`; saved-node continuation remains absent. Phase 5D subsequently removed old Graph/manual-resume paths.
- **HFSS/AEDT/ADS:** `NOT RUN`.
### Phase 5C calibration, native artifacts, trace and final manifest

- **Date:** 2026-08-22.
- **Starting Git evidence:** branch `master`, HEAD `08f001e84f463936b2bacc7ff90d77d18b7887a6`; authorized Phase 0–5A changes were unstaged/uncommitted and preserved. No staged files and no commit were created.
- **Calibration/readiness target:** `.venv\Scripts\python.exe -m pytest -q tests/test_real_hfss_safety.py tests/test_pyaedt_worker_contract.py tests/test_production_evaluation_contract.py tests/test_calibration.py` — `PASS`, 42 passed in 1.10 s.
- **RunStore/native target:** `.venv\Scripts\python.exe -m pytest -q tests/test_run_store.py` — `PASS`, 19 passed in 0.89 s.
- **Graph/final-manifest targets:** `tests/test_phase4_closed_loop.py` — `PASS`, 19 passed in 25.83 s; focused final-manifest scenarios — `PASS`, 2 passed in 1.03 s; retained/closed-loop combined route passed in subsequent full-suite coverage.
- **Full main suite:** `.venv\Scripts\python.exe -m pytest -q` — final rerun `PASS`, 195 passed in 40.89 s. The immediately preceding run reported 194 PASS and one `child.pid`-not-yet-created fixture failure in the early-cancel Windows test; its isolated rerun passed in 0.20 s before the clean full rerun.
- **Supplied optimizer vendor suite:** `.venv\Scripts\python.exe -m pytest -q vendor\optimizer\tests` — `PASS`, 7 passed in 4.67 s.
- **Compilation/config/diff hygiene:** `compileall -q src tests` plus formal entry scripts, runtime JSON parse, and `git diff --check` — `PASS`; only expected Windows LF→CRLF notices were emitted.
- **Proven:** strict calibration evidence round-trip/drift rejection; failing/context/provider/digest-drifted evidence cannot authorize a real Run; provider-native files are content-addressed, atomically registered with action completion, verified on cached replay, and preserve old bytes after source mutation; concurrent identical Touchstone publication is safe; Policy decisions expose state revision/hash, evidence, policy, reason, and next step; terminal State references a strict final manifest with a declared pre-self ledger cutoff.
- **Evidence boundary:** provider-native freezing is `OFFLINE VERIFIED` with fake `.aedt`/Touchstone and actual supplied optimizer worker files. Real `.aedt` readability, a passing current paired calibration dataset, real AEDT lifecycle, and Canary results are `NOT RUN`.
- **Phase boundary at 5C completion:** Phase 5B was still pending at that checkpoint; Phases 5B and 5D were subsequently completed offline on 2026-08-24. Phase 6 was not authorized.
- **HFSS/AEDT/ADS:** `NOT RUN`.

### Phase 5A readiness and physical execution envelope

- **Date:** 2026-08-21.
- **Starting Git evidence:** branch `master`, HEAD `08f001e84f463936b2bacc7ff90d77d18b7887a6`; authorized Phase 0–4 changes were unstaged/uncommitted and preserved. No staged files and no commit were created.
- **Pre-change safety/RunStore/real-composition characterization:** `.venv\Scripts\python.exe -m pytest -q tests/test_real_hfss_safety.py tests/test_run_store.py tests/test_pyaedt_worker_contract.py` — `PASS`, 31 passed in 1.05 s.
- **Final Phase 5A target:** `.venv\Scripts\python.exe -m pytest -q tests/test_real_hfss_safety.py tests/test_run_store.py tests/test_pyaedt_worker_contract.py tests/test_production_evaluation_contract.py` — `PASS`, 52 passed in 1.91 s.
- **Full main suite:** `.venv\Scripts\python.exe -m pytest -q` — `PASS`, 190 passed in 38.03 s.
- **Supplied optimizer vendor suite:** `.venv\Scripts\python.exe -m pytest -q vendor\optimizer\tests` — `PASS`, 7 passed in 4.58 s.
- **Compilation/config/diff hygiene:** `compileall -q src tests RUN_REAL_HFSS.py`, runtime JSON parse, and `git diff --check` — `PASS`; only expected Windows LF→CRLF notices were emitted.
- **Proven:** strict canonical readiness schema; disabled/boolean-only fail closed; expiry/not-before; clean exact HEAD and Agent-source binding; complete provider/source/contract/Goal/RunManifest identity; drift fails before real adapter construction/workspace creation; formal real Run registration rejects missing evidence; server-side immutable `ExecutionPolicy(2,0)`; concurrent third real launch rejected with exactly two attempts/provider callbacks; idempotent replay does not consume another launch.
- **Not proven:** real AEDT process/license behavior, a real Canary, operator reconciliation, every-boundary chaos injection, calibration gating, or native provider-artifact freezing.
- **HFSS/AEDT/ADS:** `NOT RUN`.

### Phase 4 Offline Closed-loop Agent

- **Date:** 2026-08-21.
- **Starting Git evidence:** branch `master`, HEAD `08f001e84f463936b2bacc7ff90d77d18b7887a6`; authorized Phase 0–3 changes were unstaged/uncommitted and preserved. No staged files and no commit were created.
- **Target command:** `.venv\Scripts\python.exe -m pytest -q tests/test_phase4_closed_loop.py`.
- **Target result:** `PASS` — 19 passed in 22.97 s.
- **Compatibility target:** `.venv\Scripts\python.exe -m pytest -q tests/test_phase4_closed_loop.py tests/test_state_v2.py tests/test_comparison_graph.py` — `PASS`, 36 passed in 28.62 s.
- **Full main suite:** `.venv\Scripts\python.exe -m pytest -q` — `PASS`, 181 passed in 35.55 s.
- **Supplied optimizer vendor suite:** `.venv\Scripts\python.exe -m pytest -q vendor\optimizer\tests` — `PASS`, 7 passed in 4.47 s.
- **Compilation/diff hygiene:** `compileall -q src tests RUN_CLOSED_LOOP_OFFLINE.py RUN_CLOSED_LOOP_SUPPLIED_MOCK.py` — `PASS`; `git diff --check` — `PASS` with expected Windows LF→CRLF notices only.
- **Proven:** baseline PASS→`SUCCEEDED_BASELINE`; Candidate 1 screen fail→Candidate 2; improved non-PASS→next candidate and reoptimization; candidate PASS→Comparison-authorized Best promotion + `SUCCEEDED_CANDIDATE`; optimizer/screen/HFSS/stagnation/controller budget exhaustion→typed `NO_SOLUTION`; new-identity safe retry; UNKNOWN→reconcile only; arbitrary scripted result sequences stay within `max_controller_iterations`; deterministic fake and actual supplied-worker+MockHFSS paths reach typed END.
- **Topology/safety evidence:** closed-loop composition requires an explicit flag and rejects real manifests before provider execution. `RUN_REAL_HFSS.py` still imports/composes only the retained comparison graph. No Production route was overwritten.
- **Not proven:** real HFSS/AEDT closed-loop behavior, operator resolution of UNKNOWN, calibration-based iteration policy, native provider-artifact freezing, or Production promotion readiness.
- **HFSS/AEDT/ADS:** `NOT RUN`.

### Phase 3 Tool and Objective convergence

- **Date:** 2026-08-21.
- **Starting Git evidence:** branch `master`, HEAD `08f001e84f463936b2bacc7ff90d77d18b7887a6`; authorized Phase 0/1/2 changes were unstaged/uncommitted and preserved. No staged files and no commit were created.
- **Target command:** `.venv\Scripts\python.exe -m pytest -q tests/test_phase3_tool_objective.py tests/test_phase3_process_safety.py tests/test_comparison_graph.py tests/test_hfss_worker_backend.py tests/test_hfss_guarded_adapter.py tests/test_pyaedt_worker_contract.py`.
- **Target result:** `PASS` — 46 passed in 14.80 s.
- **Full main suite:** `.venv\Scripts\python.exe -m pytest -q` — `PASS`, 162 passed in 15.97 s.
- **Supplied optimizer vendor suite:** `.venv\Scripts\python.exe -m pytest -q vendor\optimizer\tests` — `PASS`, 7 passed in 5.50 s.
- **Compilation/diff hygiene:** `compileall -q src tests` — `PASS`; `git diff --check` — `PASS` with expected Windows LF→CRLF notices only.
- **Proven:** Goal and diagnosis perturbations change canonical OptimizerRequest identity; effective vendor objective is applied and digest-echoed; actual supplied optimizer runs out of process and returns the full auditable Pareto set; surrogate ranking evidence persists/reuses; Builder drift fails before lock; formal HFSS uses an attested composite request; Windows timeout/cancel has a finite upper bound and zero test descendants; unverified residual state becomes UNKNOWN and quarantines the lock.
- **Evidence boundary:** process tests use real Windows subprocesses/Job Objects but not AEDT. Provider-native optimizer/HFSS files remain mutable work evidence. Formal WF-003 full CLI and current real WF-001 remain NOT RUN. The graph remains a one-pass DAG.
- **HFSS/AEDT/ADS:** `NOT RUN`.

### Phase 2 RunStore and Harness Core

- **Date:** 2026-08-21.
- **Starting Git evidence:** branch `master`, HEAD `08f001e84f463936b2bacc7ff90d77d18b7887a6`; authorized Phase 0/1 changes were unstaged/uncommitted and preserved. No staged files and no commit were created.
- **Target command:** `.venv\Scripts\python.exe -m pytest -q tests/test_run_store.py tests/test_comparison_graph.py`.
- **Target result:** `PASS` — 29 passed.
- **Full main suite:** `.venv\Scripts\python.exe -m pytest -q` — `PASS`, 154 passed in 7.97 s.
- **Compilation:** Phase 2 source/test syntax compilation `PASS`.
- **Diff hygiene:** `git diff --check` — `PASS`; only expected Windows line-ending conversion notices.
- **Source-side-effect scan:** formal node provider calls occur only inside `HarnessCore.execute` callbacks; formal artifact writes use `record_artifact`; formal checkpoints use `SQLiteComparisonCheckpointStore`.
- **Proven:** one physical callback for identical concurrent/semantic requests; provider-success/Graph-commit crash replay; UNKNOWN no-auto-retry; atomic crash/concurrency budget bound; completed Run logical no-op; Run writer/operation heartbeats and fencing; server-side cost/approval policy; strict fresh/cached decoder symmetry; immutable contained publish; checkpoint CAS; durable V1/pre-ledger V2 blocking.
- **Not proven:** current real HFSS behavior, strict worker/AEDT termination, native provider-file byte immutability, mandatory provider/code fingerprints, saved-node continuation, explicit reconciliation, bounded autonomous iteration, or supplied-objective causal control.
- **HFSS/AEDT/ADS:** `NOT RUN`.

### Phase 1 Domain Contract and State V2

- **Date:** 2026-08-21.
- **Starting Git evidence:** branch `master`, HEAD `08f001e84f463936b2bacc7ff90d77d18b7887a6`; Phase 0 changes were unstaged/uncommitted and preserved. No files were staged and no commit was created.
- **Target command:** `.venv\Scripts\python.exe -m pytest -q tests/test_domain_contract_v2.py tests/test_state_v2.py tests/test_checkpoint_v2.py tests/test_comparison_graph.py`.
- **Target result:** `PASS` — 20 passed in 0.72 s.
- **Full main suite:** `.venv\Scripts\python.exe -m pytest -q` — `PASS`, 130 passed in 1.79 s.
- **Compilation:** `.venv\Scripts\python.exe -m compileall -q src tests` — `PASS`.
- **Diff hygiene:** `git diff --check` — `PASS`; only Windows line-ending conversion notices.
- **Proven:** strict State/Manifest round-trip; Path, NaN, mutable alias, duplicate key, unsupported and unknown-field rejection; tuple/list semantic restoration; wrong run/context/candidate/result/comparison rejection; evidence-only Best promotion; V2-only writes; V1 completed/interrupted classification and no-overwrite migration; canonical manifest/ArtifactRef integration; completed V2 Graph replay.
- **Not proven:** saved-node continuation, crash-point action reconciliation, multi-process same-task safety, external process cancellation/timeout upper bound, supplied-objective behavioral control, closed-loop iteration, or current real HFSS behavior.
- **HFSS/AEDT/ADS:** `NOT RUN`.

### Phase 0 safety and authoritative result contract

- **Date:** 2026-08-21.
- **Starting Git evidence:** branch `master`, HEAD `08f001e84f463936b2bacc7ff90d77d18b7887a6`, clean working tree before implementation. No commit was created.
- **Pre-change focused baseline:** 23 passed / 6 failed across comparison graph, CLI, Production evaluation contract, and worker-contract files. The failures were the known empty-rule/stale-trace ISSUE-008 boundary.
- **Safety target:** real-entry configuration/acknowledgement tests `PASS` (7 passed) without provider composition or AEDT.
- **Phase 0 target command:** `.venv\Scripts\python.exe -m pytest -q tests\test_comparison_graph.py tests\test_cli.py tests\test_terminal_outcomes.py tests\test_production_evaluation_contract.py tests\test_real_hfss_safety.py tests\test_pyaedt_worker_contract.py`.
- **Target result:** `PASS` — 37 passed.
- **Full main suite:** `.venv\Scripts\python.exe -m pytest -q` — `PASS`, 115 passed in 1.70 s.
- **Diff hygiene:** `git diff --check` — `PASS`; only Windows line-ending conversion notices.
- **Proven:** fail-closed real entry, explicit authorization arguments, coherent Mock-only evaluation contract, rule-comparison-driven Best promotion, candidate identity checks, typed terminal outcomes, typed process exit codes, gate rejection, degraded candidate retention, candidate success, completed-checkpoint reuse, and Production-band no-AEDT comparison/promotion.
- **Not proven:** real AEDT lifecycle, current real HFSS output, formal WF-003 E2E, mid-run checkpoint type fidelity, cancellation cleanup, strict timeout upper bound, calibration, supplied-objective behavioral control, or an Agent feedback loop.
- **HFSS/AEDT/ADS:** NOT RUN.

### ISSUE-003 comparison status presenter import

- **Date:** 2026-08-20.
- **Before:** safe rule-configured WF-001 Graph reached `compare_hfss_results` and raised `NameError: name 'emit_status' is not defined` at `comparison_nodes.py:320`.
- **Contract inspection:** `harness.terminal.emit_status(scope, status, *, detail=None, stream=None)` is the existing definition/export used by production callers; both comparison calls already matched that contract.
- **Direct regression:** `.venv\Scripts\python.exe -m pytest tests/test_production_evaluation_contract.py::test_rule_configured_wf001_graph_completes_comparison_after_presenter_import -q` — `PASS` (1 passed).
- **ISSUE-003 target file:** `.venv\Scripts\python.exe -m pytest tests/test_production_evaluation_contract.py -q` — `PASS` (12 passed).
- **Comparison-related:** evaluator file `PASS` (15 passed); legacy comparison Graph file `FAIL` (5 failed) because its deprecated Mock fixtures remain empty-rule/INVALID under ISSUE-008.
- **Full main suite:** `FAIL` — 107 collected, 101 passed, 6 failed. The unchanged failures are one deprecated WF-002 CLI and five stale Mock graph/checkpoint/resume cases.
- **Safe full-Graph probe:** comparison `FULLY_ACHIEVED`; graph reaches candidate diagnosis, Best update, decision, and `complete`. `BEST=baseline` plus `update_hfss_best:retained` exposes ISSUE-004; it was not repaired.
- **Vendor optimizer suite:** `PASS` — 7 passed.
- **HFSS/AEDT:** NOT RUN.

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

- **Current date:** 2026-08-21
- **Command:** `.venv\Scripts\python.exe -m pytest -q`
- **Current Phase 2 result:** `PASS` — 154 passed.
- **Previous Phase 1 result:** `PASS` — 130 passed.
- **Previous Phase 0 result:** `PASS` — 115 passed.
- **Historical result before Phase 0:** `FAIL` — 107 collected, 101 passed, 6 failed after ISSUE-003.
- **Closure:** Phase 2 adds transactional action/event/checkpoint authority and resolves external-action duplicate replay plus formal artifact concurrency. It does not prove saved-node continuation, real worker lifecycle, or autonomous iteration.

### ISSUE-001 targeted regression

- **Before:** existing `tests\test_cli.py::test_offline_cli_returns_zero_and_creates_complete_artifacts` failed in `build_optimization_intent → emit_optimization_intent` with `NameError: name 'evaluation' is not defined`.
- **After direct:** `tests\test_terminal_output.py::test_optimization_intent_presenter_uses_explicit_evaluation_contract` — `PASS` (1 passed).
- **After presenter file:** `tests\test_terminal_output.py` — `PASS` (8 passed).
- **After original Agent boundary:** the CLI test no longer raises NameError; it fails later because deprecated WF-002 still has empty rules and produces no candidate artifact.

### Current-source Offline route

- **Current Phase 0 command evidence:** `tests/test_cli.py` invokes the same `run_offline_demo` entry boundary with a temporary artifact root.
- **Result:** `PASS`; status `succeeded_candidate`, terminal reason `candidate_target_met`, candidate artifact present, process exit mapping zero.
- **Interpretation:** WF-002 uses a separate Mock-only `offline-evaluation-v1`; it does not claim Production physics or replace Production Contract v1.

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

## Calibration-authority and real-readiness hardening — 2026-08-24

- **Final full main offline suite:** `.venv\Scripts\python.exe -m pytest -q` — `PASS`, 225 passed in 46.79 s.
- **Focused Calibration/real-safety/Production set:** 73 passed in 1.70 s after contract/model changes.
- **Three-case fake campaign:** 4 passed; proves deterministic distinct cases, default-disabled admission, exact `3/0` policy, Harness execution, passing recomputation, and 15 immutable typed receipts without AEDT.
- **ISSUE-031 regressions:** reject one-case/vacuous ranking, policy threshold/digest drift, incomplete providers, empty/missing/duplicate-role/tampered artifacts, wrong-candidate semantic forgery, and aggregate/report drift before readiness acceptance.
- **ISSUE-018 standalone Builder mapping:** `PASS`, 3 passed under Agent Python with no `ansys` import/project construction.
- **Supplied optimizer vendor suite:** `PASS`, 7 passed in 5.19 s. With the Builder-aligned PI constant, the audited quick Pareto frontier may legitimately contain one non-dominated point; the Agent preserves the complete returned frontier rather than fabricating backup points.
- **Compilation/config hygiene:** changed source/tests/tools/entries compile; runtime JSON parses; checked-in Calibration and Canary gates are both false/null; `git diff --check` exits 0 with Windows line-ending notices only.
- **Environment preflight:** `PASS` for Agent Python, LangGraph, PyAEDT Python/package 0.18.1, AEDT 2025.1 executable, Builder/optimizer/contracts, headless mode, artifact root, and idle Agent license lock. This does not consume or prove a license.
- **Default entry fail-closed probe:** both `RUN_HFSS_CALIBRATION.py` and `RUN_REAL_HFSS.py` reject disabled configuration before provider composition. No AEDT/HFSS/ADS process started.
- **Evidence level:** implementation `OFFLINE VERIFIED`; physical Calibration/Canary `NOT RUN` at this snapshot.

### First authorized Calibration import probe and repair

- **Observed result:** baseline composite worker exited 1 in about 0.1 s before PyAEDT/AEDT import with Python-3.10 `StrEnum` incompatibility. Harness status is `UNKNOWN / WAITING_RECONCILIATION`; one conservative action authorization is retained, but observed AEDT/model/solve launch count is 0.
- **Residual-process check:** no `ansysedt`, HFSS, Ansys, or worker Python process; no active/quarantine lock; no `.aedt` or `.s2p` was created.
- **Repair evidence:** package/HFSS exports are lazy and shared enums have a Python-3.10 shim. Configured PyAEDT/AEDT Python executes `hfss_optimization_agent.hfss.pyaedt_worker --help` with exit 0. Focused worker/Calibration/import suite `PASS` — 26 passed in 0.73 s.
- **Reconciliation improvement:** new campaigns preregister the short-lived exact reconciliation scope; fake campaign proves two grants. The pre-fix Run remains immutable evidence because authority correctly cannot be added after UNKNOWN.
- **Evidence level:** ISSUE-032 `RESOLVED OFFLINE`; ISSUE-033 `RESOLVED FOR NEW RUNS`; fixed physical campaign `NEEDS VERIFICATION`.
- **Post-repair full main suite:** `PASS` — 226 passed in 46.48 s.

### Second authorized Calibration cold-start probe and repair

- **Observed result:** Python-3.10 import succeeded and PyAEDT reported version 0.18.1 plus Desktop initialization. The generic 15-second heartbeat expired during cold start; supervisor terminated the process tree in about 20.2 s. Builder/Solve/extraction did not start and no `.aedt`/`.s2p` exists.
- **Cleanup:** no AEDT/HFSS/Ansys/worker process and no active/quarantined lock remained.
- **Explicit reconciliation:** `op_010fc0a5660a6ad518932068ad1b9747` / `att_2911e49b15479ae67cd1698c263bfec8` became `CONFIRMED_FAILED`; immutable evidence artifact `art_fc08e727591a9e23207787291c90bc47`, request digest `0853e6b5dad11c252d715777ff47ba263190c2703fac6ff62a0de4a111fe4bdd`. No new attempt or budget refund occurred.
- **Repair:** real composition heartbeat-loss bound is 120 seconds; action/solve timeout remains 7200 seconds and auto retry remains zero. Offline composition assertion and full process-safety regressions are required before the next campaign.
- **Post-repair verification:** process/reconciliation/worker/Calibration focus `PASS` — 39 in 1.88 s; final full suite `PASS` — 226 in 46.35 s.

### Third authorized Calibration target-design probe and repair

- **Observed result:** AEDT started and wrote a 4,271-byte project plus lock. PyAEDT log proves target design insertion was attempted, then `active_design` received `None`/`bool` and `Hfss.__init__` failed. No geometry progress, setup, solve completion, or Touchstone exists.
- **Cleanup/reconciliation:** process and Agent-lock scans empty. Operation `op_51e7f8d6face2265f8ce9f658dfc8137` / attempt `att_cd656198281bb3d76c7676caf459f80c` explicitly `CONFIRMED_FAILED`; evidence `art_f726f0afabb0245a06760bf27d6b081a`, digest `83091e195825d522e84855ab6b3b9a55d0fa6d6767f2e789027da1722ccfa536`.
- **Repair:** exact-target gRPC design resolver accepts object return or bounded polling and rejects wrong names. Unit tests cover bool acknowledgement and wrong-design fail-closed behavior.
- **Post-repair verification:** worker/process/reconciliation focus `PASS` — 41 in 1.87 s; configured AEDT Python worker import exit 0; final full suite `PASS` — 228 in 47.27 s.

### Fourth authorized Calibration delayed-design probe and repair

- **Observed result:** clean HEAD `52067ba5f0743d51b530f6665b6d2773bcc10f91` reached the exact-target compatibility hook, but AEDT did not expose `interposer_temple4` during the 30-second read-only polling window. The worker eventually emitted the same fail-closed constructor error and supervision terminated the tree. No geometry milestone, Setup/Sweep, Solve result, or Touchstone exists.
- **Cleanup/reconciliation:** process and Agent-lock scans were empty. Operation `op_ad9593d53eebacb86685fa638e62e6ff` / attempt `att_092ca07a34dc4a2166c18159ba67e20d` is explicitly `CONFIRMED_FAILED`; evidence `art_f614467f305ca1930bbf235cd6725519`, digest `ab957331f76d41b24caf708665c730656b2634119159c4322500a40220f4bfc6`. Attempt count and conservative budget remain one/consumed; no retry or refund occurred.
- **Repair:** the resolver now repeats exact-name activation throughout the finite interval instead of activating once and only reading. It captures normalized `GetTopDesignList()` evidence on timeout and retains exact-name rejection of `huitu`/fallbacks.
- **Post-repair verification:** worker/backend/process focus `PASS` — 31 in 1.24 s; final full main suite `PASS` — 229 in 46.74 s.

### Fifth authorized Calibration stale-gRPC-application probe and repair

- **Observed result:** clean HEAD `ad093263d852193ebe1f4384181c238b9416b86c` retried activation but reported `observed top designs=()`. This isolates stale gRPC application visibility after `InsertDesign`; no geometry, Setup/Sweep, Solve result, or Touchstone exists.
- **Cleanup/reconciliation:** zero AEDT/HFSS/worker processes and no Agent lock remained. Operation `op_958d6e55c74c48235f8c487efd08ea1e` / attempt `att_bac8e3b29c8efc0cca73c7472905c8b6` became `CONFIRMED_FAILED`; evidence `art_d694f78574d7d34fa9119268a9c42d04`, digest `2ed1c261705958806c727f5bbd289f25c686d4130f02268160c765a813137e3a`. No retry/refund/new attempt.
- **Repair:** one PyAEDT-supported application recreation is permitted, followed by exact original-project reacquisition and exact target-design resolution. Wrong project/design still fails closed.
- **Post-repair verification:** worker/backend/process focus `PASS` — 32 in 1.28 s; full main suite `PASS` — 230 in 46.45 s.

### Sixth authorized Calibration and license-authority finding

- **Observed result:** clean HEAD `479a5ca84470f3f9e1d9fdc335679d1264e665a4`, campaign `hfss-calibration-20260824-105414`, stopped after one baseline attempt and zero automatic retries. No Builder milestone, Solve result, Touchstone, or accepted case exists.
- **Root evidence:** the campaign `batch.log` records FlexNet `-15,10` for feature `hfss_gui` at `1055@localhost`. Retrospective scan proves the same upstream error in campaigns `102020`, `103140`, and `104554`; prior PyAEDT symptoms are not independently attributable.
- **Cleanup/reconciliation:** operation `op_450ae811bb520e722e541d4b9a91456f` / attempt `att_95f454115faf49f8cef1fdf95386995b` became `CONFIRMED_FAILED`; evidence `art_8094c55489184ab113e28b033d7a21b1`, digest `60e901ef3f3013b89ba954b0f399a187acccddafeffbdf974f68ee0f673392cd`. No process/Agent lock remains and no retry/refund/new attempt occurred.
- **License boundary:** port 1055 is not listening. Starting the exact stopped Windows service was denied for lack of service-control permission and changed no state. The discovered local license provenance is unverified/unacceptable and was not enabled or used.
- **Result:** ISSUE-036 `OPEN / BLOCKER`; real Calibration, Canary, and E2E remain `NOT RUN / BROKEN BEFORE SOLVE`. Last full offline suite remains `PASS` — 230 in 46.45 s.

### License gate recheck after external service-state change

- **Observed:** clean HEAD `b50ea3c4df7fe8d52c39265afb929d2324ca5043`; local `Ansys PLE Licensing 2026 R1` now reports Running, `:::1055` listens, and `lmgrd`/`ansyslmd` processes exist. The actor that changed service state is not inferred.
- **Authority result:** `FAIL`. The configured endpoint remains `1055@localhost` backed by the previously identified unverifiable local license source. Connectivity does not establish legitimate entitlement or authorize feature checkout.
- **Safety:** no `lmutil`, AEDT, HFSS worker, Builder, Solve, Calibration, or Canary was invoked during this recheck. ISSUE-036 remains OPEN.

### Seventh authorized Calibration and native-call heartbeat finding

- **Authority:** clean HEAD `2248da81d77edefb3ab7372040ca54a8edfa9ec4`, campaign `hfss-calibration-20260824-124719`, baseline attempt only, zero automatic retries.
- **Real milestones:** preflight passed; independent headless AEDT created exact `interposer_temple4`; materials, geometry, ports/boundaries, Setup1, Sweep, report, and project save completed; `analyze_setup` was submitted. No prior FlexNet `-15,10` appears in this campaign log.
- **Stop/result:** same-process Python heartbeat stopped during blocking native Solve. The finite 120-second stale bound terminated the Job. No response JSON, structured HFSS result, Touchstone, accepted case, Calibration Evidence, or E2E result exists.
- **Reconciliation:** operation `op_f7b18d41bbe3a71e7ac1315143b60578` / attempt `att_e3d942c4f2d2300a154a753265d03a15` is `CONFIRMED_FAILED`; evidence `art_b067a5b684f8701089b178ecd449c88c`, digest `901f5cf1e59e2feb12eb3fb58f47d6db508c7e041600c9f21f749a31b407fac6`. No retry/refund and no residual process/Agent lock.
- **Repair:** PyAEDT uses a Job-contained companion process for native-call-safe heartbeat; ordinary workers retain thread heartbeat. Calibration console output now configures UTF-8.
- **Verification:** focused process/lock/worker/Calibration suite `PASS` — 40 in 3.11 s; full offline suite `PASS` — 233 in 36.65 s; configured AEDT Python import/CLI probes pass without launching AEDT.
- **Evidence level:** repair `OFFLINE VERIFIED`; target build `REAL HFSS VERIFIED` for this exact historical revision only; completed Solve/Calibration/Canary/E2E `NOT RUN / NEEDS VERIFICATION`.

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
