"""Defines the supplied builder/optimizer nine-parameter contract in SI units."""

from ..core.models import CandidateParameters
from .schema import ParameterDefinition, ParameterSchema


_PARAMETERS = (
    ("sub_h", 200.0, 100.0, 300.0),
    ("TSV_r", 15.0, 7.5, 22.5),
    ("TSV_p", 260.0, 130.0, 390.0),
    ("BGA_r", 125.0, 62.5, 187.5),
    ("BGA_p", 660.0, 330.0, 990.0),
    ("RDL_w_layer1", 100.0, 50.0, 150.0),
    ("RDL_d_layer1", 50.0, 25.0, 75.0),
    ("RDL_w_layer2", 80.0, 40.0, 120.0),
    ("RDL_d_layer2", 50.0, 25.0, 75.0),
)


def supplied_nine_parameter_schema() -> ParameterSchema:
    """Return the exact shared contract, represented in model/builder units of metres."""

    return ParameterSchema(
        tuple(
            ParameterDefinition(
                name=name,
                unit="m",
                default=baseline_um * 1e-6,
                lower_bound=lower_um * 1e-6,
                upper_bound=upper_um * 1e-6,
                required=True,
                metadata={"display_unit": "um", "scale_from_display": 1e-6},
            )
            for name, baseline_um, lower_um, upper_um in _PARAMETERS
        )
    )


def supplied_baseline_candidate() -> CandidateParameters:
    """Create the immutable initial parameter set shared by both supplied modules."""

    schema = supplied_nine_parameter_schema()
    return CandidateParameters(
        candidate_id="baseline",
        iteration=0,
        values={item.name: float(item.default) for item in schema.parameters},
        metadata={
            "role": "baseline",
            "parameter_contract": "supplied-nine-parameter-v1",
            "unit": "m",
        },
    )
