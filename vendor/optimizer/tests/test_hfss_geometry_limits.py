from __future__ import annotations

import unittest
from pathlib import Path

from app.constraints import evaluate_constraints, load_constraint_specs, split_constraints
from app.optimizer import baseline_values, load_parameter_specs


ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = ROOT / "config" / "parameters.csv"
CONSTRAINTS = ROOT / "config" / "constraints.csv"
METRIC_NAMES = {
    "phase_weighted_rms_deg",
    "phase_reliable_max_deg",
    "worse_frequency_fraction",
    "passivity_violation",
    "worst_s11_magnitude",
}


class HfssGeometryLimitsTest(unittest.TestCase):
    def setUp(self):
        self.parameter_specs = load_parameter_specs(PARAMETERS)
        self.parameter_names = [item.name for item in self.parameter_specs]
        all_constraints = load_constraint_specs(
            CONSTRAINTS,
            metric_names=METRIC_NAMES,
            parameter_names=self.parameter_names,
        )
        self.pre_constraints, _ = split_constraints(all_constraints)

    def test_expected_parameter_bounds_are_loaded(self):
        bounds = {item.name: (item.lower, item.upper) for item in self.parameter_specs}
        self.assertEqual(bounds["sub_h"], (100.0, 300.0))
        self.assertEqual(bounds["TSV_r"], (7.5, 22.5))
        self.assertEqual(bounds["TSV_p"], (130.0, 390.0))
        self.assertEqual(bounds["BGA_r"], (62.5, 187.5))
        self.assertEqual(bounds["BGA_p"], (330.0, 990.0))
        self.assertEqual(bounds["RDL_w_layer1"], (50.0, 150.0))
        self.assertEqual(bounds["RDL_d_layer1"], (25.0, 75.0))
        self.assertEqual(bounds["RDL_w_layer2"], (40.0, 120.0))
        self.assertEqual(bounds["RDL_d_layer2"], (25.0, 75.0))

    def test_baseline_passes_all_parameter_only_constraints(self):
        result = evaluate_constraints(
            self.pre_constraints,
            parameters=baseline_values(self.parameter_specs),
        )
        self.assertTrue(result.feasible, result.by_name())

    def test_invalid_bga_radius_pitch_combination_is_rejected(self):
        parameters = baseline_values(self.parameter_specs)
        parameters.update(BGA_r=187.5, BGA_p=330.0)
        result = evaluate_constraints(self.pre_constraints, parameters=parameters)
        self.assertGreater(result.by_name()["bga_geometry_spacing"], 0.0)

    def test_valid_bga_radius_pitch_combination_is_accepted(self):
        parameters = baseline_values(self.parameter_specs)
        parameters.update(BGA_r=187.5, BGA_p=500.0)
        result = evaluate_constraints(self.pre_constraints, parameters=parameters)
        self.assertLessEqual(result.by_name()["bga_geometry_spacing"], 0.0)


if __name__ == "__main__":
    unittest.main()
