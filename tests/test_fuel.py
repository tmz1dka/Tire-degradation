"""Tests for the fuel correction.

Frames are built in the test with a known degradation rate and a known fuel
effect, so the correction can be checked against an answer that is known in
advance rather than only for not crashing. No randomness, no network.
"""

from __future__ import annotations

import pandas as pd
import pytest
from tests.conftest import RACE_LAPS, StintFactory

from tyre_deg.fuel import (
    fuel_corrected_lap_time,
    laps_of_fuel_remaining,
    laps_of_fuel_remaining_by_race,
    physical_fuel_effect,
)


def test_physical_fuel_effect_spreads_the_race_fuel_over_the_laps() -> None:
    # 100kg at 0.03 s/kg over 70 laps.
    assert physical_fuel_effect(70, 100.0, 0.03) == pytest.approx(0.042857, abs=1e-6)


def test_physical_fuel_effect_scales_with_race_length() -> None:
    assert physical_fuel_effect(35, 100.0, 0.03) == pytest.approx(
        2 * physical_fuel_effect(70, 100.0, 0.03)
    )


@pytest.mark.parametrize("total_laps", [0, -1])
def test_physical_fuel_effect_rejects_an_empty_race(total_laps: int) -> None:
    with pytest.raises(ValueError, match="at least one lap"):
        physical_fuel_effect(total_laps)


@pytest.mark.parametrize(("mass", "per_kg"), [(0.0, 0.03), (100.0, 0.0), (-1.0, 0.03)])
def test_physical_fuel_effect_rejects_unusable_constants(
    mass: float,
    per_kg: float,
) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        physical_fuel_effect(70, mass, per_kg)


def test_fuel_remaining_is_zero_on_the_final_lap() -> None:
    laps = pd.DataFrame({"LapNumber": [1.0, 35.0, 70.0]})
    assert laps_of_fuel_remaining(laps, RACE_LAPS).tolist() == [69.0, 35.0, 0.0]


def test_fuel_remaining_needs_a_lap_number() -> None:
    with pytest.raises(KeyError, match="LapNumber"):
        laps_of_fuel_remaining(pd.DataFrame({"TyreLife": [1.0]}), RACE_LAPS)


def test_correction_recovers_a_known_degradation_rate(
    stint_factory: StintFactory,
) -> None:
    true_degradation, true_fuel = 0.05, 0.04
    stint = stint_factory(
        first_lap=20,
        stint_laps=30,
        degradation_s_per_lap=true_degradation,
        fuel_s_per_lap=true_fuel,
    )
    corrected = fuel_corrected_lap_time(stint, true_fuel, RACE_LAPS)
    # With the fuel effect removed, lap time is base plus degradation times age.
    expected = 80.0 + true_degradation * stint["TyreLife"]
    pd.testing.assert_series_equal(
        corrected, expected, check_names=False, atol=1e-9
    )


def test_correction_leaves_the_final_lap_untouched(
    stint_factory: StintFactory,
) -> None:
    stint = stint_factory(first_lap=RACE_LAPS, stint_laps=1, fuel_s_per_lap=0.04)
    corrected = fuel_corrected_lap_time(stint, 0.04, RACE_LAPS)
    assert corrected.iloc[0] == pytest.approx(stint["lap_time_s"].iloc[0])


def test_a_zero_fuel_effect_changes_nothing(
    stint_factory: StintFactory,
) -> None:
    stint = stint_factory(first_lap=20, stint_laps=10, fuel_s_per_lap=0.04)
    corrected = fuel_corrected_lap_time(stint, 0.0, RACE_LAPS)
    pd.testing.assert_series_equal(
        corrected, stint["lap_time_s"], check_names=False
    )


def test_correction_rejects_a_negative_fuel_effect(
    stint_factory: StintFactory,
) -> None:
    stint = stint_factory(first_lap=20, stint_laps=5, fuel_s_per_lap=0.04)
    with pytest.raises(ValueError, match="must not be negative"):
        fuel_corrected_lap_time(stint, -0.01, RACE_LAPS)


def test_correction_needs_a_lap_time_column() -> None:
    with pytest.raises(KeyError, match="lap_time_s"):
        fuel_corrected_lap_time(pd.DataFrame({"LapNumber": [1.0]}), 0.04, RACE_LAPS)


def test_fuel_remaining_uses_each_races_own_distance() -> None:
    laps = pd.DataFrame(
        {
            "LapNumber": [1.0, 50.0, 1.0, 70.0],
            "race_id": ["2023 A", "2023 A", "2024 B", "2024 B"],
        }
    )
    remaining = laps_of_fuel_remaining_by_race(laps)
    # Race A ran to lap 50, race B to lap 70.
    assert remaining.tolist() == [49.0, 0.0, 69.0, 0.0]


def test_fuel_remaining_by_race_needs_a_race_column() -> None:
    with pytest.raises(KeyError, match="race_id"):
        laps_of_fuel_remaining_by_race(pd.DataFrame({"LapNumber": [1.0]}))
