from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import inspect

from hfss_optimization_agent.agent.closed_loop_contracts import (
    CLOSED_LOOP_WORKFLOW_ID,
    ClosedLoopBudget,
    ClosedLoopControllerState,
    ControllerAction,
)
from hfss_optimization_agent.agent.closed_loop_policy import ClosedLoopPolicy
from hfss_optimization_agent.agent.closed_loop_graph import build_closed_loop_graph
from hfss_optimization_agent.agent.comparison_state import (
    comparison_state_from_dict,
    comparison_state_to_dict,
    create_comparison_state,
)
from hfss_optimization_agent.cli import run_closed_loop_supplied_mock_demo
from hfss_optimization_agent.composition import compose_closed_loop_workflow
from hfss_optimization_agent.core.config import AppConfig
from hfss_optimization_agent.core.enums import WorkflowStatus
from hfss_optimization_agent.core.models import (
    CandidateParameters,
    ComplexSParameters,
    HFSSResult,
    OptimizationBatch,
    SParameterResult,
)
from hfss_optimization_agent.evaluation.contract import (
    OFFLINE_CONTRACT_ID,
    load_offline_evaluation_config,
)
from hfss_optimization_agent.optimization.contracts import OptimizerRequest
from hfss_optimization_agent.parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
    supplied_nine_parameter_schema,
)
from hfss_optimization_agent.harness.errors import WorkflowError
from hfss_optimization_agent.domain.canonical_json import canonical_loads
from hfss_optimization_agent.harness.final_manifest import FinalRunManifestV1


ROOT = Path(__file__).resolve().parents[1]


def _complex_response(s11_db: float = -10.0) -> ComplexSParameters:
    s11 = 10.0 ** (s11_db / 20.0)
    matrices = [
        [[complex(s11, 0.0), complex(0.8, 0.0)], [complex(0.8, 0.0), complex(s11, 0.0)]]
        for _ in range(3)
    ]
    return ComplexSParameters.from_complex_matrices(
        frequency_hz=[1e9, 2e9, 3e9], matrices=matrices
    )


class ScriptedSurrogate:
    def __init__(
        self,
        screening_scores: dict[str, float],
        *,
        failed_ids: set[str] | None = None,
    ) -> None:
        self.screening_scores = screening_scores
        self.failed_ids = failed_ids or set()
        self.calls: list[str] = []

    def run(self, candidate: CandidateParameters) -> SParameterResult:
        self.calls.append(candidate.candidate_id)
        if candidate.candidate_id in self.failed_ids:
            return SParameterResult(
                candidate_id=candidate.candidate_id,
                success=False,
                provider="scripted-surrogate",
                model_version="phase4",
                error="confirmed scripted failure",
            )
        score = self.screening_scores.get(candidate.candidate_id, 1.0)
        return SParameterResult(
            candidate_id=candidate.candidate_id,
            success=True,
            response=_complex_response(),
            metrics={"screening_score": score, "worst_s11_magnitude": 0.3},
            provider="scripted-surrogate",
            model_version="phase4",
            calibration_status="mock",
        )


class ScriptedOptimizer:
    def __init__(self, batches: list[list[str]]) -> None:
        self.batches = batches
        self.calls = 0

    def optimize(self, *, request: OptimizerRequest) -> OptimizationBatch:
        index = min(self.calls, len(self.batches) - 1)
        ids = self.batches[index]
        self.calls += 1
        candidates = [
            CandidateParameters(
                candidate_id=candidate_id,
                iteration=request.iteration + 1,
                values={
                    name: value * (1.01 + 0.01 * position)
                    for name, value in request.baseline.values.items()
                },
                metadata={"source": "scripted-optimizer"},
            )
            for position, candidate_id in enumerate(ids)
        ]
        return OptimizationBatch(
            run_id=f"scripted-{self.calls}",
            success=True,
            candidates=candidates,
            recommended_candidate_id=candidates[0].candidate_id,
            evaluations=len(candidates),
            metadata={
                "optimizer_request_digest": request.digest,
                "effective_objective_digest": request.effective_objective.digest,
                "effective_objective": request.effective_objective.to_dict(),
            },
        )


