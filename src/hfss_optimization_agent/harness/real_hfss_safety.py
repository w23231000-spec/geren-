"""Strict readiness authority for the canonical real-HFSS entry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess
from typing import Any

from ..agent.closed_loop_contracts import (
    CLOSED_LOOP_WORKFLOW_ID,
    production_policy_sha256,
)
from ..domain.canonical_json import (
    CanonicalJsonError,
    canonical_dumps,
    canonical_loads,
    require_exact_fields,
)
from ..domain.contracts import CalibrationEvidence, FrozenMap
from .execution_policy import ExecutionPolicy
from .provenance import source_tree_digest


READINESS_SCHEMA_VERSION = "real-hfss-readiness/1.0"
REAL_HFSS_WORKFLOW_ID = CLOSED_LOOP_WORKFLOW_ID
REAL_HFSS_APPROVAL_SCOPE = "real_hfss"
HFSS_WORKER_PROTOCOL = "hfss-composite-request/1.0"
REQUIRED_PROVIDER_FINGERPRINTS = frozenset(
    {
        "agent_source_sha256",
        "supplied_optimizer_source_sha256",
        "supplied_surrogate_source_sha256",
        "hfss_builder_source_sha256",
        "pyaedt_executable_sha256",
        "hfss_worker_protocol",
        "closed_loop_policy_sha256",
    }
)


class RealHFSSSafetyError(RuntimeError):
    """Raised before composition when real HFSS is not exactly authorized."""


def _non_empty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _sha256(value: Any, name: str, *, lengths: tuple[int, ...] = (64,)) -> str:
    normalized = _non_empty(value, name).lower()
    if len(normalized) not in lengths or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{name} must be a hexadecimal digest of length {lengths}")
    return normalized


def _utc_timestamp(value: Any, name: str) -> str:
    try:
        parsed = datetime.fromisoformat(_non_empty(value, name))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class RepositoryEvidence:
    git_head: str
    agent_source_sha256: str
    working_tree_clean: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "git_head", _sha256(self.git_head, "git_head", lengths=(40, 64)))
        object.__setattr__(
            self,
            "agent_source_sha256",
            _sha256(self.agent_source_sha256, "agent_source_sha256"),
        )
        if not isinstance(self.working_tree_clean, bool):
            raise ValueError("working_tree_clean must be boolean")


@dataclass(frozen=True, slots=True)
class RealHFSSReadinessManifestV1:
    schema_version: str
    readiness_id: str
    task_id: str
    run_id: str
    workflow_id: str
    created_at: str
    expires_at: str
    git_head: str
    agent_source_sha256: str
    run_manifest_sha256: str
    design_goal_sha256: str
    hfss_contract_sha256: str
    evaluation_contract_sha256: str
    provider_fingerprints: FrozenMap
    approval_id: str
    approval_scope: str
    execution_policy: ExecutionPolicy
    calibration_evidence: CalibrationEvidence

    def __post_init__(self) -> None:
        if self.schema_version != READINESS_SCHEMA_VERSION:
            raise ValueError(f"readiness schema_version must be {READINESS_SCHEMA_VERSION}")
        for name in ("readiness_id", "task_id", "run_id", "workflow_id", "approval_id", "approval_scope"):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        object.__setattr__(self, "created_at", _utc_timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.created_at:
            raise ValueError("readiness expires_at must be later than created_at")
        object.__setattr__(self, "git_head", _sha256(self.git_head, "git_head", lengths=(40, 64)))
        for name in (
            "agent_source_sha256",
            "run_manifest_sha256",
            "design_goal_sha256",
            "hfss_contract_sha256",
            "evaluation_contract_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        if self.workflow_id != REAL_HFSS_WORKFLOW_ID:
            raise ValueError(f"real readiness must bind workflow {REAL_HFSS_WORKFLOW_ID}")
        if self.approval_scope != REAL_HFSS_APPROVAL_SCOPE:
            raise ValueError(f"real readiness approval_scope must be {REAL_HFSS_APPROVAL_SCOPE}")
        fingerprints = self.provider_fingerprints.to_dict()
        if set(fingerprints) != REQUIRED_PROVIDER_FINGERPRINTS:
            raise ValueError(
                "readiness provider_fingerprints must contain exactly the mandatory "
                "Agent/optimizer/surrogate/Builder/PyAEDT/protocol identities"
            )
        for name in REQUIRED_PROVIDER_FINGERPRINTS - {"hfss_worker_protocol"}:
            fingerprints[name] = _sha256(fingerprints[name], f"provider_fingerprints.{name}")
        if fingerprints["agent_source_sha256"] != self.agent_source_sha256:
            raise ValueError("provider Agent source fingerprint must match readiness source")
        if fingerprints["hfss_worker_protocol"] != HFSS_WORKER_PROTOCOL:
            raise ValueError(f"hfss_worker_protocol must be {HFSS_WORKER_PROTOCOL}")
        if fingerprints["closed_loop_policy_sha256"] != production_policy_sha256():
            raise ValueError("closed_loop_policy_sha256 must bind the Production policy")
        object.__setattr__(self, "provider_fingerprints", FrozenMap.from_mapping(fingerprints))
        calibration = self.calibration_evidence
        if not isinstance(calibration, CalibrationEvidence):
            raise ValueError("readiness calibration_evidence must be typed evidence")
        if not calibration.passed:
            raise ValueError("real readiness requires passing calibration evidence")
        calibration_providers = calibration.provider_fingerprints.to_dict()
        if not calibration_providers or any(
            fingerprints.get(name) != digest
            for name, digest in calibration_providers.items()
        ):
            raise ValueError(
                "calibration evidence provider fingerprints do not match readiness"
            )

    @classmethod
    def from_dict(cls, value: Any) -> "RealHFSSReadinessManifestV1":
        expected = {
            "schema_version",
            "readiness_id",
            "task_id",
            "run_id",
            "workflow_id",
            "created_at",
            "expires_at",
            "git_head",
            "agent_source_sha256",
            "run_manifest_sha256",
            "design_goal_sha256",
            "hfss_contract_sha256",
            "evaluation_contract_sha256",
            "provider_fingerprints",
            "approval_id",
            "approval_scope",
            "execution_policy",
            "calibration_evidence",
        }
        data = require_exact_fields(value, expected, context="RealHFSSReadinessManifestV1")
        return cls(
            **{
                **data,
                "provider_fingerprints": FrozenMap.from_dict(data["provider_fingerprints"]),
                "execution_policy": ExecutionPolicy.from_dict(data["execution_policy"]),
                "calibration_evidence": CalibrationEvidence.from_dict(
                    data["calibration_evidence"]
                ),
            }
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_dumps(self).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RealHFSSAuthorization:
    manifest: RealHFSSReadinessManifestV1
    repository: RepositoryEvidence


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_repository_evidence(repository_root: Path) -> RepositoryEvidence:
    root = Path(repository_root).resolve()
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10.0,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=15.0,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise RealHFSSSafetyError("cannot establish exact Git repository evidence") from exc
    return RepositoryEvidence(
        git_head=head,
        agent_source_sha256=source_tree_digest(root / "src", suffixes=(".py",)),
        working_tree_clean=not status.strip(),
    )


def load_readiness_manifest(path: Path) -> RealHFSSReadinessManifestV1:
    try:
        text = Path(path).read_text(encoding="utf-8")
        payload = canonical_loads(text)
        manifest = RealHFSSReadinessManifestV1.from_dict(payload)
    except (OSError, CanonicalJsonError, ValueError) as exc:
        raise RealHFSSSafetyError(f"invalid real-HFSS readiness manifest: {exc}") from exc
    if text.strip() != canonical_dumps(manifest):
        raise RealHFSSSafetyError("real-HFSS readiness manifest is not canonical JSON")
    return manifest


def _validate_repository_binding(
    manifest: RealHFSSReadinessManifestV1,
    repository: RepositoryEvidence,
    *,
    now: datetime | None = None,
) -> None:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if current >= datetime.fromisoformat(manifest.expires_at):
        raise RealHFSSSafetyError("real-HFSS readiness manifest has expired")
    if current < datetime.fromisoformat(manifest.created_at):
        raise RealHFSSSafetyError("real-HFSS readiness manifest is not yet valid")
    if not repository.working_tree_clean:
        raise RealHFSSSafetyError("real HFSS requires a clean working tree bound to exact HEAD")
    if repository.git_head != manifest.git_head:
        raise RealHFSSSafetyError("readiness git_head does not match the current repository")
    if repository.agent_source_sha256 != manifest.agent_source_sha256:
        raise RealHFSSSafetyError("readiness Agent source fingerprint does not match")
    if manifest.execution_policy != ExecutionPolicy(2, 0):
        raise RealHFSSSafetyError("real HFSS requires max_hfss_solve_launches=2 and zero retries")


def validate_real_hfss_launch_configuration(
    config: Mapping[str, Any],
    *,
    repository_root: Path,
    repository_evidence: RepositoryEvidence | None = None,
    now: datetime | None = None,
) -> RealHFSSAuthorization:
    """Load and validate short-lived authority before Tool composition."""

    if config.get("real_hfss_enabled") is not True:
        raise RealHFSSSafetyError(
            "Real HFSS is disabled; a separately authorized Canary manifest is required."
        )
    raw_path = config.get("real_hfss_readiness_manifest")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise RealHFSSSafetyError("Real HFSS requires a readiness manifest path")
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(repository_root).resolve() / path
    manifest = load_readiness_manifest(path)
    repository = repository_evidence or collect_repository_evidence(repository_root)
    _validate_repository_binding(manifest, repository, now=now)
    return RealHFSSAuthorization(manifest, repository)


def validate_real_hfss_workflow_binding(
    authorization: RealHFSSAuthorization,
    *,
    run_manifest_sha256: str,
    design_goal_sha256: str,
    hfss_contract_sha256: str,
    evaluation_contract_sha256: str,
    provider_fingerprints: Mapping[str, Any],
    task_id: str,
    run_id: str,
    workflow_id: str,
    comparison_context_id: str,
    calibration_evidence_sha256: str,
    now: datetime | None = None,
) -> None:
    """Validate all causal inputs before constructing a worker or workspace."""

    manifest = authorization.manifest
    _validate_repository_binding(manifest, authorization.repository, now=now)
    expected = {
        "run_manifest_sha256": run_manifest_sha256,
        "design_goal_sha256": design_goal_sha256,
        "hfss_contract_sha256": hfss_contract_sha256,
        "evaluation_contract_sha256": evaluation_contract_sha256,
        "task_id": task_id,
        "run_id": run_id,
        "workflow_id": workflow_id,
        "comparison_context_id": comparison_context_id,
    }
    for name, actual in expected.items():
        expected_value = (
            manifest.calibration_evidence.comparison_context_id
            if name == "comparison_context_id"
            else getattr(manifest, name)
        )
        if expected_value != actual:
            raise RealHFSSSafetyError(f"readiness {name} does not match the requested Run")
    if manifest.calibration_evidence.digest != calibration_evidence_sha256:
        raise RealHFSSSafetyError(
            "readiness calibration_evidence_sha256 does not match the requested Run"
        )
    if manifest.provider_fingerprints.to_dict() != dict(provider_fingerprints):
        raise RealHFSSSafetyError("readiness provider/source fingerprints do not match")
