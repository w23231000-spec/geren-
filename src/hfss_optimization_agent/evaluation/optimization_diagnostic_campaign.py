"""Harness-controlled baseline-versus-optimized real-HFSS diagnostic campaign."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any

from ..domain.canonical_json import canonical_dumps, canonical_loads
from ..domain.contracts import (
    CalibrationArtifactReceipt,
    DesignGoal,
    FrozenMap,
    RunManifestV2,
    STATE_SCHEMA_VERSION,
)
from ..harness.artifacts import ArtifactStore
from ..harness.core import HarnessCore, HarnessSettings
from ..harness.errors import HFSSExecutionError, WorkflowError
from ..harness.optimization_diagnostic_safety import (
    OPTIMIZATION_DIAGNOSTIC_WORKFLOW_ID,
    OptimizationDiagnosticAuthorization,
)
from ..harness.reconciliation import RECONCILIATION_APPROVAL_SCOPE
from ..harness.result_codecs import (
    candidate_from_dict,
    hfss_result_from_dict,
    sparameter_result_from_dict,
)
from ..harness.run_store import ApprovalGrant, OperationRequest, RunStore
from ..hfss.pyaedt_composition import compose_pyaedt_hfss
from ..sparameters.supplied_adapter import (
    SuppliedSurrogateAdapter,
    SuppliedSurrogateConfig,
)


@dataclass(frozen=True, slots=True)
class OptimizationDiagnosticCampaignResult:
    physical_improvement_observed: bool
    evidence: FrozenMap
    evidence_path: Path
    evidence_sha256: str
    task_id: str
    run_id: str


def _provider_native_files(value: object) -> tuple[Path, ...]:
    raw_paths = list(getattr(value, "artifact_paths", ()) or ())
    project_path = getattr(value, "project_path", None)
    if project_path:
        raw_paths.append(project_path)
    suffixes = {".aedt", ".s1p", ".s2p", ".s3p", ".s4p", ".json", ".log", ".txt"}
    selected: set[Path] = set()
    for raw in raw_paths:
        if not isinstance(raw, str) or "://" in raw:
            continue
        path = Path(raw)
        if path.is_file():
            selected.add(path.resolve())
        elif path.is_dir():
            discovered = [
                child.resolve()
                for child in path.rglob("*")
                if child.is_file() and child.suffix.lower() in suffixes
            ]
            if len(discovered) > 256:
                raise WorkflowError(
                    "optimization diagnostic native artifact set exceeds 256 files"
                )
            selected.update(discovered)
        else:
            raise WorkflowError(
                f"optimization diagnostic provider artifact is missing: {raw}"
            )
    return tuple(sorted(selected, key=lambda item: str(item).casefold()))


def _receipt(
    *,
    role: str,
    case_id: str,
    candidate_id: str,
    task_id: str,
    receipt,
) -> CalibrationArtifactReceipt:
    return CalibrationArtifactReceipt(
        artifact_id=receipt.artifact_id,
        case_id=case_id,
        candidate_id=candidate_id,
        role=role,
        uri=f"{task_id}/{receipt.relative_uri}",
        sha256=receipt.sha256,
        size_bytes=receipt.size_bytes,
    )


def _request(
    harness: HarnessCore,
    authorization: OptimizationDiagnosticAuthorization,
    *,
    kind: str,
    subject_id: str,
    key: str,
    payload: Any,
    result_role: str,
    real_hfss: bool = False,
) -> OperationRequest:
    manifest = authorization.manifest
    return OperationRequest(
        run_id=manifest.run_id,
        kind=kind,
        subject_id=subject_id,
        idempotency_key=key,
        payload={
            "request": payload,
            "diagnostic_manifest_sha256": manifest.digest,
            "provider_fingerprints": manifest.provider_fingerprints,
        },
        result_role=result_role,
        estimated_cost=harness.cost_for(kind),
        approval_scope="real_hfss" if real_hfss else None,
        approval_id=manifest.approval_id if real_hfss else None,
        ambiguity_on_exception=real_hfss,
    )


def _s11(response) -> tuple[list[float], list[complex]]:
    if response is None:
        raise WorkflowError("optimization diagnostic response is unavailable")
    values = [
        complex(real[0][0], imag[0][0])
        for real, imag in zip(response.real, response.imag)
    ]
    return [float(value) for value in response.frequency_hz], values


def _band_mean(frequency: list[float], values: list[float]) -> float:
    width = frequency[-1] - frequency[0]
    if width <= 0.0:
        raise WorkflowError("optimization diagnostic frequency grid is invalid")
    area = sum(
        0.5 * (left_value + right_value) * (right_frequency - left_frequency)
        for left_frequency, right_frequency, left_value, right_value in zip(
            frequency,
            frequency[1:],
            values,
            values[1:],
        )
    )
    return area / width


def _single_metrics(response) -> dict[str, float]:
    frequency, values = _s11(response)
    magnitudes = [abs(value) for value in values]
    worst = max(magnitudes)
    return {
        "worst_s11_magnitude": worst,
        "worst_s11_db": 20.0 * math.log10(max(worst, 1e-300)),
        "minimum_s11_return_loss_db": -20.0 * math.log10(max(worst, 1e-300)),
        "mean_reflected_power": _band_mean(
            frequency, [magnitude**2 for magnitude in magnitudes]
        ),
    }


def _comparison_metrics(baseline_response, candidate_response) -> dict[str, Any]:
    baseline_frequency, baseline_values = _s11(baseline_response)
    candidate_frequency, candidate_values = _s11(candidate_response)
    if len(baseline_frequency) != len(candidate_frequency) or any(
        abs(left - right) > 1.0
        for left, right in zip(baseline_frequency, candidate_frequency)
    ):
        raise WorkflowError(
            "optimization diagnostic baseline/candidate frequency grids differ"
        )
    baseline = _single_metrics(baseline_response)
    candidate = _single_metrics(candidate_response)
    phase_differences = [
        math.degrees(__import__("cmath").phase(current * reference.conjugate()))
        for reference, current in zip(baseline_values, candidate_values)
    ]
    weights = [abs(value) ** 2 for value in baseline_values]
    phase_numerator = _band_mean(
        baseline_frequency,
        [weight * difference**2 for weight, difference in zip(weights, phase_differences)],
    )
    phase_denominator = _band_mean(baseline_frequency, weights)
    worst_improved = (
        candidate["worst_s11_magnitude"] < baseline["worst_s11_magnitude"]
    )
    mean_power_improved = (
        candidate["mean_reflected_power"] < baseline["mean_reflected_power"]
    )
    return {
        "baseline": baseline,
        "candidate": candidate,
        "worst_s11_improvement_db": 20.0
        * math.log10(
            baseline["worst_s11_magnitude"]
            / max(candidate["worst_s11_magnitude"], 1e-300)
        ),
        "mean_power_reduction_percent": 100.0
        * (
            baseline["mean_reflected_power"]
            - candidate["mean_reflected_power"]
        )
        / baseline["mean_reflected_power"],
        "phase_weighted_rms_deg": math.sqrt(
            phase_numerator / max(phase_denominator, 1e-300)
        ),
        "worse_frequency_fraction": sum(
            abs(current) > abs(reference)
            for reference, current in zip(baseline_values, candidate_values)
        )
        / len(baseline_values),
        "primary_worst_s11_improved": worst_improved,
        "secondary_mean_power_improved": mean_power_improved,
    }


def run_optimization_diagnostic_campaign(
    authorization: OptimizationDiagnosticAuthorization,
    *,
    optimizer_source_root: Path,
    builder_source_root: Path,
    pyaedt_python: Path,
    artifact_root: Path,
    solve_timeout_seconds: float = 7200.0,
    non_graphical: bool = True,
) -> OptimizationDiagnosticCampaignResult:
    """Execute exactly baseline plus one frozen optimized physical solve."""

    authority = authorization.manifest
    artifact_root = Path(artifact_root).resolve()
    candidates = tuple(snapshot.to_candidate() for snapshot in authority.candidates)
    context_id = authority.candidates[0].context_id
    run_manifest = RunManifestV2(
        schema_version=STATE_SCHEMA_VERSION,
        run_id=authority.run_id,
        task_id=authority.task_id,
        workflow_id=OPTIMIZATION_DIAGNOSTIC_WORKFLOW_ID,
        created_at=authority.created_at,
        design_goal=DesignGoal(
            goal_id=f"goal:{authority.campaign_id}",
            evaluation_contract_id="optimization-outcome-hfss-ab/1.0",
            comparison_context_id=context_id,
            objective="compare_frozen_optimizer_recommendation_against_baseline_in_hfss",
            target_specification=FrozenMap.from_mapping(
                {
                    "primary_metric": "worst_s11_magnitude",
                    "primary_direction": "min",
                    "secondary_metric": "mean_reflected_power",
                    "secondary_direction": "min",
                    "formal_canary_authorized": False,
                }
            ),
        ),
        baseline_candidate_id="baseline",
        code_revision=authorization.repository.git_head,
        provider_fingerprints=authority.provider_fingerprints,
        config_fingerprints=FrozenMap.from_mapping(
            {
                "real_hfss_authorization_id": authority.approval_id,
                "diagnostic_manifest_sha256": authority.digest,
                "hfss_contract_id": authority.hfss_contract_id,
                "hfss_contract_sha256": authority.hfss_contract_sha256,
                "model_alignment_sha256": authority.model_alignment_sha256,
                "optimization_summary_sha256": authority.optimization_summary_sha256,
                "diagnostic_plan_sha256": authority.diagnostic_plan_sha256,
                "formal_canary_authorized": False,
            }
        ),
        real_execution=True,
    )
    artifacts = ArtifactStore(artifact_root, authority.task_id)
    store = RunStore(artifact_root / ".runstore" / "runstore.sqlite3")
    harness = HarnessCore(
        store=store,
        artifacts=artifacts,
        settings=HarnessSettings(
            budget_limit=202,
            operation_costs={"artifact": 0, "sparameters": 1, "hfss": 100},
            required_approval_scopes={"hfss": "real_hfss"},
            execution_policy=authority.execution_policy,
            approvals=(
                ApprovalGrant(
                    approval_id=authority.approval_id,
                    scope="real_hfss",
                    granted_by=f"optimization_diagnostic_manifest:{authority.campaign_id}",
                    expires_at=authority.expires_at,
                ),
                ApprovalGrant(
                    approval_id=f"reconcile:{authority.campaign_id}",
                    scope=RECONCILIATION_APPROVAL_SCOPE,
                    granted_by=f"optimization_diagnostic_manifest:{authority.campaign_id}",
                    expires_at=authority.expires_at,
                ),
            ),
        ),
    )
    harness.ensure_run(run_manifest)
    frequency_grid = tuple(
        authorization.contract.sweep.start_hz
        + index
        * (
            authorization.contract.sweep.stop_hz
            - authorization.contract.sweep.start_hz
        )
        / (authorization.contract.sweep.points - 1)
        for index in range(authorization.contract.sweep.points)
    )
    surrogate = SuppliedSurrogateAdapter(
        SuppliedSurrogateConfig(
            source_root=Path(optimizer_source_root).resolve(),
            frequencies_hz=frequency_grid,
            reference_impedance_ohm=authorization.contract.reference_impedance_ohm,
            comparison_context_id=context_id,
            port_order=authorization.contract.port_order,
        )
    )
    hfss = compose_pyaedt_hfss(
        contract=authorization.contract,
        pyaedt_python=Path(pyaedt_python),
        builder_source_root=Path(builder_source_root),
        artifact_root=artifact_root,
        task_id=authority.task_id,
        solve_timeout_seconds=solve_timeout_seconds,
        non_graphical=non_graphical,
    )

    results: dict[str, dict[str, Any]] = {}
    evidence_receipts: list[CalibrationArtifactReceipt] = []
    with harness.run_invocation(authority.run_id) as claim:
        for candidate in candidates:
            candidate_execution = harness.execute(
                _request(
                    harness,
                    authorization,
                    kind="artifact",
                    subject_id=candidate.candidate_id,
                    key=f"optimization-diagnostic:candidate:{candidate.candidate_id}",
                    payload=candidate,
                    result_role="candidate_parameters",
                ),
                lambda candidate=candidate: candidate,
                decoder=candidate_from_dict,
            )
            surrogate_execution = harness.execute(
                _request(
                    harness,
                    authorization,
                    kind="sparameters",
                    subject_id=candidate.candidate_id,
                    key=f"optimization-diagnostic:surrogate:{candidate.candidate_id}",
                    payload=candidate,
                    result_role="surrogate_result",
                ),
                lambda candidate=candidate: surrogate.run(candidate),
                decoder=sparameter_result_from_dict,
            )

            def run_hfss(candidate=candidate):
                result = hfss.run(candidate)
                if not result.success:
                    raise HFSSExecutionError(
                        "optimization diagnostic HFSS physical outcome is not confirmed: "
                        f"{result.error}"
                    )
                return result

            hfss_execution = harness.execute(
                _request(
                    harness,
                    authorization,
                    kind="hfss",
                    subject_id=candidate.candidate_id,
                    key=f"optimization-diagnostic:hfss:{candidate.candidate_id}",
                    payload=candidate,
                    result_role="hfss_result",
                    real_hfss=True,
                ),
                run_hfss,
                decoder=hfss_result_from_dict,
                native_artifact_paths=_provider_native_files,
            )
            results[candidate.candidate_id] = {
                "candidate": candidate_execution.value,
                "surrogate": surrogate_execution.value,
                "hfss": hfss_execution.value,
            }
            for role, receipt in (
                ("candidate_parameters", candidate_execution.artifact),
                ("surrogate_result", surrogate_execution.artifact),
                ("hfss_result", hfss_execution.artifact),
            ):
                evidence_receipts.append(
                    _receipt(
                        role=role,
                        case_id=candidate.candidate_id,
                        candidate_id=candidate.candidate_id,
                        task_id=authority.task_id,
                        receipt=receipt,
                    )
                )
            project = [
                receipt
                for receipt in hfss_execution.supporting_artifacts
                if Path(receipt.relative_uri).suffix.lower() == ".aedt"
            ]
            touchstone = [
                receipt
                for receipt in hfss_execution.supporting_artifacts
                if Path(receipt.relative_uri).suffix.lower() == ".s2p"
            ]
            if len(project) != 1 or len(touchstone) != 1:
                raise WorkflowError(
                    "optimization diagnostic requires exactly one .aedt and one .s2p per case"
                )
            for role, receipt in (
                ("hfss_project", project[0]),
                ("hfss_touchstone", touchstone[0]),
            ):
                evidence_receipts.append(
                    _receipt(
                        role=role,
                        case_id=candidate.candidate_id,
                        candidate_id=candidate.candidate_id,
                        task_id=authority.task_id,
                        receipt=receipt,
                    )
                )

        baseline_id = candidates[0].candidate_id
        candidate_id = candidates[1].candidate_id
        surrogate_report = _comparison_metrics(
            results[baseline_id]["surrogate"].response,
            results[candidate_id]["surrogate"].response,
        )
        hfss_report = _comparison_metrics(
            results[baseline_id]["hfss"].complex_response,
            results[candidate_id]["hfss"].complex_response,
        )
        physical_improvement_observed = bool(
            hfss_report["primary_worst_s11_improved"]
        )
        evidence_payload = {
            "schema_version": "optimization-diagnostic-evidence/1.0",
            "evidence_id": f"optimization-diagnostic:{authority.campaign_id}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "campaign_manifest_sha256": authority.digest,
            "optimization_summary_sha256": authority.optimization_summary_sha256,
            "hfss_contract_sha256": authority.hfss_contract_sha256,
            "comparison_context_id": context_id,
            "baseline_candidate_id": baseline_id,
            "optimized_candidate_id": candidate_id,
            "formal_canary_authorized": False,
            "physical_improvement_observed": physical_improvement_observed,
            "surrogate_prediction": surrogate_report,
            "hfss_observation": hfss_report,
            "direction_agreement": bool(
                surrogate_report["primary_worst_s11_improved"]
                == hfss_report["primary_worst_s11_improved"]
            ),
            "provider_fingerprints": authority.provider_fingerprints.to_dict(),
            "source_artifacts": [
                canonical_loads(canonical_dumps(receipt))
                for receipt in evidence_receipts
            ],
        }
        evidence = FrozenMap.from_mapping(evidence_payload)
        evidence_execution = harness.execute(
            _request(
                harness,
                authorization,
                kind="artifact",
                subject_id="optimization_diagnostic_evidence",
                key="optimization-diagnostic:evidence",
                payload={
                    "campaign_manifest_sha256": authority.digest,
                    "source_artifact_count": len(evidence_receipts),
                },
                result_role="diagnostic_evidence",
            ),
            lambda: evidence,
            decoder=FrozenMap.from_dict,
        )
        evidence_path = artifacts.verify(evidence_execution.artifact)
        terminal_status = (
            "PHYSICAL_IMPROVEMENT_OBSERVED"
            if physical_improvement_observed
            else "PHYSICAL_IMPROVEMENT_NOT_OBSERVED"
        )
        store.save_checkpoint(
            authority.run_id,
            canonical_dumps(
                {
                    "manifest": canonical_loads(canonical_dumps(run_manifest)),
                    "status": terminal_status,
                    "optimization_diagnostic_evidence": evidence.to_dict(),
                    "evidence_artifact_id": evidence_execution.artifact.artifact_id,
                }
            ),
            complete=True,
            terminal_status=terminal_status,
            run_owner_token=harness.owner_token,
            run_fence=claim.fence,
        )
    return OptimizationDiagnosticCampaignResult(
        physical_improvement_observed,
        evidence,
        evidence_path,
        evidence_execution.artifact.sha256,
        authority.task_id,
        authority.run_id,
    )
