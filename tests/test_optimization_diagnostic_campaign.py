"""Offline proof for the bounded optimization-outcome HFSS diagnostic."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from hfss_optimization_agent.agent.closed_loop_contracts import production_policy_sha256
from hfss_optimization_agent.core.models import (
    ComplexSParameters,
    HFSSResult,
    SParameterResult,
)
from hfss_optimization_agent.domain.canonical_json import canonical_dumps
from hfss_optimization_agent.domain.contracts import FrozenMap
from hfss_optimization_agent.evaluation.model_alignment import (
    load_model_alignment_contract,
)
from hfss_optimization_agent.evaluation.optimization_diagnostic_campaign import (
    run_optimization_diagnostic_campaign,
)
from hfss_optimization_agent.harness.execution_policy import ExecutionPolicy
from hfss_optimization_agent.harness.optimization_diagnostic_safety import (
    OPTIMIZATION_DIAGNOSTIC_APPROVAL_SCOPE,
    OPTIMIZATION_DIAGNOSTIC_SCHEMA_VERSION,
    OPTIMIZATION_DIAGNOSTIC_WORKFLOW_ID,
    OptimizationDiagnosticAuthorization,
    OptimizationDiagnosticManifestV1,
    OptimizationDiagnosticSafetyError,
    diagnostic_plan_sha256,
    optimization_candidate_plan,
    validate_optimization_diagnostic_configuration,
)
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


def _providers() -> dict[str, str]:
    return {
        "agent_source_sha256": "1" * 64,
        "supplied_optimizer_source_sha256": "2" * 64,
        "supplied_surrogate_source_sha256": "2" * 64,
        "hfss_builder_source_sha256": "3" * 64,
        "pyaedt_executable_sha256": "4" * 64,
        "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
        "closed_loop_policy_sha256": production_policy_sha256(),
    }


def _summary(path: Path) -> Path:
    baseline = {
        "sub_h": 200e-6,
        "TSV_r": 15e-6,
        "TSV_p": 260e-6,
        "BGA_r": 125e-6,
        "BGA_p": 660e-6,
        "RDL_w_layer1": 100e-6,
        "RDL_d_layer1": 50e-6,
        "RDL_w_layer2": 80e-6,
        "RDL_d_layer2": 50e-6,
    }
    values = {name: value * 1.001 for name, value in baseline.items()}
    payload = {
        "status": "completed",
        "validation_status": "surrogate_only",
        "run_id": "optimizer-test",
        "algorithm": {"quick_mode": False},
        "recommended_point_id": "P0001",
        "recommended_parameters": {"model_units": values},
        "recommended_improvement": {
            "configured_objectives": {
                "worst_s11": {"improvement_toward_goal": 0.01},
                "mean_reflected_power": {"improvement_toward_goal": 0.001},
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _authorization(tmp_path: Path) -> OptimizationDiagnosticAuthorization:
    summary_path = _summary(tmp_path / "00_summary.json")
    candidates = optimization_candidate_plan(
        summary_path,
        comparison_context_id=CONTEXT,
    )
    alignment = load_model_alignment_contract(ALIGNMENT_PATH)
    contract = load_hfss_contract(CONTRACT_PATH)
    manifest = OptimizationDiagnosticManifestV1(
        schema_version=OPTIMIZATION_DIAGNOSTIC_SCHEMA_VERSION,
        campaign_id="optimization-diagnostic-test",
        task_id="optimization-diagnostic-test",
        run_id="run:optimization-diagnostic-test",
        workflow_id=OPTIMIZATION_DIAGNOSTIC_WORKFLOW_ID,
        created_at="2026-08-26T00:00:00+00:00",
        expires_at="2099-08-27T00:00:00+00:00",
        git_head="0" * 40,
        agent_source_sha256="1" * 64,
        hfss_contract_id=contract.contract_id,
        hfss_contract_sha256="5" * 64,
        model_alignment_sha256=alignment.digest,
        optimization_summary_uri="runs/00_summary.json",
        optimization_summary_sha256="6" * 64,
        optimizer_run_id="optimizer-test",
        recommended_point_id="P0001",
        diagnostic_plan_sha256=diagnostic_plan_sha256(candidates),
        provider_fingerprints=FrozenMap.from_mapping(_providers()),
        candidates=candidates,
        approval_id="approval:optimization-diagnostic-test",
        approval_scope=OPTIMIZATION_DIAGNOSTIC_APPROVAL_SCOPE,
        execution_policy=ExecutionPolicy(2, 0),
    )
    return OptimizationDiagnosticAuthorization(
        manifest,
        RepositoryEvidence("0" * 40, "1" * 64, True),
        alignment,
        contract,
        summary_path,
    )


def _response(s11: float) -> ComplexSParameters:
    return ComplexSParameters.from_complex_matrices(
        frequency_hz=[1e8 + index * (19.9e9 / 199) for index in range(200)],
        matrices=[
            [[complex(s11, 0), complex(0.8, 0)], [complex(0.8, 0), complex(s11, 0)]]
            for _ in range(200)
        ],
        port_order=("input", "output"),
    )


def test_optimization_candidate_plan_freezes_full_run_recommendation(tmp_path):
    summary_path = _summary(tmp_path / "00_summary.json")
    baseline, candidate = optimization_candidate_plan(
        summary_path,
        comparison_context_id=CONTEXT,
    )
    assert baseline.candidate_id == "baseline"
    assert candidate.candidate_id == "optimized_P0001"
    assert candidate.parent_candidate_id == "baseline"
    assert candidate.parameters != baseline.parameters


def test_optimization_diagnostic_is_default_disabled(tmp_path):
    with pytest.raises(OptimizationDiagnosticSafetyError, match="disabled"):
        validate_optimization_diagnostic_configuration(
            {"real_hfss_optimization_diagnostic_enabled": False},
            repository_root=tmp_path,
            repository_evidence=RepositoryEvidence("0" * 40, "1" * 64, True),
        )


def test_manifest_rejects_more_than_two_solve_launches(tmp_path):
    authority = _authorization(tmp_path)
    payload = json.loads(canonical_dumps(authority.manifest))
    payload["execution_policy"]["max_hfss_solve_launches"] = 3
    with pytest.raises(ValueError, match="exactly two"):
        OptimizationDiagnosticManifestV1.from_dict(payload)


def test_entry_configures_utf8_before_validation(monkeypatch, tmp_path):
    import RUN_HFSS_OPTIMIZATION_DIAGNOSTIC as entry

    calls: list[str] = []
    monkeypatch.setattr(entry, "configure_utf8_output", lambda: calls.append("utf8"))
    monkeypatch.setattr(
        entry,
        "validate_optimization_diagnostic_configuration",
        lambda *_args, **_kwargs: calls.append("validate") or _authorization(tmp_path),
    )
    monkeypatch.setattr(entry, "emit_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        entry,
        "run_optimization_diagnostic_campaign",
        lambda *_args, **_kwargs: calls.append("run")
        or SimpleNamespace(
            physical_improvement_observed=True,
            task_id="optimization-diagnostic-test",
            run_id="run:optimization-diagnostic-test",
            evidence_path=tmp_path / "evidence.json",
            evidence_sha256="7" * 64,
            evidence=FrozenMap.from_mapping({"status": "test"}),
        ),
    )
    assert entry.main() == 0
    assert calls == ["utf8", "validate", "run"]


def test_fake_two_case_campaign_reports_physical_improvement(monkeypatch, tmp_path):
    class FakeSurrogate:
        def run(self, candidate):
            value = 0.10 if candidate.candidate_id == "baseline" else 0.09
            return SParameterResult(
                candidate.candidate_id,
                True,
                _response(value),
                metadata={"comparison_context_id": CONTEXT},
            )

    class FakeHFSS:
        def run(self, candidate):
            value = 0.10 if candidate.candidate_id == "baseline" else 0.08
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
                complex_response=_response(value),
                execution_metadata={"comparison_context_id": CONTEXT},
            )

    monkeypatch.setattr(
        "hfss_optimization_agent.evaluation.optimization_diagnostic_campaign.SuppliedSurrogateAdapter",
        lambda _config: FakeSurrogate(),
    )
    monkeypatch.setattr(
        "hfss_optimization_agent.evaluation.optimization_diagnostic_campaign.compose_pyaedt_hfss",
        lambda **_kwargs: FakeHFSS(),
    )
    result = run_optimization_diagnostic_campaign(
        _authorization(tmp_path),
        optimizer_source_root=ROOT / "vendor" / "optimizer",
        builder_source_root=ROOT / "vendor" / "hfss_builder",
        pyaedt_python=Path(__import__("sys").executable),
        artifact_root=tmp_path / "runs",
    )
    assert result.physical_improvement_observed is True
    report = result.evidence.to_dict()
    assert report["direction_agreement"] is True
    assert report["hfss_observation"]["worst_s11_improvement_db"] > 0.0
    assert len(report["source_artifacts"]) == 10
    assert result.evidence_path.is_file()
    assert (
        RunStore(tmp_path / "runs" / ".runstore" / "runstore.sqlite3").count_rows(
            "approvals", run_id=result.run_id
        )
        == 2
    )
