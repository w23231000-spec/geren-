"""Offline deterministic HFSS-shaped simulator that never accesses Ansys or AEDT."""

from collections.abc import Mapping

from ..core.models import CandidateParameters, HFSSResult
from ..interfaces.hfss import HFSSInterface


class MockHFSS(HFSSInterface):
    def __init__(
        self,
        frequencies: tuple[float, ...] = (1.0, 2.0, 3.0),
        baseline_values: Mapping[str, float] | None = None,
    ) -> None:
        self.frequencies = frequencies
        self.baseline_values = (
            {name: float(value) for name, value in baseline_values.items()}
            if baseline_values is not None
            else None
        )
        self.call_count = 0

    def run(self, candidate: CandidateParameters) -> HFSSResult:
        self.call_count += 1
        if self.baseline_values is not None:
            if set(candidate.values) != set(self.baseline_values):
                return HFSSResult(
                    candidate_id=candidate.candidate_id,
                    success=False,
                    error="candidate parameters do not match the configured MockHFSS baseline",
                )
            ratios = [
                candidate.values[name] / value
                for name, value in self.baseline_values.items()
            ]
            quality = sum(ratios) / len(ratios) - 1.0
            score = round(quality, 12)
            s11 = [
                -10.0 - 100.0 * quality + abs(freq - 2.0)
                for freq in self.frequencies
            ]
        else:
            score = round(
                sum(candidate.values.values()) / max(len(candidate.values), 1) - 1.0,
                12,
            )
            quality = score
            s11 = [
                -15.0 - 2.0 * score + abs(freq - 2.0)
                for freq in self.frequencies
            ]
        s21 = [
            -1.2 + quality - 0.1 * abs(freq - 2.0)
            for freq in self.frequencies
        ]
        return HFSSResult(
            candidate_id=candidate.candidate_id,
            success=True,
            frequency=list(self.frequencies),
            s_parameters={"s11_db": s11, "s21_db": s21},
            metrics={"score": score, "min_s11_db": min(s11)},
            project_path=None,
        )
