"""Fail-closed authority for a two-solve optimization-outcome HFSS diagnostic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..agent.closed_loop_contracts import production_policy_sha256
from ..core.models import CandidateParameters
from ..domain.canonical_json import (
    CanonicalJsonError,
    canonical_dumps,
    canonical_loads,
    require_exact_fields,
)
from ..domain.contracts import CandidateSnapshot, FrozenMap
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


OPTIMIZATION_DIAGNOSTIC_SCHEMA_VERSION = "hfss-optimization-diagnostic/1.0"
OPTIMIZATION_DIAGNOSTIC_WORKFLOW_ID = "hfss-optimization-diagnostic-v1"
OPTIMIZATION_DIAGNOSTIC_APPROVAL_SCOPE = "real_hfss"


class OptimizationDiagnosticSafetyError(RuntimeError):
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


def _relative_posix_uri(value: str, name: str) -> str:
    normalized = _non_empty(value, name)
    path = PurePosixPath(normalized)
    if "\\" in normalized or path.is_absolute() or any(
        part in {".", ".."} for part in path.parts
    ):
        raise ValueError(f"{name} must be a repository-relative POSIX URI")
    return normalized


def diagnostic_plan_sha256(candidates: tuple[CandidateSnapshot, ...]) -> str:
    return hashlib.sha256(canonical_dumps(candidates).encode("utf-8")).hexdigest()


def optimization_candidate_plan(
    summary_path: Path,
    *,
    comparison_context_id: str,
) -> tuple[CandidateSnapshot, CandidateSnapshot]:
    """Load one completed full optimization and freeze its unique recommendation."""

    try:
        payload = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OptimizationDiagnosticSafetyError(
            f"invalid optimization summary: {exc}"
        ) from exc
    if payload.get("status") != "completed":
        raise OptimizationDiagnosticSafetyError("optimization summary is not completed")
    if payload.get("validation_status") != "surrogate_only":
        raise OptimizationDiagnosticSafetyError(
            "optimization summary must retain surrogate_only status"
        )
    algorithm = payload.get("algorithm")
    if not isinstance(algorithm, Mapping) or algorithm.get("quick_mode") is not False:
        raise OptimizationDiagnosticSafetyError(
            "optimization diagnostic requires a full, non-quick optimizer run"
        )
    point_id = payload.get("recommended_point_id")
    if not isinstance(point_id, str) or not point_id.strip():
        raise OptimizationDiagnosticSafetyError(
            "optimization summary has no recommended point"
        )
    recommended = payload.get("recommended_parameters")
    if not isinstance(recommended, Mapping) or not isinstance(
        recommended.get("model_units"), Mapping
    ):
        raise OptimizationDiagnosticSafetyError(
            "optimization summary has no model-unit recommendation"
        )
    raw_values = dict(recommended["model_units"])
    schema = supplied_nine_parameter_schema()
    if set(raw_values) != set(schema.by_name):
        raise OptimizationDiagnosticSafetyError(
            "recommended parameter names differ from the nine-parameter contract"
        )
    values: dict[str, float] = {}
    for definition in schema.parameters:
        value = float(raw_values[definition.name])
        if not math.isfinite(value):
            raise OptimizationDiagnosticSafetyError(
                f"recommended parameter {definition.name} is not finite"
            )
        if definition.lower_bound is not None and value < definition.lower_bound:
            raise OptimizationDiagnosticSafetyError(
                f"recommended parameter {definition.name} is below its lower bound"
            )
        if definition.upper_bound is not None and value > definition.upper_bound:
            raise OptimizationDiagnosticSafetyError(
                f"recommended parameter {definition.name} is above its upper bound"
            )
        values[definition.name] = value

    improvement = payload.get("recommended_improvement")
    configured = improvement.get("configured_objectives") if isinstance(improvement, Mapping) else None
    worst = configured.get("worst_s11") if isinstance(configured, Mapping) else None
    mean_power = configured.get("mean_reflected_power") if isinstance(configured, Mapping) else None
    if not isinstance(worst, Mapping) or float(worst.get("improvement_toward_goal", 0.0)) <= 0.0:
        raise OptimizationDiagnosticSafetyError(
            "recommended point does not predict an improved worst S11"
        )
    if not isinstance(mean_power, Mapping) or float(
        mean_power.get("improvement_toward_goal", 0.0)
    ) <= 0.0:
        raise OptimizationDiagnosticSafetyError(
            "recommended point does not predict reduced mean reflected power"
        )

    baseline = supplied_baseline_candidate()
    candidate = CandidateParameters(
        candidate_id=f"optimized_{point_id}",
        iteration=1,
        values=values,
        metadata={
            "role": "optimization_diagnostic_candidate",
            "parameter_contract": "supplied-nine-parameter-v1",
            "unit": "m",
            "optimizer_run_id": str(payload.get("run_id", "")),
            "recommended_point_id": point_id,
            "selection": "frozen_full_optimizer_recommendation",
        },
    )
    if candidate.values == baseline.values:
        raise OptimizationDiagnosticSafetyError(
            "recommended point is identical to the baseline"
        )
    return (
        CandidateSnapshot.from_candidate(
            baseline,
            context_id=comparison_context_id,
            source="supplied-nine-parameter-baseline-v1",
        ),
        CandidateSnapshot.from_candidate(
            candidate,
            context_id=comparison_context_id,
            source="full-surrogate-optimizer-recommendation-v1",
            parent_candidate_id=baseline.candidate_id,
        ),
    )


@dataclass(frozen=True, slots=True)
class OptimizationDiagnosticManifestV1:
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
    optimization_summary_uri: str
    optimization_summary_sha256: str
    optimizer_run_id: str
    recommended_point_id: str
    diagnostic_plan_sha256: str
    provider_fingerprints: FrozenMap
    candidates: tuple[CandidateSnapshot, ...]
    approval_id: str
    approval_scope: str
    execution_policy: ExecutionPolicy

    def __post_init__(self) -> None:
        if self.schema_version != OPTIMIZATION_DIAGNOSTIC_SCHEMA_VERSION:
            raise ValueError("unsupported optimization diagnostic manifest schema")
        for name in (
            "campaign_id",
            "task_id",
            "run_id",
            "workflow_id",
            "hfss_contract_id",
            "optimizer_run_id",
            "recommended_point_id",
            "approval_id",
            "approval_scope",
        ):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        if self.workflow_id != OPTIMIZATION_DIAGNOSTIC_WORKFLOW_ID:
            raise ValueError("optimization diagnostic workflow identity differs")
        if self.approval_scope != OPTIMIZATION_DIAGNOSTIC_APPROVAL_SCOPE:
            raise ValueError("optimization diagnostic approval scope differs")
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "expires_at", _timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.created_at:
            raise ValueError("optimization diagnostic approval must expire after creation")
        object.__setattr__(
            self, "git_head", _digest(self.git_head, "git_head", lengths=(40, 64))
        )
        for name in (
            "agent_source_sha256",
            "hfss_contract_sha256",
            "model_alignment_sha256",
            "optimization_summary_sha256",
            "diagnostic_plan_sha256",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(
            self,
            "optimization_summary_uri",
            _relative_posix_uri(self.optimization_summary_uri, "optimization_summary_uri"),
        )
        if self.execution_policy != ExecutionPolicy(2, 0):
            raise ValueError(
                "optimization diagnostic requires exactly two solves and no retries"
            )
        providers = self.provider_fingerprints.to_dict()
        if set(providers) != REQUIRED_PROVIDER_FINGERPRINTS:
            raise ValueError("optimization diagnostic provider fingerprints are incomplete")
        for name in REQUIRED_PROVIDER_FINGERPRINTS - {"hfss_worker_protocol"}:
            providers[name] = _digest(providers[name], f"provider_fingerprints.{name}")
        if providers["hfss_worker_protocol"] != HFSS_WORKER_PROTOCOL:
            raise ValueError("optimization diagnostic worker protocol differs")
        if providers["agent_source_sha256"] != self.agent_source_sha256:
            raise ValueError("optimization diagnostic Agent fingerprint differs")
        object.__setattr__(self, "provider_fingerprints", FrozenMap.from_mapping(providers))
        if len(self.candidates) != 2:
            raise ValueError("optimization diagnostic requires exactly two candidates")
        baseline, optimized = self.candidates
        if baseline.candidate_id != "baseline":
            raise ValueError("optimization diagnostic must start with baseline")
        if optimized.candidate_id != f"optimized_{self.recommended_point_id}":
            raise ValueError("optimization diagnostic candidate identity differs")
        if optimized.parent_candidate_id != baseline.candidate_id:
            raise ValueError("optimized candidate must name baseline as parent")
        if baseline.context_id != optimized.context_id:
            raise ValueError("optimization diagnostic candidate contexts differ")
        if diagnostic_plan_sha256(self.candidates) != self.diagnostic_plan_sha256:
            raise ValueError("optimization diagnostic candidate plan digest differs")

    @classmethod
    def from_dict(cls, value: Any) -> "OptimizationDiagnosticManifestV1":
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
                "optimization_summary_uri",
                "optimization_summary_sha256",
                "optimizer_run_id",
                "recommended_point_id",
                "diagnostic_plan_sha256",
                "provider_fingerprints",
                "candidates",
                "approval_id",
                "approval_scope",
                "execution_policy",
            },
            context="OptimizationDiagnosticManifestV1",
        )
        if not isinstance(data["candidates"], list):
            raise CanonicalJsonError("optimization diagnostic candidates must be an array")
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
class OptimizationDiagnosticAuthorization:
    manifest: OptimizationDiagnosticManifestV1
    repository: RepositoryEvidence
    alignment: ModelAlignmentContract
    contract: HFSSRunContract
    optimization_summary_path: Path

    @property
    def approval_id(self) -> str:
        return self.manifest.approval_id

    @property
    def digest(self) -> str:
        return self.manifest.digest


def load_optimization_diagnostic_manifest(
    path: Path,
) -> OptimizationDiagnosticManifestV1:
    source = Path(path)
    try:
        raw = source.read_bytes()
        payload = canonical_loads(raw.decode("utf-8"))
        manifest = OptimizationDiagnosticManifestV1.from_dict(payload)
    except (OSError, UnicodeDecodeError, CanonicalJsonError, ValueError) as exc:
        raise OptimizationDiagnosticSafetyError(
            f"invalid optimization diagnostic manifest: {exc}"
        ) from exc
    if canonical_dumps(manifest).encode("utf-8") != raw:
        raise OptimizationDiagnosticSafetyError(
            "optimization diagnostic manifest is not canonical JSON"
        )
    return manifest


def _resolve_repository_file(root: Path, raw_path: Any, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise OptimizationDiagnosticSafetyError(
            f"optimization diagnostic requires {label}"
        )
    base = root.resolve()
    path = Path(raw_path)
    if not path.is_absolute():
        path = base / path
    resolved = path.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise OptimizationDiagnosticSafetyError(
            f"{label} must be inside the repository"
        ) from exc
    if not resolved.is_file():
        raise OptimizationDiagnosticSafetyError(f"{label} is missing: {resolved}")
    return resolved


def validate_optimization_diagnostic_configuration(
    config: Mapping[str, Any],
    *,
    repository_root: Path,
    repository_evidence: RepositoryEvidence | None = None,
    now: datetime | None = None,
) -> OptimizationDiagnosticAuthorization:
    if config.get("real_hfss_optimization_diagnostic_enabled") is not True:
        raise OptimizationDiagnosticSafetyError(
            "Real HFSS optimization diagnostic is disabled"
        )
    raw_manifest_path = config.get("real_hfss_optimization_diagnostic_manifest")
    if not isinstance(raw_manifest_path, str) or not raw_manifest_path.strip():
        raise OptimizationDiagnosticSafetyError(
            "optimization diagnostic requires a manifest path"
        )
    root = Path(repository_root).resolve()
    manifest_path = Path(raw_manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest = load_optimization_diagnostic_manifest(manifest_path)
    repository = repository_evidence or collect_repository_evidence(root)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    if not repository.working_tree_clean:
        raise OptimizationDiagnosticSafetyError(
            "optimization diagnostic requires a clean working tree"
        )
    if repository.git_head != manifest.git_head:
        raise OptimizationDiagnosticSafetyError("optimization diagnostic git_head differs")
    if repository.agent_source_sha256 != manifest.agent_source_sha256:
        raise OptimizationDiagnosticSafetyError(
            "optimization diagnostic Agent source differs"
        )
    if current < manifest.created_at or current >= manifest.expires_at:
        raise OptimizationDiagnosticSafetyError(
            "optimization diagnostic manifest is not currently valid"
        )

    alignment_path = _resolve_repository_file(
        root, config.get("model_alignment_path"), "a versioned model alignment"
    )
    contract_path = _resolve_repository_file(
        root, config.get("hfss_contract_path"), "an HFSS contract"
    )
    summary_path = _resolve_repository_file(
        root, manifest.optimization_summary_uri, "the frozen optimization summary"
    )
    try:
        alignment = load_model_alignment_contract(alignment_path)
        contract = load_hfss_contract(contract_path)
    except (OSError, CanonicalJsonError, ValueError) as exc:
        raise OptimizationDiagnosticSafetyError(
            f"optimization diagnostic authority file is invalid: {exc}"
        ) from exc
    if alignment.digest != manifest.model_alignment_sha256:
        raise OptimizationDiagnosticSafetyError(
            "model alignment differs from optimization diagnostic authority"
        )
    if file_sha256(contract_path) != manifest.hfss_contract_sha256:
        raise OptimizationDiagnosticSafetyError(
            "HFSS contract bytes differ from optimization diagnostic authority"
        )
    if contract.contract_id != manifest.hfss_contract_id:
        raise OptimizationDiagnosticSafetyError(
            "HFSS contract identity differs from optimization diagnostic authority"
        )
    if file_sha256(summary_path) != manifest.optimization_summary_sha256:
        raise OptimizationDiagnosticSafetyError(
            "optimization summary differs from optimization diagnostic authority"
        )
    context = contract.metadata.get("comparison_context_id")
    if context != alignment.comparison_context_id:
        raise OptimizationDiagnosticSafetyError(
            "HFSS contract and model alignment contexts differ"
        )
    expected_candidates = optimization_candidate_plan(
        summary_path,
        comparison_context_id=alignment.comparison_context_id,
    )
    if expected_candidates != manifest.candidates:
        raise OptimizationDiagnosticSafetyError(
            "optimization diagnostic candidate plan differs from authority"
        )

    optimizer_root = root / "vendor" / "optimizer"
    builder_root = root / "vendor" / "hfss_builder"
    raw_pyaedt = config.get("pyaedt_python")
    if not isinstance(raw_pyaedt, str) or not Path(raw_pyaedt).is_file():
        raise OptimizationDiagnosticSafetyError(
            "configured PyAEDT Python is unavailable"
        )
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
        raise OptimizationDiagnosticSafetyError(
            "optimization diagnostic provider/source identity has drifted"
        )
    return OptimizationDiagnosticAuthorization(
        manifest,
        repository,
        alignment,
        contract,
        summary_path,
    )
