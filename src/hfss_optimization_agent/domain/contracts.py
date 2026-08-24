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
CALIBRATION_EVIDENCE_SCHEMA_VERSION = "calibration-evidence/1.0"


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
    report: FrozenMap
    source_artifact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != CALIBRATION_EVIDENCE_SCHEMA_VERSION:
            raise ValueError(
                "CalibrationEvidence schema_version must be "
                f"{CALIBRATION_EVIDENCE_SCHEMA_VERSION}"
            )
        for name in (
            "evidence_id",
            "created_at",
            "policy_version",
            "comparison_context_id",
        ):
            object.__setattr__(self, name, _non_empty(getattr(self, name), name))
        if not isinstance(self.passed, bool):
            raise ValueError("CalibrationEvidence.passed must be boolean")
        if not self.case_ids or len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("CalibrationEvidence.case_ids must be non-empty and unique")
        for case_id in self.case_ids:
            _non_empty(case_id, "CalibrationEvidence.case_id")
        for artifact_id in self.source_artifact_ids:
            _non_empty(artifact_id, "CalibrationEvidence.source_artifact_id")
        providers = self.provider_fingerprints.to_dict()
        if not providers or any(
            not isinstance(value, str) or not value.strip()
            for value in providers.values()
        ):
            raise ValueError(
                "CalibrationEvidence.provider_fingerprints must contain non-empty strings"
            )
        report = self.report.to_dict()
        if report.get("passed") is not self.passed:
            raise ValueError("CalibrationEvidence report/pass status differs")
        if report.get("comparison_context_id") != self.comparison_context_id:
            raise ValueError("CalibrationEvidence report/context differs")
        report_cases = report.get("cases")
        if not isinstance(report_cases, list) or tuple(
            item.get("case_id") if isinstance(item, dict) else None for item in report_cases
        ) != self.case_ids:
            raise ValueError("CalibrationEvidence report/case identities differ")

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
                "report",
                "source_artifact_ids",
            },
            context="CalibrationEvidence",
        )
        if not isinstance(data["case_ids"], list) or not isinstance(
            data["source_artifact_ids"], list
        ):
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
            report=FrozenMap.from_dict(data["report"]),
            source_artifact_ids=tuple(data["source_artifact_ids"]),
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_dumps(self).encode("utf-8")).hexdigest()


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
