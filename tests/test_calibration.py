"""Paired-model compatibility and error assessment tests."""

import pytest

from hfss_optimization_agent.core.models import (
    CandidateParameters,
    ComplexSParameters,
    HFSSResult,
    SParameterResult,
)
from hfss_optimization_agent.evaluation.calibration import (
    CalibrationCase,
    CalibrationPolicy,
    assess_calibration,
)
from hfss_optimization_agent.harness.errors import CalibrationError


def response(s11: float, s21: float) -> ComplexSParameters:
    return ComplexSParameters.from_complex_matrices(
        frequency_hz=[1e9, 2e9],
        matrices=[
            [[complex(s11, 0), complex(s21, 0)], [complex(s21, 0), complex(s11, 0)]],
            [[complex(s11 * 0.9, 0), complex(s21, 0)], [complex(s21, 0), complex(s11 * 0.9, 0)]],
        ],
        port_order=("input", "output"),
    )


def case(case_id: str, surrogate_s11: float, hfss_s11: float, *, context="aligned-v1"):
    candidate = CandidateParameters(case_id, 1, {"p1": 1.0})
    surrogate = SParameterResult(
        case_id,
        True,
        response(surrogate_s11, 0.8),
        metadata={"comparison_context_id": context},
    )
    hfss = HFSSResult(
        case_id,
        True,
        complex_response=response(hfss_s11, 0.8),
        execution_metadata={"comparison_context_id": context},
    )
    return CalibrationCase(case_id, candidate, surrogate, hfss)


def test_calibration_report_accepts_small_error_and_matching_rank():
    report = assess_calibration(
        [case("a", 0.10, 0.11), case("b", 0.20, 0.21)],
        CalibrationPolicy(0.02, 1.0, minimum_pairwise_ranking_agreement=1.0),
    )
    assert report.passed is True
    assert report.pairwise_ranking_agreement == 1.0
    assert report.comparison_context_id == "aligned-v1"


def test_calibration_report_rejects_reversed_candidate_ranking():
    report = assess_calibration(
        [case("a", 0.10, 0.30), case("b", 0.20, 0.10)],
        CalibrationPolicy(1.0, 20.0, minimum_pairwise_ranking_agreement=1.0),
    )
    assert report.passed is False
    assert report.pairwise_ranking_agreement == 0.0
    assert "pairwise_ranking_agreement_below_threshold" in report.reasons


def test_calibration_refuses_different_comparison_contexts():
    mismatched = case("a", 0.1, 0.1)
    mismatched.hfss.execution_metadata["comparison_context_id"] = "different"
    with pytest.raises(CalibrationError, match="context IDs differ"):
        assess_calibration([mismatched], CalibrationPolicy(1.0, 20.0))


def test_calibration_refuses_frequency_grid_mismatch():
    mismatched = case("a", 0.1, 0.1)
    mismatched.hfss.complex_response.frequency_hz[1] = 2.1e9
    with pytest.raises(CalibrationError, match="frequency grids differ"):
        assess_calibration([mismatched], CalibrationPolicy(1.0, 20.0))
