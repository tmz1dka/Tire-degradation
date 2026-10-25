"""Select the laps that carry a usable tyre degradation signal.

A raw lap time mixes tyre wear with fuel load, pit stops, safety car periods and
traffic. This module removes the laps whose pace is set by something other than
racing pace, so that what remains can be modelled. The reasoning, and the
measured cost of each filter, is in decision 5 of docs/decisions.md.

Each filter is exposed as a function returning a boolean mask rather than one
that drops rows. That keeps them pure and independently testable, and it lets
the pipeline report how many laps each step removed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from tyre_deg.config import NON_GREEN_STATUS_DIGITS, TRAFFIC_GAP_THRESHOLD_S

logger = logging.getLogger(__name__)

GAP_AHEAD_COLUMN = "gap_ahead_s"


@dataclass(frozen=True)
class CleaningStep:
    """How many laps one filter removed.

    Attributes:
        name: Human readable description of the filter.
        dropped: Laps this filter removed that earlier filters had kept.
        remaining: Laps still kept after this filter.
    """

    name: str
    dropped: int
    remaining: int


@dataclass(frozen=True)
class CleanedLaps:
    """Laps that survived cleaning, with a record of what was removed.

    Attributes:
        laps: The surviving laps.
        steps: One entry per filter, in the order applied.
        input_laps: Lap count before any filter ran.
    """

    laps: pd.DataFrame
    steps: tuple[CleaningStep, ...]
    input_laps: int

    @property
    def retained_fraction(self) -> float:
        """Share of input laps that survived, or 0.0 for an empty input."""
        if self.input_laps == 0:
            return 0.0
        return len(self.laps) / self.input_laps


def add_gap_to_car_ahead(laps: pd.DataFrame) -> pd.DataFrame:
    """Add the gap in seconds to the car ahead at each lap's timing line.

    Cars crossing the line on the same lap are ordered by elapsed session time,
    so the difference between consecutive crossings is the gap to the car in
    front. The race leader has no car ahead and gets NaN.

    This is a proxy for dirty air, not a measure of it: it is sampled once per
    lap at one point on the track.

    Args:
        laps: Lap frame with ``LapNumber`` and ``session_time_s`` columns.

    Returns:
        A copy of the frame with ``gap_ahead_s`` added, in the input's row order.

    Raises:
        KeyError: If a required column is missing.
    """
    required = {"LapNumber", "session_time_s"}
    missing = required - set(laps.columns)
    if missing:
        raise KeyError(f"lap frame is missing columns {sorted(missing)}")
    ordered = laps.sort_values(["LapNumber", "session_time_s"])
    gaps = ordered.groupby("LapNumber")["session_time_s"].diff()
    return laps.assign(**{GAP_AHEAD_COLUMN: gaps.reindex(laps.index)})


def is_timed(laps: pd.DataFrame) -> pd.Series:
    """Mask laps that have a recorded lap time.

    A lap can be missing its time when a driver retires part way round, or when
    timing data is incomplete.

    Args:
        laps: Lap frame with a ``lap_time_s`` column.

    Returns:
        Boolean mask, True for laps with a lap time.
    """
    return laps["lap_time_s"].notna()


def is_green_flag(laps: pd.DataFrame) -> pd.Series:
    """Mask laps run entirely without a safety car, VSC or red flag.

    ``TrackStatus`` concatenates every status seen during the lap, so a single
    lap can read "671", meaning VSC deployed, then ending, then clear. The test
    is therefore for containing any flagged digit, never equality against "1".

    Args:
        laps: Lap frame with a ``TrackStatus`` column.

    Returns:
        Boolean mask, True for green flag laps.
    """
    status = laps["TrackStatus"].fillna("").astype(str)
    return ~status.str.contains(f"[{NON_GREEN_STATUS_DIGITS}]", regex=True)


def is_not_pit_lap(laps: pd.DataFrame) -> pd.Series:
    """Mask laps that neither enter nor leave the pits.

    An out-lap at the Hungaroring runs about 19 seconds slow and an in-lap about
    2.7 seconds slow, against a lap of roughly 80 seconds.

    Args:
        laps: Lap frame with ``PitInTime`` and ``PitOutTime`` columns.

    Returns:
        Boolean mask, True for laps clear of the pit lane.
    """
    return laps["PitInTime"].isna() & laps["PitOutTime"].isna()


def is_not_first_lap(laps: pd.DataFrame) -> pd.Series:
    """Mask every lap except the first.

    Lap 1 starts from a standstill on the grid and runs about 7 seconds slow, so
    it is not a racing lap.

    Args:
        laps: Lap frame with a ``LapNumber`` column.

    Returns:
        Boolean mask, True for laps after the first.
    """
    return laps["LapNumber"] > 1


def is_flagged_accurate(laps: pd.DataFrame) -> pd.Series:
    """Mask laps FastF1 considers accurately timed.

    This is FastF1's own quality flag, applied as a guard. At the Hungaroring it
    removes nothing beyond the laps already dropped by the other filters.

    Args:
        laps: Lap frame with an ``IsAccurate`` column.

    Returns:
        Boolean mask, True for laps flagged accurate.
    """
    # astype("boolean") first: fillna on an object column is deprecated.
    return laps["IsAccurate"].astype("boolean").fillna(False).astype(bool)


def is_clear_of_traffic(
    laps: pd.DataFrame,
    threshold_s: float = TRAFFIC_GAP_THRESHOLD_S,
) -> pd.Series:
    """Mask laps not run close behind another car.

    The race leader, whose gap is NaN, counts as clear.

    Args:
        laps: Lap frame with a ``gap_ahead_s`` column.
        threshold_s: Gap below which a lap is treated as affected by traffic.

    Returns:
        Boolean mask, True for laps in clear air.

    Raises:
        KeyError: If the gap column is absent.
        ValueError: If the threshold is negative.
    """
    if GAP_AHEAD_COLUMN not in laps.columns:
        raise KeyError(
            f"lap frame has no {GAP_AHEAD_COLUMN!r} column; "
            "call add_gap_to_car_ahead first"
        )
    if threshold_s < 0:
        raise ValueError(f"traffic threshold must not be negative: {threshold_s}")
    gap = laps[GAP_AHEAD_COLUMN]
    return gap.isna() | (gap >= threshold_s)


def _lap_filters(
    laps: pd.DataFrame,
    traffic_threshold_s: float,
) -> tuple[tuple[str, pd.Series], ...]:
    """Return each filter's name and mask, in the order they are applied."""
    return (
        ("has a lap time", is_timed(laps)),
        ("green flag only", is_green_flag(laps)),
        ("no pit in or out lap", is_not_pit_lap(laps)),
        ("after lap 1", is_not_first_lap(laps)),
        ("timed accurately", is_flagged_accurate(laps)),
        (
            f"clear of traffic by {traffic_threshold_s:g}s",
            is_clear_of_traffic(laps, traffic_threshold_s),
        ),
    )