class ScriptedHFSS:
    def __init__(self, s11_by_candidate: dict[str, float]) -> None:
        self.s11_by_candidate = s11_by_candidate
        self.calls: list[str] = []

    def run(self, candidate: CandidateParameters) -> HFSSResult:
        self.calls.append(candidate.candidate_id)
        source_id = candidate.metadata.get("retry_of", candidate.candidate_id)
        s11 = self.s11_by_candidate.get(candidate.candidate_id)
        if s11 is None:
            s11 = self.s11_by_candidate.get(str(source_id), -10.0)
        return HFSSResult(
            candidate_id=candidate.candidate_id,
            success=True,
            frequency=[1.0, 2.0, 3.0],
            s_parameters={"s11_db": [s11, s11, s11], "s21_db": [-1.0, -1.0, -1.0]},
            metrics={"score": -s11},
        )


def _run(
    tmp_path: Path,
    *,
    task_id: str,
    optimizer: ScriptedOptimizer,
    surrogate: ScriptedSurrogate,
    hfss: ScriptedHFSS,
    budget: ClosedLoopBudget | None = None,
    gate: float = 0.0,
):
    baseline = supplied_baseline_candidate()
    evaluation = load_offline_evaluation_config(
        ROOT / "config" / "evaluation_contract.offline_v1.json"
    )
    evaluation.candidate_gate_score = gate
    config = AppConfig(
        artifact_root=tmp_path,
        evaluation=evaluation,
        closed_loop_enabled=True,
    )
    controller = ClosedLoopControllerState.initial(budget or ClosedLoopBudget())
    state = create_comparison_state(
        task_id=task_id,
        baseline_parameters=baseline,
        target_specification={"minimum_score": -1.0},
        evaluation_contract_id=OFFLINE_CONTRACT_ID,
        provider_fingerprints={
            "optimizer": "scripted",
            "surrogate": "scripted",
            "hfss": "scripted",
            "controller": controller.policy_id,
        },
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
        controller=controller,
        created_at="2026-08-24T00:00:00+00:00",
    )
    return compose_closed_loop_workflow(
        task_id=task_id,
        baseline_parameters=baseline,
        schema=supplied_nine_parameter_schema(),
        config=config,
        sparameters=surrogate,
        optimizer=optimizer,
        hfss=hfss,
        recursion_limit=2 * controller.budget.max_controller_iterations + 16,
    ).invoke(state)


def test_baseline_pass_finalizes_without_optimizer(tmp_path: Path) -> None:
    optimizer = ScriptedOptimizer([["unused"]])
    final = _run(
        tmp_path,
        task_id="baseline-pass",
        optimizer=optimizer,
        surrogate=ScriptedSurrogate({}),
        hfss=ScriptedHFSS({"baseline": -14.0}),
    )
    assert final["status"] == WorkflowStatus.SUCCEEDED_BASELINE
    assert final["terminal_outcome"].reason_code == "baseline_target_met"
    assert optimizer.calls == 0
    reference = next(
        item for item in final["artifact_refs"] if item.role == "final_run_manifest"
    )
    payload = canonical_loads(
        (tmp_path / "baseline-pass" / reference.uri).read_text(encoding="utf-8")
    )
    manifest = FinalRunManifestV1.from_dict(payload)
    assert manifest.terminal_outcome.to_dict()["status"] == "succeeded_baseline"
    assert manifest.policy_versions == ("bounded-offline-policy-v1",)
    decision = manifest.decisions[-1].to_dict()
    assert isinstance(decision["input_state_revision"], int)
    assert len(decision["input_state_sha256"]) == 64
    assert decision["policy_version"] == "bounded-offline-policy-v1"
    assert decision["reason"]
    assert decision["next_step"] == "finalize"
    assert manifest.ledger_cutoff_sequence == manifest.events[-1].to_dict()["sequence"]


def test_closed_loop_controller_state_has_strict_round_trip() -> None:
    baseline = supplied_baseline_candidate()
    state = create_comparison_state(
        task_id="controller-roundtrip",
        baseline_parameters=baseline,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
        controller=ClosedLoopControllerState.initial(ClosedLoopBudget()),
    )
    assert comparison_state_from_dict(comparison_state_to_dict(state)) == state


def test_closed_loop_composition_is_feature_flagged(tmp_path: Path) -> None:
    baseline = supplied_baseline_candidate()
    with pytest.raises(ValueError, match="closed_loop_enabled"):
        compose_closed_loop_workflow(
            task_id="flag-off",
            baseline_parameters=baseline,
            schema=supplied_nine_parameter_schema(),
            config=AppConfig(artifact_root=tmp_path),
            sparameters=ScriptedSurrogate({}),
            optimizer=ScriptedOptimizer([["candidate"]]),
            hfss=ScriptedHFSS({"baseline": -10.0}),
        )


