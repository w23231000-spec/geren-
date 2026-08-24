"""Transactional SQLite control plane for runs, actions, attempts, events and budgets."""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator, Mapping
import uuid

from ..domain.canonical_json import (
    CanonicalJsonError,
    canonical_dumps,
    canonical_loads,
)
from .execution_policy import ExecutionPolicy
from .reconciliation import (
    RECONCILIATION_APPROVAL_SCOPE,
    ReconciliationRequest,
    ReconciliationResolution,
    ReconciliationSnapshot,
)
from .real_hfss_safety import REQUIRED_PROVIDER_FINGERPRINTS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"


def manifest_identity_sha256(manifest: Any) -> str:
    """Hash immutable run identity while excluding observational creation time."""

    identity_payload = canonical_loads(canonical_dumps(manifest))
    if isinstance(identity_payload, dict):
        identity_payload.pop("created_at", None)
    return hashlib.sha256(canonical_dumps(identity_payload).encode("utf-8")).hexdigest()


class RunStatus(StrEnum):
    ACTIVE = "ACTIVE"
    WAITING_RECONCILIATION = "WAITING_RECONCILIATION"
    COMPLETED = "COMPLETED"


class OperationStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class AttemptStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ReservationStatus(StrEnum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class AcquireDisposition(StrEnum):
    OWNER = "OWNER"
    CACHED = "CACHED"
    IN_FLIGHT = "IN_FLIGHT"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class RunInvocationDisposition(StrEnum):
    OWNER = "OWNER"
    IN_FLIGHT = "IN_FLIGHT"
    TERMINAL = "TERMINAL"


class RunStoreError(RuntimeError):
    """Base error for durable control-plane invariants."""


class RunIdentityConflict(RunStoreError):
    pass


class IdempotencyConflict(RunStoreError):
    pass


class BudgetExceeded(RunStoreError):
    pass


class PhysicalLaunchLimitExceeded(RunStoreError):
    pass


class ApprovalRequired(RunStoreError):
    pass


class RunNotActionable(RunStoreError):
    pass


class CheckpointConflict(RunStoreError):
    pass

class CheckpointCorruption(RunStoreError):
    pass



@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    approval_id: str
    scope: str
    granted_by: str
    expires_at: str | None = None

    def __post_init__(self) -> None:
        for name in ("approval_id", "scope", "granted_by"):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        if self.expires_at is not None:
            try:
                parsed = datetime.fromisoformat(self.expires_at)
            except (TypeError, ValueError) as exc:
                raise ValueError("approval expires_at must be an ISO-8601 timestamp") from exc
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("approval expires_at must include a timezone")
            object.__setattr__(
                self,
                "expires_at",
                parsed.astimezone(timezone.utc).isoformat(),
            )


@dataclass(frozen=True, slots=True)
class OperationRequest:
    run_id: str
    kind: str
    subject_id: str
    idempotency_key: str
    payload: Any
    result_role: str
    estimated_cost: int = 0
    approval_scope: str | None = None
    approval_id: str | None = None
    ambiguity_on_exception: bool = False

    def __post_init__(self) -> None:
        for name in ("run_id", "kind", "subject_id", "idempotency_key", "result_role"):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        if not isinstance(self.estimated_cost, int) or self.estimated_cost < 0:
            raise ValueError("estimated_cost must be a non-negative integer")
        if self.approval_scope is not None:
            object.__setattr__(
                self, "approval_scope", _non_empty(self.approval_scope, "approval_scope")
            )
            if self.approval_id is None:
                raise ValueError("approval_id is required when approval_scope is set")
        if self.approval_id is not None:
            object.__setattr__(self, "approval_id", _non_empty(self.approval_id, "approval_id"))
            if self.approval_scope is None:
                raise ValueError("approval_scope is required when approval_id is set")
        canonical_dumps(self.payload)

    @property
    def operation_id(self) -> str:
        return _stable_id("op", self.run_id, self.idempotency_key)

    @property
    def operation_key(self) -> str:
        """Server-verifiable semantic identity, independent of a caller key."""

        semantic_json = canonical_dumps(
            {
                "run_id": self.run_id,
                "kind": self.kind,
                "subject_id": self.subject_id,
                "payload": self.payload,
                "result_role": self.result_role,
            }
        )
        return hashlib.sha256(semantic_json.encode("utf-8")).hexdigest()

    @property
    def request_json(self) -> str:
        return canonical_dumps(
            {
                "run_id": self.run_id,
                "kind": self.kind,
                "subject_id": self.subject_id,
                "idempotency_key": self.idempotency_key,
                "payload": self.payload,
                "result_role": self.result_role,
                "estimated_cost": self.estimated_cost,
                "approval_scope": self.approval_scope,
                "approval_id": self.approval_id,
                "ambiguity_on_exception": self.ambiguity_on_exception,
            }
        )

    @property
    def request_sha256(self) -> str:
        return hashlib.sha256(self.request_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ArtifactReceipt:
    artifact_id: str
    run_id: str
    operation_id: str
    attempt_id: str
    role: str
    relative_uri: str
    sha256: str
    size_bytes: int
    media_type: str = "application/json"


@dataclass(frozen=True, slots=True)
class OperationSnapshot:
    operation_id: str
    run_id: str
    idempotency_key: str
    kind: str
    subject_id: str
    status: OperationStatus
    attempt_id: str | None
    attempt_count: int
    estimated_cost: int
    result_json: str | None
    result_sha256: str | None
    artifact: ArtifactReceipt | None
    error_json: str | None
    lease_expires_at: str | None
    result_role: str


@dataclass(frozen=True, slots=True)
class AcquireResult:
    disposition: AcquireDisposition
    operation: OperationSnapshot


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    run_id: str
    task_id: str
    context_id: str
    status: RunStatus
    terminal_status: str | None
    budget_limit: int
    budget_reserved: int
    latest_checkpoint_revision: int
    manifest_sha256: str
    operation_costs: Mapping[str, int]
    required_approval_scopes: Mapping[str, str]
    execution_policy: ExecutionPolicy
    hfss_solve_launches_authorized: int


@dataclass(frozen=True, slots=True)
class RunInvocationClaim:
    disposition: RunInvocationDisposition
    run: RunSnapshot
    fence: int


class RunStore:
    """A per-artifact-root SQLite database with short, explicit transactions."""

    def __init__(self, path: Path, *, busy_timeout_seconds: float = 30.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_seconds = float(busy_timeout_seconds)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_seconds,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        deadline = time.monotonic() + self.busy_timeout_seconds
        while True:
            try:
                self._initialize_once()
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                    raise
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def _initialize_once(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE,
                    context_id TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    terminal_status TEXT,
                    budget_limit INTEGER NOT NULL CHECK (budget_limit >= 0),
                    operation_costs_json TEXT NOT NULL,
                    required_approval_scopes_json TEXT NOT NULL,
                    execution_policy_json TEXT NOT NULL,
                    latest_checkpoint_revision INTEGER NOT NULL DEFAULT 0,
                    invocation_owner_token TEXT,
                    invocation_fence INTEGER NOT NULL DEFAULT 0,
                    invocation_lease_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    granted_by TEXT NOT NULL,
                    granted_at TEXT NOT NULL,
                    expires_at TEXT,
                    revoked_at TEXT,
                    PRIMARY KEY (run_id, approval_id, scope),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    operation_key TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    current_attempt_id TEXT,
                    estimated_cost INTEGER NOT NULL CHECK (estimated_cost >= 0),
                    approval_id TEXT,
                    approval_scope TEXT,
                    ambiguity_on_exception INTEGER NOT NULL,
                    result_json TEXT,
                    result_sha256 TEXT,
                    artifact_id TEXT,
                    error_json TEXT,
                    lease_expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (run_id, idempotency_key),
                    UNIQUE (run_id, operation_key),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id TEXT PRIMARY KEY,
                    operation_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    owner_token TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    error_json TEXT,
                    UNIQUE (operation_id, ordinal),
                    FOREIGN KEY (operation_id) REFERENCES operations(operation_id)
                );
                CREATE TABLE IF NOT EXISTS budget_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL UNIQUE,
                    units INTEGER NOT NULL CHECK (units >= 0),
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id),
                    FOREIGN KEY (operation_id) REFERENCES operations(operation_id)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    relative_uri TEXT NOT NULL UNIQUE,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id),
                    FOREIGN KEY (operation_id) REFERENCES operations(operation_id),
                    FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    operation_id TEXT,
                    attempt_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id),
                    FOREIGN KEY (operation_id) REFERENCES operations(operation_id),
                    FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id)
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    run_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    state_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, revision),
                    UNIQUE (run_id, state_sha256),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS reconciliations (
                    reconciliation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL UNIQUE,
                    attempt_id TEXT NOT NULL,
                    approval_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    result_sha256 TEXT,
                    evidence_artifact_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id),
                    FOREIGN KEY (operation_id) REFERENCES operations(operation_id),
                    FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id),
                    FOREIGN KEY (evidence_artifact_id) REFERENCES artifacts(artifact_id)
                );
                CREATE INDEX IF NOT EXISTS ix_operations_run_status
                    ON operations(run_id, status);
                CREATE UNIQUE INDEX IF NOT EXISTS ux_approvals_identity_scope
                    ON approvals(approval_id, scope);
                CREATE INDEX IF NOT EXISTS ix_events_run_sequence
                    ON events(run_id, sequence);
                CREATE TRIGGER IF NOT EXISTS events_are_append_only_on_update
                    BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'events ledger is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS events_are_append_only_on_delete
                    BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'events ledger is append-only'); END;
                """
            )
            # Transitional support for SQLite files created by an earlier local
            # Phase-2 iteration. New authoritative writes still use the V2 schema.
            run_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(runs)")
            }
            for name, declaration in (
                ("operation_costs_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("required_approval_scopes_json", "TEXT NOT NULL DEFAULT '{}'"),
                (
                    "execution_policy_json",
                    "TEXT NOT NULL DEFAULT '{\"automatic_solve_retries\":0,"
                    "\"max_hfss_solve_launches\":2}'",
                ),
                ("invocation_owner_token", "TEXT"),
                ("invocation_fence", "INTEGER NOT NULL DEFAULT 0"),
                ("invocation_lease_expires_at", "TEXT"),
            ):
                if name not in run_columns:
                    connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {declaration}")
            operation_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(operations)")
            }
            if "operation_key" not in operation_columns:
                connection.execute("ALTER TABLE operations ADD COLUMN operation_key TEXT")
                connection.execute(
                    "UPDATE operations SET operation_key = request_sha256 WHERE operation_key IS NULL"
                )
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_operations_run_operation_key "
                    "ON operations(run_id, operation_key)"
                )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        *,
        run_id: str,
        event_type: str,
        payload: Any,
        operation_id: str | None = None,
        attempt_id: str | None = None,
        event_id: str | None = None,
    ) -> None:
        if operation_id is not None:
            operation = connection.execute(
                "SELECT run_id FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if operation is None or operation["run_id"] != run_id:
                raise RunStoreError("event operation identity does not belong to the run")
        if attempt_id is not None:
            attempt = connection.execute(
                """SELECT o.run_id, a.operation_id FROM attempts a
                   JOIN operations o ON o.operation_id = a.operation_id
                   WHERE a.attempt_id = ?""",
                (attempt_id,),
            ).fetchone()
            if (
                attempt is None
                or attempt["run_id"] != run_id
                or (operation_id is not None and attempt["operation_id"] != operation_id)
            ):
                raise RunStoreError("event attempt identity does not belong to the operation/run")
        connection.execute(
            """INSERT INTO events
               (event_id, run_id, operation_id, attempt_id, event_type, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id or f"evt_{uuid.uuid4().hex}",
                run_id,
                operation_id,
                attempt_id,
                event_type,
                canonical_dumps(payload),
                _now(),
            ),
        )

    def register_run(
        self,
        manifest: Any,
        *,
        budget_limit: int,
        operation_costs: Mapping[str, int],
        required_approval_scopes: Mapping[str, str],
        execution_policy: ExecutionPolicy = ExecutionPolicy(),
        approvals: tuple[ApprovalGrant, ...] = (),
    ) -> RunSnapshot:
        if not isinstance(budget_limit, int) or budget_limit < 0:
            raise ValueError("budget_limit must be a non-negative integer")
        manifest_json = canonical_dumps(manifest)
        manifest_payload = canonical_loads(manifest_json)
        manifest_sha256 = manifest_identity_sha256(manifest)
        normalized_costs: dict[str, int] = {}
        for kind, cost in operation_costs.items():
            kind = _non_empty(kind, "operation kind")
            if not isinstance(cost, int) or cost < 0:
                raise ValueError("operation costs must be non-negative integers")
            normalized_costs[kind] = cost
        normalized_scopes = {
            _non_empty(kind, "approval operation kind"): _non_empty(scope, "approval scope")
            for kind, scope in required_approval_scopes.items()
        }
        if not set(normalized_scopes).issubset(normalized_costs):
            raise ValueError("approval policy references an unknown operation kind")
        if (
            isinstance(manifest_payload, dict)
            and manifest_payload.get("real_execution") is True
            and normalized_scopes.get("hfss") != "real_hfss"
        ):
            raise ValueError("real execution requires the authoritative real_hfss approval policy")
        if isinstance(manifest_payload, dict) and manifest_payload.get("real_execution") is True:
            if execution_policy != ExecutionPolicy(2, 0):
                raise ValueError(
                    "real execution requires max_hfss_solve_launches=2 and zero retries"
                )
            if not manifest_payload.get("code_revision"):
                raise RunIdentityConflict("real RunManifest must bind an exact code revision")
            provider_fingerprints = manifest_payload.get("provider_fingerprints")
            if (
                not isinstance(provider_fingerprints, dict)
                or set(provider_fingerprints) != REQUIRED_PROVIDER_FINGERPRINTS
            ):
                raise RunIdentityConflict(
                    "real RunManifest must bind every mandatory provider/source fingerprint"
                )
            config_fingerprints = manifest_payload.get("config_fingerprints")
            required_config = {
                "real_hfss_authorization_id",
                "readiness_id",
                "hfss_contract_id",
                "hfss_contract_sha256",
                "evaluation_contract_id",
                "evaluation_contract_sha256",
                "calibration_evidence_sha256",
                "calibration_evidence",
            }
            if (
                not isinstance(config_fingerprints, dict)
                or not required_config.issubset(config_fingerprints)
            ):
                raise RunIdentityConflict(
                    "real RunManifest must bind readiness and evaluation/HFSS contracts"
                )
            from ..domain.contracts import CalibrationEvidence

            calibration = CalibrationEvidence.from_dict(
                config_fingerprints["calibration_evidence"]
            )
            if (
                not calibration.passed
                or calibration.digest
                != config_fingerprints["calibration_evidence_sha256"]
                or calibration.comparison_context_id
                != manifest_payload["design_goal"]["comparison_context_id"]
            ):
                raise RunIdentityConflict(
                    "real RunManifest calibration evidence is failing, drifted, or mismatched"
                )
            provider_fingerprints = manifest_payload["provider_fingerprints"]
            if any(
                provider_fingerprints.get(name) != digest
                for name, digest in calibration.provider_fingerprints.to_dict().items()
            ):
                raise RunIdentityConflict(
                    "real RunManifest calibration provider evidence has drifted"
                )
        authorization_id: str | None = None
        if isinstance(manifest_payload, dict) and manifest_payload.get("real_execution") is True:
            fingerprints = manifest_payload.get("config_fingerprints", {})
            authorization_id = (
                fingerprints.get("real_hfss_authorization_id")
                if isinstance(fingerprints, dict)
                else None
            )
            if not isinstance(authorization_id, str) or not authorization_id:
                raise ApprovalRequired(
                    "real RunManifest must bind its real_hfss authorization identity"
                )
        costs_json = canonical_dumps(normalized_costs)
        scopes_json = canonical_dumps(normalized_scopes)
        policy_json = canonical_dumps(execution_policy)
        run_id = _non_empty(manifest.run_id, "run_id")
        task_id = _non_empty(manifest.task_id, "task_id")
        context_id = _non_empty(
            manifest.design_goal.comparison_context_id, "comparison_context_id"
        )
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO runs
                       (run_id, task_id, context_id, manifest_json, manifest_sha256,
                        status, budget_limit, operation_costs_json,
                         required_approval_scopes_json, execution_policy_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        task_id,
                        context_id,
                        manifest_json,
                        manifest_sha256,
                        RunStatus.ACTIVE,
                        budget_limit,
                        costs_json,
                        scopes_json,
                        policy_json,
                        _now(),
                    ),
                )
                self._event(
                    connection,
                    run_id=run_id,
                    event_type="run_registered",
                    payload={
                        "task_id": task_id,
                        "budget_limit": budget_limit,
                        "operation_costs": normalized_costs,
                        "required_approval_scopes": normalized_scopes,
                        "execution_policy": execution_policy,
                    },
                )
            elif (
                existing["manifest_sha256"] != manifest_sha256
                or existing["task_id"] != task_id
                or existing["context_id"] != context_id
                or existing["budget_limit"] != budget_limit
                or existing["operation_costs_json"] != costs_json
                or existing["required_approval_scopes_json"] != scopes_json
                or existing["execution_policy_json"] != policy_json
            ):
                raise RunIdentityConflict(
                    f"run_id {run_id!r} is already bound to different immutable identity"
                )
            if authorization_id is not None and (
                existing is None or RunStatus(existing["status"]) is RunStatus.ACTIVE
            ):
                real_grants = [
                    grant for grant in approvals if grant.scope == "real_hfss"
                ]
                if not any(grant.approval_id == authorization_id for grant in real_grants):
                    raise ApprovalRequired(
                        "real Run registration requires its bound real_hfss approval grant"
                    )
                if any(grant.approval_id != authorization_id for grant in real_grants):
                    raise RunIdentityConflict(
                        "real_hfss approval does not match the RunManifest authorization identity"
                    )
            terminal = existing is not None and RunStatus(existing["status"]) is not RunStatus.ACTIVE
            for grant in (() if terminal else approvals):
                row = connection.execute(
                    """SELECT scope, granted_by, expires_at FROM approvals
                       WHERE run_id = ? AND approval_id = ? AND scope = ?""",
                    (run_id, grant.approval_id, grant.scope),
                ).fetchone()
                if row is None:
                    other_run = connection.execute(
                        """SELECT run_id FROM approvals
                           WHERE approval_id = ? AND scope = ?""",
                        (grant.approval_id, grant.scope),
                    ).fetchone()
                    if other_run is not None and other_run["run_id"] != run_id:
                        raise RunIdentityConflict(
                            "approval identity is already bound to a different Run"
                        )
                    connection.execute(
                        """INSERT INTO approvals
                           (approval_id, run_id, scope, granted_by, granted_at, expires_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            grant.approval_id,
                            run_id,
                            grant.scope,
                            grant.granted_by,
                            _now(),
                            grant.expires_at,
                        ),
                    )
                    self._event(
                        connection,
                        run_id=run_id,
                        event_type="approval_registered",
                        payload={"approval_id": grant.approval_id, "scope": grant.scope},
                    )
                elif (
                    row["granted_by"] != grant.granted_by
                    or row["expires_at"] != grant.expires_at
                ):
                    raise RunIdentityConflict("approval identity cannot be changed in place")
        snapshot = self.get_run(run_id)
        if snapshot is None:
            raise RunStoreError("registered run could not be reloaded")
        return snapshot

    def get_run(self, run_id: str) -> RunSnapshot | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT r.*,
                          COALESCE((SELECT SUM(units) FROM budget_reservations b
                                    WHERE b.run_id = r.run_id AND b.status != ?), 0)
                             AS budget_reserved,
                          COALESCE((SELECT COUNT(*) FROM operations o
                                    WHERE o.run_id = r.run_id
                                      AND o.kind = 'hfss'
                                      AND o.approval_scope = 'real_hfss'), 0)
                             AS hfss_solve_launches_authorized
                   FROM runs r WHERE r.run_id = ?""",
                (ReservationStatus.RELEASED, run_id),
            ).fetchone()
        if row is None:
            return None
        return RunSnapshot(
            run_id=row["run_id"],
            task_id=row["task_id"],
            context_id=row["context_id"],
            status=RunStatus(row["status"]),
            terminal_status=row["terminal_status"],
            budget_limit=row["budget_limit"],
            budget_reserved=row["budget_reserved"],
            latest_checkpoint_revision=row["latest_checkpoint_revision"],
            manifest_sha256=row["manifest_sha256"],
            operation_costs=canonical_loads(row["operation_costs_json"]),
            required_approval_scopes=canonical_loads(
                row["required_approval_scopes_json"]
            ),
            execution_policy=ExecutionPolicy.from_dict(
                canonical_loads(row["execution_policy_json"])
            ),
            hfss_solve_launches_authorized=row["hfss_solve_launches_authorized"],
        )

    def claim_run_invocation(
        self,
        run_id: str,
        *,
        owner_token: str,
        lease_seconds: float,
    ) -> RunInvocationClaim:
        owner_token = _non_empty(owner_token, "run invocation owner_token")
        if lease_seconds <= 0:
            raise ValueError("run invocation lease_seconds must be positive")
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        expires = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise RunNotActionable(f"run {run_id!r} is not registered")
            status = RunStatus(row["status"])
            if status is not RunStatus.ACTIVE:
                disposition = RunInvocationDisposition.TERMINAL
                fence = int(row["invocation_fence"])
            elif (
                row["invocation_owner_token"] is not None
                and row["invocation_owner_token"] != owner_token
                and row["invocation_lease_expires_at"] is not None
                and row["invocation_lease_expires_at"] > now
            ):
                disposition = RunInvocationDisposition.IN_FLIGHT
                fence = int(row["invocation_fence"])
            else:
                same_owner = row["invocation_owner_token"] == owner_token
                fence = int(row["invocation_fence"]) + (0 if same_owner else 1)
                connection.execute(
                    """UPDATE runs
                       SET invocation_owner_token = ?, invocation_fence = ?,
                           invocation_lease_expires_at = ?
                       WHERE run_id = ?""",
                    (owner_token, fence, expires, run_id),
                )
                if not same_owner:
                    self._event(
                        connection,
                        run_id=run_id,
                        event_type="run_invocation_claimed",
                        payload={"fence": fence},
                    )
                disposition = RunInvocationDisposition.OWNER
        snapshot = self.get_run(run_id)
        if snapshot is None:
            raise RunStoreError("claimed Run disappeared")
        return RunInvocationClaim(disposition, snapshot, fence)

    def heartbeat_run_invocation(
        self,
        run_id: str,
        *,
        owner_token: str,
        fence: int,
        lease_seconds: float,
    ) -> bool:
        if lease_seconds <= 0:
            raise ValueError("run invocation lease_seconds must be positive")
        expires = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).isoformat()
        with self._transaction() as connection:
            updated = connection.execute(
                """UPDATE runs SET invocation_lease_expires_at = ?
                   WHERE run_id = ? AND status = ?
                     AND invocation_owner_token = ? AND invocation_fence = ?""",
                (expires, run_id, RunStatus.ACTIVE, owner_token, fence),
            )
            return updated.rowcount == 1

    def release_run_invocation(
        self, run_id: str, *, owner_token: str, fence: int
    ) -> bool:
        with self._transaction() as connection:
            updated = connection.execute(
                """UPDATE runs
                   SET invocation_owner_token = NULL, invocation_lease_expires_at = NULL
                   WHERE run_id = ? AND invocation_owner_token = ? AND invocation_fence = ?""",
                (run_id, owner_token, fence),
            )
            return updated.rowcount == 1

    def _approval_valid(
        self, connection: sqlite3.Connection, request: OperationRequest, now: str
    ) -> bool:
        if request.approval_scope is None:
            return True
        row = connection.execute(
            """SELECT expires_at FROM approvals
               WHERE run_id = ? AND approval_id = ? AND scope = ? AND revoked_at IS NULL""",
            (request.run_id, request.approval_id, request.approval_scope),
        ).fetchone()
        return bool(row is not None and (row["expires_at"] is None or row["expires_at"] > now))

    def revoke_approval(self, run_id: str, approval_id: str, scope: str) -> None:
        approval_id = _non_empty(approval_id, "approval_id")
        scope = _non_empty(scope, "approval scope")
        now = _now()
        with self._transaction() as connection:
            run = connection.execute(
                "SELECT status FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise RunStoreError("cannot revoke approval for an unregistered Run")
            if RunStatus(run["status"]) is RunStatus.COMPLETED:
                raise RunNotActionable("completed Run approvals are immutable")
            changed = connection.execute(
                """UPDATE approvals SET revoked_at = ?
                   WHERE run_id = ? AND approval_id = ? AND scope = ?
                     AND revoked_at IS NULL""",
                (now, run_id, approval_id, scope),
            )
            if changed.rowcount != 1:
                raise ApprovalRequired("approval does not exist or is already revoked")
            self._event(
                connection,
                run_id=run_id,
                event_type="approval_revoked",
                payload={"approval_id": approval_id, "scope": scope},
            )

    def acquire_operation(
        self,
        request: OperationRequest,
        *,
        owner_token: str,
        lease_seconds: float,
        run_owner_token: str | None = None,
        run_fence: int | None = None,
    ) -> AcquireResult:
        owner_token = _non_empty(owner_token, "owner_token")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        request_json = request.request_json
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        lease_expires_at = (now_dt + timedelta(seconds=lease_seconds)).isoformat()
        with self._transaction() as connection:
            run = connection.execute(
                """SELECT status, budget_limit, operation_costs_json,
                          required_approval_scopes_json, execution_policy_json
                   FROM runs WHERE run_id = ?""",
                (request.run_id,),
            ).fetchone()
            if run is None:
                raise RunNotActionable(f"run {request.run_id!r} is not registered")
            invocation = connection.execute(
                """SELECT invocation_owner_token, invocation_fence
                   FROM runs WHERE run_id = ?""",
                (request.run_id,),
            ).fetchone()
            if invocation["invocation_owner_token"] is not None and (
                invocation["invocation_owner_token"] != run_owner_token
                or int(invocation["invocation_fence"]) != run_fence
            ):
                raise RunNotActionable("operation admission lost its Run invocation fence")
            costs = canonical_loads(run["operation_costs_json"])
            scopes = canonical_loads(run["required_approval_scopes_json"])
            if request.kind not in costs:
                raise RunStoreError(f"operation kind {request.kind!r} is not registered")
            if request.estimated_cost != costs[request.kind]:
                raise RunStoreError(
                    f"operation {request.kind!r} cost must be authoritative value "
                    f"{costs[request.kind]}, not {request.estimated_cost}"
                )
            required_scope = scopes.get(request.kind)
            if required_scope is not None and request.approval_scope != required_scope:
                raise ApprovalRequired(
                    f"operation {request.kind!r} requires approval scope {required_scope!r}"
                )
            if required_scope == "real_hfss" and not request.ambiguity_on_exception:
                raise RunStoreError("real HFSS operations require fail-closed ambiguity policy")
            matching = connection.execute(
                """SELECT * FROM operations
                   WHERE run_id = ? AND (idempotency_key = ? OR operation_key = ?)
                   ORDER BY created_at""",
                (request.run_id, request.idempotency_key, request.operation_key),
            ).fetchall()
            if len(matching) > 1:
                raise IdempotencyConflict(
                    "idempotency key and semantic operation key resolve to different actions"
                )
            existing = matching[0] if matching else None
            if existing is not None:
                if (
                    existing["idempotency_key"] == request.idempotency_key
                    and existing["request_sha256"] != request.request_sha256
                ):
                    raise IdempotencyConflict(
                        "idempotency key is already bound to a different canonical request"
                    )
                snapshot = self._operation_from_row(connection, existing)
                disposition = {
                    OperationStatus.RUNNING: AcquireDisposition.IN_FLIGHT,
                    OperationStatus.SUCCEEDED: AcquireDisposition.CACHED,
                    OperationStatus.FAILED: AcquireDisposition.FAILED,
                    OperationStatus.UNKNOWN: AcquireDisposition.UNKNOWN,
                }[snapshot.status]
                return AcquireResult(disposition, snapshot)
            if RunStatus(run["status"]) is not RunStatus.ACTIVE:
                raise RunNotActionable(
                    f"run {request.run_id!r} is {run['status']} and cannot start actions"
                )
            if not self._approval_valid(connection, request, now):
                raise ApprovalRequired(
                    f"operation requires active approval {request.approval_id!r} "
                    f"for scope {request.approval_scope!r}"
                )
            physical_launch_ordinal: int | None = None
            if required_scope == "real_hfss":
                execution_policy = ExecutionPolicy.from_dict(
                    canonical_loads(run["execution_policy_json"])
                )
                launches = int(
                    connection.execute(
                        """SELECT COUNT(*) AS total FROM operations
                           WHERE run_id = ? AND kind = 'hfss'
                             AND approval_scope = 'real_hfss'""",
                        (request.run_id,),
                    ).fetchone()["total"]
                )
                if launches >= execution_policy.max_hfss_solve_launches:
                    raise PhysicalLaunchLimitExceeded(
                        "real HFSS solve launch limit would be exceeded: "
                        f"authorized={launches}, "
                        f"limit={execution_policy.max_hfss_solve_launches}"
                    )
                physical_launch_ordinal = launches + 1
            reserved = connection.execute(
                """SELECT COALESCE(SUM(units), 0) AS total FROM budget_reservations
                   WHERE run_id = ? AND status != ?""",
                (request.run_id, ReservationStatus.RELEASED),
            ).fetchone()["total"]
            if reserved + request.estimated_cost > run["budget_limit"]:
                raise BudgetExceeded(
                    f"budget limit {run['budget_limit']} would be exceeded: "
                    f"reserved={reserved}, requested={request.estimated_cost}"
                )
            operation_id = request.operation_id
            attempt_id = _stable_id("att", operation_id, "1")
            connection.execute(
                """INSERT INTO operations
                   (operation_id, run_id, operation_key, idempotency_key, kind, subject_id,
                    request_json, request_sha256, status, attempt_count,
                    current_attempt_id, estimated_cost, approval_id, approval_scope,
                    ambiguity_on_exception, lease_expires_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    operation_id,
                    request.run_id,
                    request.operation_key,
                    request.idempotency_key,
                    request.kind,
                    request.subject_id,
                    request_json,
                    request.request_sha256,
                    OperationStatus.RUNNING,
                    attempt_id,
                    request.estimated_cost,
                    request.approval_id,
                    request.approval_scope,
                    int(request.ambiguity_on_exception),
                    lease_expires_at,
                    now,
                    now,
                ),
            )
            connection.execute(
                """INSERT INTO attempts
                   (attempt_id, operation_id, ordinal, status, owner_token, started_at)
                   VALUES (?, ?, 1, ?, ?, ?)""",
                (attempt_id, operation_id, AttemptStatus.RUNNING, owner_token, now),
            )
            connection.execute(
                """INSERT INTO budget_reservations
                   (reservation_id, run_id, operation_id, units, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    _stable_id("res", operation_id),
                    request.run_id,
                    operation_id,
                    request.estimated_cost,
                    ReservationStatus.RESERVED,
                    now,
                    now,
                ),
            )
            self._event(
                connection,
                run_id=request.run_id,
                operation_id=operation_id,
                attempt_id=attempt_id,
                event_type="physical_start_authorized",
                payload={
                    "kind": request.kind,
                    "subject_id": request.subject_id,
                    "estimated_cost": request.estimated_cost,
                    "hfss_solve_launch_ordinal": physical_launch_ordinal,
                },
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            return AcquireResult(
                AcquireDisposition.OWNER, self._operation_from_row(connection, row)
            )

    def _artifact_from_id(
        self, connection: sqlite3.Connection, artifact_id: str | None
    ) -> ArtifactReceipt | None:
        if artifact_id is None:
            return None
        row = connection.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise RunStoreError(f"operation references missing artifact {artifact_id}")
        return ArtifactReceipt(
            artifact_id=row["artifact_id"],
            run_id=row["run_id"],
            operation_id=row["operation_id"],
            attempt_id=row["attempt_id"],
            role=row["role"],
            relative_uri=row["relative_uri"],
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            media_type=row["media_type"],
        )

    def _operation_from_row(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> OperationSnapshot:
        request_payload = canonical_loads(row["request_json"])
        return OperationSnapshot(
            operation_id=row["operation_id"],
            run_id=row["run_id"],
            idempotency_key=row["idempotency_key"],
            kind=row["kind"],
            subject_id=row["subject_id"],
            status=OperationStatus(row["status"]),
            attempt_id=row["current_attempt_id"],
            attempt_count=row["attempt_count"],
            estimated_cost=row["estimated_cost"],
            result_json=row["result_json"],
            result_sha256=row["result_sha256"],
            artifact=self._artifact_from_id(connection, row["artifact_id"]),
            error_json=row["error_json"],
            lease_expires_at=row["lease_expires_at"],
            result_role=request_payload["result_role"],
        )

    def get_operation(self, operation_id: str) -> OperationSnapshot | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            return self._operation_from_row(connection, row) if row is not None else None

    def get_operation_by_idempotency(
        self, run_id: str, idempotency_key: str
    ) -> OperationSnapshot | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE run_id = ? AND idempotency_key = ?",
                (run_id, idempotency_key),
            ).fetchone()
            return self._operation_from_row(connection, row) if row is not None else None

    def list_operation_artifacts(
        self, operation_id: str
    ) -> tuple[ArtifactReceipt, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE operation_id = ? ORDER BY role, artifact_id",
                (operation_id,),
            ).fetchall()
        return tuple(
            ArtifactReceipt(
                artifact_id=row["artifact_id"],
                run_id=row["run_id"],
                operation_id=row["operation_id"],
                attempt_id=row["attempt_id"],
                role=row["role"],
                relative_uri=row["relative_uri"],
                sha256=row["sha256"],
                size_bytes=row["size_bytes"],
                media_type=row["media_type"],
            )
            for row in rows
        )

    def list_artifacts(self, run_id: str) -> tuple[ArtifactReceipt, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at, artifact_id",
                (run_id,),
            ).fetchall()
        return tuple(
            ArtifactReceipt(
                artifact_id=row["artifact_id"],
                run_id=row["run_id"],
                operation_id=row["operation_id"],
                attempt_id=row["attempt_id"],
                role=row["role"],
                relative_uri=row["relative_uri"],
                sha256=row["sha256"],
                size_bytes=row["size_bytes"],
                media_type=row["media_type"],
            )
            for row in rows
        )

    def complete_operation(
        self,
        operation_id: str,
        *,
        attempt_id: str,
        owner_token: str,
        result_json: str,
        artifact: ArtifactReceipt,
        supporting_artifacts: tuple[ArtifactReceipt, ...] = (),
    ) -> OperationSnapshot:
        decoded = canonical_loads(result_json)
        canonical_result = canonical_dumps(decoded)
        result_sha256 = hashlib.sha256(canonical_result.encode("utf-8")).hexdigest()
        if artifact.sha256 != result_sha256:
            raise RunStoreError("artifact digest does not match operation result digest")
        now = _now()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise RunStoreError("unknown operation")
            if OperationStatus(row["status"]) is OperationStatus.SUCCEEDED:
                existing_artifact = self._artifact_from_id(connection, row["artifact_id"])
                existing_supporting = tuple(
                    self._artifact_from_id(connection, item["artifact_id"])
                    for item in connection.execute(
                        """SELECT artifact_id FROM artifacts
                           WHERE operation_id = ? AND artifact_id != ?
                           ORDER BY role, artifact_id""",
                        (operation_id, row["artifact_id"]),
                    ).fetchall()
                )
                if (
                    row["result_sha256"] != result_sha256
                    or existing_artifact != artifact
                    or existing_supporting
                    != tuple(sorted(supporting_artifacts, key=lambda item: (item.role, item.artifact_id)))
                ):
                    raise RunStoreError(
                        "SUCCEEDED operation may only be completed idempotently "
                        "with the identical result receipt"
                    )
                return self._operation_from_row(connection, row)
            if OperationStatus(row["status"]) is not OperationStatus.RUNNING:
                raise RunStoreError(f"cannot complete operation in state {row['status']}")
            attempt = connection.execute(
                "SELECT owner_token FROM attempts WHERE attempt_id = ? AND operation_id = ?",
                (attempt_id, operation_id),
            ).fetchone()
            if (
                attempt is None
                or row["current_attempt_id"] != attempt_id
                or attempt["owner_token"] != owner_token
            ):
                raise RunStoreError("operation completion lost its attempt/owner fencing token")
            request_payload = canonical_loads(row["request_json"])
            if (
                artifact.run_id != row["run_id"]
                or artifact.operation_id != operation_id
                or artifact.attempt_id != attempt_id
                or artifact.role != request_payload["result_role"]
            ):
                raise RunStoreError("artifact operation/attempt identity mismatch")
            supporting_roles: set[str] = set()
            for supporting in supporting_artifacts:
                if (
                    supporting.run_id != row["run_id"]
                    or supporting.operation_id != operation_id
                    or supporting.attempt_id != attempt_id
                    or supporting.role == artifact.role
                    or supporting.role in supporting_roles
                ):
                    raise RunStoreError(
                        "supporting artifact operation/attempt/role identity mismatch"
                    )
                supporting_roles.add(supporting.role)
            connection.execute(
                """INSERT INTO artifacts
                   (artifact_id, run_id, operation_id, attempt_id, role, relative_uri,
                    sha256, size_bytes, media_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact.artifact_id,
                    artifact.run_id,
                    artifact.operation_id,
                    artifact.attempt_id,
                    artifact.role,
                    artifact.relative_uri,
                    artifact.sha256,
                    artifact.size_bytes,
                    artifact.media_type,
                    now,
                ),
            )
            for supporting in supporting_artifacts:
                connection.execute(
                    """INSERT INTO artifacts
                       (artifact_id, run_id, operation_id, attempt_id, role, relative_uri,
                        sha256, size_bytes, media_type, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        supporting.artifact_id,
                        supporting.run_id,
                        supporting.operation_id,
                        supporting.attempt_id,
                        supporting.role,
                        supporting.relative_uri,
                        supporting.sha256,
                        supporting.size_bytes,
                        supporting.media_type,
                        now,
                    ),
                )
            connection.execute(
                """UPDATE attempts SET status = ?, finished_at = ?
                   WHERE attempt_id = ?""",
                (AttemptStatus.SUCCEEDED, now, attempt_id),
            )
            connection.execute(
                """UPDATE operations
                   SET status = ?, result_json = ?, result_sha256 = ?, artifact_id = ?,
                       lease_expires_at = NULL, updated_at = ?
                   WHERE operation_id = ?""",
                (
                    OperationStatus.SUCCEEDED,
                    canonical_result,
                    result_sha256,
                    artifact.artifact_id,
                    now,
                    operation_id,
                ),
            )
            connection.execute(
                """UPDATE budget_reservations SET status = ?, updated_at = ?
                   WHERE operation_id = ?""",
                (ReservationStatus.CONSUMED, now, operation_id),
            )
            self._event(
                connection,
                run_id=row["run_id"],
                operation_id=operation_id,
                attempt_id=row["current_attempt_id"],
                event_type="operation_succeeded",
                payload={
                    "artifact_id": artifact.artifact_id,
                    "sha256": result_sha256,
                    "supporting_artifact_ids": [
                        item.artifact_id for item in supporting_artifacts
                    ],
                },
            )
            updated = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            return self._operation_from_row(connection, updated)

    def fail_operation(
        self,
        operation_id: str,
        *,
        attempt_id: str,
        owner_token: str,
        error: Any,
        ambiguous: bool,
    ) -> OperationSnapshot:
        status = OperationStatus.UNKNOWN if ambiguous else OperationStatus.FAILED
        attempt_status = AttemptStatus.UNKNOWN if ambiguous else AttemptStatus.FAILED
        error_json = canonical_dumps(error)
        now = _now()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                raise RunStoreError("unknown operation")
            if OperationStatus(row["status"]) is not OperationStatus.RUNNING:
                return self._operation_from_row(connection, row)
            attempt = connection.execute(
                "SELECT owner_token FROM attempts WHERE attempt_id = ? AND operation_id = ?",
                (attempt_id, operation_id),
            ).fetchone()
            if (
                attempt is None
                or row["current_attempt_id"] != attempt_id
                or attempt["owner_token"] != owner_token
            ):
                raise RunStoreError("operation failure lost its attempt/owner fencing token")
            connection.execute(
                """UPDATE attempts SET status = ?, finished_at = ?, error_json = ?
                   WHERE attempt_id = ?""",
                (attempt_status, now, error_json, attempt_id),
            )
            connection.execute(
                """UPDATE operations SET status = ?, error_json = ?,
                       lease_expires_at = NULL, updated_at = ? WHERE operation_id = ?""",
                (status, error_json, now, operation_id),
            )
            connection.execute(
                """UPDATE budget_reservations SET status = ?, updated_at = ?
                   WHERE operation_id = ?""",
                (ReservationStatus.CONSUMED, now, operation_id),
            )
            if ambiguous:
                connection.execute(
                    """UPDATE runs SET status = ?, invocation_owner_token = NULL,
                              invocation_lease_expires_at = NULL
                       WHERE run_id = ? AND status = ?""",
                    (RunStatus.WAITING_RECONCILIATION, row["run_id"], RunStatus.ACTIVE),
                )
            self._event(
                connection,
                run_id=row["run_id"],
                operation_id=operation_id,
                attempt_id=row["current_attempt_id"],
                event_type=("operation_unknown" if ambiguous else "operation_failed"),
                payload={"error": error},
            )
            updated = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            return self._operation_from_row(connection, updated)

    @staticmethod
    def _insert_artifact(
        connection: sqlite3.Connection,
        artifact: ArtifactReceipt,
        *,
        created_at: str,
    ) -> None:
        connection.execute(
            """INSERT INTO artifacts
               (artifact_id, run_id, operation_id, attempt_id, role, relative_uri,
                sha256, size_bytes, media_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact.artifact_id,
                artifact.run_id,
                artifact.operation_id,
                artifact.attempt_id,
                artifact.role,
                artifact.relative_uri,
                artifact.sha256,
                artifact.size_bytes,
                artifact.media_type,
                created_at,
            ),
        )

    def reconcile_operation(
        self,
        request: ReconciliationRequest,
        *,
        evidence_artifact: ArtifactReceipt,
        result_json: str | None = None,
        result_artifact: ArtifactReceipt | None = None,
        as_of: str | None = None,
    ) -> OperationSnapshot:
        """Resolve one UNKNOWN attempt without retrying or refunding its budget."""

        request_json = canonical_dumps(request)
        request_sha256 = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        now = as_of or _now()
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM reconciliations WHERE operation_id = ?",
                (request.operation_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["reconciliation_id"] != request.reconciliation_id
                    or existing["request_sha256"] != request_sha256
                ):
                    raise RunStoreError(
                        "operation already has a different reconciliation decision"
                    )
                row = connection.execute(
                    "SELECT * FROM operations WHERE operation_id = ?",
                    (request.operation_id,),
                ).fetchone()
                return self._operation_from_row(connection, row)

            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?",
                (request.operation_id,),
            ).fetchone()
            if row is None or row["run_id"] != request.run_id:
                raise RunStoreError("reconciliation operation does not belong to the Run")
            if row["current_attempt_id"] != request.attempt_id:
                raise RunStoreError("reconciliation attempt is not the UNKNOWN current attempt")
            if OperationStatus(row["status"]) is not OperationStatus.UNKNOWN:
                raise RunNotActionable("only an UNKNOWN operation may be reconciled")
            run = connection.execute(
                "SELECT status FROM runs WHERE run_id = ?", (request.run_id,)
            ).fetchone()
            if run is None or RunStatus(run["status"]) is not RunStatus.WAITING_RECONCILIATION:
                raise RunNotActionable(
                    "operation reconciliation requires a WAITING_RECONCILIATION Run"
                )
            approval = connection.execute(
                """SELECT expires_at FROM approvals
                   WHERE run_id = ? AND approval_id = ? AND scope = ?
                     AND revoked_at IS NULL""",
                (
                    request.run_id,
                    request.approval_id,
                    RECONCILIATION_APPROVAL_SCOPE,
                ),
            ).fetchone()
            if (
                approval is None
                or request.issued_at > now
                or request.expires_at <= now
                or (
                    approval["expires_at"] is not None
                    and approval["expires_at"] <= now
                )
            ):
                raise ApprovalRequired(
                    "reconciliation requires a current pre-registered operator approval"
                )
            if (
                evidence_artifact.run_id != request.run_id
                or evidence_artifact.operation_id != request.operation_id
                or evidence_artifact.attempt_id != request.attempt_id
                or evidence_artifact.role != "reconciliation_evidence"
                or evidence_artifact.sha256 != request_sha256
            ):
                raise RunStoreError("reconciliation evidence artifact identity/digest mismatch")

            request_payload = canonical_loads(row["request_json"])
            result_sha256: str | None = None
            if request.resolution is ReconciliationResolution.CONFIRMED_SUCCEEDED:
                if result_json is None or result_artifact is None:
                    raise RunStoreError("confirmed success requires a recovered result receipt")
                canonical_result = canonical_dumps(canonical_loads(result_json))
                result_sha256 = hashlib.sha256(
                    canonical_result.encode("utf-8")
                ).hexdigest()
                if (
                    result_artifact.run_id != request.run_id
                    or result_artifact.operation_id != request.operation_id
                    or result_artifact.attempt_id != request.attempt_id
                    or result_artifact.role != request_payload["result_role"]
                    or result_artifact.sha256 != result_sha256
                ):
                    raise RunStoreError("recovered result artifact identity/digest mismatch")
                self._insert_artifact(connection, result_artifact, created_at=now)
                next_status = OperationStatus.SUCCEEDED
                next_error_json = None
                artifact_id = result_artifact.artifact_id
            else:
                if result_json is not None or result_artifact is not None:
                    raise RunStoreError("confirmed failure cannot attach a result receipt")
                canonical_result = None
                next_status = OperationStatus.FAILED
                next_error_json = canonical_dumps(
                    {
                        "reason": request.reason,
                        "reconciliation_id": request.reconciliation_id,
                        "type": "OperatorConfirmedFailure",
                    }
                )
                artifact_id = None

            self._insert_artifact(connection, evidence_artifact, created_at=now)
            connection.execute(
                """INSERT INTO reconciliations
                   (reconciliation_id, run_id, operation_id, attempt_id, approval_id,
                    request_json, request_sha256, resolution, result_sha256,
                    evidence_artifact_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    request.reconciliation_id,
                    request.run_id,
                    request.operation_id,
                    request.attempt_id,
                    request.approval_id,
                    request_json,
                    request_sha256,
                    request.resolution,
                    result_sha256,
                    evidence_artifact.artifact_id,
                    now,
                ),
            )
            connection.execute(
                """UPDATE operations
                   SET status = ?, result_json = ?, result_sha256 = ?, artifact_id = ?,
                       error_json = ?, lease_expires_at = NULL, updated_at = ?
                   WHERE operation_id = ? AND status = ?""",
                (
                    next_status,
                    canonical_result,
                    result_sha256,
                    artifact_id,
                    next_error_json,
                    now,
                    request.operation_id,
                    OperationStatus.UNKNOWN,
                ),
            )
            unresolved = connection.execute(
                """SELECT COUNT(*) FROM operations
                   WHERE run_id = ? AND status IN (?, ?)""",
                (request.run_id, OperationStatus.RUNNING, OperationStatus.UNKNOWN),
            ).fetchone()[0]
            if not unresolved:
                connection.execute(
                    """UPDATE runs SET status = ?
                       WHERE run_id = ? AND status = ?""",
                    (
                        RunStatus.ACTIVE,
                        request.run_id,
                        RunStatus.WAITING_RECONCILIATION,
                    ),
                )
            self._event(
                connection,
                run_id=request.run_id,
                operation_id=request.operation_id,
                attempt_id=request.attempt_id,
                event_type="operation_reconciled",
                payload={
                    "reconciliation_id": request.reconciliation_id,
                    "resolution": request.resolution,
                    "request_sha256": request_sha256,
                    "evidence_artifact_id": evidence_artifact.artifact_id,
                    "result_sha256": result_sha256,
                    "budget_refunded": False,
                    "new_attempt_created": False,
                },
            )
            updated = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?",
                (request.operation_id,),
            ).fetchone()
            return self._operation_from_row(connection, updated)

    def get_reconciliation(
        self, operation_id: str
    ) -> ReconciliationSnapshot | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM reconciliations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
        if row is None:
            return None
        request = ReconciliationRequest.from_dict(canonical_loads(row["request_json"]))
        if request.digest != row["request_sha256"]:
            raise RunStoreError("reconciliation request digest is corrupt")
        return ReconciliationSnapshot(
            request=request,
            request_sha256=row["request_sha256"],
            result_sha256=row["result_sha256"],
            evidence_artifact_id=row["evidence_artifact_id"],
            created_at=row["created_at"],
        )

    def expire_stale_operations(self, run_id: str, *, as_of: str | None = None) -> int:
        cutoff = as_of or _now()
        expired = 0
        with self._transaction() as connection:
            rows = connection.execute(
                """SELECT operation_id, current_attempt_id FROM operations
                   WHERE run_id = ? AND status = ? AND lease_expires_at <= ?""",
                (run_id, OperationStatus.RUNNING, cutoff),
            ).fetchall()
            error = {
                "reason": "execution lease expired; physical outcome is ambiguous"
            }
            error_json = canonical_dumps(error)
            now = _now()
            for row in rows:
                updated = connection.execute(
                    """UPDATE operations
                       SET status = ?, error_json = ?, lease_expires_at = NULL, updated_at = ?
                       WHERE operation_id = ? AND status = ? AND lease_expires_at <= ?""",
                    (
                        OperationStatus.UNKNOWN,
                        error_json,
                        now,
                        row["operation_id"],
                        OperationStatus.RUNNING,
                        cutoff,
                    ),
                )
                if updated.rowcount != 1:
                    continue
                expired += 1
                connection.execute(
                    """UPDATE attempts SET status = ?, finished_at = ?, error_json = ?
                       WHERE attempt_id = ? AND status = ?""",
                    (
                        AttemptStatus.UNKNOWN,
                        now,
                        error_json,
                        row["current_attempt_id"],
                        AttemptStatus.RUNNING,
                    ),
                )
                connection.execute(
                    """UPDATE budget_reservations SET status = ?, updated_at = ?
                       WHERE operation_id = ?""",
                    (ReservationStatus.CONSUMED, now, row["operation_id"]),
                )
                connection.execute(
                    """UPDATE runs SET status = ?, invocation_owner_token = NULL,
                              invocation_lease_expires_at = NULL
                       WHERE run_id = ? AND status = ?""",
                    (RunStatus.WAITING_RECONCILIATION, run_id, RunStatus.ACTIVE),
                )
                self._event(
                    connection,
                    run_id=run_id,
                    operation_id=row["operation_id"],
                    attempt_id=row["current_attempt_id"],
                    event_type="operation_unknown",
                    payload={"error": error},
                )
        return expired

    def wait_for_operation(
        self, operation_id: str, *, timeout_seconds: float, poll_seconds: float = 0.01
    ) -> OperationSnapshot:
        deadline = time.monotonic() + timeout_seconds
        while True:
            snapshot = self.get_operation(operation_id)
            if snapshot is None:
                raise RunStoreError("operation disappeared while waiting")
            if snapshot.status is not OperationStatus.RUNNING:
                return snapshot
            if time.monotonic() >= deadline:
                raise TimeoutError(f"operation {operation_id} is still in flight")
            time.sleep(poll_seconds)

    def heartbeat_operation(
        self,
        operation_id: str,
        *,
        owner_token: str,
        lease_seconds: float,
    ) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        expires = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).isoformat()
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT o.status, o.current_attempt_id, a.owner_token
                   FROM operations o JOIN attempts a
                     ON a.attempt_id = o.current_attempt_id
                   WHERE o.operation_id = ?""",
                (operation_id,),
            ).fetchone()
            if (
                row is None
                or OperationStatus(row["status"]) is not OperationStatus.RUNNING
                or row["owner_token"] != owner_token
            ):
                return False
            connection.execute(
                """UPDATE operations SET lease_expires_at = ?, updated_at = ?
                   WHERE operation_id = ?""",
                (expires, _now(), operation_id),
            )
            return True

    def save_checkpoint(
        self,
        run_id: str,
        state_json: str,
        *,
        complete: bool = False,
        terminal_status: str | None = None,
        expected_revision: int | None = None,
        run_owner_token: str | None = None,
        run_fence: int | None = None,
    ) -> int:
        canonical_state = canonical_dumps(canonical_loads(state_json))
        digest = hashlib.sha256(canonical_state.encode("utf-8")).hexdigest()
        now = _now()
        with self._transaction() as connection:
            run = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise RunStoreError("cannot checkpoint an unregistered run")
            if run["invocation_owner_token"] is not None and (
                run["invocation_owner_token"] != run_owner_token
                or int(run["invocation_fence"]) != run_fence
            ):
                raise CheckpointConflict("checkpoint writer lost its Run invocation fence")
            latest_revision = int(run["latest_checkpoint_revision"])
            if expected_revision is not None and latest_revision != expected_revision:
                raise CheckpointConflict(
                    f"checkpoint revision changed from {expected_revision} to {latest_revision}"
                )
            state_payload = canonical_loads(canonical_state)
            if not isinstance(state_payload, dict) or "manifest" not in state_payload:
                raise RunStoreError("checkpoint must contain its RunManifest")
            if complete and state_payload.get("status") != terminal_status:
                raise RunStoreError(
                    "terminal checkpoint status does not match terminal_status"
                )
            if manifest_identity_sha256(state_payload["manifest"]) != run["manifest_sha256"]:
                raise RunIdentityConflict("checkpoint manifest does not match its registered Run")
            latest = None
            if latest_revision:
                latest = connection.execute(
                    """SELECT revision, state_sha256 FROM checkpoints
                       WHERE run_id = ? AND revision = ?""",
                    (run_id, latest_revision),
                ).fetchone()
                if latest is None:
                    raise RunStoreError("Run points to a missing latest checkpoint")
            run_status = RunStatus(run["status"])
            if run_status is RunStatus.COMPLETED:
                if (
                    complete
                    and latest is not None
                    and latest["state_sha256"] == digest
                    and run["terminal_status"] == terminal_status
                ):
                    return latest_revision
                raise RunNotActionable("completed Run checkpoint is immutable")
            if complete and run_status is not RunStatus.ACTIVE:
                raise RunNotActionable(
                    f"Run in state {run_status} cannot transition to COMPLETED"
                )
            historical = connection.execute(
                """SELECT revision FROM checkpoints
                   WHERE run_id = ? AND state_sha256 = ?""",
                (run_id, digest),
            ).fetchone()
            if historical is not None and historical["revision"] != latest_revision:
                raise CheckpointConflict("historical checkpoint digest cannot be replayed")
            if latest is not None and latest["state_sha256"] == digest:
                revision = latest_revision
            else:
                revision = latest_revision + 1
                connection.execute(
                    """INSERT INTO checkpoints
                       (run_id, revision, state_json, state_sha256, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (run_id, revision, canonical_state, digest, now),
                )
                connection.execute(
                    """UPDATE runs SET latest_checkpoint_revision = ? WHERE run_id = ?""",
                    (revision, run_id),
                )
                self._event(
                    connection,
                    run_id=run_id,
                    event_type="checkpoint_committed",
                    payload={"revision": revision, "state_sha256": digest},
                )
            if complete:
                if terminal_status is None:
                    raise ValueError("terminal_status is required for completed checkpoints")
                unresolved = connection.execute(
                    """SELECT COUNT(*) FROM operations
                       WHERE run_id = ? AND status IN (?, ?)""",
                    (run_id, OperationStatus.RUNNING, OperationStatus.UNKNOWN),
                ).fetchone()[0]
                if unresolved:
                    raise RunNotActionable(
                        "Run cannot complete with RUNNING or UNKNOWN operations"
                    )
                completed = connection.execute(
                    """UPDATE runs SET status = ?, terminal_status = ?, completed_at = ?
                              , invocation_owner_token = NULL,
                                invocation_lease_expires_at = NULL
                       WHERE run_id = ? AND status = ?
                         AND latest_checkpoint_revision = ?""",
                    (
                        RunStatus.COMPLETED,
                        terminal_status,
                        now,
                        run_id,
                        RunStatus.ACTIVE,
                        revision,
                    ),
                )
                if completed.rowcount != 1:
                    raise RunNotActionable("Run completion lost its lifecycle CAS")
                self._event(
                    connection,
                    run_id=run_id,
                    event_type="run_completed",
                    payload={"terminal_status": terminal_status, "revision": revision},
                )
            return revision

    def has_checkpoint(self, run_id: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT 1 FROM checkpoints c
                   JOIN runs r ON r.run_id = c.run_id
                   WHERE c.run_id = ? AND c.revision = r.latest_checkpoint_revision""",
                (run_id,),
            ).fetchone()
        return row is not None

    def load_checkpoint_json(self, run_id: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT c.state_json, c.state_sha256, c.revision,
                          r.manifest_sha256
                   FROM checkpoints c JOIN runs r ON r.run_id = c.run_id
                   WHERE c.run_id = ? AND c.revision = r.latest_checkpoint_revision""",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        raw = row["state_json"]
        try:
            canonical = canonical_dumps(canonical_loads(raw))
        except CanonicalJsonError as exc:
            raise CheckpointCorruption(
                f"checkpoint revision {row['revision']} is invalid JSON"
            ) from exc
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if canonical != raw or digest != row["state_sha256"]:
            raise CheckpointCorruption(
                f"checkpoint revision {row['revision']} content/digest is corrupt"
            )
        payload = canonical_loads(canonical)
        if (
            not isinstance(payload, dict)
            or "manifest" not in payload
            or manifest_identity_sha256(payload["manifest"]) != row["manifest_sha256"]
        ):
            raise CheckpointCorruption(
                f"checkpoint revision {row['revision']} manifest identity is corrupt"
            )
        return canonical

    def mark_waiting_reconciliation(self, run_id: str, *, reason: str) -> None:
        with self._transaction() as connection:
            changed = connection.execute(
                """UPDATE runs SET status = ?, invocation_owner_token = NULL,
                          invocation_lease_expires_at = NULL
                   WHERE run_id = ? AND status = ?""",
                (RunStatus.WAITING_RECONCILIATION, run_id, RunStatus.ACTIVE),
            )
            if changed.rowcount == 1:
                self._event(
                    connection,
                    run_id=run_id,
                    event_type="run_waiting_reconciliation",
                    payload={"reason": reason},
                )
                return
            existing = connection.execute(
                "SELECT status FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing is None:
                raise RunStoreError("cannot reconcile an unregistered Run")
            if RunStatus(existing["status"]) is not RunStatus.WAITING_RECONCILIATION:
                raise RunNotActionable(
                    f"Run in state {existing['status']} cannot wait for reconciliation"
                )

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: Any,
        *,
        operation_id: str | None = None,
        attempt_id: str | None = None,
    ) -> None:
        with self._transaction() as connection:
            run = connection.execute(
                "SELECT status FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise RunStoreError("cannot append an event for an unregistered run")
            if RunStatus(run["status"]) is RunStatus.COMPLETED:
                raise RunNotActionable("completed Run event ledger is immutable")
            self._event(
                connection,
                run_id=run_id,
                event_type=event_type,
                payload=payload,
                operation_id=operation_id,
                attempt_id=attempt_id,
            )

    def append_event_once(
        self,
        run_id: str,
        event_id: str,
        event_type: str,
        payload: Any,
    ) -> None:
        """Append deterministic audit evidence, or verify an identical prior append."""

        normalized_event_id = _non_empty(event_id, "event_id")
        payload_json = canonical_dumps(payload)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM events WHERE event_id = ?", (normalized_event_id,)
            ).fetchone()
            if existing is not None:
                if (
                    existing["run_id"] != run_id
                    or existing["event_type"] != event_type
                    or existing["payload_json"] != payload_json
                    or existing["operation_id"] is not None
                    or existing["attempt_id"] is not None
                ):
                    raise RunStoreError("idempotent event identity conflicts with prior evidence")
                return
            run = connection.execute(
                "SELECT status FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise RunStoreError("cannot append an event for an unregistered run")
            if RunStatus(run["status"]) is RunStatus.COMPLETED:
                raise RunNotActionable("completed Run event ledger is immutable")
            self._event(
                connection,
                run_id=run_id,
                event_id=normalized_event_id,
                event_type=event_type,
                payload=payload,
            )

    def list_events(self, run_id: str) -> tuple[dict[str, Any], ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY sequence", (run_id,)
            ).fetchall()
        return tuple(
            {
                "sequence": row["sequence"],
                "event_id": row["event_id"],
                "operation_id": row["operation_id"],
                "attempt_id": row["attempt_id"],
                "event_type": row["event_type"],
                "payload": canonical_loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        )

    def count_attempts(self, operation_id: str | None = None) -> int:
        with closing(self._connect()) as connection:
            if operation_id is None:
                return int(connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0])
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM attempts WHERE operation_id = ?", (operation_id,)
                ).fetchone()[0]
            )

    def count_rows(self, table: str, *, run_id: str | None = None) -> int:
        allowed = {
            "runs",
            "approvals",
            "operations",
            "attempts",
            "budget_reservations",
            "events",
            "artifacts",
            "checkpoints",
            "reconciliations",
        }
        if table not in allowed:
            raise ValueError("unsupported RunStore table")
        with closing(self._connect()) as connection:
            if run_id is None:
                return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if table == "attempts":
                return int(
                    connection.execute(
                        """SELECT COUNT(*) FROM attempts a
                           JOIN operations o ON o.operation_id = a.operation_id
                           WHERE o.run_id = ?""",
                        (run_id,),
                    ).fetchone()[0]
                )
            return int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run_id,)
                ).fetchone()[0]
            )
