"""Parameter schema and validation edge cases."""

import math
import pytest

from hfss_optimization_agent.core.models import CandidateParameters
from hfss_optimization_agent.harness.errors import ParameterValidationError
from hfss_optimization_agent.parameters.validator import ParameterValidator


def candidate(values):
    return CandidateParameters("c", 1, values)


def test_valid_parameters(schema):
    assert ParameterValidator(schema).validate(candidate({"p1": 1.0, "p2": 2}))


@pytest.mark.parametrize(
    "values, message",
    [
        ({"p1": -0.1, "p2": 1.0}, "below lower"),
        ({"p1": 3.1, "p2": 1.0}, "above upper"),
        ({"p1": math.nan, "p2": 1.0}, "finite"),
        ({"p1": math.inf, "p2": 1.0}, "finite"),
        ({"p1": 1.0, "p2": 1.0, "unknown": 2.0}, "unknown"),
        ({"p1": 1.0}, "missing"),
        ({"p1": "bad", "p2": 1.0}, "numeric"),
        ({"p1": True, "p2": 1.0}, "numeric"),
    ],
)
def test_invalid_parameters(schema, values, message):
    with pytest.raises(ParameterValidationError, match=message):
        ParameterValidator(schema).validate(candidate(values))
