"""Contract for batch optimizers that return a Pareto/recommended candidate set."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from ..core.models import CandidateParameters, OptimizationBatch, SParameterResult
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..optimization.intent import OptimizationObjective


class BatchOptimizerInterface(ABC):
    @abstractmethod
    def optimize(
        self,
        *,
        baseline: CandidateParameters,
        baseline_sparameters: SParameterResult,
        target_specification: Mapping[str, float],
        optimization_objective: OptimizationObjective | None = None,
    ) -> OptimizationBatch:
        """Run one optimization batch; routing and HFSS remain outside the service."""
