"""Defines generic parameter declarations without real structure names."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    name: str
    unit: str = ""
    default: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    required: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParameterSchema:
    parameters: tuple[ParameterDefinition, ...]

    def __post_init__(self) -> None:
        names = [item.name for item in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("Parameter names must be unique")

    @property
    def by_name(self) -> dict[str, ParameterDefinition]:
        return {item.name: item for item in self.parameters}

