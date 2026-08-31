"""Contract for high-fidelity validation providers."""

from abc import ABC, abstractmethod

from ..core.models import CandidateParameters, HFSSResult


class HFSSInterface(ABC):
    @abstractmethod
    def run(self, candidate: CandidateParameters) -> HFSSResult:
        """Validate one candidate and return curves plus metrics."""

