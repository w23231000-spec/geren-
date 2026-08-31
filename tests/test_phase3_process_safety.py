"""Offline proof for bounded worker cleanup, composite HFSS, and lock quarantine."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from hfss_optimization_agent.core.models import CandidateParameters
from hfss_optimization_agent.harness.errors import (
    HFSSLicenseLockError,
    HFSSProcessOutcomeUnknown,
    ProcessCancelled,
    ProcessTimedOut,
)
from hfss_optimization_agent.harness.license_lock import FileLicenseLock, LicenseLockConfig
from hfss_optimization_agent.harness.process_supervisor import (
    SupervisedProcessRunner,
    SupervisionPolicy,
)
from hfss_optimization_agent.hfss.backend import HFSSBackendInterface
from hfss_optimization_agent.hfss.contracts import (
    HFSSRunContract,
    PortContract,
    SweepContract,
    attest_builder,
)
from hfss_optimization_agent.hfss.guarded_adapter import GuardedHFSSAdapter, GuardedHFSSConfig
from hfss_optimization_agent.hfss.worker_backend import JsonSubprocessHFSSBackend, JsonWorkerConfig


def contract(builder_id: str = "phase3-builder") -> HFSSRunContract:
    return HFSSRunContract(
        schema_version="1",
        builder_id=builder_id,
        design_name="neutral",
        solution_type="Modal",
        setup_name="Setup1",
        sweep=SweepContract("Sweep", 1e9, 2e9, 2),
        ports=(PortContract("P1", "input"), PortContract("P2", "output")),
        parameter_mapping={"p1": "design_p1"},
        metadata={"comparison_context_id": "phase3-context"},
    )


WORKER_WITH_CHILD = r'''
import subprocess
import sys
import time
from pathlib import Path
from hfss_optimization_agent.harness.process_supervisor import worker_heartbeat_from_environment
with worker_heartbeat_from_environment():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")
    time.sleep(30)
'''


NATIVE_CALL_SAFE_WORKER = r'''
import sys
import time
from hfss_optimization_agent.harness.process_supervisor import worker_heartbeat_from_environment
with worker_heartbeat_from_environment(native_call_safe=True):
    sys.setswitchinterval(10.0)
    deadline = time.monotonic() + float(sys.argv[1])
    while time.monotonic() < deadline:
        pass
'''


def run_long_worker(tmp_path, *, cancel_event=None, timeout=0.25):
    pid_path = tmp_path / "child.pid"
    started = time.monotonic()
    with pytest.raises(ProcessCancelled if cancel_event is not None else ProcessTimedOut):
        SupervisedProcessRunner().run(
            (sys.executable, "-c", WORKER_WITH_CHILD, str(pid_path)),
            cwd=tmp_path,
            environment=None,
            heartbeat_path=tmp_path / "heartbeat.json",
            policy=SupervisionPolicy(
                timeout_seconds=timeout,
                heartbeat_timeout_seconds=1.0,
                termination_grace_seconds=1.0,
                poll_interval_seconds=0.02,
            ),
            cancel_event=cancel_event,
        )
    elapsed = time.monotonic() - started
    child_pid = int(pid_path.read_text(encoding="utf-8"))
    return elapsed, child_pid


def test_timeout_has_strict_upper_bound_and_leaves_no_worker_or_child(tmp_path):
    elapsed, child_pid = run_long_worker(tmp_path)
    assert elapsed < 1.75
    assert FileLicenseLock.pid_is_alive(child_pid) is False


def test_cancel_has_strict_upper_bound_and_leaves_no_worker_or_child(tmp_path):
    cancelled = threading.Event()
    timer = threading.Timer(0.15, cancelled.set)
    timer.start()
    try:
        elapsed, child_pid = run_long_worker(
            tmp_path, cancel_event=cancelled, timeout=10.0
        )
    finally:
        timer.cancel()
    assert elapsed < 1.75
    assert FileLicenseLock.pid_is_alive(child_pid) is False


def test_native_call_safe_heartbeat_survives_worker_gil_starvation(tmp_path):
    result = SupervisedProcessRunner().run(
        (sys.executable, "-c", NATIVE_CALL_SAFE_WORKER, "0.8"),
        cwd=tmp_path,
        environment=None,
        heartbeat_path=tmp_path / "native-heartbeat.json",
        policy=SupervisionPolicy(
            timeout_seconds=3.0,
            heartbeat_timeout_seconds=0.3,
            termination_grace_seconds=1.0,
            poll_interval_seconds=0.02,
        ),
    )
    assert result.returncode == 0
    assert result.elapsed_seconds >= 0.8


def test_native_call_safe_heartbeat_does_not_weaken_hard_timeout(tmp_path):
    started = time.monotonic()
    with pytest.raises(ProcessTimedOut):
        SupervisedProcessRunner().run(
            (sys.executable, "-c", NATIVE_CALL_SAFE_WORKER, "30"),
            cwd=tmp_path,
            environment=None,
            heartbeat_path=tmp_path / "native-timeout-heartbeat.json",
            policy=SupervisionPolicy(
                timeout_seconds=0.4,
                heartbeat_timeout_seconds=1.0,
                termination_grace_seconds=1.0,
                poll_interval_seconds=0.02,
            ),
        )
    assert time.monotonic() - started < 2.0


class UnknownCompositeBackend(HFSSBackendInterface):
    backend_name = "unknown-composite-test"
    process_isolated = True
    supports_composite = True

    def run_composite(self, candidate, workspace, contract, *, solve_timeout_seconds):
        del candidate, workspace, contract, solve_timeout_seconds
        raise HFSSProcessOutcomeUnknown(
            "injected unverified AEDT descendant",
            evidence={"active_processes": 1, "verified_no_processes": False},
        )

    def build(self, candidate, workspace, contract):
        raise AssertionError("composite backend must not call build")

    def solve(self, project, contract, *, timeout_seconds):
        raise AssertionError("composite backend must not call solve")

    def extract(self, solved, contract):
        raise AssertionError("composite backend must not call extract")

    def close(self):
        return None


def test_unverified_cleanup_returns_unknown_evidence_and_quarantines_lock(tmp_path):
    lock_path = tmp_path / "aedt.lock"
    adapter = GuardedHFSSAdapter(
        backend=UnknownCompositeBackend(),
        contract=contract(),
        config=GuardedHFSSConfig(
            workspace_root=tmp_path / "work",
            license_lock_path=lock_path,
            solve_timeout_seconds=1.0,
            license_wait_seconds=0.0,
        ),
    )
    result = adapter.run(CandidateParameters("candidate", 1, {"p1": 1.0}))

    assert result.success is False
    assert result.execution_metadata["physical_outcome"] == "UNKNOWN"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock["status"] == "QUARANTINED"
    assert lock["evidence"]["verified_no_processes"] is False
    with pytest.raises(HFSSLicenseLockError, match="quarantined"):
        FileLicenseLock(
            LicenseLockConfig(path=lock_path, acquire_timeout_seconds=0.0)
        ).acquire()


def test_builder_drift_fails_before_license_acquisition(tmp_path):
    builder = tmp_path / "builder"
    builder.mkdir()
    source = builder / "nine_parameter_builder.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    attestation = attest_builder(builder, "phase3-builder")
    source.write_text("VALUE = 2\n", encoding="utf-8")
    lock_path = tmp_path / "aedt.lock"
    backend = JsonSubprocessHFSSBackend(
        JsonWorkerConfig(
            command_prefix=(sys.executable, "-c", "raise SystemExit(99)"),
            worker_options={"builder_source_root": str(builder)},
            builder_attestation=attestation,
        )
    )
    adapter = GuardedHFSSAdapter(
        backend=backend,
        contract=contract(),
        config=GuardedHFSSConfig(
            workspace_root=tmp_path / "work",
            license_lock_path=lock_path,
            solve_timeout_seconds=1.0,
            license_wait_seconds=0.0,
        ),
    )

    result = adapter.run(CandidateParameters("candidate", 1, {"p1": 1.0}))

    assert result.success is False
    assert "Builder source drift detected before license acquisition" in result.error
    assert not lock_path.exists()


COMPOSITE_WORKER = r'''
import argparse
import hashlib
import json
from pathlib import Path
from hfss_optimization_agent.harness.process_supervisor import worker_heartbeat_from_environment
parser = argparse.ArgumentParser()
parser.add_argument("--stage")
parser.add_argument("--request")
parser.add_argument("--response")
args = parser.parse_args()
request = json.loads(Path(args.request).read_text(encoding="utf-8"))
digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
with worker_heartbeat_from_environment():
    response = {
        "status": "success",
        "request_digest": digest,
        "builder_attestation_digest": request["builder_attestation"]["source_digest"],
        "built": {"project_path": "mock://project", "design_name": request["contract"]["design_name"]},
        "solved": {"project_path": "mock://project", "design_name": request["contract"]["design_name"], "solution_id": "Setup1 : Sweep"},
        "raw": {
            "frequency_hz": [1e9, 2e9],
            "first": [[[0.1, 0.8], [0.8, 0.1]], [[0.2, 0.7], [0.7, 0.2]]],
            "second": [[[0.0, 0.0], [0.0, 0.0]], [[0.0, 0.0], [0.0, 0.0]]],
            "representation": "real_imag",
            "port_order": ["input", "output"],
            "reference_impedance_ohm": 50.0,
            "metadata": {}
        }
    }
    Path(args.response).write_text(json.dumps(response), encoding="utf-8")
'''


def test_composite_hfss_uses_one_attested_worker_request(tmp_path):
    builder = tmp_path / "builder"
    builder.mkdir()
    (builder / "nine_parameter_builder.py").write_text("VALUE = 1\n", encoding="utf-8")
    attestation = attest_builder(builder, "phase3-builder")
    worker = tmp_path / "composite_worker.py"
    worker.write_text(COMPOSITE_WORKER, encoding="utf-8")
    backend = JsonSubprocessHFSSBackend(
        JsonWorkerConfig(
            command_prefix=(sys.executable, str(worker)),
            worker_options={"builder_source_root": str(builder)},
            builder_attestation=attestation,
            build_timeout_seconds=1.0,
            extract_timeout_seconds=1.0,
        )
    )
    adapter = GuardedHFSSAdapter(
        backend=backend,
        contract=contract(),
        config=GuardedHFSSConfig(
            workspace_root=tmp_path / "work",
            license_lock_path=tmp_path / "aedt.lock",
            solve_timeout_seconds=1.0,
            license_wait_seconds=0.0,
        ),
    )

    result = adapter.run(CandidateParameters("candidate", 1, {"p1": 1.0}))

    assert result.success is True
    assert result.execution_metadata["composite_request_digest"]
    assert result.execution_metadata["builder_attestation_digest"] == attestation.source_digest
    workspace = Path(result.execution_metadata["workspace"])
    assert len(list(workspace.glob("*_request.json"))) == 1
    assert len(list(workspace.glob("*_response.json"))) == 1
    request_payload = json.loads(
        next(workspace.glob("*_request.json")).read_text(encoding="utf-8")
    )
    snapshot = Path(request_payload["worker_options"]["builder_source_root"])
    assert snapshot.name == "builder_snapshot"
    assert snapshot != builder
    assert attest_builder(snapshot, "phase3-builder") == attestation
    journal = json.loads((workspace / "run_journal.json").read_text(encoding="utf-8"))
    assert journal["builder_attestation_digest"] == attestation.source_digest
