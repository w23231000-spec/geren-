"""Guarded Build→Solve→Extract orchestration around an injected HFSS backend."""

import json
import math
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.models import CandidateParameters, HFSSResult
from ..harness.errors import HFSSExecutionError, HFSSProcessOutcomeUnknown, HFSSStageError
from ..harness.license_lock import FileLicenseLock, LicenseLockConfig
from ..harness.terminal import emit_stage, emit_status
from ..interfaces.hfss import HFSSInterface
from .backend import HFSSBackendInterface
from .contracts import HFSSRunContract
from .converter import convert_raw_sparameters


@dataclass(frozen=True, slots=True)
class GuardedHFSSConfig:
    workspace_root: Path
    license_lock_path: Path
    solve_timeout_seconds: float = 3600.0
    license_wait_seconds: float = 30.0
    require_process_isolation: bool = True
    preserve_failed_workspace: bool = True

    def __post_init__(self) -> None:
        if self.solve_timeout_seconds <= 0.0:
            raise ValueError("HFSS solve timeout must be positive")
        if self.license_wait_seconds < 0.0:
            raise ValueError("HFSS license wait cannot be negative")


class _Journal:
    def __init__(self, path: Path, initial: dict[str, Any]) -> None:
        self.path = path
        self.payload = initial
        self.write()

    def update(self, **changes: Any) -> None:
        self.payload.update(changes)
        self.write()

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporary.replace(self.path)


def _safe_candidate_component(candidate_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate_id).strip("._")
    if not normalized:
        raise HFSSExecutionError("Candidate ID cannot produce an empty workspace name")
    return normalized[:80]


def _db(value: complex) -> float:
    return 20.0 * math.log10(max(abs(value), 1e-300))


