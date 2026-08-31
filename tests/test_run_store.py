"""Offline concurrency, crash-safety, budget and approval tests for Harness Core."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import pytest

from hfss_optimization_agent.agent.comparison_state import (
    create_comparison_state,
    with_changes,
)
from hfss_optimization_agent.harness.artifacts import ArtifactStore
from hfss_optimization_agent.harness.core import (
    HarnessCore,
    HarnessSettings,
    OperationUnknownError,
)
from hfss_optimization_agent.harness.execution_policy import ExecutionPolicy
from hfss_optimization_agent.harness.run_store import (
    AcquireDisposition,
    ApprovalGrant,
    ApprovalRequired,
    BudgetExceeded,
    CheckpointConflict,
    IdempotencyConflict,
    OperationRequest,
    OperationStatus,
    PhysicalLaunchLimitExceeded,
    RunStatus,
    RunIdentityConflict,
    RunStore,
    RunStoreError,
)
from hfss_optimization_agent.domain.canonical_json import canonical_dumps
from hfss_optimization_agent.parameters.nine_parameter_schema import supplied_baseline_candidate


def state(task_id: str = "phase2-run"):
    return create_comparison_state(
        task_id=task_id,
        run_id=f"run:{task_id}",
        comparison_context_id=f"context:{task_id}",
        baseline_parameters=supplied_baseline_candidate(),
        created_at="2026-08-21T10:00:00+00:00",
    )


def harness(
    tmp_path: Path,
    current,
    *,
    budget=100,
    hfss_cost=1,
    approvals=(),
    required_approval_scopes=None,
    execution_policy=ExecutionPolicy(),
):
    store = RunStore(tmp_path / ".runstore" / "runstore.sqlite3")
    settings = HarnessSettings(
        budget_limit=budget,
        operation_costs={"hfss": hfss_cost, "artifact": 0},
        approvals=approvals,
        required_approval_scopes=required_approval_scopes or {},
        execution_policy=execution_policy,
        operation_lease_seconds=10.0,
        in_flight_wait_seconds=5.0,
    )
    core = HarnessCore(
        store=store,
        artifacts=ArtifactStore(tmp_path, current["manifest"].task_id),
        settings=settings,
    )
    core.ensure_run(current["manifest"])
    return core


def request(current, key="same", *, cost=1, payload=None, ambiguity=False):
    return OperationRequest(
        run_id=current["manifest"].run_id,
        kind="hfss",
        subject_id="baseline",
        idempotency_key=key,
        payload=payload or {"candidate_id": "baseline"},
        result_role="provider_result",
        estimated_cost=cost,
        ambiguity_on_exception=ambiguity,
    )


def test_identical_concurrent_request_has_one_physical_start(tmp_path):
    current = state()
    first = harness(tmp_path, current)
    second = harness(tmp_path, current)
    entered = threading.Event()
    release = threading.Event()
    counter_lock = threading.Lock()
    calls = 0

    def provider():
        nonlocal calls
        with counter_lock:
            calls += 1
        entered.set()
        assert release.wait(5.0)
        return {"candidate_id": "baseline", "score": 1}

    operation_request = request(current)
    original_acquire = second.store.acquire_operation
    follower_claimed = threading.Event()

    def tracked_acquire(*args, **kwargs):
        acquired = original_acquire(*args, **kwargs)
        if acquired.disposition is AcquireDisposition.IN_FLIGHT:
            follower_claimed.set()
        return acquired

    second.store.acquire_operation = tracked_acquire
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(
            first.execute, operation_request, provider, decoder=lambda value: value
        )
        assert entered.wait(5.0)
        follower = pool.submit(
            second.execute, operation_request, provider, decoder=lambda value: value
        )
        assert follower_claimed.wait(5.0)
        assert calls == 1
        release.set()
        first_result = owner.result(timeout=5.0)
        second_result = follower.result(timeout=5.0)

    assert calls == 1
    assert first_result.operation.operation_id == second_result.operation.operation_id
    assert first_result.artifact == second_result.artifact
    assert {first_result.cached, second_result.cached} == {False, True}
    assert first.store.count_attempts(operation_request.operation_id) == 1
    starts = [
        event
        for event in first.store.list_events(current["manifest"].run_id)
        if event["event_type"] == "physical_start_authorized"
    ]
    assert len(starts) == 1


def test_unknown_is_persistent_and_never_automatically_retried(tmp_path):
    current = state("unknown-run")
    core = harness(tmp_path, current)
    calls = 0

    def ambiguous_provider():
        nonlocal calls
        calls += 1
        raise RuntimeError("connection lost after launch")

    operation_request = request(current, ambiguity=True)
    with pytest.raises(OperationUnknownError):
        core.execute(operation_request, ambiguous_provider, decoder=lambda value: value)
    reopened = harness(tmp_path, current)
    with pytest.raises(OperationUnknownError):
        reopened.execute(operation_request, ambiguous_provider, decoder=lambda value: value)

    assert calls == 1
    assert reopened.store.count_attempts(operation_request.operation_id) == 1
    assert reopened.store.get_operation(operation_request.operation_id).status is OperationStatus.UNKNOWN
    assert reopened.store.get_run(current["manifest"].run_id).status is RunStatus.WAITING_RECONCILIATION
    assert reopened.store.get_run(current["manifest"].run_id).budget_reserved == 1


def test_budget_reservation_is_atomic_and_not_released_by_completed_action(tmp_path):
    current = state("budget-run")
    first = harness(tmp_path, current, budget=10, hfss_cost=6)
    second = harness(tmp_path, current, budget=10, hfss_cost=6)
    start = threading.Barrier(3)
    counter_lock = threading.Lock()
    calls = 0

    def provider():
        nonlocal calls
        with counter_lock:
            calls += 1
        return {"ok": True}

    def invoke(core, operation_request):
        start.wait(timeout=5.0)
        try:
            return core.execute(operation_request, provider, decoder=lambda value: value)
        except BudgetExceeded as exc:
            return exc

    first_request = request(current, "budget-a", cost=6, payload={"candidate": "a"})
    second_request = request(current, "budget-b", cost=6, payload={"candidate": "b"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(invoke, first, first_request),
            pool.submit(invoke, second, second_request),
        ]
        start.wait(timeout=5.0)
        outcomes = [future.result(timeout=5.0) for future in futures]
    assert sum(isinstance(item, BudgetExceeded) for item in outcomes) == 1
    rejected_request = (
        first_request if isinstance(outcomes[0], BudgetExceeded) else second_request
    )

    reopened = harness(tmp_path, current, budget=10, hfss_cost=6)
    with pytest.raises(BudgetExceeded):
        reopened.execute(rejected_request, provider, decoder=lambda value: value)
    snapshot = reopened.store.get_run(current["manifest"].run_id)
    assert snapshot.budget_reserved == 6
    assert snapshot.budget_reserved <= snapshot.budget_limit
    assert calls == 1


def test_approval_and_idempotency_are_checked_before_physical_start(tmp_path):
    current = state("approval-run")
    core = harness(
        tmp_path,
        current,
        budget=10,
        hfss_cost=5,
        required_approval_scopes={"hfss": "real_hfss"},
    )
    missing_scope = request(current, "missing-scope", cost=5, ambiguity=True)
    with pytest.raises(ApprovalRequired):
        core.execute(missing_scope, lambda: {"unexpected": True}, decoder=lambda value: value)
    approval_request = OperationRequest(
        run_id=current["manifest"].run_id,
        kind="hfss",
        subject_id="baseline",
        idempotency_key="approved-action",
        payload={"candidate": "baseline"},
        result_role="hfss_result",
        estimated_cost=5,
        approval_scope="real_hfss",
        approval_id="approval-1",
        ambiguity_on_exception=True,
    )
    with pytest.raises(ApprovalRequired):
        core.execute(approval_request, lambda: {"unexpected": True}, decoder=lambda value: value)
    assert core.store.count_attempts() == 0
    assert core.store.get_run(current["manifest"].run_id).budget_reserved == 0

    approved_state = state("approved-run")
    approved = harness(
        tmp_path,
        approved_state,
        hfss_cost=5,
        approvals=(ApprovalGrant("approval-1", "real_hfss", "user"),),
        required_approval_scopes={"hfss": "real_hfss"},
    )
    valid = OperationRequest(
        run_id=approved_state["manifest"].run_id,
        kind="hfss",
        subject_id="baseline",
        idempotency_key="approved-action",
        payload={"candidate": "baseline"},
        result_role="hfss_result",
        estimated_cost=5,
        approval_scope="real_hfss",
        approval_id="approval-1",
        ambiguity_on_exception=True,
    )
    approved.execute(valid, lambda: {"ok": True}, decoder=lambda value: value)
    conflicting = OperationRequest(
        run_id=valid.run_id,
        kind=valid.kind,
        subject_id=valid.subject_id,
        idempotency_key=valid.idempotency_key,
        payload={"candidate": "different"},
        result_role=valid.result_role,
        estimated_cost=valid.estimated_cost,
        approval_scope=valid.approval_scope,
        approval_id=valid.approval_id,
        ambiguity_on_exception=True,
    )
    with pytest.raises(IdempotencyConflict):
        approved.execute(conflicting, lambda: {"unexpected": True}, decoder=lambda value: value)
    assert approved.store.count_attempts(valid.operation_id) == 1
    approved.store.revoke_approval(valid.run_id, "approval-1", "real_hfss")
    revoked_request = OperationRequest(
        run_id=valid.run_id,
        kind="hfss",
        subject_id="candidate",
        idempotency_key="revoked-action",
        payload={"candidate": "candidate"},
        result_role="hfss_result",
        estimated_cost=5,
        approval_scope="real_hfss",
        approval_id="approval-1",
        ambiguity_on_exception=True,
    )
    with pytest.raises(ApprovalRequired):
        approved.execute(
            revoked_request, lambda: {"unexpected": True}, decoder=lambda value: value
        )
    assert approved.store.count_attempts() == 1
    cross_run_state = state("cross-run-approval")
    with pytest.raises(RunIdentityConflict, match="different Run"):
        harness(
            tmp_path,
            cross_run_state,
            hfss_cost=5,
            approvals=(ApprovalGrant("approval-1", "real_hfss", "user"),),
            required_approval_scopes={"hfss": "real_hfss"},
        )

    expired_state = state("expired-approval")
    expired = harness(
        tmp_path,
        expired_state,
        hfss_cost=5,
        approvals=(
            ApprovalGrant(
                "expired",
                "real_hfss",
                "user",
                expires_at="2000-01-01T00:00:00+00:00",
            ),
        ),
        required_approval_scopes={"hfss": "real_hfss"},
    )
    expired_request = OperationRequest(
        run_id=expired_state["manifest"].run_id,
        kind="hfss",
        subject_id="baseline",
        idempotency_key="expired-action",
        payload={"candidate": "baseline"},
        result_role="hfss_result",
        estimated_cost=5,
        approval_scope="real_hfss",
        approval_id="expired",
        ambiguity_on_exception=True,
    )
    with pytest.raises(ApprovalRequired):
        expired.execute(
            expired_request, lambda: {"unexpected": True}, decoder=lambda value: value
        )
    assert expired.store.count_rows(
        "attempts", run_id=expired_state["manifest"].run_id
    ) == 0


def test_immutable_artifact_layout_rejects_escape_and_detects_tamper(tmp_path):
    with pytest.raises(ValueError):
        ArtifactStore(tmp_path, "../escape")
    current = state("artifact-run")
    core = harness(tmp_path, current)
    result = core.record_artifact(
        run_id=current["manifest"].run_id,
        subject_id="run",
        idempotency_key="manifest-artifact",
        role="manifest",
        value={"version": 2},
    )
    path = core.artifacts.verify(result.artifact)
    assert path.relative_to(core.artifacts.task_dir).parts[:1] == ("artifacts",)
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(RuntimeError, match="digest"):
        core.artifacts.verify(result.artifact)


def test_provider_native_file_is_frozen_registered_and_reused(tmp_path):
    current = state("native-artifact-run")
    core = harness(tmp_path, current)
    source = tmp_path / "provider" / "baseline.aedt"
    source.parent.mkdir()
    source.write_bytes(b"completed-aedt-v1")
    operation_request = request(current, "native-hfss")

    first = core.execute(
        operation_request,
        lambda: {"candidate_id": "baseline", "project_path": str(source)},
        decoder=lambda value: value,
        native_artifact_paths=lambda value: (Path(value["project_path"]),),
    )
    assert first.cached is False
    assert len(first.supporting_artifacts) == 1
    native = first.supporting_artifacts[0]
    frozen = core.artifacts.verify(native)
    assert frozen.read_bytes() == b"completed-aedt-v1"
    assert native.media_type == "application/octet-stream"
    assert core.store.list_operation_artifacts(first.operation.operation_id) == (
        first.supporting_artifacts[0],
        first.artifact,
    )

    source.write_bytes(b"mutable-provider-output-v2")
    replay = core.execute(
        operation_request,
        lambda: pytest.fail("cached native operation must not rerun the provider"),
        decoder=lambda value: value,
        native_artifact_paths=lambda value: (Path(value["project_path"]),),
    )
    assert replay.cached is True
    assert replay.supporting_artifacts == first.supporting_artifacts
    assert core.artifacts.verify(replay.supporting_artifacts[0]).read_bytes() == b"completed-aedt-v1"


def test_concurrent_native_freeze_publishes_one_complete_object(tmp_path):
    store = ArtifactStore(tmp_path, "native-concurrent")
    source = tmp_path / "touchstone.s2p"
    source.write_bytes(b"! touchstone\n# Hz S RI R 50\n")

    def freeze():
        return store.write_immutable_file(
            run_id="run:native",
            operation_id="op_1234567890abcdef",
            attempt_id="att_1234567890abcdef",
            role="native_000",
            source_path=source,
        )[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = tuple(pool.map(lambda _index: freeze(), range(2)))
    assert receipts[0] == receipts[1]
    assert store.verify(receipts[0]).read_bytes() == source.read_bytes()


def test_crashed_running_attempt_keeps_budget_and_becomes_unknown(tmp_path):
    current = state("lease-crash")
    core = harness(tmp_path, current, budget=10, hfss_cost=6)
    operation_request = request(
        current, "leased", cost=6, payload={"candidate": "baseline"}
    )
    acquired = core.store.acquire_operation(
        operation_request,
        owner_token="crashed-owner",
        lease_seconds=1.0,
    )
    assert acquired.operation.status is OperationStatus.RUNNING
    assert core.store.get_run(current["manifest"].run_id).budget_reserved == 6
    replay = core.store.acquire_operation(
        operation_request,
        owner_token="replacement-owner",
        lease_seconds=1.0,
    )
    assert replay.disposition is AcquireDisposition.IN_FLIGHT
    assert core.store.count_rows(
        "budget_reservations", run_id=current["manifest"].run_id
    ) == 1
    other = request(current, "other", cost=6, payload={"candidate": "other"})
    with pytest.raises(BudgetExceeded):
        core.store.acquire_operation(
            other,
            owner_token="other-owner",
            lease_seconds=1.0,
        )
    assert core.store.expire_stale_operations(
        current["manifest"].run_id,
        as_of="2999-01-01T00:00:00+00:00",
    ) == 1
    reopened = harness(tmp_path, current, budget=10, hfss_cost=6)
    assert reopened.store.get_operation(operation_request.operation_id).status is OperationStatus.UNKNOWN
    assert reopened.store.get_run(current["manifest"].run_id).budget_reserved == 6
    assert reopened.store.count_attempts(operation_request.operation_id) == 1


def test_sqlite_checkpoint_compare_and_swap_rejects_lost_update(tmp_path):
    current = state("checkpoint-cas")
    core = harness(tmp_path, current)
    state_json = canonical_dumps(current)
    first_revision = core.store.save_checkpoint(
        current["manifest"].run_id,
        state_json,
        expected_revision=0,
    )
    assert first_revision == 1
    changed = dict(current)
    changed["execution_trace"] = ("concurrent",)
    with pytest.raises(CheckpointConflict):
        core.store.save_checkpoint(
            current["manifest"].run_id,
            canonical_dumps(changed),
            expected_revision=0,
        )
    assert core.store.get_run(current["manifest"].run_id).latest_checkpoint_revision == 1


def test_authoritative_policy_rejects_spoofed_cost_and_unknown_kind(tmp_path):
    current = state("policy-authority")
    core = harness(tmp_path, current, budget=10, hfss_cost=6)
    spoofed = request(current, "free-hfss", cost=0)
    with pytest.raises(RunStoreError, match="authoritative value"):
        core.execute(spoofed, lambda: {"unexpected": True}, decoder=lambda value: value)
    unknown = OperationRequest(
        run_id=current["manifest"].run_id,
        kind="unregistered-tool",
        subject_id="x",
        idempotency_key="unknown-kind",
        payload={"x": 1},
        result_role="result",
        estimated_cost=0,
    )
    with pytest.raises(RunStoreError, match="not registered"):
        core.execute(unknown, lambda: {"unexpected": True}, decoder=lambda value: value)
    assert core.store.count_attempts() == 0
    assert core.store.get_run(current["manifest"].run_id).budget_reserved == 0


def test_semantically_identical_request_deduplicates_even_with_different_caller_keys(tmp_path):
    current = state("semantic-operation-key")
    core = harness(tmp_path, current)
    calls = 0

    def provider():
        nonlocal calls
        calls += 1
        return {"ok": True}

    first = request(current, "caller-key-a", payload={"candidate": "same"})
    second = request(current, "caller-key-b", payload={"candidate": "same"})
    first_result = core.execute(first, provider, decoder=lambda value: value)
    second_result = core.execute(second, provider, decoder=lambda value: value)
    assert calls == 1
    assert first_result.operation.operation_id == second_result.operation.operation_id
    assert second_result.cached is True
    assert core.store.count_rows("operations", run_id=first.run_id) == 1


def test_historical_checkpoint_digest_cannot_bypass_cas_or_complete_run(tmp_path):
    current = state("historical-cas")
    core = harness(tmp_path, current)
    first = with_changes(current, {"execution_trace": ("first",)})
    second = with_changes(current, {"execution_trace": ("second",)})
    assert core.store.save_checkpoint(
        current["manifest"].run_id,
        canonical_dumps(first),
        expected_revision=0,
    ) == 1
    assert core.store.save_checkpoint(
        current["manifest"].run_id,
        canonical_dumps(second),
        expected_revision=1,
    ) == 2
    with pytest.raises(CheckpointConflict):
        core.store.save_checkpoint(
            current["manifest"].run_id,
            canonical_dumps(first),
            expected_revision=1,
            complete=True,
            terminal_status=first["status"],
        )
    run = core.store.get_run(current["manifest"].run_id)
    assert run.status is RunStatus.ACTIVE
    assert run.latest_checkpoint_revision == 2


def test_completed_run_store_calls_are_strictly_idempotent(tmp_path):
    current = state("terminal-noop")
    core = harness(tmp_path, current)
    terminal = dict(current)
    terminal["status"] = "failed"
    revision = core.store.save_checkpoint(
        current["manifest"].run_id,
        canonical_dumps(terminal),
        expected_revision=0,
        complete=True,
        terminal_status="failed",
    )
    before = {
        table: core.store.count_rows(table, run_id=current["manifest"].run_id)
        for table in ("approvals", "events", "checkpoints")
    }
    assert core.store.save_checkpoint(
        current["manifest"].run_id,
        canonical_dumps(terminal),
        expected_revision=revision,
        complete=True,
        terminal_status="failed",
    ) == revision
    core.store.register_run(
        current["manifest"],
        budget_limit=100,
        operation_costs={"hfss": 1, "artifact": 0},
        required_approval_scopes={},
        approvals=(ApprovalGrant("late-approval", "real_hfss", "user"),),
    )
    after = {
        table: core.store.count_rows(table, run_id=current["manifest"].run_id)
        for table in ("approvals", "events", "checkpoints")
    }
    assert after == before


def test_fresh_result_is_strictly_decoded_before_success_receipt(tmp_path):
    current = state("fresh-codec")
    core = harness(tmp_path, current)
    operation_request = request(current, "invalid-result")
    calls = 0

    def provider():
        nonlocal calls
        calls += 1
        return {"invalid": True}

    def reject(_value):
        raise ValueError("schema mismatch")

    with pytest.raises(OperationUnknownError):
        core.execute(operation_request, provider, decoder=reject)
    with pytest.raises(OperationUnknownError):
        harness(tmp_path, current).execute(operation_request, provider, decoder=reject)
    assert calls == 1
    assert core.store.get_operation(operation_request.operation_id).status is OperationStatus.UNKNOWN


def test_immutable_publish_is_concurrent_non_overwriting_and_crash_clean(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path, "immutable-publish")
    common = {
        "run_id": "run-id",
        "operation_id": "op_1234567890abcdef",
        "attempt_id": "att_1234567890abcdef",
        "role": "result",
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: store.write_immutable(**common, value={"v": 1}), range(2)))
    assert results[0][0] == results[1][0]
    assert results[0][1] == results[1][1]
    first_bytes = results[0][1].read_bytes()
    changed_receipt, changed_path = store.write_immutable(**common, value={"v": 2})
    assert changed_path != results[0][1]
    assert results[0][1].read_bytes() == first_bytes
    assert store.verify(changed_receipt) == changed_path

    from hfss_optimization_agent.harness import artifacts as artifact_module

    original_link = artifact_module.os.link

    def crash_before_publish(_source, _target):
        raise RuntimeError("injected publish crash")

    monkeypatch.setattr(artifact_module.os, "link", crash_before_publish)
    crash_args = {**common, "role": "crash_result"}
    with pytest.raises(RuntimeError, match="publish crash"):
        store.write_immutable(**crash_args, value={"v": 3})
    assert not list((store.task_dir / "artifacts").rglob("crash_result.*.json"))
    assert not list((store.task_dir / "artifacts").rglob(".crash_result.*.tmp"))
    monkeypatch.setattr(artifact_module.os, "link", original_link)
    receipt, path = store.write_immutable(**crash_args, value={"v": 3})
    assert store.verify(receipt) == path


def test_operation_heartbeat_prevents_live_attempt_from_expiring(tmp_path):
    current = state("operation-heartbeat")
    settings = HarnessSettings(
        budget_limit=10,
        operation_costs={"hfss": 1, "artifact": 0},
        operation_lease_seconds=0.3,
        run_invocation_lease_seconds=1.0,
        in_flight_wait_seconds=2.0,
    )
    core = HarnessCore(
        store=RunStore(tmp_path / ".runstore" / "runstore.sqlite3"),
        artifacts=ArtifactStore(tmp_path, current["manifest"].task_id),
        settings=settings,
    )
    core.ensure_run(current["manifest"])
    entered = threading.Event()
    release = threading.Event()
    operation_request = request(current, "heartbeat")

    def provider():
        entered.set()
        assert release.wait(3.0)
        return {"ok": True}

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            core.execute, operation_request, provider, decoder=lambda value: value
        )
        assert entered.wait(3.0)
        initial = core.store.get_operation(operation_request.operation_id).lease_expires_at
        deadline = time.monotonic() + 3.0
        renewed = initial
        while renewed == initial and time.monotonic() < deadline:
            time.sleep(0.02)
            renewed = core.store.get_operation(operation_request.operation_id).lease_expires_at
        assert renewed > initial
        assert core.store.expire_stale_operations(
            current["manifest"].run_id, as_of=initial
        ) == 0
        release.set()
        result = future.result(timeout=3.0)
    assert result.operation.status is OperationStatus.SUCCEEDED


def test_sqlite_read_connections_release_windows_file_handle(tmp_path):
    path = tmp_path / "close-check.sqlite3"
    store = RunStore(path)
    assert store.count_rows("operations") == 0
    renamed = tmp_path / "renamed.sqlite3"
    path.replace(renamed)
    renamed.replace(path)


def test_real_hfss_launch_limit_is_atomic_and_idempotent(tmp_path):
    authorization_id = "two-launch-canary"
    current = create_comparison_state(
        task_id="physical-launch-limit",
        run_id="run:physical-launch-limit",
        comparison_context_id="context:physical-launch-limit",
        baseline_parameters=supplied_baseline_candidate(),
        created_at="2026-08-21T10:00:00+00:00",
    )
    settings = {
        "budget": 100,
        "hfss_cost": 1,
        "approvals": (
            ApprovalGrant(authorization_id, "real_hfss", "readiness-manifest"),
        ),
        "required_approval_scopes": {"hfss": "real_hfss"},
        "execution_policy": ExecutionPolicy(2, 0),
    }
    cores = [harness(tmp_path, current, **settings) for _ in range(3)]
    barrier = threading.Barrier(4)
    counter_lock = threading.Lock()
    calls = 0

    def invoke(index):
        nonlocal calls
        operation_request = OperationRequest(
            run_id=current["manifest"].run_id,
            kind="hfss",
            subject_id=f"candidate-{index}",
            idempotency_key=f"physical-{index}",
            payload={"candidate_id": f"candidate-{index}"},
            result_role="hfss_result",
            estimated_cost=1,
            approval_scope="real_hfss",
            approval_id=authorization_id,
            ambiguity_on_exception=True,
        )
        barrier.wait(timeout=5.0)
        try:
            result = cores[index].execute(
                operation_request,
                lambda: counted_provider(index),
                decoder=lambda value: value,
            )
            return operation_request, result
        except PhysicalLaunchLimitExceeded as exc:
            return operation_request, exc

    def counted_provider(index):
        nonlocal calls
        with counter_lock:
            calls += 1
        return {"candidate_id": f"candidate-{index}", "success": True}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(invoke, index) for index in range(3)]
        barrier.wait(timeout=5.0)
        results = [future.result(timeout=5.0) for future in futures]

    rejected = [item for _request, item in results if isinstance(item, PhysicalLaunchLimitExceeded)]
    assert len(rejected) == 1
    assert calls == 2
    assert cores[0].store.count_rows("attempts", run_id=current["manifest"].run_id) == 2
    snapshot = cores[0].store.get_run(current["manifest"].run_id)
    assert snapshot.execution_policy == ExecutionPolicy(2, 0)
    assert snapshot.hfss_solve_launches_authorized == 2

    successful_request, successful_result = next(
        (request_item, result)
        for request_item, result in results
        if not isinstance(result, PhysicalLaunchLimitExceeded)
    )
    replay = cores[0].execute(
        successful_request,
        lambda: {"unexpected": True},
        decoder=lambda value: value,
    )
    assert replay.cached is True
    assert replay.operation.operation_id == successful_result.operation.operation_id
    assert calls == 2
    assert cores[0].store.get_run(current["manifest"].run_id).hfss_solve_launches_authorized == 2


def test_real_run_registration_rejects_missing_readiness_identity(tmp_path):
    current = create_comparison_state(
        task_id="unbound-real-run",
        baseline_parameters=supplied_baseline_candidate(),
        real_execution=True,
        config_fingerprints={"real_hfss_authorization_id": "approval-only"},
    )
    with pytest.raises(RunIdentityConflict, match="code revision"):
        harness(
            tmp_path,
            current,
            approvals=(ApprovalGrant("approval-only", "real_hfss", "test"),),
            required_approval_scopes={"hfss": "real_hfss"},
        )
