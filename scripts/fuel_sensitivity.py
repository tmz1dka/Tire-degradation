"""Show how the fuel correction changes the apparent tyre degradation.

Fits an uncontrolled slope of lap time against tyre age at several assumed fuel
effects, including zero. These are the numbers quoted in decision 6 of
docs/decisions.md, including the uncorrected medium tyre coming out negative.

The slopes here pool all drivers with no control for pace, so they diagnose the
problem rather than estimate degradation. See decision 7.

Usage:
    python scripts/fuel_sensitivity.py
    python scripts/fuel_sensitivity.py --season 2024 --circuit Hungary
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from tyre_deg.cleaning import clean_laps
from tyre_deg.config import (
    FUEL_SENSITIVITY_S_PER_LAP,
    MIN_LAPS_FOR_SLOPE,
    PILOT_CIRCUIT,
    PILOT_SEASON,
)
from tyre_deg.diagnostics import compound_slopes
from tyre_deg.fuel import fuel_corrected_lap_time, physical_fuel_effect
from tyre_deg.loading import load_race, race_lap_count, race_laps

logger = logging.getLogger(__name__)

CORRECTED_COLUMN = "corrected_lap_time_s"


def slopes_at_fuel_effect(
    laps: pd.DataFrame,
    fuel_s_per_lap: float,
    total_race_laps: int,
) -> dict[str, float | None]:
    """Return each compound's slope after correcting for a given fuel effect.

    Args:
        laps: Clean lap frame.
        fuel_s_per_lap: Assumed lap time cost per lap of fuel remaining.
        total_race_laps: Number of laps in the race.

    Returns:
        Slope in seconds per lap, keyed by compound, None where data is thin.
    """
    corrected = fuel_corrected_lap_time(laps, fuel_s_per_lap, total_race_laps)
    with_correction = laps.assign(**{CORRECTED_COLUMN: corrected})
    return {
        result.compound: result.slope_s_per_lap
        for result in compound_slopes(with_correction, CORRECTED_COLUMN)
    }


def format_slope(slope: float | None) -> str:
    """Format a slope for the table, or mark it as having too little data."""
    if slope is None:
        return f"{'too few laps':>12}"
    return f"{slope:>+12.4f}"


def report(year: int, circuit: str) -> None:
    """Print the sensitivity table for one race.

    Args:
        year: Season to load.
        circuit: Circuit name FastF1 recognises.
    """
    laps = race_laps(load_race(year, circuit))
    total_laps = race_lap_count(laps)
    clean = clean_laps(laps).laps
    physical = physical_fuel_effect(total_laps)
    effects = sorted({0.0, physical, *FUEL_SENSITIVITY_S_PER_LAP})
    counts = {
        result.compound: result.laps for result in compound_slopes(clean, "lap_time_s")
    }
    compounds = sorted(counts, key=lambda name: counts[name], reverse=True)

    print(f"\n{year} {circuit}: {total_laps} laps, {len(clean)} clean laps")
    print(f"physical estimate of the fuel effect: {physical:.4f} s/lap")
    print(f"a compound needs {MIN_LAPS_FOR_SLOPE} clean laps for a slope\n")
    header = "".join(f"{name:>13}" for name in compounds)
    print(f"  {'assumed fuel':>14}  {header}")
    print(f"  {'clean laps':>14}  " + "".join(f"{counts[c]:>13}" for c in compounds))
    print(f"  {'':>14}  " + "-" * (13 * len(compounds)))
    for effect in effects:
        slopes = slopes_at_fuel_effect(clean, effect, total_laps)
        label = f"{effect:.4f} s/lap" + (" *" if effect == physical else "")
        row = "".join(f" {format_slope(slopes.get(c))}" for c in compounds)
        print(f"  {label:>14} {row}")
    print("\n  * the physical estimate; values are seconds of lap time per lap of")
    print("    tyre age, so positive means the tyre loses time as it ages")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int, default=PILOT_SEASON)
    parser.add_argument("--circuit", default=PILOT_CIRCUIT)
    return parser.parse_args()


def main() -> None:
    """Report on the requested race."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args = parse_args()
    report(args.season, args.circuit)


if __name__ == "__main__":
    main()
