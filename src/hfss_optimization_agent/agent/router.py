"""Conditional-edge decisions for the one retained comparison workflow."""

from ..core.config import EvaluationConfig, RoutingConfig
from ..core.enums import NextAction
from ..core.models import FrequencyPlan
from ..evaluation.evaluator import DeterministicEvaluator
from ..evaluation.rule_semantics import violation_from_margin
from .comparison_state import (
    ComparisonAgentState,
    baseline_evaluation,
    candidate_evaluation,
    candidate_hfss_result,
    candidate_sparameter_result,
    evaluation_record,
    state_target_specification,
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
        target = state_target_specification(state)
        rules = target.get("rules") or self.evaluation.rules
        plan_raw = target.get("frequency_plan")
        if not rules:
            return NextAction.STOP
        plan = (
            FrequencyPlan.from_mapping(plan_raw)
            if plan_raw
            else self.evaluation.frequency_plan
        )
        candidate = DeterministicEvaluator(rules=rules, frequency_plan=plan).evaluate_sparameters(
            result,
            evaluated_stage="surrogate_gate",
            candidate_id=result.candidate_id,
        )
        if candidate.status == "INVALID":
            return NextAction.STOP
        reference = baseline_evaluation(state)
        policy = state.get("best_policy")
        if policy is not None and policy.selected_candidate_id != state["manifest"].baseline_candidate_id:
            record = evaluation_record(state, candidate_id=policy.selected_candidate_id)
            if record is not None:
                reference = record.to_result()
        if reference is None or reference.status == "INVALID":
            return NextAction.STOP

        def failed_hard_ids(evaluation):
            return {
                str(rule.get("rule_id"))
                for rule in evaluation.rule_results
                if rule.get("hard_constraint") and rule.get("status") == "FAIL"
            }

        if not failed_hard_ids(candidate).issubset(failed_hard_ids(reference)):
            return NextAction.STOP

        def rank(evaluation):
            ordered = sorted(evaluation.rule_results, key=lambda rule: str(rule.get("rule_id", "")))
            hard = [violation_from_margin(rule.get("margin_to_target")) for rule in ordered if rule.get("hard_constraint")]
            soft = [violation_from_margin(rule.get("margin_to_target")) for rule in ordered if not rule.get("hard_constraint")]
            return (
                evaluation.hard_failed_rule_count,
                max(hard, default=0.0),
                sum(hard),
                evaluation.soft_failed_rule_count,
                sum(soft),
                tuple(hard + soft),
            )

        return NextAction.RUN_HFSS if rank(candidate) < rank(reference) else NextAction.STOP

    def after_candidate_hfss(self, state: ComparisonAgentState) -> NextAction:
        result = candidate_hfss_result(state)
        if result is None or not result.success:
            return NextAction.STOP
        evaluation = candidate_evaluation(state)
        if evaluation is not None and evaluation.pass_target and evaluation.soft_failed_rule_count == 0:
            return NextAction.PASS
        return NextAction.STOP
