"""Build PA_MULTI from exactly nine upstream dimensions.

This module only performs parameter transfer and HFSS model construction.  It
does not contain an optimization algorithm and does not run a simulation.
All input values use metres; AEDT model variables are written in millimetres.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pa_multi_builder import build_project
from parameter_mapping import PARAMETER_MAP, map_nine_parameters


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
