"""Offline regressions for readiness authority; these never launch a Tool."""

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from hfss_optimization_agent.agent.closed_loop_contracts import production_policy_sha256
from hfss_optimization_agent.domain.canonical_json import canonical_dumps, canonical_loads
from hfss_optimization_agent.domain.contracts import (
    CALIBRATION_EVIDENCE_SCHEMA_VERSION,
    CalibrationEvidence,
    FrozenMap,
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


def calibration(*, passed=True, context="aligned-v1", providers=None):
    providers = providers or {
        "supplied_surrogate_source_sha256": "8" * 64,
        "hfss_builder_source_sha256": "9" * 64,
        "pyaedt_executable_sha256": "a" * 64,
        "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
    }
    return CalibrationEvidence(
        schema_version=CALIBRATION_EVIDENCE_SCHEMA_VERSION,
        evidence_id="calibration:canary",
        created_at="2026-08-20T00:00:00+00:00",
        policy_version="paired-surrogate-hfss/1.0",
        comparison_context_id=context,
        passed=passed,
        case_ids=("cal-a", "cal-b"),
        provider_fingerprints=FrozenMap.from_mapping(providers),
        policy=FrozenMap.from_mapping({"max_complex_rmse": 0.02}),
        report=FrozenMap.from_mapping(
            {
                "passed": passed,
                "comparison_context_id": context,
                "cases": [{"case_id": "cal-a"}, {"case_id": "cal-b"}],
            }
        ),
    )


def manifest(**changes):
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
        "calibration_evidence": calibration(),
    }
    values.update(changes)
    return RealHFSSReadinessManifestV1(**values)


def evidence(*, clean=True, head=HEAD, source=SOURCE):
    return RepositoryEvidence(head, source, clean)


def write_manifest(tmp_path: Path, value=None) -> Path:
    path = tmp_path / "readiness.json"
    path.write_text(canonical_dumps(value or manifest()), encoding="utf-8")
    return path


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
        {"real_hfss_enabled": True, "real_hfss_readiness_manifest": str(path)},
        repository_root=tmp_path,
        repository_evidence=evidence(),
        now=NOW,
    )
    assert authorized.manifest.approval_id == "approval-canary-1"
    assert authorized.manifest.execution_policy == ExecutionPolicy(2, 0)


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
            {"real_hfss_enabled": True, "real_hfss_readiness_manifest": str(path)},
            repository_root=tmp_path,
            repository_evidence=repository,
            now=NOW,
        )


def test_expired_manifest_is_rejected(tmp_path):
    path = write_manifest(tmp_path)
    with pytest.raises(RealHFSSSafetyError, match="expired"):
        validate_real_hfss_launch_configuration(
            {"real_hfss_enabled": True, "real_hfss_readiness_manifest": str(path)},
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
            {"real_hfss_enabled": True, "real_hfss_readiness_manifest": str(path)},
            repository_root=tmp_path,
            repository_evidence=evidence(),
            now=NOW,
        )
    path.write_text(json.dumps(canonical_loads(canonical_dumps(manifest())), indent=2), encoding="utf-8")
    with pytest.raises(RealHFSSSafetyError, match="not canonical JSON"):
        validate_real_hfss_launch_configuration(
            {"real_hfss_enabled": True, "real_hfss_readiness_manifest": str(path)},
            repository_root=tmp_path,
            repository_evidence=evidence(),
            now=NOW,
        )


def test_policy_must_be_exactly_two_launches_and_zero_retries(tmp_path):
    path = write_manifest(tmp_path, manifest(execution_policy=ExecutionPolicy(3, 0)))
    with pytest.raises(RealHFSSSafetyError, match="max_hfss_solve_launches=2"):
        validate_real_hfss_launch_configuration(
            {"real_hfss_enabled": True, "real_hfss_readiness_manifest": str(path)},
            repository_root=tmp_path,
            repository_evidence=evidence(),
            now=NOW,
        )
    with pytest.raises(ValueError, match="exactly 0"):
        ExecutionPolicy(2, 1)


def test_workflow_binding_accepts_exact_evidence_and_rejects_drift(tmp_path):
    path = write_manifest(tmp_path)
    authorized = validate_real_hfss_launch_configuration(
        {"real_hfss_enabled": True, "real_hfss_readiness_manifest": str(path)},
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
        "now": NOW,
    }
    validate_real_hfss_workflow_binding(authorized, **kwargs)
    kwargs["design_goal_sha256"] = "a" * 64
    with pytest.raises(RealHFSSSafetyError, match="design_goal_sha256"):
        validate_real_hfss_workflow_binding(authorized, **kwargs)


def test_failing_or_provider_drifted_calibration_cannot_authorize_real_hfss():
    with pytest.raises(ValueError, match="passing calibration"):
        manifest(calibration_evidence=calibration(passed=False))
    with pytest.raises(ValueError, match="provider fingerprints"):
        manifest(
            calibration_evidence=calibration(
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
