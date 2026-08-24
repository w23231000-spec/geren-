"""JSON subprocess protocol that provides hard timeouts and process isolation to HFSS workers."""

import json
import os
import shutil
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..core.models import CandidateParameters
from ..harness.errors import (
    HFSSProcessOutcomeUnknown,
    HFSSStageError,
    ProcessOutcomeUnknown,
    ProcessSupervisorError,
)
from ..harness.process_supervisor import SupervisedProcessRunner, SupervisionPolicy
from .backend import (
    BuiltProject,
    CompositeHFSSResult,
    HFSSBackendInterface,
    RawSParameterData,
    SolvedProject,
)
from .contracts import (
    BuilderAttestation,
    HFSSCompositeRequest,
    HFSSRunContract,
    verify_builder_attestation,
)


@dataclass(frozen=True, slots=True)
class JsonWorkerConfig:
    """A shell-free command prefix for a future separately deployed HFSS worker."""

    command_prefix: tuple[str, ...]
    build_timeout_seconds: float = 300.0
    extract_timeout_seconds: float = 120.0
    environment: dict[str, str] | None = None
    worker_options: dict[str, Any] | None = None
    builder_attestation: BuilderAttestation | None = None
    heartbeat_timeout_seconds: float = 15.0
    termination_grace_seconds: float = 5.0
    cancel_event: threading.Event | None = None

    def __post_init__(self) -> None:
        if not self.command_prefix or any(not value for value in self.command_prefix):
            raise ValueError("Worker command prefix cannot be empty")
        if self.build_timeout_seconds <= 0.0 or self.extract_timeout_seconds <= 0.0:
            raise ValueError("Worker stage timeouts must be positive")
        if self.heartbeat_timeout_seconds <= 0.0 or self.termination_grace_seconds <= 0.0:
            raise ValueError("Worker heartbeat/termination bounds must be positive")


class JsonSubprocessHFSSBackend(HFSSBackendInterface):
    """Runs each stage in a child process; it contains no AEDT/PyAEDT implementation."""

    backend_name = "json-subprocess-hfss-worker"
    process_isolated = True
    supports_composite = True

    def __init__(self, config: JsonWorkerConfig) -> None:
        self.config = config
        self._workspace: Path | None = None
        self._runner = SupervisedProcessRunner()
        self.supports_composite = config.builder_attestation is not None
        self._attested_builder_root: Path | None = None

    def preflight(
        self,
        candidate: CandidateParameters,
        contract: HFSSRunContract,
        workspace: Path | None = None,
    ) -> None:
        del candidate
        attestation = self.config.builder_attestation
        if attestation is None:
            return
        if attestation.builder_id != contract.builder_id:
            raise HFSSStageError("Builder attestation identity differs from HFSS contract")
        options = self.config.worker_options or {}
        root = Path(str(options.get("builder_source_root", ""))).resolve()
        verify_builder_attestation(root, attestation)
        if workspace is None:
            raise HFSSStageError("attested Builder preflight requires an isolated workspace")
        snapshot = workspace.resolve() / "builder_snapshot"
        snapshot.mkdir(parents=True, exist_ok=False)
        for relative, expected_digest in attestation.files:
            source = root / Path(relative)
            target = snapshot / Path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            # Re-read through the ordinary attestation verifier after every copy
            # has completed; a concurrent source edit cannot change the snapshot.
            if not expected_digest:
                raise HFSSStageError("Builder attestation contains an empty file digest")
        verify_builder_attestation(snapshot, attestation)
        self._attested_builder_root = snapshot

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
        request_payload = dict(payload)
        request_payload.setdefault("worker_options", dict(self.config.worker_options or {}))
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
        try:
            supervised = self._runner.run(
                command,
                cwd=self._workspace,
                environment=environment,
                heartbeat_path=self._workspace / f"{stage_code}_{token}_heartbeat.json",
                policy=SupervisionPolicy(
                    timeout_seconds=timeout_seconds,
                    heartbeat_timeout_seconds=self.config.heartbeat_timeout_seconds,
                    termination_grace_seconds=self.config.termination_grace_seconds,
                ),
                cancel_event=self.config.cancel_event,
            )
        except ProcessOutcomeUnknown as exc:
            raise HFSSProcessOutcomeUnknown(
                f"HFSS worker stage {stage!r} process outcome is UNKNOWN: {exc}",
                evidence=exc.evidence,
            ) from exc
        except ProcessSupervisorError as exc:
            raise HFSSStageError(f"HFSS worker stage {stage!r} supervision failed: {exc}") from exc
        if supervised.returncode != 0:
            detail = ""
            if response_path.is_file():
                try:
                    detail = str(json.loads(response_path.read_text(encoding="utf-8")).get("error", ""))
                except (OSError, json.JSONDecodeError):
                    detail = ""
            raise HFSSStageError(
                f"HFSS worker stage {stage!r} exited {supervised.returncode}: {detail or 'see worker output'}"
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

    def run_composite(
        self,
        candidate: CandidateParameters,
        workspace: Path,
        contract: HFSSRunContract,
        *,
        solve_timeout_seconds: float,
    ) -> CompositeHFSSResult:
        self._workspace = workspace.resolve()
        attestation = self.config.builder_attestation
        if attestation is None:
            raise HFSSStageError("HFSS composite execution requires Builder attestation")
        if self._attested_builder_root is None:
            raise HFSSStageError("Builder snapshot was not prepared before license acquisition")
        worker_options = dict(self.config.worker_options or {})
        worker_options["builder_source_root"] = str(self._attested_builder_root)
        request = HFSSCompositeRequest(
            schema_version="hfss-composite-request/1.0",
            candidate=candidate.to_dict(),
            contract=contract.to_dict(),
            workspace=str(self._workspace),
            builder_attestation=attestation,
            worker_options=worker_options,
        )
        response = self._invoke(
            "composite",
            request.to_dict(),
            timeout_seconds=(
                self.config.build_timeout_seconds
                + solve_timeout_seconds
                + self.config.extract_timeout_seconds
            ),
        )
        if response.get("request_digest") != request.digest:
            raise HFSSStageError("HFSS composite response request digest mismatch")
        if response.get("builder_attestation_digest") != attestation.source_digest:
            raise HFSSStageError("HFSS composite response Builder attestation mismatch")
        built_raw = response["built"]
        solved_raw = response["solved"]
        raw = response["raw"]
        return CompositeHFSSResult(
            built=BuiltProject(
                project_path=str(built_raw["project_path"]),
                design_name=str(built_raw["design_name"]),
                metadata=dict(built_raw.get("metadata", {})),
            ),
            solved=SolvedProject(
                project_path=str(solved_raw["project_path"]),
                design_name=str(solved_raw["design_name"]),
                solution_id=str(solved_raw["solution_id"]),
                metadata=dict(solved_raw.get("metadata", {})),
            ),
            raw=RawSParameterData(
                frequency_hz=[float(value) for value in raw["frequency_hz"]],
                first=raw["first"],
                second=raw["second"],
                representation=str(raw["representation"]),
                port_order=tuple(raw["port_order"]),
                reference_impedance_ohm=float(raw["reference_impedance_ohm"]),
                metadata=dict(raw.get("metadata", {})),
            ),
            request_digest=request.digest,
            builder_attestation_digest=attestation.source_digest,
        )

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
