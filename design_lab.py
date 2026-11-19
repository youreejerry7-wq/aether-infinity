"""Bounded, reproducible design-search sandbox: open-top paper box volume.

Pure geometry and synthetic dimensions; not a physical invention or novelty claim.
Cut equal squares of side x from the corners of a W-by-H sheet, fold sides:
V(W, H, x) = x (W - 2x) (H - 2x), for 0 < x < min(W, H)/2.

Candidate selection sees ONLY seeded training cases. Fixed holdout cases are
evaluated AFTER selection and are never used to rank candidates.
"""
import json
import math
import random
import statistics
import os
import platform
import time
from numbers import Real

SEED = 20261102
TRAIN_CASES = 8
TRAIN_SHEET = (20.0, 30.0)
HOLDOUT_SHEETS = ((18.0, 32.0), (22.0, 28.0), (19.0, 31.0))
CUT_GRID = tuple(step / 2 for step in range(1, 19))  # 0.5 to 9.0 cm
BASELINE_CUT = 2.0
NEGATIVE_CONTROL_CUT = 7.5  # Feasible on every holdout; intentionally suboptimal

BENCHMARK_WARMUP_REPETITIONS = 5
BENCHMARK_BATCHES = 5
BENCHMARK_REPETITIONS_PER_BATCH = 100
MAX_DISTRIBUTIONAL_HOLDOUT_CASES = 5000

# Checked against the cited public textbook example on 2026-11-02.
# This establishes that the mathematical model is prior art, not a new invention.
PRIOR_ART = (
    {
        "source": "OpenStax, Calculus Volume 1, section 4.7, Example 4.33 and Checkpoint 4.32",
        "url": "https://openstax.org/books/calculus-volume-1/pages/4-7-applied-optimization-problems",
        "checked_utc_date": "2026-11-02",
        "known_result": "The corner-cut open-top box volume formula and its calculus optimum are textbook examples; the checkpoint explicitly uses a 20 by 30 sheet.",
        "evidence_level": "established_textbook_model",
    },
)


def _validate_seed(seed):
    """Require a reproducible unsigned 64-bit integer seed."""
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
        raise ValueError("seed must be an unsigned 64-bit integer")
    return seed


def _is_finite_real(value):
    """Accept finite real dimensions/cuts, but reject bool and non-numeric inputs."""
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def box_volume(width, height, cut):
    """Model volume in cm^3; invalid geometry has zero usable volume."""
    if not all(_is_finite_real(value) for value in (width, height, cut)): 
        return 0.0
    if width <= 0 or height <= 0 or not 0 < cut < min(width, height) / 2:
        return 0.0
    return cut * (width - 2 * cut) * (height - 2 * cut)


def training_sheets(seed=SEED):
    """Seeded bounded perturbations, independent of the fixed holdout."""
    seed = _validate_seed(seed)
    rng = random.Random(seed)
    return tuple(
        (TRAIN_SHEET[0] + rng.uniform(-0.5, 0.5),
         TRAIN_SHEET[1] + rng.uniform(-0.5, 0.5))
        for _ in range(TRAIN_CASES)
    )


def mean_volume(sheets, cut):
    return statistics.fmean(box_volume(w, h, cut) for w, h in sheets)


def continuous_training_optimum(sheets):
    """Analytic reference for the mean cubic volume on feasible training sheets.

    d(mean V)/dx = mean(W*H) - 4*mean(W+H)*x + 12*x*x.
    The smaller stationary root maximizes volume within the common feasible
    interval. This is an oracle for this known geometry, not an invention.
    """
    if not sheets or any(
        not (_is_finite_real(w) and _is_finite_real(h) and w > 0 and h > 0)
        for w, h in sheets
    ):
        raise ValueError("Expected nonempty finite positive sheet dimensions")
    sum_dimensions = statistics.fmean(w + h for w, h in sheets)
    area = statistics.fmean(w * h for w, h in sheets)
    discriminant = sum_dimensions ** 2 - 3 * area
    optimum = (sum_dimensions - math.sqrt(discriminant)) / 6
    if not 0 < optimum < min(min(w, h) for w, h in sheets) / 2:
        raise ValueError("Continuous optimum outside common feasible range")
    return optimum


