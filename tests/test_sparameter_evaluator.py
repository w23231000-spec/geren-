from hfss_optimization_agent.evaluation import EvaluationComparator, DeterministicEvaluator, SParameterRule
from hfss_optimization_agent.core.models import FrequencyPlan

RULES = [
    SParameterRule("s11_pb", "S11", (1.5, 2.5), "<=", -15),
    SParameterRule("s21_pb", "S21", (1.5, 2.0), ">=", -2),
    SParameterRule("s21_sb", "S21", (3.0, 4.0), "<=", -20),
]

def data(s11, s21, freq=(1.0, 2.0, 3.0, 4.0)):
    return {"frequency": list(freq), "S11_dB": list(s11), "S21_dB": list(s21), "frequency_unit": "GHz"}

def test_pass_and_margin_directions_and_interpolation():
    ev = DeterministicEvaluator(rules=RULES)
    result = ev.evaluate_sparameters(data([-20, -20, -20, -20], [-1, -1, -25, -25]), candidate_id="c")
    assert result.status == "PASS"
    assert result.rule_results[0]["margin_to_target"] > 0
    assert result.rule_results[1]["margin_to_target"] > 0

def test_fail_worst_point_and_multiple_violation_ranges():
    ev = DeterministicEvaluator(rules=[SParameterRule("x", "S11", (1, 5), "<=", -15)])
    result = ev.evaluate_sparameters(data([-10, -20, -9, -20], [-1]*4, (1, 2, 3, 5)), candidate_id="c")
    rule = result.rule_results[0]
    assert result.status == "FAIL" and rule["worst_frequency"] == 3
    assert len(rule["violation_ranges"]) == 2

def test_invalid_empty_missing_and_range():
    ev = DeterministicEvaluator(rules=RULES)
    assert ev.evaluate_sparameters({}, candidate_id="c").status == "INVALID"
    assert ev.evaluate_sparameters({"frequency": [1, 2], "S11_dB": [-20, -20]}, candidate_id="c").status == "INVALID"
    assert ev.evaluate_sparameters(data([-20]*4, [-1]*4, (2, 3, 4, 5)), candidate_id="c").status == "INVALID"

def test_comparator_classifications():
    ev = DeterministicEvaluator(rules=[SParameterRule("x", "S11", (1, 2), "<=", -15)])
    baseline = ev.evaluate_sparameters(data([-10, -10], [-1, -1], (1, 2)), candidate_id="b")
    candidate = ev.evaluate_sparameters(data([-20, -20], [-1, -1], (1, 2)), candidate_id="c")
    comparison = EvaluationComparator().compare(baseline, candidate)
    assert comparison.classification == "FULLY_ACHIEVED"
    assert comparison.resolved_failures == ["x"]

def test_no_rules_is_invalid_and_never_score_fallback():
    result = DeterministicEvaluator().evaluate_sparameters(
        data([-20, -20], [-1, -1], (1, 2)), candidate_id="c"
    )
    assert result.status == "INVALID"
    assert "No S-parameter evaluation rules configured" in result.reason

def test_crossing_boundaries_and_interpolated_bandwidth():
    ev = DeterministicEvaluator(rules=[SParameterRule("x", "S11", (3, 3.01), "<=", -15)])
    start = ev.evaluate_sparameters(data([-16, -14], [-1, -1], (3, 3.01)), candidate_id="start")
    stop = ev.evaluate_sparameters(data([-14, -16], [-1, -1], (3, 3.01)), candidate_id="stop")
    assert start.rule_results[0]["violation_ranges"] == [{"start": 3.005, "stop": 3.01}]
    assert stop.rule_results[0]["violation_ranges"] == [{"start": 3.0, "stop": 3.005}]
    assert abs(start.rule_results[0]["violation_bandwidth"] - 0.005) < 1e-12

def test_comparator_rejects_rule_definition_mismatch():
    baseline = DeterministicEvaluator(rules=[SParameterRule("x", "S11", (1, 2), "<=", -15)]).evaluate_sparameters(
        data([-10, -10], [-1, -1], (1, 2)), candidate_id="b"
    )
    for changed in (
        SParameterRule("x", "S11", (1, 2), "<=", -14),
        SParameterRule("x", "S11", (1.1, 2), "<=", -15),
        SParameterRule("x", "S11", (1, 2), ">=", -15),
    ):
        candidate = DeterministicEvaluator(rules=[changed]).evaluate_sparameters(
            data([-20, -20], [-1, -1], (1, 2)), candidate_id="c"
        )
        comparison = EvaluationComparator().compare(baseline, candidate)
        assert comparison.classification == "INVALID"
        assert comparison.improved_rules == []
        assert comparison.reason

