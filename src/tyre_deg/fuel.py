"""Correct lap times for the fuel the car is still carrying.

A car starts a race around 100kg heavy and gets faster as that burns off, so
later laps are quicker for a reason that has nothing to do with tyres. Tyre age
and race lap advance together, so without this correction the two effects are
superimposed and the tyre looks better than it is. At the Hungaroring in 2023
the uncorrected medium tyre appears to get *faster* with age.

The correction references every lap to the fuel load at the end of the race, so
a corrected time answers "what would this lap have been on a nearly empty car".
The final lap is therefore unchanged and earlier laps are reduced.

This module applies a *known* fuel effect. Decision 6 in docs/decisions.md
estimates that effect from the data instead of assuming it, and uses fixed
values only as a sensitivity band around the fitted result.
"""

from __future__ import annotations

import logging

import pandas as pd

from tyre_deg.config import FUEL_SECONDS_PER_KG, RACE_FUEL_MASS_KG

logger = logging.getLogger(__name__)


def physical_fuel_effect(
    total_race_laps: int,
    fuel_mass_kg: float = RACE_FUEL_MASS_KG,
    seconds_per_kg: float = FUEL_SECONDS_PER_KG,
) -> float:
    """Return the lap time cost, in seconds, of one lap's worth of fuel.

    This is a physical estimate brought in from outside the data: roughly
    ``seconds_per_kg`` of lap time per kilogram carried, over ``fuel_mass_kg``
    burned across the race. It is a prior and a sanity check, not a measurement.

    Args:
        total_race_laps: Number of laps in the race.
        fuel_mass_kg: Fuel burned over the race distance.
        seconds_per_kg: Lap time cost per kilogram carried.

    Returns:
        Seconds of lap time per lap of fuel remaining.

    Raises:
        ValueError: If the race length or either constant is not positive.
    """
    if total_race_laps <= 0:
        raise ValueError(f"race must have at least one lap, got {total_race_laps}")
    if fuel_mass_kg <= 0 or seconds_per_kg <= 0:
        raise ValueError(
            f"fuel constants must be positive, got mass {fuel_mass_kg}kg "
            f"and {seconds_per_kg}s/kg"
        )
    return fuel_mass_kg * seconds_per_kg / total_race_laps


def laps_of_fuel_remaining(laps: pd.DataFrame, total_race_laps: int) -> pd.Series:
    """Return how many laps of fuel each lap was still carrying.

    Assumes fuel burns at a constant rate per lap. Real consumption varies with
    safety car periods, fuel saving and traffic, which this ignores.

    Args:
        laps: Lap frame with a ``LapNumber`` column.
        total_race_laps: Number of laps in the race.

    Returns:
        Laps of fuel remaining, 0 on the final lap.

    Raises:
        KeyError: If ``LapNumber`` is absent.
        ValueError: If the race length is not positive.
    """
    if "LapNumber" not in laps.columns:
        raise KeyError("lap frame has no 'LapNumber' column")
    if total_race_laps <= 0:
        raise ValueError(f"race must have at least one lap, got {total_race_laps}")
    return total_race_laps - laps["LapNumber"]


def fuel_corrected_lap_time(
    laps: pd.DataFrame,
    seconds_per_lap: float,
    total_race_laps: int,
) -> pd.Series:
    """Return lap times with the fuel load's effect removed.

    Args:
        laps: Lap frame with ``LapNumber`` and ``lap_time_s`` columns.
        seconds_per_lap: Lap time cost per lap of fuel remaining. Pass 0 to get
            the uncorrected times back unchanged.
        total_race_laps: Number of laps in the race.

    Returns:
        Corrected lap times in seconds, referenced to end-of-race fuel load.

    Raises:
        KeyError: If a required column is absent.
        ValueError: If ``seconds_per_lap`` is negative, or the race has no laps.
    """
    if "lap_time_s" not in laps.columns:
        raise KeyError("lap frame has no 'lap_time_s' column")
    if seconds_per_lap < 0:
        raise ValueError(
            f"fuel effect must not be negative, got {seconds_per_lap} s/lap"
        )
    remaining = laps_of_fuel_remaining(laps, total_race_laps)
    return laps["lap_time_s"] - remaining * seconds_per_lap
