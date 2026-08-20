"""Production Evaluation Contract v1 and ISSUE-002 regressions."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hfss_optimization_agent.agent.comparison_state import (
    create_comparison_state,
)
from hfss_optimization_agent.cli import run_real_supplied_demo
from hfss_optimization_agent.composition import compose_comparison_workflow
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
from hfss_optimization_agent.evaluation.evaluator import DeterministicEvaluator
from hfss_optimization_agent.harness.checkpoint import JsonComparisonCheckpointStore
from hfss_optimization_agent.optimization.intent import (
    ACTIVE,
    CORE_RECOVERY,
    OptimizationIntentBuilder,
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


def evaluate(*, s11: list[float], s21: list[float]):
    return production_evaluator().evaluate_sparameters(
        {
            "frequency": FREQUENCIES,
            "S11_dB": s11,
            "S21_dB": s21,
            "frequency_unit": "GHz",
            "source": "production-contract-test",
        },
        candidate_id="candidate",
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
    evaluation = evaluate(s11=passing_s11(), s21=s21)
    state = create_comparison_state(
        task_id="production-evidence-round-trip",
        baseline_parameters=supplied_baseline_candidate(),
    )
    state["baseline_evaluation"] = evaluation
    state["evaluation_result"] = evaluation
    state["evaluation_history"] = [evaluation]
    store = JsonComparisonCheckpointStore(tmp_path / "checkpoint.json")
    store.save(state)
    restored = store.load()
    expected = json.loads(json.dumps(evaluation.rule_results))
    assert restored["baseline_evaluation"].rule_results == expected
    assert restored["evaluation_result"].rule_results == expected
    assert restored["evaluation_history"][0].rule_results == expected


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
    runner = compose_comparison_workflow(
        task_id=state["task_id"],
        baseline_parameters=baseline,
        schema=supplied_nine_parameter_schema(),
        config=AppConfig(artifact_root=tmp_path, evaluation=evaluation),
        sparameters=ProductionBandSurrogate(),
        optimizer=UnusedOptimizer(),
        hfss=ProductionBandHFSS(),
    )
    for node in (
        runner.nodes.initialize_task,
        runner.nodes.calculate_baseline_sparameters,
        runner.nodes.run_baseline_hfss,
        runner.nodes.diagnose_baseline,
        runner.nodes.freeze_baseline,
        runner.nodes.build_optimization_intent,
        runner.nodes.build_optimization_objective,
    ):
        state.update(node(state))
    assert state["baseline_evaluation"].status == "FAIL"
    assert state["baseline_diagnosis"].primary_issue.issue_type == CORE_S21_RULE_NOT_MET
    assert state["optimization_intent"].status == ACTIVE
    assert state["optimization_objective"].status == ACTIVE
    assert state["execution_trace"][-1] == "build_optimization_objective"
    evidence = tmp_path / state["task_id"] / "baseline" / "evaluation_result.json"
    assert evidence.exists()


def test_wf001_real_composition_loads_production_rules_without_running_hfss(
    tmp_path, monkeypatch
):
    captured = {}

    class FakeRunner:
        def invoke(self, state):
            baseline = state["baseline_parameters"]
            return {
                **state,
                "status": "completed",
                "baseline_sparameter_result": SimpleNamespace(provider="fake"),
                "optimization_batch": None,
                "evaluation_result": None,
                "current_candidate": None,
                "best_candidate": baseline,
                "best_score": 0.0,
                "execution_trace": ["test-only"],
                "baseline_hfss_result": SimpleNamespace(project_path="baseline.aedt"),
                "candidate_hfss_result": None,
            }

    monkeypatch.setattr(
        "hfss_optimization_agent.cli.compose_pyaedt_hfss", lambda **kwargs: object()
    )

    def fake_compose(**kwargs):
        captured["config"] = kwargs["config"]
        return FakeRunner()

    monkeypatch.setattr("hfss_optimization_agent.cli.compose_comparison_workflow", fake_compose)
    summary = run_real_supplied_demo(
        optimizer_source_root=ROOT / "vendor" / "optimizer",
        builder_source_root=ROOT / "vendor" / "hfss_builder",
        pyaedt_python=Path(__import__("sys").executable),
        contract_path=HFSS_CONTRACT_PATH,
        evaluation_contract_path=CONTRACT_PATH,
        artifact_root=tmp_path,
        execute_real_hfss=True,
    )
    assert summary["real_hfss"] is True
    assert len(captured["config"].evaluation.rules) == 6
    assert captured["config"].evaluation.rules[0]["rule_id"] == "production_v1_core_s21"
