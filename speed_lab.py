"""Bounded, reproducible Monte Carlo efficiency comparison.

This tool is separate from AETHER's production research workflow. All
methods estimate pi from quarter-circle geometry with the same number of
independent sampling units, but different work per unit.
Elapsed time is measured; acceleration is never assumed.
"""

import argparse
import json
import math
import random
import statistics
import time


MAX_TOTAL_SAMPLES = 2_000_000


def circle_hits(samples, rng):
    """Baseline: two uniform random draws per point and an indicator."""
    if samples <= 0:
        raise ValueError("samples must be positive")
    hits = sum(rng.random() ** 2 + rng.random() ** 2 <= 1 for _ in range(samples))
    return 4.0 * hits / samples


def conditional_1d(samples, rng):
    """Integrate out Y analytically: E[4 * sqrt(1 - X^2)] = pi."""
    if samples <= 0:
        raise ValueError("samples must be positive")
    total = sum(math.sqrt(1.0 - (x := rng.random()) * x) for _ in range(samples))
    return 4.0 * total / samples


def antithetic_1d(samples, rng):
    """Pair X with 1-X, each marginal uniform, to reduce variance."""
    if samples <= 0:
        raise ValueError("samples must be positive")
    total = 0.0
    for _ in range(samples):
        x = rng.random()
        total += math.sqrt(1.0 - x * x) + math.sqrt(1.0 - (1.0 - x) ** 2)
    return 2.0 * total / samples


METHODS = {
    "circle_hits": circle_hits,
    "conditional_1d": conditional_1d,
    "antithetic_1d": antithetic_1d,
}


def antithetic_unit_variance_midpoint(intervals=16_384):
    """Approximate Var[2(sqrt(1-X^2)+sqrt(1-(1-X)^2))] for X~U(0,1).

    Independent antithetic *pairs* are sampling units. Their two function
    evaluations are correlated, so independent-function SE formulas are wrong.
    This fixed-grid quadrature is deterministic, not an exact analytic result.
    """
    integral = math.fsum(
        math.sqrt((1.0 - (x := (i + 0.5) / intervals) ** 2)
                  * (1.0 - (1.0 - x) ** 2))
        for i in range(intervals)
    ) / intervals
    return 16.0 / 3.0 + 8.0 * integral - math.pi ** 2


def benchmark(samples=10_000, replicates=24, seed=2026):
    """Return reproducible accuracy metrics and measured local timings.

    Monte Carlo error varies with seed, while timing varies with machine load.
    Comparisons use equal sampling-unit counts, not equal CPU work.
    This is a diagnostic benchmark, not proof of universal speedups.
    """
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise ValueError("samples must be a positive integer")
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 2:
        raise ValueError("replicates must be an integer >= 2")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if samples * replicates > MAX_TOTAL_SAMPLES:
        raise ValueError(f"samples * replicates must not exceed {MAX_TOTAL_SAMPLES:,}")

    results = {}
    for name, method in METHODS.items():
        estimates = []
        durations = []
        for i in range(replicates):
            # Fresh deterministic generator per trial; same seeds across methods.
            rng = random.Random(seed + i * 104729)
            start = time.perf_counter()
            estimate = method(samples, rng)
            elapsed = time.perf_counter() - start
            estimates.append(estimate)
            durations.append(elapsed)
        errors = [estimate - math.pi for estimate in estimates]
        # All replications average independent sampling units. The antithetic
        # unit is a correlated pair, whose variance is integrated numerically.
        unit_variance = {
            "circle_hits": 4 * math.pi - math.pi ** 2,
            "conditional_1d": 32 / 3 - math.pi ** 2,
            "antithetic_1d": antithetic_unit_variance_midpoint(),
        }[name]
        rmse = math.sqrt(statistics.mean(error * error for error in errors))
        median_time = statistics.median(durations)
        results[name] = {
            "rmse": rmse,
            "mean_absolute_error": statistics.mean(abs(error) for error in errors),
            "average_estimate": statistics.mean(estimates),
            "median_seconds_per_replication": median_time,
            "random_draws_per_sampling_unit": 2 if name == "circle_hits" else 1,
            "integrand_evaluations_per_sampling_unit": 2 if name == "antithetic_1d" else 1,
            "standard_error_basis": "numerical_midpoint_16384" if name == "antithetic_1d" else "analytic",
            "theoretical_standard_error": (
                math.sqrt(unit_variance / samples)
            ),
            # Descriptive, seed-specific error-vs-time metric; lower is better.
            "observed_rmse_squared_seconds": rmse * rmse * median_time,
        }
    baseline_rmse = results["circle_hits"]["rmse"]
    baseline_time = results["circle_hits"]["median_seconds_per_replication"]
    baseline_error_time = results["circle_hits"]["observed_rmse_squared_seconds"]
    baseline_theoretical_error_time = (
        results["circle_hits"]["theoretical_standard_error"] ** 2 * baseline_time
    )
    for value in results.values():
        # Equal-wall-time projection: extrapolate measured per-unit cost linearly.
        # This is NOT a measured fixed-time experiment; startup/cache effects and
        # machine contention can invalidate the projection.
        elapsed = value["median_seconds_per_replication"]
        value["projected_theoretical_se_at_baseline_time"] = (
            value["theoretical_standard_error"] * math.sqrt(elapsed / baseline_time)
            if baseline_time > 0 and elapsed > 0 else None
        )
        value["theoretical_error_time_efficiency_vs_baseline"] = (
            baseline_theoretical_error_time /
            (value["theoretical_standard_error"] ** 2 * elapsed)
            if elapsed > 0 else None
        )
        value["rmse_improvement_factor_vs_baseline"] = baseline_rmse / value["rmse"] if value["rmse"] else None
        value["time_speedup_factor_vs_baseline"] = baseline_time / value["median_seconds_per_replication"] if value["median_seconds_per_replication"] else None
        value["observed_error_time_efficiency_vs_baseline"] = (
            baseline_error_time / value["observed_rmse_squared_seconds"]
            if value["observed_rmse_squared_seconds"] else None
        )

    return {
        "reference": "pi",
        "target_value": math.pi,
        "samples_per_replication": samples,
        "replications": replicates,
        "seed": seed,
        "methodology": "Equal independent sampling units, not equal computation. SE is analytic for hit-or-miss and conditional estimators, and a deterministic 16384-point midpoint quadrature approximation for antithetic pairs (two integrand evaluations per unit). Projected equal-wall-time SE and theoretical error-time efficiency use measured median duration per unit and assume linear scaling; they are not measured equal-time trials. Observed RMSE^2 times median wall-time is seed- and machine-specific, not a quantum-speed claim.",
        "results": results,
    }



