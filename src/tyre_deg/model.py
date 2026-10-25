"""Fit tyre degradation while holding everything else that moves lap time.

The model is a single least squares fit of

    lap time = driver and race intercept
             + fuel effect x laps of fuel remaining
             + degradation rate for this compound x tyre age
             + baseline offset for this compound
             + error

Why each term is there:

Driver and race intercepts. Drivers and cars differ in pace by far more than a
tyre degrades over a stint, and baseline pace differs between races too. One
intercept per driver per race absorbs both without touching the slopes.

Fuel. A car sheds roughly 100kg over a race and gets faster as it does. Without
this term that improvement is credited to the tyre, which is enough to reverse
the sign of the medium compound's degradation.

What separates fuel from tyre age. Within one driver's race, lap number climbs
steadily while tyre age resets to zero at every pit stop. A ramp and a sawtooth
are not collinear, so both effects are identified from a single race. Drivers
also stop on different laps, which adds further separation between them.

Compound baseline offsets. A fresh medium is quicker than a fresh hard, so each
compound needs its own starting level as well as its own slope. Offsets are
measured against REFERENCE_COMPOUND.

Standard errors are deliberately not computed here. Laps within a stint are
strongly correlated, so the textbook formulas would be far too narrow. Use
:func:`bootstrap_degradation`, which resamples whole stints instead.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tyre_deg.config import (
    MODELLED_COMPOUNDS,
    RACE_COLUMN,
    REFERENCE_COMPOUND,
)
from tyre_deg.fuel import laps_of_fuel_remaining_by_race

logger = logging.getLogger(__name__)

FUEL_TERM = "fuel_per_lap_remaining"
STINT_KEY_COLUMNS = (RACE_COLUMN, "Driver", "Stint")


@dataclass(frozen=True)
class DegradationEstimate:
    """Coefficients from one fit of the degradation model.

    Attributes:
        fuel_s_per_lap: Lap time cost, in seconds, of one lap of fuel remaining.
        degradation_s_per_lap: Seconds lost per lap of tyre age, per compound.
        compound_offset_s: Baseline lap time of each compound relative to the
            reference compound, which is 0 by construction.
        reference_compound: Compound the offsets are measured against.
        laps: Laps the fit used.
        intercepts: Number of driver and race intercepts fitted.
        residual_std_s: Standard deviation of the residuals, in seconds.
    """

    fuel_s_per_lap: float
    degradation_s_per_lap: Mapping[str, float]
    compound_offset_s: Mapping[str, float]
    reference_compound: str
    laps: int
    intercepts: int
    residual_std_s: float


def _require_columns(laps: pd.DataFrame, columns: Sequence[str]) -> None:
    """Raise if any required column is absent.

    Args:
        laps: Frame to check.
        columns: Column names that must be present.

    Raises:
        KeyError: If any are missing.
    """
    missing = set(columns) - set(laps.columns)
    if missing:
        raise KeyError(f"lap frame is missing columns {sorted(missing)}")


def build_design(
    laps: pd.DataFrame,
    compounds: Sequence[str] = MODELLED_COMPOUNDS,
    reference_compound: str = REFERENCE_COMPOUND,
) -> tuple[pd.DataFrame, pd.Series]:
    """Build the design matrix and the lap times it explains.

    Args:
        laps: Clean laps, already restricted to the compounds of interest.
        compounds: Compounds to fit a degradation slope for.
        reference_compound: Compound the baseline offsets are measured against.

    Returns:
        The design matrix and the lap times, aligned.

    Raises:
        KeyError: If a required column is absent.
        ValueError: If no laps remain for the requested compounds.
    """
    _require_columns(laps, [*STINT_KEY_COLUMNS, "Compound", "TyreLife", "lap_time_s"])
    used = laps[laps["Compound"].isin(compounds)]
    if used.empty:
        raise ValueError(f"no laps for compounds {sorted(compounds)}")
    design = pd.get_dummies(
        used[RACE_COLUMN].astype(str) + " " + used["Driver"].astype(str),
        prefix="pace",
        dtype=float,
    )
    design[FUEL_TERM] = laps_of_fuel_remaining_by_race(used).astype(float)
    for compound in compounds:
        is_compound = (used["Compound"] == compound).astype(float)
        design[f"age_{compound}"] = is_compound * used["TyreLife"].astype(float)
        if compound != reference_compound:
            design[f"offset_{compound}"] = is_compound
    return design, used["lap_time_s"].astype(float)


def fit_degradation(
    laps: pd.DataFrame,
    compounds: Sequence[str] = MODELLED_COMPOUNDS,
    reference_compound: str = REFERENCE_COMPOUND,
) -> DegradationEstimate:
    """Fit the degradation model by least squares.

    Args:
        laps: Clean laps from several races, with race and driver columns.
        compounds: Compounds to fit a degradation slope for.
        reference_compound: Compound the baseline offsets are measured against.

    Returns:
        The fitted coefficients.

    Raises:
        ValueError: If the design matrix is rank deficient, which means two
            terms cannot be told apart from this data.
    """
    design, lap_times = build_design(laps, compounds, reference_compound)
    matrix = design.to_numpy()
    coefficients, _, rank, _ = np.linalg.lstsq(matrix, lap_times.to_numpy(), rcond=None)
    if rank < matrix.shape[1]:
        raise ValueError(
            f"design matrix is rank deficient ({rank} of {matrix.shape[1]} "
            "columns); terms cannot be separated from this data"
        )
    residuals = lap_times.to_numpy() - matrix @ coefficients
    return _estimate_from_coefficients(
        dict(zip(design.columns, coefficients, strict=True)),
        residuals=residuals,
        rank=rank,
        compounds=compounds,
        reference_compound=reference_compound,
    )


def _estimate_from_coefficients(
    by_name: Mapping[str, float],
    residuals: np.ndarray,
    rank: int,
    compounds: Sequence[str],
    reference_compound: str,
) -> DegradationEstimate:
    """Assemble the fitted coefficients into an estimate.

    Args:
        by_name: Fitted coefficient for each design column.
        residuals: Fit residuals in seconds.
        rank: Rank of the design matrix, used for the degrees of freedom.
        compounds: Compounds a slope was fitted for.
        reference_compound: Compound the offsets are measured against.

    Returns:
        The assembled estimate.
    """
    degrees_of_freedom = max(len(residuals) - rank, 1)
    return DegradationEstimate(
        fuel_s_per_lap=float(by_name[FUEL_TERM]),
        degradation_s_per_lap={
            compound: float(by_name[f"age_{compound}"]) for compound in compounds
        },
        compound_offset_s={
            compound: float(by_name.get(f"offset_{compound}", 0.0))
            for compound in compounds
        },
        reference_compound=reference_compound,
        laps=len(residuals),
        intercepts=sum(name.startswith("pace_") for name in by_name),
        residual_std_s=float(np.sqrt(residuals @ residuals / degrees_of_freedom)),
    )


@dataclass(frozen=True)
class CoefficientInterval:
    """A fitted coefficient and its bootstrap interval.

    Attributes:
        point: The coefficient from the fit on all the data.
        low: Lower end of the interval.
        high: Upper end of the interval.
    """

    point: float
    low: float
    high: float

    @property
    def width(self) -> float:
        """How wide the interval is."""
        return self.high - self.low

    def excludes(self, value: float) -> bool:
        """Whether a value falls outside the interval.

        Args:
            value: Value to test, for example 0.

        Returns:
            True when the value is outside the interval.
        """
        return not self.low <= value <= self.high


@dataclass(frozen=True)
class BootstrapResult:
    """Coefficients with intervals from resampling whole stints.

    Attributes:
        fuel: Fuel effect with its interval.
        degradation: Degradation rate with its interval, per compound.
        estimate: The fit on all the data, from which the points come.
        draws: Every successful resampled fit, kept so that an interval can be
            put on any quantity derived from the coefficients.
        resamples: Resamples that fitted successfully.
        failed_resamples: Resamples discarded because they could not be fitted.
        confidence: Confidence level the intervals cover.
    """

    fuel: CoefficientInterval
    degradation: Mapping[str, CoefficientInterval]
    estimate: DegradationEstimate
    draws: tuple[DegradationEstimate, ...]
    resamples: int
    failed_resamples: int
    confidence: float


def stint_positions(laps: pd.DataFrame) -> list[np.ndarray]:
    """Return the row positions of each stint, in a stable order.

    A stint is one driver's run on one set of tyres in one race. Resampling
    these, rather than individual laps, is what respects the fact that laps
    within a stint share a driver, a car, a tyre set and a fuel load.

    Args:
        laps: Clean laps with race, driver and stint columns.

    Returns:
        One array of row positions per stint, ordered by stint key.

    Raises:
        KeyError: If a required column is absent.
    """
    _require_columns(laps, STINT_KEY_COLUMNS)
    grouped = laps.groupby(list(STINT_KEY_COLUMNS), sort=True).indices
    return [grouped[key] for key in sorted(grouped)]


def _draw_resampled_fits(
    laps: pd.DataFrame,
    resamples: int,
    seed: int,
    compounds: Sequence[str],
) -> tuple[list[DegradationEstimate], int]:
    """Refit the model on resampled stints, reporting how many fits failed.

    Args:
        laps: Clean laps from the training races.
        resamples: How many resamples to draw.
        seed: Seed for the random generator.
        compounds: Compounds to fit a degradation slope for.

    Returns:
        The successful fits and the number that failed.
    """
    positions = stint_positions(laps)
    generator = np.random.default_rng(seed)
    draws: list[DegradationEstimate] = []
    failures = 0
    for _ in range(resamples):
        chosen = generator.integers(0, len(positions), size=len(positions))
        rows = np.concatenate([positions[index] for index in chosen])
        try:
            draws.append(fit_degradation(laps.iloc[rows], compounds))
        except (ValueError, KeyError) as error:
            failures += 1
            logger.debug("Discarded a resample that could not be fitted: %s", error)
    return draws, failures


def bootstrap_degradation(
    laps: pd.DataFrame,
    resamples: int = 1000,
    seed: int = 0,
    confidence: float = 0.95,
    compounds: Sequence[str] = MODELLED_COMPOUNDS,
    max_failure_rate: float = 0.05,
) -> BootstrapResult:
    """Fit the model many times on resampled stints to get intervals.

    Args:
        laps: Clean laps from the training races.
        resamples: How many resamples to draw.
        seed: Seed for the random generator, so results reproduce exactly.
        confidence: Confidence level for the percentile intervals.
        compounds: Compounds to fit a degradation slope for.
        max_failure_rate: Share of resamples allowed to fail before giving up.
            A resample fails when it happens to contain, say, only one compound.

    Returns:
        The coefficients with their intervals.

    Raises:
        ValueError: If the arguments are out of range.
        RuntimeError: If too many resamples could not be fitted, which means the
            data is too thin for the intervals to mean anything.
    """
    if resamples < 1:
        raise ValueError(f"need at least one resample, got {resamples}")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be between 0 and 1, got {confidence}")
    estimate = fit_degradation(laps, compounds)
    draws, failures = _draw_resampled_fits(laps, resamples, seed, compounds)
    if failures > max_failure_rate * resamples:
        raise RuntimeError(
            f"{failures} of {resamples} resamples could not be fitted, above the "
            f"{max_failure_rate:.0%} allowed; the data is too thin for intervals"
        )
    return _assemble_result(estimate, draws, failures, confidence, compounds)


def _assemble_result(
    estimate: DegradationEstimate,
    draws: Sequence[DegradationEstimate],
    failures: int,
    confidence: float,
    compounds: Sequence[str],
) -> BootstrapResult:
    """Turn the resampled fits into intervals around the full-data estimate.

    Args:
        estimate: The fit on all the data.
        draws: The fits from each successful resample.
        failures: How many resamples could not be fitted.
        confidence: Confidence level the intervals cover.
        compounds: Compounds a slope was fitted for.

    Returns:
        The assembled result.
    """
    return BootstrapResult(
        fuel=_interval(
            estimate.fuel_s_per_lap,
            [draw.fuel_s_per_lap for draw in draws],
            confidence,
        ),
        degradation={
            compound: _interval(
                estimate.degradation_s_per_lap[compound],
                [draw.degradation_s_per_lap[compound] for draw in draws],
                confidence,
            )
            for compound in compounds
        },
        estimate=estimate,
        draws=tuple(draws),
        resamples=len(draws),
        failed_resamples=failures,
        confidence=confidence,
    )


def _interval(
    point: float,
    draws: Sequence[float],
    confidence: float,
) -> CoefficientInterval:
    """Turn bootstrap draws into a percentile interval around a point estimate.

    Args:
        point: Coefficient from the fit on all the data.
        draws: The same coefficient from each resample.
        confidence: Confidence level to cover.

    Returns:
        The point estimate with its interval.
    """
    tail = (1.0 - confidence) / 2.0
    low, high = np.percentile(draws, [100 * tail, 100 * (1 - tail)])
    return CoefficientInterval(point=point, low=float(low), high=float(high))

def derived_interval(
    result: BootstrapResult,
    quantity: Callable[[DegradationEstimate], float],
) -> CoefficientInterval:
    """Put an interval on any quantity computed from the coefficients.

    Comparing two coefficients by checking whether their intervals overlap is a
    well known mistake: two intervals can overlap while their difference is
    still clearly non-zero. The sound comparison is to recompute the difference
    inside every resample, which is what this does. The same applies to the
    strategy comparison, which is a function of several coefficients at once.

    Args:
        result: A bootstrap result, which carries every resampled fit.
        quantity: Function taking one fit and returning the number of interest,
            for example the difference between two compounds' degradation rates.

    Returns:
        The quantity from the full-data fit, with its interval.

    Raises:
        ValueError: If the result carries no resampled fits.
    """
    if not result.draws:
        raise ValueError("bootstrap result has no resampled fits to work from")
    return _interval(
        quantity(result.estimate),
        [quantity(draw) for draw in result.draws],
        result.confidence,
    )
