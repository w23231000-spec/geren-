"""Offline proof for the separately authorized physical Calibration campaign."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from hfss_optimization_agent.agent.closed_loop_contracts import production_policy_sha256
from hfss_optimization_agent.core.models import (
    ComplexSParameters,
    HFSSResult,
    SParameterResult,
)
from hfss_optimization_agent.domain.canonical_json import canonical_dumps
from hfss_optimization_agent.domain.contracts import FrozenMap
from hfss_optimization_agent.evaluation.calibration import CalibrationPolicy
from hfss_optimization_agent.evaluation.calibration_campaign import (
    run_calibration_campaign,
)
from hfss_optimization_agent.evaluation.model_alignment import (
    load_model_alignment_contract,
)
from hfss_optimization_agent.harness.calibration_safety import (
    CALIBRATION_COLLECTION_APPROVAL_SCOPE,
    CALIBRATION_COLLECTION_SCHEMA_VERSION,
    CALIBRATION_COLLECTION_WORKFLOW_ID,
    CalibrationCollectionAuthorization,
    CalibrationCollectionManifestV1,
    CalibrationSafetyError,
    calibration_plan_sha256,
    deterministic_calibration_candidates,
    validate_calibration_collection_configuration,
)
from hfss_optimization_agent.harness.execution_policy import ExecutionPolicy
from hfss_optimization_agent.harness.real_hfss_safety import (
    HFSS_WORKER_PROTOCOL,
    RepositoryEvidence,
)
from hfss_optimization_agent.harness.run_store import RunStore
from hfss_optimization_agent.hfss.contracts import load_hfss_contract


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "hfss_contract.pa_multi_2025_1.json"
ALIGNMENT_PATH = ROOT / "config" / "model_alignment.hfss_builder_v1.json"
CONTEXT = "pa-multi-builder-2025.1-setup1-sweep-ports4to3-v1"


def providers():
    return {
        "agent_source_sha256": "1" * 64,
        "supplied_optimizer_source_sha256": "2" * 64,
        "supplied_surrogate_source_sha256": "2" * 64,
        "hfss_builder_source_sha256": "3" * 64,
        "pyaedt_executable_sha256": "4" * 64,
        "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
        "closed_loop_policy_sha256": production_policy_sha256(),
    }


def authorization() -> CalibrationCollectionAuthorization:
    policy = CalibrationPolicy(0.02, 1.0)
    alignment = load_model_alignment_contract(ALIGNMENT_PATH)
    contract = load_hfss_contract(CONTRACT_PATH)
    candidates = deterministic_calibration_candidates(comparison_context_id=CONTEXT)
    manifest = CalibrationCollectionManifestV1(
        schema_version=CALIBRATION_COLLECTION_SCHEMA_VERSION,
        campaign_id="calibration-test",
        task_id="calibration-test",
        run_id="run:calibration-test",
        workflow_id=CALIBRATION_COLLECTION_WORKFLOW_ID,
        created_at="2026-08-24T00:00:00+00:00",
        expires_at="2099-08-25T00:00:00+00:00",
        git_head="0" * 40,
        agent_source_sha256="1" * 64,
        hfss_contract_id=contract.contract_id,
        hfss_contract_sha256="5" * 64,
        model_alignment_sha256=alignment.digest,
        calibration_policy_sha256=__import__("hashlib").sha256(
            canonical_dumps(policy.to_dict()).encode("utf-8")
        ).hexdigest(),
        calibration_plan_sha256=calibration_plan_sha256(candidates),
        provider_fingerprints=FrozenMap.from_mapping(providers()),
        candidates=candidates,
        approval_id="approval:calibration-test",
        approval_scope=CALIBRATION_COLLECTION_APPROVAL_SCOPE,
        execution_policy=ExecutionPolicy(3, 0),
    )
    return CalibrationCollectionAuthorization(
        manifest,
        RepositoryEvidence("0" * 40, "1" * 64, True),
        policy,
        alignment,
        contract,
    )


def response(s11: float) -> ComplexSParameters:
    return ComplexSParameters.from_complex_matrices(
        frequency_hz=[1e8 + index * (19.9e9 / 199) for index in range(200)],
        matrices=[
            [[complex(s11, 0), complex(0.8, 0)], [complex(0.8, 0), complex(s11, 0)]]
            for _ in range(200)
        ],
        port_order=("input", "output"),
    )


def test_deterministic_candidates_are_three_distinct_interior_points():
    candidates = deterministic_calibration_candidates(comparison_context_id=CONTEXT)
    assert tuple(item.candidate_id for item in candidates) == (
        "baseline",
        "calibration_candidate_1",
        "calibration_candidate_2",
    )
    assert len({item.parameters for item in candidates}) == 3
    assert calibration_plan_sha256(candidates) == calibration_plan_sha256(candidates)


def test_calibration_collection_is_default_disabled_before_any_composition(tmp_path):
    with pytest.raises(CalibrationSafetyError, match="disabled"):
        validate_calibration_collection_configuration(
            {"real_hfss_calibration_enabled": False},
            repository_root=tmp_path,
            repository_evidence=RepositoryEvidence("0" * 40, "1" * 64, True),
        )


def test_collection_manifest_rejects_two_solve_policy():
    authority = authorization()
    payload = __import__("json").loads(canonical_dumps(authority.manifest))
    payload["execution_policy"]["max_hfss_solve_launches"] = 2
    with pytest.raises(ValueError, match="exactly three"):
        CalibrationCollectionManifestV1.from_dict(payload)


def test_calibration_entry_configures_utf8_before_validation(monkeypatch, tmp_path):
    import RUN_HFSS_CALIBRATION as entry

    calls = []
    monkeypatch.setattr(entry, "configure_utf8_output", lambda: calls.append("utf8"))
    monkeypatch.setattr(
        entry,
        "validate_calibration_collection_configuration",
        lambda *_args, **_kwargs: calls.append("validate") or authorization(),
    )
    monkeypatch.setattr(
        entry,
        "run_calibration_campaign",
        lambda *_args, **_kwargs: calls.append("run")
        or SimpleNamespace(
            passed=True,
            task_id="calibration-entry-test",
            run_id="run:calibration-entry-test",
            evidence_path=tmp_path / "evidence.json",
            evidence=SimpleNamespace(digest="1" * 64),
        ),
    )

    assert entry.main() == 0
    assert calls == ["utf8", "validate", "run"]


def test_fake_three_case_campaign_creates_reproducible_passing_evidence(
    monkeypatch, tmp_path
):
    values = {
        "baseline": 0.10,
        "calibration_candidate_1": 0.20,
        "calibration_candidate_2": 0.30,
    }

    class FakeSurrogate:
        def run(self, candidate):
            value = values[candidate.candidate_id]
            return SParameterResult(
                candidate.candidate_id,
                True,
                response(value),
                metadata={"comparison_context_id": CONTEXT},
            )

    class FakeHFSS:
        def run(self, candidate):
            value = values[candidate.candidate_id] + 0.001
            case_root = tmp_path / "provider" / candidate.candidate_id
            case_root.mkdir(parents=True, exist_ok=True)
            project = case_root / "model.aedt"
            touchstone = case_root / "result.s2p"
            project.write_bytes(b"fake-aedt")
            touchstone.write_bytes(b"fake-touchstone")
            return HFSSResult(
                candidate.candidate_id,
                True,
                project_path=str(project),
                artifact_paths=[str(touchstone)],
                complex_response=response(value),
                execution_metadata={"comparison_context_id": CONTEXT},
            )

    monkeypatch.setattr(
        "hfss_optimization_agent.evaluation.calibration_campaign.SuppliedSurrogateAdapter",
        lambda _config: FakeSurrogate(),
    )
    monkeypatch.setattr(
        "hfss_optimization_agent.evaluation.calibration_campaign.compose_pyaedt_hfss",
        lambda **_kwargs: FakeHFSS(),
    )
    result = run_calibration_campaign(
        authorization(),
        optimizer_source_root=ROOT / "vendor" / "optimizer",
        builder_source_root=ROOT / "vendor" / "hfss_builder",
        pyaedt_python=Path(__import__("sys").executable),
        artifact_root=tmp_path / "runs",
    )
    assert result.passed is True
    assert result.evidence.case_ids == (
        "baseline",
        "calibration_candidate_1",
        "calibration_candidate_2",
    )
    assert len(result.evidence.source_artifacts) == 15
    assert result.evidence_path.is_file()
    assert (
        RunStore(tmp_path / "runs" / ".runstore" / "runstore.sqlite3").count_rows(
            "approvals", run_id=result.run_id
        )
        == 2
    )