def test_closed_loop_graph_has_one_conditional_router() -> None:
    source = inspect.getsource(build_closed_loop_graph)
    assert source.count("add_conditional_edges") == 1


def test_closed_loop_rejects_unbound_real_manifest_before_provider_calls(tmp_path: Path) -> None:
    baseline = supplied_baseline_candidate()
    surrogate = ScriptedSurrogate({})
    optimizer = ScriptedOptimizer([["candidate"]])
    hfss = ScriptedHFSS({"baseline": -10.0})
    controller = ClosedLoopControllerState.initial(ClosedLoopBudget())
    state = create_comparison_state(
        task_id="closed-loop-real-rejected",
        baseline_parameters=baseline,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
        controller=controller,
        real_execution=True,
    )
    runner = compose_closed_loop_workflow(
        task_id="closed-loop-real-rejected",
        baseline_parameters=baseline,
        schema=supplied_nine_parameter_schema(),
        config=AppConfig(artifact_root=tmp_path, closed_loop_enabled=True),
        sparameters=surrogate,
        optimizer=optimizer,
        hfss=hfss,
    )
    with pytest.raises(WorkflowError, match="explicit Production composition"):
        runner.invoke(state)
    assert surrogate.calls == []
    assert optimizer.calls == 0
    assert hfss.calls == []


def test_screen_fail_consumes_candidate_one_then_candidate_two_passes(tmp_path: Path) -> None:
    final = _run(
        tmp_path,
        task_id="screen-next",
        optimizer=ScriptedOptimizer([["candidate-1", "candidate-2"]]),
        surrogate=ScriptedSurrogate({"candidate-1": -1.0, "candidate-2": 1.0}),
        hfss=ScriptedHFSS({"baseline": -10.0, "candidate-2": -14.0}),
    )
    assert final["status"] == WorkflowStatus.SUCCEEDED_CANDIDATE
    assert "candidate-1" in final["controller"].consumed_candidate_ids
    assert all(result.candidate_id != "candidate-1" for result in final["hfss_results"])
    assert final["best_policy"].selected_candidate_id == "candidate-2"


def test_improved_nonpass_candidate_advances_then_promotes_pass(tmp_path: Path) -> None:
    final = _run(
        tmp_path,
        task_id="improve-next",
        optimizer=ScriptedOptimizer([["candidate-1", "candidate-2"]]),
        surrogate=ScriptedSurrogate({"candidate-1": 1.0, "candidate-2": 1.0}),
        hfss=ScriptedHFSS(
            {"baseline": -10.0, "candidate-1": -11.0, "candidate-2": -14.0}
        ),
    )
    assert final["status"] == WorkflowStatus.SUCCEEDED_CANDIDATE
    assert final["best_policy"].selected_candidate_id == "candidate-2"
    assert [item.candidate_id for item in final["comparisons"]] == [
        "candidate-1",
        "candidate-2",
    ]
    assert "candidate-1" in final["controller"].consumed_candidate_ids


def test_queue_exhaustion_reoptimizes_from_candidate_diagnosis(tmp_path: Path) -> None:
    optimizer = ScriptedOptimizer([["candidate-1"], ["candidate-r2"]])
    final = _run(
        tmp_path,
        task_id="reoptimize",
        optimizer=optimizer,
        surrogate=ScriptedSurrogate({"candidate-1": 1.0, "candidate-r2": 1.0}),
        hfss=ScriptedHFSS(
            {"baseline": -10.0, "candidate-1": -11.0, "candidate-r2": -14.0}
        ),
    )
    assert final["status"] == WorkflowStatus.SUCCEEDED_CANDIDATE
    assert optimizer.calls == 2
    assert final["controller"].reoptimizations == 1
    assert any(item.action is ControllerAction.REOPTIMIZE for item in final["controller"].decisions)


