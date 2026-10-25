"""Test whether a curved degradation shape beats a straight line.

Decision 7 kept degradation linear and said a curve would be tested on held-out
races rather than assumed. This runs that test.

The shape is chosen using the training races only, by leaving each one out in
turn. The test season is not consulted, because picking the shape that flatters
it would turn a held-out result into a tuned one.

Only the shape is scored. The model fits an intercept per driver per race and
cannot predict a race it has never seen, so each driver's own mean error inside
the held-out race is removed first. That is the part strategy comparisons use.

Usage:
    python scripts/compare_forms.py
    python scripts/compare_forms.py --knees 10 20 30
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from tyre_deg.cleaning import clean_laps
from tyre_deg.config import PILOT_CIRCUIT, TRAIN_SEASONS
from tyre_deg.loading import load_race, race_laps
from tyre_deg.model import LINEAR, QUADRATIC, ModelForm, hinge_form
from tyre_deg.validation import (
    compare_forms,
    fit_shape_coefficients,
    residual_by_tyre_age,
)

logger = logging.getLogger(__name__)


def training_laps(circuit: str) -> pd.DataFrame:
    """Load and clean every training race into one frame."""
    return pd.concat(
        [
            clean_laps(race_laps(load_race(year, circuit))).laps
            for year in TRAIN_SEASONS
        ],
        ignore_index=True,
    )


def report_scores(laps: pd.DataFrame, forms: list[ModelForm]) -> None:
    """Print each shape's held-out error, best first.

    Args:
        laps: Clean training laps.
        forms: Shapes to compare.
    """
    scores = compare_forms(laps, forms)
    best = scores[0]
    baseline = next(score for score in scores if score.form.name == LINEAR.name)
    print(f"\n  {'shape':<16}{'extra terms':>12}{'held-out error':>18}")
    for score in scores:
        marker = "  <- best" if score is best else ""
        print(
            f"  {score.form.name:<16}{score.terms:>12}"
            f"{score.shape_rmse_s:>16.4f} s{marker}"
        )
    gain = baseline.shape_rmse_s - best.shape_rmse_s
    print(
        f"\n  best shape beats the straight line by {gain:.4f} s "
        f"({100 * gain / baseline.shape_rmse_s:.1f}% of its error)"
    )


def report_curvature(laps: pd.DataFrame) -> None:
    """Print the straight line's mean error by tyre age.

    A straight line that has the shape wrong leaves a pattern: a run of errors
    with the same sign at one end of a stint.

    Args:
        laps: Clean training laps.
    """
    table = residual_by_tyre_age(laps, fit_shape_coefficients(laps, LINEAR))
    print("\n  where the straight line is wrong, by tyre age:")
    for bucket, row in table.iterrows():
        bar = "+" if row["mean_residual_s"] > 0 else "-"
        print(
            f"    {bucket:>2} to {bucket + 4:<3} {row['mean_residual_s']:+.3f} s "
            f"{bar * max(1, int(abs(row['mean_residual_s']) * 40))}"
            f"  ({int(row['laps'])} laps)"
        )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--circuit", default=PILOT_CIRCUIT)
    parser.add_argument("--knees", type=float, nargs="+", default=[10, 15, 20, 25])
    return parser.parse_args()


def main() -> None:
    """Compare the shapes and show where the straight line misses."""
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    args = parse_args()
    laps = training_laps(args.circuit)
    forms = [LINEAR, QUADRATIC, *(hinge_form(knee) for knee in args.knees)]
    seasons = ", ".join(str(year) for year in TRAIN_SEASONS)
    print(f"\ntraining races: {seasons}, {len(laps)} clean laps")
    report_scores(laps, forms)
    report_curvature(laps)


if __name__ == "__main__":
    main()
