"""Contract for deterministic comparison services."""

from abc import ABC, abstractmethod
from typing import Mapping

from ..core.models import EvaluationResult


class EvaluatorInterface(ABC):
    @abstractmethod
    def evaluate(
        self,
        *,
        candidate_id: str,
        baseline_metrics: Mapping[str, float],
        current_metrics: Mapping[str, float],
        target_specification: Mapping[str, float],
    ) -> EvaluationResult:
        """Compare derived metrics without inspecting workflow state."""
