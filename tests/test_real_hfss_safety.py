"""Offline regressions for readiness authority; these never launch a Tool."""

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from hfss_optimization_agent.agent.closed_loop_contracts import production_policy_sha256
from hfss_optimization_agent.core.models import (
    CandidateParameters,
    ComplexSParameters,
    HFSSResult,
    SParameterResult,
)
from hfss_optimization_agent.domain.canonical_json import canonical_dumps, canonical_loads
from hfss_optimization_agent.domain.contracts import (
    CALIBRATION_ARTIFACT_ROLES,
    CALIBRATION_EVIDENCE_SCHEMA_VERSION,
    CALIBRATION_POLICY_VERSION,
    CalibrationArtifactReceipt,
    CalibrationEvidence,
    FrozenMap,
    calibration_policy_sha256,
)
from hfss_optimization_agent.evaluation.calibration import (
    CalibrationCase,
    CalibrationPolicy,
    assess_calibration,
    create_calibration_evidence,
)
from hfss_optimization_agent.evaluation.model_alignment import (
    load_model_alignment_contract,
)
from hfss_optimization_agent.harness.execution_policy import ExecutionPolicy
from hfss_optimization_agent.harness.real_hfss_safety import (
    HFSS_WORKER_PROTOCOL,
    READINESS_SCHEMA_VERSION,
    REAL_HFSS_APPROVAL_SCOPE,
    REAL_HFSS_WORKFLOW_ID,
    RealHFSSReadinessManifestV1,
    RealHFSSSafetyError,
    RepositoryEvidence,
    validate_real_hfss_launch_configuration,
    validate_real_hfss_workflow_binding,
)


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
HEAD = "1" * 40
SOURCE = "2" * 64
TEST_ALIGNMENT = replace(
    load_model_alignment_contract(
        ROOT / "config" / "model_alignment.hfss_builder_v1.json"
    ),
    comparison_context_id="aligned-v1",
)


def _response(s11: float) -> ComplexSParameters:
    return ComplexSParameters.from_complex_matrices(
        frequency_hz=[1e9, 2e9],
        matrices=[
            [[complex(s11, 0), complex(0.8, 0)], [complex(0.8, 0), complex(s11, 0)]],
            [
                [complex(s11 * 0.9, 0), complex(0.8, 0)],
                [complex(0.8, 0), complex(s11 * 0.9, 0)],
            ],
        ],
        port_order=("input", "output"),
    )


def calibration_case(case_id: str, surrogate_s11: float, hfss_s11: float, context: str):
    candidate = CandidateParameters(case_id, 1, {"p1": 1.0})
    surrogate = SParameterResult(
        case_id,
        True,
        _response(surrogate_s11),
        metadata={"comparison_context_id": context},
    )
    hfss = HFSSResult(
        case_id,
        True,
        complex_response=_response(hfss_s11),
        execution_metadata={"comparison_context_id": context},
    )
    return CalibrationCase(case_id, candidate, surrogate, hfss)


def calibration_cases(*, passed=True, context="aligned-v1"):
    hfss_values = (0.11, 0.21, 0.31) if passed else (0.40, 0.50, 0.60)
    return tuple(
        calibration_case(case_id, surrogate, hfss, context)
        for case_id, surrogate, hfss in zip(
            ("cal-a", "cal-b", "cal-c"), (0.10, 0.20, 0.30), hfss_values
        )
    )


def calibration_artifact_content(case_id: str, role: str) -> bytes:
    case = next(item for item in calibration_cases() if item.case_id == case_id)
    structured = {
        "candidate_parameters": case.candidate,
        "surrogate_result": case.surrogate,
        "hfss_result": case.hfss,
    }
    if role in structured:
        return canonical_dumps(structured[role]).encode("utf-8")
    return f"{case_id}:{role}".encode()


def calibration_artifacts(case_ids=("cal-a", "cal-b", "cal-c")):
    artifacts = []
    for case_id in case_ids:
        for role in sorted(CALIBRATION_ARTIFACT_ROLES):
            payload = calibration_artifact_content(case_id, role)
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


