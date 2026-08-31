from hfss_optimization_agent.core.models import EvaluationResult, EvaluationComparison
from hfss_optimization_agent.diagnosis import (
    DiagnosisNode, DIAGNOSED, NO_ISSUE, INVALID,
    CORE_MATCHING_POOR, CORE_TRANSMISSION_INSUFFICIENT,
    LOWER_FREQUENCY_MARGIN_INSUFFICIENT, UPPER_FREQUENCY_MARGIN_INSUFFICIENT,
    LOW_EDGE, CENTER, HIGH_EDGE, WHOLE_BAND, MULTIPLE_REGIONS,
)

PLAN = {"core_band": (6.0, 18.0), "lower_margin_band": (5.0, 6.0), "upper_margin_band": (18.0, 19.0)}

def result(rules=(), *, status="PASS", hard_failed=0, soft_failed=0, worst=None, soft_worst=None, lower=0.0, upper=0.0):
    return EvaluationResult(
        candidate_id="c", improved=False, pass_target=status == "PASS", baseline_metrics={}, current_metrics={},
        delta_metrics={}, score=0.0, reason=status, evaluated_stage="initial", status=status,
        rule_results=list(rules), passed_rule_count=sum(r.get("status") == "PASS" for r in rules),
        failed_rule_count=sum(r.get("status") == "FAIL" for r in rules), worst_issue=worst,
        worst_margin=worst.get("margin_to_target") if worst else None,
        data_quality={}, rules=[{k: r.get(k) for k in ("rule_id", "parameter", "frequency_band", "operator", "threshold", "hard_constraint")} for r in rules],
        hard_failed_rule_count=hard_failed, soft_failed_rule_count=soft_failed, worst_soft_issue=soft_worst,
        frequency_margin={"lower_margin_remaining": lower, "upper_margin_remaining": upper}, frequency_plan=PLAN,
    )

def rule(rule_id, parameter="S11", band=(6.0, 18.0), *, hard=True, status="FAIL", worst_frequency=17.5, margin=-1.0, ranges=None, bandwidth=1.0, operator="<="):
    return {"rule_id": rule_id, "parameter": parameter, "frequency_band": band, "operator": operator, "threshold": -15.0,
            "status": status, "worst_value": -14.0, "worst_frequency": worst_frequency, "margin_to_target": margin,
            "violation_ranges": ranges if ranges is not None else [{"start": band[0], "stop": band[1]}],
            "violation_bandwidth": bandwidth, "hard_constraint": hard}

def test_invalid_and_no_issue_statuses():
    assert DiagnosisNode().diagnose(result(status="INVALID"), stage="initial").status == INVALID
    assert DiagnosisNode().diagnose(result(), stage="initial").status == NO_ISSUE

def test_core_and_margin_issue_priority_and_focus():
    core = rule("core_s11", worst_frequency=17.5, margin=-5.2)
    soft = rule("low_s11", band=(5.0, 6.0), hard=False, worst_frequency=5.5, margin=-1.0)
    evaluation = result([core, soft], status="FAIL", hard_failed=1, soft_failed=1, worst=core, soft_worst=soft, lower=0.4)
    diagnosis = DiagnosisNode().diagnose(evaluation, stage="initial")
    assert diagnosis.status == DIAGNOSED
    assert diagnosis.primary_issue.issue_type == CORE_MATCHING_POOR
    assert diagnosis.secondary_issues[0].issue_type == LOWER_FREQUENCY_MARGIN_INSUFFICIENT
    assert diagnosis.optimization_focus[0] == "CORE_MATCHING"

def test_transmission_and_margin_primary_selection():
    s21 = rule("core_s21", parameter="S21", operator=">=", margin=-2.0)
    evaluation = result([s21], status="FAIL", hard_failed=1, worst=s21)
    assert DiagnosisNode().diagnose(evaluation, stage="initial").primary_issue.issue_type == CORE_TRANSMISSION_INSUFFICIENT
    low = result([rule("low", band=(5.0, 6.0), hard=False)], soft_failed=1, soft_worst=rule("low", band=(5.0, 6.0), hard=False), lower=0.8, upper=0.2)
    assert DiagnosisNode().diagnose(low, stage="initial").primary_issue.issue_type == LOWER_FREQUENCY_MARGIN_INSUFFICIENT
    high = result([rule("high", band=(18.0, 19.0), hard=False)], soft_failed=1, soft_worst=rule("high", band=(18.0, 19.0), hard=False), lower=0.2, upper=0.8)
    assert DiagnosisNode().diagnose(high, stage="initial").primary_issue.issue_type == UPPER_FREQUENCY_MARGIN_INSUFFICIENT

