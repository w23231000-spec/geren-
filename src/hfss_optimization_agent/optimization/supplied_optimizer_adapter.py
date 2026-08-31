"""Supervised subprocess adapter for the supplied multi-objective optimizer."""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..core.models import OptimizationBatch
from ..domain.canonical_json import canonical_dumps
from ..harness.errors import OptimizerError, ProcessSupervisorError
from ..harness.process_supervisor import SupervisedProcessRunner, SupervisionPolicy
from ..harness.result_codecs import optimization_batch_from_dict
from ..interfaces.batch_optimizer import BatchOptimizerInterface
from .contracts import OptimizerRequest


@dataclass(frozen=True, slots=True)
class SuppliedOptimizerConfig:
    source_root: Path
    output_root: Path
    quick: bool = False
    debug: bool = False
    python_executable: Path | None = None
    timeout_seconds: float = 1800.0
    heartbeat_timeout_seconds: float = 15.0
    termination_grace_seconds: float = 5.0
    cancel_event: threading.Event | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0.0:
            raise ValueError("optimizer timeout must be positive")


class SuppliedBatchOptimizerAdapter(BatchOptimizerInterface):
    def __init__(self, config: SuppliedOptimizerConfig) -> None:
        self.config = config
        self._runner = SupervisedProcessRunner()

    def optimize(self, *, request: OptimizerRequest) -> OptimizationBatch:
        root = Path(self.config.source_root).resolve()
        output_root = Path(self.config.output_root).resolve()
        workspace = output_root / "worker_requests" / uuid.uuid4().hex
        workspace.mkdir(parents=True, exist_ok=False)
        request_path = workspace / "optimizer_request.json"
        response_path = workspace / "optimizer_response.json"
        heartbeat_path = workspace / "worker_heartbeat.json"
        request_path.write_text(
            canonical_dumps(request.to_dict()),
            encoding="utf-8",
        )
        package_src = Path(__file__).resolve().parents[2]
        environment = {
            "PYTHONPATH": os.pathsep.join(
                value
                for value in (str(package_src), os.environ.get("PYTHONPATH", ""))
                if value
            ),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "MPLCONFIGDIR": str(workspace / ".matplotlib"),
        }
        interpreter = (self.config.python_executable or Path(sys.executable)).resolve()
        command = [
            str(interpreter),
            "-m",
            "hfss_optimization_agent.optimization.supplied_worker",
            "--request",
            str(request_path),
            "--response",
            str(response_path),
            "--source-root",
            str(root),
            "--output-root",
            str(output_root),
        ]
        if self.config.quick:
            command.append("--quick")
        if self.config.debug:
            command.append("--debug")
        try:
            result = self._runner.run(
                command,
                cwd=workspace,
                environment=environment,
                heartbeat_path=heartbeat_path,
                policy=SupervisionPolicy(
                    timeout_seconds=self.config.timeout_seconds,
                    heartbeat_timeout_seconds=self.config.heartbeat_timeout_seconds,
                    termination_grace_seconds=self.config.termination_grace_seconds,
                ),
                cancel_event=self.config.cancel_event,
            )
        except ProcessSupervisorError as exc:
            raise OptimizerError(f"supplied optimizer worker supervision failed: {exc}") from exc
        if result.returncode != 0:
            detail = "worker did not return structured error"
            if response_path.is_file():
                try:
                    detail = str(
                        json.loads(response_path.read_text(encoding="utf-8")).get(
                            "error", detail
                        )
                    )
                except (OSError, json.JSONDecodeError):
                    pass
            raise OptimizerError(
                f"supplied optimizer worker exited {result.returncode}: {detail}"
            )
        try:
            payload = json.loads(response_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OptimizerError("supplied optimizer worker returned invalid JSON") from exc
        if payload.get("status") != "success":
            raise OptimizerError(str(payload.get("error", "supplied optimizer worker failed")))
        if payload.get("optimizer_request_digest") != request.digest:
            raise OptimizerError("optimizer worker response request digest mismatch")
        if payload.get("effective_objective_digest") != request.effective_objective.digest:
            raise OptimizerError("optimizer worker response effective objective digest mismatch")
        batch = optimization_batch_from_dict(payload["batch"])
        if batch.metadata.get("effective_objective_digest") != request.effective_objective.digest:
            raise OptimizerError("optimizer batch omitted the effective objective digest")
        worker_contract_files = (request_path, response_path, heartbeat_path)
        batch.artifact_paths = sorted(
            {
                *batch.artifact_paths,
                *(str(path) for path in worker_contract_files if path.is_file()),
            }
        )
        return batch
