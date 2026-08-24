"""Phase 3 optimizer request, effective-objective, and candidate-set contracts."""

from __future__ import annotations

import copy
from pathlib import Path

from hfss_optimization_agent.optimization.contracts import (
    OptimizerRequest,
    map_effective_objective,
)
from hfss_optimization_agent.optimization.deterministic_batch_optimizer import (
    DeterministicBatchOptimizer,
)
from hfss_optimization_agent.optimization.intent import ACTIVE, OptimizationObjective
from hfss_optimization_agent.optimization.supplied_optimizer_adapter import (
    SuppliedBatchOptimizerAdapter,
    SuppliedOptimizerConfig,
)
from hfss_optimization_agent.parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
)
from hfss_optimization_agent.sparameters.mock_surrogate import DeterministicSurrogate


ROOT = Path(__file__).resolve().parents[1]


def optimizer_request(*, goal: str = "meet rules", diagnosis: str = "d" * 64):
    baseline = supplied_baseline_candidate()
    baseline_sparameters = DeterministicSurrogate(baseline.values).run(baseline)
    objective = OptimizationObjective(
        status=ACTIVE,
        mode="CORE_RECOVERY",
        priority_terms=[
            {
                "priority": 1,
                "focus": "CORE_MATCHING",
                "metric": "matching_penalty",
                "penalty": 2.5,
            },
            {
                "priority": 2,
                "focus": "CORE_S21_COMPLIANCE",
                "metric": "s21_rule_penalty",
                "penalty": 1.0,
            },
        ],
        protected_constraints=["core_s11"],
        source_intent={"primary_focus": "CORE_MATCHING"},
    )
    target = {
        "minimum_score": -1.0,
        "frequency_plan": {
            "lower_margin_band": [0.1, 1.0],
            "core_band": [1.0, 19.0],
            "upper_margin_band": [19.0, 20.0],
        },
    }
    effective = map_effective_objective(objective, target)
    return OptimizerRequest(
        schema_version="optimizer-request/1.0",
        run_id="phase3-run",
        context_id="phase3-context",
        iteration=0,
        baseline=baseline,
        baseline_sparameters=baseline_sparameters,
        design_goal={
            "goal_id": "goal",
            "evaluation_contract_id": "contract",
            "comparison_context_id": "phase3-context",
            "objective": goal,
            "target_specification": copy.deepcopy(target),
        },
        diagnosis_digest=diagnosis,
        target_specification=target,
        optimization_objective=objective,
        effective_objective=effective,
        provider_fingerprints={"optimizer": "test-v1"},
        config_fingerprints={"config": "test-v1"},
    )


def test_goal_and_diagnosis_perturbation_change_optimizer_request_digest():
    original = optimizer_request()
    goal_changed = optimizer_request(goal="prioritize transmission")
    diagnosis_changed = optimizer_request(diagnosis="e" * 64)

    assert original.digest != goal_changed.digest
    assert original.digest != diagnosis_changed.digest
    assert original.effective_objective.digest == goal_changed.effective_objective.digest


def test_deterministic_optimizer_echoes_effective_objective_and_auditable_set():
    request = optimizer_request()
    batch = DeterministicBatchOptimizer((1.01, 1.02, 1.03)).optimize(request=request)

    assert batch.metadata["optimizer_request_digest"] == request.digest
    assert batch.metadata["effective_objective_digest"] == request.effective_objective.digest
    assert len(batch.candidates) == 3
    assert len({candidate.candidate_id for candidate in batch.candidates}) == 3


def test_supplied_optimizer_runs_in_worker_and_returns_full_auditable_candidate_set(tmp_path):
    request = optimizer_request()
    adapter = SuppliedBatchOptimizerAdapter(
        SuppliedOptimizerConfig(
            source_root=ROOT / "vendor" / "optimizer",
            output_root=tmp_path / "optimizer",
            quick=True,
            timeout_seconds=120.0,
            heartbeat_timeout_seconds=10.0,
            termination_grace_seconds=2.0,
        )
    )

    batch = adapter.optimize(request=request)

    assert batch.metadata["optimizer_request_digest"] == request.digest
    assert batch.metadata["effective_objective_digest"] == request.effective_objective.digest
    assert batch.metadata["pareto_points"] == len(batch.candidates)
    # A complete Pareto frontier may legitimately contain one non-dominated point;
    # the Agent must preserve that physical result instead of fabricating backups.
    assert len(batch.candidates) >= 1
    assert batch.recommended_candidate_id in {
        candidate.candidate_id for candidate in batch.candidates
    }
    assert all("vendor_evidence_digest" in candidate.metadata for candidate in batch.candidates)
    assert any(Path(path).name == "01_pareto.csv" for path in batch.artifact_paths)
