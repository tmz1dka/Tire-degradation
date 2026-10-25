"""Tests for the parts of loading that do not touch the network or the cache."""

from __future__ import annotations

import pandas as pd
import pytest

from tyre_deg.loading import race_lap_count


def test_race_lap_count_is_the_highest_lap_number() -> None:
    laps = pd.DataFrame({"LapNumber": [1.0, 2.0, 70.0, 69.0]})
    assert race_lap_count(laps) == 70


def test_race_lap_count_of_an_empty_race_is_zero() -> None:
    assert race_lap_count(pd.DataFrame({"LapNumber": []})) == 0


def test_race_lap_count_needs_the_lap_number_column() -> None:
    with pytest.raises(KeyError, match="LapNumber"):
        race_lap_count(pd.DataFrame({"Driver": ["VER"]}))
