"""Phase 5B kill verification, parent-death containment and lock reconciliation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from hfss_optimization_agent.agent.comparison_state import create_comparison_state
from hfss_optimization_agent.domain.contracts import FrozenMap
from hfss_optimization_agent.harness.artifacts import ArtifactStore
from hfss_optimization_agent.harness.core import HarnessCore, HarnessSettings, OperationUnknownError
from hfss_optimization_agent.harness.errors import (
    HFSSLicenseLockError,
    ProcessOutcomeUnknown,
)
from hfss_optimization_agent.harness.license_lock import FileLicenseLock, LicenseLockConfig
from hfss_optimization_agent.harness.lock_reconciliation import reconcile_quarantined_lock
from hfss_optimization_agent.harness.process_supervisor import (
    SupervisedProcessRunner,
    SupervisionPolicy,
)
from hfss_optimization_agent.harness.reconciliation import (
    RECONCILIATION_APPROVAL_SCOPE,
    RECONCILIATION_SCHEMA_VERSION,
    ReconciliationRequest,
    ReconciliationResolution,
)
from hfss_optimization_agent.harness.run_store import ApprovalGrant, OperationRequest, RunStore
from hfss_optimization_agent.parameters.nine_parameter_schema import supplied_baseline_candidate


HEARTBEATING_WORKER = r'''
import time
from hfss_optimization_agent.harness.process_supervisor import worker_heartbeat_from_environment
with worker_heartbeat_from_environment():
    time.sleep(30)
'''


def test_kill_verification_failure_is_bounded_and_unknown(tmp_path, monkeypatch):
    runner = SupervisedProcessRunner()
    monkeypatch.setattr(runner, "_wait_empty", lambda *_args: False)
    started = time.monotonic()
    with pytest.raises(ProcessOutcomeUnknown) as unknown:
        runner.run(
            (sys.executable, "-c", HEARTBEATING_WORKER),
            cwd=tmp_path,
            environment=None,
            heartbeat_path=tmp_path / "heartbeat.json",
            policy=SupervisionPolicy(
                timeout_seconds=0.15,
                heartbeat_timeout_seconds=1.0,
                termination_grace_seconds=0.2,
                poll_interval_seconds=0.01,
            ),
        )
    assert time.monotonic() - started < 1.0
    assert unknown.value.evidence["verified_no_processes"] is False
    assert unknown.value.evidence["reason"] == "timeout"


PARENT_DEATH_WORKER = r'''
import os
import subprocess
import sys
import time
from pathlib import Path
from hfss_optimization_agent.harness.process_supervisor import worker_heartbeat_from_environment
Path(sys.argv[1]).write_text(str(os.getpid()), encoding="utf-8")
with worker_heartbeat_from_environment():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    Path(sys.argv[2]).write_text(str(child.pid), encoding="utf-8")
    time.sleep(30)
'''


PARENT_DEATH_SUPERVISOR = r'''
import os
import sys
import threading
import time
from pathlib import Path
from hfss_optimization_agent.harness.process_supervisor import SupervisedProcessRunner, SupervisionPolicy
root = Path(sys.argv[1])
worker_pid = root / "worker.pid"
child_pid = root / "child.pid"
worker_code = sys.argv[2]
def supervise():
    SupervisedProcessRunner().run(
        (sys.executable, "-c", worker_code, str(worker_pid), str(child_pid)),
        cwd=root,
        environment=None,
        heartbeat_path=root / "heartbeat.json",
        policy=SupervisionPolicy(
            timeout_seconds=30.0,
            heartbeat_timeout_seconds=2.0,
            termination_grace_seconds=1.0,
            poll_interval_seconds=0.02,
        ),
    )
threading.Thread(target=supervise, daemon=True).start()
deadline = time.monotonic() + 8.0
while (not worker_pid.exists() or not child_pid.exists()) and time.monotonic() < deadline:
    time.sleep(0.02)
if not worker_pid.exists() or not child_pid.exists():
    os._exit(92)
os._exit(91)
'''


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object parent-death contract")
def test_parent_death_closes_job_and_leaves_no_worker_or_child(tmp_path):
    completed = subprocess.run(
        (
            sys.executable,
            "-c",
            PARENT_DEATH_SUPERVISOR,
            str(tmp_path),
            PARENT_DEATH_WORKER,
        ),
        cwd=tmp_path,
        timeout=12.0,
        check=False,
    )
    assert completed.returncode == 91
    worker_pid = int((tmp_path / "worker.pid").read_text(encoding="utf-8"))
    child_pid = int((tmp_path / "child.pid").read_text(encoding="utf-8"))
    deadline = time.monotonic() + 3.0
    while (
        FileLicenseLock.pid_is_alive(worker_pid)
        or FileLicenseLock.pid_is_alive(child_pid)
    ) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert FileLicenseLock.pid_is_alive(worker_pid) is False
    assert FileLicenseLock.pid_is_alive(child_pid) is False


def _unknown_core(tmp_path):
    current = create_comparison_state(
        task_id="lock-reconciliation",
        run_id="run:lock-reconciliation",
        comparison_context_id="context:lock-reconciliation",
        baseline_parameters=supplied_baseline_candidate(),
        created_at="2026-08-24T00:00:00+00:00",
    )
    core = HarnessCore(
        store=RunStore(tmp_path / ".runstore" / "runstore.sqlite3"),
        artifacts=ArtifactStore(tmp_path, current["manifest"].task_id),
        settings=HarnessSettings(
            budget_limit=10,
            operation_costs={"hfss": 1},
            approvals=(
                ApprovalGrant(
                    "lock-operator",
                    RECONCILIATION_APPROVAL_SCOPE,
                    "operator",
                ),
            ),
        ),
    )
    core.ensure_run(current["manifest"])
    request = OperationRequest(
        run_id=current["manifest"].run_id,
        kind="hfss",
        subject_id="candidate",
        idempotency_key="unknown-lock-action",
        payload={"candidate_id": "candidate"},
        result_role="hfss_result",
        estimated_cost=1,
        ambiguity_on_exception=True,
    )
    with pytest.raises(OperationUnknownError):
        core.execute(
            request,
            lambda: (_ for _ in ()).throw(RuntimeError("unverified descendant")),
            decoder=lambda value: value,
        )
    return core, request


def test_quarantined_lock_requires_accepted_exact_reconciliation_and_is_archived(tmp_path):
    core, operation_request = _unknown_core(tmp_path)
    lock_config = LicenseLockConfig(
        path=tmp_path / "aedt.lock", acquire_timeout_seconds=0.0
    )
    lock = FileLicenseLock(lock_config)
    lock.acquire()
    lock.quarantine(
        "injected residual",
        evidence={"active_processes": 1, "verified_no_processes": False},
    )
    raw = lock_config.path.read_bytes()
    marker = json.loads(raw.decode("utf-8"))
    with pytest.raises(HFSSLicenseLockError, match="accepted operation reconciliation"):
        reconcile_quarantined_lock(
            lock_config, store=core.store, operation_id=operation_request.operation_id
        )

    operation = core.store.get_operation(operation_request.operation_id)
    now = datetime.now(timezone.utc)
    decision = ReconciliationRequest(
        schema_version=RECONCILIATION_SCHEMA_VERSION,
        reconciliation_id="reconcile:lock:verified-empty",
        run_id=operation_request.run_id,
        operation_id=operation_request.operation_id,
        attempt_id=operation.attempt_id,
        approval_id="lock-operator",
        issued_at=(now - timedelta(seconds=1)).isoformat(),
        expires_at=(now + timedelta(minutes=5)).isoformat(),
        resolution=ReconciliationResolution.CONFIRMED_FAILED,
        reason="operator verified the AEDT process tree is empty",
        evidence=FrozenMap.from_mapping(
            {
                "lock_sha256": hashlib.sha256(raw).hexdigest(),
                "lock_token": marker["token"],
                "verified_no_processes": True,
            }
        ),
    )
    core.reconcile_unknown(decision)
    archive = reconcile_quarantined_lock(
        lock_config, store=core.store, operation_id=operation_request.operation_id
    )
    assert reconcile_quarantined_lock(
        lock_config,
        store=core.store,
        operation_id=operation_request.operation_id,
    ) == archive
    assert lock_config.path.exists() is False
    assert archive.exists()
    archived = json.loads(archive.read_text(encoding="utf-8"))
    assert archived["status"] == "RECONCILED"
    assert archived["reconciliation_id"] == decision.reconciliation_id

    replacement = FileLicenseLock(lock_config)
    replacement.acquire()
    replacement.release()
    assert lock_config.path.exists() is False
