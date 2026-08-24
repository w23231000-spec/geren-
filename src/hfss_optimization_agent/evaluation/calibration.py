"""Deterministic paired surrogate-versus-HFSS compatibility and error assessment."""

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Mapping

from ..core.models import CandidateParameters, HFSSResult, SParameterResult
from ..harness.errors import CalibrationError
from ..domain.contracts import (
    CALIBRATION_EVIDENCE_SCHEMA_VERSION,
    CalibrationEvidence,
    FrozenMap,
)


CALIBRATION_POLICY_VERSION = "paired-surrogate-hfss/1.0"


@dataclass(frozen=True, slots=True)
class CalibrationPolicy:
    max_complex_rmse: float
    max_magnitude_db_rmse: float
    minimum_pairwise_ranking_agreement: float = 0.8
    frequency_tolerance_hz: float = 1.0
    impedance_tolerance_ohm: float = 1e-9
    require_comparison_context_id: bool = True

    def __post_init__(self) -> None:
        if self.max_complex_rmse < 0.0 or self.max_magnitude_db_rmse < 0.0:
            raise ValueError("Calibration error limits cannot be negative")
        if not 0.0 <= self.minimum_pairwise_ranking_agreement <= 1.0:
            raise ValueError("Ranking agreement threshold must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class CalibrationCase:
    case_id: str
    candidate: CandidateParameters
    surrogate: SParameterResult
    hfss: HFSSResult


@dataclass(slots=True)
class CalibrationCaseResult:
    case_id: str
    complex_rmse: float
    magnitude_db_rmse: float
    max_complex_error: float
    surrogate_worst_s11: float
    hfss_worst_s11: float


@dataclass(slots=True)
class CalibrationReport:
    passed: bool
    cases: list[CalibrationCaseResult]
    mean_complex_rmse: float
    mean_magnitude_db_rmse: float
    pairwise_ranking_agreement: float
    comparison_context_id: str | None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _complex_matrices(response) -> list[list[list[complex]]]:
    return [
        [
            [complex(real, imag) for real, imag in zip(real_row, imag_row)]
            for real_row, imag_row in zip(real_matrix, imag_matrix)
        ]
        for real_matrix, imag_matrix in zip(response.real, response.imag)
    ]


def _check_pair(case: CalibrationCase, policy: CalibrationPolicy) -> str | None:
    if not case.surrogate.success or case.surrogate.response is None:
        raise CalibrationError(f"Case {case.case_id}: surrogate result is unavailable")
    if not case.hfss.success or case.hfss.complex_response is None:
        raise CalibrationError(f"Case {case.case_id}: HFSS complex result is unavailable")
    if case.surrogate.candidate_id != case.candidate.candidate_id:
        raise CalibrationError(f"Case {case.case_id}: surrogate candidate identity differs")
    if case.hfss.candidate_id != case.candidate.candidate_id:
        raise CalibrationError(f"Case {case.case_id}: HFSS candidate identity differs")
    surrogate = case.surrogate.response
    hfss = case.hfss.complex_response
    if surrogate.port_order != hfss.port_order:
        raise CalibrationError(f"Case {case.case_id}: port order differs")
    if not math.isclose(
        surrogate.reference_impedance_ohm,
        hfss.reference_impedance_ohm,
        rel_tol=0.0,
        abs_tol=policy.impedance_tolerance_ohm,
    ):
        raise CalibrationError(f"Case {case.case_id}: reference impedance differs")
    if len(surrogate.frequency_hz) != len(hfss.frequency_hz) or any(
        abs(left - right) > policy.frequency_tolerance_hz
        for left, right in zip(surrogate.frequency_hz, hfss.frequency_hz)
    ):
        raise CalibrationError(f"Case {case.case_id}: frequency grids differ")
    surrogate_context = case.surrogate.metadata.get("comparison_context_id")
    hfss_context = case.hfss.execution_metadata.get("comparison_context_id")
    if policy.require_comparison_context_id:
        if not surrogate_context or not hfss_context:
            raise CalibrationError(f"Case {case.case_id}: comparison context ID is missing")
        if surrogate_context != hfss_context:
            raise CalibrationError(f"Case {case.case_id}: comparison context IDs differ")
    return surrogate_context or hfss_context


def _case_result(case: CalibrationCase, policy: CalibrationPolicy) -> tuple[CalibrationCaseResult, str | None]:
    context_id = _check_pair(case, policy)
    surrogate_matrices = _complex_matrices(case.surrogate.response)
    hfss_matrices = _complex_matrices(case.hfss.complex_response)
    squared_complex: list[float] = []
    squared_db: list[float] = []
    absolute_errors: list[float] = []
    for surrogate_matrix, hfss_matrix in zip(surrogate_matrices, hfss_matrices):
        for surrogate_row, hfss_row in zip(surrogate_matrix, hfss_matrix):
            for surrogate_value, hfss_value in zip(surrogate_row, hfss_row):
                error = abs(surrogate_value - hfss_value)
                absolute_errors.append(error)
                squared_complex.append(error**2)
                surrogate_db = 20.0 * math.log10(max(abs(surrogate_value), 1e-300))
                hfss_db = 20.0 * math.log10(max(abs(hfss_value), 1e-300))
                squared_db.append((surrogate_db - hfss_db) ** 2)
    surrogate_worst = max(abs(matrix[0][0]) for matrix in surrogate_matrices)
    hfss_worst = max(abs(matrix[0][0]) for matrix in hfss_matrices)
    return (
        CalibrationCaseResult(
            case_id=case.case_id,
            complex_rmse=math.sqrt(sum(squared_complex) / len(squared_complex)),
            magnitude_db_rmse=math.sqrt(sum(squared_db) / len(squared_db)),
            max_complex_error=max(absolute_errors),
            surrogate_worst_s11=surrogate_worst,
            hfss_worst_s11=hfss_worst,
        ),
        context_id,
    )


def _ranking_agreement(results: list[CalibrationCaseResult]) -> float:
    agreements = 0
    comparable = 0
    for left_index, left in enumerate(results):
        for right in results[left_index + 1 :]:
            surrogate_delta = left.surrogate_worst_s11 - right.surrogate_worst_s11
            hfss_delta = left.hfss_worst_s11 - right.hfss_worst_s11
            if math.isclose(surrogate_delta, 0.0, abs_tol=1e-15) or math.isclose(
                hfss_delta, 0.0, abs_tol=1e-15
            ):
                continue
            comparable += 1
            agreements += int((surrogate_delta < 0.0) == (hfss_delta < 0.0))
    return 1.0 if comparable == 0 else agreements / comparable


def assess_calibration(
    cases: list[CalibrationCase],
    policy: CalibrationPolicy,
) -> CalibrationReport:
    if not cases:
        raise CalibrationError("At least one paired calibration case is required")
    paired = [_case_result(case, policy) for case in cases]
    results = [item[0] for item in paired]
    context_ids = {item[1] for item in paired if item[1] is not None}
    if len(context_ids) > 1:
        raise CalibrationError("Calibration cases use different comparison context IDs")
    mean_complex = sum(item.complex_rmse for item in results) / len(results)
    mean_db = sum(item.magnitude_db_rmse for item in results) / len(results)
    ranking = _ranking_agreement(results)
    reasons: list[str] = []
    if mean_complex > policy.max_complex_rmse:
        reasons.append("mean_complex_rmse_exceeded")
    if mean_db > policy.max_magnitude_db_rmse:
        reasons.append("mean_magnitude_db_rmse_exceeded")
    if ranking < policy.minimum_pairwise_ranking_agreement:
        reasons.append("pairwise_ranking_agreement_below_threshold")
    return CalibrationReport(
        passed=not reasons,
        cases=results,
        mean_complex_rmse=mean_complex,
        mean_magnitude_db_rmse=mean_db,
        pairwise_ranking_agreement=ranking,
        comparison_context_id=next(iter(context_ids), None),
        reasons=reasons,
    )


def create_calibration_evidence(
    report: CalibrationReport,
    policy: CalibrationPolicy,
    *,
    evidence_id: str,
    provider_fingerprints: Mapping[str, str],
    created_at: str | None = None,
    source_artifact_ids: tuple[str, ...] = (),
) -> CalibrationEvidence:
    """Freeze one assessed report with the exact providers and policy that produced it."""

    if report.comparison_context_id is None:
        raise CalibrationError("Calibration evidence requires a comparison context ID")
    return CalibrationEvidence(
        schema_version=CALIBRATION_EVIDENCE_SCHEMA_VERSION,
        evidence_id=evidence_id,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        policy_version=CALIBRATION_POLICY_VERSION,
        comparison_context_id=report.comparison_context_id,
        passed=report.passed,
        case_ids=tuple(item.case_id for item in report.cases),
        provider_fingerprints=FrozenMap.from_mapping(provider_fingerprints),
        policy=FrozenMap.from_mapping(asdict(policy)),
        report=FrozenMap.from_mapping(report.to_dict()),
        source_artifact_ids=source_artifact_ids,
    )
