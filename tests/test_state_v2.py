"""Alias-free State V2 schema and semantic validation tests."""

import pytest

from hfss_optimization_agent.agent.comparison_state import (
    ComparisonAgentState,
    append_candidate_snapshots,
    comparison_state_from_dict,
    comparison_state_to_dict,
    create_comparison_state,
    validate_comparison_state,
)
from hfss_optimization_agent.core.models import (
    CandidateParameters,
    EvaluationComparison,
    EvaluationResult,
    HFSSResult,
)
from hfss_optimization_agent.domain.contracts import (
    BestPolicy,
    CandidateSnapshot,
    ComparisonRecord,
    EvaluationRecord,
)
from hfss_optimization_agent.parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
)



def evaluation(candidate_id: str, stage: str, *, status: str) -> EvaluationResult:
    rule = {
        "rule_id": "core-s11",
        "parameter": "S11",
        "frequency_band": (1.5, 2.5),
        "operator": "<=",
        "threshold": -12.0,
        "hard_constraint": True,
        "status": "PASS" if status == "PASS" else "FAIL",
        "margin_to_target": 1.0 if status == "PASS" else -1.0,
    }
    return EvaluationResult(
        candidate_id,
        False,
        status == "PASS",
        {},
        {},
        {},
        0.0,
        status,
        evaluated_stage=stage,
        status=status,
        rule_results=[rule],
        rules=[{key: rule[key] for key in (
            "rule_id", "parameter", "frequency_band", "operator", "threshold", "hard_constraint"
        )}],
        frequency_plan={
            "core_band": (1.5, 2.5),
            "lower_margin_band": (1.0, 1.5),
            "upper_margin_band": (2.5, 3.0),
            "tolerance_ghz": 1e-9,
        },
    )


def state_v2():
    return create_comparison_state(
        task_id="state-v2",
        baseline_parameters=supplied_baseline_candidate(),
        target_specification={"minimum_score": -1.0},
        evaluation_contract_id="offline-evaluation-v1",
        comparison_context_id="context-v2",
        run_id="run-v2",
        created_at="2026-08-21T08:00:00+00:00",
    )


def test_minimal_state_v2_round_trip_is_semantically_identical_and_alias_free():
    state = state_v2()
    payload = comparison_state_to_dict(state)
    restored = comparison_state_from_dict(payload)
    assert restored == state
    assert set(payload) == set(ComparisonAgentState.__required_keys__)
    for removed_v1_fact in (
        "task_id",
        "target_specification",
        "baseline_parameters",
        "current_candidate",
        "best_candidate",
        "best_hfss_result",
        "best_score",
        "evaluation_result",
        "evaluation_history",
        "hfss_history",
        "sparameter_history",
        "run_metadata",
        "next_action",
    ):
        assert removed_v1_fact not in payload


def test_state_rejects_candidate_snapshot_from_wrong_context():
    state = state_v2()
    wrong = CandidateSnapshot.from_candidate(
        CandidateParameters("candidate", 1, dict(supplied_baseline_candidate().values)),
        context_id="wrong-context",
        source="optimizer",
        parent_candidate_id="baseline",
    )
    state["candidates"] = (*state["candidates"], wrong)
    with pytest.raises(ValueError, match="wrong comparison context"):
        validate_comparison_state(state)


def test_state_rejects_comparison_with_wrong_candidate_identity():
    state = state_v2()
    candidate = CandidateParameters(
        "candidate", 1, dict(supplied_baseline_candidate().values)
    )
    state["candidates"] = append_candidate_snapshots(
        state,
        [candidate],
        source="optimizer",
        parent_candidate_id="baseline",
    )
    baseline_record = EvaluationRecord.from_result(
        evaluation("baseline", "initial", status="FAIL"),
        run_id="run-v2",
        context_id="context-v2",
    )
    candidate_record = EvaluationRecord.from_result(
        evaluation("candidate", "optimized", status="PASS"),
        run_id="run-v2",
        context_id="context-v2",
    )
    state["evaluations"] = (baseline_record, candidate_record)
    comparison = ComparisonRecord.from_comparison(
        EvaluationComparison(
            classification="FULLY_ACHIEVED", promotion_eligible=True
        ),
        run_id="run-v2",
        context_id="context-v2",
        baseline_evaluation_id=baseline_record.record_id,
        candidate_evaluation_id=candidate_record.record_id,
        baseline_candidate_id="baseline",
        candidate_id="not-the-evaluated-candidate",
    )
    state["comparisons"] = (comparison,)
    with pytest.raises(ValueError, match="candidate identity is inconsistent"):
        validate_comparison_state(state)


def test_state_best_policy_cannot_alias_candidate_without_comparison_evidence():
    state = state_v2()
    candidate = CandidateParameters(
        "candidate", 1, dict(supplied_baseline_candidate().values)
    )
    state["candidates"] = append_candidate_snapshots(
        state,
        [candidate],
        source="optimizer",
        parent_candidate_id="baseline",
    )
    baseline_record = EvaluationRecord.from_result(
        evaluation("baseline", "initial", status="FAIL"),
        run_id="run-v2",
        context_id="context-v2",
    )
    state["evaluations"] = (baseline_record,)
    state["best_policy"] = BestPolicy(
        run_id="run-v2",
        context_id="context-v2",
        selected_candidate_id="candidate",
        seed_evaluation_id=baseline_record.record_id,
        selection_comparison_id=None,
        reason="illicit direct candidate update",
    )
    with pytest.raises(ValueError, match="BestPolicy"):
        validate_comparison_state(state)


def test_state_rejects_result_for_unknown_candidate_identity():
    state = state_v2()
    state["hfss_results"] = (
        HFSSResult("wrong-candidate", False, error="offline injected mismatch"),
    )
    with pytest.raises(ValueError, match="unknown candidate wrong-candidate"):
        validate_comparison_state(state)
