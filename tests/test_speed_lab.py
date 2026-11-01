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

    def test_does_not_write_research_archive(self):
        # The script is an isolated, pure experiment; no output persisted.
        before = Path("data/research.json")
        was_present = before.exists()
        benchmark(samples=100, replicates=2)
        self.assertEqual(before.exists(), was_present)


if __name__ == "__main__":
    unittest.main()
