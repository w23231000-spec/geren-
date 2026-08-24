"""Strict operator authority for resolving indeterminate physical actions.

Reconciliation is deliberately separate from retry.  It may only attach new
evidence to one durable UNKNOWN attempt and conclude that the original action
failed or succeeded.  It never creates another attempt and never refunds the
conservatively consumed budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
from typing import Any

from ..domain.canonical_json import CanonicalJsonError, canonical_dumps, require_exact_fields
from ..domain.contracts import FrozenMap


RECONCILIATION_SCHEMA_VERSION = "operation-reconciliation/1.0"
RECONCILIATION_APPROVAL_SCOPE = "reconcile_unknown"


class ReconciliationResolution(StrEnum):
    CONFIRMED_SUCCEEDED = "CONFIRMED_SUCCEEDED"
    CONFIRMED_FAILED = "CONFIRMED_FAILED"


def _non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _timestamp(value: str, name: str) -> str:
    normalized = _non_empty(value, name)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ReconciliationRequest:
    """Short-lived, operation-bound operator decision with canonical evidence."""

    schema_version: str
    reconciliation_id: str
    run_id: str
    operation_id: str
    attempt_id: str
    approval_id: str
    issued_at: str
    expires_at: str
    resolution: ReconciliationResolution
    reason: str
    evidence: FrozenMap

    def __post_init__(self) -> None:
        if self.schema_version != RECONCILIATION_SCHEMA_VERSION:
            raise ValueError(
                "ReconciliationRequest schema_version must be "
                f"{RECONCILIATION_SCHEMA_VERSION}"
            )
        for name in (
            "reconciliation_id",
            "run_id",
            "operation_id",
            "attempt_id",
            "approval_id",
            "reason",
        ):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        issued = _timestamp(self.issued_at, "issued_at")
        expires = _timestamp(self.expires_at, "expires_at")
        if expires <= issued:
            raise ValueError("ReconciliationRequest expires_at must be after issued_at")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)
        object.__setattr__(
            self, "resolution", ReconciliationResolution(self.resolution)
        )
        if not self.evidence.items:
            raise ValueError("ReconciliationRequest evidence must not be empty")

    @classmethod
    def from_dict(cls, value: Any) -> "ReconciliationRequest":
        data = require_exact_fields(
            value,
            {
                "schema_version",
                "reconciliation_id",
                "run_id",
                "operation_id",
                "attempt_id",
                "approval_id",
                "issued_at",
                "expires_at",
                "resolution",
                "reason",
                "evidence",
            },
            context="ReconciliationRequest",
        )
        try:
            resolution = ReconciliationResolution(data["resolution"])
        except (TypeError, ValueError) as exc:
            raise CanonicalJsonError("ReconciliationRequest resolution is invalid") from exc
        return cls(
            schema_version=data["schema_version"],
            reconciliation_id=data["reconciliation_id"],
            run_id=data["run_id"],
            operation_id=data["operation_id"],
            attempt_id=data["attempt_id"],
            approval_id=data["approval_id"],
            issued_at=data["issued_at"],
            expires_at=data["expires_at"],
            resolution=resolution,
            reason=data["reason"],
            evidence=FrozenMap.from_dict(data["evidence"]),
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_dumps(self).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ReconciliationSnapshot:
    request: ReconciliationRequest
    request_sha256: str
    result_sha256: str | None
    evidence_artifact_id: str
    created_at: str
