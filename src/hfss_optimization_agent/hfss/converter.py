"""Pure conversion of declared HFSS export representations to complex matrices."""

import cmath
import math

from ..core.models import ComplexSParameters
from ..harness.errors import HFSSContractError
from .backend import RawSParameterData
from .contracts import HFSSRunContract


def convert_raw_sparameters(
    raw: RawSParameterData,
    contract: HFSSRunContract,
) -> ComplexSParameters:
    if raw.representation != contract.extractor_format:
        raise HFSSContractError(
            f"Extractor returned {raw.representation!r}; contract requires {contract.extractor_format!r}"
        )
    if raw.port_order != contract.port_order:
        raise HFSSContractError(
            f"Extractor port order {raw.port_order!r} does not match {contract.port_order!r}"
        )
    if not math.isclose(
        raw.reference_impedance_ohm,
        contract.reference_impedance_ohm,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise HFSSContractError("Extractor reference impedance does not match the HFSS contract")

    matrices: list[list[list[complex]]] = []
    for first, second in zip(raw.first, raw.second):
        matrix: list[list[complex]] = []
        for first_row, second_row in zip(first, second):
            row: list[complex] = []
            for first_value, second_value in zip(first_row, second_row):
                if raw.representation == "real_imag":
                    value = complex(first_value, second_value)
                else:
                    magnitude = (
                        10.0 ** (first_value / 20.0)
                        if raw.representation == "db_phase_deg"
                        else first_value
                    )
                    value = cmath.rect(magnitude, math.radians(second_value))
                row.append(value)
            matrix.append(row)
        matrices.append(matrix)
    return ComplexSParameters.from_complex_matrices(
        frequency_hz=raw.frequency_hz,
        matrices=matrices,
        port_order=raw.port_order,
        reference_impedance_ohm=raw.reference_impedance_ohm,
    )
