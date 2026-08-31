"""Adapter for the user-supplied nine-parameter electrical surrogate."""

import math
from dataclasses import dataclass
from pathlib import Path

from ..core.models import CandidateParameters, ComplexSParameters, SParameterResult
from ..harness.errors import SParameterCalculationError
from ..interfaces.sparameters import SParameterInterface
from ..optimization.supplied_loader import import_supplied_module


@dataclass(frozen=True, slots=True)
class SuppliedSurrogateConfig:
    source_root: Path
    frequencies_hz: tuple[float, ...]
    reference_impedance_ohm: float = 50.0
    shunt_regularization: float = 1e-8
    comparison_context_id: str | None = None
    port_order: tuple[str, str] = ("input", "output")


class SuppliedSurrogateAdapter(SParameterInterface):
    """Lazily imports the supplied model; constructing this adapter has no HFSS side effects."""

    def __init__(self, config: SuppliedSurrogateConfig) -> None:
        self.config = config

    def run(self, candidate: CandidateParameters) -> SParameterResult:
        try:
            module = import_supplied_module(self.config.source_root, "app.surrogate_adapter")
            adapter = module.SurrogateAdapter(
                reference_impedance_ohm=self.config.reference_impedance_ohm,
                shunt_regularization=self.config.shunt_regularization,
            )
            response = adapter.evaluate(candidate.values, self.config.frequencies_hz)
            frequencies = [float(value) for value in response.frequencies_hz.tolist()]
            matrices = response.s_parameters.tolist()
            structured = ComplexSParameters.from_complex_matrices(
                frequency_hz=frequencies,
                matrices=matrices,
                port_order=self.config.port_order,
                reference_impedance_ohm=self.config.reference_impedance_ohm,
            )
            worst_s11 = max(
                abs(complex(real[0][0], imag[0][0]))
                for real, imag in zip(structured.real, structured.imag)
            )
            db = lambda value: 20.0 * math.log10(max(abs(value), 1e-300))
            s11_db = [
                db(complex(real[0][0], imag[0][0]))
                for real, imag in zip(structured.real, structured.imag)
            ]
            s21_db = [
                db(complex(real[1][0], imag[1][0]))
                for real, imag in zip(structured.real, structured.imag)
            ]
            return SParameterResult(
                candidate_id=candidate.candidate_id,
                success=True,
                response=structured,
                metrics={
                    "screening_score": -worst_s11,
                    "worst_s11_magnitude": worst_s11,
                    "maximum_s11_db": max(s11_db),
                    "minimum_s11_db": min(s11_db),
                    "maximum_s21_db": max(s21_db),
                    "minimum_s21_db": min(s21_db),
                },
                provider="supplied-electrical-surrogate",
                model_version=module.surrogate_model_sha256(),
                calibration_status="uncalibrated",
                metadata={"comparison_context_id": self.config.comparison_context_id},
            )
        except Exception as exc:
            if isinstance(exc, SParameterCalculationError):
                raise
            raise SParameterCalculationError(
                f"Supplied surrogate failed for {candidate.candidate_id}: {exc}"
            ) from exc
