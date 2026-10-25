"""Tests for choosing the degradation shape.

The important case is a race whose tyres really do wear on a curve. If the
comparison cannot tell that apart from a straight line, it cannot be trusted
when it says a straight line is enough.
"""

from __future__ import annotations

import pandas as pd
import pytest
from tests.conftest import RaceFactory, Truth

from tyre_deg.model import LINEAR, QUADRATIC, hinge_form
from tyre_deg.validation import (
    build_design_like,
    compare_forms,
    fit_shape_coefficients,
    residual_by_tyre_age,
    score_form,
    shape_residuals,
)


@pytest.fixture
def two_linear_races(race_factory: RaceFactory) -> pd.DataFrame:
    """Two races whose tyres wear in a straight line."""
    return pd.concat(
        [
            race_factory("2023 Race", stop_shift=0, noise_std=0.1, seed=1),
            race_factory("2024 Race", stop_shift=3, noise_std=0.1, seed=2),
        ],
        ignore_index=True,
    )


@pytest.fixture
def two_curved_races(race_factory: RaceFactory, truth: Truth) -> pd.DataFrame:
    """Two races whose wear starts fast and then eases off sharply."""

    def curved(compound: str, age: float) -> float:
        return truth.degradation[compound] * age - 0.0015 * age**2

    return pd.concat(
        [
            race_factory("2023 Race", stop_shift=0, degradation=curved,
                         noise_std=0.1, seed=1),
            race_factory("2024 Race", stop_shift=3, degradation=curved,
                         noise_std=0.1, seed=2),
        ],
        ignore_index=True,
    )


def test_fitted_coefficients_drop_the_driver_baselines(
    two_linear_races: pd.DataFrame,
) -> None:
    coefficients = fit_shape_coefficients(two_linear_races)
    assert not any(name.startswith("pace_") for name in coefficients.index)
    assert "fuel_per_lap_remaining" in coefficients.index
    assert {"age_MEDIUM", "age_HARD"} <= set(coefficients.index)


def test_a_model_fitted_on_a_race_explains_that_race(
    race_factory: RaceFactory,
) -> None:
    clean = race_factory("2023 Race")
    residuals = shape_residuals(clean, fit_shape_coefficients(clean))
    assert residuals.abs().max() < 1e-6


def test_curvature_is_found_when_it_is_really_there(
    two_curved_races: pd.DataFrame,
) -> None:
    scores = {
        score.form.name: score.shape_rmse_s
        for score in compare_forms(two_curved_races, [LINEAR, QUADRATIC])
    }
    assert scores["quadratic"] < scores["linear"]


def test_a_straight_line_is_not_beaten_on_straight_line_data(
    two_linear_races: pd.DataFrame,
) -> None:
    scores = {
        score.form.name: score.shape_rmse_s
        for score in compare_forms(two_linear_races, [LINEAR, QUADRATIC])
    }
    assert scores["linear"] <= scores["quadratic"]


def test_forms_come_back_best_first(two_curved_races: pd.DataFrame) -> None:
    scores = compare_forms(two_curved_races, [LINEAR, QUADRATIC, hinge_form(20)])
    errors = [score.shape_rmse_s for score in scores]
    assert errors == sorted(errors)
    assert scores[0].folds == 2


def test_extra_terms_are_counted(two_linear_races: pd.DataFrame) -> None:
    assert score_form(two_linear_races, LINEAR).terms == 0
    assert score_form(two_linear_races, QUADRATIC).terms == 1
    assert score_form(two_linear_races, hinge_form(20)).terms == 1


def test_one_race_cannot_be_left_out(race_factory: RaceFactory) -> None:
    with pytest.raises(ValueError, match="at least two races"):
        score_form(race_factory("2023 Race"))


def test_a_missing_compound_becomes_a_zero_column(
    two_linear_races: pd.DataFrame,
) -> None:
    coefficients = fit_shape_coefficients(two_linear_races)
    hard_only = two_linear_races[two_linear_races["Compound"] == "HARD"]
    design, _ = build_design_like(hard_only, coefficients)
    assert list(design.columns) == list(coefficients.index)
    assert (design["age_MEDIUM"] == 0.0).all()


def test_residuals_are_summarized_by_tyre_age(
    two_linear_races: pd.DataFrame,
) -> None:
    coefficients = fit_shape_coefficients(two_linear_races)
    table = residual_by_tyre_age(two_linear_races, coefficients, bucket_laps=5)
    assert table.index.min() == 0
    assert table["laps"].sum() == len(two_linear_races)
    assert set(table.columns) == {"mean_residual_s", "laps"}
