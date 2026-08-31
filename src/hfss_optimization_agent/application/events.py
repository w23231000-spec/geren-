"""Application-level run events for the REAL HFSS desktop UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RunEvent:
    event_type: str
    stage: str
    message: str
    detail: str | None = None
    payload: Mapping[str, Any] | None = None
