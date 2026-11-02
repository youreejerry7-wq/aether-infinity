"""Bounded, reproducible design-search sandbox: open-top paper box volume.

Pure geometry and synthetic dimensions; not a physical invention or novelty claim.
Cut equal squares of side x from the corners of a W-by-H sheet, fold sides:
V(W, H, x) = x (W - 2x) (H - 2x), for 0 < x < min(W, H)/2.

Candidate selection sees ONLY seeded training cases. Fixed holdout cases are
evaluated AFTER selection and are never used to rank candidates.
"""
import json
import random
import statistics

SEED = 20261102
TRAIN_CASES = 8
TRAIN_SHEET = (20.0, 30.0)
HOLDOUT_SHEETS = ((18.0, 32.0), (22.0, 28.0), (19.0, 31.0))
CUT_GRID = tuple(step / 2 for step in range(1, 19))  # 0.5 to 9.0 cm
BASELINE_CUT = 2.0
NEGATIVE_CONTROL_CUT = 9.0


def box_volume(width, height, cut):
    """Model volume in cm^3; invalid geometry has zero usable volume."""
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


def evaluate(cut, holdout=HOLDOUT_SHEETS):
    """Holdout check versus a predeclared baseline; no training score used."""
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
    candidate = evaluate(selected)
    negative = evaluate(NEGATIVE_CONTROL_CUT)
    return {
        "problem": "Open-top folded box from rectangular sheet (synthetic geometry)",
        "formula": "V=x*(W-2*x)*(H-2*x), 0<x<min(W,H)/2",
        "objective": "Maximize mean modeled volume on seeded training sheets",
        "hypothesis": "The training-selected cut improves modeled volume over a fixed 2 cm baseline on every holdout sheet",
        "falsification": "Any holdout improvement <= 0 rejects the stated hypothesis",
        "seed": seed,
        "training_case_count": len(sheets),
        "training_sheet_cm": list(TRAIN_SHEET),
        "training_jitter_cm": 0.5,
        "grid_cuts_cm": list(CUT_GRID),
        "baseline_cut_cm": BASELINE_CUT,
        "selected_training_mean_volume_cm3": scores[selected],
        "baseline_training_mean_volume_cm3": scores[BASELINE_CUT],
        "holdout_sheets_cm": [list(pair) for pair in HOLDOUT_SHEETS],
        "candidate": {**candidate, "evidence_level": "simulation_candidate" if candidate["passed_all_holdouts"] else "rejected_simulation_candidate"},
        "negative_control": {**negative, "evidence_level": "rejected_simulation_candidate" if not negative["passed_all_holdouts"] else "simulation_candidate"},
        "novelty_status": "not_assessed",
        "physical_validation": False,
        "uncertainty": "Only three fixed holdout sheet sizes; no manufacturing tolerances, materials, folds, costs, or independent physical replication modeled.",
        "safety_scope": "Noncritical mathematical geometry demonstration only.",
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
