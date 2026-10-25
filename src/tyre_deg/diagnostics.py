"""Uncontrolled degradation slopes, for diagnosis rather than estimation.

A slope fitted here pools every driver together with no control for pace, and so
partly measures who happened to be on which compound and when. Decision 7 in
docs/decisions.md rejects this as an estimator: on the 2023 Hungarian GP it puts
the hard tyre degrading faster than the medium, which is the wrong way round.

These functions exist for two honest purposes: to reproduce the evidence quoted
in decision 6, where an uncorrected slope comes out negative, and to show what
the fuel correction changes. Do not quote their output as the project's estimate
of degradation. The fitted model, with driver effects, is what does that.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tyre_deg.config import MIN_LAPS_FOR_SLOPE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompoundSlope:
    """An uncontrolled lap time trend against tyre age for one compound.

    Attributes:
        compound: Tyre compound name.
        laps: Clean laps available for this compound.
        slope_s_per_lap: Seconds of lap time gained per lap of tyre age, or
            None when there were too few laps to fit.
    """

    compound: str
    laps: int
    slope_s_per_lap: float | None

    @property
    def has_estimate(self) -> bool:
        """Whether a slope could be fitted at all."""
        return self.slope_s_per_lap is not None


def uncontrolled_slope(
    tyre_ages: pd.Series,
    lap_times: pd.Series,
    min_laps: int = MIN_LAPS_FOR_SLOPE,
) -> float | None:
    """Fit a straight line through lap time against tyre age.

    Args:
        tyre_ages: Tyre age in laps.
        lap_times: Lap times in seconds, corrected or not.
        min_laps: Fewest usable laps that will produce an estimate.

    Returns:
        The slope in seconds per lap, or None when there are too few laps or
        every lap shares one tyre age, in which case no line is defined.

    Raises:
        ValueError: If the two inputs are of different lengths.
    """
    if len(tyre_ages) != len(lap_times):
        raise ValueError(
            f"tyre ages and lap times differ in length: "
            f"{len(tyre_ages)} and {len(lap_times)}"
        )
    usable = tyre_ages.notna() & lap_times.notna()
    ages, times = tyre_ages[usable], lap_times[usable]
    if len(ages) < min_laps:
        logger.info("Too few laps to fit a slope: %d < %d", len(ages), min_laps)
        return None
    if ages.nunique() < 2:
        logger.info("All %d laps share one tyre age; no slope is defined", len(ages))
        return None
    slope, _ = np.polyfit(ages, times, 1)
    return float(slope)


def compound_slopes(
    laps: pd.DataFrame,
    lap_time_column: str = "lap_time_s",
    min_laps: int = MIN_LAPS_FOR_SLOPE,
) -> tuple[CompoundSlope, ...]:
    """Fit an uncontrolled slope per compound, best covered compound first.

    Compounds with too little data are returned with no estimate rather than
    silently dropped, so a thin compound is visible instead of missing.

    Args:
        laps: Clean lap frame with ``Compound``, ``TyreLife`` and the time column.
        lap_time_column: Column holding the lap times to fit.
        min_laps: Fewest usable laps that will produce an estimate.

    Returns:
        One entry per compound present, ordered by lap count, highest first.

    Raises:
        KeyError: If a required column is absent.
    """
    required = {"Compound", "TyreLife", lap_time_column}
    missing = required - set(laps.columns)
    if missing:
        raise KeyError(f"lap frame is missing columns {sorted(missing)}")
    results = [
        CompoundSlope(
            compound=str(compound),
            laps=len(group),
            slope_s_per_lap=uncontrolled_slope(
                group["TyreLife"], group[lap_time_column], min_laps
            ),
        )
        for compound, group in laps.groupby("Compound")
    ]
    return tuple(sorted(results, key=lambda result: result.laps, reverse=True))
