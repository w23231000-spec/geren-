"""Serializable domain models that keep curves separate from derived metrics."""

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .enums import SUCCESS_WORKFLOW_STATUSES, WorkflowStatus


@dataclass(slots=True)
class CandidateParameters:
    candidate_id: str
    iteration: int
    values: dict[str, float]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FrequencyPlan:
    core_band: tuple[float, float] = (6.0, 18.0)
    lower_margin_band: tuple[float, float] = (5.0, 6.0)
    upper_margin_band: tuple[float, float] = (18.0, 19.0)
    tolerance_ghz: float = 1e-9

    def __post_init__(self) -> None:
        for name in ("core_band", "lower_margin_band", "upper_margin_band"):
            value = getattr(self, name)
            try:
                object.__setattr__(self, name, tuple(float(item) for item in value))
            except (TypeError, ValueError):
                continue

    @property
    def validation_error(self) -> str | None:
        bands = (self.lower_margin_band, self.core_band, self.upper_margin_band)
        if not math.isfinite(float(self.tolerance_ghz)) or self.tolerance_ghz <= 0:
            return "FrequencyPlan tolerance must be positive and finite"
        if any(len(band) != 2 or any(not math.isfinite(float(item)) for item in band) or band[0] >= band[1] for band in bands):
            return "FrequencyPlan bands must have finite start < end"
        if abs(self.lower_margin_band[1] - self.core_band[0]) > self.tolerance_ghz:
            return "FrequencyPlan lower margin and core bands must be continuous"
        if abs(self.core_band[1] - self.upper_margin_band[0]) > self.tolerance_ghz:
            return "FrequencyPlan core and upper margin bands must be continuous"
        return None

    @property
    def is_valid(self) -> bool:
        return self.validation_error is None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "FrequencyPlan":
        return cls(tuple(value.get("core_band", ())), tuple(value.get("lower_margin_band", ())), tuple(value.get("upper_margin_band", ())), float(value.get("tolerance_ghz", 1e-9)))

    @property
    def lower_margin_target(self) -> float:
        return self.core_band[0] - self.lower_margin_band[0]

    @property
    def upper_margin_target(self) -> float:
        return self.upper_margin_band[1] - self.core_band[1]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HFSSResult:
    candidate_id: str
    success: bool
    frequency: list[float] = field(default_factory=list)
    s_parameters: dict[str, list[float]] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    project_path: str | None = None
    artifact_paths: list[str] = field(default_factory=list)
    error: str | None = None
    complex_response: "ComplexSParameters | None" = None
    execution_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvaluationResult:
    candidate_id: str
    improved: bool
    pass_target: bool
    baseline_metrics: dict[str, float]
    current_metrics: dict[str, float]
    delta_metrics: dict[str, float]
    score: float
    reason: str
    evaluated_stage: str = "optimized"
    status: str = "INVALID"
    rule_results: list[dict[str, Any]] = field(default_factory=list)
    passed_rule_count: int = 0
    failed_rule_count: int = 0
    worst_issue: dict[str, Any] | None = None
    worst_margin: float | None = None
    data_quality: dict[str, Any] = field(default_factory=dict)
    rules: list[dict[str, Any]] = field(default_factory=list)
    hard_failed_rule_count: int = 0
    soft_failed_rule_count: int = 0
    worst_soft_issue: dict[str, Any] | None = None
    frequency_margin: dict[str, Any] = field(default_factory=dict)
    frequency_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvaluationComparison:
    improved_rules: list[dict[str, Any]] = field(default_factory=list)
    degraded_rules: list[dict[str, Any]] = field(default_factory=list)
    unchanged_rules: list[dict[str, Any]] = field(default_factory=list)
    resolved_failures: list[str] = field(default_factory=list)
    remaining_failures: list[str] = field(default_factory=list)
    new_failures: list[str] = field(default_factory=list)
    worst_issue_migration: dict[str, Any] | None = None
    classification: str = "INVALID"
    reason: str | None = None
    lower_frequency_margin_delta: float | None = None
    upper_frequency_margin_delta: float | None = None
    baseline_frequency_margin: dict[str, Any] = field(default_factory=dict)
    candidate_frequency_margin: dict[str, Any] = field(default_factory=dict)
    frequency_margin_delta: dict[str, Any] = field(default_factory=dict)
    promotion_eligible: bool = False
    promotion_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TerminalOutcome:
    """Authoritative terminal meaning bound to one run and evidence context."""

    status: WorkflowStatus
    reason_code: str
    reason: str
    run_id: str = ""
    context_id: str = ""
    candidate_id: str | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", WorkflowStatus(self.status))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("TerminalOutcome evidence IDs must be unique")

    @property
    def successful(self) -> bool:
        return self.status in SUCCESS_WORKFLOW_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ComplexSParameters:
    """JSON-safe complex two-port response with explicit frequency and port metadata."""

    frequency_hz: list[float]
    real: list[list[list[float]]]
    imag: list[list[list[float]]]
    port_order: tuple[str, str] = ("port_1", "port_2")
    reference_impedance_ohm: float = 50.0

    def __post_init__(self) -> None:
        size = len(self.frequency_hz)
        if size < 2:
            raise ValueError("Complex S parameters require at least two frequency points")
        if any(not math.isfinite(float(value)) for value in self.frequency_hz):
            raise ValueError("S-parameter frequencies must be finite")
        if any(right <= left for left, right in zip(self.frequency_hz, self.frequency_hz[1:])):
            raise ValueError("S-parameter frequencies must be strictly increasing")
        if len(self.real) != size or len(self.imag) != size:
            raise ValueError("S-parameter matrix count must match the frequency count")
        for component_name, matrices in (("real", self.real), ("imag", self.imag)):
            for matrix in matrices:
                if len(matrix) != 2 or any(len(row) != 2 for row in matrix):
                    raise ValueError(f"{component_name} S-parameter matrices must all be 2x2")
                if any(not math.isfinite(float(value)) for row in matrix for value in row):
                    raise ValueError(f"{component_name} S-parameter values must be finite")
        if len(self.port_order) != 2 or self.port_order[0] == self.port_order[1]:
            raise ValueError("Exactly two distinct ports are required")
        if not math.isfinite(self.reference_impedance_ohm) or self.reference_impedance_ohm <= 0.0:
            raise ValueError("Reference impedance must be a positive finite number")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_complex_matrices(
        cls,
        *,
        frequency_hz: list[float],
        matrices: list[list[list[complex]]],
        port_order: tuple[str, str] = ("port_1", "port_2"),
        reference_impedance_ohm: float = 50.0,
    ) -> "ComplexSParameters":
        return cls(
            frequency_hz=[float(value) for value in frequency_hz],
            real=[[[float(value.real) for value in row] for row in matrix] for matrix in matrices],
            imag=[[[float(value.imag) for value in row] for row in matrix] for matrix in matrices],
            port_order=port_order,
            reference_impedance_ohm=float(reference_impedance_ohm),
        )


