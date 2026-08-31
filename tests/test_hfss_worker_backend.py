"""Subprocess JSON protocol tests proving hard timeout and stage isolation without AEDT."""

import sys
from pathlib import Path

from hfss_optimization_agent.core.models import CandidateParameters
from hfss_optimization_agent.hfss.contracts import HFSSRunContract, PortContract, SweepContract
from hfss_optimization_agent.hfss.guarded_adapter import GuardedHFSSAdapter, GuardedHFSSConfig
from hfss_optimization_agent.hfss.worker_backend import JsonSubprocessHFSSBackend, JsonWorkerConfig


WORKER = r'''
import argparse
import json
import os
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--stage", required=True)
parser.add_argument("--request", required=True)
parser.add_argument("--response", required=True)
args = parser.parse_args()
request = json.loads(Path(args.request).read_text(encoding="utf-8"))
if os.environ.get("FAKE_SLEEP_STAGE") == args.stage:
    time.sleep(float(os.environ.get("FAKE_SLEEP_SECONDS", "0.2")))
if args.stage == "build":
    response = {"status": "success", "project_path": "mock://isolated-project", "design_name": request["contract"]["design_name"]}
elif args.stage == "solve":
    response = {"status": "success", "solution_id": "isolated-solution"}
else:
    response = {
        "status": "success",
        "frequency_hz": [1e9, 2e9],
        "first": [[[0.1, 0.8], [0.8, 0.1]], [[0.2, 0.7], [0.7, 0.2]]],
        "second": [[[0.0, 0.0], [0.0, 0.0]], [[0.0, 0.0], [0.0, 0.0]]],
        "representation": "real_imag",
        "port_order": ["input", "output"],
        "reference_impedance_ohm": 50.0
    }
Path(args.response).write_text(json.dumps(response), encoding="utf-8")
'''


def contract():
    return HFSSRunContract(
        schema_version="1",
        builder_id="json-worker-test",
        design_name="neutral",
        solution_type="Modal",
        setup_name="Setup1",
        sweep=SweepContract("Sweep", 1e9, 2e9, 2),
        ports=(PortContract("P1", "input"), PortContract("P2", "output")),
        parameter_mapping={"p1": "design_p1"},
        metadata={"comparison_context_id": "aligned-v1"},
    )


def make_adapter(tmp_path, *, solve_timeout=2.0, environment=None):
    worker = tmp_path / "fake_worker.py"
    worker.write_text(WORKER, encoding="utf-8")
    backend = JsonSubprocessHFSSBackend(
        JsonWorkerConfig((sys.executable, str(worker)), environment=environment)
    )
    return GuardedHFSSAdapter(
        backend=backend,
        contract=contract(),
        config=GuardedHFSSConfig(
            workspace_root=tmp_path / "runs",
            license_lock_path=tmp_path / "hfss.lock",
            solve_timeout_seconds=solve_timeout,
            license_wait_seconds=0.0,
        ),
    )


def test_json_worker_runs_all_stages_in_child_processes(tmp_path):
    result = make_adapter(tmp_path).run(CandidateParameters("candidate", 1, {"p1": 1.0}))
    assert result.success is True
    workspace = Path(result.execution_metadata["workspace"])
    assert len(list(workspace.glob("*_request.json"))) == 3
    assert len(list(workspace.glob("*_response.json"))) == 3
    assert result.execution_metadata["process_isolated"] is True


def test_json_worker_solve_has_hard_subprocess_timeout(tmp_path):
    result = make_adapter(
        tmp_path,
        solve_timeout=0.05,
        environment={"FAKE_SLEEP_STAGE": "solve", "FAKE_SLEEP_SECONDS": "0.3"},
    ).run(CandidateParameters("candidate", 1, {"p1": 1.0}))
    assert result.success is False
    assert "exceeded 0.05 seconds" in result.error
    assert not (tmp_path / "hfss.lock").exists()