def test_worst_issue_is_most_negative_hard_margin_only():
    rules = [
        SParameterRule("soft", "S11", (1, 2), "<=", -15, False),
        SParameterRule("hard_a", "S21", (1, 2), ">=", -2),
        SParameterRule("hard_b", "S11", (1, 2), "<=", -15),
    ]
    result = DeterministicEvaluator(rules=rules).evaluate_sparameters(
        data([-8, -8], [-4, -4], (1, 2)), candidate_id="c"
    )
    assert result.worst_issue["rule_id"] == "hard_b"
    passed = DeterministicEvaluator(rules=[SParameterRule("x", "S11", (1, 2), "<=", -15)]).evaluate_sparameters(
        data([-20, -20], [-1, -1], (1, 2)), candidate_id="p"
    )
    assert passed.worst_issue is None

def test_classification_uses_one_nanosecond_tolerance():
    rule = SParameterRule("x", "S11", (1, 2), "<=", -15)
    ev = DeterministicEvaluator(rules=[rule])
    baseline = ev.evaluate_sparameters(data([-10, -10], [-1, -1], (1, 2)), candidate_id="b")
    improved = ev.evaluate_sparameters(data([-12, -12], [-1, -1], (1, 2)), candidate_id="i")
    degraded = ev.evaluate_sparameters(data([-9, -9], [-1, -1], (1, 2)), candidate_id="d")
    unchanged = ev.evaluate_sparameters(data([-10.0000000005, -10.0000000005], [-1, -1], (1, 2)), candidate_id="u")
    assert EvaluationComparator().compare(baseline, improved).classification == "IMPROVED"
    assert EvaluationComparator().compare(baseline, degraded).classification == "DEGRADED"
    assert EvaluationComparator().compare(baseline, unchanged).classification == "NO_MEANINGFUL_CHANGE"

def test_improved_and_mixed_classifications():
    rules = [SParameterRule("a", "S11", (1, 2), "<=", -15), SParameterRule("b", "S21", (1, 2), ">=", -2)]
    ev = DeterministicEvaluator(rules=rules)
    baseline = ev.evaluate_sparameters(data([-10, -10], [-4, -4], (1, 2)), candidate_id="b")
    improved = ev.evaluate_sparameters(data([-12, -12], [-4, -4], (1, 2)), candidate_id="i")
    mixed = ev.evaluate_sparameters(data([-12, -12], [-5, -5], (1, 2)), candidate_id="m")
    assert EvaluationComparator().compare(baseline, improved).classification == "IMPROVED"
    assert EvaluationComparator().compare(baseline, mixed).classification == "MIXED"

def test_core_hard_and_side_soft_rules_and_frequency_margins():
    rules = [
        SParameterRule("core_s11", "S11", (6, 18), "<=", -15, True),
        SParameterRule("core_s21", "S21", (6, 18), ">=", -2, True),
        SParameterRule("low_s11", "S11", (5, 6), "<=", -15, False),
        SParameterRule("low_s21", "S21", (5, 6), ">=", -2, False),
        SParameterRule("high_s11", "S11", (18, 19), "<=", -15, False),
        SParameterRule("high_s21", "S21", (18, 19), ">=", -2, False),
    ]
    values = data([-10, -16, -16, -16, -14, -14], [-1, -1, -1, -1, -1, -1], (5, 5.5, 6, 18, 18.5, 19))
    result = DeterministicEvaluator(rules=rules).evaluate_sparameters(values, candidate_id="c")
    assert result.status == "PASS"
    assert result.hard_failed_rule_count == 0
    assert result.soft_failed_rule_count == 2
    assert result.worst_issue is None
    assert result.worst_soft_issue["rule_id"] == "low_s11"
    margin = result.frequency_margin
    assert abs(margin["achieved_lower_edge"] - 5.4166666667) < 1e-9
    assert abs(margin["lower_frequency_margin"] - (6 - margin["achieved_lower_edge"])) < 1e-12
    assert abs(margin["lower_margin_remaining"] - (1 - margin["lower_frequency_margin"])) < 1e-12
    assert abs(margin["achieved_upper_edge"] - 18.25) < 1e-9
    assert abs(margin["upper_frequency_margin"] - 0.25) < 1e-12
    assert abs(margin["upper_margin_remaining"] - 0.75) < 1e-12

