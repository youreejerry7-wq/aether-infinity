"""Offline controls for the bounded geometry candidate search."""
import json
import math
import unittest

import design_lab as lab


class BoxDesignLabTests(unittest.TestCase):
    def test_known_geometry_and_invalid_cuts(self):
        self.assertEqual(lab.box_volume(20, 30, 2), 832)
        self.assertEqual(lab.box_volume(20, 30, 0), 0)
        self.assertEqual(lab.box_volume(20, 30, 10), 0)
        self.assertEqual(lab.box_volume(18, 32, 9), 0)
        self.assertEqual(lab.box_volume(-1, 30, 2), 0)

    def test_training_seed_reproducible_and_bounded(self):
        a = lab.training_sheets(42)
        self.assertEqual(a, lab.training_sheets(42))
        self.assertNotEqual(a, lab.training_sheets(43))
        self.assertEqual(len(a), 8)
        for width, height in a:
            self.assertLessEqual(abs(width - 20), 0.5)
            self.assertLessEqual(abs(height - 30), 0.5)

    def test_grid_search_uses_training_only(self):
        training = lab.training_sheets(lab.SEED)
        scores = {x: lab.mean_volume(training, x) for x in lab.CUT_GRID}
        expected = max(lab.CUT_GRID, key=lambda x: (scores[x], -x))
        report = lab.run()
        self.assertEqual(report["candidate"]["cut_cm"], expected)
        self.assertGreater(scores[expected], scores[lab.BASELINE_CUT])

    def test_positive_and_negative_controls_on_unseen_holdout(self):
        report = lab.run()
        self.assertTrue(report["candidate"]["passed_all_holdouts"])
        self.assertGreater(report["candidate"]["minimum_holdout_improvement_cm3"], 0)
        self.assertEqual(report["candidate"]["evidence_level"], "simulation_candidate")
        self.assertFalse(report["negative_control"]["passed_all_holdouts"])
        self.assertLess(report["negative_control"]["minimum_holdout_improvement_cm3"], 0)
        self.assertEqual(report["negative_control"]["evidence_level"], "rejected_simulation_candidate")

    def test_holdout_not_used_to_select_candidate(self):
        # Evaluating alternate holdouts cannot change the training-only selection.
        selected = lab.run()["candidate"]["cut_cm"]
        altered_holdout = ((12.0, 12.0), (40.0, 40.0))
        _ = lab.evaluate(selected, holdout=altered_holdout)
        self.assertEqual(selected, lab.run()["candidate"]["cut_cm"])
        self.assertEqual(lab.HOLDOUT_SHEETS, ((18.0, 32.0), (22.0, 28.0), (19.0, 31.0)))

    def test_analytic_oracle_matches_independent_dense_grid(self):
        # Independent numerical sweep catches wrong derivative/root selection.
        sheets = lab.training_sheets(lab.SEED)
        optimum = lab.continuous_training_optimum(sheets)
        dense = (i / 1000 for i in range(1, 9000))
        numeric_optimum = max(dense, key=lambda x: lab.mean_volume(sheets, x))
        self.assertLess(abs(optimum - numeric_optimum), 0.0011)
        self.assertGreater(lab.mean_volume(sheets, optimum), 0)
        self.assertGreaterEqual(lab.mean_volume(sheets, optimum),
                                lab.mean_volume(sheets, lab.run()["candidate"]["cut_cm"]))

    def test_grid_discretization_regret_is_bounded_and_reported(self):
        report = lab.run()
        optimum = report["continuous_training_optimum_cut_cm"]
        selected = report["candidate"]["cut_cm"]
        self.assertLessEqual(abs(optimum - selected), 0.25)
        self.assertGreaterEqual(report["grid_discretization_regret_cm3"], 0)
        self.assertAlmostEqual(
            report["grid_discretization_regret_cm3"],
            report["continuous_training_optimum_mean_volume_cm3"]
            - report["selected_training_mean_volume_cm3"],
            places=9,
        )
        self.assertIn("Analytic stationary point", report["reference_method"])

    def test_analytic_reference_rejects_invalid_dimensions(self):
        for sheets in ((), ((0, 30),), ((float("nan"), 30),),
                       ((20, float("inf")),)):
            with self.subTest(sheets=sheets):
                with self.assertRaises(ValueError):
                    lab.continuous_training_optimum(sheets)

    def test_report_reproducible_and_honestly_labeled(self):
        a = lab.run()
        self.assertEqual(a, lab.run())
        self.assertNotEqual(a["selected_training_mean_volume_cm3"],
                            lab.run(seed=7)["selected_training_mean_volume_cm3"])
        self.assertEqual(a["novelty_status"], "not_assessed")
        self.assertIs(a["physical_validation"], False)
        self.assertEqual(a["training_case_count"], 8)
        self.assertEqual(len(a["holdout_sheets_cm"]), 3)
        self.assertTrue(all(math.isfinite(x) for x in a["candidate"]["holdout_volumes_cm3"]))
        self.assertEqual(json.loads(json.dumps(a)), a)


if __name__ == "__main__":
    unittest.main()
