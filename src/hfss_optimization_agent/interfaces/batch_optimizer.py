"""Contract for batch optimizers that return a Pareto/recommended candidate set."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..core.models import OptimizationBatch

if TYPE_CHECKING:
    from ..optimization.contracts import OptimizerRequest


class BatchOptimizerInterface(ABC):
    @abstractmethod
    def optimize(
        self,
        *,
        request: "OptimizerRequest",
    ) -> OptimizationBatch:
        """Run one canonical request; routing and HFSS remain outside the service."""
