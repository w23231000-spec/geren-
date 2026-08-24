"""Harness-controlled three-case surrogate/HFSS Calibration campaign."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.canonical_json import canonical_dumps, canonical_loads
from ..domain.contracts import (
    CalibrationArtifactReceipt,
    CalibrationEvidence,
    DesignGoal,
    FrozenMap,
    RunManifestV2,
    STATE_SCHEMA_VERSION,
)
from ..harness.artifacts import ArtifactStore
from ..harness.calibration_safety import (
    CALIBRATION_COLLECTION_WORKFLOW_ID,
    CalibrationCollectionAuthorization,
)
from ..harness.core import HarnessCore, HarnessSettings
from ..harness.errors import HFSSExecutionError, WorkflowError
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
from .calibration import CalibrationCase, assess_calibration, create_calibration_evidence


@dataclass(frozen=True, slots=True)
class CalibrationCampaignResult:
    passed: bool
    evidence: CalibrationEvidence
    evidence_path: Path
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
                raise WorkflowError("Calibration native artifact set exceeds 256 files")
            selected.update(discovered)
        else:
            raise WorkflowError(f"Calibration provider artifact is missing: {raw}")
    return tuple(sorted(selected, key=lambda item: str(item).casefold()))


def _calibration_receipt(
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
    authorization: CalibrationCollectionAuthorization,
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
            "campaign_manifest_sha256": manifest.digest,
            "provider_fingerprints": manifest.provider_fingerprints,
        },
        result_role=result_role,
        estimated_cost=harness.cost_for(kind),
        approval_scope="real_hfss" if real_hfss else None,
        approval_id=manifest.approval_id if real_hfss else None,
        ambiguity_on_exception=real_hfss,
    )


def run_calibration_campaign(
    authorization: CalibrationCollectionAuthorization,
    *,
    optimizer_source_root: Path,
    builder_source_root: Path,
    pyaedt_python: Path,
    artifact_root: Path,
    solve_timeout_seconds: float = 7200.0,
    non_graphical: bool = True,
) -> CalibrationCampaignResult:
    """Execute exactly three receipt-safe physical solves and freeze evidence."""

    authority = authorization.manifest
    artifact_root = Path(artifact_root).resolve()
    candidates = tuple(snapshot.to_candidate() for snapshot in authority.candidates)
    context_id = authority.candidates[0].context_id
    config_fingerprints = {
        "real_hfss_authorization_id": authority.approval_id,
        "readiness_id": authority.campaign_id,
        "hfss_contract_id": authority.hfss_contract_id,
        "hfss_contract_sha256": authority.hfss_contract_sha256,
        "model_alignment_sha256": authority.model_alignment_sha256,
        "calibration_policy_sha256": authority.calibration_policy_sha256,
        "calibration_plan_sha256": authority.calibration_plan_sha256,
        "calibration_collection_manifest_sha256": authority.digest,
    }
    run_manifest = RunManifestV2(
        schema_version=STATE_SCHEMA_VERSION,
        run_id=authority.run_id,
        task_id=authority.task_id,
        workflow_id=CALIBRATION_COLLECTION_WORKFLOW_ID,
        created_at=authority.created_at,
        design_goal=DesignGoal(
            goal_id=f"goal:{authority.campaign_id}",
            evaluation_contract_id="paired-surrogate-hfss/1.0",
            comparison_context_id=context_id,
            objective="collect_three_case_physical_calibration",
            target_specification=FrozenMap.from_mapping(authorization.policy.to_dict()),
        ),
        baseline_candidate_id="baseline",
        code_revision=authorization.repository.git_head,
        provider_fingerprints=authority.provider_fingerprints,
        config_fingerprints=FrozenMap.from_mapping(config_fingerprints),
        real_execution=True,
    )
    artifacts = ArtifactStore(artifact_root, authority.task_id)
    store = RunStore(artifact_root / ".runstore" / "runstore.sqlite3")
    harness = HarnessCore(
        store=store,
        artifacts=artifacts,
        settings=HarnessSettings(
            budget_limit=303,
            operation_costs={"artifact": 0, "sparameters": 1, "hfss": 100},
            required_approval_scopes={"hfss": "real_hfss"},
            execution_policy=authority.execution_policy,
            approvals=(
                ApprovalGrant(
                    approval_id=authority.approval_id,
                    scope="real_hfss",
                    granted_by=f"calibration_manifest:{authority.campaign_id}",
                    expires_at=authority.expires_at,
                ),
            ),
        ),
    )
    harness.ensure_run(run_manifest)
    surrogate = SuppliedSurrogateAdapter(
        SuppliedSurrogateConfig(
            source_root=Path(optimizer_source_root).resolve(),
            frequencies_hz=tuple(
                float(item)
                for item in (
                    authorization.contract.sweep.start_hz
                    + index
                    * (
                        authorization.contract.sweep.stop_hz
                        - authorization.contract.sweep.start_hz
                    )
                    / (authorization.contract.sweep.points - 1)
                    for index in range(authorization.contract.sweep.points)
                )
            ),
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

    calibration_cases: list[CalibrationCase] = []
    evidence_receipts: list[CalibrationArtifactReceipt] = []
    with harness.run_invocation(authority.run_id) as claim:
        for candidate in candidates:
            candidate_execution = harness.execute(
                _request(
                    harness,
                    authorization,
                    kind="artifact",
                    subject_id=candidate.candidate_id,
                    key=f"calibration:candidate:{candidate.candidate_id}",
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
                    key=f"calibration:surrogate:{candidate.candidate_id}",
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
                        f"Calibration HFSS physical outcome is not confirmed: {result.error}"
                    )
                return result

            hfss_execution = harness.execute(
                _request(
                    harness,
                    authorization,
                    kind="hfss",
                    subject_id=candidate.candidate_id,
                    key=f"calibration:hfss:{candidate.candidate_id}",
                    payload=candidate,
                    result_role="hfss_result",
                    real_hfss=True,
                ),
                run_hfss,
                decoder=hfss_result_from_dict,
                native_artifact_paths=_provider_native_files,
            )
            calibration_cases.append(
                CalibrationCase(
                    candidate.candidate_id,
                    candidate_execution.value,
                    surrogate_execution.value,
                    hfss_execution.value,
                )
            )
            for role, receipt in (
                ("candidate_parameters", candidate_execution.artifact),
                ("surrogate_result", surrogate_execution.artifact),
                ("hfss_result", hfss_execution.artifact),
            ):
                evidence_receipts.append(
                    _calibration_receipt(
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
                    "Calibration HFSS evidence requires exactly one .aedt and one .s2p"
                )
            for role, receipt in (
                ("hfss_project", project[0]),
                ("hfss_touchstone", touchstone[0]),
            ):
                evidence_receipts.append(
                    _calibration_receipt(
                        role=role,
                        case_id=candidate.candidate_id,
                        candidate_id=candidate.candidate_id,
                        task_id=authority.task_id,
                        receipt=receipt,
                    )
                )

        report = assess_calibration(calibration_cases, authorization.policy)
        calibration_providers = {
            name: authority.provider_fingerprints.to_dict()[name]
            for name in (
                "supplied_surrogate_source_sha256",
                "hfss_builder_source_sha256",
                "pyaedt_executable_sha256",
                "hfss_worker_protocol",
            )
        }
        evidence = create_calibration_evidence(
            report,
            authorization.policy,
            evidence_id=f"calibration:{authority.campaign_id}",
            provider_fingerprints=calibration_providers,
            hfss_contract_sha256=authority.hfss_contract_sha256,
            source_artifacts=tuple(evidence_receipts),
        )
        evidence_execution = harness.execute(
            _request(
                harness,
                authorization,
                kind="artifact",
                subject_id="calibration_evidence",
                key="calibration:evidence",
                payload={"source_artifact_manifest_sha256": evidence.source_artifact_manifest_sha256},
                result_role="calibration_evidence",
            ),
            lambda: evidence,
            decoder=CalibrationEvidence.from_dict,
        )
        evidence_path = artifacts.verify(evidence_execution.artifact)
        terminal_status = "CALIBRATION_PASSED" if evidence.passed else "CALIBRATION_FAILED"
        store.save_checkpoint(
            authority.run_id,
            canonical_dumps(
                {
                    "manifest": canonical_loads(canonical_dumps(run_manifest)),
                    "status": terminal_status,
                    "calibration_evidence": canonical_loads(canonical_dumps(evidence)),
                    "evidence_artifact_id": evidence_execution.artifact.artifact_id,
                }
            ),
            complete=True,
            terminal_status=terminal_status,
            run_owner_token=harness.owner_token,
            run_fence=claim.fence,
        )
    return CalibrationCampaignResult(
        evidence.passed,
        evidence,
        evidence_path,
        authority.task_id,
        authority.run_id,
    )
