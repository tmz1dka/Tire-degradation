"""Tests for the MCP server's data layer.

Most tests build a tiny results file in the test, with coefficients chosen so
the strategy arithmetic can be checked by hand. The last few read the committed
results file, which is in the repository precisely so the server works without
a FastF1 cache, and guard the numbers published in the README.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mcp_server.data import (
    DEFAULT_OUTPUT_PATH,
    ModelOutputs,
    UnknownValue,
    compare_stints,
    compare_strategies,
    get_degradation,
    list_races,
    percentile,
)

# One stint of 10 laps on a 0.10 s/lap tyre costs 0.10 x (1+..+10) = 5.50 s.
# Splitting it into two 5-lap stints costs 2 x 0.10 x 15 = 3.00 s of wear plus
# one 20 s stop, so the second strategy is 17.50 s worse.
HAND_WORKED_DELTA = 17.50


def build_race() -> dict[str, Any]:
    """Build the single race the small results object contains."""
    return {
            "race_id": "2023 Test Grand Prix",
            "season": 2023,
            "role": "training",
            "total_laps": 10,
            "clean_laps": 100,
            "laps_fitted": 95,
            "drivers": ["AAA", "BBB", "CCC"],
            "compounds": [
                {"compound": "HARD", "clean_laps": 60, "stints": 4,
                 "degradation_s_per_lap": {"estimate": 0.10, "low": 0.08,
                                           "high": 0.12}},
                {"compound": "SOFT", "clean_laps": 5, "stints": 1,
                 "degradation_s_per_lap": None,
                 "no_estimate_because": "only 5 clean racing laps"},
            ],
            "fuel_s_per_lap": {"estimate": 0.04, "low": 0.03, "high": 0.05},
            "stints": [
                {"driver": "AAA", "stint": 1, "compound": "HARD",
                 "laps": 10, "clean_laps": 9, "trend_s_per_lap": 0.1},
                {"driver": "BBB", "stint": 1, "compound": "HARD",
                 "laps": 5, "clean_laps": 4, "trend_s_per_lap": None},
                {"driver": "BBB", "stint": 2, "compound": "HARD",
                 "laps": 5, "clean_laps": 5, "trend_s_per_lap": -0.2},
                {"driver": "CCC", "stint": 1, "compound": "SOFT",
                 "laps": 10, "clean_laps": 5, "trend_s_per_lap": None},
            ],
        }


def build_outputs(draws: list[float] | None = None) -> ModelOutputs:
    """Build a small results object with hand-chosen coefficients."""
    spread = draws if draws is not None else [0.10, 0.10, 0.10]
    return ModelOutputs(
        settings={
            "circuit": "Testland",
            "resamples": len(spread),
            "min_laps_for_stint_trend": 8,
            "min_laps_for_slope": 40,
        },
        pooled={
            "fitted_on": ["2023 Test Grand Prix"],
            "pit_loss_s": 20.0,
            "degradation_s_per_lap": {
                "HARD": {"estimate": 0.10, "low": 0.08, "high": 0.12},
                "MEDIUM": {"estimate": 0.05, "low": 0.04, "high": 0.06},
            },
            "compound_offset_s": {"HARD": 0.0, "MEDIUM": 0.0},
            "draws": [
                {"degradation": {"HARD": rate, "MEDIUM": 0.05},
                 "offset": {"HARD": 0.0, "MEDIUM": 0.0}}
                for rate in spread
            ],
        },
        races=(build_race(),),
    )


@pytest.fixture
def outputs() -> ModelOutputs:
    """A small results object whose arithmetic is checkable by hand."""
    return build_outputs()


def test_percentile_interpolates_between_neighbours() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.0) == pytest.approx(1.0)
    assert percentile([1.0, 2.0, 3.0, 4.0], 1.0) == pytest.approx(4.0)


def test_percentile_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="empty sample"):
        percentile([], 0.5)
    with pytest.raises(ValueError, match="between 0 and 1"):
        percentile([1.0], 1.5)


def test_a_missing_results_file_says_how_to_build_it(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="mcp_server.precompute"):
        ModelOutputs.from_file(tmp_path / "absent.json")


def test_a_results_file_from_another_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"schema_version": 99, "settings": {},
                                "pooled_model": {}, "races": []}))
    with pytest.raises(ValueError, match="schema version 99"):
        ModelOutputs.from_file(path)


def test_a_race_can_be_found_by_name_or_season(outputs: ModelOutputs) -> None:
    by_name = outputs.race("2023 test grand prix")
    by_season = outputs.race("2023")
    assert by_name["race_id"] == by_season["race_id"] == "2023 Test Grand Prix"


def test_an_unknown_race_lists_the_real_ones(outputs: ModelOutputs) -> None:
    with pytest.raises(UnknownValue, match="2023 Test Grand Prix"):
        outputs.race("1998 Monaco Grand Prix")


def test_list_races_reports_roles_and_drivers(outputs: ModelOutputs) -> None:
    listed = list_races(outputs)
    assert [r["race"] for r in listed["races"]] == ["2023 Test Grand Prix"]
    assert listed["races"][0]["role"] == "training"
    assert listed["races"][0]["drivers"] == ["AAA", "BBB", "CCC"]


def test_degradation_comes_back_with_its_interval(outputs: ModelOutputs) -> None:
    result = get_degradation(outputs, "hard", "2023")
    assert result["degradation_s_per_lap"] == pytest.approx(0.10)
    assert result["confidence_interval_95"] == [0.08, 0.12]
    assert result["clean_racing_laps"] == 60
    assert "whole stints" in result["interval_from"]


def test_a_compound_with_too_little_data_explains_itself(
    outputs: ModelOutputs,
) -> None:
    result = get_degradation(outputs, "SOFT", "2023")
    assert result["degradation_s_per_lap"] is None
    assert "only 5 clean racing laps" in result["no_estimate_because"]
    assert "confidence_interval_95" not in result


def test_an_unknown_compound_lists_the_real_ones(outputs: ModelOutputs) -> None:
    with pytest.raises(UnknownValue, match="HARD, SOFT"):
        get_degradation(outputs, "ultrasoft", "2023")


def test_an_unknown_driver_lists_the_real_ones(outputs: ModelOutputs) -> None:
    with pytest.raises(UnknownValue, match="AAA, BBB, CCC"):
        compare_stints(outputs, "AAA", "ZZZ", "2023")


def test_compare_stints_returns_both_drivers_with_a_caveat(
    outputs: ModelOutputs,
) -> None:
    result = compare_stints(outputs, "aaa", "BBB", "2023")
    assert set(result["drivers"]) == {"AAA", "BBB"}
    assert [s["stint"] for s in result["drivers"]["BBB"]] == [1, 2]
    # The caveat has to warn about exactly the trap in this fixture: a negative
    # single-stint trend that does not mean the tyre improved.
    assert "does not mean the tyre got faster" in result["trend_caveat"]
    assert result["drivers"]["BBB"][1]["trend_s_per_lap"] == -0.2


def test_strategy_difference_matches_the_hand_worked_figure(
    outputs: ModelOutputs,
) -> None:
    result = compare_strategies(outputs, "2023", "AAA", "BBB")
    assert result["difference_s"] == pytest.approx(HAND_WORKED_DELTA)
    assert result["quicker_on_pace"] == "AAA"
    assert result["strategies"]["AAA"]["stops"] == 0
    assert result["strategies"]["BBB"]["stops"] == 1
    assert result["pit_loss_s_used"] == pytest.approx(20.0)


def test_the_strategy_interval_comes_from_the_draws() -> None:
    # Spread the per-draw hard degradation, so the delta spreads with it.
    spread = build_outputs(draws=[0.05, 0.10, 0.15])
    result = compare_strategies(spread, "2023", "AAA", "BBB")
    low, high = result["confidence_interval_95"]
    assert low < result["difference_s"] < high


def test_a_strategy_on_an_unmodelled_compound_is_refused(
    outputs: ModelOutputs,
) -> None:
    with pytest.raises(UnknownValue, match="soft"):
        compare_strategies(outputs, "2023", "AAA", "CCC")


def test_the_comparison_says_it_ignores_track_position(
    outputs: ModelOutputs,
) -> None:
    result = compare_strategies(outputs, "2023", "AAA", "BBB")
    assert "track position" in result["what_this_is"]


@pytest.mark.skipif(
    not DEFAULT_OUTPUT_PATH.exists(), reason="precomputed results not built"
)
def test_the_committed_results_still_hold_the_published_numbers() -> None:
    real = ModelOutputs.from_file()
    assert len(real.races) == 3
    assert [r["role"] for r in real.races] == ["training", "training", "held out"]
    # The figures the README and docs/decisions.md quote.
    assert real.pooled["laps_fitted"] == 2029
    assert real.pooled["pit_loss_s"] == pytest.approx(19.60, abs=0.01)
    hard = real.pooled["degradation_s_per_lap"]["HARD"]
    assert hard["estimate"] == pytest.approx(0.0784, abs=1e-4)
    held_out = compare_strategies(real, "2025", "NOR", "PIA")
    assert held_out["difference_s"] == pytest.approx(-9.0, abs=0.05)
    assert held_out["confidence_interval_95"] == [pytest.approx(-13.3, abs=0.05),
                                                  pytest.approx(-4.77, abs=0.05)]
