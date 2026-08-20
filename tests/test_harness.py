"""Artifact isolation and comparison-state checkpoint tests."""

from hfss_optimization_agent.agent.comparison_state import create_comparison_state
from hfss_optimization_agent.core.models import CandidateParameters, HFSSResult
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
    state.update(
        current_candidate=candidate,
        baseline_hfss_result=baseline_hfss,
        best_candidate=baseline,
        best_hfss_result=baseline_hfss,
        best_score=-0.5,
    )
    store = JsonComparisonCheckpointStore(tmp_path / "checkpoint.json")
    store.save(state)
    restored = store.load()
    assert restored["current_candidate"] == candidate
    assert restored["baseline_hfss_result"] == baseline_hfss
    assert restored["best_candidate"] == baseline
    assert restored["best_score"] == -0.5
