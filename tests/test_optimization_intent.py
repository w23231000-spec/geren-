from hfss_optimization_agent.core.models import EvaluationResult, FrequencyPlan
from hfss_optimization_agent.diagnosis import (
    DiagnosisIssue, DiagnosisResult, DIAGNOSED, NO_ISSUE, INVALID,
    CORE_MATCHING_POOR, CORE_TRANSMISSION_INSUFFICIENT,
    LOWER_FREQUENCY_MARGIN_INSUFFICIENT, LOWER_FREQUENCY_MARGIN,
    CORE_MATCHING, CORE_TRANSMISSION,
)
from hfss_optimization_agent.optimization.intent import (
    OptimizationIntentBuilder, OptimizationObjectiveBuilder,
    ACTIVE, NO_ACTION, INVALID as INTENT_INVALID, CORE_RECOVERY, MARGIN_EXPANSION,
)

PLAN = FrequencyPlan()

def evaluation(*rules, status="FAIL", hard_failed=1, lower=0.0, upper=0.0):
    return EvaluationResult(
        "c", False, status == "PASS", {}, {}, {}, 0.0, status, "initial", status,
        [dict(rule) for rule in rules], 0, len(rules), rules[0] if rules else None, -1.0 if rules else None, {},
        [{k: rule.get(k) for k in ("rule_id", "parameter", "frequency_band", "operator", "threshold", "hard_constraint")} for rule in rules],
        hard_failed, sum(not r.get("hard_constraint") and r.get("status") == "FAIL" for r in rules), None,
        {"lower_margin_remaining": lower, "upper_margin_remaining": upper}, PLAN.to_dict(),
    )

def issue(issue_type, rule_id="r"):
    return DiagnosisIssue(issue_type, rule_id, "S11", (6.0, 18.0), "CENTER", 12.0, -14.0, -1.0, [], 0.0, 0.0, True, 0)

def diagnosis(status=DIAGNOSED, issues=None, focus=None):
    issues = issues or []
    return DiagnosisResult("initial", status, issues[0] if issues else None, issues[1:], issues, focus or [], summary={})

def test_intent_status_and_modes():
    builder = OptimizationIntentBuilder()
    assert builder.build(diagnosis(INVALID)).status == INTENT_INVALID
    assert builder.build(diagnosis(NO_ISSUE)).status == NO_ACTION
    core = builder.build(diagnosis(DIAGNOSED, [issue(CORE_MATCHING_POOR)], [CORE_MATCHING]))
    assert core.status == ACTIVE and core.mode == CORE_RECOVERY
    margin = builder.build(diagnosis(DIAGNOSED, [issue(LOWER_FREQUENCY_MARGIN_INSUFFICIENT)], [LOWER_FREQUENCY_MARGIN]))
    assert margin.mode == MARGIN_EXPANSION

def test_intent_reuses_diagnosis_focus_order_and_protects_core():
    intent = OptimizationIntentBuilder().build(diagnosis(DIAGNOSED, [issue(CORE_MATCHING_POOR), issue(CORE_TRANSMISSION_INSUFFICIENT)], [CORE_MATCHING, CORE_TRANSMISSION]))
    assert intent.primary_focus == CORE_MATCHING
    assert intent.secondary_focuses == [CORE_TRANSMISSION]
    assert intent.protect_core_constraints is True

def test_objective_penalty_mapping_and_protected_constraints():
    rules = (
        {"rule_id": "s11", "parameter": "S11", "operator": "<=", "threshold": -15, "status": "FAIL", "margin_to_target": -2.0, "hard_constraint": True},
        {"rule_id": "s21", "parameter": "S21", "operator": ">=", "threshold": -2, "status": "FAIL", "margin_to_target": -1.0, "hard_constraint": True},
    )
    ev = evaluation(*rules)
    intent = OptimizationIntentBuilder().build(diagnosis(DIAGNOSED, [issue(CORE_MATCHING_POOR)], [CORE_MATCHING]))
    obj = OptimizationObjectiveBuilder().build(intent, ev, PLAN, rules)
    assert obj.status == ACTIVE
    assert obj.priority_terms[0]["metric"] == "matching_penalty"
    assert obj.priority_terms[0]["penalty"] == 2.0
    assert obj.protected_constraints == ["s11", "s21"]

def test_objective_rank_order_is_deterministic_and_core_protected():
    builder = OptimizationObjectiveBuilder()
    intent = OptimizationIntentBuilder().build(diagnosis(DIAGNOSED, [issue(CORE_MATCHING_POOR)], [CORE_MATCHING]))
    better = evaluation({"rule_id": "a", "parameter": "S11", "operator": "<=", "status": "FAIL", "margin_to_target": -1.0, "hard_constraint": True})
    worse = evaluation({"rule_id": "a", "parameter": "S11", "operator": "<=", "status": "FAIL", "margin_to_target": -2.0, "hard_constraint": True})
    assert builder.rank(better, intent).key() < builder.rank(worse, intent).key()
    invalid = EvaluationResult("x", False, False, {}, {}, {}, 0, "bad", status="INVALID")
    assert builder.rank(better, intent).key() < builder.rank(invalid, intent).key()

def test_margin_objective_uses_remaining_distance_without_weighted_score():
    rules = ({"rule_id": "low", "parameter": "S11", "operator": "<=", "status": "FAIL", "margin_to_target": -0.2, "hard_constraint": False},)
    ev = evaluation(*rules, hard_failed=0, lower=0.37, status="PASS")
    intent = OptimizationIntentBuilder().build(diagnosis(DIAGNOSED, [issue(LOWER_FREQUENCY_MARGIN_INSUFFICIENT, "low")], [LOWER_FREQUENCY_MARGIN]))
    obj = OptimizationObjectiveBuilder().build(intent, ev, PLAN, rules)
    assert obj.priority_terms[0]["penalty"] == 0.37
    assert all("weight" not in term for term in obj.priority_terms)
