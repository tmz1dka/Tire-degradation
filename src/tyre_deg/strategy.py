"""Compare pit strategies using the fitted degradation model.

Comparing two strategies for the same driver in the same race is simpler than
simulating a race. Both cover the same laps with the same fuel load on each lap,
so the driver's pace and the fuel burn are identical in both and cancel in the
difference. Only three things differ:

* which compound is on the car,
* how old that tyre is on each lap,
* how many pit stops were made.

So a strategy's cost is the sum over its laps of the degradation and compound
terms, plus the time lost in the pit lane. Absolute race time is never needed,
which also means the answer does not depend on how quick the driver was.

The pit loss is measured rather than assumed: for every real stop, the in and
out laps are compared against what the model says those same laps would have
taken had the car stayed out on its old tyres.

What this does not model: track position. A strategy that comes out faster here
could still lose on the road if it leaves a driver stuck behind traffic, which
at some circuits matters more than the lap time. The number this produces is a
free-air difference and the write-up says so.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from tyre_deg.config import RACE_COLUMN
from tyre_deg.model import DegradationEstimate, predict_lap_time

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Stint:
    """One run on one set of tyres.

    Attributes:
        compound: Tyre compound.
        laps: How many laps the stint lasts.
    """

    compound: str
    laps: int

    def __post_init__(self) -> None:
        """Reject a stint that cannot exist.

        Raises:
            ValueError: If the stint has no laps.
        """
        if self.laps < 1:
            raise ValueError(f"a stint needs at least one lap, got {self.laps}")

    @property
    def tyre_ages(self) -> range:
        """Tyre age on each lap of the stint, starting at 1 on a fresh set."""
        return range(1, self.laps + 1)


@dataclass(frozen=True)
class Strategy:
    """A sequence of stints covering a whole race.

    Attributes:
        name: Label for reporting, for example "one stop".
        stints: The stints in order.
    """

    name: str
    stints: tuple[Stint, ...]

    def __post_init__(self) -> None:
        """Reject a strategy with no stints.

        Raises:
            ValueError: If there are no stints.
        """
        if not self.stints:
            raise ValueError("a strategy needs at least one stint")

    @property
    def stops(self) -> int:
        """Number of pit stops, one fewer than the number of stints."""
        return len(self.stints) - 1

    @property
    def race_laps(self) -> int:
        """Total laps the strategy covers."""
        return sum(stint.laps for stint in self.stints)

    @property
    def compounds(self) -> tuple[str, ...]:
        """Compounds used, in order."""
        return tuple(stint.compound for stint in self.stints)


def measure_pit_loss(
    laps: pd.DataFrame,
    estimate: DegradationEstimate,
) -> float:
    """Measure what a pit stop costs, in seconds, from the races themselves.

    For each stop, the real in lap and out lap are compared against what the
    model says those two laps would have taken at racing pace on the old tyres.
    The median across stops is used, so one botched stop or one stop made under
    a safety car cannot drag the estimate around.

    Args:
        laps: All laps of the races, including pit laps, with lap times.
        estimate: A model fitted on those races.

    Returns:
        Median seconds lost to one pit stop.

    Raises:
        KeyError: If a required column is absent.
        ValueError: If no completed stops could be measured.
    """
    required = ["Driver", "Stint", "LapNumber", "TyreLife", "Compound", "lap_time_s"]
    missing = set(required) - set(laps.columns)
    if missing:
        raise KeyError(f"lap frame is missing columns {sorted(missing)}")
    distances = (
        laps.groupby(RACE_COLUMN)["LapNumber"].max().astype(int).to_dict()
    )
    costs = [
        cost
        for _, race_laps in laps.groupby(RACE_COLUMN, sort=True)
        for cost in _stop_costs(race_laps, estimate, distances)
    ]
    if not costs:
        raise ValueError("no completed pit stops found to measure")
    median = float(pd.Series(costs).median())
    logger.info("Pit loss measured from %d stops: %.2f s", len(costs), median)
    return median


def _stop_costs(
    race_laps: pd.DataFrame,
    estimate: DegradationEstimate,
    race_distance: Mapping[str, int],
) -> list[float]:
    """Return the measured cost of every pit stop in one race.

    Args:
        race_laps: Every lap of a single race.
        estimate: A model fitted on that race.
        race_distance: Laps in each race, keyed by race identifier.

    Returns:
        One cost in seconds per stop.
    """
    costs: list[float] = []
    for _, driver_laps in race_laps.groupby("Driver", sort=True):
        ordered = driver_laps.sort_values("LapNumber")
        in_laps = ordered[ordered["PitInTime"].notna()]
        for _, in_lap in in_laps.iterrows():
            out_lap = ordered[ordered["LapNumber"] == in_lap["LapNumber"] + 1]
            if out_lap.empty or out_lap.iloc[0]["PitOutTime"] is pd.NaT:
                continue
            cost = _stop_cost(in_lap, out_lap.iloc[0], estimate, race_distance)
            if cost is not None:
                costs.append(cost)
    return costs


def _stop_cost(
    in_lap: pd.Series,
    out_lap: pd.Series,
    estimate: DegradationEstimate,
    race_distance: Mapping[str, int],
) -> float | None:
    """Return one stop's cost, or None if either lap is missing a time.

    The counterfactual is the same two laps with the old tyre still on the car,
    so its age keeps climbing instead of resetting.

    Args:
        in_lap: The lap entering the pits.
        out_lap: The lap leaving the pits.
        estimate: A fitted model.
        race_distance: Laps in each race, keyed by race identifier.

    Returns:
        Seconds lost, or None when a lap time is missing.
    """
    actual = in_lap["lap_time_s"] + out_lap["lap_time_s"]
    if pd.isna(actual):
        return None
    stayed_out = pd.DataFrame(
        {
            RACE_COLUMN: [in_lap[RACE_COLUMN], in_lap[RACE_COLUMN]],
            "Driver": [in_lap["Driver"], in_lap["Driver"]],
            "Compound": [in_lap["Compound"], in_lap["Compound"]],
            "TyreLife": [in_lap["TyreLife"], in_lap["TyreLife"] + 1],
            "LapNumber": [in_lap["LapNumber"], in_lap["LapNumber"] + 1],
        }
    )
    stay_out_time = predict_lap_time(stayed_out, estimate, race_distance).sum()
    return float(actual - stay_out_time)


def max_observed_tyre_age(laps: pd.DataFrame) -> dict[str, float]:
    """Return the oldest tyre age actually seen for each compound.

    The model is a straight line, and a straight line will happily predict a
    40 lap stint from 20 laps of evidence. That prediction is not supported by
    anything, so simulations are refused beyond this.

    Args:
        laps: Clean laps with compound and tyre age.

    Returns:
        Oldest tyre age per compound.

    Raises:
        KeyError: If a required column is absent.
    """
    missing = {"Compound", "TyreLife"} - set(laps.columns)
    if missing:
        raise KeyError(f"lap frame is missing columns {sorted(missing)}")
    return laps.groupby("Compound")["TyreLife"].max().astype(float).to_dict()


def check_within_evidence(
    strategy: Strategy,
    max_tyre_age: Mapping[str, float],
) -> None:
    """Raise if a strategy needs a stint longer than anything observed.

    Args:
        strategy: The strategy to check.
        max_tyre_age: Oldest tyre age seen per compound.

    Raises:
        ValueError: If a stint runs past the evidence, or uses a compound the
            model was not fitted for.
    """
    for stint in strategy.stints:
        if stint.compound not in max_tyre_age:
            raise ValueError(
                f"{strategy.name}: no data for compound {stint.compound!r}"
            )
        oldest = max_tyre_age[stint.compound]
        if stint.laps > oldest:
            raise ValueError(
                f"{strategy.name}: a {stint.laps} lap stint on the "
                f"{stint.compound.lower()} goes beyond the oldest tyre observed "
                f"({oldest:.0f} laps), so the model would be extrapolating"
            )


def strategy_cost(
    strategy: Strategy,
    estimate: DegradationEstimate,
    pit_loss_s: float,
) -> float:
    """Return the part of race time that depends on the strategy.

    Driver pace and fuel burn are identical across strategies covering the same
    race, so they are left out. What remains is tyre wear, the compound
    baselines and the time lost in the pit lane. The number is only meaningful
    compared against another strategy over the same race distance.

    Args:
        strategy: The strategy to cost.
        estimate: A fitted model.
        pit_loss_s: Seconds lost per pit stop.

    Returns:
        Strategy dependent race time in seconds.

    Raises:
        KeyError: If the model has no coefficient for a compound used.
    """
    total = strategy.stops * pit_loss_s
    for stint in strategy.stints:
        rate = estimate.degradation_s_per_lap[stint.compound]
        offset = estimate.compound_offset_s[stint.compound]
        laps = stint.laps
        # Sum of ages 1..laps, so the closed form rather than a loop.
        total += rate * laps * (laps + 1) / 2 + offset * laps
    return total


def compare_strategies(
    faster: Strategy,
    slower: Strategy,
    estimate: DegradationEstimate,
    pit_loss_s: float,
) -> float:
    """Return how much more time ``slower`` takes than ``faster``.

    Args:
        faster: The reference strategy.
        slower: The strategy being judged against it.
        estimate: A fitted model.
        pit_loss_s: Seconds lost per pit stop.

    Returns:
        Seconds. Positive means ``slower`` costs more time.

    Raises:
        ValueError: If the two strategies cover different race distances.
    """
    if faster.race_laps != slower.race_laps:
        raise ValueError(
            f"strategies cover different races: {faster.name} runs "
            f"{faster.race_laps} laps, {slower.name} runs {slower.race_laps}"
        )
    return strategy_cost(slower, estimate, pit_loss_s) - strategy_cost(
        faster, estimate, pit_loss_s
    )


def strategy_from_stints(name: str, stints: Sequence[tuple[str, int]]) -> Strategy:
    """Build a strategy from compound and length pairs.

    Args:
        name: Label for reporting.
        stints: Pairs of compound name and stint length.

    Returns:
        The strategy.
    """
    return Strategy(name=name, stints=tuple(Stint(c, n) for c, n in stints))


def cumulative_cost(
    strategy: Strategy,
    estimate: DegradationEstimate,
    pit_loss_s: float,
) -> pd.Series:
    """Return the strategy dependent time accumulated by each lap of the race.

    The pit loss lands on the lap a new stint starts, so the series steps up
    there and then climbs more slowly on fresh tyres. The final value equals
    :func:`strategy_cost`.

    Args:
        strategy: The strategy to cost.
        estimate: A fitted model.
        pit_loss_s: Seconds lost per pit stop.

    Returns:
        Running cost in seconds, indexed by lap number from 1.

    Raises:
        KeyError: If the model has no coefficient for a compound used.
    """
    running = 0.0
    costs: list[float] = []
    for index, stint in enumerate(strategy.stints):
        if index > 0:
            running += pit_loss_s
        rate = estimate.degradation_s_per_lap[stint.compound]
        offset = estimate.compound_offset_s[stint.compound]
        for age in stint.tyre_ages:
            running += rate * age + offset
            costs.append(running)
    return pd.Series(
        costs, index=pd.RangeIndex(1, len(costs) + 1, name="lap"), name=strategy.name
    )
