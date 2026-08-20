"""Deterministic batch optimizer used to exercise the confirmed business workflow offline."""

from collections.abc import Mapping

from ..core.models import CandidateParameters, OptimizationBatch, SParameterResult
from .intent import OptimizationObjective
from ..interfaces.batch_optimizer import BatchOptimizerInterface


class DeterministicBatchOptimizer(BatchOptimizerInterface):
    def __init__(self, factors: tuple[float, ...] = (1.02, 1.05)) -> None:
        if not factors or any(factor <= 0.0 for factor in factors):
            raise ValueError("At least one positive deterministic factor is required")
        self.factors = factors
        self.call_count = 0

    def optimize(
        self,
        *,
        baseline: CandidateParameters,
        baseline_sparameters: SParameterResult,
        target_specification: Mapping[str, float],
        optimization_objective: OptimizationObjective | None = None,
    ) -> OptimizationBatch:
        self.call_count += 1
        candidates = [
            CandidateParameters(
                candidate_id=f"optimized-{index:03d}",
                iteration=1,
                values={name: value * factor for name, value in baseline.values.items()},
                metadata={
                    "source": "deterministic-batch-optimizer",
                    "factor": factor,
                    "calibration_status": "mock",
                },
            )
            for index, factor in enumerate(self.factors, start=1)
        ]
        return OptimizationBatch(
            run_id=f"deterministic-{self.call_count:03d}",
            success=True,
            candidates=candidates,
            recommended_candidate_id=candidates[-1].candidate_id,
            evaluations=len(candidates),
            metadata={
                "baseline_sparameter_provider": baseline_sparameters.provider,
                "target_specification": dict(target_specification),
                "optimization_objective": optimization_objective.to_dict() if optimization_objective else None,
                "calibration_status": "mock",
            },
        )
