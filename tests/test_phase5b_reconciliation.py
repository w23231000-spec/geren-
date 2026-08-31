"""Phase 5B operator reconciliation and fail-closed recovery tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hfss_optimization_agent.agent.comparison_state import create_comparison_state
from hfss_optimization_agent.domain.canonical_json import CanonicalJsonError, canonical_dumps, canonical_loads
from hfss_optimization_agent.domain.contracts import FrozenMap
from hfss_optimization_agent.harness.artifacts import ArtifactStore
from hfss_optimization_agent.harness.core import HarnessCore, HarnessSettings, OperationUnknownError
from hfss_optimization_agent.harness.reconciliation import (
    RECONCILIATION_APPROVAL_SCOPE,
    RECONCILIATION_SCHEMA_VERSION,
    ReconciliationRequest,
    ReconciliationResolution,
)
from hfss_optimization_agent.harness.run_store import (
    ApprovalGrant,
    ApprovalRequired,
    OperationRequest,
    OperationStatus,
    RunStatus,
    RunStore,
    RunStoreError,
)
from hfss_optimization_agent.parameters.nine_parameter_schema import supplied_baseline_candidate


def _state(name: str):
    return create_comparison_state(
        task_id=name,
        run_id=f"run:{name}",
        comparison_context_id=f"context:{name}",
        baseline_parameters=supplied_baseline_candidate(),
        created_at="2026-08-24T00:00:00+00:00",
    )


def _core(tmp_path: Path, current, *, approved: bool = True) -> HarnessCore:
    approvals = (
        ApprovalGrant("operator-approval", RECONCILIATION_APPROVAL_SCOPE, "operator"),
    ) if approved else ()
    core = HarnessCore(
        store=RunStore(tmp_path / ".runstore" / "runstore.sqlite3"),
        artifacts=ArtifactStore(tmp_path, current["manifest"].task_id),
        settings=HarnessSettings(
            budget_limit=10,
            operation_costs={"hfss": 6},
            approvals=approvals,
            operation_lease_seconds=1.0,
            in_flight_wait_seconds=1.0,
        ),
    )
    core.ensure_run(current["manifest"])
    return core


def _unknown(core: HarnessCore, current) -> OperationRequest:
    request = OperationRequest(
        run_id=current["manifest"].run_id,
        kind="hfss",
        subject_id="baseline",
        idempotency_key="unknown-action",
        payload={"candidate_id": "baseline"},
        result_role="hfss_result",
        estimated_cost=6,
        ambiguity_on_exception=True,
    )
    with pytest.raises(OperationUnknownError):
        core.execute(
            request,
            lambda: (_ for _ in ()).throw(RuntimeError("lost after launch")),
            decoder=lambda value: value,
        )
    return request


def _decision(request: OperationRequest, resolution: ReconciliationResolution):
    now = datetime.now(timezone.utc)
    operation_id = request.operation_id
    return ReconciliationRequest(
        schema_version=RECONCILIATION_SCHEMA_VERSION,
        reconciliation_id=f"reconcile:{operation_id}:{resolution.value}",
        run_id=request.run_id,
        operation_id=operation_id,
        attempt_id="placeholder",
        approval_id="operator-approval",
        issued_at=(now - timedelta(seconds=1)).isoformat(),
        expires_at=(now + timedelta(minutes=5)).isoformat(),
        resolution=resolution,
        reason="operator reviewed process and provider evidence",
        evidence=FrozenMap.from_mapping(
            {"source": "offline-chaos-test", "verified_no_processes": True}
        ),
    )


def _bound_decision(core, request, resolution):
    operation = core.store.get_operation(request.operation_id)
    decision = _decision(request, resolution)
    payload = canonical_loads(canonical_dumps(decision))
    payload["attempt_id"] = operation.attempt_id
    return ReconciliationRequest.from_dict(payload)


def test_reconciliation_contract_is_strict_and_round_trips(tmp_path):
    current = _state("reconciliation-contract")
    core = _core(tmp_path, current)
    request = _unknown(core, current)
    decision = _bound_decision(
        core, request, ReconciliationResolution.CONFIRMED_FAILED
    )
    assert ReconciliationRequest.from_dict(
        canonical_loads(canonical_dumps(decision))
    ) == decision
    malformed = canonical_loads(canonical_dumps(decision))
    malformed["unknown"] = True
    with pytest.raises(CanonicalJsonError, match="unknown fields"):
        ReconciliationRequest.from_dict(malformed)


def test_operator_confirmed_failure_is_atomic_auditable_and_never_retried(tmp_path):
    current = _state("reconciled-failure")
    core = _core(tmp_path, current)
    request = _unknown(core, current)
    decision = _bound_decision(
        core, request, ReconciliationResolution.CONFIRMED_FAILED
    )
    before_attempts = core.store.count_attempts(request.operation_id)
    before_budget = core.store.get_run(request.run_id).budget_reserved

    result = core.reconcile_unknown(decision)
    replay = core.reconcile_unknown(decision)

    assert result.operation.status is OperationStatus.FAILED
    assert replay.operation == result.operation
    assert core.store.count_attempts(request.operation_id) == before_attempts == 1
    assert core.store.get_run(request.run_id).budget_reserved == before_budget == 6
    assert core.store.get_run(request.run_id).status is RunStatus.ACTIVE
    assert core.store.count_rows("reconciliations", run_id=request.run_id) == 1
    reconciliation = core.store.get_reconciliation(request.operation_id)
    assert reconciliation.request == decision
    events = [
        event for event in core.store.list_events(request.run_id)
        if event["event_type"] == "operation_reconciled"
    ]
    assert len(events) == 1
    assert events[0]["payload"]["budget_refunded"] is False
    assert events[0]["payload"]["new_attempt_created"] is False
    with pytest.raises(Exception, match="not automatically retried"):
        core.execute(request, lambda: pytest.fail("must not rerun"), decoder=lambda value: value)


def test_operator_confirmed_success_requires_and_replays_strict_result(tmp_path):
    current = _state("reconciled-success")
    core = _core(tmp_path, current)
    request = _unknown(core, current)
    decision = _bound_decision(
        core, request, ReconciliationResolution.CONFIRMED_SUCCEEDED
    )
    with pytest.raises(ValueError, match="strict result decoder"):
        core.reconcile_unknown(decision, recovered_result={"success": True})

    result = core.reconcile_unknown(
        decision,
        recovered_result={"candidate_id": "baseline", "success": True},
        decoder=lambda value: value,
    )
    cached = core.execute(
        request,
        lambda: pytest.fail("reconciled success must replay without provider"),
        decoder=lambda value: value,
    )
    assert result.operation.status is OperationStatus.SUCCEEDED
    assert cached.cached is True
    assert cached.value == {"candidate_id": "baseline", "success": True}
    assert core.store.count_attempts(request.operation_id) == 1
    assert core.store.get_run(request.run_id).budget_reserved == 6


def test_reconciliation_rejects_missing_authority_expiry_and_wrong_identity(tmp_path):
    current = _state("reconciliation-authority")
    core = _core(tmp_path, current, approved=False)
    request = _unknown(core, current)
    decision = _bound_decision(
        core, request, ReconciliationResolution.CONFIRMED_FAILED
    )
    with pytest.raises(ApprovalRequired):
        core.reconcile_unknown(decision)
    assert core.store.get_operation(request.operation_id).status is OperationStatus.UNKNOWN

    approved_current = _state("reconciliation-expired")
    approved = _core(tmp_path, approved_current)
    approved_request = _unknown(approved, approved_current)
    expired = canonical_loads(canonical_dumps(
        _bound_decision(approved, approved_request, ReconciliationResolution.CONFIRMED_FAILED)
    ))
    expired["issued_at"] = "2000-01-01T00:00:00+00:00"
    expired["expires_at"] = "2000-01-01T00:01:00+00:00"
    with pytest.raises(ApprovalRequired):
        approved.reconcile_unknown(ReconciliationRequest.from_dict(expired))
    wrong = canonical_loads(canonical_dumps(
        _bound_decision(approved, approved_request, ReconciliationResolution.CONFIRMED_FAILED)
    ))
    wrong["attempt_id"] = "attempt:wrong"
    with pytest.raises(RuntimeError, match="identity"):
        approved.reconcile_unknown(ReconciliationRequest.from_dict(wrong))
    assert approved.store.count_rows("reconciliations", run_id=approved_request.run_id) == 0


def test_conflicting_second_reconciliation_is_rejected(tmp_path):
    current = _state("reconciliation-conflict")
    core = _core(tmp_path, current)
    request = _unknown(core, current)
    failed = _bound_decision(core, request, ReconciliationResolution.CONFIRMED_FAILED)
    core.reconcile_unknown(failed)
    conflicting = canonical_loads(canonical_dumps(failed))
    conflicting["reason"] = "different operator conclusion"
    conflicting["reconciliation_id"] = "reconcile:conflict"
    evidence, _ = core.artifacts.write_immutable(
        run_id=request.run_id,
        operation_id=request.operation_id,
        attempt_id=failed.attempt_id,
        role="reconciliation_evidence",
        value=ReconciliationRequest.from_dict(conflicting),
    )
    with pytest.raises(RunStoreError, match="different reconciliation"):
        core.store.reconcile_operation(
            ReconciliationRequest.from_dict(conflicting), evidence_artifact=evidence
        )

def test_reconciliation_approval_can_be_revoked_while_waiting(tmp_path):
    current = _state("reconciliation-revoked")
    core = _core(tmp_path, current)
    request = _unknown(core, current)
    assert core.store.get_run(request.run_id).status is RunStatus.WAITING_RECONCILIATION
    core.store.revoke_approval(
        request.run_id, "operator-approval", RECONCILIATION_APPROVAL_SCOPE
    )
    decision = _bound_decision(
        core, request, ReconciliationResolution.CONFIRMED_FAILED
    )
    with pytest.raises(ApprovalRequired):
        core.reconcile_unknown(decision)
    assert core.store.get_operation(request.operation_id).status is OperationStatus.UNKNOWN
