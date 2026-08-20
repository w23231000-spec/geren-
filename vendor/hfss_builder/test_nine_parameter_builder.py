from __future__ import annotations

import unittest

from nine_parameter_builder import map_nine_parameters


class NineParameterBuilderTests(unittest.TestCase):
    def setUp(self):
        self.parameters = {
            "sub_h": 200e-6,
            "TSV_r": 15e-6,
            "TSV_p": 260e-6,
            "BGA_r": 125e-6,
            "BGA_p": 660e-6,
            "RDL_w_layer1": 100e-6,
            "RDL_d_layer1": 50e-6,
            "RDL_w_layer2": 80e-6,
            "RDL_d_layer2": 50e-6,
        }

    def test_maps_all_nine_values_to_explicit_mm(self):
        mapped = map_nine_parameters(self.parameters)
        self.assertEqual(mapped["inter_h"], "0.2mm")
        self.assertEqual(mapped["r_tsv"], "0.015mm")
        self.assertEqual(mapped["offset_ubm_ubm"], "0.66mm")
        self.assertEqual(mapped["signal_w2"], "0.08mm")

    def test_accepts_changed_values(self):
        self.parameters["sub_h"] = 210e-6
        self.parameters["BGA_p"] = 680e-6
        self.parameters["RDL_d_layer2"] = 52e-6
        mapped = map_nine_parameters(self.parameters)
        self.assertEqual(mapped["inter_h"], "0.21mm")
        self.assertEqual(mapped["offset_ubm_ubm"], "0.68mm")
        self.assertEqual(mapped["signal_d2"], "0.052mm")

    def test_requires_exact_nine_names(self):
        del self.parameters["TSV_r"]
        with self.assertRaises(ValueError):
            map_nine_parameters(self.parameters)


if __name__ == "__main__":
    unittest.main()
