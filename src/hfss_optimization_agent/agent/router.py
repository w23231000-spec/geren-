"""Conditional-edge decisions for the one retained comparison workflow."""

from ..core.config import EvaluationConfig, RoutingConfig
from ..core.enums import NextAction
from .comparison_state import (
    ComparisonAgentState,
    candidate_evaluation,
    candidate_hfss_result,
    candidate_sparameter_result,
)


class WorkflowRouter:
    def __init__(self, evaluation: EvaluationConfig, routing: RoutingConfig) -> None:
        self.evaluation = evaluation
        self.routing = routing

    def after_candidate_sparameters(self, state: ComparisonAgentState) -> NextAction:
        """Gate the final optimized candidate before the expensive HFSS provider."""

        result = candidate_sparameter_result(state)
        if result is None or not result.success:
            return NextAction.STOP
        if result.metrics.get("screening_score", float("-inf")) < self.evaluation.candidate_gate_score:
            return NextAction.STOP
        return NextAction.RUN_HFSS

    def after_candidate_hfss(self, state: ComparisonAgentState) -> NextAction:
        result = candidate_hfss_result(state)
        if result is None or not result.success:
            return NextAction.STOP
        evaluation = candidate_evaluation(state)
        if evaluation is not None and evaluation.pass_target:
            return NextAction.PASS
        return NextAction.STOP
