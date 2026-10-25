"""Report how lap cleaning affects each race, reproducing decision 5.

Prints one table per season showing how many laps each filter removes, plus the
share of green laps held up in traffic and the clean lap count per compound.
These are the numbers quoted in decision 5 of docs/decisions.md.

The table is this program's output and goes to stdout; progress and warnings go
through logging.

Usage:
    python scripts/cleaning_report.py
    python scripts/cleaning_report.py --seasons 2023 --traffic-gap 2.0
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from tyre_deg.cleaning import (
    GAP_AHEAD_COLUMN,
    add_gap_to_car_ahead,
    clean_lap_counts_by_compound,
    clean_laps,
    is_green_flag,
)
from tyre_deg.config import (
    MODELLING_SEASONS,
    PILOT_CIRCUIT,
    TRAFFIC_GAP_THRESHOLD_S,
)
from tyre_deg.loading import load_race, race_lap_count, race_laps

logger = logging.getLogger(__name__)


def traffic_share(laps: pd.DataFrame, threshold_s: float) -> float:
    """Return the share of green-flag laps run within ``threshold_s`` of a car.

    Args:
        laps: Lap frame carrying a gap column and ``TrackStatus``.
        threshold_s: Gap below which a lap counts as held up.

    Returns:
        Share between 0 and 1, or 0.0 when there are no green laps with a gap.
    """
    gaps = laps.loc[is_green_flag(laps), GAP_AHEAD_COLUMN].dropna()
    if gaps.empty:
        return 0.0
    return float((gaps < threshold_s).mean())


def report_race(year: int, circuit: str, threshold_s: float) -> None:
    """Print the cleaning funnel and compound coverage for one race.

    Args:
        year: Season to load.
        circuit: Circuit name FastF1 recognises.
        threshold_s: Traffic gap threshold to apply.
    """
    laps = race_laps(load_race(year, circuit))
    cleaned = clean_laps(laps, threshold_s)
    print(f"\n{year} {circuit}: {race_lap_count(laps)} laps, "
          f"{cleaned.input_laps} lap records")
    print(f"  {'filter':<28} {'dropped':>8} {'remaining':>10}")
    for step in cleaned.steps:
        print(f"  {step.name:<28} {step.dropped:>8} {step.remaining:>10}")
    print(f"  kept {len(cleaned.laps)} of {cleaned.input_laps} "
          f"({100 * cleaned.retained_fraction:.0f}%)")
    print(f"  green laps within {threshold_s:g}s of the car ahead: "
          f"{100 * traffic_share(add_gap_to_car_ahead(laps), threshold_s):.1f}%")
    counts = clean_lap_counts_by_compound(cleaned)
    print(f"  clean laps by compound: {counts.to_dict()}")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--seasons",
        type=int,
        nargs="+",
        default=list(MODELLING_SEASONS),
        help="seasons to report on",
    )
    parser.add_argument(
        "--circuit",
        default=PILOT_CIRCUIT,
        help="circuit name FastF1 recognises",
    )
    parser.add_argument(
        "--traffic-gap",
        type=float,
        default=TRAFFIC_GAP_THRESHOLD_S,
        help="gap in seconds below which a lap counts as held up in traffic",
    )
    return parser.parse_args()


def main() -> None:
    """Report on every requested race."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args = parse_args()
    for year in args.seasons:
        report_race(year, args.circuit, args.traffic_gap)


if __name__ == "__main__":
    main()
