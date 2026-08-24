"""Pure fake-backend tests for HFSS contracts, guards, conversion, and failure release."""

import json
from pathlib import Path

import pytest

from hfss_optimization_agent.core.models import CandidateParameters
from hfss_optimization_agent.harness.license_lock import FileLicenseLock, LicenseLockConfig
from hfss_optimization_agent.harness.errors import HFSSLicenseLockError
from hfss_optimization_agent.hfss.backend import (
    BuiltProject,
    HFSSBackendInterface,
    RawSParameterData,
    SolvedProject,
)
from hfss_optimization_agent.hfss.contracts import (
    HFSSRunContract,
    MaterialContract,
    PortContract,
    SweepContract,
    load_hfss_contract,
)
from hfss_optimization_agent.hfss.guarded_adapter import GuardedHFSSAdapter, GuardedHFSSConfig


def contract(*, representation="real_imag", context="aligned-v1") -> HFSSRunContract:
    return HFSSRunContract(
        schema_version="1.0",
        builder_id="fake-builder-v1",
        design_name="neutral_design",
        solution_type="Modal",
        setup_name="Setup1",
        sweep=SweepContract("Sweep", 1e9, 2e9, 2),
        ports=(
            PortContract("P1", "input"),
            PortContract("P2", "output"),
        ),
        parameter_mapping={"p1": "design_p1"},
        materials=(MaterialContract("neutral", 3.5),),
        extractor_format=representation,
        metadata={"comparison_context_id": context},
    )


class FakeBackend(HFSSBackendInterface):
    backend_name = "fake-process-backend"
    process_isolated = True

    def __init__(
        self,
        *,
        fail_stage=None,
        representation="real_imag",
        port_order=("input", "output"),
        frequency_hz=(1e9, 2e9),
    ):
        self.fail_stage = fail_stage
        self.representation = representation
        self.port_order = port_order
        self.frequency_hz = frequency_hz
        self.calls = []
        self.close_count = 0
        self.timeout = None

    def build(self, candidate, workspace, run_contract):
        self.calls.append("build")
        if self.fail_stage == "build":
            raise RuntimeError("controlled build failure")
        return BuiltProject("mock://project", run_contract.design_name, {"workspace": str(workspace)})

    def solve(self, project, run_contract, *, timeout_seconds):
        self.calls.append("solve")
        self.timeout = timeout_seconds
        if self.fail_stage == "solve":
            raise TimeoutError("controlled solve timeout")
        return SolvedProject(project.project_path, project.design_name, "solution-1")

    def extract(self, solved, run_contract):
        self.calls.append("extract")
        if self.fail_stage == "extract":
            raise RuntimeError("controlled extract failure")
        if self.representation == "real_imag":
            first = [[[0.1, 0.8], [0.8, 0.1]], [[0.2, 0.7], [0.7, 0.2]]]
            second = [[[0.0, -0.1], [-0.1, 0.0]], [[0.1, -0.2], [-0.2, 0.1]]]
        elif self.representation == "magnitude_phase_deg":
            first = [[[0.1, 0.8], [0.8, 0.1]], [[0.2, 0.7], [0.7, 0.2]]]
            second = [[[0.0, -10.0], [-10.0, 0.0]], [[20.0, -20.0], [-20.0, 20.0]]]
        else:
            first = [[[-20.0, -1.0], [-1.0, -20.0]], [[-14.0, -3.0], [-3.0, -14.0]]]
            second = [[[0.0, -10.0], [-10.0, 0.0]], [[20.0, -20.0], [-20.0, 20.0]]]
        return RawSParameterData(
            self.frequency_hz,
            first,
            second,
            self.representation,
            self.port_order,
            50.0,
        )

    def close(self):
        self.calls.append("close")
        self.close_count += 1


def adapter(tmp_path: Path, backend: FakeBackend, run_contract=None) -> GuardedHFSSAdapter:
    return GuardedHFSSAdapter(
        backend=backend,
        contract=run_contract or contract(representation=backend.representation),
        config=GuardedHFSSConfig(
            workspace_root=tmp_path / "workspaces",
            license_lock_path=tmp_path / "locks" / "hfss.lock",
            solve_timeout_seconds=12.5,
            license_wait_seconds=0.0,
        ),
    )


