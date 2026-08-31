"""Comparison of two immutable EvaluationResult objects."""
from collections.abc import Mapping
from ..core.models import EvaluationComparison, EvaluationResult
from .rule_semantics import violation_from_margin

def metric_deltas(baseline: Mapping[str, float], current: Mapping[str, float]) -> dict[str, float]:
    return {k: float(current[k])-float(baseline[k]) for k in sorted(set(baseline)&set(current))}

class EvaluationComparator:
    def __init__(self, tolerance: float = 1e-9): self.tolerance=tolerance
    def compare(self, baseline: EvaluationResult, candidate: EvaluationResult) -> EvaluationComparison:
        if baseline.status=="INVALID" or candidate.status=="INVALID": return EvaluationComparison(classification="INVALID", reason="Baseline or Candidate EvaluationResult is INVALID.")
        if not self._same_rules(baseline, candidate):
            return EvaluationComparison(classification="INVALID", reason="Baseline and Candidate use different S-parameter evaluation rules.")
        if baseline.frequency_plan != candidate.frequency_plan:
            return EvaluationComparison(classification="INVALID", reason="Baseline and Candidate use different FrequencyPlan values.")
        b={r["rule_id"]:r for r in baseline.rule_results}; c={r["rule_id"]:r for r in candidate.rule_results}; improved=[]; degraded=[]; unchanged=[]; resolved=[]; remaining=[]; new=[]
        for rid in sorted(set(b)&set(c)):
            br,cr=b[rid],c[rid]; bm,cm=br.get("margin_to_target"),cr.get("margin_to_target")
            if bm is None or cm is None: continue
            delta=cm-bm; item={"rule_id":rid,"baseline_status":br["status"],"candidate_status":cr["status"],"baseline_margin":bm,"candidate_margin":cm,"margin_delta":delta}
            if delta>self.tolerance: improved.append(item)
            elif delta< -self.tolerance: degraded.append(item)
            else: unchanged.append(item)
            if br["status"]=="FAIL" and cr["status"]=="PASS": resolved.append(rid)
            elif cr["status"]=="FAIL":
                remaining.append(rid)
                if br["status"]=="PASS": new.append(rid)
        def rank(result: EvaluationResult):
            ordered = sorted(result.rule_results, key=lambda rule: str(rule.get("rule_id", "")))
            hard = [violation_from_margin(rule.get("margin_to_target")) for rule in ordered if rule.get("hard_constraint")]
            soft = [violation_from_margin(rule.get("margin_to_target")) for rule in ordered if not rule.get("hard_constraint")]
            return (
                result.hard_failed_rule_count,
                max(hard, default=0.0),
                sum(hard),
                result.soft_failed_rule_count,
                sum(soft),
                tuple(hard + soft),
            )
        baseline_rank = rank(baseline)
        candidate_rank = rank(candidate)
        all_rules_pass = candidate.pass_target and candidate.soft_failed_rule_count == 0
        if all_rules_pass: classification="FULLY_ACHIEVED"
        elif candidate.pass_target: classification="CORE_ACHIEVED_MARGIN_INCOMPLETE"
        elif improved and degraded: classification="MIXED"
        elif improved: classification="IMPROVED"
        elif degraded or new: classification="DEGRADED"
        else: classification="NO_MEANINGFUL_CHANGE"
        promotion_eligible = candidate_rank < baseline_rank
        promotion_reason = (
            "Candidate satisfies every configured hard and soft rule."
            if classification == "FULLY_ACHIEVED"
            else "Candidate has a better deterministic hard-first, soft-second rule rank."
            if promotion_eligible
            else "Candidate is not eligible for automatic Best promotion."
        )
        lower_delta = candidate.frequency_margin.get("lower_frequency_margin", 0.0) - baseline.frequency_margin.get("lower_frequency_margin", 0.0)
        upper_delta = candidate.frequency_margin.get("upper_frequency_margin", 0.0) - baseline.frequency_margin.get("upper_frequency_margin", 0.0)
        return EvaluationComparison(
            improved, degraded, unchanged, resolved, remaining, new,
            {"baseline": baseline.worst_issue, "candidate": candidate.worst_issue}, classification,
            None, lower_delta, upper_delta, baseline.frequency_margin,
            candidate.frequency_margin,
            {"lower_frequency_margin_delta": lower_delta, "upper_frequency_margin_delta": upper_delta},
            promotion_eligible, promotion_reason,
        )

    @staticmethod
    def _same_rules(baseline: EvaluationResult, candidate: EvaluationResult) -> bool:
        fields = ("rule_id", "parameter", "frequency_band", "operator", "threshold", "hard_constraint")
        def signature(result):
            rules = result.rules or [
                {key: rule.get(key) for key in fields}
                for rule in result.rule_results
            ]
            return sorted(tuple(rule.get(key) for key in fields) for rule in rules)
        return signature(baseline) == signature(candidate)
