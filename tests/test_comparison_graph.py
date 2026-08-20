"""Offline end-to-end tests for the confirmed baseline/candidate comparison sequence."""

from hfss_optimization_agent.agent.comparison_state import create_comparison_state
from hfss_optimization_agent.composition import compose_comparison_workflow
from hfss_optimization_agent.core.config import AppConfig, EvaluationConfig
from hfss_optimization_agent.hfss.mock_hfss import MockHFSS
from hfss_optimization_agent.optimization.deterministic_batch_optimizer import (
    DeterministicBatchOptimizer,
)
from hfss_optimization_agent.parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
    supplied_nine_parameter_schema,
)
from hfss_optimization_agent.sparameters.mock_surrogate import DeterministicSurrogate


def invoke(tmp_path, *, factor=1.05, gate=0.0):
    baseline = supplied_baseline_candidate()
    schema = supplied_nine_parameter_schema()
    config = AppConfig(
        artifact_root=tmp_path,
        evaluation=EvaluationConfig(candidate_gate_score=gate, target_score=-1.0),
    )
    surrogate = DeterministicSurrogate(baseline.values)
    optimizer = DeterministicBatchOptimizer((factor,))
    hfss = MockHFSS()
    state = create_comparison_state(
        task_id="comparison-test",
        baseline_parameters=baseline,
        target_specification={"minimum_score": -1.0},
    )
    final = compose_comparison_workflow(
        task_id=state["task_id"],
        baseline_parameters=baseline,
        schema=schema,
        config=config,
        sparameters=surrogate,
        optimizer=optimizer,
        hfss=hfss,
    ).invoke(state)
    return final, surrogate, optimizer, hfss


def test_confirmed_business_sequence_runs_each_formal_baseline_and_candidate_stage(tmp_path):
    final, surrogate, optimizer, hfss = invoke(tmp_path)
    assert final["status"] == "completed"
    assert surrogate.call_count == 2
    assert optimizer.call_count == 1
    assert hfss.call_count == 2
    assert final["best_candidate"].candidate_id == "optimized-001"
    assert final["evaluation_result"].improved is True
    assert final["execution_trace"] == [
        "initialize_task",
        "calculate_baseline_sparameters",
        "run_baseline_hfss",
        "freeze_baseline",
        "run_optimizer:deterministic-001",
        "select_optimized_candidate:optimized-001",
        "validate_optimized_candidate",
        "recalculate_candidate_sparameters",
        "candidate_sparameter_gate:run_hfss",
        "run_candidate_hfss",
        "compare_hfss_results",
        "update_hfss_best:updated",
        "decide_after_hfss:pass",
        "complete",
    ]
    task = tmp_path / "comparison-test"
    assert (task / "baseline" / "sparameter_result.json").exists()
    assert (task / "baseline" / "hfss_result.json").exists()
    assert (task / "optimization" / "batch.json").exists()
    assert (task / "candidate" / "sparameter_result.json").exists()
    assert (task / "candidate" / "hfss_result.json").exists()
    assert (task / "candidate" / "hfss_comparison.json").exists()


def test_candidate_sparameter_gate_prevents_second_hfss_call(tmp_path):
    final, _surrogate, _optimizer, hfss = invoke(tmp_path, factor=0.95, gate=0.0)
    assert hfss.call_count == 1
    assert final["candidate_hfss_result"] is None
    assert final["best_candidate"].candidate_id == "baseline"
    assert "candidate_sparameter_gate:stop" in final["execution_trace"]
    assert (tmp_path / "comparison-test" / "candidate" / "status.json").exists()


def test_worse_hfss_candidate_never_replaces_baseline_best(tmp_path):
    final, _surrogate, _optimizer, hfss = invoke(tmp_path, factor=0.95, gate=-1.0)
    assert hfss.call_count == 2
    assert final["evaluation_result"].improved is False
    assert final["best_candidate"].candidate_id == "baseline"
    assert "update_hfss_best:retained" in final["execution_trace"]


def test_completed_checkpoint_restores_both_baseline_and_candidate_results(tmp_path):
    final, *_ = invoke(tmp_path)
    restored = compose_comparison_workflow(
        task_id="unused",
        baseline_parameters=supplied_baseline_candidate(),
        schema=supplied_nine_parameter_schema(),
        config=AppConfig(artifact_root=tmp_path),
        sparameters=DeterministicSurrogate(supplied_baseline_candidate().values),
        optimizer=DeterministicBatchOptimizer(),
        hfss=MockHFSS(),
    ).nodes.checkpoint
    restored.path = tmp_path / "comparison-test" / "checkpoint.json"
    loaded = restored.load()
    assert loaded["status"] == final["status"]
    assert loaded["baseline_sparameter_result"].candidate_id == "baseline"
    assert loaded["candidate_sparameter_result"].candidate_id == "optimized-001"
    assert loaded["best_candidate"].candidate_id == "optimized-001"


def test_restart_from_checkpoint_reuses_all_completed_expensive_stages(tmp_path):
    invoke(tmp_path)
    baseline = supplied_baseline_candidate()
    surrogate = DeterministicSurrogate(baseline.values)
    optimizer = DeterministicBatchOptimizer((1.05,))
    hfss = MockHFSS()
    runner = compose_comparison_workflow(
        task_id="comparison-test",
        baseline_parameters=baseline,
        schema=supplied_nine_parameter_schema(),
        config=AppConfig(artifact_root=tmp_path),
        sparameters=surrogate,
        optimizer=optimizer,
        hfss=hfss,
    )
    resumed = runner.invoke(runner.nodes.checkpoint.load())
    assert resumed["status"] == "completed"
    assert surrogate.call_count == 0
    assert optimizer.call_count == 0
    assert hfss.call_count == 0
    assert "calculate_baseline_sparameters:reused" in resumed["execution_trace"]
    assert "run_optimizer:reused" in resumed["execution_trace"]
    assert "run_candidate_hfss:reused" in resumed["execution_trace"]