@pytest.mark.parametrize("representation", ["real_imag", "magnitude_phase_deg", "db_phase_deg"])
def test_guarded_adapter_runs_build_solve_extract_and_converts_complex_data(tmp_path, representation):
    backend = FakeBackend(representation=representation)
    result = adapter(tmp_path, backend).run(CandidateParameters("candidate", 1, {"p1": 1.0}))
    assert result.success is True
    assert backend.calls == ["build", "solve", "extract", "close"]
    assert backend.timeout == 12.5
    assert result.complex_response.port_order == ("input", "output")
    assert result.execution_metadata["comparison_context_id"] == "aligned-v1"
    assert not (tmp_path / "locks" / "hfss.lock").exists()
    journal = json.loads(Path(result.artifact_paths[0]).read_text(encoding="utf-8"))
    assert journal["status"] == "completed"


def test_solve_failure_is_traceable_releases_backend_and_preserves_workspace(tmp_path):
    backend = FakeBackend(fail_stage="solve")
    result = adapter(tmp_path, backend).run(CandidateParameters("candidate", 1, {"p1": 1.0}))
    assert result.success is False
    assert "controlled solve timeout" in result.error
    assert backend.calls == ["build", "solve", "close"]
    assert backend.close_count == 1
    assert not (tmp_path / "locks" / "hfss.lock").exists()
    journal = json.loads(Path(result.artifact_paths[0]).read_text(encoding="utf-8"))
    assert journal["status"] == "failed"
    assert Path(result.artifact_paths[1]).is_dir()


def test_port_order_mismatch_fails_before_result_is_accepted(tmp_path):
    backend = FakeBackend(port_order=("output", "input"))
    result = adapter(tmp_path, backend).run(CandidateParameters("candidate", 1, {"p1": 1.0}))
    assert result.success is False
    assert "port order" in result.error
    assert backend.close_count == 1


def test_frequency_grid_mismatch_fails_before_result_is_accepted(tmp_path):
    backend = FakeBackend(frequency_hz=(1e9 + 10.0, 2e9))
    result = adapter(tmp_path, backend).run(CandidateParameters("candidate", 1, {"p1": 1.0}))
    assert result.success is False
    assert "frequency grid mismatch at index 0" in result.error
    assert backend.close_count == 1


def test_backend_without_process_isolation_is_rejected_without_stage_calls(tmp_path):
    backend = FakeBackend()
    backend.process_isolated = False
    result = adapter(tmp_path, backend).run(CandidateParameters("candidate", 1, {"p1": 1.0}))
    assert result.success is False
    assert "process isolation" in result.error
    assert backend.calls == []


def test_file_license_lock_detects_contention_and_preserves_owner(tmp_path):
    path = tmp_path / "hfss.lock"
    first = FileLicenseLock(LicenseLockConfig(path, acquire_timeout_seconds=0.0))
    second = FileLicenseLock(LicenseLockConfig(path, acquire_timeout_seconds=0.0))
    first.acquire()
    with pytest.raises(HFSSLicenseLockError, match="Timed out"):
        second.acquire()
    assert path.exists()
    first.release()
    assert not path.exists()


def test_file_license_lock_reclaims_dead_owner(tmp_path):
    path = tmp_path / "hfss.lock"
    path.write_text('{"token":"stale","pid":-1}', encoding="utf-8")
    lock = FileLicenseLock(LicenseLockConfig(path, acquire_timeout_seconds=0.0))
    lock.acquire()
    assert path.exists()
    lock.release()
    assert not path.exists()


def test_contract_fingerprint_changes_with_material_assumption():
    first = contract()
    second = HFSSRunContract(
        **{
            **first.to_dict(),
            "sweep": first.sweep,
            "ports": first.ports,
            "materials": (MaterialContract("neutral", 3.9),),
        }
    )
    assert first.contract_id != second.contract_id


def test_json_contract_loader_reconstructs_nested_contract(tmp_path):
    source = tmp_path / "contract.json"
    source.write_text(json.dumps(contract().to_dict()), encoding="utf-8")
    loaded = load_hfss_contract(source)
    assert loaded.contract_id == contract().contract_id
    assert loaded.ports[0].physical_role == "input"
