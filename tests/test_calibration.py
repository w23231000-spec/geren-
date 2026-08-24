"""Paired-model compatibility and error assessment tests."""

import hashlib

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
    create_calibration_evidence,
)
from hfss_optimization_agent.domain.canonical_json import canonical_dumps, canonical_loads
from hfss_optimization_agent.domain.contracts import (
    CALIBRATION_ARTIFACT_ROLES,
    CALIBRATION_PROVIDER_FINGERPRINTS,
    CalibrationArtifactReceipt,
    CalibrationEvidence,
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


def calibration_cases():
    return [
        case("a", 0.10, 0.11),
        case("b", 0.20, 0.21),
        case("c", 0.30, 0.31),
    ]


def provider_fingerprints():
    providers = {
        name: (str(index) * 64)
        for index, name in enumerate(CALIBRATION_PROVIDER_FINGERPRINTS, start=1)
    }
    providers["hfss_worker_protocol"] = "hfss-composite-request/1.0"
    return providers


def source_artifacts(case_ids=("a", "b", "c")):
    artifacts = []
    for case_id in case_ids:
        for role in sorted(CALIBRATION_ARTIFACT_ROLES):
            payload = f"{case_id}:{role}".encode()
            artifacts.append(
                CalibrationArtifactReceipt(
                    artifact_id=f"{case_id}:{role}",
                    case_id=case_id,
                    candidate_id=case_id,
                    role=role,
                    uri=f"calibration/{case_id}/{role}.bin",
                    sha256=hashlib.sha256(payload).hexdigest(),
                    size_bytes=len(payload),
                )
            )
    return tuple(artifacts)


def test_calibration_report_accepts_small_error_and_matching_rank():
    report = assess_calibration(
        calibration_cases(),
        CalibrationPolicy(0.02, 1.0, minimum_pairwise_ranking_agreement=1.0),
    )
    assert report.passed is True
    assert report.pairwise_ranking_agreement == 1.0
    assert report.comparison_context_id == "aligned-v1"


def test_calibration_report_rejects_reversed_candidate_ranking():
    report = assess_calibration(
        [case("a", 0.10, 0.30), case("b", 0.20, 0.20), case("c", 0.30, 0.10)],
        CalibrationPolicy(1.0, 20.0, minimum_pairwise_ranking_agreement=1.0),
    )
    assert report.passed is False
    assert report.pairwise_ranking_agreement == 0.0
    assert "pairwise_ranking_agreement_below_threshold" in report.reasons


def test_calibration_refuses_different_comparison_contexts():
    mismatched = case("a", 0.1, 0.1)
    mismatched.hfss.execution_metadata["comparison_context_id"] = "different"
    with pytest.raises(CalibrationError, match="context IDs differ"):
        assess_calibration(
            [mismatched, case("b", 0.2, 0.2), case("c", 0.3, 0.3)],
            CalibrationPolicy(1.0, 20.0),
        )


def test_calibration_refuses_frequency_grid_mismatch():
    mismatched = case("a", 0.1, 0.1)
    mismatched.hfss.complex_response.frequency_hz[1] = 2.1e9
    with pytest.raises(CalibrationError, match="frequency grids differ"):
        assess_calibration(
            [mismatched, case("b", 0.2, 0.2), case("c", 0.3, 0.3)],
            CalibrationPolicy(1.0, 20.0),
        )


def test_calibration_refuses_one_case_and_vacuous_ranking():
    with pytest.raises(CalibrationError, match="At least 3"):
        assess_calibration([case("a", 0.1, 0.1)], CalibrationPolicy(1.0, 20.0))


def test_calibration_evidence_is_strict_canonical_and_digest_stable():
    policy = CalibrationPolicy(0.02, 1.0, minimum_pairwise_ranking_agreement=1.0)
    report = assess_calibration(calibration_cases(), policy)
    evidence = create_calibration_evidence(
        report,
        policy,
        evidence_id="calibration:aligned-v1",
        provider_fingerprints=provider_fingerprints(),
        hfss_contract_sha256="f" * 64,
        source_artifacts=source_artifacts(),
        created_at="2026-08-21T00:00:00+00:00",
    )

    restored = CalibrationEvidence.from_dict(canonical_loads(canonical_dumps(evidence)))
    assert restored == evidence
    assert restored.digest == evidence.digest
    assert restored.case_ids == ("a", "b", "c")

    unknown = canonical_loads(canonical_dumps(evidence))
    unknown["unexpected"] = True
    with pytest.raises(ValueError, match="unexpected"):
        CalibrationEvidence.from_dict(unknown)


def test_calibration_evidence_refuses_report_identity_drift():
    policy = CalibrationPolicy(1.0, 20.0)
    report = assess_calibration(calibration_cases(), policy)
    evidence = create_calibration_evidence(
        report,
        policy,
        evidence_id="calibration:one",
        provider_fingerprints=provider_fingerprints(),
        hfss_contract_sha256="f" * 64,
        source_artifacts=source_artifacts(),
    )
    payload = canonical_loads(canonical_dumps(evidence))
    payload["comparison_context_id"] = "drifted"
    with pytest.raises(ValueError, match="report/context"):
        CalibrationEvidence.from_dict(payload)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["provider_fingerprints"].pop(
                "hfss_builder_source_sha256"
            ),
            "complete causal",
        ),
        (lambda payload: payload.update(source_artifacts=[]), "artifact roles"),
        (
            lambda payload: payload["policy"].update(max_complex_rmse=0.5),
            "policy SHA-256",
        ),
        (
            lambda payload: payload["report"].update(mean_complex_rmse=0.5),
            "not recomputed",
        ),
    ],
)
def test_calibration_evidence_rejects_formal_bypass(mutates_evidence, mutate, message):
    payload = canonical_loads(canonical_dumps(mutates_evidence))
    mutate(payload)
    with pytest.raises(ValueError, match=message):
        CalibrationEvidence.from_dict(payload)


@pytest.fixture
def mutates_evidence():
    policy = CalibrationPolicy(0.02, 1.0)
    report = assess_calibration(calibration_cases(), policy)
    return create_calibration_evidence(
        report,
        policy,
        evidence_id="calibration:bypass-regression",
        provider_fingerprints=provider_fingerprints(),
        hfss_contract_sha256="f" * 64,
        source_artifacts=source_artifacts(),
    )
