"""Immutable server-side limits for physical Tool execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.canonical_json import require_exact_fields


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    """First-version real-HFSS execution envelope.

    The launch ceiling is enforced transactionally by RunStore for operations
    requiring the ``real_hfss`` approval scope. Test-double HFSS callbacks do
    not represent physical solver launches and are therefore not charged to
    this counter.
    """

    max_hfss_solve_launches: int = 2
    automatic_solve_retries: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_hfss_solve_launches, int)
            or isinstance(self.max_hfss_solve_launches, bool)
            or self.max_hfss_solve_launches < 0
        ):
            raise ValueError("max_hfss_solve_launches must be a non-negative integer")
        if (
            not isinstance(self.automatic_solve_retries, int)
            or isinstance(self.automatic_solve_retries, bool)
            or self.automatic_solve_retries != 0
        ):
            raise ValueError("automatic_solve_retries must be exactly 0")

    @classmethod
    def from_dict(cls, value: Any) -> "ExecutionPolicy":
        data = require_exact_fields(
            value,
            {"max_hfss_solve_launches", "automatic_solve_retries"},
            context="ExecutionPolicy",
        )
        return cls(
            max_hfss_solve_launches=data["max_hfss_solve_launches"],
            automatic_solve_retries=data["automatic_solve_retries"],
        )
