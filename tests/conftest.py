"""Shared test fixtures.

Lap times here are built from known coefficients so results can be checked
against an answer known in advance. ``race_factory`` takes the degradation
shape as a function of tyre age, so a test can build a race that really is
linear, or really is curved, and then ask whether the code notices. Nothing is
random unless a test asks for noise, and that noise is seeded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pytest

RACE_LAPS = 70

StintFactory = Callable[..., pd.DataFrame]
RaceFactory = Callable[..., pd.DataFrame]
Degradation = Callable[[str, float], float]


@dataclass(frozen=True)
class Truth:
    """The coefficients the synthetic lap times are built from.

    Attributes:
        race_laps: Laps in the race.
        fuel: Lap time cost per lap of fuel remaining.
        degradation: Lap time cost per lap of tyre age, per compound.
        offsets: Compound baseline offsets.
        pace: Baseline lap time per driver.
    """

    race_laps: int = RACE_LAPS
    fuel: float = 0.045
    degradation: dict[str, float] = field(
        default_factory=lambda: {"MEDIUM": 0.05, "HARD": 0.07}
    )
    offsets: dict[str, float] = field(
        default_factory=lambda: {"MEDIUM": -0.40, "HARD": 0.0}
    )
    pace: dict[str, float] = field(
        default_factory=lambda: {
            "VER": 80.0, "NOR": 80.3, "PIA": 80.5,
            "RUS": 80.8, "LEC": 81.0, "HAM": 81.2,
        }
    )

    @property
    def drivers(self) -> tuple[str, ...]:
        """Drivers in the synthetic races."""
        return tuple(self.pace)

    def linear_wear(self, compound: str, age: float) -> float:
        """Lap time lost to a tyre of this compound at this age, as a line."""
        return self.degradation[compound] * age


@pytest.fixture
def truth() -> Truth:
    """The coefficients the synthetic data is built from."""
    return Truth()


def _lap_rows(
    race_id: str,
    stints: list[tuple[str, int, str, int, int]],
    truth: Truth,
    degradation: Degradation,
) -> list[dict[str, object]]:
    """Build one row per lap, with a known pace, fuel and tyre term."""
    rows = []
    for driver, stint, compound, first_lap, length in stints:
        for offset in range(length):
            lap_number = first_lap + offset
            age = offset + 1
            rows.append(
                {
                    "race_id": race_id,
                    "Driver": driver,
                    "Stint": float(stint),
                    "Compound": compound,
                    "LapNumber": float(lap_number),
                    "TyreLife": float(age),
                    "lap_time_s": (
                        truth.pace[driver]
                        + truth.fuel * (truth.race_laps - lap_number)
                        + degradation(compound, age)
                        + truth.offsets[compound]
                    ),
                }
            )
    return rows


@pytest.fixture
def stint_factory(truth: Truth) -> StintFactory:
    """Return a callable building one driver's stint with known effects."""

    def factory(
        first_lap: int = 1,
        stint_laps: int = 50,
        base_s: float = 80.0,
        degradation_s_per_lap: float = 0.05,
        fuel_s_per_lap: float = 0.0,
        compound: str = "HARD",
    ) -> pd.DataFrame:
        lap_numbers = [first_lap + offset for offset in range(stint_laps)]
        ages = [offset + 1 for offset in range(stint_laps)]
        return pd.DataFrame(
            {
                "LapNumber": [float(lap) for lap in lap_numbers],
                "TyreLife": [float(age) for age in ages],
                "lap_time_s": [
                    base_s
                    + degradation_s_per_lap * age
                    + fuel_s_per_lap * (RACE_LAPS - lap)
                    for lap, age in zip(lap_numbers, ages, strict=True)
                ],
                "Compound": compound,
            }
        )

    return factory


@pytest.fixture
def race_factory(truth: Truth) -> RaceFactory:
    """Return a callable building a whole race of three stint runs.

    Every driver runs medium, then hard, then hard, stopping on a different lap
    so the field covers a spread of tyre ages at any given point in the race.
    """

    def factory(
        race_id: str = "2023 Race",
        stop_shift: int = 0,
        degradation: Degradation | None = None,
        noise_std: float = 0.0,
        seed: int = 0,
    ) -> pd.DataFrame:
        stints: list[tuple[str, int, str, int, int]] = []
        for index, driver in enumerate(truth.drivers):
            first_stop = 18 + stop_shift + index
            second_stop = first_stop + 24
            stints.extend(
                [
                    (driver, 1, "MEDIUM", 1, first_stop - 1),
                    (driver, 2, "HARD", first_stop, second_stop - first_stop),
                    (driver, 3, "HARD", second_stop,
                     truth.race_laps - second_stop + 1),
                ]
            )
        frame = pd.DataFrame(
            _lap_rows(race_id, stints, truth, degradation or truth.linear_wear)
        )
        if noise_std:
            generator = np.random.default_rng(seed)
            frame["lap_time_s"] += generator.normal(0.0, noise_std, len(frame))
        return frame

    return factory