def strict_calibration(*, passed=True, context="aligned-v1", providers=None):
    providers = providers or {
        "supplied_surrogate_source_sha256": "8" * 64,
        "hfss_builder_source_sha256": "9" * 64,
        "pyaedt_executable_sha256": "a" * 64,
        "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
    }
    policy = CalibrationPolicy(0.02, 1.0)
    cases = calibration_cases(passed=passed, context=context)
    report = assess_calibration(list(cases), policy)
    return create_calibration_evidence(
        report,
        policy,
        evidence_id="calibration:canary",
        provider_fingerprints=providers,
        hfss_contract_sha256="5" * 64,
        source_artifacts=calibration_artifacts(tuple(item.case_id for item in cases)),
        created_at="2026-08-20T00:00:00+00:00",
    )


def manifest(**changes):
    calibration_evidence = strict_calibration()
    values = {
        "schema_version": READINESS_SCHEMA_VERSION,
        "readiness_id": "canary-2026-08-21",
        "task_id": "real-canary-fixed",
        "run_id": "run:real-canary-fixed",
        "workflow_id": REAL_HFSS_WORKFLOW_ID,
        "created_at": "2026-08-21T09:00:00+00:00",
        "expires_at": "2026-08-21T11:00:00+00:00",
        "git_head": HEAD,
        "agent_source_sha256": SOURCE,
        "run_manifest_sha256": "3" * 64,
        "design_goal_sha256": "4" * 64,
        "hfss_contract_sha256": "5" * 64,
        "evaluation_contract_sha256": "6" * 64,
        "model_alignment_sha256": TEST_ALIGNMENT.digest,
        "calibration_policy_sha256": calibration_evidence.policy_sha256,
        "calibration_artifact_manifest_sha256": calibration_evidence.source_artifact_manifest_sha256,
        "provider_fingerprints": FrozenMap.from_mapping(
            {
                "agent_source_sha256": SOURCE,
                "supplied_optimizer_source_sha256": "7" * 64,
                "supplied_surrogate_source_sha256": "8" * 64,
                "hfss_builder_source_sha256": "9" * 64,
                "pyaedt_executable_sha256": "a" * 64,
                "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
                "closed_loop_policy_sha256": production_policy_sha256(),
            }
        ),
        "approval_id": "approval-canary-1",
        "approval_scope": REAL_HFSS_APPROVAL_SCOPE,
        "execution_policy": ExecutionPolicy(2, 0),
        "calibration_evidence": calibration_evidence,
    }
    values.update(changes)
    return RealHFSSReadinessManifestV1(**values)


def evidence(*, clean=True, head=HEAD, source=SOURCE):
    return RepositoryEvidence(head, source, clean)


def write_manifest(tmp_path: Path, value=None) -> Path:
    path = tmp_path / "readiness.json"
    path.write_text(canonical_dumps(value or manifest()), encoding="utf-8")
    return path


