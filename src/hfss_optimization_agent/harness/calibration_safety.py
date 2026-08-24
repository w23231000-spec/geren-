"""Fail-closed authority for the three-solve physical Calibration campaign."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Mapping

from ..agent.closed_loop_contracts import production_policy_sha256
from ..domain.canonical_json import (
    CanonicalJsonError,
    canonical_dumps,
    canonical_loads,
    require_exact_fields,
)
from ..domain.contracts import CandidateSnapshot, FrozenMap
from ..evaluation.calibration import CalibrationPolicy
from ..evaluation.model_alignment import (
    ModelAlignmentContract,
    load_model_alignment_contract,
)
from ..hfss.contracts import HFSSRunContract, attest_builder, load_hfss_contract
from ..parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
    supplied_nine_parameter_schema,
)
from .execution_policy import ExecutionPolicy
from .provenance import source_tree_digest
from .real_hfss_safety import (
    HFSS_WORKER_PROTOCOL,
    REQUIRED_PROVIDER_FINGERPRINTS,
    RepositoryEvidence,
    collect_repository_evidence,
    file_sha256,
)


CALIBRATION_COLLECTION_SCHEMA_VERSION = "hfss-calibration-collection/1.0"
CALIBRATION_COLLECTION_WORKFLOW_ID = "hfss-calibration-collection-v1"
CALIBRATION_COLLECTION_APPROVAL_SCOPE = "real_hfss"


class CalibrationSafetyError(RuntimeError):
    pass


def _non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _timestamp(value: str, name: str) -> str:
    try:
        parsed = datetime.fromisoformat(_non_empty(value, name))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _digest(value: str, name: str, *, lengths: tuple[int, ...] = (64,)) -> str:
    normalized = _non_empty(value, name).lower()
    if len(normalized) not in lengths or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{name} must be a hexadecimal digest")
    return normalized


def deterministic_calibration_candidates(
    *, comparison_context_id: str
) -> tuple[CandidateSnapshot, CandidateSnapshot, CandidateSnapshot]:
    """Return baseline plus two safe, deterministic, separated interior points."""

    schema = supplied_nine_parameter_schema()
    baseline = supplied_baseline_candidate()
    values_one: dict[str, float] = {}
    values_two: dict[str, float] = {}
    for index, definition in enumerate(schema.parameters):
        if definition.lower_bound is None or definition.upper_bound is None:
            raise ValueError("Calibration candidates require finite parameter bounds")
        low = float(definition.lower_bound)
        high = float(definition.upper_bound)
        first_fraction = 0.35 if index % 2 == 0 else 0.65
        second_fraction = 1.0 - first_fraction
        values_one[definition.name] = low + first_fraction * (high - low)
        values_two[definition.name] = low + second_fraction * (high - low)
    from ..core.models import CandidateParameters

    first = CandidateParameters(
        "calibration_candidate_1",
        1,
        values_one,
        {"role": "calibration", "strategy": "alternating-interior-35-65-v1"},
    )
    second = CandidateParameters(
        "calibration_candidate_2",
        1,
        values_two,
        {"role": "calibration", "strategy": "alternating-interior-65-35-v1"},
    )
    return (
        CandidateSnapshot.from_candidate(
            baseline,
            context_id=comparison_context_id,
            source="supplied-nine-parameter-baseline-v1",
        ),
        CandidateSnapshot.from_candidate(
            first,
            context_id=comparison_context_id,
            source="deterministic-calibration-plan-v1",
            parent_candidate_id=baseline.candidate_id,
        ),
        CandidateSnapshot.from_candidate(
            second,
            context_id=comparison_context_id,
            source="deterministic-calibration-plan-v1",
            parent_candidate_id=baseline.candidate_id,
        ),
    )


def calibration_plan_sha256(candidates: tuple[CandidateSnapshot, ...]) -> str:
    return hashlib.sha256(canonical_dumps(candidates).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CalibrationCollectionManifestV1:
    schema_version: str
    campaign_id: str
    task_id: str
    run_id: str
    workflow_id: str
    created_at: str
    expires_at: str
    git_head: str
    agent_source_sha256: str
    hfss_contract_id: str
    hfss_contract_sha256: str
    model_alignment_sha256: str
    calibration_policy_sha256: str
    calibration_plan_sha256: str
    provider_fingerprints: FrozenMap
    candidates: tuple[CandidateSnapshot, ...]
    approval_id: str
    approval_scope: str
    execution_policy: ExecutionPolicy

    def __post_init__(self) -> None:
        if self.schema_version != CALIBRATION_COLLECTION_SCHEMA_VERSION:
            raise ValueError("unsupported Calibration collection manifest schema")
        for name in (
            "campaign_id",
            "task_id",
            "run_id",
            "workflow_id",
            "hfss_contract_id",
            "approval_id",
            "approval_scope",
        ):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        if self.workflow_id != CALIBRATION_COLLECTION_WORKFLOW_ID:
            raise ValueError("Calibration collection workflow identity differs")
        if self.approval_scope != CALIBRATION_COLLECTION_APPROVAL_SCOPE:
            raise ValueError("Calibration collection approval scope differs")
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "expires_at", _timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.created_at:
            raise ValueError("Calibration collection approval must expire after creation")
        object.__setattr__(
            self, "git_head", _digest(self.git_head, "git_head", lengths=(40, 64))
        )
        for name in (
            "agent_source_sha256",
            "hfss_contract_sha256",
            "model_alignment_sha256",
            "calibration_policy_sha256",
            "calibration_plan_sha256",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        if self.execution_policy != ExecutionPolicy(3, 0):
            raise ValueError("Calibration collection requires exactly three solves and no retries")
        providers = self.provider_fingerprints.to_dict()
        if set(providers) != REQUIRED_PROVIDER_FINGERPRINTS:
            raise ValueError("Calibration collection provider fingerprints are incomplete")
        for name in REQUIRED_PROVIDER_FINGERPRINTS - {"hfss_worker_protocol"}:
            providers[name] = _digest(providers[name], f"provider_fingerprints.{name}")
        if providers["hfss_worker_protocol"] != HFSS_WORKER_PROTOCOL:
            raise ValueError("Calibration collection worker protocol differs")
        if providers["agent_source_sha256"] != self.agent_source_sha256:
            raise ValueError("Calibration collection Agent fingerprint differs")
        object.__setattr__(self, "provider_fingerprints", FrozenMap.from_mapping(providers))
        if len(self.candidates) != 3:
            raise ValueError("Calibration collection requires exactly three candidates")
        if tuple(item.candidate_id for item in self.candidates) != (
            "baseline",
            "calibration_candidate_1",
            "calibration_candidate_2",
        ):
            raise ValueError("Calibration collection candidate identities differ")
        if calibration_plan_sha256(self.candidates) != self.calibration_plan_sha256:
            raise ValueError("Calibration collection candidate plan digest differs")

    @classmethod
    def from_dict(cls, value: Any) -> "CalibrationCollectionManifestV1":
        data = require_exact_fields(
            value,
            {
                "schema_version",
                "campaign_id",
                "task_id",
                "run_id",
                "workflow_id",
                "created_at",
                "expires_at",
                "git_head",
                "agent_source_sha256",
                "hfss_contract_id",
                "hfss_contract_sha256",
                "model_alignment_sha256",
                "calibration_policy_sha256",
                "calibration_plan_sha256",
                "provider_fingerprints",
                "candidates",
                "approval_id",
                "approval_scope",
                "execution_policy",
            },
            context="CalibrationCollectionManifestV1",
        )
        if not isinstance(data["candidates"], list):
            raise CanonicalJsonError("Calibration collection candidates must be an array")
        return cls(
            **{
                **data,
                "provider_fingerprints": FrozenMap.from_dict(
                    data["provider_fingerprints"]
                ),
                "candidates": tuple(
                    CandidateSnapshot.from_dict(item) for item in data["candidates"]
                ),
                "execution_policy": ExecutionPolicy.from_dict(data["execution_policy"]),
            }
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_dumps(self).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CalibrationCollectionAuthorization:
    manifest: CalibrationCollectionManifestV1
    repository: RepositoryEvidence
    policy: CalibrationPolicy
    alignment: ModelAlignmentContract
    contract: HFSSRunContract


def load_calibration_collection_manifest(path: Path) -> CalibrationCollectionManifestV1:
    source = Path(path)
    try:
        raw = source.read_bytes()
        text = raw.decode("utf-8")
        payload = canonical_loads(text)
        manifest = CalibrationCollectionManifestV1.from_dict(payload)
    except (OSError, UnicodeDecodeError, CanonicalJsonError, ValueError) as exc:
        raise CalibrationSafetyError(f"invalid Calibration collection manifest: {exc}") from exc
    if canonical_dumps(manifest).encode("utf-8") != raw:
        raise CalibrationSafetyError("Calibration collection manifest is not canonical JSON")
    return manifest


def _resolve_repository_file(root: Path, raw_path: Any, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise CalibrationSafetyError(f"Calibration collection requires {label}")
    base = root.resolve()
    path = Path(raw_path)
    if not path.is_absolute():
        path = base / path
    resolved = path.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise CalibrationSafetyError(f"{label} must be inside the repository") from exc
    if not resolved.is_file():
        raise CalibrationSafetyError(f"{label} is missing: {resolved}")
    return resolved


def validate_calibration_collection_configuration(
    config: Mapping[str, Any],
    *,
    repository_root: Path,
    repository_evidence: RepositoryEvidence | None = None,
    now: datetime | None = None,
) -> CalibrationCollectionAuthorization:
    if config.get("real_hfss_calibration_enabled") is not True:
        raise CalibrationSafetyError("Real HFSS Calibration collection is disabled")
    raw_manifest_path = config.get("real_hfss_calibration_manifest")
    if not isinstance(raw_manifest_path, str) or not raw_manifest_path.strip():
        raise CalibrationSafetyError("Calibration collection requires a manifest path")
    root = Path(repository_root).resolve()
    manifest_path = Path(raw_manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest = load_calibration_collection_manifest(manifest_path)
    repository = repository_evidence or collect_repository_evidence(root)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    if not repository.working_tree_clean:
        raise CalibrationSafetyError("Calibration collection requires a clean working tree")
    if repository.git_head != manifest.git_head:
        raise CalibrationSafetyError("Calibration collection git_head differs")
    if repository.agent_source_sha256 != manifest.agent_source_sha256:
        raise CalibrationSafetyError("Calibration collection Agent source differs")
    if current < manifest.created_at or current >= manifest.expires_at:
        raise CalibrationSafetyError("Calibration collection manifest is not currently valid")

    policy_path = _resolve_repository_file(
        root, config.get("calibration_policy_path"), "a versioned Calibration policy"
    )
    alignment_path = _resolve_repository_file(
        root, config.get("model_alignment_path"), "a versioned model alignment"
    )
    contract_path = _resolve_repository_file(
        root, config.get("hfss_contract_path"), "an HFSS contract"
    )
    try:
        policy = CalibrationPolicy.from_dict(
            canonical_loads(policy_path.read_text(encoding="utf-8"))
        )
        alignment = load_model_alignment_contract(alignment_path)
        contract = load_hfss_contract(contract_path)
    except (OSError, CanonicalJsonError, ValueError) as exc:
        raise CalibrationSafetyError(f"Calibration authority file is invalid: {exc}") from exc
    policy_digest = hashlib.sha256(
        canonical_dumps(policy.to_dict()).encode("utf-8")
    ).hexdigest()
    if policy_digest != manifest.calibration_policy_sha256:
        raise CalibrationSafetyError("Calibration policy differs from collection authority")
    if alignment.digest != manifest.model_alignment_sha256:
        raise CalibrationSafetyError("model alignment differs from collection authority")
    if file_sha256(contract_path) != manifest.hfss_contract_sha256:
        raise CalibrationSafetyError("HFSS contract bytes differ from collection authority")
    if contract.contract_id != manifest.hfss_contract_id:
        raise CalibrationSafetyError("HFSS contract identity differs from collection authority")
    context = contract.metadata.get("comparison_context_id")
    if (
        context != alignment.comparison_context_id
        or context != manifest.candidates[0].context_id
    ):
        raise CalibrationSafetyError("Calibration comparison context differs")
    expected_candidates = deterministic_calibration_candidates(
        comparison_context_id=alignment.comparison_context_id
    )
    if expected_candidates != manifest.candidates:
        raise CalibrationSafetyError("Calibration candidate plan differs from authority")

    optimizer_root = root / "vendor" / "optimizer"
    builder_root = root / "vendor" / "hfss_builder"
    raw_pyaedt = config.get("pyaedt_python")
    if not isinstance(raw_pyaedt, str) or not Path(raw_pyaedt).is_file():
        raise CalibrationSafetyError("configured PyAEDT Python is unavailable")
    providers = {
        "agent_source_sha256": source_tree_digest(root / "src", suffixes=(".py",)),
        "supplied_optimizer_source_sha256": source_tree_digest(
            optimizer_root, suffixes=(".py", ".csv", ".toml")
        ),
        "supplied_surrogate_source_sha256": source_tree_digest(
            optimizer_root, suffixes=(".py", ".csv", ".toml")
        ),
        "hfss_builder_source_sha256": attest_builder(
            builder_root, contract.builder_id
        ).source_digest,
        "pyaedt_executable_sha256": file_sha256(Path(raw_pyaedt)),
        "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
        "closed_loop_policy_sha256": production_policy_sha256(),
    }
    if providers != manifest.provider_fingerprints.to_dict():
        raise CalibrationSafetyError("Calibration provider/source identity has drifted")
    return CalibrationCollectionAuthorization(
        manifest,
        repository,
        policy,
        alignment,
        contract,
    )
