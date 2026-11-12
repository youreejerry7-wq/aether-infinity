"""Bounded, reproducible Monte Carlo efficiency comparison.

This tool is separate from AETHER's production research workflow. All
methods estimate pi from quarter-circle geometry with the same number of
independent sampling units, but different work per unit.
Elapsed time is measured; acceleration is never assumed.
"""

import argparse
import json
import math
import os
import platform
import random
import statistics
import time


MAX_TOTAL_SAMPLES = 2_000_000
MAX_REPLICATES = 1_000
ANTITHETIC_VARIANCE_INTERVALS = 16_384


def benchmark_environment():
    """Non-identifying runtime context for interpreting local timing results."""
    return {
        "python_version": platform.python_version(),
        "os_family": platform.system(),
        "machine_architecture": platform.machine(),
        "logical_cpu_count_reported": os.cpu_count(),
        "perf_counter_resolution_seconds": time.get_clock_info("perf_counter").resolution,
        "caveat": (
            "CPU quotas, processor model, background load and energy use "
            "are not measured; timings are not portable hardware benchmarks."
        ),
    }


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


def antithetic_unit_variance_midpoint(intervals=ANTITHETIC_VARIANCE_INTERVALS):
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
    if replicates > MAX_REPLICATES:
        raise ValueError(f"replicates must not exceed {MAX_REPLICATES:,}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if samples * replicates * len(METHODS) > MAX_TOTAL_SAMPLES:
        raise ValueError(f"total sampling units across all methods must not exceed {MAX_TOTAL_SAMPLES:,}")

    # Report shared reference setup separately from per-method trial timings.
    variance_setup_start = time.perf_counter()
    antithetic_variance = antithetic_unit_variance_midpoint()
    variance_reference_setup_seconds = time.perf_counter() - variance_setup_start
    unit_variances = {
        "circle_hits": 4 * math.pi - math.pi ** 2,
        "conditional_1d": 32 / 3 - math.pi ** 2,
        "antithetic_1d": antithetic_variance,
    }
    results = {}
    trial_data = {
        name: {"estimates": [], "durations": []}
        for name in METHODS
    }
    execution_order = []
    order_rng = random.Random(seed ^ 0x5EED5EED)
    # Interleave methods in a deterministic shuffled order per replication.
    # Each method keeps the same per-replication RNG seed as before.
    for i in range(replicates):
        names = list(METHODS)
        order_rng.shuffle(names)
        execution_order.append(names)
        for name in names:
            method = METHODS[name]
            rng = random.Random(seed + i * 104729)
            start = time.perf_counter()
            estimate = method(samples, rng)
            elapsed = time.perf_counter() - start
            trial_data[name]["estimates"].append(estimate)
            trial_data[name]["durations"].append(elapsed)

    for name, data in trial_data.items():
        estimates = data["estimates"]
        durations = data["durations"]
        errors = [estimate - math.pi for estimate in estimates]
        # All replications average independent sampling units. The antithetic
        # unit is a correlated pair, whose variance is integrated numerically.
        unit_variance = unit_variances[name]
        rmse = math.sqrt(statistics.mean(error * error for error in errors))
        median_time = statistics.median(durations)
        results[name] = {
            "rmse": rmse,
            "mean_absolute_error": statistics.mean(abs(error) for error in errors),
            "average_estimate": statistics.mean(estimates),
            "median_seconds_per_replication": median_time,
            "sampling_units_per_second": samples / median_time if median_time > 0 else None,
            "integrand_evaluations_per_second": (
                samples * (2 if name == "antithetic_1d" else 1) / median_time
                if median_time > 0 else None
            ),
            "random_draws_per_sampling_unit": 2 if name == "circle_hits" else 1,
            "integrand_evaluations_per_sampling_unit": 2 if name == "antithetic_1d" else 1,
            "standard_error_basis": "numerical_midpoint_16384" if name == "antithetic_1d" else "analytic",
            "theoretical_standard_error": math.sqrt(unit_variance / samples),
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
        "environment": benchmark_environment(),
        "variance_reference_setup": {
            "method": "deterministic_midpoint_quadrature",
            "quadrature_points": ANTITHETIC_VARIANCE_INTERVALS,
            "elapsed_seconds": variance_reference_setup_seconds,
            "included_in_per_method_trial_times": False,
        },
        "reference": "pi",
        "target_value": math.pi,
        "samples_per_replication": samples,
        "replications": replicates,
        "seed": seed,
        "execution_order_by_replication": execution_order,
        "methodology": "Equal independent sampling units, not equal computation; methods are deterministically shuffled and interleaved per replication to reduce fixed-order timing bias. SE is analytic for hit-or-miss and conditional estimators, and a deterministic 16384-point midpoint quadrature approximation for antithetic pairs (two integrand evaluations per unit). Projected equal-wall-time SE and theoretical error-time efficiency use measured median duration per unit and assume linear scaling; they are not measured equal-time trials. Observed RMSE^2 times median wall-time is seed- and machine-specific, not a quantum-speed claim.",
        "results": results,
    }



def allocate_sampling_budget(requested_samples, replicates, calibration_units):
    """Proportionally scale validated method counts within the shared compute cap."""
    if not isinstance(requested_samples, dict) or not requested_samples:
        raise ValueError("requested_samples must be a nonempty dictionary")
    if len(requested_samples) > len(METHODS):
        raise ValueError("requested_samples cannot exceed the number of benchmark methods")
    if (isinstance(replicates, bool) or not isinstance(replicates, int)
            or not 1 <= replicates <= MAX_REPLICATES):
        raise ValueError(f"replicates must be an integer between 1 and {MAX_REPLICATES:,}")
    if (isinstance(calibration_units, bool) or not isinstance(calibration_units, int)
            or not 0 <= calibration_units <= MAX_TOTAL_SAMPLES):
        raise ValueError("calibration_units must be an integer within the shared sampling budget")
    for name, samples in requested_samples.items():
        if name not in METHODS:
            raise ValueError(f"unknown benchmark method: {name!r}")
        if (isinstance(samples, bool) or not isinstance(samples, int)
                or not 1 <= samples <= MAX_TOTAL_SAMPLES):
            raise ValueError("requested sampling units must be positive bounded integers")
    available_units = MAX_TOTAL_SAMPLES - calibration_units
    # Divide the shared remaining budget across replicates, not equally per method;
    # unused capacity from faster methods remains available to the others.
    available_per_replication = available_units // replicates
    requested_total = sum(requested_samples.values())
    if requested_total <= available_per_replication:
        return dict(requested_samples), 1.0
    if requested_total <= 0:
        raise ValueError("requested sampling units must be positive")
    scale = available_per_replication / requested_total
    allocated = {
        name: max(100, math.floor(samples * scale))
        for name, samples in requested_samples.items()
    }
    while sum(allocated.values()) > available_per_replication:
        largest = max(allocated, key=allocated.get)
        if allocated[largest] <= 100:
            raise ValueError("sampling budget is too small for minimum method samples")
        allocated[largest] -= 1
    return allocated, scale


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

    # Report shared reference setup separately from per-method trial timings.
    variance_setup_start = time.perf_counter()
    antithetic_variance = antithetic_unit_variance_midpoint()
    variance_reference_setup_seconds = time.perf_counter() - variance_setup_start
    unit_variances = {
        "circle_hits": 4 * math.pi - math.pi ** 2,
        "conditional_1d": 32 / 3 - math.pi ** 2,
        "antithetic_1d": antithetic_variance,
    }
    results = {}
    calibration_seconds = 0.0
    # Include calibration calls in the global sampling-unit budget.
    calibration_units_per_method = 3 * 1000
    calibration_units = len(METHODS) * calibration_units_per_method
    method_names = list(METHODS)
    method_indices = {name: index for index, name in enumerate(method_names)}

    # Shuffle calibration calls across methods so one method is not always
    # calibrated first under a different warm-up or background-load state.
    calibration_times_by_method = {name: [] for name in method_names}
    calibration_order = [
        (name, trial)
        for name in method_names
        for trial in range(3)
    ]
    calibration_order_rng = random.Random(seed ^ 0xCA1B4A7E)
    calibration_order_rng.shuffle(calibration_order)
    for name, trial in calibration_order:
        method_index = method_indices[name]
        rng = random.Random(seed + method_index * 1009 + trial)
        start = time.perf_counter()
        METHODS[name](1000, rng)
        calibration_times_by_method[name].append(time.perf_counter() - start)
    calibration_seconds = sum(
        sum(times) for times in calibration_times_by_method.values()
    )

    requested_samples_by_method = {}
    for name, calibration_times in calibration_times_by_method.items():
        calibration_median = statistics.median(calibration_times)
        requested_samples_by_method[name] = min(
            100_000,
            max(100, round(1000 * budget_seconds / calibration_median)),
        )
    samples_by_method, budget_scale_factor = allocate_sampling_budget(
        requested_samples_by_method, replicates, calibration_units
    )

    # Interleave measured trials with a deterministic shuffled schedule.
    # Each method retains its own deterministic RNG seed for each replicate.
    trial_data = {name: {"errors": [], "durations": []} for name in method_names}
    trial_order = [
        (name, trial)
        for name in method_names
        for trial in range(replicates)
    ]
    trial_order_rng = random.Random(seed ^ 0x5EED5EED)
    trial_order_rng.shuffle(trial_order)
    for name, trial in trial_order:
        method_index = method_indices[name]
        samples = samples_by_method[name]
        rng = random.Random(seed + 1_000_003 * (trial + 1) + 9973 * method_index)
        start = time.perf_counter()
        estimate = METHODS[name](samples, rng)
        elapsed = time.perf_counter() - start
        trial_data[name]["durations"].append(elapsed)
        trial_data[name]["errors"].append(estimate - math.pi)

    for name in method_names:
        samples = samples_by_method[name]
        errors = trial_data[name]["errors"]
        durations = trial_data[name]["durations"]
        unit_variance = unit_variances[name]
        median_observed = statistics.median(durations)
        rmse = math.sqrt(statistics.mean(error * error for error in errors))
        theoretical_se = math.sqrt(unit_variance / samples)
        results[name] = {
            "sampling_units_per_replication": samples,
            "sampling_units_per_second": (
                samples / median_observed if median_observed > 0 else None
            ),
            "random_draws_per_sampling_unit": 2 if name == "circle_hits" else 1,
            "integrand_evaluations_per_sampling_unit": 2 if name == "antithetic_1d" else 1,
            "random_draws_per_second": (
                samples * (2 if name == "circle_hits" else 1) / median_observed
                if median_observed > 0 else None
            ),
            "integrand_evaluations_per_second": (
                samples * (2 if name == "antithetic_1d" else 1) / median_observed
                if median_observed > 0 else None
            ),
            "rmse": rmse,
            "theoretical_standard_error": theoretical_se,
            "standard_error_basis": (
                "numerical_midpoint_16384" if name == "antithetic_1d" else "analytic"
            ),
            "median_observed_seconds": median_observed,
            "observed_rmse_squared_seconds": rmse * rmse * median_observed,
            "theoretical_standard_error_squared_seconds": (
                theoretical_se * theoretical_se * median_observed
            ),
            "min_observed_seconds": min(durations),
            "max_observed_seconds": max(durations),
            "requested_sampling_units_per_replication": requested_samples_by_method[name],
            "sample_cap_reached": samples < requested_samples_by_method[name],
        }

    # Make the accuracy-versus-time tradeoff explicit for each matched-time
    # method. Observed RMSE is seed/replicate-specific; theoretical SE is
    # model-based (with numerical quadrature for antithetic pairs).
    baseline_observed_error_time = results["circle_hits"]["observed_rmse_squared_seconds"]
    baseline_theoretical_error_time = (
        results["circle_hits"]["theoretical_standard_error_squared_seconds"]
    )
    for metrics in results.values():
        metrics["observed_error_time_efficiency_vs_baseline"] = (
            baseline_observed_error_time / metrics["observed_rmse_squared_seconds"]
            if metrics["observed_rmse_squared_seconds"] > 0 else None
        )
        metrics["theoretical_error_time_efficiency_vs_baseline"] = (
            baseline_theoretical_error_time
            / metrics["theoretical_standard_error_squared_seconds"]
            if metrics["theoretical_standard_error_squared_seconds"] > 0 else None
        )

    return {
        "environment": benchmark_environment(),
        "variance_reference_setup": {
            "method": "deterministic_midpoint_quadrature",
            "quadrature_points": ANTITHETIC_VARIANCE_INTERVALS,
            "elapsed_seconds": variance_reference_setup_seconds,
            "included_in_per_method_trial_times": False,
        },
        "reference": "pi",
        "methodology": (
            "Measured trials with separately calibrated sampling-unit counts near "
            "a common wall-time target, not identical elapsed time. Calibration "
            "cost is reported separately and not included in trial durations. "
            "Calibrated per-method counts are proportionally scaled only if their aggregate exceeds the shared budget; requested and allocated counts are reported. "
            "Method-specific random draws and integrand evaluations per unit are reported; "
            "observed RMSE is seed-specific. Matched-time reports include observed RMSE^2*time "
            "and model-based SE^2*time efficiency ratios versus the hit-or-miss baseline. "
            "Calibration and measured trials are deterministically shuffled across methods to reduce fixed-order timing bias. "
            "No quantum, hardware-independent, or universal speed claim."
        ),
        "target_seconds_per_replication": budget_seconds,
        "replications": replicates,
        "seed": seed,
        "calibration_execution_order": calibration_order,
        "trial_execution_order": trial_order,
        "calibration_seconds_total": calibration_seconds,
        "calibration_sampling_units": calibration_units,
        "total_sampling_units_including_calibration": (
            calibration_units + replicates * sum(
                item["sampling_units_per_replication"] for item in results.values()
            )
        ),
        "total_random_draws_including_calibration": sum(
            (calibration_units_per_method + replicates * item["sampling_units_per_replication"])
            * (2 if name == "circle_hits" else 1)
            for name, item in results.items()
        ),
        "total_integrand_evaluations_including_calibration": sum(
            (calibration_units_per_method + replicates * item["sampling_units_per_replication"])
            * (2 if name == "antithetic_1d" else 1)
            for name, item in results.items()
        ),
        "sampling_budget_scale_factor": budget_scale_factor,
        "sampling_unit_budget": MAX_TOTAL_SAMPLES,
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
