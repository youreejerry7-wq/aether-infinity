"""Scheduled, bounded statistical research. No external API keys or paid services."""
import json
import math
import random
import datetime
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "data" / "research.json"

# Significance threshold: |z| > 3.29 corresponds to two-tailed p < 0.001 (99.9% confidence)
DEFAULT_Z_THRESHOLD = 3.29


def bernoulli(n, p, rng=None, z_threshold=DEFAULT_Z_THRESHOLD):
    """
    Perform Bernoulli trial sequence and compute standard score (z-score).
    """
    if n <= 0:
        raise ValueError("Number of trials must be positive.")
    if not (0 <= p <= 1):
        raise ValueError("Probability p must be between 0 and 1.")

    if rng is None:
        rng = random.Random()

    x = sum(rng.random() < p for _ in range(n))
    observed = x / n
    std_error = math.sqrt(p * (1 - p) / n)
    z = (observed - p) / std_error if std_error > 0 else 0.0
    flag = abs(z) > z_threshold

    return {
        "category": "known_baseline",
        "observed": round(observed, 6),
        "expected": p,
        "z_score": round(z, 3),
        "trials": n,
        "z_threshold": z_threshold,
        "flag": flag,
        "description": f"Bernoulli trial with expected probability p={p}"
    }


def pi_test(n, rng=None, z_threshold=DEFAULT_Z_THRESHOLD):
    """
    Monte Carlo estimation of Pi via uniform sampling in unit square.
    """
    if n <= 0:
        raise ValueError("Number of trials must be positive.")

    if rng is None:
        rng = random.Random()

    hits = sum(rng.random() ** 2 + rng.random() ** 2 <= 1 for _ in range(n))
    estimate = 4 * hits / n
    expected_p = math.pi / 4
    # Standard error of four times a Bernoulli estimator:
    se = 4 * math.sqrt(expected_p * (1 - expected_p) / n)
    z = (estimate - math.pi) / se if se > 0 else 0.0
    flag = abs(z) > z_threshold

    return {
        "category": "known_baseline",
        "observed": round(estimate, 6),
        "expected": round(math.pi, 6),
        "z_score": round(z, 3),
        "trials": n,
        "z_threshold": z_threshold,
        "flag": flag,
        "description": "Monte Carlo unit-square quarter-circle Pi estimation"
    }


def run_research_cycle(seed=None, out_path=OUT, z_threshold=DEFAULT_Z_THRESHOLD):
    """
    Executes a complete research cycle and saves the result record.
    Returns the cycle record dict.
    """
    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed) if seed is not None else random.Random()

    experiment_defs = [
        ("Fair coin frequency", lambda: bernoulli(100000, 0.5, rng=rng, z_threshold=z_threshold)),
        ("Uniform threshold frequency", lambda: bernoulli(100000, 0.25, rng=rng, z_threshold=z_threshold)),
        ("Monte Carlo pi estimation", lambda: pi_test(100000, rng=rng, z_threshold=z_threshold)),
        ("Rare-event frequency", lambda: bernoulli(200000, 0.02, rng=rng, z_threshold=z_threshold)),
    ]

    results = []
    errors = []

    for name, exp_func in experiment_defs:
        try:
            res = exp_func()
            results.append({"name": name, **res})
        except Exception as err:
            errors.append({"name": name, "error": str(err)})

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    status = "completed" if not errors else ("partial_failure" if results else "failed")

    record = {
        "time": now,
        "status": status,
        "z_threshold": z_threshold,
        "experiments": results,
        "errors": errors,
        "interpretation": (
            f"Flags (|z| > {z_threshold}, two-tailed p < 0.001) indicate statistical fluctuations "
            "from known mathematical baselines, not scientific discoveries. Independent replication required."
        )
    }

    try:
        old_data = []
        if out_path.exists():
            content = out_path.read_text(encoding="utf-8")
            if content.strip():
                old_data = json.loads(content)
                if not isinstance(old_data, list):
                    old_data = []
    except Exception as e:
        print(f"Warning: could not read existing research log at {out_path}: {e}", file=sys.stderr)
        old_data = []

    old_data.insert(0, record)
    out_path.write_text(json.dumps(old_data[:100], indent=2) + "\n", encoding="utf-8")
    return record


if __name__ == "__main__":
    record = run_research_cycle()
    print(json.dumps(record))
