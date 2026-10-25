"""Choose the degradation shape on the training races, never on the test race.

Decision 7 kept degradation as a straight line and said a curved shape would be
tested against held-out races rather than assumed. This module is that test.

Two rules make it honest.

The shape is chosen using the training races only. The test season is looked at
once, after the choice is made, and never used to make it. Picking the form that
scores best on the test race would quietly turn a held-out result into a tuned
one.

Only the shape is scored, not the absolute pace. The model fits one intercept
per driver per race, so it cannot predict a race it has never seen: those
intercepts do not exist. Each driver's own mean residual is therefore removed
within the held-out race, which is the same as granting every driver a free
baseline and asking whether the degradation and fuel curve carries over. That is
also exactly the part that matters, because intercepts cancel when two
strategies are compared.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tyre_deg.config import MODELLED_COMPOUNDS, RACE_COLUMN, REFERENCE_COMPOUND
from tyre_deg.model import (
    LINEAR,
    ModelForm,
    build_design,
    is_pace_term,
    pace_keys,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FormScore:
    """How well one degradation shape predicted races it was not fitted on.

    Attributes:
        form: The shape that was scored.
        shape_rmse_s: Error in seconds after each driver's own baseline is
            removed, averaged across held-out races.
        terms: Free parameters the shape adds per compound.
        folds: How many held-out races it was scored on.
    """

    form: ModelForm
    shape_rmse_s: float
    terms: int
    folds: int


def shape_residuals(
    laps: pd.DataFrame,
    coefficients: pd.Series,
    form: ModelForm = LINEAR,
    compounds: Sequence[str] = MODELLED_COMPOUNDS,
) -> pd.Series:
    """Return lap time errors once each driver's own baseline is removed.

    The form has to match the one the coefficients were fitted with. Scoring a
    curved fit against a design built for a straight line would quietly fill the
    curved terms with zeros and blame the shape for the mistake.

    Args:
        laps: Laps to score, carrying race, driver and the model's inputs.
        coefficients: Fitted coefficients for the non-pace terms, by name.
        form: The degradation shape the coefficients were fitted with.
        compounds: Compounds the model covers.

    Returns:
        Residuals in seconds, centred within each driver and race.
    """
    design, actual = build_design_like(
        laps, coefficients, compounds=compounds, form=form
    )
    predicted = design.to_numpy() @ coefficients.to_numpy()
    residual = actual.to_numpy() - predicted
    centred = pd.Series(residual, index=laps.index[: len(residual)])
    groups = pace_keys(laps).iloc[: len(residual)]
    return centred - centred.groupby(groups.to_numpy()).transform("mean")


def build_design_like(
    laps: pd.DataFrame,
    coefficients: pd.Series,
    compounds: Sequence[str] = MODELLED_COMPOUNDS,
    reference_compound: str = REFERENCE_COMPOUND,
    form: ModelForm = LINEAR,
) -> tuple[pd.DataFrame, pd.Series]:
    """Build a design matrix holding exactly the columns a fit produced.

    A held-out race has its own drivers and may not use every compound, so its
    design is lined up against the training columns and anything absent is
    filled with zeros.

    Args:
        laps: Laps to build a design for.
        coefficients: Fitted coefficients, whose index names the columns wanted.
        compounds: Compounds the model covers.
        reference_compound: Compound the offsets are measured against.
        form: The degradation shape.

    Returns:
        The aligned design matrix and the lap times.
    """
    design, actual = build_design(laps, compounds, reference_compound, form)
    aligned = design.reindex(columns=coefficients.index, fill_value=0.0)
    return aligned, actual


def fit_shape_coefficients(
    laps: pd.DataFrame,
    form: ModelForm = LINEAR,
    compounds: Sequence[str] = MODELLED_COMPOUNDS,
    reference_compound: str = REFERENCE_COMPOUND,
) -> pd.Series:
    """Fit the model and return only the coefficients that transfer.

    Driver and race baselines are dropped: they are specific to the races they
    were fitted on and mean nothing elsewhere.

    Args:
        laps: Clean training laps.
        form: The degradation shape.
        compounds: Compounds to cover.
        reference_compound: Compound the offsets are measured against.

    Returns:
        Fitted coefficients for the fuel, age and compound terms.

    Raises:
        ValueError: If the design matrix is rank deficient.
    """
    design, lap_times = build_design(laps, compounds, reference_compound, form)
    matrix = design.to_numpy()
    coefficients, _, rank, _ = np.linalg.lstsq(matrix, lap_times.to_numpy(), rcond=None)
    if rank < matrix.shape[1]:
        raise ValueError(
            f"design matrix is rank deficient ({rank} of {matrix.shape[1]} columns)"
        )
    named = pd.Series(coefficients, index=design.columns)
    return named[[name for name in named.index if not is_pace_term(name)]]


def score_form(
    laps: pd.DataFrame,
    form: ModelForm = LINEAR,
    compounds: Sequence[str] = MODELLED_COMPOUNDS,
) -> FormScore:
    """Score a shape by leaving each training race out in turn.

    Args:
        laps: Clean laps from the training races.
        form: The degradation shape to score.
        compounds: Compounds the model covers.

    Returns:
        The shape's held-out error.

    Raises:
        ValueError: If there are fewer than two races to leave out.
    """
    races = sorted(laps[RACE_COLUMN].unique())
    if len(races) < 2:
        raise ValueError(
            f"need at least two races to leave one out, got {len(races)}"
        )
    errors = []
    for held_out in races:
        training = laps[laps[RACE_COLUMN] != held_out]
        testing = laps[laps[RACE_COLUMN] == held_out]
        coefficients = fit_shape_coefficients(training, form, compounds)
        residuals = shape_residuals(testing, coefficients, form, compounds)
        errors.append(float(np.sqrt(np.mean(residuals.to_numpy() ** 2))))
        logger.info("%s held out: shape error %.4f s", held_out, errors[-1])
    return FormScore(
        form=form,
        shape_rmse_s=float(np.mean(errors)),
        terms=len(form.age_terms(pd.Series([1.0]))) - 1,
        folds=len(races),
    )


def compare_forms(
    laps: pd.DataFrame,
    forms: Sequence[ModelForm],
    compounds: Sequence[str] = MODELLED_COMPOUNDS,
) -> tuple[FormScore, ...]:
    """Score several shapes, best held-out error first.

    Args:
        laps: Clean laps from the training races.
        forms: The shapes to compare.
        compounds: Compounds the model covers.

    Returns:
        One score per shape, ordered by held-out error.
    """
    scores = [score_form(laps, form, compounds) for form in forms]
    return tuple(sorted(scores, key=lambda score: score.shape_rmse_s))


def residual_by_tyre_age(
    laps: pd.DataFrame,
    coefficients: pd.Series,
    bucket_laps: int = 5,
    form: ModelForm = LINEAR,
) -> pd.DataFrame:
    """Average the model's errors by tyre age, to show any curvature.

    A straight line that is wrong about the shape leaves a pattern behind: if
    real degradation eases off with age, the model over-predicts lap times late
    in a stint and the average residual there goes negative.

    Args:
        laps: Laps to score.
        coefficients: Fitted non-pace coefficients.
        bucket_laps: Width of each tyre age bucket, in laps.
        form: The degradation shape the coefficients were fitted with.

    Returns:
        Mean residual and lap count per age bucket.
    """
    residuals = shape_residuals(laps, coefficients, form)
    ages = laps["TyreLife"].astype(float).iloc[: len(residuals)]
    buckets = (ages // bucket_laps * bucket_laps).astype(int)
    frame = pd.DataFrame(
        {"bucket": buckets.to_numpy(), "residual": residuals.to_numpy()}
    )
    summary = frame.groupby("bucket")["residual"].agg(["mean", "size"])
    return summary.rename(columns={"mean": "mean_residual_s", "size": "laps"})
