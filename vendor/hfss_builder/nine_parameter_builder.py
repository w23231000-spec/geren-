"""Build PA_MULTI from exactly nine upstream dimensions.

This module only performs parameter transfer and HFSS model construction.  It
does not contain an optimization algorithm and does not run a simulation.
All input values use metres; AEDT model variables are written in millimetres.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from pa_multi_builder import build_project


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
        raise ValueError("parameter mismatch; missing=%s, extra=%s" % (sorted(missing), sorted(extra)))

    overrides = {}
    for upstream_name, hfss_name in PARAMETER_MAP.items():
        value = parameters[upstream_name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("%s must be numeric and use metres" % upstream_name)
        value = float(value)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("%s must be finite and greater than zero" % upstream_name)
        overrides[hfss_name] = "%.15gmm" % (value * 1000.0)
    return overrides


def build_from_nine_parameters(parameters, output_path, non_graphical=True, progress_callback=None):
    """Create a complete AEDT project; no solve is started."""
    output_path = Path(output_path).resolve()
    if output_path.exists():
        raise FileExistsError("Refusing to overwrite existing project: %s" % output_path)
    return build_project(
        output_path=output_path,
        non_graphical=non_graphical,
        parameter_overrides=map_nine_parameters(parameters),
        progress_callback=progress_callback,
    )


def main():
    parser = argparse.ArgumentParser(description="PA_MULTI nine-parameter model builder")
    parser.add_argument("--input", required=True, help="JSON containing exactly nine values in metres")
    parser.add_argument("--output", required=True, help="new .aedt output path")
    parser.add_argument("--graphical", action="store_true")
    args = parser.parse_args()
    parameters = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = build_from_nine_parameters(parameters, args.output, non_graphical=not args.graphical)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
