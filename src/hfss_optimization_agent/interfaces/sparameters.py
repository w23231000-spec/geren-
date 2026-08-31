"""Contract for deterministic fast S-parameter calculation providers."""

from abc import ABC, abstractmethod

from ..core.models import CandidateParameters, SParameterResult


class SParameterInterface(ABC):
    @abstractmethod
    def run(self, candidate: CandidateParameters) -> SParameterResult:
        """Calculate one candidate response without making workflow decisions."""
