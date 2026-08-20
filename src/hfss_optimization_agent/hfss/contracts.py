"""Versioned HFSS execution and comparison contracts with no AEDT dependency."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..harness.errors import HFSSContractError


@dataclass(frozen=True, slots=True)
class SweepContract:
    name: str
    start_hz: float
    stop_hz: float
    points: int
    spacing: str = "linear"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise HFSSContractError("Sweep name is required")
        if not all(math.isfinite(value) for value in (self.start_hz, self.stop_hz)):
            raise HFSSContractError("Sweep frequencies must be finite")
        if not 0.0 < self.start_hz < self.stop_hz or self.points < 2:
            raise HFSSContractError("Sweep requires 0 < start < stop and at least two points")
        if self.spacing not in {"linear", "log", "explicit"}:
            raise HFSSContractError(f"Unsupported sweep spacing {self.spacing!r}")


@dataclass(frozen=True, slots=True)
class PortContract:
    exported_name: str
    physical_role: str
    mode_index: int = 1
    reference_impedance_ohm: float = 50.0
    renormalize: bool = True
    deembed_distance_m: float = 0.0

    def __post_init__(self) -> None:
        if not self.exported_name.strip() or not self.physical_role.strip():
            raise HFSSContractError("Port exported name and physical role are required")
        if self.mode_index < 1:
            raise HFSSContractError("Port mode index must be positive")
        if not math.isfinite(self.reference_impedance_ohm) or self.reference_impedance_ohm <= 0.0:
            raise HFSSContractError("Port reference impedance must be positive and finite")
        if not math.isfinite(self.deembed_distance_m) or self.deembed_distance_m < 0.0:
            raise HFSSContractError("Port de-embedding distance cannot be negative")


@dataclass(frozen=True, slots=True)
class MaterialContract:
    material_name: str
    relative_permittivity: float | None = None
    loss_tangent: float | None = None
    conductivity_s_per_m: float | None = None
    evidence_status: str = "unconfirmed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.material_name.strip():
            raise HFSSContractError("Material name is required")
        for name, value in (
            ("relative_permittivity", self.relative_permittivity),
            ("loss_tangent", self.loss_tangent),
            ("conductivity_s_per_m", self.conductivity_s_per_m),
        ):
            if value is not None and (not math.isfinite(value) or value < 0.0):
                raise HFSSContractError(f"Material {name} must be non-negative and finite")
        if self.evidence_status not in {"unconfirmed", "datasheet", "measured", "calibrated"}:
            raise HFSSContractError(f"Unknown material evidence status {self.evidence_status!r}")


@dataclass(frozen=True, slots=True)
class HFSSRunContract:
    """Everything required to identify the meaning of one exported two-port result."""

    schema_version: str
    builder_id: str
    design_name: str
    solution_type: str
    setup_name: str
    sweep: SweepContract
    ports: tuple[PortContract, PortContract]
    parameter_mapping: dict[str, str]
    materials: tuple[MaterialContract, ...] = ()
    extractor_format: str = "real_imag"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        required = (
            self.schema_version,
            self.builder_id,
            self.design_name,
            self.solution_type,
            self.setup_name,
        )
        if any(not value.strip() for value in required):
            raise HFSSContractError("HFSS contract identity fields cannot be empty")
        if self.ports[0].exported_name == self.ports[1].exported_name:
            raise HFSSContractError("HFSS two-port exported names must be distinct")
        if self.ports[0].physical_role == self.ports[1].physical_role:
            raise HFSSContractError("HFSS two-port physical roles must be distinct")
        if any(not source.strip() or not target.strip() for source, target in self.parameter_mapping.items()):
            raise HFSSContractError("Parameter mapping names cannot be empty")
        if len(set(self.parameter_mapping.values())) != len(self.parameter_mapping):
            raise HFSSContractError("HFSS design-variable targets must be unique")
        if self.extractor_format not in {"real_imag", "magnitude_phase_deg", "db_phase_deg"}:
            raise HFSSContractError(f"Unsupported extractor format {self.extractor_format!r}")

    @property
    def port_order(self) -> tuple[str, str]:
        return (self.ports[0].physical_role, self.ports[1].physical_role)

    @property
    def reference_impedance_ohm(self) -> float:
        first, second = (port.reference_impedance_ohm for port in self.ports)
        if not math.isclose(first, second, rel_tol=0.0, abs_tol=1e-12):
            raise HFSSContractError("The current two-port result model requires equal port impedances")
        return first

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "HFSSRunContract":
        copied = dict(value)
        copied["sweep"] = SweepContract(**copied["sweep"])
        copied["ports"] = tuple(PortContract(**item) for item in copied["ports"])
        copied["materials"] = tuple(
            MaterialContract(**item) for item in copied.get("materials", [])
        )
        return cls(**copied)

    @property
    def contract_id(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest().upper()


def load_hfss_contract(path: str | Path) -> HFSSRunContract:
    """Load a JSON contract so later physical decisions remain configuration changes."""

    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HFSSContractError(f"Unable to load HFSS contract {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise HFSSContractError("HFSS contract root must be a JSON object")
    return HFSSRunContract.from_dict(value)
