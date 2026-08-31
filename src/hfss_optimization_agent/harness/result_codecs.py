"""Strict reconstruction of provider results cached by the Harness ledger."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

from ..core.models import (
    CandidateParameters,
    ComplexSParameters,
    HFSSResult,
    OptimizationBatch,
    SParameterResult,
)
from ..domain.canonical_json import require_exact_fields


def _field_names(cls: type) -> set[str]:
    return {item.name for item in fields(cls)}


def complex_sparameters_from_dict(value: Any) -> ComplexSParameters | None:
    if value is None:
        return None
    data = require_exact_fields(
        value, _field_names(ComplexSParameters), context="ComplexSParameters"
    )
    return ComplexSParameters(
        frequency_hz=list(data["frequency_hz"]),
        real=[[list(row) for row in matrix] for matrix in data["real"]],
        imag=[[list(row) for row in matrix] for matrix in data["imag"]],
        port_order=tuple(data["port_order"]),
        reference_impedance_ohm=data["reference_impedance_ohm"],
    )


def sparameter_result_from_dict(value: Any) -> SParameterResult:
    data = require_exact_fields(
        value, _field_names(SParameterResult), context="SParameterResult"
    )
    return SParameterResult(
        candidate_id=data["candidate_id"],
        success=data["success"],
        response=complex_sparameters_from_dict(data["response"]),
        metrics=dict(data["metrics"]),
        provider=data["provider"],
        model_version=data["model_version"],
        calibration_status=data["calibration_status"],
        artifact_paths=list(data["artifact_paths"]),
        error=data["error"],
        metadata=dict(data["metadata"]),
    )


def hfss_result_from_dict(value: Any) -> HFSSResult:
    data = require_exact_fields(value, _field_names(HFSSResult), context="HFSSResult")
    return HFSSResult(
        candidate_id=data["candidate_id"],
        success=data["success"],
        frequency=list(data["frequency"]),
        s_parameters={key: list(item) for key, item in data["s_parameters"].items()},
        metrics=dict(data["metrics"]),
        project_path=data["project_path"],
        artifact_paths=list(data["artifact_paths"]),
        error=data["error"],
        complex_response=complex_sparameters_from_dict(data["complex_response"]),
        execution_metadata=dict(data["execution_metadata"]),
    )


def candidate_from_dict(value: Any) -> CandidateParameters:
    data = require_exact_fields(
        value, _field_names(CandidateParameters), context="CandidateParameters"
    )
    return CandidateParameters(
        candidate_id=data["candidate_id"],
        iteration=data["iteration"],
        values=dict(data["values"]),
        metadata=dict(data["metadata"]),
    )


def optimization_batch_from_dict(value: Any) -> OptimizationBatch:
    data = require_exact_fields(
        value, _field_names(OptimizationBatch), context="OptimizationBatch"
    )
    return OptimizationBatch(
        run_id=data["run_id"],
        success=data["success"],
        candidates=[candidate_from_dict(item) for item in data["candidates"]],
        recommended_candidate_id=data["recommended_candidate_id"],
        evaluations=data["evaluations"],
        metadata=dict(data["metadata"]),
        artifact_paths=list(data["artifact_paths"]),
        error=data["error"],
    )
