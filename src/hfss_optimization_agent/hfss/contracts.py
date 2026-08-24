"""Versioned HFSS execution and comparison contracts with no AEDT dependency."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ..harness.errors import HFSSContractError
from ..harness.provenance import source_manifest_digest, source_tree_manifest


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


FREQUENCY_GRID_ABS_TOLERANCE_HZ = 1.0
FREQUENCY_GRID_REL_TOLERANCE = 1e-12


def expected_sweep_frequency_hz(sweep: SweepContract) -> tuple[float, ...]:
    """Return the grid fully declared by a linear or logarithmic sweep contract."""

    if sweep.spacing == "linear":
        step_hz = (sweep.stop_hz - sweep.start_hz) / (sweep.points - 1)
        values = [sweep.start_hz + index * step_hz for index in range(sweep.points)]
    elif sweep.spacing == "log":
        ratio = (sweep.stop_hz / sweep.start_hz) ** (1.0 / (sweep.points - 1))
        values = [sweep.start_hz * ratio**index for index in range(sweep.points)]
    else:
        raise HFSSContractError(
            "Explicit sweep spacing cannot be verified because SweepContract does not "
            "declare the intermediate frequencies"
        )
    values[0] = sweep.start_hz
    values[-1] = sweep.stop_hz
    return tuple(values)


def validate_sweep_frequency_grid(
    frequency_hz: Sequence[float],
    sweep: SweepContract,
) -> tuple[float, ...]:
    """Fail closed unless the returned HFSS grid matches the declared sweep point by point."""

    actual = tuple(float(value) for value in frequency_hz)
    if len(actual) != sweep.points:
        raise HFSSContractError(
            f"HFSS returned {len(actual)} frequency points; contract requires {sweep.points}"
        )
    if not all(math.isfinite(value) for value in actual):
        raise HFSSContractError("HFSS returned a non-finite frequency")
    if any(current <= previous for previous, current in zip(actual, actual[1:])):
        raise HFSSContractError("HFSS returned a frequency grid that is not strictly increasing")

    expected = expected_sweep_frequency_hz(sweep)
    for index, (observed_hz, expected_hz) in enumerate(zip(actual, expected)):
        if not math.isclose(
            observed_hz,
            expected_hz,
            rel_tol=FREQUENCY_GRID_REL_TOLERANCE,
            abs_tol=FREQUENCY_GRID_ABS_TOLERANCE_HZ,
        ):
            raise HFSSContractError(
                "HFSS frequency grid mismatch at index "
                f"{index}: returned {observed_hz:.17g} Hz; "
                f"contract requires {expected_hz:.17g} Hz"
            )
    return actual


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


@dataclass(frozen=True, slots=True)
class BuilderAttestation:
    schema_version: str
    builder_id: str
    source_digest: str
    files: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.schema_version != "builder-attestation/1.0":
            raise HFSSContractError("unsupported Builder attestation schema")
        if not self.builder_id or len(self.source_digest) != 64 or not self.files:
            raise HFSSContractError("invalid Builder attestation identity")
        if source_manifest_digest(self.files) != self.source_digest:
            raise HFSSContractError("Builder attestation manifest digest mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "builder_id": self.builder_id,
            "source_digest": self.source_digest,
            "files": [list(item) for item in self.files],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BuilderAttestation":
        return cls(
            schema_version=str(value["schema_version"]),
            builder_id=str(value["builder_id"]),
            source_digest=str(value["source_digest"]),
            files=tuple((str(item[0]), str(item[1])) for item in value["files"]),
        )


def attest_builder(root: Path, builder_id: str) -> BuilderAttestation:
    files = source_tree_manifest(root, suffixes=(".py",))
    return BuilderAttestation(
        schema_version="builder-attestation/1.0",
        builder_id=builder_id,
        source_digest=source_manifest_digest(files),
        files=files,
    )


def verify_builder_attestation(root: Path, attestation: BuilderAttestation) -> None:
    actual = attest_builder(root, attestation.builder_id)
    if actual != attestation:
        raise HFSSContractError(
            "Builder source drift detected before license acquisition: "
            f"expected {attestation.source_digest}, observed {actual.source_digest}"
        )


@dataclass(frozen=True, slots=True)
class HFSSCompositeRequest:
    schema_version: str
    candidate: dict[str, Any]
    contract: dict[str, Any]
    workspace: str
    builder_attestation: BuilderAttestation
    worker_options: dict[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != "hfss-composite-request/1.0":
            raise HFSSContractError("unsupported HFSS composite request schema")
        if not self.workspace:
            raise HFSSContractError("HFSS composite workspace is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate": self.candidate,
            "contract": self.contract,
            "workspace": self.workspace,
            "builder_attestation": self.builder_attestation.to_dict(),
            "worker_options": self.worker_options,
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


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
