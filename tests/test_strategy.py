"""Tests for the pit strategy comparison.

Costs here are small enough to work out by hand, so the tests check the
arithmetic rather than only that the code runs.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tyre_deg.model import DegradationEstimate
from tyre_deg.strategy import (
    Stint,
    Strategy,
    check_within_evidence,
    compare_strategies,
    cumulative_cost,
    max_observed_tyre_age,
    measure_pit_loss,
    strategy_cost,
    strategy_from_stints,
)

RACE_LAPS = 70
PIT_LOSS = 20.0


def make_estimate(
    degradation: dict[str, float],
    offsets: dict[str, float],
    fuel: float = 0.045,
    pace: float = 80.0,
) -> DegradationEstimate:
    """Build a model with known coefficients, bypassing any fitting."""
    return DegradationEstimate(
        fuel_s_per_lap=fuel,
        degradation_s_per_lap=degradation,
        compound_offset_s=offsets,
        reference_compound="HARD",
        laps=0,
        pace_s={"2023 Race VER": pace},
        residual_std_s=0.0,
    )


def test_a_stint_needs_laps() -> None:
    with pytest.raises(ValueError, match="at least one lap"):
        Stint("HARD", 0)


def test_stint_tyre_ages_start_fresh() -> None:
    assert list(Stint("HARD", 3).tyre_ages) == [1, 2, 3]


def test_a_strategy_needs_stints() -> None:
    with pytest.raises(ValueError, match="at least one stint"):
        Strategy("empty", ())


def test_strategy_counts_stops_and_laps() -> None:
    strategy = strategy_from_stints("two stop", [("MEDIUM", 18), ("HARD", 27),
                                                 ("HARD", 25)])
    assert strategy.stops == 2
    assert strategy.race_laps == 70
    assert strategy.compounds == ("MEDIUM", "HARD", "HARD")


def test_strategy_cost_sums_degradation_over_every_lap() -> None:
    estimate = make_estimate({"HARD": 0.07}, {"HARD": 0.0})
    one_stint = strategy_from_stints("no stop", [("HARD", 10)])
    # Ages 1 to 10 sum to 55, so 0.07 x 55 = 3.85 seconds, and no pit stops.
    assert strategy_cost(one_stint, estimate, PIT_LOSS) == pytest.approx(3.85)


def test_strategy_cost_adds_the_pit_loss_for_each_stop() -> None:
    estimate = make_estimate({"HARD": 0.0}, {"HARD": 0.0})
    two_stints = strategy_from_stints("one stop", [("HARD", 5), ("HARD", 5)])
    assert strategy_cost(two_stints, estimate, PIT_LOSS) == pytest.approx(20.0)


def test_strategy_cost_includes_the_compound_baseline() -> None:
    estimate = make_estimate({"HARD": 0.0, "MEDIUM": 0.0},
                             {"HARD": 0.0, "MEDIUM": -0.3})
    medium = strategy_from_stints("medium", [("MEDIUM", 10)])
    assert strategy_cost(medium, estimate, PIT_LOSS) == pytest.approx(-3.0)


def test_an_extra_stop_pays_for_itself_only_if_the_tyre_saving_is_bigger() -> None:
    estimate = make_estimate({"HARD": 0.07}, {"HARD": 0.0})
    one_stop = strategy_from_stints("one stop", [("HARD", 35), ("HARD", 35)])
    two_stop = strategy_from_stints("two stop", [("HARD", 24), ("HARD", 23),
                                                 ("HARD", 23)])
    # Shorter stints mean younger tyres: the two stop saves 28.6s of wear here.
    # Whether that is worth it depends entirely on what a stop costs.
    assert compare_strategies(one_stop, two_stop, estimate, 20.0) < 0
    assert compare_strategies(one_stop, two_stop, estimate, 35.0) > 0


def test_comparing_strategies_over_different_races_is_refused() -> None:
    estimate = make_estimate({"HARD": 0.07}, {"HARD": 0.0})
    short = strategy_from_stints("short", [("HARD", 10)])
    long_race = strategy_from_stints("long", [("HARD", 20)])
    with pytest.raises(ValueError, match="different races"):
        compare_strategies(short, long_race, estimate, PIT_LOSS)


def test_max_observed_tyre_age_reads_the_data() -> None:
    laps = pd.DataFrame(
        {
            "Compound": ["HARD", "HARD", "MEDIUM"],
            "TyreLife": [12.0, 37.0, 25.0],
        }
    )
    assert max_observed_tyre_age(laps) == {"HARD": 37.0, "MEDIUM": 25.0}


def test_a_stint_beyond_the_evidence_is_refused() -> None:
    strategy = strategy_from_stints("one stop", [("HARD", 40), ("HARD", 30)])
    with pytest.raises(ValueError, match="beyond the oldest tyre observed"):
        check_within_evidence(strategy, {"HARD": 37.0})


def test_a_compound_the_model_never_saw_is_refused() -> None:
    strategy = strategy_from_stints("soft run", [("SOFT", 10)])
    with pytest.raises(ValueError, match="no data for compound"):
        check_within_evidence(strategy, {"HARD": 37.0})


def test_a_strategy_inside_the_evidence_passes() -> None:
    strategy = strategy_from_stints("one stop", [("MEDIUM", 31), ("HARD", 39)])
    check_within_evidence(strategy, {"HARD": 55.0, "MEDIUM": 40.0})


def build_race_with_stops(penalty_in: float, penalty_out: float) -> pd.DataFrame:
    """Build one driver's race whose lap times match a zero degradation model.

    With no degradation and no compound offset, a fresh tyre and a one lap older
    tyre predict the same time, so the measured pit loss is exactly the penalty
    added to the in and out laps.
    """
    rows = []
    for lap in range(1, 41):
        stint, age = (1, lap) if lap <= 20 else (2, lap - 20)
        penalty = 0.0
        if lap == 20:
            penalty = penalty_in
        elif lap == 21:
            penalty = penalty_out
        rows.append(
            {
                "race_id": "2023 Race",
                "Driver": "VER",
                "Stint": float(stint),
                "Compound": "HARD",
                "LapNumber": float(lap),
                "TyreLife": float(age),
                "lap_time_s": 80.0 + 0.045 * (40 - lap) + penalty,
                "PitInTime": pd.Timedelta(seconds=1) if lap == 20 else pd.NaT,
                "PitOutTime": pd.Timedelta(seconds=1) if lap == 21 else pd.NaT,
            }
        )
    return pd.DataFrame(rows)


def test_pit_loss_is_measured_from_the_in_and_out_laps() -> None:
    laps = build_race_with_stops(penalty_in=2.5, penalty_out=18.0)
    estimate = make_estimate({"HARD": 0.0}, {"HARD": 0.0})
    assert measure_pit_loss(laps, estimate) == pytest.approx(20.5)


def test_pit_loss_needs_a_completed_stop() -> None:
    laps = build_race_with_stops(2.5, 18.0)
    estimate = make_estimate({"HARD": 0.0}, {"HARD": 0.0})
    no_stops = laps.assign(PitInTime=pd.NaT)
    with pytest.raises(ValueError, match="no completed pit stops"):
        measure_pit_loss(no_stops, estimate)


def test_pit_loss_needs_its_columns() -> None:
    estimate = make_estimate({"HARD": 0.0}, {"HARD": 0.0})
    with pytest.raises(KeyError, match="TyreLife"):
        measure_pit_loss(pd.DataFrame({"race_id": ["x"], "Driver": ["VER"]}), estimate)


def test_cumulative_cost_ends_where_the_total_does() -> None:
    estimate = make_estimate({"MEDIUM": 0.05, "HARD": 0.07},
                             {"MEDIUM": -0.3, "HARD": 0.0})
    strategy = strategy_from_stints("two stop", [("MEDIUM", 18), ("HARD", 27),
                                                 ("HARD", 25)])
    running = cumulative_cost(strategy, estimate, PIT_LOSS)
    assert len(running) == strategy.race_laps
    assert running.index[0] == 1
    assert running.iloc[-1] == pytest.approx(
        strategy_cost(strategy, estimate, PIT_LOSS)
    )


def test_cumulative_cost_steps_up_at_each_pit_stop() -> None:
    estimate = make_estimate({"HARD": 0.0}, {"HARD": 0.0})
    strategy = strategy_from_stints("one stop", [("HARD", 5), ("HARD", 5)])
    running = cumulative_cost(strategy, estimate, PIT_LOSS)
    # With no degradation the only cost is the stop, charged on lap 6.
    assert running.loc[5] == pytest.approx(0.0)
    assert running.loc[6] == pytest.approx(PIT_LOSS)


def test_cumulative_cost_climbs_faster_on_an_older_tyre() -> None:
    estimate = make_estimate({"HARD": 0.07}, {"HARD": 0.0})
    running = cumulative_cost(
        strategy_from_stints("no stop", [("HARD", 30)]), estimate, PIT_LOSS
    )
    early = running.loc[2] - running.loc[1]
    late = running.loc[30] - running.loc[29]
    assert late > early
