# Calibration Evidence and Real Canary Review

Reviewed: **2026-08-24 +08:00**

## Review outcome

- Reviewed implementation revision: `cd29846aef5cdf99b36aa74fda717231bcd3450e`.
- Calibration Evidence: `INSUFFICIENT EVIDENCE`. No accepted current-provider paired dataset or `calibration-evidence/1.0` artifact exists.
- Real HFSS Canary: `NO-GO`. ISSUE-009, ISSUE-010, and ISSUE-031 are mandatory blockers.
- HFSS/AEDT/ADS: `NOT RUN` during this review.

This review does not turn historical data into current evidence, does not approve physical-model assumptions, and does not authorize a Canary.

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

The final documentation commit changes Git HEAD but not Agent/provider source bytes. Any future readiness manifest must freshly collect and bind the then-current clean HEAD rather than copy the implementation revision above.

## Existing-data disposition

The ignored historical run `runs/real-vscode-20260818-101711` contains two Touchstone files and paired surrogate/HFSS JSON for baseline and candidate. Its context string matches the current contract, but it has no attributable Agent/Builder revision manifest; its recorded optimizer source identity differs from the current source identity. The earlier reconstruction also produced mean complex RMSE `0.07320`, mean dB RMSE `3.327 dB`, and pairwise ranking agreement `0.0`.

Disposition: `HISTORICALLY VERIFIED / CALIBRATION FAILED` only. It cannot be imported as passing evidence or authorize current execution.

## Evidence that must be prepared

1. Approve a versioned physical-model alignment contract. The current example remains `unconfirmed`, declares 800 points while Production declares 200, and leaves PI permittivity, SiO2 mapping, Gsub, Rlf1, alpha, and fixed-frequency assumptions unresolved.
2. Fix ISSUE-031 so readiness accepts only an approved calibration policy/version, enough comparable cases, the complete causal provider set, and non-empty immutable source-artifact receipts.
3. Approve the calibration policy before collecting data. Thresholds must come from a model/domain owner, not be selected after observing results.
4. Collect at least two comparable paired cases; baseline plus at least two representative candidates is recommended. Every case must contain the same candidate identity, 200-point 0.1-20 GHz grid, input/output port order, 50-ohm reference, comparison context, and full complex S11/S12/S21/S22 from both surrogate and HFSS.
5. Freeze candidate inputs, surrogate request/result, HFSS request/result, structured complex export, Touchstone, project, provider fingerprints, and case identities as immutable receipts.
6. Run `assess_calibration` and create canonical evidence only from those receipts. A failing report remains evidence but cannot authorize a Canary.

Data collection requires separately authorized physical solves and is outside this review.

## Blocker acceptance review

| Issue | Review disposition | Rationale |
|---|---|---|
| ISSUE-009 calibration absent | `BLOCK` | Mandatory physical evidence cannot be waived without defeating the real-run gate. |
| ISSUE-010 model alignment | `BLOCK` | Calibration has no stable physical meaning until model-owner assumptions are versioned and approved. |
| ISSUE-031 calibration authority gap | `BLOCK` | Formally valid but insufficient/fabricated evidence could otherwise satisfy readiness. |
| ISSUE-012 historical attribution | `DO NOT ACCEPT AS CURRENT EVIDENCE` | Not a blocker to a new attributable run; historical results remain history only. |
| ISSUE-013 START-based resume | `RECOMMEND CONDITIONAL ACCEPTANCE` | At-most-once receipts, fencing, bounded control, and completed no-op limit Canary risk; saved-node continuation remains deferred. |
| ISSUE-015 / ISSUE-026 real AEDT lifecycle | `RECOMMEND CONDITIONAL ACCEPTANCE FOR CANARY ONLY` | Job containment, deadlines, zero auto-retry, UNKNOWN, and quarantine pass offline; actual AEDT behavior is precisely what a bounded Canary must verify. |
| ISSUE-018 Builder test environment | `CLOSE BEFORE CANARY` | The test is pure parameter mapping but imports the AEDT-coupled module; decouple the mapping import or run the test in the declared PyAEDT interpreter without constructing AEDT. |
| ISSUE-019 returned grid | `RESOLVED OFFLINE` | Preserve as a Canary assertion; no risk acceptance is needed. |
| ISSUE-028 sparse non-real manifests | `RECOMMEND SCOPE ACCEPTANCE` | Formal actionable real Runs reject sparse identity; residual scope is Mock/non-real only. |

No conditional recommendation above is user acceptance. The user must explicitly accept the exact residuals in the short-lived Canary authorization after mandatory blockers are closed.

## Next engineering action

Fix ISSUE-031 first, close the inexpensive ISSUE-018 import/test gap, and obtain model-owner approval for a versioned alignment contract plus calibration policy. Then request separate authorization to collect current-revision paired Calibration Evidence. Only a passing, immutable, fully bound evidence package should be followed by an exact short-lived readiness manifest and a separately authorized Phase 6 Canary.
