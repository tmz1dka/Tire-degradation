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


@dataclass(frozen=True)
class LineFit:
    """A straight line fitted through lap time against tyre age.

    Attributes:
        slope_s_per_lap: Seconds of lap time gained per lap of tyre age.
        intercept_s: Fitted lap time at a tyre age of zero laps.
        laps: Laps the fit used.
        youngest_age: Lowest tyre age in the fitted data.
        oldest_age: Highest tyre age in the fitted data.
    """

    slope_s_per_lap: float
    intercept_s: float
    laps: int
    youngest_age: float
    oldest_age: float

    def predict(self, tyre_age: float) -> float:
        """Return the fitted lap time at a given tyre age.

        Args:
            tyre_age: Tyre age in laps.

        Returns:
            Fitted lap time in seconds.
        """
        return self.intercept_s + self.slope_s_per_lap * tyre_age


def uncontrolled_line(
    tyre_ages: pd.Series,
    lap_times: pd.Series,
    min_laps: int = MIN_LAPS_FOR_SLOPE,
) -> LineFit | None:
    """Fit a straight line through lap time against tyre age.

    Args:
        tyre_ages: Tyre age in laps.
        lap_times: Lap times in seconds, corrected or not.
        min_laps: Fewest usable laps that will produce a fit.

    Returns:
        The fitted line, or None when there are too few laps or every lap
        shares one tyre age, in which case no line is defined.

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
        logger.info("Too few laps to fit a line: %d < %d", len(ages), min_laps)
        return None
    if ages.nunique() < 2:
        logger.info("All %d laps share one tyre age; no line is defined", len(ages))
        return None
    slope, intercept = np.polyfit(ages, times, 1)
    return LineFit(
        slope_s_per_lap=float(slope),
        intercept_s=float(intercept),
        laps=len(ages),
        youngest_age=float(ages.min()),
        oldest_age=float(ages.max()),
    )


def uncontrolled_slope(
    tyre_ages: pd.Series,
    lap_times: pd.Series,
    min_laps: int = MIN_LAPS_FOR_SLOPE,
) -> float | None:
    """Return just the slope of :func:`uncontrolled_line`.

    Args:
        tyre_ages: Tyre age in laps.
        lap_times: Lap times in seconds, corrected or not.
        min_laps: Fewest usable laps that will produce an estimate.

    Returns:
        The slope in seconds per lap, or None when no line could be fitted.
    """
    fit = uncontrolled_line(tyre_ages, lap_times, min_laps)
    return None if fit is None else fit.slope_s_per_lap


def median_lap_time_by_tyre_age(
    laps: pd.DataFrame,
    lap_time_column: str = "lap_time_s",
    min_laps_per_age: int = 5,
) -> pd.Series:
    """Return the median lap time at each tyre age.

    Medians are far less sensitive to a single bad lap than a mean, which makes
    the trend readable on a chart without hiding the spread behind it. Ages with
    too few laps are dropped, because a median of two laps is noise.

    Args:
        laps: Lap frame with ``TyreLife`` and the time column.
        lap_time_column: Column holding the lap times.
        min_laps_per_age: Fewest laps an age needs to be included.

    Returns:
        Median lap time in seconds, indexed by tyre age, ascending.

    Raises:
        KeyError: If a required column is absent.
    """
    required = {"TyreLife", lap_time_column}
    missing = required - set(laps.columns)
    if missing:
        raise KeyError(f"lap frame is missing columns {sorted(missing)}")
    grouped = laps.groupby("TyreLife")[lap_time_column]
    medians = grouped.median()[grouped.size() >= min_laps_per_age]
    return medians.sort_index()


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
