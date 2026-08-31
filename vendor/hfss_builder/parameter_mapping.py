"""Pure nine-parameter validation and metre-to-millimetre mapping."""

from __future__ import annotations

import math


PARAMETER_MAP = {
    "sub_h": "inter_h",
    "TSV_r": "r_tsv",
    "TSV_p": "offset_tsv_line",
    "BGA_r": "r_bga",
    "BGA_p": "offset_ubm_ubm",
    "RDL_w_layer1": "signal_w1",
    "RDL_d_layer1": "signal_d1",
    "RDL_w_layer2": "signal_w2",
    "RDL_d_layer2": "signal_d2",
}


def map_nine_parameters(parameters):
    """Convert the exact nine metre-valued inputs to AEDT expressions."""

    if not isinstance(parameters, dict):
        raise TypeError("parameters must be a dictionary")
    missing = set(PARAMETER_MAP) - set(parameters)
    extra = set(parameters) - set(PARAMETER_MAP)
    if missing or extra:
        raise ValueError(
            "parameter mismatch; missing=%s, extra=%s"
            % (sorted(missing), sorted(extra))
        )

    overrides = {}
    for upstream_name, hfss_name in PARAMETER_MAP.items():
        value = parameters[upstream_name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{upstream_name} must be numeric and use metres")
        value = float(value)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{upstream_name} must be finite and greater than zero")
        overrides[hfss_name] = f"{value * 1000.0:.15g}mm"
    return overrides