def launch_config(tmp_path: Path, path: Path, *, readiness=None) -> dict:
    readiness = readiness or manifest()
    (tmp_path / "calibration_policy.json").write_text(
        canonical_dumps(readiness.calibration_evidence.policy.to_dict()),
        encoding="utf-8",
    )
    (tmp_path / "model_alignment.json").write_text(
        canonical_dumps(TEST_ALIGNMENT),
        encoding="utf-8",
    )
    artifact_root = tmp_path / "artifacts"
    for receipt in readiness.calibration_evidence.source_artifacts:
        target = artifact_root / Path(receipt.uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(calibration_artifact_content(receipt.case_id, receipt.role))
    return {
        "real_hfss_enabled": True,
        "real_hfss_readiness_manifest": str(path),
        "calibration_policy_path": str(tmp_path / "calibration_policy.json"),
        "model_alignment_path": str(tmp_path / "model_alignment.json"),
        "artifact_root": str(artifact_root),
    }

def test_repository_runtime_configuration_is_fail_closed():
    config = json.loads((ROOT / "runtime_config.json").read_text(encoding="utf-8"))
    with pytest.raises(RealHFSSSafetyError, match="disabled"):
        validate_real_hfss_launch_configuration(config, repository_root=ROOT)


def test_boolean_enable_alone_is_not_authorization(tmp_path):
    with pytest.raises(RealHFSSSafetyError, match="manifest path"):
        validate_real_hfss_launch_configuration(
            {"real_hfss_enabled": True},
            repository_root=tmp_path,
            repository_evidence=evidence(),
            now=NOW,
        )


def test_canonical_manifest_and_exact_repository_binding_are_accepted(tmp_path):
    path = write_manifest(tmp_path)
    authorized = validate_real_hfss_launch_configuration(
        launch_config(tmp_path, path),
        repository_root=tmp_path,
        repository_evidence=evidence(),
        now=NOW,
    )
    assert authorized.manifest.approval_id == "approval-canary-1"
    assert authorized.manifest.execution_policy == ExecutionPolicy(2, 0)


def test_versioned_calibration_policy_drift_fails_closed(tmp_path):
    path = write_manifest(tmp_path)
    config = launch_config(tmp_path, path)
    policy_path = Path(config["calibration_policy_path"])
    payload = canonical_loads(policy_path.read_text(encoding="utf-8"))
    payload["max_complex_rmse"] = 0.5
    policy_path.write_text(canonical_dumps(payload), encoding="utf-8")
    with pytest.raises(RealHFSSSafetyError, match="policy differs"):
        validate_real_hfss_launch_configuration(
            config,
            repository_root=tmp_path,
            repository_evidence=evidence(),
            now=NOW,
        )


def test_calibration_artifact_byte_tamper_fails_closed(tmp_path):
    readiness = manifest()
    path = write_manifest(tmp_path, readiness)
    config = launch_config(tmp_path, path, readiness=readiness)
    receipt = readiness.calibration_evidence.source_artifacts[0]
    artifact_path = Path(config["artifact_root"]) / Path(receipt.uri)
    artifact_path.write_bytes(b"tampered")
    with pytest.raises(RealHFSSSafetyError, match="artifact bytes differ"):
        validate_real_hfss_launch_configuration(
            config,
            repository_root=tmp_path,
            repository_evidence=evidence(),
            now=NOW,
        )


def test_calibration_report_is_recomputed_from_source_artifacts(tmp_path):
    readiness = manifest()
    candidate_receipt = next(
        receipt
        for receipt in readiness.calibration_evidence.source_artifacts
        if receipt.role == "candidate_parameters"
    )
    payload = canonical_loads(
        calibration_artifact_content(candidate_receipt.case_id, candidate_receipt.role)
    )
    payload["candidate_id"] = "different-candidate"
    rewritten = canonical_dumps(payload).encode("utf-8")
    forged_receipt = replace(
        candidate_receipt,
        sha256=hashlib.sha256(rewritten).hexdigest(),
        size_bytes=len(rewritten),
    )
    forged_artifacts = tuple(
        forged_receipt if receipt == candidate_receipt else receipt
        for receipt in readiness.calibration_evidence.source_artifacts
    )
    forged_evidence = replace(
        readiness.calibration_evidence,
        source_artifacts=forged_artifacts,
    )
    readiness = manifest(
        calibration_evidence=forged_evidence,
        calibration_artifact_manifest_sha256=(
            forged_evidence.source_artifact_manifest_sha256
        ),
    )
    path = write_manifest(tmp_path, readiness)
    config = launch_config(tmp_path, path, readiness=readiness)
    candidate_path = Path(config["artifact_root"]) / Path(candidate_receipt.uri)
    candidate_path.write_bytes(rewritten)
    with pytest.raises(RealHFSSSafetyError, match="cannot reproduce"):
        validate_real_hfss_launch_configuration(
            config,
            repository_root=tmp_path,
            repository_evidence=evidence(),
            now=NOW,
        )


@pytest.mark.parametrize(
    ("repository", "message"),
    [
        (evidence(clean=False), "clean working tree"),
        (evidence(head="8" * 40), "git_head"),
        (evidence(source="9" * 64), "source fingerprint"),
    ],
)
def test_repository_drift_fails_closed_before_composition(tmp_path, repository, message):
    path = write_manifest(tmp_path)
    with pytest.raises(RealHFSSSafetyError, match=message):
        validate_real_hfss_launch_configuration(
            launch_config(tmp_path, path),
            repository_root=tmp_path,
            repository_evidence=repository,
            now=NOW,
        )


def test_expired_manifest_is_rejected(tmp_path):
    path = write_manifest(tmp_path)
    with pytest.raises(RealHFSSSafetyError, match="expired"):
        validate_real_hfss_launch_configuration(
            launch_config(tmp_path, path),
            repository_root=tmp_path,
            repository_evidence=evidence(),
            now=datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
        )


def test_unknown_field_and_noncanonical_bytes_are_rejected(tmp_path):
    path = write_manifest(tmp_path)
    payload = canonical_loads(path.read_text(encoding="utf-8"))
    payload["surprise"] = True
    path.write_text(canonical_dumps(payload), encoding="utf-8")
    with pytest.raises(RealHFSSSafetyError, match="unknown fields"):
        validate_real_hfss_launch_configuration(
            launch_config(tmp_path, path),
            repository_root=tmp_path,
            repository_evidence=evidence(),
            now=NOW,
        )
    path.write_text(json.dumps(canonical_loads(canonical_dumps(manifest())), indent=2), encoding="utf-8")
    with pytest.raises(RealHFSSSafetyError, match="not canonical JSON"):
        validate_real_hfss_launch_configuration(
            launch_config(tmp_path, path),
            repository_root=tmp_path,
            repository_evidence=evidence(),
            now=NOW,
        )


def test_policy_must_be_exactly_two_launches_and_zero_retries(tmp_path):
    path = write_manifest(tmp_path, manifest(execution_policy=ExecutionPolicy(3, 0)))
    with pytest.raises(RealHFSSSafetyError, match="max_hfss_solve_launches=2"):
        validate_real_hfss_launch_configuration(
            launch_config(tmp_path, path),
            repository_root=tmp_path,
            repository_evidence=evidence(),
            now=NOW,
        )
    with pytest.raises(ValueError, match="exactly 0"):
        ExecutionPolicy(2, 1)


def test_workflow_binding_accepts_exact_evidence_and_rejects_drift(tmp_path):
    path = write_manifest(tmp_path)
    authorized = validate_real_hfss_launch_configuration(
        launch_config(tmp_path, path),
        repository_root=tmp_path,
        repository_evidence=evidence(),
        now=NOW,
    )
    kwargs = {
        "run_manifest_sha256": "3" * 64,
        "design_goal_sha256": "4" * 64,
        "hfss_contract_sha256": "5" * 64,
        "evaluation_contract_sha256": "6" * 64,
        "provider_fingerprints": manifest().provider_fingerprints.to_dict(),
        "task_id": "real-canary-fixed",
        "run_id": "run:real-canary-fixed",
        "workflow_id": REAL_HFSS_WORKFLOW_ID,
        "comparison_context_id": "aligned-v1",
        "calibration_evidence_sha256": manifest().calibration_evidence.digest,
        "model_alignment_sha256": manifest().model_alignment_sha256,
        "calibration_policy_sha256": manifest().calibration_policy_sha256,
        "calibration_artifact_manifest_sha256": manifest().calibration_artifact_manifest_sha256,
        "now": NOW,
    }
    validate_real_hfss_workflow_binding(authorized, **kwargs)
    kwargs["design_goal_sha256"] = "a" * 64
    with pytest.raises(RealHFSSSafetyError, match="design_goal_sha256"):
        validate_real_hfss_workflow_binding(authorized, **kwargs)


def test_failing_or_provider_drifted_calibration_cannot_authorize_real_hfss():
    with pytest.raises(ValueError, match="passing calibration"):
        manifest(calibration_evidence=strict_calibration(passed=False))
    with pytest.raises(ValueError, match="complete causal"):
        manifest(
            calibration_evidence=strict_calibration(
                providers={"supplied_surrogate_source_sha256": "f" * 64}
            )
        )


def test_readiness_rejects_production_policy_digest_drift() -> None:
    fingerprints = manifest().provider_fingerprints.to_dict()
    fingerprints["closed_loop_policy_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="Production policy"):
        manifest(
            provider_fingerprints=FrozenMap.from_mapping(fingerprints),
        )
