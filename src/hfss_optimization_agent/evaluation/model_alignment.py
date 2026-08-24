"""Strict versioned physical-model alignment authority."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping

from ..domain.canonical_json import canonical_dumps, canonical_loads, require_exact_fields
from ..domain.contracts import FrozenMap


MODEL_ALIGNMENT_SCHEMA_VERSION = "physical-model-alignment/1.0"


@dataclass(frozen=True, slots=True)
class ModelAlignmentContract:
    schema_version: str
    alignment_id: str
    approval_status: str
    approved_by: str
    authority: str
    hfss_contract_id: str
    design_name: str
    comparison_context_id: str
    frequency_grid: FrozenMap
    port_order: tuple[str, str]
    reference_impedance_ohm: float
    materials: FrozenMap
    surrogate_requirements: FrozenMap

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_ALIGNMENT_SCHEMA_VERSION:
            raise ValueError(
                f"model alignment schema_version must be {MODEL_ALIGNMENT_SCHEMA_VERSION}"
            )
        for name in (
            "alignment_id",
            "approved_by",
            "hfss_contract_id",
            "comparison_context_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ModelAlignmentContract.{name} must be non-empty")
        if self.approval_status != "APPROVED":
            raise ValueError("model alignment must be explicitly APPROVED")
        if self.authority != "hfss_builder":
            raise ValueError("model alignment authority must be hfss_builder")
        if self.design_name != "interposer_temple4":
            raise ValueError("model alignment may authorize only interposer_temple4")
        if self.port_order != ("input", "output"):
            raise ValueError("model alignment port order must be input then output")
        if float(self.reference_impedance_ohm) != 50.0:
            raise ValueError("model alignment reference impedance must be 50 ohm")

        grid = self.frequency_grid.to_dict()
        if set(grid) != {"start_hz", "stop_hz", "points", "spacing"}:
            raise ValueError("model alignment frequency grid fields differ")
        if grid != {
            "start_hz": 100_000_000.0,
            "stop_hz": 20_000_000_000.0,
            "points": 200,
            "spacing": "linear",
        }:
            raise ValueError("model alignment frequency grid differs from Production HFSS")

        materials = self.materials.to_dict()
        if materials != {
            "pi": {"loss_tangent": 0.02, "relative_permittivity": 3.5},
            "silicon_dioxide": {"relative_permittivity": 4.0},
        }:
            raise ValueError("model alignment material authority differs from HFSS Builder")
        requirements = self.surrogate_requirements.to_dict()
        if requirements != {
            "empirical_terms": ["Gsub", "Rlf1", "alpha"],
            "empirical_terms_disposition": "accepted_only_by_passing_calibration",
            "frequency_points": 200,
            "pi_relative_permittivity": 3.5,
        }:
            raise ValueError("model alignment surrogate requirements differ")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelAlignmentContract":
        data = require_exact_fields(
            value,
            {
                "schema_version",
                "alignment_id",
                "approval_status",
                "approved_by",
                "authority",
                "hfss_contract_id",
                "design_name",
                "comparison_context_id",
                "frequency_grid",
                "port_order",
                "reference_impedance_ohm",
                "materials",
                "surrogate_requirements",
            },
            context="ModelAlignmentContract",
        )
        if not isinstance(data["port_order"], list) or len(data["port_order"]) != 2:
            raise ValueError("model alignment port_order must contain two items")
        return cls(
            schema_version=data["schema_version"],
            alignment_id=data["alignment_id"],
            approval_status=data["approval_status"],
            approved_by=data["approved_by"],
            authority=data["authority"],
            hfss_contract_id=data["hfss_contract_id"],
            design_name=data["design_name"],
            comparison_context_id=data["comparison_context_id"],
            frequency_grid=FrozenMap.from_dict(data["frequency_grid"]),
            port_order=tuple(data["port_order"]),
            reference_impedance_ohm=float(data["reference_impedance_ohm"]),
            materials=FrozenMap.from_dict(data["materials"]),
            surrogate_requirements=FrozenMap.from_dict(data["surrogate_requirements"]),
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_dumps(self).encode("utf-8")).hexdigest()


def load_model_alignment_contract(path: Path) -> ModelAlignmentContract:
    return ModelAlignmentContract.from_dict(
        canonical_loads(Path(path).read_text(encoding="utf-8"))
    )
