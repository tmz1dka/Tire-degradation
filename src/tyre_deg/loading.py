"""Load Formula 1 race sessions from the FastF1 timing archive.

Data provenance: FastF1 reads Formula 1's official timing archive, which covers
2018 onwards. Sessions are cached on disk on first download and read back from
there afterwards, so an analysis run needs no network access. The cache holds
raw session data; nothing in this project writes to it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import fastf1
import pandas as pd

from tyre_deg.config import CACHE_DIR, MODELLING_SEASONS

logger = logging.getLogger(__name__)


def enable_cache(cache_dir: Path = CACHE_DIR) -> Path:
    """Point FastF1 at the on-disk session cache, creating it if absent.

    Args:
        cache_dir: Directory FastF1 should use for cached session data.

    Returns:
        The directory that was enabled.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache_dir))
    return cache_dir


def _warn_if_outside_modelling_window(year: int) -> None:
    """Warn when a season sits outside the window fitting is allowed to use."""
    if year not in MODELLING_SEASONS:
        logger.warning(
            "Season %d is outside the modelling window %s; load it for "
            "comparison evidence only, never for fitting.",
            year,
            MODELLING_SEASONS,
        )


def load_race(
    year: int,
    circuit: str,
    cache_dir: Path = CACHE_DIR,
) -> fastf1.core.Session:
    """Load one race session, with laps, weather and race control messages.

    Telemetry is not loaded: it is large and this project works at lap
    granularity.

    Args:
        year: Season, for example 2023.
        circuit: Circuit or event name FastF1 recognises, for example "Hungary".
        cache_dir: Directory holding the FastF1 session cache.

    Returns:
        A loaded FastF1 race session.

    Raises:
        ValueError: If the season or circuit does not resolve to a race session.
    """
    enable_cache(cache_dir)
    _warn_if_outside_modelling_window(year)
    try:
        session = fastf1.get_session(year, circuit, "R")
        session.load(laps=True, telemetry=False, weather=True, messages=True)
    except ValueError as error:
        raise ValueError(
            f"Could not load the {year} race at {circuit!r} from "
            f"cache {cache_dir}: {error}"
        ) from error
    logger.info(
        "Loaded %s %s: %d laps from %d drivers",
        year,
        session.event["EventName"],
        len(session.laps),
        session.laps["DriverNumber"].nunique(),
    )
    return session


def race_laps(session: fastf1.core.Session) -> pd.DataFrame:
    """Return the session's laps with timing columns converted to seconds.

    FastF1 returns timedeltas, which are awkward to model with. This adds plain
    float columns and leaves every original column untouched.

    Args:
        session: A loaded FastF1 race session.

    Returns:
        A copy of the lap frame with ``lap_time_s`` and ``session_time_s`` added.
    """
    laps = session.laps.copy()
    laps["lap_time_s"] = laps["LapTime"].dt.total_seconds()
    laps["session_time_s"] = laps["Time"].dt.total_seconds()
    return laps


def race_lap_count(laps: pd.DataFrame) -> int:
    """Return the number of laps the race winner completed.

    Used by the fuel correction, which needs the race distance to work out how
    much fuel remained on a given lap.

    Args:
        laps: A lap frame with a ``LapNumber`` column.

    Returns:
        The highest lap number in the frame, or 0 if it is empty.

    Raises:
        KeyError: If the frame has no ``LapNumber`` column.
    """
    if "LapNumber" not in laps.columns:
        raise KeyError("lap frame has no 'LapNumber' column")
    if laps.empty:
        return 0
    return int(laps["LapNumber"].max())
