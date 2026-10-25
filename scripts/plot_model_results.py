"""Chart what the model estimates and what it says about the 2025 strategies.

Two panels. The left shows each fitted coefficient with the interval from
resampling whole stints, and marks the physical estimate of the fuel effect that
the model was never given. The right follows the two strategies through the
race, showing where the extra pit stop costs time and where fresher tyres win it
back.

Writes figures/model_results.png.

Usage:
    python scripts/plot_model_results.py
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from tyre_deg.cleaning import clean_laps  # noqa: E402
from tyre_deg.config import PILOT_CIRCUIT, TEST_SEASON, TRAIN_SEASONS  # noqa: E402
from tyre_deg.fuel import physical_fuel_effect  # noqa: E402
from tyre_deg.loading import load_race, race_lap_count, race_laps  # noqa: E402
from tyre_deg.model import (  # noqa: E402
    BootstrapResult,
    DegradationEstimate,
    bootstrap_degradation,
)
from tyre_deg.strategy import (  # noqa: E402
    Stint,
    Strategy,
    cumulative_cost,
    measure_pit_loss,
)

logger = logging.getLogger(__name__)

COLORS = {
    "fuel": "#444444",
    "MEDIUM": "#E69F00",
    "HARD": "#0072B2",
    "difference": "#333333",
    "actual": "#D55E00",
}


def draw_coefficients(axis: plt.Axes, result: BootstrapResult, physical: float) -> None:
    """Draw each fitted coefficient with its interval.

    Args:
        axis: Axis to draw on.
        result: Fitted coefficients with intervals.
        physical: Physical estimate of the fuel effect, for comparison.
    """
    rows = [
        ("fuel, per lap of fuel left", result.fuel, COLORS["fuel"]),
        ("medium, per lap of tyre age", result.degradation["MEDIUM"],
         COLORS["MEDIUM"]),
        ("hard, per lap of tyre age", result.degradation["HARD"], COLORS["HARD"]),
    ]
    for position, (label, interval, color) in enumerate(reversed(rows)):
        axis.plot([interval.low, interval.high], [position, position],
                  color=color, linewidth=2.4, solid_capstyle="round", zorder=2)
        axis.plot([interval.point], [position], "o", color=color, markersize=7,
                  zorder=3)
        axis.text(interval.high + 0.003, position + 0.17,
                  f"{interval.point:.4f}", fontsize=9, color=color, va="center")
        axis.text(-0.004, position, label, fontsize=9.5, ha="right", va="center")
    axis.plot([physical], [2.32], marker="*", markersize=14, color="#009E73",
              zorder=4, linestyle="none",
              label=f"physics says {physical:.4f}, never given to the model")
    axis.annotate(
        "", xy=(physical, 2.06), xytext=(physical, 2.24),
        arrowprops={"arrowstyle": "-", "color": "#009E73", "linewidth": 1.2},
    )
    axis.text(
        0.0455, 0.52,
        "these two overlap:\nthe data cannot\nseparate the compounds",
        fontsize=8.5, color="#666666", va="center", linespacing=1.4,
    )
    axis.set_xlim(-0.004, 0.115)
    axis.set_ylim(-0.6, 2.6)
    axis.set_yticks([])
    axis.set_xlabel("seconds per lap")
    axis.set_title("What the model estimates", fontsize=11, pad=8)
    axis.legend(loc="lower right", fontsize=8.5, framealpha=0.95)
    axis.grid(axis="x", alpha=0.25, linewidth=0.6)
    for side in ("top", "right", "left"):
        axis.spines[side].set_visible(False)


def difference_band(
    result: BootstrapResult,
    one_stop: Strategy,
    two_stop: Strategy,
    pit_loss: float,
) -> tuple[pd.Series, np.ndarray, np.ndarray]:
    """Return the running time difference and its interval, lap by lap.

    Args:
        result: Fitted coefficients with every resampled fit.
        one_stop: The one stop strategy.
        two_stop: The two stop strategy.
        pit_loss: Seconds lost per pit stop.

    Returns:
        The difference per lap, and the low and high edges of the band.
    """
    def running(fit: DegradationEstimate) -> np.ndarray:
        two = cumulative_cost(two_stop, fit, pit_loss).to_numpy()
        one = cumulative_cost(one_stop, fit, pit_loss).to_numpy()
        return two - one

    point = pd.Series(running(result.estimate), index=range(1, one_stop.race_laps + 1))
    draws = np.vstack([running(draw) for draw in result.draws])
    tail = (1.0 - result.confidence) / 2.0
    low, high = np.percentile(draws, [100 * tail, 100 * (1 - tail)], axis=0)
    return point, low, high


def draw_strategies(
    axis: plt.Axes,
    point: pd.Series,
    low: np.ndarray,
    high: np.ndarray,
    actual_gap: float,
) -> None:
    """Draw the running difference between the two strategies.

    Args:
        axis: Axis to draw on.
        point: Difference per lap, two stop minus one stop.
        low: Lower edge of the interval.
        high: Upper edge of the interval.
        actual_gap: The real finishing gap between the two drivers.
    """
    laps = point.index.to_numpy()
    axis.axhline(0, color="#999999", linewidth=1.0, zorder=1)
    axis.fill_between(laps, low, high, color=COLORS["difference"], alpha=0.15,
                      linewidth=0, zorder=2)
    axis.plot(laps, point.to_numpy(), color=COLORS["difference"], linewidth=2.0,
              zorder=3, label="model: two stop minus one stop")
    axis.plot([laps[-1]], [actual_gap], marker="D", markersize=7,
              color=COLORS["actual"], linestyle="none", zorder=4,
              label=f"actual finish: {actual_gap:+.2f} s")
    axis.annotate(f"{point.iloc[-1]:+.1f} s", xy=(laps[-1], point.iloc[-1]),
                  xytext=(-6, -14), textcoords="offset points", fontsize=9.5,
                  color=COLORS["difference"], ha="right")
    axis.set_xlabel("race lap")
    axis.set_ylabel("seconds, two stop relative to one stop")
    axis.set_title("What it says about the 2025 race", fontsize=11, pad=8)
    axis.legend(loc="lower left", fontsize=8.5, framealpha=0.95)
    axis.grid(alpha=0.25, linewidth=0.6)


def strategy_run_by(laps: pd.DataFrame, driver: str, name: str) -> Strategy:
    """Read the strategy a driver actually ran, from their stints.

    Args:
        laps: Every lap of the race, including pit laps.
        driver: Driver abbreviation.
        name: Label for reporting.

    Returns:
        The strategy as run.
    """
    stints = (
        laps[laps["Driver"] == driver]
        .groupby("Stint")
        .agg(compound=("Compound", "first"), laps=("LapNumber", "size"))
        .sort_index()
    )
    return Strategy(
        name=name,
        stints=tuple(
            Stint(str(row.compound), int(row.laps)) for row in stints.itertuples()
        ),
    )


def caption(result: BootstrapResult, pit_loss: float) -> str:
    """Return the footnote explaining what the chart does and does not show."""
    seasons = " and ".join(str(year) for year in TRAIN_SEASONS)
    return (
        f"Fitted on {seasons}, {result.estimate.laps} clean laps, one baseline "
        f"per driver per race. {result.confidence:.0%} intervals from "
        f"{result.resamples} resamples of whole stints, not single laps.\n"
        f"Pit loss of {pit_loss:.2f} s measured from the training races. The "
        f"model estimates a difference in clear air; the actual gap also "
        f"carries track position, which it cannot see.\n"
        f"Regenerate with scripts/plot_model_results.py"
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resamples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--output", type=Path, default=Path("figures/model_results.png")
    )
    return parser.parse_args()


def main() -> None:
    """Build the chart and write it to disk."""
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    args = parse_args()
    raw = [race_laps(load_race(year, PILOT_CIRCUIT)) for year in TRAIN_SEASONS]
    training = pd.concat([clean_laps(laps).laps for laps in raw], ignore_index=True)
    result = bootstrap_degradation(training, resamples=args.resamples, seed=args.seed)
    pit_loss = measure_pit_loss(pd.concat(raw, ignore_index=True), result.estimate)
    physical = physical_fuel_effect(race_lap_count(raw[0]))

    test_session = load_race(TEST_SEASON, PILOT_CIRCUIT)
    test_laps = race_laps(test_session)
    one_stop = strategy_run_by(test_laps, "NOR", "one stop")
    two_stop = strategy_run_by(test_laps, "PIA", "two stop")
    actual_gap = (
        test_session.results.set_index("Abbreviation").loc["PIA", "Time"]
    ).total_seconds()

    figure, axes = plt.subplots(1, 2, figsize=(12.0, 5.0), dpi=150)
    draw_coefficients(axes[0], result, physical)
    draw_strategies(axes[1], *difference_band(result, one_stop, two_stop, pit_loss),
                    actual_gap)
    figure.suptitle(
        f"Tyre degradation at the Hungaroring, and what it implies for the "
        f"{TEST_SEASON} race",
        fontsize=13, y=0.975,
    )
    figure.text(0.5, 0.012, caption(result, pit_loss), fontsize=7.8,
                color="#555555", ha="center", va="bottom", linespacing=1.6)
    figure.subplots_adjust(top=0.86, bottom=0.23, left=0.195, right=0.975,
                           wspace=0.28)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