def benchmark_matched_time(budget_seconds=0.02, replicates=8, seed=2026):
    """Calibrate then *measure* independent trials near a common time target.

    Each method gets its own calibrated sample count. The actual wall times
    are recorded, never forced to equal the requested budget. Calibration
    overhead is excluded from trial durations and reported separately.
    """
    if (isinstance(budget_seconds, bool) or
            not isinstance(budget_seconds, (int, float)) or
            not math.isfinite(budget_seconds) or
            not 0.005 <= budget_seconds <= 0.25):
        raise ValueError("budget_seconds must be finite and between 0.005 and 0.25")
    if isinstance(replicates, bool) or not isinstance(replicates, int) or not 2 <= replicates <= 30:
        raise ValueError("replicates must be an integer between 2 and 30")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")

    results = {}
    calibration_seconds = 0.0
    # Three methods share the global sampling budget; cap each independently.
    max_samples = min(100_000, MAX_TOTAL_SAMPLES // (len(METHODS) * replicates))
    for method_index, (name, method) in enumerate(METHODS.items()):
        calibration_times = []
        for i in range(3):
            start = time.perf_counter()
            method(1000, random.Random(seed + method_index * 1009 + i))
            calibration_times.append(time.perf_counter() - start)
        calibration_seconds += sum(calibration_times)
        calibration_median = statistics.median(calibration_times)
        samples = min(max_samples, max(100, round(1000 * budget_seconds / calibration_median)))
        errors = []
        durations = []
        for i in range(replicates):
            # Distinct seeded trials; never reuse calibration generators.
            rng = random.Random(seed + 1_000_003 * (i + 1) + 9973 * method_index)
            start = time.perf_counter()
            estimate = method(samples, rng)
            durations.append(time.perf_counter() - start)
            errors.append(estimate - math.pi)
        unit_variance = {
            "circle_hits": 4 * math.pi - math.pi ** 2,
            "conditional_1d": 32 / 3 - math.pi ** 2,
            "antithetic_1d": antithetic_unit_variance_midpoint(),
        }[name]
        results[name] = {
            "sampling_units_per_replication": samples,
            "rmse": math.sqrt(statistics.mean(error * error for error in errors)),
            "theoretical_standard_error": math.sqrt(unit_variance / samples),
            "median_observed_seconds": statistics.median(durations),
            "min_observed_seconds": min(durations),
            "max_observed_seconds": max(durations),
            "sample_cap_reached": samples == max_samples,
        }
    return {
        "reference": "pi",
        "methodology": (
            "Measured trials with separately calibrated sampling-unit counts near "
            "a common wall-time target, not identical elapsed time. Calibration "
            "cost is reported separately and not included in trial durations. "
            "Method-specific work per unit differs; observed RMSE is seed-specific. "
            "No quantum, hardware-independent, or universal speed claim."
        ),
        "target_seconds_per_replication": budget_seconds,
        "replications": replicates,
        "seed": seed,
        "calibration_seconds_total": calibration_seconds,
        "results": results,
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10_000)
    parser.add_argument("--replicates", type=int, default=24)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--matched-seconds", type=float, default=None, help="Calibrated wall-time target (0.005 to 0.25 seconds) per method and trial")
    args = parser.parse_args()
    try:
        data = (benchmark_matched_time(args.matched_seconds, args.replicates, args.seed)
                if args.matched_seconds is not None else benchmark(args.samples, args.replicates, args.seed))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
