"""Phase-0 terminal classification for the retained comparison graph."""

from __future__ import annotations

from .comparison_state import (
    ComparisonAgentState,
    baseline_evaluation,
    baseline_evaluation_record,
    candidate_evaluation,
    candidate_evaluation_record,
    candidate_hfss_result,
    candidate_sparameter_result,
    current_candidate,
    current_comparison_record,
    state_context_id,
    state_run_id,
)
from ..core.enums import NextAction, WorkflowStatus
from ..core.models import TerminalOutcome


def classify_terminal_outcome(state: ComparisonAgentState) -> TerminalOutcome:
    """Classify the graph's terminal state without treating all stops as success."""

    run_id = state_run_id(state)
    context_id = state_context_id(state)
    candidate = current_candidate(state)
    candidate_id = candidate.candidate_id if candidate else None
    candidate_hfss = candidate_hfss_result(state)
    candidate_eval = candidate_evaluation(state)
    candidate_record = candidate_evaluation_record(state)
    comparison_record = current_comparison_record(state)
    candidate_evidence = tuple(
        evidence_id
        for evidence_id in (
            candidate_record.record_id if candidate_record else None,
            comparison_record.record_id if comparison_record else None,
        )
        if evidence_id is not None
    )
    if candidate_hfss is not None:
        if not candidate_hfss.success:
            return TerminalOutcome(
                WorkflowStatus.FAILED,
                "candidate_hfss_failed",
                candidate_hfss.error or "Candidate HFSS provider failed.",
                run_id,
                context_id,
                candidate_id,
                candidate_evidence,
            )
        if candidate_eval is None or candidate_eval.status == "INVALID":
            return TerminalOutcome(
                WorkflowStatus.INVALID,
                "candidate_evaluation_invalid",
                candidate_eval.reason if candidate_eval else "Candidate evaluation is missing.",
                run_id,
                context_id,
                candidate_id,
                candidate_evidence,
            )
        if candidate_eval.pass_target:
            return TerminalOutcome(
                WorkflowStatus.SUCCEEDED_CANDIDATE,
                "candidate_target_met",
                "Candidate HFSS evidence satisfies the configured hard rules.",
                run_id,
                context_id,
                candidate_id,
                candidate_evidence,
            )
        return TerminalOutcome(
            WorkflowStatus.REJECTED,
            "candidate_not_accepted",
            "Candidate HFSS evidence is valid but does not satisfy the target.",
            run_id,
            context_id,
            candidate_id,
            candidate_evidence,
        )

    candidate_sparameters = candidate_sparameter_result(state)
    if candidate is not None:
        if candidate_sparameters is None or not candidate_sparameters.success:
            return TerminalOutcome(
                WorkflowStatus.FAILED,
                "candidate_surrogate_failed",
                (
                    candidate_sparameters.error
                    if candidate_sparameters is not None
                    else "Candidate surrogate result is missing."
                ),
                run_id,
                context_id,
                candidate_id,
                (f"sparameter:{candidate_id}",) if candidate_id else (),
            )
        decision = state["decision_outcome"]
        if decision is not None and decision.action == NextAction.STOP:
            return TerminalOutcome(
                WorkflowStatus.REJECTED,
                "candidate_gate_rejected",
                "Candidate did not pass the configured surrogate gate.",
                run_id,
                context_id,
                candidate_id,
                decision.evidence_ids,
            )
        return TerminalOutcome(
            WorkflowStatus.FAILED,
            "candidate_execution_incomplete",
            "Candidate execution ended before an HFSS result was available.",
            run_id,
            context_id,
            candidate_id,
            decision.evidence_ids if decision else (),
        )

    baseline_result = baseline_evaluation(state)
    baseline_record = baseline_evaluation_record(state)
    baseline_evidence = (baseline_record.record_id,) if baseline_record else ()
    if baseline_result is None or baseline_result.status == "INVALID":
        return TerminalOutcome(
            WorkflowStatus.INVALID,
            "baseline_evaluation_invalid",
            baseline_result.reason if baseline_result else "Baseline evaluation is missing.",
            run_id,
            context_id,
            state["manifest"].baseline_candidate_id,
            baseline_evidence,
        )
    if baseline_result.pass_target:
        return TerminalOutcome(
            WorkflowStatus.SUCCEEDED_BASELINE,
            "baseline_target_met",
            "Baseline HFSS evidence already satisfies the configured hard rules.",
            run_id,
            context_id,
            state["manifest"].baseline_candidate_id,
            baseline_evidence,
        )
    return TerminalOutcome(
        WorkflowStatus.REJECTED,
        "no_actionable_optimization",
        "Baseline is valid but the retained workflow produced no actionable candidate route.",
        run_id,
        context_id,
        state["manifest"].baseline_candidate_id,
        baseline_evidence,
    )
