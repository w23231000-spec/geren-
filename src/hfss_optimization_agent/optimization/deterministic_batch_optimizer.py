"""Deterministic batch optimizer used to exercise the confirmed business workflow offline."""

from ..core.models import CandidateParameters, OptimizationBatch
from ..interfaces.batch_optimizer import BatchOptimizerInterface
from .contracts import OptimizerRequest


class DeterministicBatchOptimizer(BatchOptimizerInterface):
    def __init__(self, factors: tuple[float, ...] = (1.02, 1.05)) -> None:
        if not factors or any(factor <= 0.0 for factor in factors):
            raise ValueError("At least one positive deterministic factor is required")
        self.factors = factors
        self.call_count = 0

    def optimize(
        self,
        *,
        request: OptimizerRequest,
    ) -> OptimizationBatch:
        self.call_count += 1
        baseline = request.baseline
        prefix = "optimized" if request.iteration == 0 else f"optimized-r{request.iteration}"
        candidates = [
            CandidateParameters(
                candidate_id=f"{prefix}-{index:03d}",
                iteration=request.iteration + 1,
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
                "baseline_sparameter_provider": request.baseline_sparameters.provider,
                "target_specification": request.target_specification,
                "optimization_objective": request.optimization_objective.to_dict(),
                "optimizer_request_digest": request.digest,
                "effective_objective_digest": request.effective_objective.digest,
                "effective_objective": request.effective_objective.to_dict(),
                "calibration_status": "mock",
            },
        )
