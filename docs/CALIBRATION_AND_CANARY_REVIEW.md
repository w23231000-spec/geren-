# Calibration Evidence and Real Canary Review

Reviewed: **2026-08-24 +08:00**

## Review outcome

- Starting review revision: `cd29846aef5cdf99b36aa74fda717231bcd3450e`; current work started from HEAD `b42378f55de22690f12b7b62ee0ee7da107db6b8`. The final executable revision must be freshly recorded after offline verification/commit.
- Calibration authority: `OFFLINE VERIFIED` for schema/policy/cardinality/provider/artifact/recomputation controls; ISSUE-031 is resolved offline.
- Model authority: the user explicitly approved the existing HFSS Builder and recommended threshold policy. The strict versioned model-alignment/HFSS contracts fix those choices before collection; ISSUE-010 is resolved for evidence collection.
- Builder test isolation: ISSUE-018 is resolved offline.
- Calibration Evidence: `INSUFFICIENT EVIDENCE` until the authorized baseline plus two-candidate physical campaign runs and passes.
- Real HFSS Canary: authorized in principle but still gate-dependent. It can run only after a passing campaign on the same clean exact revision creates a validated short-lived readiness manifest.
- HFSS/AEDT/ADS: `NOT RUN` at this documentation snapshot.

The user accepted the bounded Canary residuals under ISSUE-013 and ISSUE-015/026 for this exact sequence. That acceptance does not waive Calibration, clean-HEAD, expiry, solve-budget, zero-retry, UNKNOWN, or process-quarantine controls.

## Reproducible identity inventory

| Identity | Value / status |
|---|---|
| Implementation Git revision | `cd29846aef5cdf99b36aa74fda717231bcd3450e` |
| Agent source SHA-256 | `dbeb03d7465de892c2943c38d5b30a1200a88e84ad77342a117f391299f5cd42` |
| Supplied optimizer source SHA-256 | `8b31faad6fb9b35ede396222f528da6ea2df887638e1b3a28298c69f273cc14c` |
| Supplied surrogate source SHA-256 | `8b31faad6fb9b35ede396222f528da6ea2df887638e1b3a28298c69f273cc14c` |
| HFSS Builder source SHA-256 | `a7dfa048050d5a09ccd3da3208c4d3baa30e1b021aef85150d21f0b58d41fc61` |
| PyAEDT executable SHA-256 | `d35e39ef646753a455f053b1f080b70096e17fc4ffee5c2c664863ebe4e61955` |
| HFSS worker protocol | `hfss-composite-request/1.0` |
| Closed-loop policy SHA-256 | `fb53f34ca0d00350c59a3e7501da0efe7c0f8638f7f5a3bd945bc850627f4296` |
| HFSS contract SHA-256 | `7bc879f71518f6ea1034910ae27cd711a3356ae2758bce9ae3ef2d80cce0dcef` |
| HFSS contract ID | `0EF9651247B177C5A27937B9AB8CE3D0B5A72A0AD859DB02DD34309A3ED5679D` |
| Evaluation contract SHA-256 | `907f1999d6cab62387a75d4a14982628f572fcd335520bb1a883fbdd8babfa47` |
| Comparison context | `pa-multi-builder-2025.1-setup1-sweep-ports4to3-v1` |

The table above is retained as the previous committed-review inventory and must not be copied into a new manifest. The preparation tools freshly hash the final clean HEAD, Agent/provider/PyAEDT bytes, current contract/model/policy, deterministic case plan, and expiry.

## Existing-data disposition

The ignored historical run `runs/real-vscode-20260818-101711` contains two Touchstone files and paired surrogate/HFSS JSON for baseline and candidate. Its context string matches the current contract, but it has no attributable Agent/Builder revision manifest; its recorded optimizer source identity differs from the current source identity. The earlier reconstruction also produced mean complex RMSE `0.07320`, mean dB RMSE `3.327 dB`, and pairwise ranking agreement `0.0`.

Disposition: `HISTORICALLY VERIFIED / CALIBRATION FAILED` only. It cannot be imported as passing evidence or authorize current execution.

## Authorized evidence sequence

1. Final offline suite, compile/default-disable/diff checks, memory synchronization, and a user-authorized Git commit establish one clean exact revision.
2. `PREPARE_HFSS_CALIBRATION.py` issues an eight-hour authority for the exact revision and deterministic case plan: baseline plus two interior candidates. It never launches AEDT.
3. With `HFSS_CALIBRATION_MANIFEST` set, `RUN_HFSS_CALIBRATION.py` executes exactly three Harness-controlled composite HFSS actions, headless, timeout 7200 seconds, zero automatic retry, and freezes 15 mandatory receipts.
4. Calibration Evidence 1.1 is recomputed from the immutable structured results under the approved thresholds: mean complex RMSE at most 0.02, mean dB RMSE at most 1.0 dB, and ranking agreement at least 0.8, with strict grid/context/port/impedance agreement.
5. Failure, UNKNOWN, timeout, unverified kill, residual process, or missing/tampered receipt stops. Passing evidence permits `PREPARE_REAL_HFSS_CANARY.py` to create and self-validate an eight-hour exact Production readiness manifest.
6. `RUN_REAL_HFSS.py` then executes the Closed-loop V2 Canary with at most baseline plus one candidate physical launch, zero automatic retry. Only that exact revision/contract/source combination may be labelled `REAL HFSS VERIFIED` if terminal/evidence/process checks succeed.

## Blocker acceptance review

| Issue | Review disposition | Rationale |
|---|---|---|
| ISSUE-009 calibration absent | `PHYSICAL GATE` | Mandatory physical evidence cannot be waived; the authorized campaign is the next action. |
| ISSUE-010 model alignment | `RESOLVED FOR COLLECTION` | User-approved Builder authority and strict versioned contract now fix the comparison basis before results. |
| ISSUE-031 calibration authority gap | `RESOLVED OFFLINE` | Evidence 1.1 and readiness recomputation reject formal and semantic bypasses. |
| ISSUE-012 historical attribution | `DO NOT ACCEPT AS CURRENT EVIDENCE` | Not a blocker to a new attributable run; historical results remain history only. |
| ISSUE-013 START-based resume | `USER-ACCEPTED FOR THIS BOUNDED CANARY` | At-most-once receipts, fencing, bounded control, and completed no-op limit Canary risk; saved-node continuation remains deferred. |
| ISSUE-015 / ISSUE-026 real AEDT lifecycle | `USER-ACCEPTED FOR THIS BOUNDED CANARY` | Job containment, deadlines, zero auto-retry, UNKNOWN, and quarantine pass offline; actual AEDT behavior is a Canary observation. |
| ISSUE-018 Builder test environment | `RESOLVED OFFLINE` | Pure mapping is decoupled from PyAEDT and passes under Agent Python. |
| ISSUE-019 returned grid | `RESOLVED OFFLINE` | Preserve as a Canary assertion; no risk acceptance is needed. |
| ISSUE-028 sparse non-real manifests | `RECOMMEND SCOPE ACCEPTANCE` | Formal actionable real Runs reject sparse identity; residual scope is Mock/non-real only. |

Acceptance is limited to the exact committed revision, headless mode, three Calibration launches, two Canary launches, 7200-second per-action timeout, and zero automatic retry. It is not a standing authorization for later revisions.

## Next engineering action

Complete the final offline suite and commit. Then execute the exact authorized Calibration sequence. Only a passing immutable package proceeds to Canary; otherwise preserve the evidence and stop with an explicit non-success/UNKNOWN outcome.
