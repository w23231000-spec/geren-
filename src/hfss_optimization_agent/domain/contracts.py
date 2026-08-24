"""Immutable Phase-1 domain contracts and evidence-backed Best policy."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Mapping

from ..core.models import (
    CandidateParameters,
    EvaluationComparison,
    EvaluationResult,
    OptimizationBatch,
)
from .canonical_json import CanonicalJsonError, canonical_dumps, require_exact_fields


STATE_SCHEMA_VERSION = "2.0"
CALIBRATION_EVIDENCE_SCHEMA_VERSION = "calibration-evidence/1.1"
CALIBRATION_POLICY_VERSION = "paired-surrogate-hfss/1.0"
MINIMUM_CALIBRATION_CASES = 3
MINIMUM_CALIBRATION_COMPARABLE_PAIRS = 2
CALIBRATION_PROVIDER_FINGERPRINTS = frozenset(
    {
        "supplied_surrogate_source_sha256",
        "hfss_builder_source_sha256",
        "pyaedt_executable_sha256",
        "hfss_worker_protocol",
    }
)
CALIBRATION_ARTIFACT_ROLES = frozenset(
    {
        "candidate_parameters",
        "surrogate_result",
        "hfss_result",
        "hfss_touchstone",
        "hfss_project",
    }
)
CALIBRATION_POLICY_FIELDS = frozenset(
    {
        "max_complex_rmse",
        "max_magnitude_db_rmse",
        "minimum_pairwise_ranking_agreement",
        "frequency_tolerance_hz",
        "impedance_tolerance_ohm",
        "require_comparison_context_id",
        "minimum_case_count",
        "minimum_comparable_pairs",
    }
)


def _non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _finite(value: float, field_name: str) -> float:
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class FrozenMap:
    """Canonical immutable representation of an open JSON object."""

    items: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        keys = [key for key, _ in self.items]
        if any(not isinstance(key, str) for key in keys):
            raise ValueError("FrozenMap keys must be strings")
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ValueError("FrozenMap keys must be unique and sorted")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "FrozenMap":
        return cls(
            tuple(
                (str(key), _freeze_json(item))
                for key, item in sorted((value or {}).items())
            )
        )

    @classmethod
    def from_dict(cls, value: Any) -> "FrozenMap":
        if not isinstance(value, Mapping):
            raise CanonicalJsonError("FrozenMap must be an object")
        return cls.from_mapping(value)

    def to_dict(self) -> dict[str, Any]:
        return {key: _thaw_json(value) for key, value in self.items}

    def __canonical_json__(self) -> dict[str, Any]:
        return self.to_dict()


def _sha256(value: str, field_name: str) -> str:
    normalized = _non_empty(value, field_name).lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return normalized


def calibration_policy_sha256(policy: Any) -> str:
    return hashlib.sha256(canonical_dumps(policy).encode("utf-8")).hexdigest()


def calibration_artifact_manifest_sha256(artifacts: Any) -> str:
    return hashlib.sha256(canonical_dumps(artifacts).encode("utf-8")).hexdigest()


def _freeze_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return _finite(value, "JSON number")
    if isinstance(value, Mapping):
        return FrozenMap.from_mapping(value)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError(f"unsupported canonical value type {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, FrozenMap):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class DesignGoal:
    goal_id: str
    evaluation_contract_id: str
    comparison_context_id: str
    objective: str
    target_specification: FrozenMap = FrozenMap()

    def __post_init__(self) -> None:
        for name in (
            "goal_id",
            "evaluation_contract_id",
            "comparison_context_id",
            "objective",
        ):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))

    @classmethod
    def from_dict(cls, value: Any) -> "DesignGoal":
        data = require_exact_fields(
            value,
            {
                "goal_id",
                "evaluation_contract_id",
                "comparison_context_id",
                "objective",
                "target_specification",
            },
            context="DesignGoal",
        )
        return cls(
            goal_id=data["goal_id"],
            evaluation_contract_id=data["evaluation_contract_id"],
            comparison_context_id=data["comparison_context_id"],
            objective=data["objective"],
            target_specification=FrozenMap.from_dict(data["target_specification"]),
        )

    def to_target_specification(self) -> dict[str, Any]:
        return self.target_specification.to_dict()


@dataclass(frozen=True, slots=True)
class CalibrationArtifactReceipt:
    artifact_id: str
    case_id: str
    candidate_id: str
    role: str
    uri: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        for name in ("artifact_id", "case_id", "candidate_id", "role", "uri"):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        if self.role not in CALIBRATION_ARTIFACT_ROLES:
            raise ValueError(f"unsupported Calibration artifact role {self.role!r}")
        uri_path = PurePosixPath(self.uri)
        if (
            "\\" in self.uri
            or uri_path.is_absolute()
            or any(part in {".", ".."} for part in uri_path.parts)
        ):
            raise ValueError("CalibrationArtifactReceipt.uri must be a relative POSIX URI")
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise ValueError("CalibrationArtifactReceipt.size_bytes must be an integer")
        if self.size_bytes <= 0:
            raise ValueError("CalibrationArtifactReceipt.size_bytes must be positive")

    @classmethod
    def from_dict(cls, value: Any) -> "CalibrationArtifactReceipt":
        data = require_exact_fields(
            value,
            {
                "artifact_id",
                "case_id",
                "candidate_id",
                "role",
                "uri",
                "sha256",
                "size_bytes",
            },
            context="CalibrationArtifactReceipt",
        )
        return cls(**data)


@dataclass(frozen=True, slots=True)
class CalibrationEvidence:
    """Immutable paired surrogate/HFSS evidence used by the real-run gate."""

    schema_version: str
    evidence_id: str
    created_at: str
    policy_version: str
    comparison_context_id: str
    passed: bool
    case_ids: tuple[str, ...]
    provider_fingerprints: FrozenMap
    policy: FrozenMap
    policy_sha256: str
    hfss_contract_sha256: str
    report: FrozenMap
    source_artifacts: tuple[CalibrationArtifactReceipt, ...]

    def __post_init__(self) -> None:
        if self.schema_version != CALIBRATION_EVIDENCE_SCHEMA_VERSION:
            raise ValueError(
                "CalibrationEvidence schema_version must be "
                f"{CALIBRATION_EVIDENCE_SCHEMA_VERSION}"
            )
        for name in (
            "evidence_id",
            "created_at",
            "comparison_context_id",
        ):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        if self.policy_version != CALIBRATION_POLICY_VERSION:
            raise ValueError(
                f"CalibrationEvidence policy_version must be {CALIBRATION_POLICY_VERSION}"
            )
        if not isinstance(self.passed, bool):
            raise ValueError("CalibrationEvidence.passed must be boolean")
        if (
            len(self.case_ids) < MINIMUM_CALIBRATION_CASES
            or len(self.case_ids) != len(set(self.case_ids))
        ):
            raise ValueError(
                f"CalibrationEvidence requires at least {MINIMUM_CALIBRATION_CASES} unique cases"
            )
        for case_id in self.case_ids:
            _non_empty(case_id, "CalibrationEvidence.case_id")

        policy = self.policy.to_dict()
        if set(policy) != CALIBRATION_POLICY_FIELDS:
            raise ValueError("CalibrationEvidence policy fields are incomplete or unknown")
        for name in (
            "max_complex_rmse",
            "max_magnitude_db_rmse",
            "frequency_tolerance_hz",
            "impedance_tolerance_ohm",
        ):
            if _finite(policy[name], f"policy.{name}") < 0.0:
                raise ValueError(f"policy.{name} cannot be negative")
        ranking = _finite(
            policy["minimum_pairwise_ranking_agreement"],
            "policy.minimum_pairwise_ranking_agreement",
        )
        if not 0.0 <= ranking <= 1.0:
            raise ValueError("policy.minimum_pairwise_ranking_agreement must be in [0, 1]")
        if policy["require_comparison_context_id"] is not True:
            raise ValueError("real Calibration policy must require comparison context identity")
        if (
            isinstance(policy["minimum_case_count"], bool)
            or not isinstance(policy["minimum_case_count"], int)
            or policy["minimum_case_count"] < MINIMUM_CALIBRATION_CASES
            or len(self.case_ids) < policy["minimum_case_count"]
        ):
            raise ValueError("Calibration policy/cases do not meet minimum case cardinality")
        if (
            isinstance(policy["minimum_comparable_pairs"], bool)
            or not isinstance(policy["minimum_comparable_pairs"], int)
            or policy["minimum_comparable_pairs"] < MINIMUM_CALIBRATION_COMPARABLE_PAIRS
        ):
            raise ValueError("Calibration policy requires too few comparable ranking pairs")
        actual_policy_sha256 = calibration_policy_sha256(policy)
        object.__setattr__(self, "policy_sha256", _sha256(self.policy_sha256, "policy_sha256"))
        if self.policy_sha256 != actual_policy_sha256:
            raise ValueError("CalibrationEvidence policy SHA-256 differs from policy content")
        object.__setattr__(
            self,
            "hfss_contract_sha256",
            _sha256(self.hfss_contract_sha256, "hfss_contract_sha256"),
        )

        providers = self.provider_fingerprints.to_dict()
        if set(providers) != CALIBRATION_PROVIDER_FINGERPRINTS:
            raise ValueError(
                "CalibrationEvidence must bind the complete causal Calibration provider set"
            )
        for name in CALIBRATION_PROVIDER_FINGERPRINTS - {"hfss_worker_protocol"}:
            providers[name] = _sha256(providers[name], f"provider_fingerprints.{name}")
        if providers["hfss_worker_protocol"] != "hfss-composite-request/1.0":
            raise ValueError("CalibrationEvidence uses an unsupported HFSS worker protocol")
        object.__setattr__(self, "provider_fingerprints", FrozenMap.from_mapping(providers))

        report = self.report.to_dict()
        expected_report_fields = {
            "passed",
            "cases",
            "mean_complex_rmse",
            "mean_magnitude_db_rmse",
            "pairwise_ranking_agreement",
            "comparable_pairs",
            "comparison_context_id",
            "reasons",
        }
        if set(report) != expected_report_fields:
            raise ValueError("CalibrationEvidence report fields are incomplete or unknown")
        report_cases = report["cases"]
        if not isinstance(report_cases, list) or tuple(
            item.get("case_id") if isinstance(item, dict) else None for item in report_cases
        ) != self.case_ids:
            raise ValueError("CalibrationEvidence report/case identities differ")
        candidate_by_case: dict[str, str] = {}
        expected_case_fields = {
            "case_id",
            "candidate_id",
            "complex_rmse",
            "magnitude_db_rmse",
            "max_complex_error",
            "surrogate_worst_s11",
            "hfss_worst_s11",
        }
        for item in report_cases:
            if set(item) != expected_case_fields:
                raise ValueError("CalibrationEvidence report case fields differ")
            candidate_by_case[item["case_id"]] = _non_empty(
                item["candidate_id"], "CalibrationEvidence.report.candidate_id"
            )
            for name in expected_case_fields - {"case_id", "candidate_id"}:
                _finite(item[name], f"CalibrationEvidence.report.{name}")
        if len(set(candidate_by_case.values())) != len(candidate_by_case):
            raise ValueError("CalibrationEvidence candidates must be unique")

        computed_mean_complex = sum(item["complex_rmse"] for item in report_cases) / len(
            report_cases
        )
        computed_mean_db = sum(item["magnitude_db_rmse"] for item in report_cases) / len(
            report_cases
        )
        comparable = 0
        agreements = 0
        for left_index, left in enumerate(report_cases):
            for right in report_cases[left_index + 1 :]:
                surrogate_delta = (
                    left["surrogate_worst_s11"] - right["surrogate_worst_s11"]
                )
                hfss_delta = left["hfss_worst_s11"] - right["hfss_worst_s11"]
                if math.isclose(surrogate_delta, 0.0, abs_tol=1e-15) or math.isclose(
                    hfss_delta, 0.0, abs_tol=1e-15
                ):
                    continue
                comparable += 1
                agreements += int((surrogate_delta < 0.0) == (hfss_delta < 0.0))
        computed_agreement = 0.0 if comparable == 0 else agreements / comparable

        comparable_pairs = report["comparable_pairs"]
        if (
            isinstance(comparable_pairs, bool)
            or not isinstance(comparable_pairs, int)
            or comparable_pairs < policy["minimum_comparable_pairs"]
            or comparable_pairs != comparable
        ):
            raise ValueError("CalibrationEvidence has insufficient comparable ranking pairs")
        mean_complex = _finite(report["mean_complex_rmse"], "report.mean_complex_rmse")
        mean_db = _finite(report["mean_magnitude_db_rmse"], "report.mean_magnitude_db_rmse")
        agreement = _finite(
            report["pairwise_ranking_agreement"], "report.pairwise_ranking_agreement"
        )
        if not math.isclose(mean_complex, computed_mean_complex, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError("CalibrationEvidence mean complex RMSE is not recomputed from cases")
        if not math.isclose(mean_db, computed_mean_db, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError("CalibrationEvidence mean dB RMSE is not recomputed from cases")
        if not math.isclose(agreement, computed_agreement, rel_tol=0.0, abs_tol=1e-15):
            raise ValueError("CalibrationEvidence ranking is not recomputed from cases")
        expected_reasons: list[str] = []
        if mean_complex > policy["max_complex_rmse"]:
            expected_reasons.append("mean_complex_rmse_exceeded")
        if mean_db > policy["max_magnitude_db_rmse"]:
            expected_reasons.append("mean_magnitude_db_rmse_exceeded")
        if agreement < policy["minimum_pairwise_ranking_agreement"]:
            expected_reasons.append("pairwise_ranking_agreement_below_threshold")
        if report["reasons"] != expected_reasons:
            raise ValueError("CalibrationEvidence report reasons do not match policy")
        if report["passed"] is not (not expected_reasons) or self.passed is not report["passed"]:
            raise ValueError("CalibrationEvidence report/pass status differs")
        if report["comparison_context_id"] != self.comparison_context_id:
            raise ValueError("CalibrationEvidence report/context differs")

        artifact_ids: set[str] = set()
        artifact_uris: set[str] = set()
        roles_by_case = {case_id: set() for case_id in self.case_ids}
        for artifact in self.source_artifacts:
            if artifact.case_id not in roles_by_case:
                raise ValueError("Calibration artifact uses an unknown case")
            if artifact.candidate_id != candidate_by_case[artifact.case_id]:
                raise ValueError("Calibration artifact candidate identity differs")
            if artifact.artifact_id in artifact_ids or artifact.uri in artifact_uris:
                raise ValueError("Calibration artifact identity/URI must be unique")
            artifact_ids.add(artifact.artifact_id)
            artifact_uris.add(artifact.uri)
            if artifact.role in roles_by_case[artifact.case_id]:
                raise ValueError("Calibration artifact role is duplicated for a case")
            roles_by_case[artifact.case_id].add(artifact.role)
        if any(roles != CALIBRATION_ARTIFACT_ROLES for roles in roles_by_case.values()):
            raise ValueError("Calibration evidence lacks required source artifact roles")

    @classmethod
    def from_dict(cls, value: Any) -> "CalibrationEvidence":
        data = require_exact_fields(
            value,
            {
                "schema_version",
                "evidence_id",
                "created_at",
                "policy_version",
                "comparison_context_id",
                "passed",
                "case_ids",
                "provider_fingerprints",
                "policy",
                "policy_sha256",
                "hfss_contract_sha256",
                "report",
                "source_artifacts",
            },
            context="CalibrationEvidence",
        )
        if not isinstance(data["case_ids"], list) or not isinstance(data["source_artifacts"], list):
            raise CanonicalJsonError("CalibrationEvidence identity fields must be arrays")
        return cls(
            schema_version=data["schema_version"],
            evidence_id=data["evidence_id"],
            created_at=data["created_at"],
            policy_version=data["policy_version"],
            comparison_context_id=data["comparison_context_id"],
            passed=data["passed"],
            case_ids=tuple(data["case_ids"]),
            provider_fingerprints=FrozenMap.from_dict(data["provider_fingerprints"]),
            policy=FrozenMap.from_dict(data["policy"]),
            policy_sha256=data["policy_sha256"],
            hfss_contract_sha256=data["hfss_contract_sha256"],
            report=FrozenMap.from_dict(data["report"]),
            source_artifacts=tuple(
                CalibrationArtifactReceipt.from_dict(item) for item in data["source_artifacts"]
            ),
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_dumps(self).encode("utf-8")).hexdigest()

    @property
    def source_artifact_ids(self) -> tuple[str, ...]:
        return tuple(artifact.artifact_id for artifact in self.source_artifacts)

    @property
    def source_artifact_manifest_sha256(self) -> str:
        return calibration_artifact_manifest_sha256(self.source_artifacts)


@dataclass(frozen=True, slots=True)
class RunManifestV2:
    schema_version: str
    run_id: str
    task_id: str
    workflow_id: str
    created_at: str
    design_goal: DesignGoal
    baseline_candidate_id: str
    code_revision: str | None = None
    provider_fingerprints: FrozenMap = FrozenMap()
    config_fingerprints: FrozenMap = FrozenMap()
    real_execution: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError(f"RunManifest schema_version must be {STATE_SCHEMA_VERSION}")
        for name in (
            "run_id",
            "task_id",
            "workflow_id",
            "created_at",
            "baseline_candidate_id",
        ):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        if self.code_revision is not None:
            object.__setattr__(
                self, "code_revision", _non_empty(self.code_revision, "code_revision")
            )

    @classmethod
    def from_dict(cls, value: Any) -> "RunManifestV2":
        expected = {
            "schema_version",
            "run_id",
            "task_id",
            "workflow_id",
            "created_at",
            "design_goal",
            "baseline_candidate_id",
            "code_revision",
            "provider_fingerprints",
            "config_fingerprints",
            "real_execution",
        }
        data = require_exact_fields(value, expected, context="RunManifestV2")
        return cls(
            schema_version=data["schema_version"],
            run_id=data["run_id"],
            task_id=data["task_id"],
            workflow_id=data["workflow_id"],
            created_at=data["created_at"],
            design_goal=DesignGoal.from_dict(data["design_goal"]),
            baseline_candidate_id=data["baseline_candidate_id"],
            code_revision=data["code_revision"],
            provider_fingerprints=FrozenMap.from_dict(data["provider_fingerprints"]),
            config_fingerprints=FrozenMap.from_dict(data["config_fingerprints"]),
            real_execution=data["real_execution"],
        )


@dataclass(frozen=True, slots=True)
class CandidateSnapshot:
    candidate_id: str
    iteration: int
    context_id: str
    parameters: tuple[tuple[str, float], ...]
    source: str
    parent_candidate_id: str | None = None
    metadata: FrozenMap = FrozenMap()

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", _non_empty(self.candidate_id, "candidate_id"))
        object.__setattr__(self, "context_id", _non_empty(self.context_id, "context_id"))
        object.__setattr__(self, "source", _non_empty(self.source, "source"))
        if not isinstance(self.iteration, int) or self.iteration < 0:
            raise ValueError("iteration must be a non-negative integer")
        names = [name for name, _ in self.parameters]
        if names != sorted(names) or len(names) != len(set(names)) or not names:
            raise ValueError("candidate parameter names must be non-empty, unique, and sorted")
        normalized = tuple((name, _finite(value, f"parameter {name}")) for name, value in self.parameters)
        object.__setattr__(self, "parameters", normalized)
        if self.parent_candidate_id is not None:
            object.__setattr__(
                self,
                "parent_candidate_id",
                _non_empty(self.parent_candidate_id, "parent_candidate_id"),
            )

    @classmethod
    def from_candidate(
        cls,
        candidate: CandidateParameters,
        *,
        context_id: str,
        source: str,
        parent_candidate_id: str | None = None,
    ) -> "CandidateSnapshot":
        return cls(
            candidate_id=candidate.candidate_id,
            iteration=candidate.iteration,
            context_id=context_id,
            parameters=tuple(sorted((name, float(value)) for name, value in candidate.values.items())),
            source=source,
            parent_candidate_id=parent_candidate_id,
            metadata=FrozenMap.from_mapping(candidate.metadata),
        )

    @classmethod
    def from_dict(cls, value: Any) -> "CandidateSnapshot":
        data = require_exact_fields(
            value,
            {
                "candidate_id",
                "iteration",
                "context_id",
                "parameters",
                "source",
                "parent_candidate_id",
                "metadata",
            },
            context="CandidateSnapshot",
        )
        if not isinstance(data["parameters"], list):
            raise CanonicalJsonError("CandidateSnapshot.parameters must be an array")
        parameters = []
        for item in data["parameters"]:
            if not isinstance(item, list) or len(item) != 2:
                raise CanonicalJsonError("each candidate parameter must be [name, value]")
            parameters.append((item[0], item[1]))
        return cls(
            candidate_id=data["candidate_id"],
            iteration=data["iteration"],
            context_id=data["context_id"],
            parameters=tuple(parameters),
            source=data["source"],
            parent_candidate_id=data["parent_candidate_id"],
            metadata=FrozenMap.from_dict(data["metadata"]),
        )

    def to_candidate(self) -> CandidateParameters:
        return CandidateParameters(
            self.candidate_id,
            self.iteration,
            dict(self.parameters),
            self.metadata.to_dict(),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    uri: str
    role: str
    media_type: str
    run_id: str
    context_id: str
    candidate_id: str | None = None
    sha256: str | None = None

    def __post_init__(self) -> None:
        for name in ("artifact_id", "uri", "role", "media_type", "run_id", "context_id"):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        uri_path = PurePosixPath(self.uri)
        if (
            "\\" in self.uri
            or uri_path.is_absolute()
            or any(part in {".", ".."} for part in uri_path.parts)
        ):
            raise ValueError("ArtifactRef.uri must be a relative POSIX-style URI")
        if self.candidate_id is not None:
            object.__setattr__(self, "candidate_id", _non_empty(self.candidate_id, "candidate_id"))
        if self.sha256 is not None:
            digest = self.sha256.lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("ArtifactRef.sha256 must be a 64-character hex digest")
            object.__setattr__(self, "sha256", digest)

    @classmethod
    def from_dict(cls, value: Any) -> "ArtifactRef":
        data = require_exact_fields(
            value,
            {
                "artifact_id",
                "uri",
                "role",
                "media_type",
                "run_id",
                "context_id",
                "candidate_id",
                "sha256",
            },
            context="ArtifactRef",
        )
        return cls(**data)


def _normalize_evaluation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    copied = dict(payload)
    for key in ("rules", "rule_results"):
        normalized = []
        for rule in copied.get(key, []):
            item = dict(rule)
            if item.get("frequency_band") is not None:
                item["frequency_band"] = tuple(item["frequency_band"])
            normalized.append(item)
        copied[key] = normalized
    plan = dict(copied.get("frequency_plan", {}))
    for key in ("core_band", "lower_margin_band", "upper_margin_band"):
        if key in plan:
            plan[key] = tuple(plan[key])
    copied["frequency_plan"] = plan
    return copied


@dataclass(frozen=True, slots=True)
class EvaluationRecord:
    record_id: str
    run_id: str
    context_id: str
    candidate_id: str
    stage: str
    payload: FrozenMap
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("record_id", "run_id", "context_id", "candidate_id", "stage"):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        result = self.to_result()
        if result.candidate_id != self.candidate_id or result.evaluated_stage != self.stage:
            raise ValueError("EvaluationRecord identity does not match its payload")
        if len(self.artifact_refs) != len(set(self.artifact_refs)):
            raise ValueError("EvaluationRecord artifact references must be unique")

    @classmethod
    def from_result(
        cls,
        result: EvaluationResult,
        *,
        run_id: str,
        context_id: str,
        record_id: str | None = None,
        artifact_refs: tuple[str, ...] = (),
    ) -> "EvaluationRecord":
        return cls(
            record_id=record_id or f"evaluation:{result.candidate_id}:{result.evaluated_stage}",
            run_id=run_id,
            context_id=context_id,
            candidate_id=result.candidate_id,
            stage=result.evaluated_stage,
            payload=FrozenMap.from_mapping(result.to_dict()),
            artifact_refs=artifact_refs,
        )

    @classmethod
    def from_dict(cls, value: Any) -> "EvaluationRecord":
        data = require_exact_fields(
            value,
            {
                "record_id",
                "run_id",
                "context_id",
                "candidate_id",
                "stage",
                "payload",
                "artifact_refs",
            },
            context="EvaluationRecord",
        )
        return cls(
            record_id=data["record_id"],
            run_id=data["run_id"],
            context_id=data["context_id"],
            candidate_id=data["candidate_id"],
            stage=data["stage"],
            payload=FrozenMap.from_dict(data["payload"]),
            artifact_refs=tuple(data["artifact_refs"]),
        )

    def to_result(self) -> EvaluationResult:
        return EvaluationResult(**_normalize_evaluation_payload(self.payload.to_dict()))


@dataclass(frozen=True, slots=True)
class ComparisonRecord:
    record_id: str
    run_id: str
    context_id: str
    baseline_evaluation_id: str
    candidate_evaluation_id: str
    baseline_candidate_id: str
    candidate_id: str
    classification: str
    promotion_eligible: bool
    promotion_reason: str | None
    payload: FrozenMap
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "record_id",
            "run_id",
            "context_id",
            "baseline_evaluation_id",
            "candidate_evaluation_id",
            "baseline_candidate_id",
            "candidate_id",
            "classification",
        ):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        comparison = self.to_comparison()
        if (
            comparison.classification != self.classification
            or comparison.promotion_eligible != self.promotion_eligible
            or comparison.promotion_reason != self.promotion_reason
        ):
            raise ValueError("ComparisonRecord summary does not match its payload")
        required = {self.baseline_evaluation_id, self.candidate_evaluation_id}
        if not required.issubset(set(self.evidence_ids)):
            raise ValueError("ComparisonRecord must cite both EvaluationRecord IDs")

    @classmethod
    def from_comparison(
        cls,
        comparison: EvaluationComparison,
        *,
        run_id: str,
        context_id: str,
        baseline_evaluation_id: str,
        candidate_evaluation_id: str,
        baseline_candidate_id: str,
        candidate_id: str,
        record_id: str | None = None,
    ) -> "ComparisonRecord":
        return cls(
            record_id=record_id or f"comparison:{baseline_candidate_id}:{candidate_id}",
            run_id=run_id,
            context_id=context_id,
            baseline_evaluation_id=baseline_evaluation_id,
            candidate_evaluation_id=candidate_evaluation_id,
            baseline_candidate_id=baseline_candidate_id,
            candidate_id=candidate_id,
            classification=comparison.classification,
            promotion_eligible=comparison.promotion_eligible,
            promotion_reason=comparison.promotion_reason,
            payload=FrozenMap.from_mapping(comparison.to_dict()),
            evidence_ids=(baseline_evaluation_id, candidate_evaluation_id),
        )

    @classmethod
    def from_dict(cls, value: Any) -> "ComparisonRecord":
        data = require_exact_fields(
            value,
            {
                "record_id",
                "run_id",
                "context_id",
                "baseline_evaluation_id",
                "candidate_evaluation_id",
                "baseline_candidate_id",
                "candidate_id",
                "classification",
                "promotion_eligible",
                "promotion_reason",
                "payload",
                "evidence_ids",
            },
            context="ComparisonRecord",
        )
        return cls(
            **{
                **data,
                "payload": FrozenMap.from_dict(data["payload"]),
                "evidence_ids": tuple(data["evidence_ids"]),
            }
        )

    def to_comparison(self) -> EvaluationComparison:
        return EvaluationComparison(**self.payload.to_dict())


@dataclass(frozen=True, slots=True)
class BestPolicy:
    run_id: str
    context_id: str
    selected_candidate_id: str
    seed_evaluation_id: str
    selection_comparison_id: str | None
    reason: str

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "context_id",
            "selected_candidate_id",
            "seed_evaluation_id",
            "reason",
        ):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        if self.selection_comparison_id is not None:
            object.__setattr__(
                self,
                "selection_comparison_id",
                _non_empty(self.selection_comparison_id, "selection_comparison_id"),
            )

    @classmethod
    def seed(
        cls,
        *,
        run_id: str,
        context_id: str,
        baseline_candidate_id: str,
        baseline_evaluation_id: str,
    ) -> "BestPolicy":
        return cls(
            run_id,
            context_id,
            baseline_candidate_id,
            baseline_evaluation_id,
            None,
            "Baseline seed established from baseline evaluation evidence.",
        )

    def promote(self, record: ComparisonRecord) -> "BestPolicy":
        if record.run_id != self.run_id or record.context_id != self.context_id:
            raise ValueError("BestPolicy and ComparisonRecord run/context do not match")
        if not record.promotion_eligible:
            raise ValueError("BestPolicy cannot promote without eligible Comparison evidence")
        return BestPolicy(
            run_id=self.run_id,
            context_id=self.context_id,
            selected_candidate_id=record.candidate_id,
            seed_evaluation_id=self.seed_evaluation_id,
            selection_comparison_id=record.record_id,
            reason=record.promotion_reason or "Comparison evidence authorized promotion.",
        )

    @classmethod
    def from_dict(cls, value: Any) -> "BestPolicy":
        data = require_exact_fields(
            value,
            {
                "run_id",
                "context_id",
                "selected_candidate_id",
                "seed_evaluation_id",
                "selection_comparison_id",
                "reason",
            },
            context="BestPolicy",
        )
        return cls(**data)


class DecisionAction(StrEnum):
    RUN_HFSS = "run_hfss"
    PASS = "pass"
    STOP = "stop"
    WAITING_RECONCILIATION = "waiting_reconciliation"


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    decision_id: str
    run_id: str
    context_id: str
    action: DecisionAction
    reason_code: str
    reason: str
    candidate_id: str | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("decision_id", "run_id", "context_id", "reason_code", "reason"):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        object.__setattr__(self, "action", DecisionAction(self.action))
        if self.candidate_id is not None:
            object.__setattr__(self, "candidate_id", _non_empty(self.candidate_id, "candidate_id"))
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("DecisionOutcome evidence IDs must be unique")

    @classmethod
    def from_dict(cls, value: Any) -> "DecisionOutcome":
        data = require_exact_fields(
            value,
            {
                "decision_id",
                "run_id",
                "context_id",
                "action",
                "reason_code",
                "reason",
                "candidate_id",
                "evidence_ids",
            },
            context="DecisionOutcome",
        )
        return cls(**{**data, "evidence_ids": tuple(data["evidence_ids"])})


@dataclass(frozen=True, slots=True)
class OptimizationRunRecord:
    run_id: str
    success: bool
    candidate_ids: tuple[str, ...]
    recommended_candidate_id: str | None
    evaluations: int
    metadata: FrozenMap
    artifact_refs: tuple[str, ...]
    error: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _non_empty(self.run_id, "optimization run_id"))
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("OptimizationRunRecord candidate IDs must be unique")
        if self.success:
            if not self.candidate_ids or self.recommended_candidate_id not in self.candidate_ids:
                raise ValueError("successful optimization requires a valid recommended candidate")
        elif not self.error:
            raise ValueError("failed optimization requires an error")

    @classmethod
    def from_batch(cls, batch: OptimizationBatch) -> "OptimizationRunRecord":
        return cls(
            run_id=batch.run_id,
            success=batch.success,
            candidate_ids=tuple(candidate.candidate_id for candidate in batch.candidates),
            recommended_candidate_id=batch.recommended_candidate_id,
            evaluations=batch.evaluations,
            metadata=FrozenMap.from_mapping(batch.metadata),
            artifact_refs=tuple(batch.artifact_paths),
            error=batch.error,
        )

    @classmethod
    def from_dict(cls, value: Any) -> "OptimizationRunRecord":
        data = require_exact_fields(
            value,
            {
                "run_id",
                "success",
                "candidate_ids",
                "recommended_candidate_id",
                "evaluations",
                "metadata",
                "artifact_refs",
                "error",
            },
            context="OptimizationRunRecord",
        )
        return cls(
            **{
                **data,
                "candidate_ids": tuple(data["candidate_ids"]),
                "metadata": FrozenMap.from_dict(data["metadata"]),
                "artifact_refs": tuple(data["artifact_refs"]),
            }
        )

    def to_batch(self, candidates: Mapping[str, CandidateSnapshot]) -> OptimizationBatch:
        return OptimizationBatch(
            run_id=self.run_id,
            success=self.success,
            candidates=[candidates[candidate_id].to_candidate() for candidate_id in self.candidate_ids],
            recommended_candidate_id=self.recommended_candidate_id,
            evaluations=self.evaluations,
            metadata=self.metadata.to_dict(),
            artifact_paths=list(self.artifact_refs),
            error=self.error,
        )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()
