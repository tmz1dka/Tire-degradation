"""Tests for lap cleaning.

Every frame here is built in the test, so the suite needs no network access and
no cached session data. There is no randomness to seed.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from tyre_deg.cleaning import (
    GAP_AHEAD_COLUMN,
    add_gap_to_car_ahead,
    clean_lap_counts_by_compound,
    clean_laps,
    is_clear_of_traffic,
    is_flagged_accurate,
    is_green_flag,
    is_not_first_lap,
    is_not_pit_lap,
    is_timed,
)

DEFAULT_LAP: dict[str, Any] = {
    "LapNumber": 5.0,
    "Driver": "VER",
    "Stint": 1.0,
    "Compound": "HARD",
    "TyreLife": 10.0,
    "lap_time_s": 80.0,
    "session_time_s": 400.0,
    "TrackStatus": "1",
    "PitInTime": pd.NaT,
    "PitOutTime": pd.NaT,
    "IsAccurate": True,
}


def make_laps(*overrides: dict[str, Any]) -> pd.DataFrame:
    """Build a lap frame, one row per override mapping."""
    rows = [{**DEFAULT_LAP, **override} for override in overrides]
    return pd.DataFrame(rows)


def test_a_lap_with_no_time_is_dropped() -> None:
    laps = make_laps({"lap_time_s": 80.0}, {"lap_time_s": None})
    assert is_timed(laps).tolist() == [True, False]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("1", True),
        ("12", True),
        ("21", True),
        ("4", False),
        ("671", False),
        ("2671", False),
        ("5", False),
        ("", True),
    ],
)
def test_green_flag_tests_digits_not_equality(status: str, expected: bool) -> None:
    assert is_green_flag(make_laps({"TrackStatus": status})).tolist() == [expected]


def test_missing_track_status_counts_as_green() -> None:
    assert is_green_flag(make_laps({"TrackStatus": None})).tolist() == [True]


def test_pit_in_and_out_laps_are_dropped() -> None:
    laps = make_laps(
        {},
        {"PitInTime": pd.Timedelta(seconds=1)},
        {"PitOutTime": pd.Timedelta(seconds=1)},
    )
    assert is_not_pit_lap(laps).tolist() == [True, False, False]


def test_first_lap_is_dropped() -> None:
    laps = make_laps({"LapNumber": 1.0}, {"LapNumber": 2.0})
    assert is_not_first_lap(laps).tolist() == [False, True]


def test_inaccurate_and_unknown_laps_are_dropped() -> None:
    laps = make_laps({"IsAccurate": True}, {"IsAccurate": False}, {"IsAccurate": None})
    assert is_flagged_accurate(laps).tolist() == [True, False, False]


def test_gap_is_measured_against_the_car_ahead_on_the_same_lap() -> None:
    laps = make_laps(
        {"LapNumber": 2.0, "Driver": "VER", "session_time_s": 100.0},
        {"LapNumber": 2.0, "Driver": "PER", "session_time_s": 102.5},
        {"LapNumber": 3.0, "Driver": "VER", "session_time_s": 180.0},
    )
    gaps = add_gap_to_car_ahead(laps)[GAP_AHEAD_COLUMN]
    assert gaps.isna().tolist() == [True, False, True]
    assert gaps.iloc[1] == pytest.approx(2.5)


def test_gap_keeps_the_input_row_order() -> None:
    laps = make_laps(
        {"LapNumber": 2.0, "Driver": "PER", "session_time_s": 102.5},
        {"LapNumber": 2.0, "Driver": "VER", "session_time_s": 100.0},
    )
    result = add_gap_to_car_ahead(laps)
    assert result["Driver"].tolist() == ["PER", "VER"]
    assert result[GAP_AHEAD_COLUMN].iloc[0] == pytest.approx(2.5)
    assert pd.isna(result[GAP_AHEAD_COLUMN].iloc[1])


def test_gap_needs_its_input_columns() -> None:
    with pytest.raises(KeyError, match="session_time_s"):
        add_gap_to_car_ahead(pd.DataFrame({"LapNumber": [1.0]}))


@pytest.mark.parametrize(
    ("gap", "expected"),
    [(0.5, False), (0.999, False), (1.0, True), (3.0, True), (None, True)],
)
def test_traffic_threshold_is_inclusive_and_leader_counts_as_clear(
    gap: float | None,
    expected: bool,
) -> None:
    laps = make_laps({GAP_AHEAD_COLUMN: gap})
    assert is_clear_of_traffic(laps, 1.0).tolist() == [expected]


def test_traffic_filter_rejects_a_negative_threshold() -> None:
    laps = make_laps({GAP_AHEAD_COLUMN: 2.0})
    with pytest.raises(ValueError, match="must not be negative"):
        is_clear_of_traffic(laps, -1.0)


def test_traffic_filter_needs_the_gap_column() -> None:
    with pytest.raises(KeyError, match=GAP_AHEAD_COLUMN):
        is_clear_of_traffic(make_laps({}))


def test_clean_laps_reports_each_step_in_order() -> None:
    laps = make_laps(
        {"LapNumber": 1.0, "session_time_s": 90.0},
        {"lap_time_s": None, "session_time_s": 200.0},
        {"TrackStatus": "4", "session_time_s": 300.0},
        {"PitInTime": pd.Timedelta(seconds=1), "session_time_s": 400.0},
        {"IsAccurate": False, "session_time_s": 500.0},
        {"session_time_s": 600.0},
    )
    cleaned = clean_laps(laps)
    assert [step.name for step in cleaned.steps] == [
        "has a lap time",
        "green flag only",
        "no pit in or out lap",
        "after lap 1",
        "timed accurately",
        "clear of traffic by 1s",
    ]
    assert [step.dropped for step in cleaned.steps] == [1, 1, 1, 1, 1, 0]
    assert cleaned.steps[-1].remaining == len(cleaned.laps) == 1
    assert cleaned.input_laps == 6
    assert cleaned.retained_fraction == pytest.approx(1 / 6)


def test_clean_laps_drops_only_the_retired_drivers_missing_lap() -> None:
    laps = make_laps(
        {"Driver": "OCO", "LapNumber": 20.0, "session_time_s": 1600.0},
        {"Driver": "OCO", "LapNumber": 21.0, "lap_time_s": None,
         "session_time_s": 1680.0},
        {"Driver": "VER", "LapNumber": 21.0, "session_time_s": 1700.0},
    )
    cleaned = clean_laps(laps)
    assert len(cleaned.laps) == 2
    assert cleaned.laps["LapNumber"].tolist() == [20.0, 21.0]


def test_clean_laps_removes_a_whole_safety_car_period() -> None:
    laps = make_laps(
        *[
            {"LapNumber": float(lap), "session_time_s": 80.0 * lap,
             "TrackStatus": "41" if lap in (30, 31, 32) else "1"}
            for lap in range(28, 35)
        ]
    )
    cleaned = clean_laps(laps)
    assert cleaned.laps["LapNumber"].tolist() == [28.0, 29.0, 33.0, 34.0]


def test_clean_laps_handles_an_empty_frame() -> None:
    empty = make_laps().reindex(columns=list(DEFAULT_LAP))
    cleaned = clean_laps(empty)
    assert cleaned.laps.empty
    assert cleaned.input_laps == 0
    assert cleaned.retained_fraction == 0.0


def test_clean_laps_does_not_modify_its_input() -> None:
    laps = make_laps({"session_time_s": 100.0}, {"lap_time_s": None})
    before = laps.copy(deep=True)
    clean_laps(laps)
    pd.testing.assert_frame_equal(laps, before)
    assert GAP_AHEAD_COLUMN not in laps.columns


def test_compound_counts_rank_the_best_covered_compound_first() -> None:
    laps = make_laps(
        {"Compound": "HARD", "session_time_s": 100.0},
        {"Compound": "HARD", "session_time_s": 200.0},
        {"Compound": "MEDIUM", "session_time_s": 300.0},
        {"Compound": "SOFT", "lap_time_s": None, "session_time_s": 400.0},
    )
    counts = clean_lap_counts_by_compound(clean_laps(laps))
    assert counts.to_dict() == {"HARD": 2, "MEDIUM": 1}
    assert "SOFT" not in counts.index


def test_compound_counts_of_nothing_is_empty() -> None:
    empty = make_laps().reindex(columns=list(DEFAULT_LAP))
    assert clean_lap_counts_by_compound(clean_laps(empty)).empty