def test_optimizer_budget_exhaustion_is_typed_no_solution(tmp_path: Path) -> None:
    final = _run(
        tmp_path,
        task_id="no-solution",
        optimizer=ScriptedOptimizer([["candidate-1"]]),
        surrogate=ScriptedSurrogate({"candidate-1": 1.0}),
        hfss=ScriptedHFSS({"baseline": -10.0, "candidate-1": -11.0}),
        budget=ClosedLoopBudget(max_optimizer_calls=1, max_reoptimizations=0),
    )
    assert final["status"] == WorkflowStatus.NO_SOLUTION
    assert final["terminal_outcome"].reason_code == "optimizer_budget_exhausted"


def test_screening_budget_stops_before_an_unbudgeted_second_screen(tmp_path: Path) -> None:
    final = _run(
        tmp_path,
        task_id="screen-budget",
        optimizer=ScriptedOptimizer([["candidate-1", "candidate-2"]]),
        surrogate=ScriptedSurrogate({"candidate-1": -1.0, "candidate-2": 1.0}),
        hfss=ScriptedHFSS({"baseline": -10.0, "candidate-2": -14.0}),
        budget=ClosedLoopBudget(max_candidate_screenings=1),
    )
    assert final["status"] == WorkflowStatus.NO_SOLUTION
    assert final["terminal_outcome"].reason_code == "candidate_screening_budget_exhausted"
    assert final["controller"].candidate_screenings == 1


def test_candidate_hfss_budget_stops_before_second_hfss(tmp_path: Path) -> None:
    final = _run(
        tmp_path,
        task_id="hfss-budget",
        optimizer=ScriptedOptimizer([["candidate-1", "candidate-2"]]),
        surrogate=ScriptedSurrogate({"candidate-1": 1.0, "candidate-2": 1.0}),
        hfss=ScriptedHFSS(
            {"baseline": -10.0, "candidate-1": -10.5, "candidate-2": -14.0}
        ),
        budget=ClosedLoopBudget(max_candidate_hfss_calls=1),
    )
    assert final["status"] == WorkflowStatus.NO_SOLUTION
    assert final["terminal_outcome"].reason_code == "candidate_hfss_budget_exhausted"
    assert final["controller"].candidate_hfss_calls == 1


def test_stagnation_budget_prevents_reoptimization(tmp_path: Path) -> None:
    final = _run(
        tmp_path,
        task_id="stagnation-budget",
        optimizer=ScriptedOptimizer([["candidate-1"], ["candidate-r2"]]),
        surrogate=ScriptedSurrogate({"candidate-1": 1.0, "candidate-r2": 1.0}),
        hfss=ScriptedHFSS({"baseline": -10.0, "candidate-1": -9.5}),
        budget=ClosedLoopBudget(max_stagnation=1),
    )
    assert final["status"] == WorkflowStatus.NO_SOLUTION
    assert final["terminal_outcome"].reason_code == "stagnation_budget_exhausted"
    assert final["controller"].reoptimizations == 0


def test_safe_retry_uses_new_candidate_and_action_identity(tmp_path: Path) -> None:
    surrogate = ScriptedSurrogate(
        {"candidate-1-safe-retry-1": 1.0}, failed_ids={"candidate-1"}
    )
    final = _run(
        tmp_path,
        task_id="retry-safe",
        optimizer=ScriptedOptimizer([["candidate-1"]]),
        surrogate=surrogate,
        hfss=ScriptedHFSS(
            {"baseline": -10.0, "candidate-1-safe-retry-1": -14.0}
        ),
    )
    assert final["status"] == WorkflowStatus.SUCCEEDED_CANDIDATE
    assert final["controller"].safe_retries == 1
    assert final["best_policy"].selected_candidate_id == "candidate-1-safe-retry-1"


@pytest.mark.parametrize("candidate_value", [-10.0, -10.5, -11.0, -11.5])
def test_any_scripted_sequence_obeys_controller_iteration_bound(
    tmp_path: Path, candidate_value: float
) -> None:
    budget = ClosedLoopBudget(
        max_controller_iterations=7,
        max_optimizer_calls=3,
        max_candidate_screenings=6,
        max_candidate_hfss_calls=6,
        max_reoptimizations=2,
        max_safe_retries=0,
        max_stagnation=6,
    )
    final = _run(
        tmp_path,
        task_id=f"bound-{abs(int(candidate_value * 10))}",
        optimizer=ScriptedOptimizer([["c1"], ["c2"], ["c3"]]),
        surrogate=ScriptedSurrogate({"c1": 1.0, "c2": 1.0, "c3": 1.0}),
        hfss=ScriptedHFSS(
            {"baseline": -10.0, "c1": candidate_value, "c2": candidate_value, "c3": candidate_value}
        ),
        budget=budget,
    )
    assert final["controller"].controller_iterations <= budget.max_controller_iterations
    assert final["terminal_outcome"] is not None


