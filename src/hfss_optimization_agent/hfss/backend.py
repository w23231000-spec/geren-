"""Build/Solve/Extract backend protocol; the default implementation is intentionally inert."""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.models import CandidateParameters
from .contracts import HFSSRunContract


@dataclass(frozen=True, slots=True)
class BuiltProject:
    project_path: str
    design_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SolvedProject:
    project_path: str
    design_name: str
    solution_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RawSParameterData:
    """Backend-neutral pair of numeric 2x2 matrices in a declared representation."""

    frequency_hz: list[float]
    first: list[list[list[float]]]
    second: list[list[list[float]]]
    representation: str
    port_order: tuple[str, str]
    reference_impedance_ohm: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.representation not in {"real_imag", "magnitude_phase_deg", "db_phase_deg"}:
            raise ValueError(f"Unknown raw S-parameter representation {self.representation!r}")
        count = len(self.frequency_hz)
        if count < 2 or len(self.first) != count or len(self.second) != count:
            raise ValueError("Raw S-parameter frequency and matrix counts differ")
        if any(not math.isfinite(float(value)) for value in self.frequency_hz):
            raise ValueError("Raw frequencies must be finite")
        if any(right <= left for left, right in zip(self.frequency_hz, self.frequency_hz[1:])):
            raise ValueError("Raw frequencies must be strictly increasing")
        for matrices in (self.first, self.second):
            for matrix in matrices:
                if len(matrix) != 2 or any(len(row) != 2 for row in matrix):
                    raise ValueError("Raw S-parameter matrices must be 2x2")
                if any(not math.isfinite(float(value)) for row in matrix for value in row):
                    raise ValueError("Raw S-parameter matrix values must be finite")


class HFSSBackendInterface(ABC):
    """Implementation boundary that a future PyAEDT/COM/gRPC worker must satisfy."""

    backend_name: str = "unknown"
    process_isolated: bool = False

    @abstractmethod
    def build(
        self,
        candidate: CandidateParameters,
        workspace: Path,
        contract: HFSSRunContract,
    ) -> BuiltProject:
        """Map parameters and create/update a project in the isolated workspace."""

    @abstractmethod
    def solve(
        self,
        project: BuiltProject,
        contract: HFSSRunContract,
        *,
        timeout_seconds: float,
    ) -> SolvedProject:
        """Solve the declared setup/sweep and honor the supplied timeout."""

    @abstractmethod
    def extract(
        self,
        solved: SolvedProject,
        contract: HFSSRunContract,
    ) -> RawSParameterData:
        """Extract the declared two-port complex response."""

    @abstractmethod
    def close(self) -> None:
        """Release backend resources; called exactly once from a finally block."""


class UnavailableHFSSBackend(HFSSBackendInterface):
    """Explicit placeholder that can never access AEDT."""

    backend_name = "unavailable-real-hfss"
    process_isolated = False

    @staticmethod
    def _unavailable() -> None:
        raise NotImplementedError(
            "No real HFSS backend is configured; AEDT/PyAEDT is not accessed by this project."
        )

    def build(self, candidate, workspace, contract):
        del candidate, workspace, contract
        self._unavailable()

    def solve(self, project, contract, *, timeout_seconds):
        del project, contract, timeout_seconds
        self._unavailable()

    def extract(self, solved, contract):
        del solved, contract
        self._unavailable()

    def close(self) -> None:
        return None
