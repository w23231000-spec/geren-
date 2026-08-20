"""Focused tests for optimizer functionality retained by the Agent integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.run import check_baseline, execute, normalize_algorithm  # noqa: E402


def test_baseline_surrogate_and_geometry_constraints_are_computable():
    result = check_baseline()
    assert result["worst_s11_magnitude"] > 0.0
    assert result["configured_objective_count"] >= 2
    assert result["configured_constraint_count"] > 0
    assert result["model_id"] == "tsv_bga_rdl_electrical"


def test_quick_optimizer_writes_recommended_candidate(tmp_path):
    directory = execute(output_root=tmp_path, quick=True, debug=False)
    summary = json.loads((directory / "00_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "completed"
    assert summary["recommended_point_id"]
    assert set(summary["recommended_parameters"]["model_units"]) == {
        "sub_h",
        "TSV_r",
        "TSV_p",
        "BGA_r",
        "BGA_p",
        "RDL_w_layer1",
        "RDL_d_layer1",
        "RDL_w_layer2",
        "RDL_d_layer2",
    }


def test_supported_algorithm_aliases_are_stable():
    assert normalize_algorithm("NSGA3") == "NSGA-III"
    assert normalize_algorithm("PSO") == "MOPSO"
    assert normalize_algorithm("SA") == "MOSA"
