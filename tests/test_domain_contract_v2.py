"""Pure offline tests for Phase-1 immutable domain contracts and JSON rules."""

from pathlib import Path

import pytest

from hfss_optimization_agent.core.models import EvaluationComparison, EvaluationResult
from hfss_optimization_agent.domain.canonical_json import (
    CanonicalJsonError,
    canonical_dumps,
    canonical_loads,
)
from hfss_optimization_agent.domain.contracts import (
    STATE_SCHEMA_VERSION,
    ArtifactRef,
    BestPolicy,
    CandidateSnapshot,
    ComparisonRecord,
    DecisionAction,
    DecisionOutcome,
    DesignGoal,
    FrozenMap,
    EvaluationRecord,
    RunManifestV2,
)
from hfss_optimization_agent.parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
)


def manifest() -> RunManifestV2:
    return RunManifestV2(
        schema_version=STATE_SCHEMA_VERSION,
        run_id="run-001",
        task_id="task-001",
        workflow_id="baseline-optimize-hfss-compare-v2",
        created_at="2026-08-21T08:00:00+00:00",
        design_goal=DesignGoal(
            goal_id="goal-001",
            evaluation_contract_id="offline-evaluation-v1",
            comparison_context_id="context-001",
            objective="Satisfy configured S-parameter hard rules.",
            target_specification=FrozenMap.from_mapping({"minimum_score": -1.0}),
        ),
        baseline_candidate_id="baseline",
        code_revision="08f001e",
        provider_fingerprints=FrozenMap.from_mapping({"hfss": "mock-v1"}),
        config_fingerprints=FrozenMap.from_mapping({"evaluation": "sha256:test"}),
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
        candidate_id=candidate_id,
        improved=False,
        pass_target=status == "PASS",
        baseline_metrics={},
        current_metrics={},
        delta_metrics={},
        score=0.0,
        reason=status,
        evaluated_stage=stage,
        status=status,
        rule_results=[rule],
        rules=[{key: rule[key] for key in (
            "rule_id", "parameter", "frequency_band", "operator", "threshold", "hard_constraint"
        )}],
        hard_failed_rule_count=0 if status == "PASS" else 1,
        frequency_plan={
            "core_band": (1.5, 2.5),
            "lower_margin_band": (1.0, 1.5),
            "upper_margin_band": (2.5, 3.0),
            "tolerance_ghz": 1e-9,
        },
    )


def test_manifest_and_candidate_have_canonical_semantic_round_trip():
    source_manifest = manifest()
    restored_manifest = RunManifestV2.from_dict(
        canonical_loads(canonical_dumps(source_manifest))
    )
    assert restored_manifest == source_manifest
    assert canonical_dumps(restored_manifest) == canonical_dumps(source_manifest)

    snapshot = CandidateSnapshot.from_candidate(
        supplied_baseline_candidate(),
        context_id=source_manifest.design_goal.comparison_context_id,
        source="baseline",
    )
    restored_snapshot = CandidateSnapshot.from_dict(
        canonical_loads(canonical_dumps(snapshot))
    )
    assert restored_snapshot == snapshot
    assert restored_snapshot.to_candidate() == supplied_baseline_candidate()


def test_evaluation_tuple_list_round_trip_restores_contract_semantics():
    record = EvaluationRecord.from_result(
        evaluation("baseline", "initial", status="FAIL"),
        run_id="run-001",
        context_id="context-001",
    )
    restored = EvaluationRecord.from_dict(canonical_loads(canonical_dumps(record)))
    result = restored.to_result()
    assert result.rules[0]["frequency_band"] == (1.5, 2.5)
    assert result.rule_results[0]["frequency_band"] == (1.5, 2.5)
    assert result.frequency_plan["core_band"] == (1.5, 2.5)
    assert restored == record


def test_best_policy_only_promotes_from_matching_eligible_comparison_evidence():
    baseline = EvaluationRecord.from_result(
        evaluation("baseline", "initial", status="FAIL"),
        run_id="run-001",
        context_id="context-001",
    )
    candidate = EvaluationRecord.from_result(
        evaluation("candidate", "optimized", status="PASS"),
        run_id="run-001",
        context_id="context-001",
    )
    comparison = ComparisonRecord.from_comparison(
        EvaluationComparison(
            classification="FULLY_ACHIEVED",
            promotion_eligible=True,
            promotion_reason="Candidate satisfies all hard rules.",
        ),
        run_id="run-001",
        context_id="context-001",
        baseline_evaluation_id=baseline.record_id,
        candidate_evaluation_id=candidate.record_id,
        baseline_candidate_id="baseline",
        candidate_id="candidate",
    )
    policy = BestPolicy.seed(
        run_id="run-001",
        context_id="context-001",
        baseline_candidate_id="baseline",
        baseline_evaluation_id=baseline.record_id,
    )
    promoted = policy.promote(comparison)
    assert promoted.selected_candidate_id == "candidate"
    assert promoted.selection_comparison_id == comparison.record_id

    wrong_context = ComparisonRecord.from_comparison(
        comparison.to_comparison(),
        run_id="run-001",
        context_id="wrong-context",
        baseline_evaluation_id=baseline.record_id,
        candidate_evaluation_id=candidate.record_id,
        baseline_candidate_id="baseline",
        candidate_id="candidate",
    )
    with pytest.raises(ValueError, match="run/context"):
        policy.promote(wrong_context)
    ineligible = ComparisonRecord.from_comparison(
        EvaluationComparison(classification="DEGRADED", promotion_eligible=False),
        run_id="run-001",
        context_id="context-001",
        baseline_evaluation_id=baseline.record_id,
        candidate_evaluation_id=candidate.record_id,
        baseline_candidate_id="baseline",
        candidate_id="candidate",
    )
    with pytest.raises(ValueError, match="eligible Comparison evidence"):
        policy.promote(ineligible)


def test_decision_and_artifact_refs_are_explicit_context_bound_contracts():
    decision = DecisionOutcome(
        decision_id="decision:candidate:gate",
        run_id="run-001",
        context_id="context-001",
        action=DecisionAction.RUN_HFSS,
        reason_code="surrogate_gate_passed",
        reason="Candidate passed the configured surrogate gate.",
        candidate_id="candidate",
        evidence_ids=("sparameter:candidate",),
    )
    assert DecisionOutcome.from_dict(canonical_loads(canonical_dumps(decision))) == decision

    artifact = ArtifactRef(
        artifact_id="artifact:candidate:evaluation",
        uri="candidate/evaluation_result.json",
        role="candidate_evaluation",
        media_type="application/json",
        run_id="run-001",
        context_id="context-001",
        candidate_id="candidate",
        sha256="0" * 64,
    )
    assert ArtifactRef.from_dict(canonical_loads(canonical_dumps(artifact))) == artifact


def test_canonical_json_rejects_path_nan_alias_and_unknown_schema_fields():
    with pytest.raises(CanonicalJsonError, match="Path"):
        canonical_dumps({"checkpoint": Path("checkpoint.json")})
    with pytest.raises(CanonicalJsonError, match="non-finite"):
        canonical_dumps({"score": float("nan")})

    shared = []
    with pytest.raises(CanonicalJsonError, match="mutable alias"):
        canonical_dumps({"first": shared, "second": shared})

    payload = canonical_loads(canonical_dumps(manifest()))
    payload["unexpected"] = True
    with pytest.raises(CanonicalJsonError, match="unknown fields: unexpected"):
        RunManifestV2.from_dict(payload)
    with pytest.raises(CanonicalJsonError, match="duplicate JSON object key"):
        canonical_loads('{"run_id":"first","run_id":"second"}')
