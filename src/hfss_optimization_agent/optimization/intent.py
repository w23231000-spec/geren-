"""Deterministic diagnosis-to-optimization intent and objective mapping."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from ..core.models import EvaluationResult, FrequencyPlan
from ..evaluation.rule_semantics import extremum_metric_name, violation_from_margin
from ..diagnosis import (
    CORE_MATCHING_POOR, CORE_TRANSMISSION_INSUFFICIENT,
    CORE_S11_RULE_NOT_MET, CORE_S21_RULE_NOT_MET,
    CORE_MATCHING, CORE_TRANSMISSION,
    CORE_S11_COMPLIANCE, CORE_S21_COMPLIANCE,
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
    max_hard_violation: float
    total_hard_violation: float
    soft_failed_rule_count: int
    total_soft_violation: float
    per_rule_violations: tuple[float, ...] = ()

    def key(self):
        return (
            self.invalid_flag,
            self.hard_failed_rule_count,
            self.max_hard_violation,
            self.total_hard_violation,
            self.soft_failed_rule_count,
            self.total_soft_violation,
            self.per_rule_violations,
        )


class OptimizationIntentBuilder:
    def build(self, diagnosis: DiagnosisResult) -> OptimizationIntent:
        if diagnosis.status == DIAGNOSIS_INVALID:
            return OptimizationIntent(INVALID, source_primary_issue=None, source_diagnosis_stage=diagnosis.stage)
        if diagnosis.status == NO_ISSUE:
            return OptimizationIntent(NO_ACTION, source_primary_issue=None, source_diagnosis_stage=diagnosis.stage)
        if diagnosis.status != DIAGNOSED or not diagnosis.optimization_focus:
            return OptimizationIntent(INVALID, source_primary_issue=None, source_diagnosis_stage=diagnosis.stage)
        issue_types = {issue.issue_type for issue in diagnosis.issue_details}
        core_issues = {
            CORE_MATCHING_POOR,
            CORE_TRANSMISSION_INSUFFICIENT,
            CORE_S11_RULE_NOT_MET,
            CORE_S21_RULE_NOT_MET,
        }
        mode = CORE_RECOVERY if core_issues & issue_types else MARGIN_EXPANSION
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
        protected = [str(rule.get("rule_id")) for rule in evaluation.rule_results if rule.get("hard_constraint")]
        worst_rule_id = str((evaluation.worst_issue or {}).get("rule_id", ""))
        indexed_rules = list(enumerate(evaluation.rule_results))
        indexed_rules.sort(
            key=lambda item: (
                0 if str(item[1].get("rule_id", "")) == worst_rule_id else 1,
                0 if item[1].get("hard_constraint") else 1,
                0 if item[1].get("status") == "FAIL" else 1,
                item[0],
            )
        )
        terms = []
        for priority, (_, rule) in enumerate(indexed_rules, start=1):
            parameter = str(rule.get("parameter", "")).upper()
            operator = str(rule.get("operator", ""))
            band = tuple(float(value) for value in rule.get("frequency_band", ()))
            if len(band) != 2:
                raise ValueError(f"rule {rule.get('rule_id')} has no two-point frequency band")
            terms.append(
                {
                    "priority": priority,
                    "source_rule_id": str(rule.get("rule_id")),
                    "parameter": parameter,
                    "operator": operator,
                    "threshold": float(rule.get("target", rule.get("threshold"))),
                    "frequency_band": band,
                    "hard_constraint": bool(rule.get("hard_constraint")),
                    "status": str(rule.get("status", "INVALID")),
                    "metric": extremum_metric_name(parameter=parameter, operator=operator),
                    "penalty": violation_from_margin(rule.get("margin_to_target")),
                }
            )
        return OptimizationObjective(ACTIVE, intent.mode, terms, protected, intent.to_dict())

    def rank(self, evaluation: EvaluationResult, intent: OptimizationIntent) -> ObjectiveRank:
        invalid = 0 if evaluation.status != "INVALID" else 1
        ordered = sorted(evaluation.rule_results, key=lambda rule: str(rule.get("rule_id", "")))
        hard_penalties = [
            violation_from_margin(rule.get("margin_to_target"))
            for rule in ordered
            if rule.get("hard_constraint")
        ]
        soft_penalties = [
            violation_from_margin(rule.get("margin_to_target"))
            for rule in ordered
            if not rule.get("hard_constraint")
        ]
        return ObjectiveRank(
            invalid_flag=invalid,
            hard_failed_rule_count=evaluation.hard_failed_rule_count,
            max_hard_violation=max(hard_penalties, default=0.0),
            total_hard_violation=sum(hard_penalties),
            soft_failed_rule_count=evaluation.soft_failed_rule_count,
            total_soft_violation=sum(soft_penalties),
            per_rule_violations=tuple(hard_penalties + soft_penalties),
        )
