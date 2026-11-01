"""Non-production benchmark regression tests, standard library only."""

import math
import random
import unittest
from pathlib import Path

from speed_lab import (
    MAX_TOTAL_SAMPLES,
    METHODS,
    antithetic_1d,
    benchmark,
    benchmark_matched_time,
    circle_hits,
    conditional_1d,
)


class SpeedLabTests(unittest.TestCase):
    def test_methods_have_reasonable_pi_estimates(self):
        for name, method in METHODS.items():
            with self.subTest(name=name):
                self.assertLess(abs(method(20_000, random.Random(88)) - math.pi), 0.10)

    def test_methods_are_reproducible(self):
        for method in (circle_hits, conditional_1d, antithetic_1d):
            self.assertEqual(method(1000, random.Random(42)), method(1000, random.Random(42)))

    def test_validation(self):
        for method in METHODS.values():
            with self.assertRaises(ValueError):
                method(0, random.Random(7))
        for kwargs in (
            {"samples": 0},
            {"replicates": 1},
            {"samples": MAX_TOTAL_SAMPLES, "replicates": 2},
            {"samples": True},
            {"seed": 0.3},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                benchmark(**kwargs)

    def test_benchmark_reports_valid_comparative_metrics(self):
        result = benchmark(samples=1000, replicates=3, seed=2)
        self.assertEqual(result["samples_per_replication"], 1000)
        self.assertEqual(result["replications"], 3)
        self.assertEqual(set(result["results"]), set(METHODS))
        for metrics in result["results"].values():
            self.assertTrue(math.isfinite(metrics["rmse"]))
            self.assertGreaterEqual(metrics["median_seconds_per_replication"], 0)
            self.assertGreater(metrics["rmse_improvement_factor_vs_baseline"], 0)

    def test_analytic_errors_and_observed_error_time_are_explicit(self):
        data = benchmark(samples=1000, replicates=4, seed=17)
        metrics = data["results"]
        self.assertAlmostEqual(
            metrics["circle_hits"]["theoretical_standard_error"],
            math.sqrt((4 * math.pi - math.pi ** 2) / 1000),
        )
        self.assertAlmostEqual(
            metrics["conditional_1d"]["theoretical_standard_error"],
            math.sqrt((32 / 3 - math.pi ** 2) / 1000),
        )
        self.assertLess(
            metrics["conditional_1d"]["theoretical_standard_error"],
            metrics["circle_hits"]["theoretical_standard_error"],
        )
        # Deterministic quadrature of the correlated pair's second moment.
        # Reference is independently converged to ~0.10972585 per pair.
        self.assertAlmostEqual(
            metrics["antithetic_1d"]["theoretical_standard_error"] ** 2 * 1000,
            0.10972585,
            delta=0.00001,
        )
        self.assertLess(
            metrics["antithetic_1d"]["theoretical_standard_error"],
            metrics["conditional_1d"]["theoretical_standard_error"],
        )
        self.assertEqual(metrics["antithetic_1d"]["standard_error_basis"], "numerical_midpoint_16384")
        self.assertEqual(metrics["antithetic_1d"]["integrand_evaluations_per_sampling_unit"], 2)
        self.assertEqual(metrics["circle_hits"]["standard_error_basis"], "analytic")
        self.assertAlmostEqual(
            metrics["circle_hits"]["observed_error_time_efficiency_vs_baseline"], 1.0,
        )
        for result in metrics.values():
            self.assertAlmostEqual(
                result["observed_rmse_squared_seconds"],
                result["rmse"] ** 2 * result["median_seconds_per_replication"],
            )
            self.assertGreater(result["observed_error_time_efficiency_vs_baseline"], 0)

    def test_equal_wall_time_projection_is_labeled_and_algebraically_consistent(self):
        data = benchmark(samples=2000, replicates=4, seed=13)
        results = data["results"]
        baseline = results["circle_hits"]
        baseline_time = baseline["median_seconds_per_replication"]
        self.assertGreater(baseline_time, 0)
        self.assertAlmostEqual(
            baseline["projected_theoretical_se_at_baseline_time"],
            baseline["theoretical_standard_error"], places=12,
        )
        self.assertAlmostEqual(
            baseline["theoretical_error_time_efficiency_vs_baseline"], 1.0,
            places=12,
        )
        for name, metrics in results.items():
            with self.subTest(name=name):
                expected = metrics["theoretical_standard_error"] * math.sqrt(
                    metrics["median_seconds_per_replication"] / baseline_time
                )
                self.assertAlmostEqual(
                    metrics["projected_theoretical_se_at_baseline_time"],
                    expected, places=12,
                )
                self.assertGreater(metrics["theoretical_error_time_efficiency_vs_baseline"], 0)
        self.assertIn("not measured equal-time trials", data["methodology"])

    def test_standard_errors_scale_with_independent_units(self):
        small = benchmark(samples=400, replicates=2, seed=9)
        large = benchmark(samples=1600, replicates=2, seed=9)
        for name in METHODS:
            with self.subTest(name=name):
                self.assertAlmostEqual(
                    small["results"][name]["theoretical_standard_error"],
                    2 * large["results"][name]["theoretical_standard_error"],
                    places=12,
                )


    def test_matched_time_trials_are_bounded_and_labeled(self):
        data = benchmark_matched_time(budget_seconds=0.005, replicates=2, seed=31)
        self.assertEqual(data["replications"], 2)
        self.assertEqual(data["seed"], 31)
        self.assertIn("not identical elapsed time", data["methodology"])
        self.assertGreater(data["calibration_seconds_total"], 0)
        self.assertEqual(set(data["results"]), set(METHODS))
        total_units = 0
        for name, metrics in data["results"].items():
            with self.subTest(name=name):
                n = metrics["sampling_units_per_replication"]
                total_units += n * data["replications"]
                self.assertGreaterEqual(n, 100)
                self.assertLessEqual(n, 100_000)
                self.assertGreater(metrics["median_observed_seconds"], 0)
                self.assertLessEqual(metrics["min_observed_seconds"],
                                     metrics["median_observed_seconds"])
                self.assertLessEqual(metrics["median_observed_seconds"],
                                     metrics["max_observed_seconds"])
                self.assertTrue(math.isfinite(metrics["rmse"]))
                self.assertGreater(metrics["theoretical_standard_error"], 0)
        self.assertLessEqual(total_units, MAX_TOTAL_SAMPLES)

    def test_matched_time_rejects_unbounded_inputs(self):
        for kwargs in (
            {"budget_seconds": 0},
            {"budget_seconds": 0.5},
            {"budget_seconds": float("nan")},
            {"budget_seconds": True},
            {"replicates": 1},
            {"replicates": 31},
            {"replicates": True},
            {"seed": 1.1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                benchmark_matched_time(**kwargs)

    def test_does_not_write_research_archive(self):
        # The script is an isolated, pure experiment; no output persisted.
        before = Path("data/research.json")
        was_present = before.exists()
        benchmark(samples=100, replicates=2)
        self.assertEqual(before.exists(), was_present)


if __name__ == "__main__":
    unittest.main()
