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
import time

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


def box_volume(width, height, cut):
    """Model volume in cm^3; invalid geometry has zero usable volume."""
    if not all(math.isfinite(value) for value in (width, height, cut)):
        return 0.0
    if width <= 0 or height <= 0 or not 0 < cut < min(width, height) / 2:
        return 0.0
    return cut * (width - 2 * cut) * (height - 2 * cut)


def training_sheets(seed=SEED):
    """Seeded bounded perturbations, independent of the fixed holdout."""
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
        not (math.isfinite(w) and math.isfinite(h) and w > 0 and h > 0)
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
    if not holdout or not math.isfinite(cut) or cut <= 0:
        raise ValueError("Expected nonempty holdout and finite positive cut")
    for width, height in holdout:
        if not all(math.isfinite(v) for v in (width, height)):
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


def run(seed=SEED):
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
            "total_box_volume_evaluations": (
                len(CUT_GRID) * len(sheets)
                + len(sheets)
                + 2 * 2 * len(HOLDOUT_SHEETS)
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
        "negative_control": {**negative, "evidence_level": "rejected_simulation_candidate" if not negative["passed_all_holdouts"] else "simulation_candidate"},
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
    if not isinstance(case_count, int) or isinstance(case_count, bool) or case_count <= 0:
        raise ValueError("case_count must be a positive integer")

    width_range = (18.0, 22.0)
    height_range = (28.0, 32.0)
    for cut in (BASELINE_CUT, candidate_cut, negative_control_cut):
        if not math.isfinite(cut) or cut <= 0 or cut >= min(width_range[0], height_range[0]) / 2:
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
        p05_index = max(0, math.ceil(0.05 * len(ordered)) - 1)
        positive_count = sum(value > 0 for value in ordered)
        return {
            "mean_improvement_cm3": round(statistics.fmean(ordered), 6),
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
            "evidence_level": "simulation_candidate",
        },
        "negative_control": {
            **negative_summary,
            "rejected_on_all_sampled_cases": negative_summary["positive_cases"] == 0,
            "evidence_level": "rejected_simulation_candidate",
        },
        "interpretation": (
            "Finite synthetic robustness sample over the declared ranges only; "
            "not a statistical population guarantee, patent search, or physical validation."
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
    hypotheses = report["workload"]["hypotheses_evaluated"]
    seconds_per_hypothesis = (
        median_seconds_per_run / hypotheses if hypotheses > 0 else None
    )
    report["performance"] = {
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
        "measurement_scope": (
            "Median of 5 batches of 100 in-process run() calls; includes training, "
            "grid scoring, analytic reference, and holdout checks; excludes interpreter "
            "startup and JSON serialization."
        ),
        "comparability": (
            "Diagnostic only; CPU model/quota, system load, runner image, and energy "
            "are not normalized. Compare only with the same code, runner, and protocol."
        ),
    }
    return report


def run_complete_report(seed=SEED):
    """Combine the timed training search with a separately seeded holdout report."""
    report = run_measured(seed)
    report["distributional_holdout"] = distributional_holdout_report(
        candidate_cut=report["candidate"]["cut_cm"],
        negative_control_cut=report["negative_control"]["cut_cm"],
        seed=seed + 1,
    )
    return report


if __name__ == "__main__":
    print(json.dumps(run_complete_report(), indent=2, sort_keys=True))
