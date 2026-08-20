"""Shared neutral fixtures for offline tests."""

import os
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest

from hfss_optimization_agent.core.models import CandidateParameters
from hfss_optimization_agent.parameters.schema import ParameterDefinition, ParameterSchema


def pytest_configure(config) -> None:
    """Use a unique temp root so stale pytest directories cannot block a run."""

    if config.option.basetemp is None:
        run_id = f"hfss-agent-pytest-{os.getpid()}-{uuid.uuid4().hex}"
        config.option.basetemp = str(Path(tempfile.gettempdir()) / run_id)


@pytest.fixture
def schema() -> ParameterSchema:
    return ParameterSchema(
        (
            ParameterDefinition("p1", "u", 1.0, 0.0, 3.0, True),
            ParameterDefinition("p2", "u", 1.0, 0.0, 3.0, True),
            ParameterDefinition("p3", "u", 0.5, -1.0, 1.0, False),
        )
    )


@pytest.fixture
def baseline() -> CandidateParameters:
    return CandidateParameters("baseline", 0, {"p1": 1.0, "p2": 1.0}, {"role": "baseline"})
