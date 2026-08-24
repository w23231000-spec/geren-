"""Offline tests for the real-worker contract; these never import or launch PyAEDT."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from hfss_optimization_agent.agent.closed_loop_contracts import production_policy_sha256
from hfss_optimization_agent.cli import _contract_frequency_grid, run_real_supplied_demo
from hfss_optimization_agent.harness.errors import HFSSContractError
from hfss_optimization_agent.hfss.contracts import (
    SweepContract,
    load_hfss_contract,
    validate_sweep_frequency_grid,
)
from hfss_optimization_agent.hfss.pyaedt_composition import compose_pyaedt_hfss
from hfss_optimization_agent.hfss.pyaedt_worker import (
    _candidate_values,
    _frequency_multiplier,
    _logical_expressions,
    _resolve_active_design,
)
from hfss_optimization_agent.domain.contracts import (
    CALIBRATION_ARTIFACT_ROLES,
    CALIBRATION_EVIDENCE_SCHEMA_VERSION,
    CALIBRATION_POLICY_VERSION,
    CalibrationArtifactReceipt,
    CalibrationEvidence,
    FrozenMap,
    calibration_policy_sha256,
    calibration_artifact_manifest_sha256,
)
from hfss_optimization_agent.harness.execution_policy import ExecutionPolicy
from hfss_optimization_agent.harness.real_hfss_safety import (
    HFSS_WORKER_PROTOCOL,
    READINESS_SCHEMA_VERSION,
    REAL_HFSS_APPROVAL_SCOPE,
    REAL_HFSS_WORKFLOW_ID,
    RealHFSSAuthorization,
    RealHFSSReadinessManifestV1,
    RealHFSSSafetyError,
    RepositoryEvidence,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "hfss_contract.pa_multi_2025_1.json"


def test_configured_aedt_python_can_import_worker_cli_without_launching_aedt():
    configuration = json.loads((ROOT / "runtime_config.json").read_text(encoding="utf-8"))
    interpreter = Path(configuration["pyaedt_python"])
    if not interpreter.is_file():
        pytest.skip("configured AEDT/PyAEDT Python is unavailable")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [
            str(interpreter),
            "-m",
            "hfss_optimization_agent.hfss.pyaedt_worker",
            "--help",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20.0,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "pyaedt-hfss-worker" in completed.stdout


def contract_dict():
    return load_hfss_contract(CONTRACT_PATH).to_dict()


def test_real_contract_solves_template_and_orders_input_port_4_first():
    contract = load_hfss_contract(CONTRACT_PATH)
    assert contract.design_name == "interposer_temple4"
    assert contract.metadata["build_strategy"] == "target_design_only"
    assert [port.exported_name for port in contract.ports] == ["4", "3"]
    assert contract.port_order == ("input", "output")
    assert contract.sweep.points == 200


def test_logical_expression_matrix_maps_s11_and_s21_without_reciprocity_assumption():
    expressions, matrix = _logical_expressions(contract_dict())
    assert matrix == [["S(4,4)", "S(4,3)"], ["S(3,4)", "S(3,3)"]]
    assert expressions == ["S(4,4)", "S(4,3)", "S(3,4)", "S(3,3)"]
    assert matrix[1][0] == "S(3,4)"


def test_grpc_active_design_compatibility_resolves_exact_object_after_bool_ack():
    class Design:
        def GetName(self):
            return "interposer_temple4"

    class Project:
        def SetActiveDesign(self, _name):
            return True

        def GetDesign(self, _name):
            return Design()

        def GetActiveDesign(self):
            return None

    resolved = _resolve_active_design(
        Project(), "interposer_temple4", timeout_seconds=0.0
    )
    assert resolved.GetName() == "interposer_temple4"


def test_grpc_active_design_compatibility_never_selects_wrong_design():
    class WrongDesign:
        def GetName(self):
            return "huitu"

    class Project:
        def SetActiveDesign(self, _name):
            return None

        def GetDesign(self, _name):
            return WrongDesign()

        def GetActiveDesign(self):
            return WrongDesign()

    with pytest.raises(RuntimeError, match="exact active design"):
        _resolve_active_design(Project(), "interposer_temple4", timeout_seconds=0.0)


@pytest.mark.parametrize(
    ("unit", "expected"),
    [("Hz", 1.0), ("kHz", 1e3), ("MHz", 1e6), ("GHz", 1e9), ("THz", 1e12)],
)
def test_frequency_units_are_converted_to_hz(unit, expected):
    assert _frequency_multiplier(unit) == expected


def test_surrogate_comparison_grid_exactly_matches_hfss_contract():
    grid = _contract_frequency_grid(load_hfss_contract(CONTRACT_PATH))
    assert len(grid) == 200
    assert grid[0] == pytest.approx(0.1e9)
    assert grid[-1] == pytest.approx(20e9)
    assert grid[1] - grid[0] == pytest.approx(0.1e9)


def test_hfss_frequency_grid_accepts_exact_declared_linear_grid():
    contract = load_hfss_contract(CONTRACT_PATH)
    grid = _contract_frequency_grid(contract)
    assert validate_sweep_frequency_grid(grid, contract.sweep) == tuple(grid)


@pytest.mark.parametrize(
    ("grid", "message"),
    [
        ([1e9, 1.5e9], "frequency points"),
        ([1e9 + 10.0, 1.5e9, 2e9], "index 0"),
        ([1e9, 1.5e9 + 10.0, 2e9], "index 1"),
        ([1e9, 1.5e9, 2e9 - 10.0], "index 2"),
        ([1.0, 1.5, 2.0], "index 0"),
    ],
)
def test_hfss_frequency_grid_rejects_count_endpoint_interior_and_unit_drift(grid, message):
    with pytest.raises(HFSSContractError, match=message):
        validate_sweep_frequency_grid(grid, SweepContract("Sweep", 1e9, 2e9, 3))


def test_explicit_grid_fails_closed_until_contract_declares_intermediate_points():
    with pytest.raises(HFSSContractError, match="Explicit sweep spacing cannot be verified"):
        validate_sweep_frequency_grid(
            [1e9, 1.5e9, 2e9],
            SweepContract("Sweep", 1e9, 2e9, 3, spacing="explicit"),
        )


def test_candidate_requires_exact_nine_parameter_contract():
    contract = contract_dict()
    values = {name: 1e-4 for name in contract["parameter_mapping"]}
    request = {"candidate": {"values": values}}
    assert _candidate_values(request, contract) == values
    request["candidate"]["values"].pop("sub_h")
    with pytest.raises(ValueError, match="parameter mismatch"):
        _candidate_values(request, contract)


def test_real_composition_is_inert_and_carries_runtime_options(tmp_path):
    builder = tmp_path / "builder"
    builder.mkdir()
    (builder / "nine_parameter_builder.py").write_text("# inert test builder\n", encoding="utf-8")
    adapter = compose_pyaedt_hfss(
        contract=load_hfss_contract(CONTRACT_PATH),
        pyaedt_python=Path(__import__("sys").executable),
        builder_source_root=builder,
        artifact_root=tmp_path / "runs",
        task_id="inert",
    )
    assert adapter.backend.process_isolated is True
    assert adapter.backend.config.heartbeat_timeout_seconds == 120.0
    assert adapter.backend.config.worker_options["builder_source_root"] == str(builder.resolve())
    assert not (tmp_path / "runs").exists()


def test_real_workflow_requires_explicit_execution_acknowledgement(tmp_path):
    with pytest.raises(ValueError, match="execute_real_hfss=True"):
        run_real_supplied_demo(
            optimizer_source_root=tmp_path,
            builder_source_root=tmp_path,
            pyaedt_python=Path(__import__("sys").executable),
            contract_path=CONTRACT_PATH,
            execute_real_hfss=False,
        )


def test_real_workflow_requires_validated_readiness_authorization(tmp_path):
    with pytest.raises(ValueError, match="readiness authorization"):
        run_real_supplied_demo(
            optimizer_source_root=tmp_path,
            builder_source_root=tmp_path,
            pyaedt_python=Path(__import__("sys").executable),
            contract_path=CONTRACT_PATH,
            execute_real_hfss=True,
        )


def test_readiness_drift_fails_before_real_worker_composition(monkeypatch, tmp_path):
    composed = 0

    def forbidden_composition(**_kwargs):
        nonlocal composed
        composed += 1
        raise AssertionError("worker composition must remain unreachable")

    monkeypatch.setattr(
        "hfss_optimization_agent.cli.compose_pyaedt_hfss", forbidden_composition
    )
    source = "1" * 64
    calibration_case_ids = ("cal-a", "cal-b", "cal-c")
    calibration_policy = {
        "max_complex_rmse": 0.02,
        "max_magnitude_db_rmse": 1.0,
        "minimum_pairwise_ranking_agreement": 0.8,
        "frequency_tolerance_hz": 1.0,
        "impedance_tolerance_ohm": 1e-9,
        "require_comparison_context_id": True,
        "minimum_case_count": 3,
        "minimum_comparable_pairs": 2,
    }
    calibration_artifacts = tuple(
        CalibrationArtifactReceipt(
            artifact_id=f"{case_id}:{role}",
            case_id=case_id,
            candidate_id=case_id,
            role=role,
            uri=f"calibration/{case_id}/{role}.bin",
            sha256=hashlib.sha256(f"{case_id}:{role}".encode()).hexdigest(),
            size_bytes=len(f"{case_id}:{role}".encode()),
        )
        for case_id in calibration_case_ids
        for role in sorted(CALIBRATION_ARTIFACT_ROLES)
    )
    authorization = RealHFSSAuthorization(
        RealHFSSReadinessManifestV1(
            schema_version=READINESS_SCHEMA_VERSION,
            readiness_id="drift-test",
            task_id="drift-test",
            run_id="run:drift-test",
            workflow_id=REAL_HFSS_WORKFLOW_ID,
            created_at="2026-08-21T00:00:00+00:00",
            expires_at="2099-08-21T00:00:00+00:00",
            git_head="0" * 40,
            agent_source_sha256=source,
            run_manifest_sha256="2" * 64,
            design_goal_sha256="3" * 64,
            hfss_contract_sha256="4" * 64,
            evaluation_contract_sha256="5" * 64,
            model_alignment_sha256="a" * 64,
            calibration_policy_sha256=calibration_policy_sha256(calibration_policy),
            calibration_artifact_manifest_sha256=calibration_artifact_manifest_sha256(calibration_artifacts),
            provider_fingerprints=FrozenMap.from_mapping(
                {
                    "agent_source_sha256": source,
                    "supplied_optimizer_source_sha256": "6" * 64,
                    "supplied_surrogate_source_sha256": "7" * 64,
                    "hfss_builder_source_sha256": "8" * 64,
                    "pyaedt_executable_sha256": "9" * 64,
                    "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
                    "closed_loop_policy_sha256": production_policy_sha256(),
                }
            ),
            approval_id="drift-approval",
            approval_scope=REAL_HFSS_APPROVAL_SCOPE,
            execution_policy=ExecutionPolicy(2, 0),
            calibration_evidence=CalibrationEvidence(
                schema_version=CALIBRATION_EVIDENCE_SCHEMA_VERSION,
                evidence_id="calibration:drift-test",
                created_at="2026-08-20T00:00:00+00:00",
                policy_version=CALIBRATION_POLICY_VERSION,
                comparison_context_id="pa-multi-2025.1:interposer_temple4:ports-4-3",
                passed=True,
                case_ids=calibration_case_ids,
                provider_fingerprints=FrozenMap.from_mapping(
                    {
                        "supplied_surrogate_source_sha256": "7" * 64,
                        "hfss_builder_source_sha256": "8" * 64,
                        "pyaedt_executable_sha256": "9" * 64,
                        "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
                    }
                ),
                policy=FrozenMap.from_mapping(calibration_policy),
                policy_sha256=calibration_policy_sha256(calibration_policy),
                hfss_contract_sha256="4" * 64,
                report=FrozenMap.from_mapping(
                    {
                        "passed": True,
                        "comparison_context_id": "pa-multi-2025.1:interposer_temple4:ports-4-3",
                        "cases": [
                            {
                                "case_id": case_id,
                                "candidate_id": case_id,
                                "complex_rmse": 0.01,
                                "magnitude_db_rmse": 0.5,
                                "max_complex_error": 0.02,
                                "surrogate_worst_s11": 0.1 * index,
                                "hfss_worst_s11": 0.1 * index + 0.01,
                            }
                            for index, case_id in enumerate(calibration_case_ids, start=1)
                        ],
                        "mean_complex_rmse": 0.01,
                        "mean_magnitude_db_rmse": 0.5,
                        "pairwise_ranking_agreement": 1.0,
                        "comparable_pairs": 3,
                        "reasons": [],
                    }
                ),
                source_artifacts=calibration_artifacts,
            ),
        ),
        RepositoryEvidence("0" * 40, source, True),
    )
    with pytest.raises(RealHFSSSafetyError, match="run_manifest_sha256"):
        run_real_supplied_demo(
            optimizer_source_root=ROOT / "vendor" / "optimizer",
            builder_source_root=ROOT / "vendor" / "hfss_builder",
            pyaedt_python=Path(__import__("sys").executable),
            contract_path=CONTRACT_PATH,
            evaluation_contract_path=ROOT / "config" / "evaluation_contract.production_v1.json",
            artifact_root=tmp_path,
            execute_real_hfss=True,
            readiness_authorization=authorization,
        )
    assert composed == 0
    assert not (tmp_path / "drift-test").exists()