def test_frequency_margin_requires_all_related_rules_and_is_continuous():
    rules = [
        SParameterRule("low_s11", "S11", (5, 6), "<=", -15, False),
        SParameterRule("low_s21", "S21", (5, 6), ">=", -2, False),
    ]
    result = DeterministicEvaluator(rules=rules).evaluate_sparameters(
        data([-16, -16, -16, -16, -16], [-1, -1, -3, -1, -1], (5, 5.3, 5.5, 5.7, 6)), candidate_id="c"
    )
    # 5.7→5.5 is the first continuous failure; the later PASS at 5.3 is ignored.
    assert result.frequency_margin["achieved_lower_edge"] > 5.5
    assert result.frequency_margin["achieved_lower_edge"] < 5.7

def test_frequency_margin_comparison_includes_signed_deltas_and_soft_changes():
    rules = [SParameterRule("low", "S11", (5, 6), "<=", -15, False)]
    ev = DeterministicEvaluator(rules=rules)
    baseline = ev.evaluate_sparameters(data([-10, -16], [-1, -1], (5, 6)), candidate_id="b")
    candidate = ev.evaluate_sparameters(data([-12, -16], [-1, -1], (5, 6)), candidate_id="c")
    comparison = EvaluationComparator().compare(baseline, candidate)
    assert comparison.lower_frequency_margin_delta > 0
    assert comparison.frequency_margin_delta["lower_frequency_margin_delta"] == comparison.lower_frequency_margin_delta
    assert comparison.improved_rules

def test_frequency_plan_validation_and_rule_alignment():
    valid = FrequencyPlan()
    rules = [SParameterRule("core", "S11", (6, 18), "<=", -15, True), SParameterRule("low", "S11", (5, 6), "<=", -15, False), SParameterRule("high", "S11", (18, 19), "<=", -15, False)]
    assert valid.is_valid
    assert DeterministicEvaluator(rules=rules, frequency_plan=valid).evaluate_sparameters(
        data([-20, -20, -20, -20, -20], [-1] * 5, (5, 6, 10, 18, 19)), candidate_id="c"
    ).status == "PASS"
    invalid_plan = FrequencyPlan((6, 18), (5, 5.8), (18, 19))
    assert DeterministicEvaluator(rules=rules, frequency_plan=invalid_plan).evaluate_sparameters(
        data([-20, -20, -20, -20], [-1] * 4), candidate_id="c"
    ).status == "INVALID"
    mismatched = [SParameterRule("core", "S11", (6.2, 18), "<=", -15, True)]
    assert DeterministicEvaluator(rules=mismatched, frequency_plan=valid).evaluate_sparameters(
        data([-20, -20, -20, -20], [-1] * 4, (6.2, 10, 18, 19)), candidate_id="c"
    ).status == "INVALID"

def test_non_one_ghz_frequency_plan_drives_margin_targets_and_comparator_plan_check():
    plan = FrequencyPlan((6, 18), (5.5, 6), (18, 18.5))
    rules = [SParameterRule("core", "S11", (6, 18), "<=", -15, True), SParameterRule("low", "S11", (5.5, 6), "<=", -15, False), SParameterRule("high", "S11", (18, 18.5), "<=", -15, False)]
    ev = DeterministicEvaluator(rules=rules, frequency_plan=plan)
    values = data([-20, -20, -20, -20, -20, -20], [-1] * 6, (5.5, 6, 10, 18, 18.5, 19))
    baseline = ev.evaluate_sparameters(values, candidate_id="b")
    candidate = ev.evaluate_sparameters(values, candidate_id="c")
    assert baseline.frequency_margin["lower_margin_target"] == 0.5
    assert baseline.frequency_margin["upper_margin_target"] == 0.5
    assert baseline.frequency_plan["core_band"] == (6.0, 18.0)
    assert EvaluationComparator().compare(baseline, candidate).classification == "FULLY_ACHIEVED"
    different = DeterministicEvaluator(rules=rules, frequency_plan=FrequencyPlan((6, 18), (5, 6), (18, 19))).evaluate_sparameters(values, candidate_id="d")
    assert EvaluationComparator().compare(baseline, different).classification == "INVALID"
