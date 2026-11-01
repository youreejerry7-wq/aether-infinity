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
        results[name] = {
            "rmse": math.sqrt(statistics.mean(error * error for error in errors)),
            "mean_absolute_error": statistics.mean(abs(error) for error in errors),
            "average_estimate": statistics.mean(estimates),
            "median_seconds_per_replication": statistics.median(durations),
            "random_draws_per_sampling_unit": 2 if name == "circle_hits" else 1,
        }
    baseline_rmse = results["circle_hits"]["rmse"]
    baseline_time = results["circle_hits"]["median_seconds_per_replication"]
    for value in results.values():
        value["rmse_improvement_factor_vs_baseline"] = baseline_rmse / value["rmse"] if value["rmse"] else None
        value["time_speedup_factor_vs_baseline"] = baseline_time / value["median_seconds_per_replication"] if value["median_seconds_per_replication"] else None

    return {
        "reference": "pi",
        "target_value": math.pi,
        "samples_per_replication": samples,
        "replications": replicates,
        "seed": seed,
        "methodology": "Equal independent sampling units, not equal computation; random errors and runtime vary. No quantum hardware.",
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=10_000)
    parser.add_argument("--replicates", type=int, default=24)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    try:
        data = benchmark(args.samples, args.replicates, args.seed)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
