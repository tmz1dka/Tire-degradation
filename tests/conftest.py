"""Shared test fixtures.

``stint_factory`` builds a stint whose lap times contain a known degradation
rate and a known fuel effect, so results can be checked against an answer known
in advance. Nothing here is random and nothing reads from disk or the network.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest

RACE_LAPS = 70

StintFactory = Callable[..., pd.DataFrame]


def _build_stint(
    first_lap: int,
    stint_laps: int,
    base_s: float,
    degradation_s_per_lap: float,
    fuel_s_per_lap: float,
    compound: str,
) -> pd.DataFrame:
    """Build one stint with a known tyre and fuel effect baked into its times."""
    lap_numbers = [first_lap + offset for offset in range(stint_laps)]
    tyre_ages = [offset + 1 for offset in range(stint_laps)]
    lap_times = [
        base_s + degradation_s_per_lap * age + fuel_s_per_lap * (RACE_LAPS - lap)
        for lap, age in zip(lap_numbers, tyre_ages, strict=True)
    ]
    return pd.DataFrame(
        {
            "LapNumber": [float(lap) for lap in lap_numbers],
            "TyreLife": [float(age) for age in tyre_ages],
            "lap_time_s": lap_times,
            "Compound": compound,
        }
    )


@pytest.fixture
def stint_factory() -> StintFactory:
    """Return a callable that builds a stint with known effects in its times."""

    def factory(
        first_lap: int = 1,
        stint_laps: int = 50,
        base_s: float = 80.0,
        degradation_s_per_lap: float = 0.05,
        fuel_s_per_lap: float = 0.0,
        compound: str = "HARD",
    ) -> pd.DataFrame:
        return _build_stint(
            first_lap,
            stint_laps,
            base_s,
            degradation_s_per_lap,
            fuel_s_per_lap,
            compound,
        )

    return factory