def evaluate(cut, holdout=HOLDOUT_SHEETS):
    """Holdout check versus a predeclared baseline; no training score used."""
    # Reject invalid test fixtures rather than silently scoring zero-volume
    # geometry as a meaningful failure or success.
    if not holdout or not _is_finite_real(cut) or cut <= 0:
        raise ValueError("Expected nonempty holdout and finite positive cut")
    for width, height in holdout:
        if not all(_is_finite_real(v) for v in (width, height)):
            raise ValueError("Holdout dimensions must be finite")
        if not 0 < BASELINE_CUT < min(width, height) / 2 or not 0 < cut < min(width, height) / 2:
            raise ValueError("Both baseline and candidate cuts must be feasible")
    baseline = [box_volume(w, h, BASELINE_CUT) for w, h in holdout]
    candidate = [box_volume(w, h, cut) for w, h in holdout]
    differences = [a - b for a, b in zip(candidate, baseline)]
    return {
        "cut_cm": cut,
        "holdout_volumes_cm3": candidate,
        "baseline_volumes_cm3": baseline,
        "holdout_improvements_cm3": differences,
        "mean_holdout_improvement_cm3": statistics.fmean(differences),
        "minimum_holdout_improvement_cm3": min(differences),
        "passed_all_holdouts": all(delta > 0 for delta in differences),
    }


def _validate_dimension_range(bounds, name):
    """Validate a closed positive two-value dimension range."""
    if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
        raise ValueError(f"{name} must contain exactly two dimensions")
    low, high = bounds
    if (
        not _is_finite_real(low)
        or not _is_finite_real(high)
        or low <= 0
        or high < low
    ):
        raise ValueError(f"{name} must be finite, positive, and ordered")
    return low, high


def _volume_difference(width, height, cut, baseline):
    """Factorized V(cut)-V(baseline), bilinear in width and height."""
    return (cut - baseline) * (
        width * height
        - 2 * (cut + baseline) * (width + height)
        + 4 * (cut * cut + cut * baseline + baseline * baseline)
    )


def range_robustness_report(
    candidate_cut,
    negative_control_cut=NEGATIVE_CONTROL_CUT,
    width_range=(18.0, 22.0),
    height_range=(28.0, 32.0),
):
    """Prove model-only improvement bounds over a rectangular size range.

    For fixed cuts, the difference in box volume is bilinear in width and
    height. Its extrema over a closed rectangle therefore occur at its four
    corners. This is an exact bound for the ideal geometry model, not a
    statistical sample or a physical manufacturing guarantee.
    """
    width_low, width_high = _validate_dimension_range(width_range, "width_range")
    height_low, height_high = _validate_dimension_range(height_range, "height_range")
    minimum_dimension = min(width_low, height_low)
    for name, cut in (
        ("baseline", BASELINE_CUT),
        ("candidate", candidate_cut),
        ("negative control", negative_control_cut),
    ):
        if not _is_finite_real(cut) or not 0 < cut < minimum_dimension / 2:
            raise ValueError(f"{name} cut must be finite, positive, and feasible across the range")

    corners = (
        (width_low, height_low),
        (width_low, height_high),
        (width_high, height_low),
        (width_high, height_high),
    )

    def summarize(cut):
        values = [_volume_difference(w, h, cut, BASELINE_CUT) for w, h in corners]
        minimum_index = min(range(len(values)), key=values.__getitem__)
        maximum_index = max(range(len(values)), key=values.__getitem__)
        minimum = values[minimum_index]
        maximum = values[maximum_index]
        return {
            "corner_improvements_cm3": [
                {"width_cm": w, "height_cm": h, "improvement_cm3": value}
                for (w, h), value in zip(corners, values)
            ],
            "minimum_improvement_cm3": minimum,
            "minimum_at_cm": list(corners[minimum_index]),
            "maximum_improvement_cm3": maximum,
            "maximum_at_cm": list(corners[maximum_index]),
            "passed_entire_range": minimum > 0,
            "evidence_level": (
                "simulation_candidate" if minimum > 0 else "rejected_simulation_candidate"
            ),
        }

    candidate = summarize(candidate_cut)
    negative = summarize(negative_control_cut)
    negative["rejected_entire_range"] = negative["maximum_improvement_cm3"] <= 0
    negative["control_result"] = (
        "rejected" if negative["rejected_entire_range"] else "not_rejected"
    )
    return {
        "method": "exact_bilinear_corner_bounds",
        "width_range_cm": [width_low, width_high],
        "height_range_cm": [height_low, height_high],
        "corner_difference_evaluations": 8,
        "candidate_cut_cm": candidate_cut,
        "negative_control_cut_cm": negative_control_cut,
        "baseline_cut_cm": BASELINE_CUT,
        "mathematical_basis": (
            "For fixed cuts, the volume difference is bilinear in width and height; "
            "its extrema on a closed rectangle occur at the four corners."
        ),
        "candidate": candidate,
        "negative_control": negative,
        "scope": (
            "Exact for the ideal box-volume formula over every width/height pair "
            "in the declared closed ranges; excludes materials, fold geometry, "
            "manufacturing tolerances, costs, and physical validation."
        ),
    }

