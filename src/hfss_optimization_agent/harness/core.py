"""Harness facade: the only formal-workflow gateway to physical side effects."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Callable, Generic, Iterator, Mapping, TypeVar
import threading
import uuid

from ..domain.canonical_json import canonical_dumps, canonical_loads
from .artifacts import ArtifactStore
from .execution_policy import ExecutionPolicy
from .errors import WorkflowError
from .fault_injection import (
    CrashPoint,
    FaultInjector,
    InjectedProcessCrash,
    NoFaultInjector,
)
from .reconciliation import (
    ReconciliationRequest,
    ReconciliationResolution,
)
from .run_store import (
    AcquireDisposition,
    ApprovalGrant,
    ArtifactReceipt,
    OperationRequest,
    OperationSnapshot,
    OperationStatus,
    RunInvocationClaim,
    RunInvocationDisposition,
    RunStore,
)


T = TypeVar("T")


class OperationUnknownError(WorkflowError):
    def __init__(self, operation: OperationSnapshot) -> None:
        self.operation = operation
        super().__init__(
            f"operation {operation.operation_id} has UNKNOWN physical outcome; "
            "explicit reconciliation is required"
        )


class OperationFailedError(WorkflowError):
    def __init__(self, operation: OperationSnapshot) -> None:
        self.operation = operation
        super().__init__(
            f"operation {operation.operation_id} failed and is not automatically retried"
        )


@dataclass(frozen=True, slots=True)
class HarnessSettings:
    budget_limit: int = 1000
    operation_costs: Mapping[str, int] = field(
        default_factory=lambda: {
            "sparameters": 1,
            "optimizer": 10,
            "hfss": 100,
            "artifact": 0,
        }
    )
    approvals: tuple[ApprovalGrant, ...] = ()
    required_approval_scopes: Mapping[str, str] = field(default_factory=dict)
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    operation_lease_seconds: float = 300.0
    run_invocation_lease_seconds: float = 60.0
    in_flight_wait_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.budget_limit, int) or self.budget_limit < 0:
            raise ValueError("Harness budget_limit must be a non-negative integer")
        if (
            self.operation_lease_seconds <= 0
            or self.run_invocation_lease_seconds <= 0
            or self.in_flight_wait_seconds <= 0
        ):
            raise ValueError("Harness lease/wait timeouts must be positive")
        for kind, cost in self.operation_costs.items():
            if not isinstance(kind, str) or not kind or not isinstance(cost, int) or cost < 0:
                raise ValueError("Harness operation costs must be non-negative integers")
        if not set(self.required_approval_scopes).issubset(self.operation_costs):
            raise ValueError("Harness approval policy references an unknown operation kind")
        for kind, scope in self.required_approval_scopes.items():
            if not isinstance(kind, str) or not kind or not isinstance(scope, str) or not scope:
                raise ValueError("Harness approval policy keys/scopes must be non-empty strings")


@dataclass(frozen=True, slots=True)
class HarnessExecution(Generic[T]):
    value: T
    operation: OperationSnapshot
    artifact: ArtifactReceipt
    cached: bool
    supporting_artifacts: tuple[ArtifactReceipt, ...] = ()


@dataclass(frozen=True, slots=True)
class ReconciliationExecution(Generic[T]):
    operation: OperationSnapshot
    evidence_artifact: ArtifactReceipt
    value: T | None = None
    result_artifact: ArtifactReceipt | None = None


class HarnessCore:
    """Claims an idempotent action before invoking a provider outside the transaction."""

    def __init__(
        self,
        *,
        store: RunStore,
        artifacts: ArtifactStore,
        settings: HarnessSettings | None = None,
        owner_token: str | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.settings = settings or HarnessSettings()
        self.owner_token = owner_token or f"owner_{uuid.uuid4().hex}"
        self.fault_injector = fault_injector or NoFaultInjector()
        self._invocation_local = threading.local()

    def ensure_run(self, manifest: Any) -> None:
        self.store.register_run(
            manifest,
            budget_limit=self.settings.budget_limit,
            operation_costs=self.settings.operation_costs,
            required_approval_scopes=self.settings.required_approval_scopes,
            execution_policy=self.settings.execution_policy,
            approvals=self.settings.approvals,
        )

    def cost_for(self, kind: str) -> int:
        if kind not in self.settings.operation_costs:
            raise ValueError(f"unregistered Harness operation kind {kind!r}")
        return int(self.settings.operation_costs[kind])

    @contextmanager
    def run_invocation(self, run_id: str) -> Iterator[RunInvocationClaim]:
        """Serialize Graph writers for one Run and continuously renew their fence."""

        deadline = time.monotonic() + self.settings.in_flight_wait_seconds
        while True:
            claim = self.store.claim_run_invocation(
                run_id,
                owner_token=self.owner_token,
                lease_seconds=self.settings.run_invocation_lease_seconds,
            )
            if claim.disposition is not RunInvocationDisposition.IN_FLIGHT:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Run {run_id} is already being invoked")
            time.sleep(0.01)
        if claim.disposition is RunInvocationDisposition.TERMINAL:
            yield claim
            return
        self._invocation_local.run_id = run_id
        self._invocation_local.fence = claim.fence
        heartbeat_stop = threading.Event()

        def heartbeat() -> None:
            interval = max(0.05, self.settings.run_invocation_lease_seconds / 3.0)
            while not heartbeat_stop.wait(interval):
                try:
                    if not self.store.heartbeat_run_invocation(
                        run_id,
                        owner_token=self.owner_token,
                        fence=claim.fence,
                        lease_seconds=self.settings.run_invocation_lease_seconds,
                    ):
                        return
                except Exception:
                    continue

        heartbeat_thread = threading.Thread(
            target=heartbeat,
            name=f"run-heartbeat-{run_id}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            yield claim
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1.0)
            self.store.release_run_invocation(
                run_id, owner_token=self.owner_token, fence=claim.fence
            )
            self._invocation_local.run_id = None
            self._invocation_local.fence = None

    def emit_event(self, run_id: str, event_type: str, payload: Any) -> None:
        self.store.append_event(run_id, event_type, payload)

    @staticmethod
    def _raise_terminal(operation: OperationSnapshot) -> None:
        if operation.status is OperationStatus.UNKNOWN:
            raise OperationUnknownError(operation)
        if operation.status is OperationStatus.FAILED:
            raise OperationFailedError(operation)
        raise RuntimeError(f"operation {operation.operation_id} is not reusable")

    def _cached(
        self,
        operation: OperationSnapshot,
        decoder: Callable[[Any], T],
    ) -> HarnessExecution[T]:
        if operation.result_json is None or operation.artifact is None:
            raise RuntimeError("SUCCEEDED operation is missing its durable result receipt")
        self.artifacts.verify(operation.artifact)
        all_artifacts = self.store.list_operation_artifacts(operation.operation_id)
        supporting = tuple(
            artifact
            for artifact in all_artifacts
            if artifact.artifact_id != operation.artifact.artifact_id
        )
        for artifact in supporting:
            self.artifacts.verify(artifact)
        value = decoder(canonical_loads(operation.result_json))
        return HarnessExecution(value, operation, operation.artifact, True, supporting)

    def execute(
        self,
        request: OperationRequest,
        provider: Callable[[], T],
        *,
        decoder: Callable[[Any], T],
        native_artifact_paths: Callable[[T], tuple[Path, ...]] | None = None,
    ) -> HarnessExecution[T]:
        run_fence = None
        run_owner_token = None
        if getattr(self._invocation_local, "run_id", None) == request.run_id:
            run_fence = getattr(self._invocation_local, "fence", None)
            run_owner_token = self.owner_token
        acquired = self.store.acquire_operation(
            request,
            owner_token=self.owner_token,
            lease_seconds=self.settings.operation_lease_seconds,
            run_owner_token=run_owner_token,
            run_fence=run_fence,
        )
        if acquired.disposition is AcquireDisposition.CACHED:
            return self._cached(acquired.operation, decoder)
        if acquired.disposition is AcquireDisposition.IN_FLIGHT:
            completed = self.store.wait_for_operation(
                acquired.operation.operation_id,
                timeout_seconds=self.settings.in_flight_wait_seconds,
            )
            if completed.status is OperationStatus.SUCCEEDED:
                return self._cached(completed, decoder)
            self._raise_terminal(completed)
        if acquired.disposition in {AcquireDisposition.FAILED, AcquireDisposition.UNKNOWN}:
            self._raise_terminal(acquired.operation)
        operation = acquired.operation
        if operation.attempt_id is None:
            raise RuntimeError("owned operation has no attempt identity")
        self.fault_injector.hit(CrashPoint.ACTION_AFTER_CLAIM)
        heartbeat_stop = threading.Event()

        def heartbeat() -> None:
            interval = max(0.05, self.settings.operation_lease_seconds / 3.0)
            while not heartbeat_stop.wait(interval):
                try:
                    if not self.store.heartbeat_operation(
                        operation.operation_id,
                        owner_token=self.owner_token,
                        lease_seconds=self.settings.operation_lease_seconds,
                    ):
                        return
                except Exception:
                    # A transient heartbeat failure cannot make a second physical
                    # launch safe. The durable lease remains conservative.
                    continue

        heartbeat_thread = threading.Thread(
            target=heartbeat,
            name=f"harness-heartbeat-{operation.operation_id}",
            daemon=True,
        )
        heartbeat_thread.start()
        provider_completed = False
        try:
            value = provider()
            provider_completed = True
            self.fault_injector.hit(CrashPoint.ACTION_AFTER_PROVIDER)
            result_json = canonical_dumps(value)
            decoded_value = decoder(canonical_loads(result_json))
            result_json = canonical_dumps(decoded_value)
            artifact, _path = self.artifacts.write_immutable(
                run_id=request.run_id,
                operation_id=operation.operation_id,
                attempt_id=operation.attempt_id,
                role=request.result_role,
                value=decoded_value,
            )
            supporting: list[ArtifactReceipt] = []
            if native_artifact_paths is not None:
                native_paths = tuple(
                    sorted(
                        {Path(path).resolve(strict=True) for path in native_artifact_paths(decoded_value)},
                        key=lambda path: str(path).casefold(),
                    )
                )
                for index, native_path in enumerate(native_paths):
                    receipt, _frozen_path = self.artifacts.write_immutable_file(
                        run_id=request.run_id,
                        operation_id=operation.operation_id,
                        attempt_id=operation.attempt_id,
                        role=f"native_{index:03d}",
                        source_path=native_path,
                    )
                    supporting.append(receipt)
            self.fault_injector.hit(CrashPoint.ACTION_AFTER_ARTIFACT_FREEZE)
            completed = self.store.complete_operation(
                operation.operation_id,
                attempt_id=operation.attempt_id,
                owner_token=self.owner_token,
                result_json=result_json,
                artifact=artifact,
                supporting_artifacts=tuple(supporting),
            )
            self.fault_injector.hit(CrashPoint.ACTION_AFTER_RECEIPT_COMMIT)
            return HarnessExecution(
                decoded_value, completed, artifact, False, tuple(supporting)
            )
        except InjectedProcessCrash:
            raise
        except BaseException as exc:
            ambiguous = provider_completed or request.ambiguity_on_exception
            try:
                failed = self.store.fail_operation(
                    operation.operation_id,
                    attempt_id=operation.attempt_id,
                    owner_token=self.owner_token,
                    error={"type": type(exc).__name__, "message": str(exc)},
                    ambiguous=ambiguous,
                )
            except BaseException:
                # The durable lease remains; a later recovery can only move it to UNKNOWN.
                raise
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if ambiguous:
                raise OperationUnknownError(failed) from exc
            raise OperationFailedError(failed) from exc
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1.0)

    def reconcile_unknown(
        self,
        request: ReconciliationRequest,
        *,
        recovered_result: Any = None,
        decoder: Callable[[Any], T] | None = None,
        as_of: str | None = None,
    ) -> ReconciliationExecution[T]:
        """Apply explicit operator evidence to UNKNOWN without invoking a provider."""

        operation = self.store.get_operation(request.operation_id)
        if operation is None:
            raise RuntimeError("reconciliation references an unknown operation")
        existing = self.store.get_reconciliation(request.operation_id)
        if existing is not None:
            if existing.request != request:
                raise RuntimeError("operation already has a different reconciliation decision")
            artifacts = self.store.list_operation_artifacts(request.operation_id)
            evidence_artifact = next(
                (
                    artifact
                    for artifact in artifacts
                    if artifact.artifact_id == existing.evidence_artifact_id
                ),
                None,
            )
            if evidence_artifact is None:
                raise RuntimeError("reconciliation references missing evidence artifact")
            self.artifacts.verify(evidence_artifact)
            decoded_value: T | None = None
            if request.resolution is ReconciliationResolution.CONFIRMED_SUCCEEDED:
                if decoder is None or operation.result_json is None or operation.artifact is None:
                    raise ValueError(
                        "confirmed success replay requires its strict result decoder/receipt"
                    )
                self.artifacts.verify(operation.artifact)
                decoded_value = decoder(canonical_loads(operation.result_json))
            return ReconciliationExecution(
                operation=operation,
                evidence_artifact=evidence_artifact,
                value=decoded_value,
                result_artifact=operation.artifact,
            )
        if operation.status is not OperationStatus.UNKNOWN:
            raise RuntimeError("only an UNKNOWN operation may be reconciled")
        if operation.attempt_id != request.attempt_id or operation.run_id != request.run_id:
            raise RuntimeError("reconciliation operation/attempt identity mismatch")
        evidence_artifact, _evidence_path = self.artifacts.write_immutable(
            run_id=request.run_id,
            operation_id=request.operation_id,
            attempt_id=request.attempt_id,
            role="reconciliation_evidence",
            value=request,
        )
        decoded_value: T | None = None
        result_json: str | None = None
        result_artifact: ArtifactReceipt | None = None
        if request.resolution is ReconciliationResolution.CONFIRMED_SUCCEEDED:
            if decoder is None:
                raise ValueError("confirmed success requires a strict result decoder")
            result_json = canonical_dumps(recovered_result)
            decoded_value = decoder(canonical_loads(result_json))
            result_json = canonical_dumps(decoded_value)
            result_artifact, _result_path = self.artifacts.write_immutable(
                run_id=request.run_id,
                operation_id=request.operation_id,
                attempt_id=request.attempt_id,
                role=operation.result_role,
                value=decoded_value,
            )
        elif recovered_result is not None or decoder is not None:
            raise ValueError("confirmed failure cannot attach a recovered result")
        reconciled = self.store.reconcile_operation(
            request,
            evidence_artifact=evidence_artifact,
            result_json=result_json,
            result_artifact=result_artifact,
            as_of=as_of,
        )
        self.artifacts.verify(evidence_artifact)
        if result_artifact is not None:
            self.artifacts.verify(result_artifact)
        return ReconciliationExecution(
            operation=reconciled,
            evidence_artifact=evidence_artifact,
            value=decoded_value,
            result_artifact=result_artifact,
        )
    def record_artifact(
        self,
        *,
        run_id: str,
        subject_id: str,
        idempotency_key: str,
        role: str,
        value: T,
        decoder: Callable[[Any], T] = lambda item: item,
    ) -> HarnessExecution[T]:
        return self.execute(
            OperationRequest(
                run_id=run_id,
                kind="artifact",
                subject_id=subject_id,
                idempotency_key=idempotency_key,
                payload={"role": role, "value": value},
                result_role=role,
                estimated_cost=self.cost_for("artifact"),
            ),
            lambda: value,
            decoder=decoder,
        )
