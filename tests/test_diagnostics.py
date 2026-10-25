"""Tests for the uncontrolled slope diagnostics.

The key case is the one that motivates the whole correction: data built so that
the tyre genuinely degrades, but the uncorrected slope comes out negative.
"""

from __future__ import annotations

import pandas as pd
import pytest
from tests.conftest import RACE_LAPS, StintFactory

from tyre_deg.diagnostics import (
    compound_slopes,
    median_lap_time_by_tyre_age,
    uncontrolled_line,
    uncontrolled_slope,
)
from tyre_deg.fuel import fuel_corrected_lap_time


def test_slope_recovers_a_straight_line() -> None:
    ages = pd.Series(range(1, 51), dtype=float)
    times = 80.0 + 0.07 * ages
    assert uncontrolled_slope(ages, times) == pytest.approx(0.07)


def test_slope_is_none_when_there_are_too_few_laps() -> None:
    ages = pd.Series(range(1, 11), dtype=float)
    assert uncontrolled_slope(ages, 80.0 + 0.07 * ages, min_laps=40) is None


def test_slope_is_none_when_every_lap_has_the_same_tyre_age() -> None:
    ages = pd.Series([12.0] * 50)
    times = pd.Series([80.0] * 50)
    assert uncontrolled_slope(ages, times) is None


def test_slope_ignores_laps_with_missing_values() -> None:
    ages = pd.Series(range(1, 51), dtype=float)
    times = 80.0 + 0.07 * ages
    times.iloc[0] = None
    assert uncontrolled_slope(ages, times, min_laps=40) == pytest.approx(0.07)
    times.iloc[1:12] = None
    assert uncontrolled_slope(ages, times, min_laps=40) is None


def test_slope_rejects_mismatched_inputs() -> None:
    with pytest.raises(ValueError, match="differ in length"):
        uncontrolled_slope(pd.Series([1.0, 2.0]), pd.Series([80.0]))


def test_uncorrected_slope_can_invert_the_sign_of_real_degradation(
    stint_factory: StintFactory,
) -> None:
    # The tyre degrades at 0.03 s/lap, but the car sheds fuel worth 0.05 s/lap,
    # and tyre age advances with the race, so the raw trend points downwards.
    stint = stint_factory(
        stint_laps=60, degradation_s_per_lap=0.03, fuel_s_per_lap=0.05
    )
    raw = uncontrolled_slope(stint["TyreLife"], stint["lap_time_s"])
    corrected = uncontrolled_slope(
        stint["TyreLife"], fuel_corrected_lap_time(stint, 0.05, RACE_LAPS)
    )
    assert raw is not None and raw < 0
    assert raw == pytest.approx(0.03 - 0.05)
    assert corrected == pytest.approx(0.03)


def test_compound_slopes_order_by_laps_and_keep_thin_compounds_visible(
    stint_factory: StintFactory,
) -> None:
    hard = stint_factory(stint_laps=60, degradation_s_per_lap=0.04)
    medium = stint_factory(
        stint_laps=45, base_s=79.0, degradation_s_per_lap=0.06, compound="MEDIUM"
    )
    soft = stint_factory(
        stint_laps=9, base_s=78.0, degradation_s_per_lap=0.09, compound="SOFT"
    )
    results = compound_slopes(pd.concat([hard, medium, soft], ignore_index=True))
    assert [result.compound for result in results] == ["HARD", "MEDIUM", "SOFT"]
    assert [result.laps for result in results] == [60, 45, 9]
    assert results[0].slope_s_per_lap == pytest.approx(0.04)
    assert results[1].slope_s_per_lap == pytest.approx(0.06)
    assert results[2].has_estimate is False
    assert results[2].slope_s_per_lap is None


def test_compound_slopes_needs_its_input_columns() -> None:
    with pytest.raises(KeyError, match="TyreLife"):
        compound_slopes(pd.DataFrame({"Compound": ["HARD"], "lap_time_s": [80.0]}))


def test_line_fit_recovers_slope_and_intercept(
    stint_factory: StintFactory,
) -> None:
    stint = stint_factory(stint_laps=50, base_s=80.0, degradation_s_per_lap=0.06)
    fit = uncontrolled_line(stint["TyreLife"], stint["lap_time_s"])
    assert fit is not None
    assert fit.slope_s_per_lap == pytest.approx(0.06)
    # The stint starts at a tyre age of one lap, so the intercept sits one
    # degradation step below the first lap time.
    assert fit.intercept_s == pytest.approx(80.0)
    assert fit.laps == 50
    assert (fit.youngest_age, fit.oldest_age) == (1.0, 50.0)


def test_line_fit_predicts_along_the_fitted_line(
    stint_factory: StintFactory,
) -> None:
    stint = stint_factory(stint_laps=50, base_s=80.0, degradation_s_per_lap=0.06)
    fit = uncontrolled_line(stint["TyreLife"], stint["lap_time_s"])
    assert fit is not None
    assert fit.predict(0.0) == pytest.approx(80.0)
    assert fit.predict(10.0) == pytest.approx(80.6)


def test_line_fit_is_none_when_data_is_too_thin(
    stint_factory: StintFactory,
) -> None:
    stint = stint_factory(stint_laps=10)
    assert uncontrolled_line(stint["TyreLife"], stint["lap_time_s"]) is None


def test_median_by_tyre_age_follows_the_degradation(
    stint_factory: StintFactory,
) -> None:
    # Five drivers running the same stint, so every age has five laps.
    stint = pd.concat(
        [stint_factory(stint_laps=20, degradation_s_per_lap=0.05) for _ in range(5)],
        ignore_index=True,
    )
    medians = median_lap_time_by_tyre_age(stint, min_laps_per_age=5)
    assert medians.index.tolist() == [float(age) for age in range(1, 21)]
    assert medians.iloc[0] == pytest.approx(80.05)
    assert medians.iloc[-1] == pytest.approx(81.0)


def test_median_by_tyre_age_drops_thinly_covered_ages(
    stint_factory: StintFactory,
) -> None:
    common = pd.concat(
        [stint_factory(stint_laps=5) for _ in range(5)], ignore_index=True
    )
    rare = stint_factory(first_lap=40, stint_laps=30).query("TyreLife > 5")
    medians = median_lap_time_by_tyre_age(
        pd.concat([common, rare], ignore_index=True), min_laps_per_age=5
    )
    assert medians.index.max() == 5.0


def test_median_by_tyre_age_needs_its_columns() -> None:
    with pytest.raises(KeyError, match="TyreLife"):
        median_lap_time_by_tyre_age(pd.DataFrame({"lap_time_s": [80.0]}))
