"""Production Evaluation Contract v1 and ISSUE-002 regressions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hfss_optimization_agent.domain.canonical_json import canonical_dumps, canonical_loads

from hfss_optimization_agent.agent.comparison_state import (
    baseline_diagnosis,
    baseline_evaluation,
    best_candidate,
    candidate_evaluation,
    current_comparison,
    create_comparison_state,
)
from hfss_optimization_agent.agent.closed_loop_contracts import (
    CLOSED_LOOP_WORKFLOW_ID,
    ClosedLoopBudget,
    ClosedLoopControllerState,
    production_policy_sha256,
)
from hfss_optimization_agent.cli import run_real_supplied_demo
from hfss_optimization_agent.composition import compose_closed_loop_workflow, compose_comparison_nodes
from hfss_optimization_agent.core.config import AppConfig
from hfss_optimization_agent.core.models import (
    CandidateParameters,
    ComplexSParameters,
    HFSSResult,
    SParameterResult,
)
from hfss_optimization_agent.diagnosis import (
    CORE_S11_COMPLIANCE,
    CORE_S11_RULE_NOT_MET,
    CORE_S21_COMPLIANCE,
    CORE_S21_RULE_NOT_MET,
    DiagnosisNode,
)
from hfss_optimization_agent.evaluation.contract import (
    PRODUCTION_CONTRACT_ID,
    load_production_evaluation_config,
)
from hfss_optimization_agent.domain.contracts import (
    CALIBRATION_ARTIFACT_ROLES,
    CALIBRATION_EVIDENCE_SCHEMA_VERSION,
    CALIBRATION_POLICY_VERSION,
    CalibrationArtifactReceipt,
    CalibrationEvidence,
    FrozenMap,
    calibration_policy_sha256,
    canonical_digest,
)
from hfss_optimization_agent.evaluation.calibration import CalibrationPolicy
from hfss_optimization_agent.harness.execution_policy import ExecutionPolicy
from hfss_optimization_agent.harness.provenance import source_tree_digest
from hfss_optimization_agent.harness.real_hfss_safety import (
    HFSS_WORKER_PROTOCOL,
    READINESS_SCHEMA_VERSION,
    REAL_HFSS_APPROVAL_SCOPE,
    RealHFSSAuthorization,
    RealHFSSReadinessManifestV1,
    RepositoryEvidence,
    file_sha256,
)
from hfss_optimization_agent.harness.run_store import manifest_identity_sha256
from hfss_optimization_agent.hfss.contracts import attest_builder, load_hfss_contract
from hfss_optimization_agent.evaluation.evaluator import DeterministicEvaluator
from hfss_optimization_agent.harness.checkpoint import JsonComparisonCheckpointStore
from hfss_optimization_agent.domain.contracts import EvaluationRecord
from hfss_optimization_agent.optimization.intent import (
    ACTIVE,
    CORE_RECOVERY,
    OptimizationIntentBuilder,
)
from hfss_optimization_agent.optimization.deterministic_batch_optimizer import (
    DeterministicBatchOptimizer,
)
from hfss_optimization_agent.parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
    supplied_nine_parameter_schema,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "evaluation_contract.production_v1.json"
HFSS_CONTRACT_PATH = ROOT / "config" / "hfss_contract.pa_multi_2025_1.json"
FREQUENCIES = [5.0, 5.5, 6.0, 12.0, 18.0, 18.5, 19.0]


def production_evaluator() -> DeterministicEvaluator:
    config = load_production_evaluation_config(CONTRACT_PATH)
    return DeterministicEvaluator(
        rules=config.rules,
        frequency_plan=config.frequency_plan,
    )


def evaluate(*, s11: list[float], s21: list[float], candidate_id: str = "candidate"):
    return production_evaluator().evaluate_sparameters(
        {
            "frequency": FREQUENCIES,
            "S11_dB": s11,
            "S21_dB": s21,
            "frequency_unit": "GHz",
            "source": "production-contract-test",
        },
        candidate_id=candidate_id,
    )


def passing_s11() -> list[float]:
    return [-0.4] * len(FREQUENCIES)


def passing_s21() -> list[float]:
    return [-31.0] * len(FREQUENCIES)


def by_id(result, rule_id: str) -> dict:
    return next(rule for rule in result.rule_results if rule["rule_id"] == rule_id)


def test_contract_v1_loads_exact_authoritative_frequency_plan_and_rules():
    config = load_production_evaluation_config(CONTRACT_PATH)
    assert PRODUCTION_CONTRACT_ID == "production-evaluation-v1"
    assert config.frequency_plan.core_band == (6.0, 18.0)
    assert config.frequency_plan.lower_margin_band == (5.0, 6.0)
    assert config.frequency_plan.upper_margin_band == (18.0, 19.0)
    assert [
        (
            rule["rule_id"],
            rule["parameter"],
            rule["frequency_band"],
            rule["operator"],
            rule["threshold"],
            rule["hard_constraint"],
        )
        for rule in config.rules
    ] == [
        ("production_v1_core_s21", "S21", (6.0, 18.0), "<=", -30.0, True),
        ("production_v1_core_s11", "S11", (6.0, 18.0), ">=", -0.5, True),
        ("production_v1_lower_s21", "S21", (5.0, 6.0), "<=", -30.0, False),
        ("production_v1_lower_s11", "S11", (5.0, 6.0), ">=", -0.5, False),
        ("production_v1_upper_s21", "S21", (18.0, 19.0), "<=", -30.0, False),
        ("production_v1_upper_s11", "S11", (18.0, 19.0), ">=", -0.5, False),
    ]


def test_core_s21_can_fail_while_core_s11_passes_with_structured_evidence():
    s21 = passing_s21()
    s21[FREQUENCIES.index(12.0)] = -28.0
    result = evaluate(s11=passing_s11(), s21=s21)
    failed = by_id(result, "production_v1_core_s21")
    passed = by_id(result, "production_v1_core_s11")
    assert result.status == "FAIL" and result.pass_target is False
    assert failed["status"] == "FAIL"
    assert failed["worst_value"] == -28.0
    assert failed["worst_frequency"] == 12.0
    assert failed["margin_to_target"] == -2.0
    assert failed["violation_ranges"] == [{"start": 8.0, "stop": 16.0}]
    assert failed["violation_bandwidth"] == 8.0
    assert {
        "rule_id",
        "parameter",
        "frequency_band",
        "operator",
        "target",
        "hard_constraint",
        "status",
        "worst_value",
        "worst_frequency",
        "margin_to_target",
        "violation_ranges",
        "violation_bandwidth",
    } <= failed.keys()
    assert passed["status"] == "PASS"


def test_core_s11_can_fail_while_core_s21_passes_with_structured_evidence():
    s11 = passing_s11()
    s11[FREQUENCIES.index(12.0)] = -1.0
    result = evaluate(s11=s11, s21=passing_s21())
    failed = by_id(result, "production_v1_core_s11")
    passed = by_id(result, "production_v1_core_s21")
    assert result.status == "FAIL" and result.pass_target is False
    assert failed["status"] == "FAIL"
    assert failed["worst_value"] == -1.0
    assert failed["worst_frequency"] == 12.0
    assert failed["margin_to_target"] == -0.5
    assert failed["violation_ranges"] == [
        {"start": pytest.approx(7.0), "stop": pytest.approx(17.0)}
    ]
    assert passed["status"] == "PASS"


def test_both_core_rules_pass_when_every_core_point_satisfies_targets():
    result = evaluate(s11=passing_s11(), s21=passing_s21())
    assert result.status == "PASS" and result.pass_target is True
    assert by_id(result, "production_v1_core_s21")["status"] == "PASS"
    assert by_id(result, "production_v1_core_s11")["status"] == "PASS"
    assert result.hard_failed_rule_count == 0


def test_lower_margin_failure_is_soft_and_does_not_fail_overall():
    s21 = passing_s21()
    s21[FREQUENCIES.index(5.0)] = -29.0
    result = evaluate(s11=passing_s11(), s21=s21)
    soft = by_id(result, "production_v1_lower_s21")
    assert result.status == "PASS" and result.pass_target is True
    assert soft["hard_constraint"] is False and soft["status"] == "FAIL"
    assert soft["margin_to_target"] == -1.0
    assert soft["violation_ranges"] == [{"start": 5.0, "stop": 5.25}]
    assert result.soft_failed_rule_count == 1


def test_upper_margin_failure_is_soft_and_does_not_fail_overall():
    s11 = passing_s11()
    s11[FREQUENCIES.index(19.0)] = -1.0
    result = evaluate(s11=s11, s21=passing_s21())
    soft = by_id(result, "production_v1_upper_s11")
    assert result.status == "PASS" and result.pass_target is True
    assert soft["hard_constraint"] is False and soft["status"] == "FAIL"
    assert soft["worst_value"] == -1.0
    assert soft["worst_frequency"] == 19.0
    assert soft["margin_to_target"] == -0.5
    assert soft["violation_ranges"] == [
        {"start": pytest.approx(18.583333333333332), "stop": 19.0}
    ]


@pytest.mark.parametrize(
    ("parameter", "issue_type", "focus"),
    [
        ("S21", CORE_S21_RULE_NOT_MET, CORE_S21_COMPLIANCE),
        ("S11", CORE_S11_RULE_NOT_MET, CORE_S11_COMPLIANCE),
    ],
)
def test_hard_failure_survives_evaluation_diagnosis_and_active_intent(
    parameter, issue_type, focus
):
    s11 = passing_s11()
    s21 = passing_s21()
    if parameter == "S21":
        s21[FREQUENCIES.index(12.0)] = -28.0
    else:
        s11[FREQUENCIES.index(12.0)] = -1.0
    evaluation = evaluate(s11=s11, s21=s21)
    diagnosis = DiagnosisNode().diagnose(evaluation, stage="initial")
    intent = OptimizationIntentBuilder().build(diagnosis)
    assert diagnosis.primary_issue.issue_type == issue_type
    assert diagnosis.primary_issue.parameter == parameter
    assert diagnosis.optimization_focus[0] == focus
    assert intent.status == ACTIVE
    assert intent.mode == CORE_RECOVERY
    assert intent.primary_focus == focus


def test_checkpoint_round_trip_preserves_existing_rule_level_evidence(tmp_path):
    s21 = passing_s21()
    s21[FREQUENCIES.index(12.0)] = -28.0
    evaluation = evaluate(s11=passing_s11(), s21=s21, candidate_id="baseline")
    evaluation.evaluated_stage = "initial"
    state = create_comparison_state(
        task_id="production-evidence-round-trip",
        baseline_parameters=supplied_baseline_candidate(),
    )
    record = EvaluationRecord.from_result(
        evaluation,
        run_id=state["manifest"].run_id,
        context_id=state["manifest"].design_goal.comparison_context_id,
    )
    state["evaluations"] = (record,)
    store = JsonComparisonCheckpointStore(tmp_path / "checkpoint.json")
    store.save(state)
    restored = store.load()
    restored_evaluation = baseline_evaluation(restored)
    assert restored_evaluation.rule_results == evaluation.rule_results
    assert restored_evaluation.rules[0]["frequency_band"] == (6.0, 18.0)
    assert restored_evaluation.frequency_plan["core_band"] == (6.0, 18.0)


class ProductionBandSurrogate:
    def run(self, candidate: CandidateParameters) -> SParameterResult:
        matrices = [
            [[0.95 + 0.0j, 0.01 + 0.0j], [0.01 + 0.0j, 0.95 + 0.0j]]
            for _ in FREQUENCIES
        ]
        return SParameterResult(
            candidate.candidate_id,
            True,
            ComplexSParameters.from_complex_matrices(
                frequency_hz=[frequency * 1e9 for frequency in FREQUENCIES],
                matrices=matrices,
            ),
            {"screening_score": 0.0},
            provider="production-band-test-surrogate",
        )


class ProductionBandHFSS:
    def run(self, candidate: CandidateParameters) -> HFSSResult:
        s21 = passing_s21()
        if candidate.candidate_id == "baseline":
            s21[FREQUENCIES.index(12.0)] = -28.0
        return HFSSResult(
            candidate.candidate_id,
            True,
            list(FREQUENCIES),
            {"s11_db": passing_s11(), "s21_db": s21},
            {"score": 0.0},
            execution_metadata={"frequency_unit": "GHz"},
        )


class UnusedOptimizer:
    pass


def test_wf001_nodes_reach_active_objective_with_production_band_test_fixture(tmp_path):
    evaluation = load_production_evaluation_config(CONTRACT_PATH)
    baseline = supplied_baseline_candidate()
    state = create_comparison_state(
        task_id="wf001-production-evaluation",
        baseline_parameters=baseline,
    )
    nodes = compose_comparison_nodes(
        task_id=state["manifest"].task_id,
        baseline_parameters=baseline,
        schema=supplied_nine_parameter_schema(),
        config=AppConfig(artifact_root=tmp_path, evaluation=evaluation),
        sparameters=ProductionBandSurrogate(),
        optimizer=UnusedOptimizer(),
        hfss=ProductionBandHFSS(),
    )
    for node in (
        nodes.initialize_task,
        nodes.calculate_baseline_sparameters,
        nodes.run_baseline_hfss,
        nodes.diagnose_baseline,
        nodes.freeze_baseline,
        nodes.build_optimization_intent,
        nodes.build_optimization_objective,
    ):
        state.update(node(state))
    assert baseline_evaluation(state).status == "FAIL"
    assert baseline_diagnosis(state).primary_issue.issue_type == CORE_S21_RULE_NOT_MET
    assert state["optimization_intent"].status == ACTIVE
    assert state["optimization_objective"].status == ACTIVE
    assert state["execution_trace"][-1] == "build_optimization_objective"
    evidence_ref = next(
        item for item in state["artifact_refs"] if item.role == "baseline_evaluation"
    )
    evidence = tmp_path / state["manifest"].task_id / evidence_ref.uri
    assert evidence.exists()


def test_rule_configured_wf001_graph_completes_comparison_after_presenter_import(
    tmp_path,
):
    evaluation = load_production_evaluation_config(CONTRACT_PATH)
    baseline = supplied_baseline_candidate()
    controller = ClosedLoopControllerState.initial(ClosedLoopBudget())
    state = create_comparison_state(
        task_id="issue003-comparison-regression",
        baseline_parameters=baseline,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
        controller=controller,
    )
    runner = compose_closed_loop_workflow(
        task_id=state["manifest"].task_id,
        baseline_parameters=baseline,
        schema=supplied_nine_parameter_schema(),
        config=AppConfig(
            artifact_root=tmp_path,
            evaluation=evaluation,
            closed_loop_enabled=True,
        ),
        sparameters=ProductionBandSurrogate(),
        optimizer=DeterministicBatchOptimizer((1.05,)),
        hfss=ProductionBandHFSS(),
        recursion_limit=2 * controller.budget.max_controller_iterations + 16,
    )
    final = runner.invoke(state)
    assert final["status"] == "succeeded_candidate"
    assert "compare_hfss_results" in final["execution_trace"]
    assert current_comparison(final).classification == "FULLY_ACHIEVED"
    assert current_comparison(final).promotion_eligible is True
    assert best_candidate(final).candidate_id == "optimized-001"
    assert candidate_evaluation(final).status == "PASS"
    comparison_ref = next(
        item for item in final["artifact_refs"] if item.role == "evaluation_comparison"
    )
    comparison_artifact = tmp_path / state["manifest"].task_id / comparison_ref.uri
    assert comparison_artifact.exists()


def test_wf001_real_composition_loads_production_rules_without_running_hfss(
    tmp_path, monkeypatch
):
    captured = {}

    class FakeRunner:
        def invoke(self, state):
            state["status"] = "completed"
            state["sparameter_results"] = (
                SimpleNamespace(candidate_id="baseline", provider="fake"),
            )
            state["hfss_results"] = (
                SimpleNamespace(
                    candidate_id="baseline",
                    project_path="baseline.aedt",
                    metrics={"score": 0.0},
                ),
            )
            state["execution_trace"] = ("test-only",)
            return state

    monkeypatch.setattr(
        "hfss_optimization_agent.cli.compose_pyaedt_hfss", lambda **kwargs: object()
    )

    def fake_compose(**kwargs):
        captured["config"] = kwargs["config"]
        captured["allow_real_execution"] = kwargs["allow_real_execution"]
        captured["recursion_limit"] = kwargs["recursion_limit"]
        return FakeRunner()

    monkeypatch.setattr("hfss_optimization_agent.cli.compose_closed_loop_workflow", fake_compose)
    task_id = "test-only-real-composition"
    run_id = f"run:{task_id}"
    created_at = "2026-08-21T10:00:00+00:00"
    git_head = "0" * 40
    readiness_id = "test-readiness"
    approval_id = "test-only-no-aedt"
    pyaedt_python = Path(__import__("sys").executable)
    optimizer_digest = source_tree_digest(
        ROOT / "vendor" / "optimizer", suffixes=(".py", ".csv", ".toml")
    )
    agent_digest = source_tree_digest(ROOT / "src", suffixes=(".py",))
    builder_digest = attest_builder(
        ROOT / "vendor" / "hfss_builder",
        load_hfss_contract(HFSS_CONTRACT_PATH).builder_id,
    ).source_digest
    provider_fingerprints = {
        "agent_source_sha256": agent_digest,
        "supplied_optimizer_source_sha256": optimizer_digest,
        "supplied_surrogate_source_sha256": optimizer_digest,
        "hfss_builder_source_sha256": builder_digest,
        "pyaedt_executable_sha256": file_sha256(pyaedt_python),
        "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
        "closed_loop_policy_sha256": production_policy_sha256(),
    }
    contract = load_hfss_contract(HFSS_CONTRACT_PATH)
    calibration_case_ids = ("cal-a", "cal-b", "cal-c")
    calibration_policy = CalibrationPolicy(0.02, 1.0)
    calibration_policy_dict = calibration_policy.to_dict()
    calibration = CalibrationEvidence(
        schema_version=CALIBRATION_EVIDENCE_SCHEMA_VERSION,
        evidence_id="calibration:test-only",
        created_at="2026-08-20T00:00:00+00:00",
        policy_version=CALIBRATION_POLICY_VERSION,
        comparison_context_id=contract.metadata["comparison_context_id"],
        passed=True,
        case_ids=calibration_case_ids,
        provider_fingerprints=FrozenMap.from_mapping(
            {
                "supplied_surrogate_source_sha256": optimizer_digest,
                "hfss_builder_source_sha256": builder_digest,
                "pyaedt_executable_sha256": file_sha256(pyaedt_python),
                "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
            }
        ),
        policy=FrozenMap.from_mapping(calibration_policy_dict),
        policy_sha256=calibration_policy_sha256(calibration_policy_dict),
        hfss_contract_sha256=file_sha256(HFSS_CONTRACT_PATH),
        report=FrozenMap.from_mapping(
            {
                "passed": True,
                "comparison_context_id": contract.metadata["comparison_context_id"],
                "cases": [
                    {
                        "case_id": case_id,
                        "candidate_id": case_id,
                        "complex_rmse": 0.01,
                        "magnitude_db_rmse": 0.5,
                        "max_complex_error": 0.02,
                        "surrogate_worst_s11": 0.1 * index,
                        "hfss_worst_s11": 0.1 * index + 0.01,
                    }
                    for index, case_id in enumerate(calibration_case_ids, start=1)
                ],
                "mean_complex_rmse": 0.01,
                "mean_magnitude_db_rmse": 0.5,
                "pairwise_ranking_agreement": 1.0,
                "comparable_pairs": 3,
                "reasons": [],
            }
        ),
        source_artifacts=tuple(
            CalibrationArtifactReceipt(
                artifact_id=f"{case_id}:{role}",
                case_id=case_id,
                candidate_id=case_id,
                role=role,
                uri=f"calibration/{case_id}/{role}.bin",
                sha256=hashlib.sha256(f"{case_id}:{role}".encode()).hexdigest(),
                size_bytes=len(f"{case_id}:{role}".encode()),
            )
            for case_id in calibration_case_ids
            for role in sorted(CALIBRATION_ARTIFACT_ROLES)
        ),
    )
    controller = ClosedLoopControllerState.production_canary()
    expected_state = create_comparison_state(
        task_id=task_id,
        run_id=run_id,
        created_at=created_at,
        code_revision=git_head,
        baseline_parameters=supplied_baseline_candidate(),
        target_specification={"minimum_score": -1.0},
        evaluation_contract_id=PRODUCTION_CONTRACT_ID,
        comparison_context_id=contract.metadata["comparison_context_id"],
        real_execution=True,
        provider_fingerprints=provider_fingerprints,
        config_fingerprints={
            "hfss_contract_id": contract.contract_id,
            "hfss_contract_sha256": file_sha256(HFSS_CONTRACT_PATH),
            "evaluation_contract_id": PRODUCTION_CONTRACT_ID,
            "evaluation_contract_sha256": file_sha256(CONTRACT_PATH),
            "real_hfss_authorization_id": approval_id,
            "readiness_id": readiness_id,
            "calibration_evidence_sha256": calibration.digest,
            "model_alignment_sha256": "b" * 64,
            "calibration_policy_sha256": calibration.policy_sha256,
            "calibration_artifact_manifest_sha256": calibration.source_artifact_manifest_sha256,
            "calibration_evidence": canonical_loads(canonical_dumps(calibration)),
            "closed_loop_policy_id": controller.policy_id,
            "closed_loop_budget": canonical_loads(
                canonical_dumps(controller.budget)
            ),
        },
        controller=controller,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
    )
    readiness = RealHFSSReadinessManifestV1(
        schema_version=READINESS_SCHEMA_VERSION,
        readiness_id=readiness_id,
        task_id=task_id,
        run_id=run_id,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
        created_at=created_at,
        expires_at="2099-08-21T11:00:00+00:00",
        git_head=git_head,
        agent_source_sha256=agent_digest,
        run_manifest_sha256=manifest_identity_sha256(expected_state["manifest"]),
        design_goal_sha256=canonical_digest(expected_state["manifest"].design_goal),
        hfss_contract_sha256=file_sha256(HFSS_CONTRACT_PATH),
        evaluation_contract_sha256=file_sha256(CONTRACT_PATH),
        model_alignment_sha256="b" * 64,
        calibration_policy_sha256=calibration.policy_sha256,
        calibration_artifact_manifest_sha256=calibration.source_artifact_manifest_sha256,
        provider_fingerprints=FrozenMap.from_mapping(provider_fingerprints),
        approval_id=approval_id,
        approval_scope=REAL_HFSS_APPROVAL_SCOPE,
        execution_policy=ExecutionPolicy(2, 0),
        calibration_evidence=calibration,
    )
    authorization = RealHFSSAuthorization(
        manifest=readiness,
        repository=RepositoryEvidence(git_head, agent_digest, True),
    )
    summary = run_real_supplied_demo(
        optimizer_source_root=ROOT / "vendor" / "optimizer",
        builder_source_root=ROOT / "vendor" / "hfss_builder",
        pyaedt_python=pyaedt_python,
        contract_path=HFSS_CONTRACT_PATH,
        evaluation_contract_path=CONTRACT_PATH,
        artifact_root=tmp_path,
        execute_real_hfss=True,
        readiness_authorization=authorization,
    )
    assert summary["real_hfss"] is True
    assert len(captured["config"].evaluation.rules) == 6
    assert captured["config"].evaluation.rules[0]["rule_id"] == "production_v1_core_s21"
    assert captured["config"].closed_loop_enabled is True
    assert captured["allow_real_execution"] is True
    assert captured["recursion_limit"] == (
        2 * controller.budget.max_controller_iterations + 16
    )
    assert controller.budget.max_candidate_hfss_calls == 1
