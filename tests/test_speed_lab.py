"""Non-production benchmark regression tests, standard library only."""

import math
import random
import unittest
from pathlib import Path

from speed_lab import (
    MAX_REPLICATES,
    MAX_TOTAL_SAMPLES,
    METHODS,
    allocate_sampling_budget,
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

    def test_benchmark_interleaves_methods_reproducibly(self):
        first = benchmark(samples=300, replicates=6, seed=77)
        second = benchmark(samples=300, replicates=6, seed=77)
        orders = first["execution_order_by_replication"]

        self.assertEqual(orders, second["execution_order_by_replication"])
        self.assertGreater(len({tuple(order) for order in orders}), 1)
        for order in orders:
            self.assertCountEqual(order, METHODS)
        # Execution order must not change the seeded estimator results.
        for name in METHODS:
            self.assertEqual(
                first["results"][name]["average_estimate"],
                second["results"][name]["average_estimate"],
            )

    def test_validation(self):
        for method in METHODS.values():
            with self.assertRaises(ValueError):
                method(0, random.Random(7))
        for kwargs in (
            {"samples": 0},
            {"replicates": 1},
            # Tiny sample counts must not permit unbounded result/order arrays.
            {"samples": 1, "replicates": MAX_REPLICATES + 1},
            {"samples": MAX_TOTAL_SAMPLES, "replicates": 2},
            # Each of the three methods counts against the shared budget.
            {"samples": 250_000, "replicates": 3},
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
        self.assertEqual(len(data["calibration_execution_order"]), 9)
        self.assertEqual(len(data["trial_execution_order"]), len(METHODS) * 2)
        for name in METHODS:
            self.assertEqual(
                sum(item[0] == name for item in data["calibration_execution_order"]),
                3,
            )
            self.assertEqual(
                sum(item[0] == name for item in data["trial_execution_order"]),
                2,
            )
        repeated = benchmark_matched_time(budget_seconds=0.005, replicates=2, seed=31)
        self.assertEqual(data["calibration_execution_order"], repeated["calibration_execution_order"])
        self.assertEqual(data["trial_execution_order"], repeated["trial_execution_order"])
        self.assertIn("shuffled", data["methodology"])
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
                self.assertLessEqual(
                    n, metrics["requested_sampling_units_per_replication"]
                )
                self.assertEqual(
                    metrics["sample_cap_reached"],
                    n < metrics["requested_sampling_units_per_replication"],
                )
                self.assertGreater(metrics["median_observed_seconds"], 0)
                self.assertLessEqual(metrics["min_observed_seconds"],
                                     metrics["median_observed_seconds"])
                self.assertLessEqual(metrics["median_observed_seconds"],
                                     metrics["max_observed_seconds"])
                self.assertTrue(math.isfinite(metrics["rmse"]))
                self.assertGreater(metrics["theoretical_standard_error"], 0)
                self.assertAlmostEqual(
                    metrics["observed_rmse_squared_seconds"],
                    metrics["rmse"] ** 2 * metrics["median_observed_seconds"],
                )
                self.assertAlmostEqual(
                    metrics["theoretical_standard_error_squared_seconds"],
                    metrics["theoretical_standard_error"] ** 2
                    * metrics["median_observed_seconds"],
                )
                self.assertGreater(
                    metrics["observed_error_time_efficiency_vs_baseline"], 0
                )
                self.assertGreater(
                    metrics["theoretical_error_time_efficiency_vs_baseline"], 0
                )
                expected_basis = (
                    "numerical_midpoint_16384" if name == "antithetic_1d" else "analytic"
                )
                self.assertEqual(metrics["standard_error_basis"], expected_basis)
                expected_draws = 2 if name == "circle_hits" else 1
                expected_evaluations = 2 if name == "antithetic_1d" else 1
                self.assertEqual(metrics["random_draws_per_sampling_unit"], expected_draws)
                self.assertEqual(metrics["integrand_evaluations_per_sampling_unit"], expected_evaluations)
                self.assertAlmostEqual(
                    metrics["random_draws_per_second"] * metrics["median_observed_seconds"],
                    n * expected_draws, places=6,
                )
                self.assertAlmostEqual(
                    metrics["integrand_evaluations_per_second"] * metrics["median_observed_seconds"],
                    n * expected_evaluations, places=6,
                )
        self.assertAlmostEqual(
            data["results"]["circle_hits"]["observed_error_time_efficiency_vs_baseline"],
            1.0,
        )
        self.assertAlmostEqual(
            data["results"]["circle_hits"]["theoretical_error_time_efficiency_vs_baseline"],
            1.0,
        )
        expected_random_draws = sum(
            (3_000 + data["replications"] * item["sampling_units_per_replication"])
            * (2 if name == "circle_hits" else 1)
            for name, item in data["results"].items()
        )
        expected_integrand_evaluations = sum(
            (3_000 + data["replications"] * item["sampling_units_per_replication"])
            * (2 if name == "antithetic_1d" else 1)
            for name, item in data["results"].items()
        )
        self.assertEqual(data["total_random_draws_including_calibration"], expected_random_draws)
        self.assertEqual(data["total_integrand_evaluations_including_calibration"], expected_integrand_evaluations)
        self.assertLessEqual(total_units, MAX_TOTAL_SAMPLES)
        self.assertEqual(data["calibration_sampling_units"], 9_000)
        self.assertEqual(data["total_sampling_units_including_calibration"],
                         total_units + data["calibration_sampling_units"])
        self.assertLessEqual(data["total_sampling_units_including_calibration"],
                             data["sampling_unit_budget"])
        self.assertEqual(data["sampling_unit_budget"], MAX_TOTAL_SAMPLES)
        self.assertGreater(data["sampling_budget_scale_factor"], 0.0)
        self.assertLessEqual(data["sampling_budget_scale_factor"], 1.0)

    def test_shared_budget_rejects_invalid_inputs(self):
        invalid_cases = (
            ({}, 1, 0),
            ([], 1, 0),
            ({"circle_hits": 0}, 1, 0),
            ({"circle_hits": -1}, 1, 0),
            ({"circle_hits": True}, 1, 0),
            ({"circle_hits": 1.5}, 1, 0),
            ({"circle_hits": MAX_TOTAL_SAMPLES + 1}, 1, 0),
            ({"circle_hits": 1}, 0, 0),
            ({"circle_hits": 1}, True, 0),
            ({"circle_hits": 1}, MAX_REPLICATES + 1, 0),
            ({"circle_hits": 1}, 1, -1),
            ({"circle_hits": 1}, 1, MAX_TOTAL_SAMPLES + 1),
            ({"": 1}, 1, 0),
            ({"unknown_method": 1}, 1, 0),
            ({1: 1}, 1, 0),
            ({"a": 1, "b": 1, "c": 1, "d": 1}, 1, 0),
        )
        for requested, replicates, calibration_units in invalid_cases:
            with self.subTest(
                requested=requested,
                replicates=replicates,
                calibration_units=calibration_units,
            ):
                with self.assertRaises(ValueError):
                    allocate_sampling_budget(requested, replicates, calibration_units)

    def test_shared_budget_scales_aggregate_only_when_needed(self):
        requested = {
            "circle_hits": 32_431,
            "conditional_1d": 60_000,
            "antithetic_1d": 38_831,
        }
        allocated, scale = allocate_sampling_budget(requested, 15, 9_000)
        self.assertEqual(scale, 1.0)
        self.assertEqual(allocated, requested)
        self.assertLessEqual(9_000 + 15 * sum(allocated.values()), MAX_TOTAL_SAMPLES)

        oversized = {name: 100_000 for name in METHODS}
        replicates = 15
        allocated, scale = allocate_sampling_budget(oversized, replicates, 9_000)
        self.assertLess(scale, 1.0)
        self.assertTrue(all(allocated[name] < oversized[name] for name in oversized))
        total = 9_000 + replicates * sum(allocated.values())
        self.assertLessEqual(total, MAX_TOTAL_SAMPLES)
        # Integer per-replication allocation can leave fewer than one
        # sampling unit per method per replicate unused.
        self.assertLess(MAX_TOTAL_SAMPLES - total, replicates * len(METHODS))
        self.assertGreaterEqual(min(allocated.values()), 100)

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

    def test_runtime_context_and_measured_sampling_throughput(self):
        # These metrics describe this machine/run, not a universal speedup.
        reports = [
            benchmark(samples=300, replicates=2, seed=5),
            benchmark_matched_time(budget_seconds=0.005, replicates=2, seed=5),
        ]
        for report in reports:
            with self.subTest(mode=report["methodology"][:32]):
                env = report["environment"]
                self.assertTrue(env["python_version"])
                self.assertTrue(env["os_family"])
                self.assertTrue(env["machine_architecture"])
                self.assertGreater(env["perf_counter_resolution_seconds"], 0)
                self.assertIn("not measured", env["caveat"])
                for name, metrics in report["results"].items():
                    n = metrics.get(
                        "sampling_units_per_replication",
                        report.get("samples_per_replication"),
                    )
                    duration = metrics.get(
                        "median_observed_seconds",
                        metrics.get("median_seconds_per_replication"),
                    )
                    self.assertGreater(duration, 0)
                    self.assertAlmostEqual(
                        metrics["sampling_units_per_second"] * duration,
                        n, places=6,
                    )
                    if "integrand_evaluations_per_second" in metrics:
                        evaluations_per_unit = 2 if name == "antithetic_1d" else 1
                        self.assertAlmostEqual(
                            metrics["integrand_evaluations_per_second"] * duration,
                            n * evaluations_per_unit, places=6,
                        )

    def test_does_not_write_research_archive(self):
        # The script is an isolated, pure experiment; no output persisted.
        before = Path("data/research.json")
        was_present = before.exists()
        benchmark(samples=100, replicates=2)
        self.assertEqual(before.exists(), was_present)


    def test_matched_time_calibration_excludes_rng_setup(self):
        """Calibration and measured trials time the estimator, not RNG setup."""
        from unittest.mock import patch
        import speed_lab

        events = []
        ticks = iter(range(1000))

        def fake_clock():
            events.append("clock")
            return next(ticks) * 0.001

        class TrackingRandom:
            def __init__(self, seed):
                events.append("rng")

            def shuffle(self, values):
                # The benchmark also uses seeded RNGs for its deterministic
                # interleaving schedule; keep this test focused on timer order.
                values.reverse()

        def stub_method(samples, rng):
            events.append("method")
            return math.pi

        methods = {
            "circle_hits": stub_method,
            "conditional_1d": stub_method,
            "antithetic_1d": stub_method,
        }
        with patch.object(speed_lab, "METHODS", methods), \
             patch.object(speed_lab.time, "perf_counter", side_effect=fake_clock), \
             patch.object(speed_lab.random, "Random", TrackingRandom):
            speed_lab.benchmark_matched_time(
                budget_seconds=0.005, replicates=2, seed=1
            )

        # The two leading clock events measure shared quadrature setup.
        self.assertEqual(events[:2], ["clock", "clock"])
        # The next event creates the deterministic calibration-order RNG.
        # Each method RNG is created before its estimator timer starts.
        self.assertEqual(events[3:15], ["rng", "clock", "method", "clock"] * 3)


    def test_antithetic_variance_quadrature_runs_once_per_report(self):
        from unittest.mock import patch
        import speed_lab

        with patch.object(speed_lab, "antithetic_unit_variance_midpoint", return_value=0.109) as estimate:
            benchmark(samples=100, replicates=2, seed=11)
            estimate.assert_called_once_with()

        with patch.object(speed_lab, "antithetic_unit_variance_midpoint", return_value=0.109) as estimate:
            benchmark_matched_time(budget_seconds=0.005, replicates=2, seed=11)
            estimate.assert_called_once_with()


    def test_variance_reference_setup_cost_is_reported_separately(self):
        reports = (
            benchmark(samples=100, replicates=2, seed=5),
            benchmark_matched_time(budget_seconds=0.005, replicates=2, seed=5),
        )
        for report in reports:
            setup = report["variance_reference_setup"]
            self.assertEqual(setup["method"], "deterministic_midpoint_quadrature")
            self.assertEqual(setup["quadrature_points"], 16_384)
            self.assertGreaterEqual(setup["elapsed_seconds"], 0.0)
            self.assertFalse(setup["included_in_per_method_trial_times"])


if __name__ == "__main__":
    unittest.main()