def clean_laps(
    laps: pd.DataFrame,
    traffic_threshold_s: float = TRAFFIC_GAP_THRESHOLD_S,
) -> CleanedLaps:
    """Apply every lap filter in order and record what each one removed.

    Args:
        laps: Lap frame from :func:`tyre_deg.loading.race_laps`.
        traffic_threshold_s: Gap below which a lap counts as held up in traffic.

    Returns:
        The surviving laps and the per-filter counts.
    """
    with_gap = add_gap_to_car_ahead(laps)
    filters = _lap_filters(with_gap, traffic_threshold_s)
    keep = pd.Series(True, index=with_gap.index)
    steps: list[CleaningStep] = []
    for name, mask in filters:
        before = int(keep.sum())
        keep &= mask
        remaining = int(keep.sum())
        steps.append(CleaningStep(name, before - remaining, remaining))
    result = CleanedLaps(with_gap[keep], tuple(steps), len(with_gap))
    logger.info(
        "Cleaning kept %d of %d laps (%.0f%%)",
        len(result.laps),
        result.input_laps,
        100 * result.retained_fraction,
    )
    return result


def clean_lap_counts_by_compound(cleaned: CleanedLaps) -> pd.Series:
    """Count surviving laps per tyre compound.

    Used to check a compound has enough data to model before fitting a curve to
    it, which is how the soft tyre was ruled out at the Hungaroring.

    Args:
        cleaned: Output of :func:`clean_laps`.

    Returns:
        Lap counts indexed by compound name, highest first.
    """
    if cleaned.laps.empty:
        return pd.Series(dtype="int64")
    return cleaned.laps.groupby("Compound").size().sort_values(ascending=False)