def run(seed=SEED):
    seed = _validate_seed(seed)
    sheets = training_sheets(seed)
    scores = {cut: mean_volume(sheets, cut) for cut in CUT_GRID}
    # Fixed grid and deterministic tie-break; no adaptive holdout peeking.
    selected = max(CUT_GRID, key=lambda cut: (scores[cut], -cut))
    continuous_optimum = continuous_training_optimum(sheets)
    continuous_score = mean_volume(sheets, continuous_optimum)
    grid_regret = max(0.0, continuous_score - scores[selected])
    # Pass the predeclared holdout explicitly so review tests can replace it
    # without changing the training-only candidate selection.
    candidate = evaluate(selected, holdout=HOLDOUT_SHEETS)
    negative = evaluate(NEGATIVE_CONTROL_CUT, holdout=HOLDOUT_SHEETS)
    range_robustness = range_robustness_report(selected, NEGATIVE_CONTROL_CUT)
    return {
        "problem": "Open-top folded box from rectangular sheet (synthetic geometry)",
        "formula": "V=x*(W-2*x)*(H-2*x), 0<x<min(W,H)/2",
        "objective": "Maximize mean modeled volume on seeded training sheets",
        "hypothesis": "The training-selected cut improves modeled volume over a fixed 2 cm baseline on every holdout sheet",
        "falsification": "Any holdout improvement <= 0 rejects the stated hypothesis",
        "seed": seed,
        "training_case_count": len(sheets),
        "workload": {
            "training_grid_evaluations": len(CUT_GRID) * len(sheets),
            "continuous_reference_evaluations": len(sheets),
            # Two holdout reports (candidate and negative control), each scoring
            # both the selected cut and the fixed baseline on every holdout.
            "holdout_volume_evaluations": 2 * 2 * len(HOLDOUT_SHEETS),
            "range_corner_difference_evaluations": 8,
            "total_box_volume_evaluations": (
                len(CUT_GRID) * len(sheets)
                + len(sheets)
                + 2 * 2 * len(HOLDOUT_SHEETS)
            ),
            "total_model_evaluations": (
                len(CUT_GRID) * len(sheets)
                + len(sheets)
                + 2 * 2 * len(HOLDOUT_SHEETS)
                + 8
            ),
            "hypotheses_evaluated": 1,
        },
        "training_sheet_cm": list(TRAIN_SHEET),
        "training_jitter_cm": 0.5,
        "grid_cuts_cm": list(CUT_GRID),
        "baseline_cut_cm": BASELINE_CUT,
        "selected_training_mean_volume_cm3": scores[selected],
        "continuous_training_optimum_cut_cm": continuous_optimum,
        "continuous_training_optimum_mean_volume_cm3": continuous_score,
        "grid_discretization_regret_cm3": grid_regret,
        "reference_method": "Analytic stationary point of mean cubic volume; training-only, not a novelty claim",
        "baseline_training_mean_volume_cm3": scores[BASELINE_CUT],
        "holdout_sheets_cm": [list(pair) for pair in HOLDOUT_SHEETS],
        "candidate": {**candidate, "evidence_level": "simulation_candidate" if candidate["passed_all_holdouts"] else "rejected_simulation_candidate"},
        "negative_control": {
            **negative,
            "evidence_level": "negative_control",
            "control_result": "rejected" if not negative["passed_all_holdouts"] else "not_rejected",
        },
        "range_robustness": range_robustness,
        "prior_art_evidence": [dict(item) for item in PRIOR_ART],
        "model_prior_art_status": "established_textbook_example",
        "novelty_status": "not_assessed",
        "novelty_scope": "The geometry and optimization are known textbook examples; no patent search or novelty claim for any new implementation.",
        "physical_validation": False,
        "uncertainty": "Only three fixed holdout sheet sizes; no manufacturing tolerances, materials, folds, costs, or independent physical replication modeled.",
        "safety_scope": "Noncritical mathematical geometry demonstration only.",
    }


