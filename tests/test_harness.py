"""Artifact isolation and comparison-state checkpoint tests."""

from hfss_optimization_agent.agent.comparison_state import (
    append_candidate_snapshots,
    baseline_hfss_result,
    best_candidate,
    create_comparison_state,
    current_candidate,
)
from hfss_optimization_agent.core.models import (
    CandidateParameters,
    EvaluationResult,
    HFSSResult,
)
from hfss_optimization_agent.domain.contracts import BestPolicy, EvaluationRecord
from hfss_optimization_agent.harness.artifacts import ArtifactStore
from hfss_optimization_agent.harness.checkpoint import JsonComparisonCheckpointStore
from hfss_optimization_agent.parameters.nine_parameter_schema import supplied_baseline_candidate


def test_task_artifacts_do_not_overwrite_other_tasks(tmp_path):
    first = ArtifactStore(tmp_path, "task-a")
    second = ArtifactStore(tmp_path, "task-b")
    first.initialize({})
    second.initialize({})
    first_path = first.write_candidate_artifact(
        "parameters", CandidateParameters("c1", 1, {"p1": 1.0})
    )
    second_path = second.write_candidate_artifact(
        "parameters", CandidateParameters("c2", 1, {"p1": 2.0})
    )
    assert first_path != second_path
    assert '"c1"' in first_path.read_text(encoding="utf-8")
    assert '"c2"' in second_path.read_text(encoding="utf-8")


def test_comparison_checkpoint_preserves_baseline_best_and_candidate(tmp_path):
    baseline = supplied_baseline_candidate()
    candidate = CandidateParameters("candidate", 1, dict(baseline.values))
    baseline_hfss = HFSSResult("baseline", True, metrics={"score": -0.5})
    state = create_comparison_state(task_id="task", baseline_parameters=baseline)
    state["candidates"] = append_candidate_snapshots(
        state,
        [candidate],
        source="optimizer",
        parent_candidate_id="baseline",
    )
    state["current_candidate_id"] = candidate.candidate_id
    state["hfss_results"] = (baseline_hfss,)
    evaluation = EvaluationRecord.from_result(
        EvaluationResult("baseline", False, False, {}, {}, {}, 0.0, "baseline", evaluated_stage="initial", status="FAIL"),
        run_id=state["manifest"].run_id,
        context_id=state["manifest"].design_goal.comparison_context_id,
    )
    state["evaluations"] = (evaluation,)
    state["best_policy"] = BestPolicy.seed(
        run_id=state["manifest"].run_id,
        context_id=state["manifest"].design_goal.comparison_context_id,
        baseline_candidate_id="baseline",
        baseline_evaluation_id=evaluation.record_id,
    )
    store = JsonComparisonCheckpointStore(tmp_path / "checkpoint.json")
    store.save(state)
    restored = store.load()
    assert current_candidate(restored) == candidate
    assert baseline_hfss_result(restored) == baseline_hfss
    assert best_candidate(restored) == baseline
    assert restored["best_policy"].selection_comparison_id is None
