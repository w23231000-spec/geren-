"""Deterministic diagnosis-to-optimization intent and objective mapping."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from ..core.models import EvaluationResult, FrequencyPlan
from ..diagnosis import (
    CORE_MATCHING_POOR, CORE_TRANSMISSION_INSUFFICIENT,
    CORE_MATCHING, CORE_TRANSMISSION,
    LOWER_FREQUENCY_MARGIN, UPPER_FREQUENCY_MARGIN,
    LOWER_FREQUENCY_MARGIN_INSUFFICIENT, UPPER_FREQUENCY_MARGIN_INSUFFICIENT,
    DiagnosisResult, INVALID as DIAGNOSIS_INVALID, NO_ISSUE, DIAGNOSED,
)

ACTIVE = "ACTIVE"
NO_ACTION = "NO_ACTION"
INVALID = "INVALID"
CORE_RECOVERY = "CORE_RECOVERY"
MARGIN_EXPANSION = "MARGIN_EXPANSION"


@dataclass(slots=True)
class OptimizationIntent:
    status: str
    mode: str | None = None
    primary_focus: str | None = None
    secondary_focuses: list[str] = field(default_factory=list)
    protect_core_constraints: bool = True
    source_primary_issue: str | None = None
    source_diagnosis_stage: str | None = None

    def to_dict(self): return asdict(self)


@dataclass(slots=True)
class OptimizationObjective:
    status: str
    mode: str | None = None
    priority_terms: list[dict[str, Any]] = field(default_factory=list)
    protected_constraints: list[str] = field(default_factory=list)
    source_intent: dict[str, Any] = field(default_factory=dict)

    def to_dict(self): return asdict(self)


@dataclass(frozen=True, slots=True)
class ObjectiveRank:
    invalid_flag: int
    hard_failed_rule_count: int
    primary_focus_penalty: float
    total_hard_violation: float
    secondary_focus_penalties: tuple[float, ...] = ()
    remaining_soft_penalties: tuple[float, ...] = ()

    def key(self):
        return (self.invalid_flag, self.hard_failed_rule_count, self.primary_focus_penalty,
                self.total_hard_violation, self.secondary_focus_penalties, self.remaining_soft_penalties)


class OptimizationIntentBuilder:
    def build(self, diagnosis: DiagnosisResult) -> OptimizationIntent:
        if diagnosis.status == DIAGNOSIS_INVALID:
            return OptimizationIntent(INVALID, source_primary_issue=None, source_diagnosis_stage=diagnosis.stage)
        if diagnosis.status == NO_ISSUE:
            return OptimizationIntent(NO_ACTION, source_primary_issue=None, source_diagnosis_stage=diagnosis.stage)
        if diagnosis.status != DIAGNOSED or not diagnosis.optimization_focus:
            return OptimizationIntent(INVALID, source_primary_issue=None, source_diagnosis_stage=diagnosis.stage)
        issue_types = {issue.issue_type for issue in diagnosis.issue_details}
        mode = CORE_RECOVERY if {CORE_MATCHING_POOR, CORE_TRANSMISSION_INSUFFICIENT} & issue_types else MARGIN_EXPANSION
        primary = diagnosis.optimization_focus[0]
        return OptimizationIntent(ACTIVE, mode, primary, list(diagnosis.optimization_focus[1:]), True,
                                  diagnosis.primary_issue.issue_type if diagnosis.primary_issue else None, diagnosis.stage)


class OptimizationObjectiveBuilder:
    def build(self, intent: OptimizationIntent, evaluation: EvaluationResult,
              frequency_plan: FrequencyPlan, rules: Sequence[Mapping[str, Any]] = ()) -> OptimizationObjective:
        if intent.status == INVALID:
            return OptimizationObjective(INVALID, source_intent=intent.to_dict())
        if intent.status == NO_ACTION:
            return OptimizationObjective(NO_ACTION, source_intent=intent.to_dict())
        protected = [rule.get("rule_id") for rule in evaluation.rule_results if rule.get("hard_constraint")]
        terms = [{"priority": index, "focus": focus, "metric": self._metric(focus), "penalty": self._penalty(focus, evaluation)}
                 for index, focus in enumerate([intent.primary_focus, *intent.secondary_focuses], start=1)]
        return OptimizationObjective(ACTIVE, intent.mode, terms, protected, intent.to_dict())

    @staticmethod
    def _metric(focus):
        return {CORE_MATCHING: "matching_penalty", CORE_TRANSMISSION: "transmission_penalty",
                LOWER_FREQUENCY_MARGIN: "lower_margin_penalty", UPPER_FREQUENCY_MARGIN: "upper_margin_penalty"}.get(focus, "unknown")

    @staticmethod
    def _penalty(focus, evaluation: EvaluationResult) -> float:
        rules = evaluation.rule_results
        if focus == CORE_MATCHING:
            margins = [r.get("margin_to_target") for r in rules if r.get("hard_constraint") and str(r.get("parameter", "")).upper() == "S11"]
            return max(0.0, -min(margins)) if margins else 0.0
        if focus == CORE_TRANSMISSION:
            margins = [r.get("margin_to_target") for r in rules if r.get("hard_constraint") and str(r.get("parameter", "")).upper() == "S21" and r.get("operator") == ">="]
            return max(0.0, -min(margins)) if margins else 0.0
        margin = evaluation.frequency_margin
        return max(0.0, float(margin.get("lower_margin_remaining", 0.0 if focus == LOWER_FREQUENCY_MARGIN else margin.get("upper_margin_remaining", 0.0)))) if focus == LOWER_FREQUENCY_MARGIN else max(0.0, float(margin.get("upper_margin_remaining", 0.0)))

    def rank(self, evaluation: EvaluationResult, intent: OptimizationIntent) -> ObjectiveRank:
        invalid = 0 if evaluation.status != "INVALID" else 1
        hard = evaluation.hard_failed_rule_count
        primary = self._penalty(intent.primary_focus, evaluation) if intent.primary_focus else 0.0
        total = sum(max(0.0, -float(rule.get("margin_to_target", 0.0))) for rule in evaluation.rule_results if rule.get("hard_constraint"))
        secondary = tuple(self._penalty(focus, evaluation) for focus in intent.secondary_focuses)
        soft = tuple(max(0.0, -float(rule.get("margin_to_target", 0.0))) for rule in evaluation.rule_results if not rule.get("hard_constraint") and rule.get("status") == "FAIL")
        return ObjectiveRank(invalid, hard, primary, total, secondary, soft)