@dataclass(slots=True)
class SParameterResult:
    """One baseline or candidate response from a named fast-simulation provider."""

    candidate_id: str
    success: bool
    response: ComplexSParameters | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    provider: str = "unknown"
    model_version: str = "unknown"
    calibration_status: str = "uncalibrated"
    artifact_paths: list[str] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.success and self.response is None:
            raise ValueError("A successful S-parameter result requires a response")
        if not self.success and not self.error:
            raise ValueError("A failed S-parameter result requires an error")
        if any(not math.isfinite(float(value)) for value in self.metrics.values()):
            raise ValueError("S-parameter metrics must be finite")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OptimizationBatch:
    """Serializable result of one batch optimization and its recommended candidate."""

    run_id: str
    success: bool
    candidates: list[CandidateParameters] = field(default_factory=list)
    recommended_candidate_id: str | None = None
    evaluations: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    artifact_paths: list[str] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Optimization candidate IDs must be unique")
        if self.success:
            if not self.candidates:
                raise ValueError("A successful optimization batch requires candidates")
            if self.recommended_candidate_id not in candidate_ids:
                raise ValueError("The recommended candidate must exist in the batch")
        elif not self.error:
            raise ValueError("A failed optimization batch requires an error")

    def recommended_candidate(self) -> CandidateParameters:
        if not self.success or self.recommended_candidate_id is None:
            raise ValueError("No recommended candidate is available")
        return next(
            candidate
            for candidate in self.candidates
            if candidate.candidate_id == self.recommended_candidate_id
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