def test_band_locations_and_fraction():
    node = DiagnosisNode()
    def diagnose(r):
        return node.diagnose(result([r], status="FAIL", hard_failed=1, worst=r), stage="initial").primary_issue
    assert diagnose(rule("low", worst_frequency=6.2, ranges=[{"start": 6.0, "stop": 7.0}], bandwidth=1.0)).band_location == LOW_EDGE
    assert diagnose(rule("center", worst_frequency=12.0, ranges=[{"start": 10.0, "stop": 13.0}], bandwidth=3.0)).band_location == CENTER
    assert diagnose(rule("high", worst_frequency=17.0, ranges=[{"start": 16.0, "stop": 17.5}], bandwidth=1.5)).band_location == HIGH_EDGE
    assert diagnose(rule("whole", ranges=[{"start": 6.0, "stop": 18.0}], bandwidth=12.0)).band_location == WHOLE_BAND
    issue = diagnose(rule("multi", ranges=[{"start": 6.0, "stop": 7.0}, {"start": 15.0, "stop": 16.0}], bandwidth=2.0))
    assert issue.band_location == MULTIPLE_REGIONS and issue.violation_fraction == 2.0 / 12.0

def test_optimized_resolved_remaining_new_and_migration():
    before_issue = rule("core", worst_frequency=6.5, ranges=[{"start": 6.0, "stop": 8.0}], bandwidth=2.0)
    baseline = DiagnosisNode().diagnose(result([before_issue], status="FAIL", hard_failed=1, worst=before_issue), stage="initial")
    after_issue = rule("core", worst_frequency=17.0, ranges=[{"start": 16.0, "stop": 18.0}], bandwidth=2.0)
    candidate = DiagnosisNode().diagnose(result([after_issue], status="FAIL", hard_failed=1, worst=after_issue), stage="optimized", baseline_diagnosis=baseline, comparison=EvaluationComparison())
    assert candidate.remaining_issues == [CORE_MATCHING_POOR]
    assert candidate.issue_migrations[0].from_location == LOW_EDGE
    assert candidate.issue_migrations[0].to_location == HIGH_EDGE
    resolved = DiagnosisNode().diagnose(result(), stage="optimized", baseline_diagnosis=baseline, comparison=EvaluationComparison())
    assert resolved.resolved_issues == [CORE_MATCHING_POOR]
    new_rule = rule("new", parameter="S21", operator=">=")
    new_candidate = DiagnosisNode().diagnose(result([new_rule], status="FAIL", hard_failed=1, worst=new_rule), stage="optimized", baseline_diagnosis=baseline, comparison=EvaluationComparison())
    assert new_candidate.new_issues == [CORE_TRANSMISSION_INSUFFICIENT]

def test_soft_margin_delta_is_reflected_in_optimized_summary():
    comparison = EvaluationComparison(lower_frequency_margin_delta=0.27, upper_frequency_margin_delta=-0.1)
    baseline = DiagnosisNode().diagnose(result(), stage="initial")
    candidate = DiagnosisNode().diagnose(result(), stage="optimized", baseline_diagnosis=baseline, comparison=comparison)
    assert candidate.summary["lower_frequency_margin_delta"] == 0.27
    assert candidate.summary["upper_frequency_margin_delta"] == -0.1

def test_diagnosis_digest_regression_uses_serialized_diagnosis():
    import inspect

    from hfss_optimization_agent.agent.comparison_nodes import ComparisonWorkflowNodes
    from hfss_optimization_agent.domain.contracts import canonical_digest

    core = rule(
        "digest_regression_core_s21",
        parameter="S21",
        operator="<=",
        margin=-5.0,
    )
    evaluation = result(
        [core],
        status="FAIL",
        hard_failed=1,
        worst=core,
    )

    diagnosis = DiagnosisNode().diagnose(
        evaluation,
        stage="initial",
    )

    # DiagnosisResult intentionally reuses the same issue object as
    # primary_issue and issue_details[0].
    assert diagnosis.primary_issue is diagnosis.issue_details[0]

    # The serialized representation must remain canonical-digest safe.
    digest = canonical_digest(diagnosis.to_dict())
    assert len(digest) == 64

    # Lock the production OptimizerRequest construction against regression.
    source = inspect.getsource(ComparisonWorkflowNodes.run_optimizer)
    assert "canonical_digest(diagnosis.to_dict())" in source
