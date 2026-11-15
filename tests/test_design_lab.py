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
        self.assertEqual(lab.box_volume(float("nan"), 30, 2), 0)
        self.assertEqual(lab.box_volume(20, float("inf"), 2), 0)
        self.assertEqual(lab.box_volume(20, 30, float("nan")), 0)
        self.assertEqual(lab.box_volume(20, 30, float("-inf")), 0)

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
        # A failed control must be physically feasible within the model;
        # invalid zero-volume geometry would be a misleading easy rejection.
        self.assertEqual(report["negative_control"]["cut_cm"], 7.5)
        for w, h in lab.HOLDOUT_SHEETS:
            self.assertGreater(lab.box_volume(w, h, lab.NEGATIVE_CONTROL_CUT), 0)
            self.assertGreater(lab.box_volume(w, h, lab.BASELINE_CUT), 0)
        self.assertTrue(all(v > 0 for v in report["negative_control"]["holdout_volumes_cm3"]))
        self.assertFalse(report["negative_control"]["passed_all_holdouts"])
        self.assertLess(report["negative_control"]["minimum_holdout_improvement_cm3"], 0)
        self.assertEqual(report["negative_control"]["evidence_level"], "rejected_simulation_candidate")

    def test_holdout_not_used_to_select_candidate(self):
        # Actually substitute the holdout used by run(), not merely call
        # evaluate() independently; the training-selected cut must not change.
        from unittest.mock import patch
        original = lab.run()
        altered_holdout = ((16.0, 34.0), (24.0, 28.0))
        with patch.object(lab, "HOLDOUT_SHEETS", altered_holdout):
            alternate = lab.run()
        self.assertEqual(original["candidate"]["cut_cm"],
                         alternate["candidate"]["cut_cm"])
        self.assertEqual(alternate["holdout_sheets_cm"],
                         [list(pair) for pair in altered_holdout])
        self.assertNotEqual(original["candidate"]["holdout_volumes_cm3"],
                            alternate["candidate"]["holdout_volumes_cm3"])
        self.assertEqual(lab.HOLDOUT_SHEETS,
                         ((18.0, 32.0), (22.0, 28.0), (19.0, 31.0)))

    def test_holdout_rejects_invalid_or_infeasible_fixtures(self):
        invalid_cases = (
            (4.0, ()),
            (4.0, ((0.0, 30.0),)),
            (4.0, ((float("nan"), 30.0),)),
            (4.0, ((20.0, float("inf")),)),
            (9.0, ((18.0, 32.0),)),
            (4.0, ((3.0, 30.0),)),
            (float("nan"), lab.HOLDOUT_SHEETS),
        )
        for cut, holdout in invalid_cases:
            with self.subTest(cut=cut, holdout=holdout):
                with self.assertRaises(ValueError):
                    lab.evaluate(cut, holdout=holdout)

    def test_valid_holdout_results_remain_unchanged(self):
        result = lab.evaluate(4.0)
        self.assertEqual(result["holdout_improvements_cm3"],
                         [176.0, 256.0, 202.0])
        self.assertTrue(result["passed_all_holdouts"])

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

    def test_openstax_textbook_reference(self):
        # Independent published 24 x 36 example: x = 10 - 2*sqrt(7).
        # Formula works in inches here; the sandbox's sheets use centimeters.
        reference_cut = 10 - 2 * math.sqrt(7)
        reference_volume = 640 + 448 * math.sqrt(7)
        self.assertAlmostEqual(lab.box_volume(24, 36, reference_cut),
                               reference_volume, places=8)
        self.assertAlmostEqual(
            lab.continuous_training_optimum(((24, 36),)),
            reference_cut, places=8)

    def test_prior_art_is_cited_and_no_novelty_claim_is_made(self):
        report = lab.run()
        self.assertEqual(report["model_prior_art_status"],
                         "established_textbook_example")
        self.assertEqual(report["novelty_status"], "not_assessed")
        self.assertFalse(report["physical_validation"])
        self.assertIn("no patent search", report["novelty_scope"])
        sources = report["prior_art_evidence"]
        self.assertEqual(len(sources), 1)
        self.assertIn("openstax.org/books/calculus-volume-1",
                      sources[0]["url"])
        self.assertIn("20 by 30", sources[0]["known_result"])
        self.assertEqual(sources[0]["evidence_level"],
                         "established_textbook_model")

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


    def test_workload_counts_are_explicit_and_deterministic(self):
        report = lab.run()
        self.assertEqual(report["workload"], {
            "training_grid_evaluations": 144,
            "continuous_reference_evaluations": 8,
            "holdout_volume_evaluations": 12,
            "total_box_volume_evaluations": 164,
            "hypotheses_evaluated": 1,
        })
        self.assertEqual(report["workload"], lab.run()["workload"])

    def test_measured_run_uses_batched_median_and_reports_throughput(self):
        from unittest.mock import patch

        sample = {
            "workload": {
                "total_box_volume_evaluations": 164,
                "hypotheses_evaluated": 1,
            }
        }
        timings = (
            10.0, 10.1,
            20.0, 20.2,
            30.0, 30.3,
            40.0, 40.2,
            50.0, 50.5,
        )
        with patch.object(lab, "run", return_value=sample) as run_mock:
            with patch.object(lab.time, "perf_counter", side_effect=timings):
                report = lab.run_measured()

        metrics = report["performance"]
        self.assertEqual(run_mock.call_count, 5 + 5 * 100 + 1)
        self.assertEqual(metrics["benchmark_batches"], 5)
        self.assertEqual(metrics["repetitions_per_batch"], 100)
        self.assertEqual(metrics["warmup_repetitions"], 5)
        self.assertEqual(metrics["measured_repetitions"], 500)
        self.assertEqual(metrics["elapsed_seconds"], 1.3)
        self.assertEqual(metrics["median_seconds_per_run"], 0.002)
        self.assertEqual(metrics["seconds_per_hypothesis"], 0.002)
        self.assertEqual(metrics["min_seconds_per_hypothesis"], 0.001)
        self.assertEqual(metrics["max_seconds_per_hypothesis"], 0.005)
        self.assertEqual(metrics["hypotheses_per_second"], 500.0)
        self.assertEqual(metrics["box_volume_evaluations_per_second"], 82000.0)
        self.assertIn("5 batches of 100", metrics["measurement_scope"])
        self.assertIn("same code, runner, and protocol", metrics["comparability"])
        # The deterministic core report remains free of timing fields.
        self.assertNotIn("performance", lab.run())


    def test_distributional_holdout_is_reproducible_and_uses_separate_seed(self):
        candidate = lab.distributional_holdout_report(4.0, 7.5)
        repeated = lab.distributional_holdout_report(4.0, 7.5)
        changed_seed = lab.distributional_holdout_report(4.0, 7.5, seed=20261104)

        self.assertEqual(candidate, repeated)
        self.assertNotEqual(candidate["candidate"], changed_seed["candidate"])
        self.assertEqual(candidate["seed"], 20261103)
        self.assertEqual(candidate["case_count"], 200)
        self.assertEqual(candidate["width_cm_range"], [18.0, 22.0])
        self.assertEqual(candidate["height_cm_range"], [28.0, 32.0])
        self.assertEqual(candidate["box_volume_evaluations"], 600)
        self.assertEqual(candidate["candidate_cut_cm"], 4.0)
        self.assertEqual(candidate["negative_control_cut_cm"], 7.5)

        selected = candidate["candidate"]
        self.assertEqual(selected["positive_cases"], 200)
        self.assertTrue(selected["passed_all_sampled_cases"])
        self.assertAlmostEqual(selected["mean_improvement_cm3"], 232.509111, places=6)
        self.assertAlmostEqual(selected["minimum_improvement_cm3"], 133.090258, places=6)
        self.assertAlmostEqual(
            selected["fifth_percentile_nearest_rank_cm3"], 163.365045, places=6
        )
        self.assertEqual(selected["evidence_level"], "simulation_candidate")

        rejected = candidate["negative_control"]
        self.assertEqual(rejected["positive_cases"], 0)
        self.assertTrue(rejected["rejected_on_all_sampled_cases"])
        self.assertAlmostEqual(rejected["mean_improvement_cm3"], -258.650827, places=6)
        self.assertEqual(rejected["evidence_level"], "rejected_simulation_candidate")
        self.assertEqual(candidate["novelty_status"], "not_assessed")
        self.assertFalse(candidate["physical_validation"])
        self.assertIn("not a statistical population guarantee", candidate["interpretation"])

    def test_distributional_holdout_rejects_invalid_budgets_and_infeasible_cuts(self):
        invalid = (
            (4.0, 7.5, 0),
            (4.0, 7.5, True),
            (4.0, 7.5, 1.5),
            (9.0, 7.5, 200),
            (float("nan"), 7.5, 200),
            (4.0, 9.0, 200),
        )
        for candidate, negative, count in invalid:
            with self.subTest(candidate=candidate, negative=negative, count=count):
                with self.assertRaises(ValueError):
                    lab.distributional_holdout_report(candidate, negative, case_count=count)

    def test_complete_report_includes_separate_distributional_holdout(self):
        from unittest.mock import patch

        sample = {
            "seed": 2026,
            "candidate": {"cut_cm": 4.0},
            "negative_control": {"cut_cm": 7.5},
        }
        holdout = {"seed": 2027, "case_count": 200}
        with patch.object(lab, "run_measured", return_value=sample) as measured:
            with patch.object(
                lab, "distributional_holdout_report", return_value=holdout
            ) as distributional:
                report = lab.run_complete_report(seed=2026)

        measured.assert_called_once_with(2026)
        distributional.assert_called_once_with(
            candidate_cut=4.0, negative_control_cut=7.5, seed=2027
        )
        self.assertIs(report["distributional_holdout"], holdout)


if __name__ == "__main__":
    unittest.main()
