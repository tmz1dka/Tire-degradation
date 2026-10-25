"""Judge the 2025 one stop against the two stop, using a model that never saw it.

The model is fitted on 2023 and 2024 only. The 2025 race supplies two things it
could not have known: which strategies were actually run, and how the race
finished. Nothing from 2025 reaches the fit.

Usage:
    python scripts/strategy_test.py
    python scripts/strategy_test.py --resamples 2000
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from tyre_deg.cleaning import clean_laps
from tyre_deg.config import PILOT_CIRCUIT, TEST_SEASON, TRAIN_SEASONS
from tyre_deg.loading import load_race, race_laps
from tyre_deg.model import BootstrapResult, bootstrap_degradation, derived_interval
from tyre_deg.strategy import (
    Stint,
    Strategy,
    check_within_evidence,
    compare_strategies,
    max_observed_tyre_age,
    measure_pit_loss,
)

logger = logging.getLogger(__name__)

ONE_STOP_DRIVER = "NOR"
TWO_STOP_DRIVER = "PIA"


def strategy_run_by(laps: pd.DataFrame, driver: str, name: str) -> Strategy:
    """Read the strategy a driver actually ran, from their stints.

    Args:
        laps: Every lap of the race, including pit laps.
        driver: Driver abbreviation.
        name: Label for reporting.

    Returns:
        The strategy as run.

    Raises:
        ValueError: If the driver has no laps in this race.
    """
    driver_laps = laps[laps["Driver"] == driver]
    if driver_laps.empty:
        raise ValueError(f"no laps found for {driver}")
    stints = (
        driver_laps.groupby("Stint")
        .agg(compound=("Compound", "first"), laps=("LapNumber", "size"))
        .sort_index()
    )
    return Strategy(
        name=name,
        stints=tuple(
            Stint(str(row.compound), int(row.laps)) for row in stints.itertuples()
        ),
    )


def describe(strategy: Strategy) -> str:
    """Render a strategy as a readable line."""
    stints = ", ".join(
        f"{stint.compound.lower()} {stint.laps}" for stint in strategy.stints
    )
    return f"{strategy.name:<9} {strategy.stops} stop: {stints}"


def report(
    one_stop: Strategy,
    two_stop: Strategy,
    result: BootstrapResult,
    pit_loss: float,
    actual_gap: float,
) -> None:
    """Print the comparison and set it against what actually happened.

    Args:
        one_stop: The one stop strategy as run.
        two_stop: The two stop strategy as run.
        result: Fitted coefficients with their resampled fits.
        pit_loss: Measured seconds lost per pit stop.
        actual_gap: The real finishing gap between the two drivers.
    """
    delta = derived_interval(
        result,
        lambda fit: compare_strategies(one_stop, two_stop, fit, pit_loss),
    )
    print(f"\n  {describe(one_stop)}")
    print(f"  {describe(two_stop)}")
    print(f"\n  pit loss measured from the training races: {pit_loss:.2f} s")
    print(f"\n  model says the two stop cost {delta.point:+.2f} s "
          f"[{delta.low:+.2f}, {delta.high:+.2f}] against the one stop")
    print(f"  actual finishing gap                   {actual_gap:+.3f} s")
    verdict = (
        "the model picks the one stop"
        if delta.point > 0
        else "the model picks the two stop"
    )
    print(f"\n  {verdict}; the race was won on the one stop")
    print("\n  these are not the same quantity. the model estimates a free air")
    print("  difference, while the finishing gap also carries track position:")
    print("  the two stop finished in dirty air at a circuit where passing is")
    print("  rare, so it could not use whatever pace it had left.")
    report_pit_loss_sensitivity(one_stop, two_stop, result, pit_loss)


def report_pit_loss_sensitivity(
    one_stop: Strategy,
    two_stop: Strategy,
    result: BootstrapResult,
    pit_loss: float,
) -> None:
    """Show how much the answer moves if the pit loss is wrong.

    The pit loss is one measured number whose own uncertainty is not carried
    through the interval, so its effect is shown separately.

    Args:
        one_stop: The one stop strategy as run.
        two_stop: The two stop strategy as run.
        result: Fitted coefficients with their resampled fits.
        pit_loss: Measured seconds lost per pit stop.
    """
    for offset in (-2.0, 2.0):
        shifted = derived_interval(
            result,
            lambda fit, o=offset: compare_strategies(
                one_stop, two_stop, fit, pit_loss + o
            ),
        )
        print(
            f"  pit loss {pit_loss + offset:5.2f} s would give "
            f"{shifted.point:+.2f} s"
        )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resamples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    """Fit on the training races, then judge the held out one."""
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    args = parse_args()
    training_raw = [race_laps(load_race(year, PILOT_CIRCUIT)) for year in TRAIN_SEASONS]
    training = pd.concat([clean_laps(laps).laps for laps in training_raw],
                         ignore_index=True)
    result = bootstrap_degradation(training, resamples=args.resamples, seed=args.seed)
    pit_loss = measure_pit_loss(pd.concat(training_raw, ignore_index=True),
                                result.estimate)

    test_session = load_race(TEST_SEASON, PILOT_CIRCUIT)
    test_laps = race_laps(test_session)
    one_stop = strategy_run_by(test_laps, ONE_STOP_DRIVER, "one stop")
    two_stop = strategy_run_by(test_laps, TWO_STOP_DRIVER, "two stop")
    oldest = max_observed_tyre_age(training)
    for strategy in (one_stop, two_stop):
        check_within_evidence(strategy, oldest)

    results = test_session.results.set_index("Abbreviation")
    actual_gap = results.loc[TWO_STOP_DRIVER, "Time"].total_seconds()
    print(f"\nfitted on {', '.join(str(year) for year in TRAIN_SEASONS)}, "
          f"{result.estimate.laps} clean laps")
    print(f"judged on {TEST_SEASON}, never seen during fitting")
    report(one_stop, two_stop, result, pit_loss, actual_gap)


if __name__ == "__main__":
    main()
