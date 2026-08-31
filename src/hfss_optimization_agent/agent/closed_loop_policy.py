"""Authoritative bounded policy for the real-HFSS production closed-loop graph."""

from __future__ import annotations

from .closed_loop_contracts import (
    ClosedLoopControllerState,
    ControllerAction,
    ControllerDecision,
)
from .comparison_state import (
    ComparisonAgentState,
    baseline_evaluation,
    candidate_evaluation,
    candidate_hfss_result,
    candidate_sparameter_result,
    evaluation_record,
)
from ..core.enums import NextAction, WorkflowStatus


class ClosedLoopPolicy:
    """Produce the sole conditional-route decision for every controller turn."""

    def decide(self, state: ComparisonAgentState) -> ClosedLoopControllerState:
        controller = state["controller"]
        if controller is None:
            raise ValueError("closed-loop policy requires controller state")
        if controller.pending_action is not None:
            return controller

        action, code, reason = self._choose(state, controller)
        iteration = controller.controller_iterations + 1
        # The last admitted controller turn is always a typed finalization. This
        # makes the bound true for every provider result sequence.
        if iteration >= controller.budget.max_controller_iterations and action not in {
            ControllerAction.FINALIZE,
            ControllerAction.RECONCILE,
        }:
            action, code, reason = self._budget_terminal(
                state, "controller_iteration_budget_exhausted"
            )
        decision = ControllerDecision(
            decision_id=f"controller:{iteration}:{action}",
            iteration=iteration,
            action=action,
            reason_code=code,
            reason=reason,
            candidate_id=state["current_candidate_id"],
        )
        return controller.replace(
            controller_iterations=iteration,
            pending_action=action,
            decisions=(*controller.decisions, decision),
        )

    def _choose(
        self,
        state: ComparisonAgentState,
        controller: ClosedLoopControllerState,
    ) -> tuple[ControllerAction, str, str]:
        if WorkflowStatus(state["status"]) is WorkflowStatus.WAITING_RECONCILIATION:
            return (
                ControllerAction.RECONCILE,
                "physical_outcome_requires_reconciliation",
                "An UNKNOWN physical outcome requires explicit reconciliation.",
            )
        baseline = baseline_evaluation(state)
        if baseline is None or baseline.status == "INVALID":
            return (
                ControllerAction.FINALIZE,
                "baseline_evaluation_invalid",
                "Baseline evaluation is missing or invalid.",
            )
        if baseline.pass_target and baseline.soft_failed_rule_count == 0:
            return (
                ControllerAction.FINALIZE,
                "baseline_target_met",
                "Baseline HFSS evidence satisfies all configured hard and soft rules.",
            )

        candidate_id = state["current_candidate_id"]
        if candidate_id is not None:
            surrogate = candidate_sparameter_result(state)
            if surrogate is None:
                if controller.candidate_screenings >= controller.budget.max_candidate_screenings:
                    return self._budget_terminal(state, "candidate_screening_budget_exhausted")
                return (
                    ControllerAction.SCREEN_CANDIDATE,
                    "candidate_requires_screening",
                    "The selected candidate requires surrogate screening.",
                )
            if not surrogate.success:
                if controller.safe_retries < controller.budget.max_safe_retries:
                    return (
                        ControllerAction.RETRY_SAFE,
                        "confirmed_surrogate_failure_retry_safe",
                        "The surrogate returned a confirmed failure; retry with a new action identity is safe.",
                    )
                return self._next_candidate("surrogate_failure_retry_budget_exhausted")
            decision = state["decision_outcome"]
            if decision is not None and decision.candidate_id == candidate_id and decision.action == NextAction.STOP:
                return self._next_candidate("candidate_screen_rejected")

            hfss = candidate_hfss_result(state)
            if hfss is None:
                if controller.candidate_hfss_calls >= controller.budget.max_candidate_hfss_calls:
                    return self._budget_terminal(state, "candidate_hfss_budget_exhausted")
                return (
                    ControllerAction.RUN_CANDIDATE_HFSS,
                    "candidate_screen_passed",
                    "The candidate passed screening and requires HFSS evaluation.",
                )
            if not hfss.success:
                if (
                    not state["manifest"].real_execution
                    and controller.safe_retries < controller.budget.max_safe_retries
                ):
                    return (
                        ControllerAction.RETRY_SAFE,
                        "confirmed_fake_hfss_failure_retry_safe",
                        "The fake HFSS provider returned a confirmed failure; a new-identity retry is safe.",
                    )
                return self._next_candidate("candidate_hfss_failed")
            evaluation = candidate_evaluation(state)
            if (
                evaluation is not None
                and evaluation.pass_target
                and evaluation.soft_failed_rule_count == 0
            ):
                return (
                    ControllerAction.FINALIZE,
                    "candidate_target_met",
                    "Candidate HFSS evidence satisfies all configured hard and soft rules.",
                )
            return self._next_candidate("candidate_improved_or_evaluated_without_target")

        if state["candidate_queue"]:
            return (
                ControllerAction.SELECT_NEXT_CANDIDATE,
                "candidate_queue_available",
                "Select the next unconsumed candidate from the authoritative queue.",
            )

        budget = controller.budget
        if controller.stagnation_count >= budget.max_stagnation:
            return self._budget_terminal(state, "stagnation_budget_exhausted")
        if controller.optimizer_calls >= budget.max_optimizer_calls:
            return self._budget_terminal(state, "optimizer_budget_exhausted")
        if controller.prepared_optimizer_iteration == controller.optimizer_calls:
            return (
                ControllerAction.OPTIMIZE,
                "optimizer_request_prepared",
                "Execute the prepared optimizer request.",
            )
        if controller.optimizer_calls > 0 and controller.reoptimizations >= budget.max_reoptimizations:
            return self._budget_terminal(state, "reoptimization_budget_exhausted")
        if controller.optimizer_calls == 0:
            return (
                ControllerAction.PREPARE_OPTIMIZATION,
                "initial_optimization_required",
                "Prepare the first diagnosis-driven optimization request.",
            )
        return (
            ControllerAction.REOPTIMIZE,
            "queue_exhausted_reoptimization_available",
            "The queue is exhausted and bounded diagnosis-driven reoptimization is available.",
        )

    @staticmethod
    def _next_candidate(code: str) -> tuple[ControllerAction, str, str]:
        return (
            ControllerAction.NEXT_CANDIDATE,
            code,
            "Consume the current candidate and continue with the next candidate or reoptimization.",
        )

    @staticmethod
    def _no_solution(code: str) -> tuple[ControllerAction, str, str]:
        return (
            ControllerAction.FINALIZE,
            code,
            "The bounded search budget is exhausted without a target-satisfying solution.",
        )

    @staticmethod
    def _budget_terminal(
        state: ComparisonAgentState, code: str
    ) -> tuple[ControllerAction, str, str]:
        policy = state.get("best_policy")
        selected = policy.selected_candidate_id if policy is not None else None
        record = evaluation_record(state, candidate_id=selected) if selected else None
        evaluation = record.to_result() if record is not None else baseline_evaluation(state)
        if evaluation is not None and evaluation.pass_target:
            return (
                ControllerAction.FINALIZE,
                "core_pass_margin_incomplete",
                f"The configured hard rules pass, but configured soft-rule margins remain incomplete ({code}).",
            )
        return ClosedLoopPolicy._no_solution(code)
