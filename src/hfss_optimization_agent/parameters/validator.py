"""Validates candidate values against a generic parameter schema."""

import math
from numbers import Real

from ..core.models import CandidateParameters
from ..harness.errors import ParameterValidationError
from .schema import ParameterSchema


class ParameterValidator:
    def __init__(self, schema: ParameterSchema) -> None:
        self.schema = schema

    def validate(self, candidate: CandidateParameters) -> CandidateParameters:
        definitions = self.schema.by_name
        unknown = sorted(set(candidate.values) - set(definitions))
        missing = sorted(
            name
            for name, definition in definitions.items()
            if definition.required and name not in candidate.values
        )
        errors: list[str] = []
        if unknown:
            errors.append(f"unknown parameters: {unknown}")
        if missing:
            errors.append(f"missing required parameters: {missing}")

        for name, value in candidate.values.items():
            definition = definitions.get(name)
            if definition is None:
                continue
            if isinstance(value, bool) or not isinstance(value, Real):
                errors.append(f"{name} must be numeric")
                continue
            numeric = float(value)
            if not math.isfinite(numeric):
                errors.append(f"{name} must be finite")
                continue
            if definition.lower_bound is not None and numeric < definition.lower_bound:
                errors.append(f"{name} is below lower bound {definition.lower_bound}")
            if definition.upper_bound is not None and numeric > definition.upper_bound:
                errors.append(f"{name} is above upper bound {definition.upper_bound}")

        if errors:
            raise ParameterValidationError("; ".join(errors))
        return candidate

