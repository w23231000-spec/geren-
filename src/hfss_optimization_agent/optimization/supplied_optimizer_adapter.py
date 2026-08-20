"""Batch adapter around the supplied multi-objective optimizer's artifact-producing API."""

import csv
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..core.models import CandidateParameters, OptimizationBatch, SParameterResult
from .intent import OptimizationObjective
from ..harness.errors import OptimizerError
from ..interfaces.batch_optimizer import BatchOptimizerInterface
from .supplied_loader import import_supplied_module


@dataclass(frozen=True, slots=True)
class SuppliedOptimizerConfig:
    source_root: Path
    output_root: Path
    quick: bool = False
    debug: bool = False


class SuppliedBatchOptimizerAdapter(BatchOptimizerInterface):
    def __init__(self, config: SuppliedOptimizerConfig) -> None:
        self.config = config

    def _validate_baseline(self, baseline: CandidateParameters) -> None:
        path = Path(self.config.source_root) / "config" / "parameters.csv"
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        expected = {
            row["name"]: float(row["baseline"]) * float(row["scale_to_model"])
            for row in rows
            if row.get("active", "").strip().lower() in {"true", "1", "yes", "y"}
        }
        if set(expected) != set(baseline.values):
            raise OptimizerError("Supplied optimizer and workflow baseline parameter names differ")
        mismatched = [
            name
            for name, value in expected.items()
            if abs(value - baseline.values[name]) > max(abs(value), 1.0) * 1e-12
        ]
        if mismatched:
            raise OptimizerError(f"Supplied optimizer baseline values differ for {mismatched}")

    def optimize(
        self,
        *,
        baseline: CandidateParameters,
        baseline_sparameters: SParameterResult,
        target_specification: Mapping[str, float],
        optimization_objective: OptimizationObjective | None = None,
    ) -> OptimizationBatch:
        try:
            self._validate_baseline(baseline)
            root = Path(self.config.source_root).resolve()
            matplotlib_config = Path(self.config.output_root).resolve() / ".matplotlib"
            matplotlib_config.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_config))
            module = import_supplied_module(root, "app.run")
            run_directory = Path(
                module.execute(
                    config_path=root / "config" / "config.toml",
                    parameters_path=root / "config" / "parameters.csv",
                    objectives_path=root / "config" / "objectives.csv",
                    constraints_path=root / "config" / "constraints.csv",
                    models_path=root / "config" / "models.csv",
                    output_root=self.config.output_root,
                    quick=self.config.quick,
                    debug=self.config.debug,
                )
            )
            summary_path = run_directory / "00_summary.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if summary.get("status") not in {"completed", "success"}:
                raise OptimizerError(str(summary.get("error", "supplied optimizer failed")))
            recommended = summary["recommended_parameters"]["model_units"]
            candidate_id = str(summary["recommended_point_id"])
            candidate = CandidateParameters(
                candidate_id=candidate_id,
                iteration=1,
                values={name: float(value) for name, value in recommended.items()},
                metadata={
                    "source": "supplied-batch-optimizer",
                    "run_directory": str(run_directory),
                    "calibration_status": "uncalibrated",
                },
            )
            artifacts = [str(path) for path in sorted(run_directory.iterdir()) if path.is_file()]
            return OptimizationBatch(
                run_id=run_directory.name,
                success=True,
                candidates=[candidate],
                recommended_candidate_id=candidate_id,
                evaluations=int(summary.get("algorithm", {}).get("evaluations", 0)),
                metadata={
                    "validation_status": summary.get("validation_status", "surrogate_only"),
                    "baseline_provider": baseline_sparameters.provider,
                    "target_specification": dict(target_specification),
                    "optimization_objective": optimization_objective.to_dict() if optimization_objective else None,
                    "pareto_points": summary.get("algorithm", {}).get("pareto_points"),
                },
                artifact_paths=artifacts,
            )
        except Exception as exc:
            if isinstance(exc, OptimizerError):
                raise
            raise OptimizerError(f"Supplied batch optimizer failed: {exc}") from exc