def distributional_holdout_report(
    candidate_cut,
    negative_control_cut=NEGATIVE_CONTROL_CUT,
    seed=20261103,
    case_count=200,
):
    """Evaluate fixed candidate/control cuts on a separate seeded size range.

    This broader synthetic holdout is generated independently of training.
    It is a robustness diagnostic over the stated rectangle ranges, not a
    confidence interval, population guarantee, novelty check, or physical test.
    """
    seed = _validate_seed(seed)
    if (
        not isinstance(case_count, int)
        or isinstance(case_count, bool)
        or not 0 < case_count <= MAX_DISTRIBUTIONAL_HOLDOUT_CASES
    ):
        raise ValueError(
            f"case_count must be an integer from 1 to {MAX_DISTRIBUTIONAL_HOLDOUT_CASES}"
        )

    width_range = (18.0, 22.0)
    height_range = (28.0, 32.0)
    for cut in (BASELINE_CUT, candidate_cut, negative_control_cut):
        if not _is_finite_real(cut) or cut <= 0 or cut >= min(width_range[0], height_range[0]) / 2:
            raise ValueError("All cuts must be finite, positive, and feasible across the holdout range")

    rng = random.Random(seed)
    candidate_deltas = []
    negative_deltas = []
    for _ in range(case_count):
        width = rng.uniform(*width_range)
        height = rng.uniform(*height_range)
        baseline_volume = box_volume(width, height, BASELINE_CUT)
        candidate_deltas.append(
            box_volume(width, height, candidate_cut) - baseline_volume
        )
        negative_deltas.append(
            box_volume(width, height, negative_control_cut) - baseline_volume
        )

    def summarize(values):
        ordered = sorted(values)
        mean = statistics.fmean(ordered)
        sample_stddev = statistics.stdev(ordered) if len(ordered) > 1 else None
        standard_error = (
            sample_stddev / math.sqrt(len(ordered))
            if sample_stddev is not None else None
        )
        if standard_error is None:
            interval = None
            uncertainty_method = "not_estimable_single_case"
        elif len(ordered) < 30:
            interval = None
            uncertainty_method = "standard_error_only_fewer_than_30_cases"
        else:
            interval = [
                round(mean - 1.96 * standard_error, 6),
                round(mean + 1.96 * standard_error, 6),
            ]
            uncertainty_method = "normal_approximation_1.96_se"
        p05_index = max(0, math.ceil(0.05 * len(ordered)) - 1)
        positive_count = sum(value > 0 for value in ordered)
        return {
            "mean_improvement_cm3": round(mean, 6),
            "sample_standard_deviation_cm3": (
                round(sample_stddev, 6) if sample_stddev is not None else None
            ),
            "standard_error_of_mean_cm3": (
                round(standard_error, 6) if standard_error is not None else None
            ),
            "mean_95pct_normal_interval_cm3": interval,
            "mean_uncertainty_method": uncertainty_method,
            "median_improvement_cm3": round(statistics.median(ordered), 6),
            "minimum_improvement_cm3": round(ordered[0], 6),
            "fifth_percentile_nearest_rank_cm3": round(ordered[p05_index], 6),
            "maximum_improvement_cm3": round(ordered[-1], 6),
            "positive_cases": positive_count,
            "positive_fraction": round(positive_count / len(ordered), 6),
        }

    candidate_summary = summarize(candidate_deltas)
    negative_summary = summarize(negative_deltas)
    return {
        "method": "independent seeded synthetic rectangular-sheet holdout",
        "seed": seed,
        "case_count": case_count,
        "width_cm_range": list(width_range),
        "height_cm_range": list(height_range),
        "baseline_cut_cm": BASELINE_CUT,
        "candidate_cut_cm": candidate_cut,
        "negative_control_cut_cm": negative_control_cut,
        "box_volume_evaluations": 3 * case_count,
        "candidate": {
            **candidate_summary,
            "passed_all_sampled_cases": candidate_summary["positive_cases"] == case_count,
            "evidence_level": (
                "simulation_candidate"
                if candidate_summary["positive_cases"] == case_count
                else "rejected_simulation_candidate"
            ),
        },
        "negative_control": {
            **negative_summary,
            "rejected_on_all_sampled_cases": negative_summary["positive_cases"] == 0,
            "evidence_level": "negative_control",
            "control_result": (
                "rejected"
                if negative_summary["positive_cases"] < case_count
                else "not_rejected"
            ),
        },
        "interpretation": (
            "Finite synthetic robustness sample over the declared ranges only; "
            "not a statistical population guarantee, patent search, or physical validation."
        ),
        "uncertainty_scope": (
            "Approximate normal intervals quantify Monte Carlo sampling uncertainty "
            "under the declared independent uniform width/height draws only; they "
            "exclude model error, manufacturing tolerances, material variation, and "
            "physical uncertainty."
        ),
        "novelty_status": "not_assessed",
        "physical_validation": False,
    }