class GuardedHFSSAdapter(HFSSInterface):
    """Reusable orchestration; only the injected backend may know how AEDT is accessed."""

    def __init__(
        self,
        *,
        backend: HFSSBackendInterface,
        contract: HFSSRunContract,
        config: GuardedHFSSConfig,
    ) -> None:
        self.backend = backend
        self.contract = contract
        self.config = config

    def _workspace(self, candidate: CandidateParameters) -> Path:
        root = self.config.workspace_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        workspace = root / _safe_candidate_component(candidate.candidate_id) / uuid.uuid4().hex[:12]
        workspace.mkdir(parents=True, exist_ok=False)
        if root not in workspace.resolve().parents:
            raise HFSSExecutionError("Resolved HFSS workspace escaped its configured root")
        return workspace

    @staticmethod
    def _run_name(candidate: CandidateParameters) -> str:
        if candidate.candidate_id == "baseline":
            return "HFSS·初始模型"
        return f"HFSS·优化模型 {candidate.candidate_id}"

    def run(self, candidate: CandidateParameters) -> HFSSResult:
        workspace = self._workspace(candidate)
        run_name = self._run_name(candidate)
        emit_stage(run_name, 1, 5, "准备独立工作目录", detail=str(workspace))
        journal = _Journal(
            workspace / "run_journal.json",
            {
                "candidate_id": candidate.candidate_id,
                "contract_id": self.contract.contract_id,
                "backend": self.backend.backend_name,
                "status": "created",
                "stage": "created",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "process_isolated": self.backend.process_isolated,
            },
        )
        project_path: str | None = None
        composite_request_digest: str | None = None
        builder_attestation_digest: str | None = None
        started = time.monotonic()
        lock = FileLicenseLock(
            LicenseLockConfig(
                path=self.config.license_lock_path,
                acquire_timeout_seconds=self.config.license_wait_seconds,
            )
        )
        try:
            if self.config.require_process_isolation and not self.backend.process_isolated:
                raise HFSSStageError(
                    "Configured HFSS backend does not guarantee worker-process isolation"
                )
            journal.update(stage="builder_attestation")
            self.backend.preflight(candidate, self.contract, workspace)
            journal.update(stage="waiting_for_license", status="running")
            emit_stage(run_name, 2, 5, "等待 HFSS 许可")
            with lock:
                try:
                    if self.backend.supports_composite:
                        journal.update(stage="composite_worker")
                        emit_stage(run_name, 3, 5, "启动受监管复合 Worker")
                        composite_started = time.monotonic()
                        composite = self.backend.run_composite(
                            candidate,
                            workspace,
                            self.contract,
                            solve_timeout_seconds=self.config.solve_timeout_seconds,
                        )
                        built = composite.built
                        solved = composite.solved
                        raw = composite.raw
                        composite_request_digest = composite.request_digest
                        builder_attestation_digest = composite.builder_attestation_digest
                        solve_elapsed = time.monotonic() - composite_started
                        project_path = built.project_path
                        journal.update(
                            stage="extract",
                            project=asdict(built),
                            solve=asdict(solved),
                            composite_seconds=solve_elapsed,
                            composite_request_digest=composite.request_digest,
                            builder_attestation_digest=composite.builder_attestation_digest,
                        )
                        emit_stage(run_name, 5, 5, "复合 Worker 已导出复数 S 参数")
                    else:
                        journal.update(stage="build")
                        emit_stage(run_name, 3, 5, "创建 HFSS 工程")
                        built = self.backend.build(candidate, workspace, self.contract)
                        project_path = built.project_path
                        journal.update(stage="solve", project=asdict(built))
                        emit_stage(
                            run_name,
                            4,
                            5,
                            "求解目标设计",
                            detail=f"仅求解 {self.contract.design_name}",
                        )
                        solve_started = time.monotonic()
                        solved = self.backend.solve(
                            built,
                            self.contract,
                            timeout_seconds=self.config.solve_timeout_seconds,
                        )
                        solve_elapsed = time.monotonic() - solve_started
                        if solve_elapsed > self.config.solve_timeout_seconds:
                            raise HFSSStageError(
                                f"HFSS backend exceeded solve timeout: {solve_elapsed:.3f}s"
                            )
                        journal.update(
                            stage="extract", solve=asdict(solved), solve_seconds=solve_elapsed
                        )
                        emit_stage(run_name, 5, 5, "导出复数 S 参数")
                        raw = self.backend.extract(solved, self.contract)
                    complex_response = convert_raw_sparameters(raw, self.contract)
                except HFSSProcessOutcomeUnknown as exc:
                    lock.quarantine(str(exc), evidence=exc.evidence)
                    journal.update(
                        stage="quarantined",
                        status="unknown",
                        quarantine_reason=str(exc),
                        quarantine_evidence=exc.evidence,
                    )
                    raise
                finally:
                    if not lock.quarantined:
                        journal.update(stage="release_backend")
                    self.backend.close()

            matrices = [
                [
                    [complex(real, imag) for real, imag in zip(real_row, imag_row)]
                    for real_row, imag_row in zip(real_matrix, imag_matrix)
                ]
                for real_matrix, imag_matrix in zip(
                    complex_response.real, complex_response.imag
                )
            ]
            s11_db = [_db(matrix[0][0]) for matrix in matrices]
            s21_db = [_db(matrix[1][0]) for matrix in matrices]
            worst_s11 = max(abs(matrix[0][0]) for matrix in matrices)
            finished_at = datetime.now(timezone.utc).isoformat()
            journal.update(
                stage="complete",
                status="completed",
                completed_at=finished_at,
                elapsed_seconds=time.monotonic() - started,
            )
            emit_status(run_name, "完成")
            backend_artifacts = [
                str(value)
                for key, value in raw.metadata.items()
                if key.endswith("_path") and isinstance(value, str)
            ]
            return HFSSResult(
                candidate_id=candidate.candidate_id,
                success=True,
                frequency=list(complex_response.frequency_hz),
                s_parameters={"s11_db": s11_db, "s21_db": s21_db},
                metrics={
                    "score": -worst_s11,
                    "worst_s11_magnitude": worst_s11,
                    "minimum_return_loss_db": -max(s11_db),
                    "maximum_s11_db": max(s11_db),
                    "minimum_s11_db": min(s11_db),
                    "maximum_s21_db": max(s21_db),
                    "minimum_s21_db": min(s21_db),
                },
                project_path=project_path,
                artifact_paths=[str(journal.path), str(workspace), *backend_artifacts],
                complex_response=complex_response,
                execution_metadata={
                    "contract_id": self.contract.contract_id,
                    "backend": self.backend.backend_name,
                    "workspace": str(workspace),
                    "process_isolated": self.backend.process_isolated,
                    "validation_status": "hfss_backend_result",
                    "backend_metadata": dict(raw.metadata),
                    "composite_request_digest": composite_request_digest,
                    "builder_attestation_digest": builder_attestation_digest,
                    "comparison_context_id": self.contract.metadata.get("comparison_context_id"),
                },
            )
        except Exception as exc:
            emit_status(run_name, "失败", detail=f"{type(exc).__name__}: {exc}")
            journal_error: str | None = None
            try:
                outcome_unknown = isinstance(exc, HFSSProcessOutcomeUnknown)
                journal.update(
                    stage="quarantined" if outcome_unknown else "failed",
                    status="unknown" if outcome_unknown else "failed",
                    failed_at=datetime.now(timezone.utc).isoformat(),
                    elapsed_seconds=time.monotonic() - started,
                    error=f"{type(exc).__name__}: {exc}",
                    preserve_failed_workspace=self.config.preserve_failed_workspace,
                )
            except (OSError, TypeError, ValueError) as journal_exc:
                journal_error = f"{type(journal_exc).__name__}: {journal_exc}"
            return HFSSResult(
                candidate_id=candidate.candidate_id,
                success=False,
                project_path=project_path,
                artifact_paths=[str(journal.path), str(workspace)],
                error=f"{type(exc).__name__}: {exc}",
                execution_metadata={
                    "contract_id": self.contract.contract_id,
                    "backend": self.backend.backend_name,
                    "workspace": str(workspace),
                    "process_isolated": self.backend.process_isolated,
                    "validation_status": "failed",
                    "physical_outcome": (
                        "UNKNOWN"
                        if isinstance(exc, HFSSProcessOutcomeUnknown)
                        else "FAILED"
                    ),
                    "journal_error": journal_error,
                    "composite_request_digest": composite_request_digest,
                    "builder_attestation_digest": builder_attestation_digest,
                    "comparison_context_id": self.contract.metadata.get("comparison_context_id"),
                },
            )
