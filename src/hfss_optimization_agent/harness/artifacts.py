"""Immutable Harness artifacts plus the retained Phase-1 compatibility writers."""

import json
import hashlib
import mimetypes
import os
import re
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..domain.canonical_json import canonical_dumps
from .run_store import ArtifactReceipt


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def _safe_segment(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_SEGMENT.fullmatch(value):
        raise ValueError(f"{name} must be one safe path segment")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{name} must not escape the artifact layout")
    return value


class ArtifactStore:
    def __init__(self, root: Path, task_id: str) -> None:
        safe_task_id = _safe_segment(task_id, "task_id")
        artifact_root = Path(root).resolve()
        self.root = artifact_root
        self.task_dir = artifact_root / safe_task_id
        if self.task_dir.parent != artifact_root:
            raise ValueError("task artifact path escapes the configured root")

    def write_immutable(
        self,
        *,
        run_id: str,
        operation_id: str,
        attempt_id: str,
        role: str,
        value: Any,
    ) -> tuple[ArtifactReceipt, Path]:
        """Create a content-addressed result once; existing bytes are never replaced."""

        operation_id = _safe_segment(operation_id, "operation_id")
        attempt_id = _safe_segment(attempt_id, "attempt_id")
        role = _safe_segment(role, "artifact role")
        encoded = canonical_dumps(value).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        # Keep the immutable hierarchy Windows-path-safe while the ledger retains
        # the full operation/attempt/digest identities.
        operation_component = operation_id.rsplit("_", 1)[-1][:12]
        attempt_component = attempt_id.rsplit("_", 1)[-1][:12]
        directory = self.task_dir / "artifacts" / operation_component / attempt_component
        path = directory / f"{role}.{digest[:20]}.json"
        directory.mkdir(parents=True, exist_ok=True)
        task_root = self.task_dir.resolve()
        resolved_directory = directory.resolve()
        if task_root.parent != self.root or task_root not in resolved_directory.parents:
            raise ValueError("resolved artifact directory escapes the configured root")
        temporary = directory / f".{role}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != encoded:
                    raise RuntimeError("immutable artifact path exists with different bytes")
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        relative_uri = path.relative_to(self.task_dir).as_posix()
        artifact_id = f"art_{hashlib.sha256(f'{run_id}\0{relative_uri}'.encode()).hexdigest()[:32]}"
        return (
            ArtifactReceipt(
                artifact_id=artifact_id,
                run_id=run_id,
                operation_id=operation_id,
                attempt_id=attempt_id,
                role=role,
                relative_uri=relative_uri,
                sha256=digest,
                size_bytes=len(encoded),
            ),
            path,
        )

    def write_immutable_file(
        self,
        *,
        run_id: str,
        operation_id: str,
        attempt_id: str,
        role: str,
        source_path: Path,
        media_type: str | None = None,
    ) -> tuple[ArtifactReceipt, Path]:
        """Freeze one completed provider file without ever replacing existing bytes."""

        operation_id = _safe_segment(operation_id, "operation_id")
        attempt_id = _safe_segment(attempt_id, "attempt_id")
        role = _safe_segment(role, "artifact role")
        source = Path(source_path).resolve(strict=True)
        if not source.is_file():
            raise ValueError("native artifact source must be a regular file")
        before = source.stat()
        operation_component = operation_id.rsplit("_", 1)[-1][:12]
        attempt_component = attempt_id.rsplit("_", 1)[-1][:12]
        directory = self.task_dir / "artifacts" / operation_component / attempt_component
        directory.mkdir(parents=True, exist_ok=True)
        task_root = self.task_dir.resolve()
        resolved_directory = directory.resolve()
        if task_root.parent != self.root or task_root not in resolved_directory.parents:
            raise ValueError("resolved artifact directory escapes the configured root")
        temporary = directory / f".{role}.{uuid.uuid4().hex}.tmp"
        digest = hashlib.sha256()
        size = 0
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
                for block in iter(lambda: reader.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
                    writer.write(block)
                writer.flush()
                os.fsync(writer.fileno())
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError("native artifact changed while it was being frozen")
            hexdigest = digest.hexdigest()
            suffix = source.suffix.lower()
            if not re.fullmatch(r"\.[a-z0-9]{1,12}", suffix):
                suffix = ".bin"
            path = directory / f"{role}.{hexdigest[:20]}{suffix}"
            try:
                os.link(temporary, path)
            except FileExistsError:
                existing = hashlib.sha256(path.read_bytes()).hexdigest()
                if existing != hexdigest or path.stat().st_size != size:
                    raise RuntimeError("immutable artifact path exists with different bytes")
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        relative_uri = path.relative_to(self.task_dir).as_posix()
        artifact_id = f"art_{hashlib.sha256(f'{run_id}\0{relative_uri}'.encode()).hexdigest()[:32]}"
        return (
            ArtifactReceipt(
                artifact_id=artifact_id,
                run_id=run_id,
                operation_id=operation_id,
                attempt_id=attempt_id,
                role=role,
                relative_uri=relative_uri,
                sha256=hexdigest,
                size_bytes=size,
                media_type=media_type
                or mimetypes.guess_type(source.name)[0]
                or "application/octet-stream",
            ),
            path,
        )

    def verify(self, receipt: ArtifactReceipt) -> Path:
        path = self.task_dir / Path(receipt.relative_uri)
        resolved = path.resolve()
        if self.task_dir.resolve() not in resolved.parents:
            raise ValueError("artifact receipt escapes the task directory")
        data = resolved.read_bytes()
        if len(data) != receipt.size_bytes or hashlib.sha256(data).hexdigest() != receipt.sha256:
            raise RuntimeError("immutable artifact digest verification failed")
        return resolved

    def initialize(self, metadata: dict[str, Any]) -> Path:
        self.task_dir.mkdir(parents=True, exist_ok=True)
        payload = {"task_id": self.task_dir.name, "created_at": datetime.now(timezone.utc).isoformat(), **metadata}
        return self._write(self.task_dir / "task.json", payload)

    def write_manifest(self, manifest: Any) -> Path:
        path = self.task_dir / "run_manifest.v2.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(canonical_dumps(manifest), encoding="utf-8")
        temporary.replace(path)
        return path

    def write_baseline(self, value: Any) -> Path:
        return self._write(self.task_dir / "baseline" / "hfss_result.json", value)

    def write_baseline_sparameters(self, value: Any) -> Path:
        return self._write(self.task_dir / "baseline" / "sparameter_result.json", value)

    def write_baseline_evaluation(self, value: Any) -> Path:
        return self._write(self.task_dir / "baseline" / "evaluation_result.json", value)

    def write_baseline_diagnosis(self, value: Any) -> Path:
        return self._write(self.task_dir / "baseline" / "diagnosis_result.json", value)

    def write_optimization_batch(self, value: Any) -> Path:
        return self._write(self.task_dir / "optimization" / "batch.json", value)

    def write_optimization_artifact(self, name: str, value: Any) -> Path:
        return self._write(self.task_dir / "optimization" / f"{name}.json", value)

    def write_candidate_artifact(self, name: str, value: Any) -> Path:
        return self._write(self.task_dir / "candidate" / f"{name}.json", value)

    def write_calibration_report(self, value: Any) -> Path:
        return self._write(self.task_dir / "calibration" / "report.json", value)

    def write_best(
        self,
        candidate: Any,
        result: Any,
        score: float | None,
        *,
        comparison: Any | None = None,
    ) -> None:
        self._write(self.task_dir / "best" / "candidate.json", candidate)
        self._write(self.task_dir / "best" / "hfss_result.json", result)
        summary = {"score": score}
        if comparison is not None:
            summary.update(
                promotion_classification=comparison.classification,
                promotion_reason=comparison.promotion_reason,
            )
        self._write(self.task_dir / "best" / "summary.json", summary)

    def _write(self, path: Path, value: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(value) if is_dataclass(value) else value
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        return path
