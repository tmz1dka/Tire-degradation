"""Tests for the degradation model.

Lap times are built from known coefficients, so the fit can be checked for
recovering the right answer rather than merely running. Noise, where used, is
seeded.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from tyre_deg.model import (
    CoefficientInterval,
    bootstrap_degradation,
    build_design,
    derived_interval,
    fit_degradation,
    stint_positions,
)

TOTAL_LAPS = 70
FUEL = 0.045
DEGRADATION = {"MEDIUM": 0.05, "HARD": 0.07}
OFFSETS = {"MEDIUM": -0.40, "HARD": 0.0}
PACE = {"VER": 80.0, "NOR": 80.3, "PIA": 80.5, "RUS": 80.8, "LEC": 81.0, "HAM": 81.2}


def build_laps(
    race_id: str,
    stints: list[tuple[str, int, str, int, int]],
    noise_std: float = 0.0,
    seed: int = 0,
) -> pd.DataFrame:
    """Build laps whose times contain known pace, fuel and degradation terms.

    Args:
        race_id: Race identifier.
        stints: Tuples of driver, stint number, compound, first lap, length.
        noise_std: Standard deviation of optional seeded noise, in seconds.
        seed: Seed for that noise.

    Returns:
        A lap frame with every column the model requires.
    """
    generator = np.random.default_rng(seed)
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
                        PACE[driver]
                        + FUEL * (TOTAL_LAPS - lap_number)
                        + DEGRADATION[compound] * age
                        + OFFSETS[compound]
                    ),
                }
            )
    frame = pd.DataFrame(rows)
    if noise_std:
        frame["lap_time_s"] += generator.normal(0.0, noise_std, len(frame))
    return frame


def three_stint_race(race_id: str, stop_shift: int, **kwargs: object) -> pd.DataFrame:
    """Build a race where every driver runs medium, hard, hard at varied laps."""
    stints = []
    for index, driver in enumerate(PACE):
        first_stop = 18 + stop_shift + index
        second_stop = first_stop + 24
        stints.extend(
            [
                (driver, 1, "MEDIUM", 1, first_stop - 1),
                (driver, 2, "HARD", first_stop, second_stop - first_stop),
                (driver, 3, "HARD", second_stop, TOTAL_LAPS - second_stop + 1),
            ]
        )
    return build_laps(race_id, stints, **kwargs)


@pytest.fixture
def two_races() -> pd.DataFrame:
    """Two races of six drivers running three stints each."""
    return pd.concat(
        [three_stint_race("2023 Race", 0), three_stint_race("2024 Race", 3)],
        ignore_index=True,
    )


def test_fit_recovers_the_coefficients_it_was_built_from(
    two_races: pd.DataFrame,
) -> None:
    fit = fit_degradation(two_races)
    assert fit.fuel_s_per_lap == pytest.approx(FUEL, abs=1e-9)
    assert fit.degradation_s_per_lap["MEDIUM"] == pytest.approx(0.05, abs=1e-9)
    assert fit.degradation_s_per_lap["HARD"] == pytest.approx(0.07, abs=1e-9)


def test_fit_recovers_the_compound_baseline_offset(two_races: pd.DataFrame) -> None:
    fit = fit_degradation(two_races)
    assert fit.compound_offset_s["MEDIUM"] == pytest.approx(-0.40, abs=1e-9)
    assert fit.compound_offset_s["HARD"] == 0.0
    assert fit.reference_compound == "HARD"


def test_fit_uses_one_intercept_per_driver_per_race(two_races: pd.DataFrame) -> None:
    fit = fit_degradation(two_races)
    assert fit.intercepts == len(PACE) * 2
    assert fit.residual_std_s == pytest.approx(0.0, abs=1e-9)
    assert fit.laps == len(two_races)


def test_a_single_stint_cannot_separate_fuel_from_tyre_age() -> None:
    # Within one stint, tyre age rises exactly as fuel remaining falls, so the
    # two terms are the same column in disguise. Several stints break the tie.
    one_stint = build_laps("2023 Race", [("VER", 1, "HARD", 1, 30)])
    with pytest.raises(ValueError, match="rank deficient"):
        fit_degradation(one_stint, compounds=["HARD"])


def test_two_stints_for_one_driver_are_enough_to_separate_them() -> None:
    # The pit stop resets tyre age while fuel keeps falling, which is what makes
    # the two effects identifiable even from a single driver's race.
    two_stints = build_laps(
        "2023 Race",
        [("VER", 1, "HARD", 1, 30), ("VER", 2, "HARD", 31, 40)],
    )
    fit = fit_degradation(two_stints, compounds=["HARD"])
    assert fit.fuel_s_per_lap == pytest.approx(FUEL, abs=1e-9)
    assert fit.degradation_s_per_lap["HARD"] == pytest.approx(0.07, abs=1e-9)


def test_design_has_one_column_per_term(two_races: pd.DataFrame) -> None:
    design, lap_times = build_design(two_races)
    assert len(design) == len(lap_times) == len(two_races)
    assert "fuel_per_lap_remaining" in design.columns
    assert {"age_MEDIUM", "age_HARD", "offset_MEDIUM"} <= set(design.columns)
    # The reference compound gets no offset column: it is the baseline.
    assert "offset_HARD" not in design.columns


def test_design_rejects_a_frame_with_no_usable_compounds(
    two_races: pd.DataFrame,
) -> None:
    with pytest.raises(ValueError, match="no laps for compounds"):
        build_design(two_races, compounds=["INTERMEDIATE"])


def test_design_needs_its_columns() -> None:
    with pytest.raises(KeyError, match="TyreLife"):
        build_design(pd.DataFrame({"lap_time_s": [80.0]}))


def test_stint_positions_finds_every_stint(two_races: pd.DataFrame) -> None:
    positions = stint_positions(two_races)
    assert len(positions) == len(PACE) * 3 * 2
    assert sum(len(block) for block in positions) == len(two_races)


def test_bootstrap_is_reproducible_from_its_seed(two_races: pd.DataFrame) -> None:
    noisy = three_stint_race("2023 Race", 0, noise_std=0.15, seed=1)
    first = bootstrap_degradation(noisy, resamples=50, seed=7)
    again = bootstrap_degradation(noisy, resamples=50, seed=7)
    different = bootstrap_degradation(noisy, resamples=50, seed=8)
    assert first.fuel == again.fuel
    assert first.fuel != different.fuel


def test_bootstrap_intervals_cover_the_true_coefficients() -> None:
    noisy = pd.concat(
        [
            three_stint_race("2023 Race", 0, noise_std=0.15, seed=1),
            three_stint_race("2024 Race", 3, noise_std=0.15, seed=2),
        ],
        ignore_index=True,
    )
    result = bootstrap_degradation(noisy, resamples=200, seed=3)
    assert result.fuel.low <= FUEL <= result.fuel.high
    for compound, true_rate in DEGRADATION.items():
        interval = result.degradation[compound]
        assert interval.low <= true_rate <= interval.high
        assert interval.excludes(0.0)
    assert result.resamples == 200
    assert result.failed_resamples == 0


def test_bootstrap_rejects_impossible_arguments(two_races: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="at least one resample"):
        bootstrap_degradation(two_races, resamples=0)
    with pytest.raises(ValueError, match="confidence must be between"):
        bootstrap_degradation(two_races, resamples=5, confidence=1.5)


def test_interval_reports_its_width_and_what_it_excludes() -> None:
    interval = CoefficientInterval(point=0.05, low=0.04, high=0.07)
    assert interval.width == pytest.approx(0.03)
    assert interval.excludes(0.0) is True
    assert interval.excludes(0.05) is False


def test_derived_interval_compares_two_coefficients_properly() -> None:
    noisy = pd.concat(
        [
            three_stint_race("2023 Race", 0, noise_std=0.15, seed=1),
            three_stint_race("2024 Race", 3, noise_std=0.15, seed=2),
        ],
        ignore_index=True,
    )
    result = bootstrap_degradation(noisy, resamples=200, seed=3)
    gap = derived_interval(
        result,
        lambda fit: fit.degradation_s_per_lap["HARD"]
        - fit.degradation_s_per_lap["MEDIUM"],
    )
    true_gap = DEGRADATION["HARD"] - DEGRADATION["MEDIUM"]
    assert gap.low <= true_gap <= gap.high
    assert len(result.draws) == 200


def test_derived_interval_needs_resampled_fits(two_races: pd.DataFrame) -> None:
    result = bootstrap_degradation(two_races, resamples=5, seed=0)
    empty = replace(result, draws=())
    with pytest.raises(ValueError, match="no resampled fits"):
        derived_interval(empty, lambda fit: fit.fuel_s_per_lap)
