"""Writes task, baseline, optimization, candidate, calibration and Best artifacts."""

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ArtifactStore:
    def __init__(self, root: Path, task_id: str) -> None:
        self.task_dir = Path(root) / task_id

    def initialize(self, metadata: dict[str, Any]) -> None:
        self.task_dir.mkdir(parents=True, exist_ok=True)
        payload = {"task_id": self.task_dir.name, "created_at": datetime.now(timezone.utc).isoformat(), **metadata}
        self._write(self.task_dir / "task.json", payload)

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

    def write_best(self, candidate: Any, result: Any, score: float) -> None:
        self._write(self.task_dir / "best" / "candidate.json", candidate)
        self._write(self.task_dir / "best" / "hfss_result.json", result)
        self._write(self.task_dir / "best" / "summary.json", {"score": score})

    def _write(self, path: Path, value: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(value) if is_dataclass(value) else value
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        return path
