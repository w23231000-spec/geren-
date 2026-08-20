"""JSON subprocess protocol that provides hard timeouts and process isolation to HFSS workers."""

import json
import os
import signal
import subprocess
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..core.models import CandidateParameters
from ..harness.errors import HFSSStageError
from .backend import BuiltProject, HFSSBackendInterface, RawSParameterData, SolvedProject
from .contracts import HFSSRunContract


@dataclass(frozen=True, slots=True)
class JsonWorkerConfig:
    """A shell-free command prefix for a future separately deployed HFSS worker."""

    command_prefix: tuple[str, ...]
    build_timeout_seconds: float = 300.0
    extract_timeout_seconds: float = 120.0
    environment: dict[str, str] | None = None
    worker_options: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.command_prefix or any(not value for value in self.command_prefix):
            raise ValueError("Worker command prefix cannot be empty")
        if self.build_timeout_seconds <= 0.0 or self.extract_timeout_seconds <= 0.0:
            raise ValueError("Worker stage timeouts must be positive")


class JsonSubprocessHFSSBackend(HFSSBackendInterface):
    """Runs each stage in a child process; it contains no AEDT/PyAEDT implementation."""

    backend_name = "json-subprocess-hfss-worker"
    process_isolated = True

    def __init__(self, config: JsonWorkerConfig) -> None:
        self.config = config
        self._workspace: Path | None = None

    def _invoke(
        self,
        stage: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if self._workspace is None:
            raise HFSSStageError("Worker workspace is not initialized")
        token = uuid.uuid4().hex[:8]
        stage_code = {"build": "b", "solve": "s", "extract": "x"}.get(stage, stage[:1])
        request_path = self._workspace / f"{stage_code}_{token}_request.json"
        response_path = self._workspace / f"{stage_code}_{token}_response.json"
        request_payload = {
            **payload,
            "worker_options": dict(self.config.worker_options or {}),
        }
        request_path.write_text(
            json.dumps(request_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        command = [
            *self.config.command_prefix,
            "--stage",
            stage,
            "--request",
            str(request_path),
            "--response",
            str(response_path),
        ]
        environment = None
        if self.config.environment is not None:
            environment = {**os.environ, **self.config.environment}
        creation_flags = 0
        start_new_session = os.name != "nt"
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            command,
            cwd=self._workspace,
            env=environment,
            stdout=None,
            stderr=None,
            shell=False,
            creationflags=creation_flags,
            start_new_session=start_new_session,
        )
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            self._terminate_process_tree(process)
            process.wait()
            raise HFSSStageError(
                f"HFSS worker stage {stage!r} exceeded {timeout_seconds:g} seconds"
            ) from exc
        if process.returncode != 0:
            detail = ""
            if response_path.is_file():
                try:
                    detail = str(json.loads(response_path.read_text(encoding="utf-8")).get("error", ""))
                except (OSError, json.JSONDecodeError):
                    detail = ""
            raise HFSSStageError(
                f"HFSS worker stage {stage!r} exited {process.returncode}: {detail or 'see worker output'}"
            )
        if not response_path.is_file():
            raise HFSSStageError(f"HFSS worker stage {stage!r} did not create a response")
        try:
            response = json.loads(response_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HFSSStageError(f"HFSS worker stage {stage!r} returned invalid JSON") from exc
        if response.get("status") != "success":
            raise HFSSStageError(
                f"HFSS worker stage {stage!r} failed: {response.get('error', 'unknown error')}"
            )
        return response

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen) -> None:
        """Best-effort termination of an exact timed-out worker and its AEDT children."""

        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                shell=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return

    def build(
        self,
        candidate: CandidateParameters,
        workspace: Path,
        contract: HFSSRunContract,
    ) -> BuiltProject:
        self._workspace = workspace.resolve()
        response = self._invoke(
            "build",
            {
                "candidate": candidate.to_dict(),
                "contract": contract.to_dict(),
                "workspace": str(self._workspace),
            },
            timeout_seconds=self.config.build_timeout_seconds,
        )
        return BuiltProject(
            project_path=str(response["project_path"]),
            design_name=str(response.get("design_name", contract.design_name)),
            metadata=dict(response.get("metadata", {})),
        )

    def solve(
        self,
        project: BuiltProject,
        contract: HFSSRunContract,
        *,
        timeout_seconds: float,
    ) -> SolvedProject:
        response = self._invoke(
            "solve",
            {"project": asdict(project), "contract": contract.to_dict()},
            timeout_seconds=timeout_seconds,
        )
        return SolvedProject(
            project_path=str(response.get("project_path", project.project_path)),
            design_name=str(response.get("design_name", project.design_name)),
            solution_id=str(response["solution_id"]),
            metadata=dict(response.get("metadata", {})),
        )

    def extract(
        self,
        solved: SolvedProject,
        contract: HFSSRunContract,
    ) -> RawSParameterData:
        response = self._invoke(
            "extract",
            {"solved": asdict(solved), "contract": contract.to_dict()},
            timeout_seconds=self.config.extract_timeout_seconds,
        )
        return RawSParameterData(
            frequency_hz=[float(value) for value in response["frequency_hz"]],
            first=response["first"],
            second=response["second"],
            representation=str(response["representation"]),
            port_order=tuple(response["port_order"]),
            reference_impedance_ohm=float(response["reference_impedance_ohm"]),
            metadata=dict(response.get("metadata", {})),
        )

    def close(self) -> None:
        self._workspace = None