def test_waiting_state_routes_only_to_reconcile() -> None:
    baseline = supplied_baseline_candidate()
    controller = ClosedLoopControllerState.initial(ClosedLoopBudget())
    state = create_comparison_state(
        task_id="reconcile-policy",
        baseline_parameters=baseline,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
        controller=controller,
    )
    # Policy prioritizes reconciliation before it considers missing baseline evidence.
    state["status"] = WorkflowStatus.WAITING_RECONCILIATION
    decided = ClosedLoopPolicy().decide(state)
    assert decided.pending_action is ControllerAction.RECONCILE


def test_supplied_mock_closed_loop_reaches_typed_end_to_end(tmp_path: Path) -> None:
    summary = run_closed_loop_supplied_mock_demo(
        source_root=ROOT / "vendor" / "optimizer",
        artifact_root=tmp_path,
        task_id="supplied-closed-loop-e2e",
        quick=True,
        budget=ClosedLoopBudget(
            max_optimizer_calls=1,
            max_reoptimizations=0,
            max_controller_iterations=64,
        ),
    )
    assert summary["status"] in {
        WorkflowStatus.SUCCEEDED_CANDIDATE,
        WorkflowStatus.NO_SOLUTION,
    }
    assert summary["terminal_reason_code"]
    assert summary["controller"]["iterations"] <= 64


def test_production_canary_controller_is_policy_bound_and_two_solve_safe() -> None:
    from hfss_optimization_agent.agent.closed_loop_contracts import (
        PRODUCTION_CLOSED_LOOP_POLICY_ID,
        production_policy_sha256,
    )
    controller = ClosedLoopControllerState.production_canary()
    assert controller.policy_id == PRODUCTION_CLOSED_LOOP_POLICY_ID
    assert controller.budget.max_candidate_hfss_calls == 1
    assert controller.budget.max_safe_retries == 0
    assert controller.budget.max_optimizer_calls == 2
    assert controller.budget.max_reoptimizations == 1
    digest = production_policy_sha256()
    assert len(digest) == 64
    assert digest == production_policy_sha256()


def test_completed_v2_run_reinvoke_is_provider_and_ledger_noop(tmp_path: Path) -> None:
    first_optimizer = ScriptedOptimizer([["candidate-1"]])
    first_surrogate = ScriptedSurrogate({"candidate-1": 1.0})
    first_hfss = ScriptedHFSS({"baseline": -10.0, "candidate-1": -14.0})
    first = _run(
        tmp_path,
        task_id="completed-v2-noop",
        optimizer=first_optimizer,
        surrogate=first_surrogate,
        hfss=first_hfss,
    )
    second_optimizer = ScriptedOptimizer([["must-not-run"]])
    second_surrogate = ScriptedSurrogate({"must-not-run": 1.0})
    second_hfss = ScriptedHFSS({"baseline": -1.0, "must-not-run": -1.0})
    second = _run(
        tmp_path,
        task_id="completed-v2-noop",
        optimizer=second_optimizer,
        surrogate=second_surrogate,
        hfss=second_hfss,
    )
    assert second == first
    assert second_optimizer.calls == 0
    assert second_surrogate.calls == []
    assert second_hfss.calls == []


def test_concurrent_v2_invocations_have_one_physical_workflow(tmp_path: Path) -> None:
    optimizers = [ScriptedOptimizer([["candidate-1"]]) for _ in range(2)]
    surrogates = [ScriptedSurrogate({"candidate-1": 1.0}) for _ in range(2)]
    hfss_providers = [
        ScriptedHFSS({"baseline": -10.0, "candidate-1": -14.0})
        for _ in range(2)
    ]

    def invoke(index: int):
        return _run(
            tmp_path,
            task_id="concurrent-v2-writer",
            optimizer=optimizers[index],
            surrogate=surrogates[index],
            hfss=hfss_providers[index],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(invoke, range(2)))
    assert results[0] == results[1]
    assert sum(provider.calls for provider in optimizers) == 1
    assert sum(len(provider.calls) for provider in hfss_providers) == 2
