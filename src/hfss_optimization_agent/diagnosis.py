"""Deterministic diagnosis derived only from EvaluationResult artifacts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .core.models import EvaluationResult, EvaluationComparison

class DiagnosisStatus(StrEnum):
    NO_ISSUE = "NO_ISSUE"
    DIAGNOSED = "DIAGNOSED"
    INVALID = "INVALID"

class DiagnosisIssueType(StrEnum):
    CORE_MATCHING_POOR = "CORE_MATCHING_POOR"
    CORE_TRANSMISSION_INSUFFICIENT = "CORE_TRANSMISSION_INSUFFICIENT"
    LOWER_FREQUENCY_MARGIN_INSUFFICIENT = "LOWER_FREQUENCY_MARGIN_INSUFFICIENT"
    UPPER_FREQUENCY_MARGIN_INSUFFICIENT = "UPPER_FREQUENCY_MARGIN_INSUFFICIENT"

class BandLocation(StrEnum):
    LOW_EDGE = "LOW_EDGE"
    CENTER = "CENTER"
    HIGH_EDGE = "HIGH_EDGE"
    WHOLE_BAND = "WHOLE_BAND"
    MULTIPLE_REGIONS = "MULTIPLE_REGIONS"
    UNKNOWN = "UNKNOWN"

DIAGNOSED = DiagnosisStatus.DIAGNOSED
NO_ISSUE = DiagnosisStatus.NO_ISSUE
INVALID = DiagnosisStatus.INVALID

CORE_MATCHING_POOR = DiagnosisIssueType.CORE_MATCHING_POOR
CORE_TRANSMISSION_INSUFFICIENT = DiagnosisIssueType.CORE_TRANSMISSION_INSUFFICIENT
LOWER_FREQUENCY_MARGIN_INSUFFICIENT = DiagnosisIssueType.LOWER_FREQUENCY_MARGIN_INSUFFICIENT
UPPER_FREQUENCY_MARGIN_INSUFFICIENT = DiagnosisIssueType.UPPER_FREQUENCY_MARGIN_INSUFFICIENT

CORE_MATCHING = "CORE_MATCHING"
CORE_TRANSMISSION = "CORE_TRANSMISSION"
LOWER_FREQUENCY_MARGIN = "LOWER_FREQUENCY_MARGIN"
UPPER_FREQUENCY_MARGIN = "UPPER_FREQUENCY_MARGIN"

LOW_EDGE = BandLocation.LOW_EDGE
CENTER = BandLocation.CENTER
HIGH_EDGE = BandLocation.HIGH_EDGE
WHOLE_BAND = BandLocation.WHOLE_BAND
MULTIPLE_REGIONS = BandLocation.MULTIPLE_REGIONS
UNKNOWN = BandLocation.UNKNOWN

_TOLERANCE_GHZ = 1e-9


@dataclass(slots=True)
class DiagnosisIssue:
    issue_type: str
    source_rule_id: str | None
    parameter: str | None
    frequency_band: tuple[float, float] | None
    band_location: str
    worst_frequency: float | None
    worst_value: float | None
    margin_to_target: float | None
    violation_ranges: list[dict[str, float]] = field(default_factory=list)
    violation_bandwidth: float = 0.0
    violation_fraction: float = 0.0
    hard_constraint: bool = False
    priority: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class IssueMigration:
    issue_type: str
    rule_id: str | None
    from_location: str
    to_location: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DiagnosisResult:
    stage: str
    status: str
    primary_issue: DiagnosisIssue | None = None
    secondary_issues: list[DiagnosisIssue] = field(default_factory=list)
    issue_details: list[DiagnosisIssue] = field(default_factory=list)
    optimization_focus: list[str] = field(default_factory=list)
    resolved_issues: list[str] = field(default_factory=list)
    remaining_issues: list[str] = field(default_factory=list)
    new_issues: list[str] = field(default_factory=list)
    issue_migrations: list[IssueMigration] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DiagnosisResult":
        copied = dict(value)
        issue_keys = ("primary_issue", "secondary_issues", "issue_details")
        copied["primary_issue"] = _issue_from_dict(copied.get("primary_issue"))
        for key in issue_keys[1:]:
            copied[key] = [_issue_from_dict(item) for item in copied.get(key, [])]
        copied["issue_migrations"] = [IssueMigration(**item) for item in copied.get("issue_migrations", [])]
        return cls(**copied)


def _issue_from_dict(value: dict[str, Any] | None) -> DiagnosisIssue | None:
    if value is None:
        return None
    copied = dict(value)
    if copied.get("frequency_band") is not None:
        copied["frequency_band"] = tuple(copied["frequency_band"])
    return DiagnosisIssue(**copied)


class DiagnosisNode:
    """Pure deterministic diagnosis node; it never reads raw S-parameter data."""

    def diagnose(
        self,
        evaluation: EvaluationResult,
        *,
        stage: str,
        comparison: EvaluationComparison | None = None,
        baseline_diagnosis: DiagnosisResult | None = None,
    ) -> DiagnosisResult:
        if evaluation.status == "INVALID":
            return DiagnosisResult(stage=stage, status=INVALID, summary={"reason": evaluation.reason})
        issues = self._issues(evaluation)
        primary, secondary = self._prioritize(evaluation, issues)
        status = DIAGNOSED if issues else NO_ISSUE
        result = DiagnosisResult(
            stage=stage,
            status=status,
            primary_issue=primary,
            secondary_issues=secondary,
            issue_details=issues,
            optimization_focus=self._focus(primary, secondary),
            summary=self._summary(evaluation, primary, secondary, comparison),
        )
        if stage == "optimized" and baseline_diagnosis is not None:
            self._compare_diagnoses(baseline_diagnosis, result)
        return result

    @staticmethod
    def _issue_type(rule: dict[str, Any], evaluation: EvaluationResult) -> str | None:
        if rule.get("hard_constraint"):
            parameter = str(rule.get("parameter", "")).upper()
            if parameter == "S11":
                return CORE_MATCHING_POOR
            if parameter == "S21" and rule.get("operator") == ">=":
                return CORE_TRANSMISSION_INSUFFICIENT
            return None
        band = tuple(rule.get("frequency_band") or ())
        plan = evaluation.frequency_plan
        lower = tuple(plan.get("lower_margin_band", ()))
        upper = tuple(plan.get("upper_margin_band", ()))
        if len(band) == 2 and len(lower) == 2 and abs(float(band[0]) - lower[0]) <= _TOLERANCE_GHZ and abs(float(band[1]) - lower[1]) <= _TOLERANCE_GHZ:
            return LOWER_FREQUENCY_MARGIN_INSUFFICIENT
        if len(band) == 2 and len(upper) == 2 and abs(float(band[0]) - upper[0]) <= _TOLERANCE_GHZ and abs(float(band[1]) - upper[1]) <= _TOLERANCE_GHZ:
            return UPPER_FREQUENCY_MARGIN_INSUFFICIENT
        return None

    def _issues(self, evaluation: EvaluationResult) -> list[DiagnosisIssue]:
        issues: list[DiagnosisIssue] = []
        for rule in evaluation.rule_results:
            if rule.get("status") != "FAIL":
                continue
            issue_type = self._issue_type(rule, evaluation)
            if issue_type is None:
                continue
            band = tuple(rule.get("frequency_band") or ()) or None
            width = abs(band[1] - band[0]) if band else 0.0
            fraction = min(1.0, max(0.0, float(rule.get("violation_bandwidth", 0.0)) / width)) if width else 0.0
            issues.append(DiagnosisIssue(issue_type, rule.get("rule_id"), rule.get("parameter"), band,
                self._band_location(rule), rule.get("worst_frequency"), rule.get("worst_value"),
                rule.get("margin_to_target"), list(rule.get("violation_ranges", [])),
                float(rule.get("violation_bandwidth", 0.0)), fraction,
                bool(rule.get("hard_constraint", False)), 0))
        margin = evaluation.frequency_margin
        for key, issue_type in (("lower_margin_remaining", LOWER_FREQUENCY_MARGIN_INSUFFICIENT), ("upper_margin_remaining", UPPER_FREQUENCY_MARGIN_INSUFFICIENT)):
            if float(margin.get(key, 0.0)) <= 0.0:
                continue
            if any(issue.issue_type == issue_type for issue in issues):
                continue
            issues.append(DiagnosisIssue(issue_type, None, None, None, UNKNOWN, None, None,
                -float(margin[key]), [], 0.0, 0.0, False, 0))
        return issues

    def _prioritize(self, evaluation: EvaluationResult, issues: list[DiagnosisIssue]):
        hard = [issue for issue in issues if issue.hard_constraint]
        if hard:
            source_id = (evaluation.worst_issue or {}).get("rule_id")
            primary = next((issue for issue in hard if issue.source_rule_id == source_id), hard[0])
            rest = [issue for issue in issues if issue is not primary]
            return primary, rest
        if not issues:
            return None, []
        margin = evaluation.frequency_margin
        lower = float(margin.get("lower_margin_remaining", 0.0))
        upper = float(margin.get("upper_margin_remaining", 0.0))
        if lower > upper:
            preferred = LOWER_FREQUENCY_MARGIN_INSUFFICIENT
        elif upper > lower:
            preferred = UPPER_FREQUENCY_MARGIN_INSUFFICIENT
        else:
            source_id = (evaluation.worst_soft_issue or {}).get("rule_id")
            preferred_issue = next((issue for issue in issues if issue.source_rule_id == source_id), None)
            preferred = preferred_issue.issue_type if preferred_issue else issues[0].issue_type
        primary = next((issue for issue in issues if issue.issue_type == preferred), issues[0])
        return primary, [issue for issue in issues if issue is not primary]

    @staticmethod
    def _focus(primary, secondary):
        mapping = {CORE_MATCHING_POOR: CORE_MATCHING, CORE_TRANSMISSION_INSUFFICIENT: CORE_TRANSMISSION,
                   LOWER_FREQUENCY_MARGIN_INSUFFICIENT: LOWER_FREQUENCY_MARGIN,
                   UPPER_FREQUENCY_MARGIN_INSUFFICIENT: UPPER_FREQUENCY_MARGIN}
        result=[]
        for issue in [primary, *secondary]:
            if issue is not None and mapping[issue.issue_type] not in result:
                result.append(mapping[issue.issue_type])
        return result

    @staticmethod
    def _band_location(rule):
        ranges = list(rule.get("violation_ranges", []))
        band = tuple(rule.get("frequency_band") or ())
        if len(ranges) > 1:
            return MULTIPLE_REGIONS
        if not ranges or len(band) != 2:
            return UNKNOWN
        item = ranges[0]
        if abs(item.get("start", 0.0) - band[0]) <= _TOLERANCE_GHZ and abs(item.get("stop", 0.0) - band[1]) <= _TOLERANCE_GHZ:
            return WHOLE_BAND
        worst = rule.get("worst_frequency")
        if worst is None or band[1] == band[0]:
            return UNKNOWN
        position = (float(worst) - band[0]) / (band[1] - band[0])
        if position <= 1.0 / 3.0:
            return LOW_EDGE
        if position >= 2.0 / 3.0:
            return HIGH_EDGE
        return CENTER

    @staticmethod
    def _compare_diagnoses(baseline: DiagnosisResult, candidate: DiagnosisResult) -> None:
        def key(issue): return (issue.issue_type, issue.source_rule_id)
        before = {key(issue): issue for issue in baseline.issue_details}
        after = {key(issue): issue for issue in candidate.issue_details}
        candidate.resolved_issues = sorted({issue.issue_type for k, issue in before.items() if k not in after})
        candidate.remaining_issues = sorted({issue.issue_type for k, issue in after.items() if k in before})
        candidate.new_issues = sorted({issue.issue_type for k, issue in after.items() if k not in before})
        candidate.issue_migrations = [IssueMigration(issue.issue_type, issue.source_rule_id, before[k].band_location, issue.band_location)
                                      for k, issue in after.items() if k in before and before[k].band_location != issue.band_location and issue.issue_type not in {LOWER_FREQUENCY_MARGIN_INSUFFICIENT, UPPER_FREQUENCY_MARGIN_INSUFFICIENT}]

    @staticmethod
    def _summary(evaluation, primary, secondary, comparison):
        summary = {"status": evaluation.status, "primary_issue": primary.issue_type if primary else None,
                   "secondary_issues": [issue.issue_type for issue in secondary]}
        if comparison is not None:
            summary["lower_frequency_margin_delta"] = comparison.lower_frequency_margin_delta
            summary["upper_frequency_margin_delta"] = comparison.upper_frequency_margin_delta
            summary["improved_rules"] = [item.get("rule_id") for item in comparison.improved_rules]
            summary["degraded_rules"] = [item.get("rule_id") for item in comparison.degraded_rules]
            summary["resolved_failures"] = list(comparison.resolved_failures)
            summary["remaining_failures"] = list(comparison.remaining_failures)
            summary["new_failures"] = list(comparison.new_failures)
        return summary