def run_measured(seed=SEED):
    """Measure repeated in-process runs; keep timing out of the deterministic core report."""
    for _ in range(BENCHMARK_WARMUP_REPETITIONS):
        run(seed)

    seconds_per_run = []
    for _ in range(BENCHMARK_BATCHES):
        started = time.perf_counter()
        for _ in range(BENCHMARK_REPETITIONS_PER_BATCH):
            run(seed)
        elapsed = time.perf_counter() - started
        seconds_per_run.append(elapsed / BENCHMARK_REPETITIONS_PER_BATCH)

    report = run(seed)
    median_seconds_per_run = statistics.median(seconds_per_run)
    evaluations = report["workload"]["total_box_volume_evaluations"]
    model_evaluations = report["workload"]["total_model_evaluations"]
    hypotheses = report["workload"]["hypotheses_evaluated"]
    seconds_per_hypothesis = (
        median_seconds_per_run / hypotheses if hypotheses > 0 else None
    )
    report["performance"] = {
        "runtime_environment": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "logical_cpu_count": os.cpu_count(),
            "cpu_quota_measured": False,
            "energy_measured": False,
        },
        "benchmark_batches": BENCHMARK_BATCHES,
        "repetitions_per_batch": BENCHMARK_REPETITIONS_PER_BATCH,
        "warmup_repetitions": BENCHMARK_WARMUP_REPETITIONS,
        "measured_repetitions": BENCHMARK_BATCHES * BENCHMARK_REPETITIONS_PER_BATCH,
        "hypotheses_evaluated": hypotheses,
        "elapsed_seconds": round(sum(seconds_per_run) * BENCHMARK_REPETITIONS_PER_BATCH, 6),
        "median_seconds_per_run": round(median_seconds_per_run, 6),
        "seconds_per_hypothesis": (
            round(seconds_per_hypothesis, 6)
            if seconds_per_hypothesis is not None else None
        ),
        "min_seconds_per_hypothesis": (
            round(min(seconds_per_run) / hypotheses, 6)
            if hypotheses > 0 else None
        ),
        "max_seconds_per_hypothesis": (
            round(max(seconds_per_run) / hypotheses, 6)
            if hypotheses > 0 else None
        ),
        "hypotheses_per_second": (
            round(hypotheses / median_seconds_per_run, 2)
            if median_seconds_per_run > 0 else None
        ),
        "box_volume_evaluations_per_second": (
            round(evaluations / median_seconds_per_run, 2)
            if median_seconds_per_run > 0 else None
        ),
        "model_evaluations_per_second": (
            round(model_evaluations / median_seconds_per_run, 2)
            if median_seconds_per_run > 0 else None
        ),
        "measurement_scope": (
            "Median of 5 batches of 100 in-process run() calls; includes training, "
            "grid scoring, analytic reference, fixed holdouts, and exact range bounds; excludes interpreter "
            "startup and JSON serialization."
        ),
        "comparability": (
            "Diagnostic only; CPU model/quota, system load, runner image, and energy "
            "are not normalized. Compare only with the same code, runner, and protocol."
        ),
    }
    return report


def run_complete_report(seed=SEED):
    """Combine the timed training search with a separately seeded holdout report.

    Record both the holdout-stage duration and complete report wall time. The
    per-run benchmark above excludes the distributional holdout; these fields
    make that additional verification cost visible.
    """
    seed = _validate_seed(seed)
    complete_started = time.perf_counter()
    report = run_measured(seed)
    holdout_started = time.perf_counter()
    report["distributional_holdout"] = distributional_holdout_report(
        candidate_cut=report["candidate"]["cut_cm"],
        negative_control_cut=report["negative_control"]["cut_cm"],
        seed=(seed + 1) % (2 ** 64),
    )
    holdout_elapsed = time.perf_counter() - holdout_started
    performance = report.setdefault("performance", {})
    performance["distributional_holdout_elapsed_seconds"] = round(
        holdout_elapsed, 6
    )
    performance["complete_report_elapsed_seconds"] = round(
        time.perf_counter() - complete_started, 6
    )
    performance["complete_report_measurement_scope"] = (
        "Wall time for run_complete_report(), including run_measured() warmups, "
        "500 timed run() repetitions, the final deterministic run(), and one "
        "distributional holdout; excludes interpreter startup and JSON serialization."
    )
    return report


if __name__ == "__main__":
    print(json.dumps(run_complete_report(), indent=2, sort_keys=True))
