"""Deterministic complex two-port surrogate used to verify workflow semantics offline."""

import cmath
from collections.abc import Mapping

from ..core.models import CandidateParameters, ComplexSParameters, SParameterResult
from ..interfaces.sparameters import SParameterInterface


class DeterministicSurrogate(SParameterInterface):
    def __init__(
        self,
        baseline_values: Mapping[str, float],
        frequencies_hz: tuple[float, ...] = (1e9, 2e9, 3e9),
    ) -> None:
        self.baseline_values = {name: float(value) for name, value in baseline_values.items()}
        self.frequencies_hz = tuple(float(value) for value in frequencies_hz)
        self.call_count = 0

    def run(self, candidate: CandidateParameters) -> SParameterResult:
        self.call_count += 1
        if set(candidate.values) != set(self.baseline_values):
            return SParameterResult(
                candidate_id=candidate.candidate_id,
                success=False,
                provider="deterministic-surrogate",
                model_version="mock-v1",
                error="candidate parameters do not match the configured baseline contract",
            )
        ratios = [candidate.values[name] / value for name, value in self.baseline_values.items()]
        quality = sum(ratios) / len(ratios) - 1.0
        matrices: list[list[list[complex]]] = []
        for index, _frequency in enumerate(self.frequencies_hz):
            phase = 0.08 * index
            s11 = (0.30 - 0.08 * quality) * cmath.exp(1j * phase)
            s21 = (0.82 + 0.05 * quality) * cmath.exp(-1j * phase)
            matrices.append([[s11, s21], [s21, s11]])
        response = ComplexSParameters.from_complex_matrices(
            frequency_hz=list(self.frequencies_hz),
            matrices=matrices,
        )
        return SParameterResult(
            candidate_id=candidate.candidate_id,
            success=True,
            response=response,
            metrics={
                "screening_score": round(quality, 12),
                "worst_s11_magnitude": max(
                    abs(complex(real[0][0], imag[0][0]))
                    for real, imag in zip(response.real, response.imag)
                ),
            },
            provider="deterministic-surrogate",
            model_version="mock-v1",
            calibration_status="mock",
        )
