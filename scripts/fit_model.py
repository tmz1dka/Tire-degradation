"""Fit the degradation model on the training races and report its coefficients.

Prints the fuel effect and each compound's degradation rate, with intervals from
resampling whole stints, and compares the fitted fuel effect against the
physical estimate it would otherwise have been assumed to equal.

Usage:
    python scripts/fit_model.py
    python scripts/fit_model.py --seasons 2023 2024 --resamples 2000
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from tyre_deg.cleaning import clean_laps
from tyre_deg.config import (
    MODELLED_COMPOUNDS,
    PILOT_CIRCUIT,
    TRAIN_SEASONS,
)
from tyre_deg.fuel import physical_fuel_effect
from tyre_deg.loading import load_race, race_lap_count, race_laps
from tyre_deg.model import (
    BootstrapResult,
    CoefficientInterval,
    bootstrap_degradation,
    derived_interval,
)

logger = logging.getLogger(__name__)


def training_laps(seasons: tuple[int, ...], circuit: str) -> pd.DataFrame:
    """Load and clean every training race into one frame.

    Args:
        seasons: Seasons to train on.
        circuit: Circuit name FastF1 recognizes.

    Returns:
        Clean laps from all the training races, concatenated.
    """
    races = []
    for season in seasons:
        laps = race_laps(load_race(season, circuit))
        clean = clean_laps(laps).laps
        logger.info("%s: %d clean laps", clean["race_id"].iloc[0], len(clean))
        races.append(clean)
    return pd.concat(races, ignore_index=True)


def format_interval(interval: CoefficientInterval, unit: str = "s/lap") -> str:
    """Render a coefficient and its interval for the report."""
    return (
        f"{interval.point:+.4f} {unit} "
        f"[{interval.low:+.4f}, {interval.high:+.4f}]"
    )


def report(result: BootstrapResult, physical: float) -> None:
    """Print the fitted coefficients and how they compare to the prior.

    Args:
        result: Fitted coefficients with intervals.
        physical: The physical estimate of the fuel effect, for comparison.
    """
    estimate = result.estimate
    print(f"\nlaps fitted            {estimate.laps}")
    print(f"driver and race terms  {estimate.intercepts}")
    print(f"residual spread        {estimate.residual_std_s:.3f} s")
    print(f"resamples              {result.resamples} "
          f"({result.failed_resamples} discarded)")
    print(f"\n{result.confidence:.0%} intervals from resampling whole stints\n")
    print(f"  fuel effect          {format_interval(result.fuel)}")
    print(f"  physical estimate    {physical:+.4f} s/lap, "
          f"{'inside' if not result.fuel.excludes(physical) else 'OUTSIDE'} "
          "the interval")
    print()
    for compound in MODELLED_COMPOUNDS:
        interval = result.degradation[compound]
        zero = "excludes 0" if interval.excludes(0.0) else "INCLUDES 0"
        print(f"  {compound.lower():<20} {format_interval(interval)}  {zero}")
    offsets = estimate.compound_offset_s
    print(f"\n  baseline offsets vs the {estimate.reference_compound.lower()}:")
    for compound, offset in offsets.items():
        print(f"    {compound.lower():<18} {offset:+.3f} s")
    report_compound_gap(result)


def report_compound_gap(result: BootstrapResult) -> None:
    """Report the difference between the two compounds' degradation rates.

    Overlapping intervals do not mean two coefficients are indistinguishable,
    so the difference is recomputed inside every resample and reported in its
    own right.

    Args:
        result: Fitted coefficients with their resampled fits.
    """
    first, second = MODELLED_COMPOUNDS[0], MODELLED_COMPOUNDS[1]
    gap = derived_interval(
        result,
        lambda fit: (
            fit.degradation_s_per_lap[second] - fit.degradation_s_per_lap[first]
        ),
    )
    verdict = (
        "the two compounds differ"
        if gap.excludes(0.0)
        else "the data cannot tell the two compounds apart"
    )
    print(
        f"\n  {second.lower()} minus {first.lower():<10} "
        f"{format_interval(gap)}\n  {verdict}"
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seasons", type=int, nargs="+", default=list(TRAIN_SEASONS))
    parser.add_argument("--circuit", default=PILOT_CIRCUIT)
    parser.add_argument("--resamples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    """Fit the model and print the report."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    laps = training_laps(tuple(args.seasons), args.circuit)
    race_lengths = [
        race_lap_count(group) for _, group in laps.groupby("race_id", sort=True)
    ]
    physical = physical_fuel_effect(round(sum(race_lengths) / len(race_lengths)))
    result = bootstrap_degradation(laps, resamples=args.resamples, seed=args.seed)
    report(result, physical)


if __name__ == "__main__":
    main()
