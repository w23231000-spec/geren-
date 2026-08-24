"""Deterministic Phase 5B action/checkpoint/resume corruption chaos matrix."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

import pytest

from hfss_optimization_agent.agent.closed_loop_contracts import (
    CLOSED_LOOP_WORKFLOW_ID,
    ClosedLoopBudget,
    ClosedLoopControllerState,
)
from hfss_optimization_agent.agent.comparison_state import create_comparison_state
from hfss_optimization_agent.composition import compose_closed_loop_workflow
from hfss_optimization_agent.core.config import AppConfig
from hfss_optimization_agent.evaluation.contract import load_offline_evaluation_config
from hfss_optimization_agent.harness.artifacts import ArtifactStore
from hfss_optimization_agent.harness.checkpoint import SQLiteComparisonCheckpointStore
from hfss_optimization_agent.harness.core import HarnessCore, HarnessSettings, OperationUnknownError
from hfss_optimization_agent.harness.errors import WorkflowError
from hfss_optimization_agent.harness.fault_injection import (
    ArmedFaultInjector,
    CrashPoint,
    InjectedProcessCrash,
)
from hfss_optimization_agent.harness.run_store import (
    CheckpointCorruption,
    OperationRequest,
    OperationStatus,
    RunStatus,
    RunStore,
)
from hfss_optimization_agent.hfss.mock_hfss import MockHFSS
from hfss_optimization_agent.optimization.deterministic_batch_optimizer import (
    DeterministicBatchOptimizer,
)
from hfss_optimization_agent.parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
    supplied_nine_parameter_schema,
)
from hfss_optimization_agent.sparameters.mock_surrogate import DeterministicSurrogate


CONTRACT_PATH = Path(__file__).parents[1] / "config" / "evaluation_contract.offline_v1.json"


def _state(name: str, *, workflow_id=CLOSED_LOOP_WORKFLOW_ID):
    return create_comparison_state(
        task_id=name,
        run_id=f"run:{name}",
        comparison_context_id=f"context:{name}",
        baseline_parameters=supplied_baseline_candidate(),
        workflow_id=workflow_id,
        controller=(
            ClosedLoopControllerState.initial(ClosedLoopBudget())
            if workflow_id == CLOSED_LOOP_WORKFLOW_ID else None
        ),
        created_at="2026-08-24T00:00:00+00:00",
    )


def _core(tmp_path, current, injector=None):
    core = HarnessCore(
        store=RunStore(tmp_path / ".runstore" / "runstore.sqlite3"),
        artifacts=ArtifactStore(tmp_path, current["manifest"].task_id),
        settings=HarnessSettings(
            budget_limit=10,
            operation_costs={"hfss": 1},
            operation_lease_seconds=0.2,
            in_flight_wait_seconds=0.5,
        ),
        fault_injector=injector,
    )
    core.ensure_run(current["manifest"])
    return core


def _request(current):
    return OperationRequest(
        run_id=current["manifest"].run_id,
        kind="hfss",
        subject_id="baseline",
        idempotency_key="chaos-action",
        payload={"candidate_id": "baseline"},
        result_role="hfss_result",
        estimated_cost=1,
        ambiguity_on_exception=True,
    )


@pytest.mark.parametrize(
    "point,provider_calls,expected_status",
    (
        (CrashPoint.ACTION_AFTER_CLAIM, 0, OperationStatus.RUNNING),
        (CrashPoint.ACTION_AFTER_PROVIDER, 1, OperationStatus.RUNNING),
        (CrashPoint.ACTION_AFTER_ARTIFACT_FREEZE, 1, OperationStatus.RUNNING),
        (CrashPoint.ACTION_AFTER_RECEIPT_COMMIT, 1, OperationStatus.SUCCEEDED),
    ),
)
def test_every_action_boundary_has_conservative_crash_semantics(
    tmp_path, point, provider_calls, expected_status
):
    current = _state(f"action-{point.value}")
    injector = ArmedFaultInjector({point})
    core = _core(tmp_path, current, injector)
    request = _request(current)
    calls = 0

    def provider():
        nonlocal calls
        calls += 1
        return {"candidate_id": "baseline", "success": True}

    with pytest.raises(InjectedProcessCrash) as crash:
        core.execute(request, provider, decoder=lambda value: value)
    assert crash.value.point is point
    assert calls == provider_calls
    assert core.store.get_operation(request.operation_id).status is expected_status
    assert core.store.count_attempts(request.operation_id) == 1
    assert core.store.get_run(request.run_id).budget_reserved == 1

    reopened = _core(tmp_path, current)
    if expected_status is OperationStatus.SUCCEEDED:
        with ThreadPoolExecutor(max_workers=2) as pool:
            resumes = tuple(
                pool.map(
                    lambda _index: reopened.execute(
                        request,
                        lambda: pytest.fail("receipt replay must not call provider"),
                        decoder=lambda value: value,
                    ),
                    range(2),
                )
            )
        assert all(item.cached for item in resumes)
        assert reopened.store.count_attempts(request.operation_id) == 1
    else:
        reopened.store.expire_stale_operations(
            request.run_id, as_of="2999-01-01T00:00:00+00:00"
        )
        with pytest.raises(OperationUnknownError):
            reopened.execute(
                request,
                lambda: pytest.fail("UNKNOWN must not call provider"),
                decoder=lambda value: value,
            )
        assert reopened.store.get_operation(request.operation_id).status is OperationStatus.UNKNOWN
        assert reopened.store.get_run(request.run_id).status is RunStatus.WAITING_RECONCILIATION
        assert reopened.store.count_attempts(request.operation_id) == 1


@pytest.mark.parametrize(
    "point,expected_revision",
    (
        (CrashPoint.CHECKPOINT_BEFORE_COMMIT, 0),
        (CrashPoint.CHECKPOINT_AFTER_COMMIT, 1),
    ),
)
def test_checkpoint_commit_boundaries_are_atomic_and_resumable(
    tmp_path, point, expected_revision
):
    current = _state(f"checkpoint-{point.value}")
    core = _core(tmp_path, current)
    checkpoint = SQLiteComparisonCheckpointStore(
        core.store, fault_injector=ArmedFaultInjector({point})
    )
    checkpoint.bind(current["manifest"].run_id)
    with pytest.raises(InjectedProcessCrash):
        checkpoint.save(current)
    run = core.store.get_run(current["manifest"].run_id)
    assert run.latest_checkpoint_revision == expected_revision

    reopened = SQLiteComparisonCheckpointStore(
        RunStore(tmp_path / ".runstore" / "runstore.sqlite3")
    )
    reopened.bind(current["manifest"].run_id)
    if expected_revision:
        assert reopened.load() == current
        assert reopened.save(current) == expected_revision
    else:
        assert reopened.has_checkpoint() is False
        assert reopened.save(current) == 1


def _runner(tmp_path, current):
    evaluation = load_offline_evaluation_config(CONTRACT_PATH)
    config = AppConfig(artifact_root=tmp_path, evaluation=evaluation, closed_loop_enabled=True)
    baseline = supplied_baseline_candidate()
    surrogate = DeterministicSurrogate(baseline.values)
    optimizer = DeterministicBatchOptimizer((1.05,))
    hfss = MockHFSS(baseline_values=baseline.values)
    runner = compose_closed_loop_workflow(
        task_id=current["manifest"].task_id,
        baseline_parameters=baseline,
        schema=supplied_nine_parameter_schema(),
        config=config,
        sparameters=surrogate,
        optimizer=optimizer,
        hfss=hfss,
    )
    return runner, surrogate, optimizer, hfss


def test_corrupt_checkpoint_fails_closed_before_any_provider(tmp_path):
    current = _state("corrupt-checkpoint")
    runner, surrogate, optimizer, hfss = _runner(tmp_path, current)
    runner.nodes.harness.ensure_run(current["manifest"])
    runner.nodes.checkpoint.bind(current["manifest"].run_id)
    runner.nodes.checkpoint.save(current)
    database = tmp_path / ".runstore" / "runstore.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE checkpoints SET state_json = ? WHERE run_id = ?",
            ("{not-json", current["manifest"].run_id),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(CheckpointCorruption):
        runner.nodes.checkpoint.load()
    waiting = runner.invoke(current)
    assert waiting["status"] == "waiting_reconciliation"
    assert waiting["decision_outcome"].reason_code == "checkpoint_corrupt"
    assert runner.nodes.harness.store.get_run(current["manifest"].run_id).status is RunStatus.WAITING_RECONCILIATION
    assert surrogate.call_count == optimizer.call_count == hfss.call_count == 0
    assert len([
        event for event in runner.nodes.harness.store.list_events(current["manifest"].run_id)
        if event["event_type"] == "checkpoint_corrupt"
    ]) == 1


def test_graph_version_incompatibility_fails_before_run_or_provider(tmp_path):
    current = _state("future-graph", workflow_id="closed-loop-agent-v99")
    runner, surrogate, optimizer, hfss = _runner(tmp_path, current)
    with pytest.raises(WorkflowError, match="Graph/workflow identity is incompatible"):
        runner.invoke(current)
    assert runner.nodes.harness.store.count_rows("runs") == 0
    assert surrogate.call_count == optimizer.call_count == hfss.call_count == 0
