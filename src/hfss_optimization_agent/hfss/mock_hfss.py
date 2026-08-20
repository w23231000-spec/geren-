"""Offline deterministic HFSS-shaped simulator that never accesses Ansys or AEDT."""

from ..core.models import CandidateParameters, HFSSResult
from ..interfaces.hfss import HFSSInterface


class MockHFSS(HFSSInterface):
    def __init__(self, frequencies: tuple[float, ...] = (1.0, 2.0, 3.0)) -> None:
        self.frequencies = frequencies
        self.call_count = 0

    def run(self, candidate: CandidateParameters) -> HFSSResult:
        self.call_count += 1
        score = round(sum(candidate.values.values()) / max(len(candidate.values), 1) - 1.0, 12)
        s11 = [-15.0 - 2.0 * score + abs(freq - 2.0) for freq in self.frequencies]
        s21 = [-1.2 + score - 0.1 * abs(freq - 2.0) for freq in self.frequencies]
        return HFSSResult(
            candidate_id=candidate.candidate_id,
            success=True,
            frequency=list(self.frequencies),
            s_parameters={"s11_db": s11, "s21_db": s21},
            metrics={"score": score, "min_s11_db": min(s11)},
            project_path=None,
        )
