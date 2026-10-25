"""Chart tyre degradation before and after the fuel correction.

Two panels of lap time against tyre age for the pilot race: raw on the left,
fuel corrected on the right. Without the correction the medium tyre's trend
points downwards, which would mean the tyre gets faster the longer it is used.

Both panels use the same y-axis span, so a slope in one is directly comparable
to a slope in the other. Different spans would make the correction look larger
or smaller than it is.

The slopes drawn here pool every driver with no control for pace, so they
diagnose the problem rather than estimate degradation. See decision 7.

Writes figures/fuel_correction.png.

Usage:
    python scripts/plot_fuel_correction.py
    python scripts/plot_fuel_correction.py --season 2024 --output figures/x.png
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
from tyre_deg.config import (  # noqa: E402
    MODELLED_COMPOUNDS,
    PILOT_CIRCUIT,
    PILOT_SEASON,
)
from tyre_deg.diagnostics import (  # noqa: E402
    LineFit,
    median_lap_time_by_tyre_age,
    uncontrolled_line,
)
from tyre_deg.fuel import fuel_corrected_lap_time, physical_fuel_effect  # noqa: E402
from tyre_deg.loading import load_race, race_lap_count, race_laps  # noqa: E402

logger = logging.getLogger(__name__)

RAW_COLUMN = "lap_time_s"
CORRECTED_COLUMN = "corrected_lap_time_s"

# Okabe and Ito colors, chosen to stay distinguishable for colorblind readers.
# Pirelli's own yellow and white would be unreadable on a pale background.
COMPOUND_COLORS = {"MEDIUM": "#E69F00", "HARD": "#0072B2"}

PANELS = (
    (RAW_COLUMN, "Raw lap time"),
    (CORRECTED_COLUMN, "After the fuel correction"),
)


def axis_span(laps: pd.DataFrame, columns: tuple[str, ...]) -> float:
    """Return a y-axis height covering the middle 98% of every panel's laps.

    Args:
        laps: Lap frame holding each panel's time column.
        columns: Time columns that will be plotted.

    Returns:
        The largest span in seconds needed by any single panel.
    """
    spans = []
    for column in columns:
        low, high = laps[column].quantile([0.01, 0.99])
        spans.append(float(high - low))
    return max(spans)


def draw_panel(
    axis: plt.Axes,
    laps: pd.DataFrame,
    column: str,
    title: str,
    span: float,
) -> dict[str, LineFit]:
    """Draw one panel and return the fitted line per compound.

    Args:
        axis: Axis to draw on.
        laps: Clean laps for the race.
        column: Time column to plot.
        title: Panel heading.
        span: Y-axis height in seconds, shared across panels.

    Returns:
        The fitted line for each compound that had enough laps.
    """
    fits: dict[str, LineFit] = {}
    for compound in MODELLED_COMPOUNDS:
        subset = laps[laps["Compound"] == compound]
        if subset.empty:
            continue
        color = COMPOUND_COLORS[compound]
        axis.scatter(
            subset["TyreLife"], subset[column], s=7, alpha=0.12, color=color,
            linewidths=0, zorder=1,
        )
        medians = median_lap_time_by_tyre_age(subset, column)
        axis.plot(
            medians.index, medians.to_numpy(), color=color, linewidth=1.8,
            marker="o", markersize=3, zorder=3,
            label=f"{compound.lower()} median by age",
        )
        fit = uncontrolled_line(subset["TyreLife"], subset[column])
        if fit is None:
            continue
        fits[compound] = fit
        ages = np.array([fit.youngest_age, fit.oldest_age])
        axis.plot(
            ages, [fit.predict(age) for age in ages], color=color,
            linewidth=1.6, linestyle="--", zorder=4,
        )
    centre = float(laps[column].quantile([0.01, 0.99]).mean())
    axis.set_ylim(centre - span / 2, centre + span / 2)
    axis.set_title(title, fontsize=11, pad=8)
    axis.set_xlabel("Tyre age (laps)")
    axis.grid(alpha=0.25, linewidth=0.6)
    return fits


def annotate_slopes(axis: plt.Axes, fits: dict[str, LineFit]) -> None:
    """Write each compound's fitted slope into the corner of a panel.

    Args:
        axis: Axis to annotate.
        fits: Fitted line per compound.
    """
    lines = [
        f"{compound.lower()}: {fit.slope_s_per_lap:+.4f} s/lap"
        for compound, fit in fits.items()
    ]
    axis.text(
        0.03, 0.955, "\n".join(lines), transform=axis.transAxes,
        fontsize=9.5, va="top", ha="left", linespacing=1.5,
        bbox={"boxstyle": "round,pad=0.45", "facecolor": "white",
              "edgecolor": "#cccccc"},
    )


def build_figure(laps: pd.DataFrame, year: int, event_name: str) -> plt.Figure:
    """Build the two panel figure.

    Args:
        laps: Clean laps carrying both the raw and corrected time columns.
        year: Season, used in the title.
        event_name: Official event name, used in the title.

    Returns:
        The finished figure.
    """
    figure, axes = plt.subplots(1, 2, figsize=(11.5, 5.0), dpi=150)
    span = axis_span(laps, tuple(column for column, _ in PANELS))
    for axis, (column, title) in zip(axes, PANELS, strict=True):
        annotate_slopes(axis, draw_panel(axis, laps, column, title, span))
    axes[0].set_ylabel("Lap time (seconds)")
    axes[0].legend(loc="lower right", fontsize=8.5, framealpha=0.9)
    figure.suptitle(
        f"Tyre degradation at the {year} {event_name}, "
        "before and after correcting for fuel load",
        fontsize=13, y=0.975,
    )
    return figure


def caption(laps: pd.DataFrame, fuel_effect: float) -> str:
    """Return the footnote spelling out what the chart does and does not show."""
    return (
        f"Both panels share one y-axis span, so slopes are comparable. "
        f"Fuel correction of {fuel_effect:.4f} s/lap per lap of fuel remaining, "
        f"a physical estimate; the fitted model estimates it instead.\n"
        f"Slopes pool all drivers with no control for pace, so they are a "
        f"diagnostic, not this project's estimate of degradation. "
        f"Soft tyre excluded: too few clean laps.\n"
        f"{len(laps)} clean racing laps from FastF1 timing data. "
        f"Regenerate with scripts/plot_fuel_correction.py"
    )


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int, default=PILOT_SEASON)
    parser.add_argument("--circuit", default=PILOT_CIRCUIT)
    parser.add_argument(
        "--output", type=Path, default=Path("figures/fuel_correction.png")
    )
    return parser.parse_args()


def main() -> None:
    """Build the chart and write it to disk."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args = parse_args()
    session = load_race(args.season, args.circuit)
    laps = race_laps(session)
    total_laps = race_lap_count(laps)
    fuel_effect = physical_fuel_effect(total_laps)
    clean = clean_laps(laps).laps
    clean = clean.assign(
        **{
            CORRECTED_COLUMN: fuel_corrected_lap_time(
                clean, fuel_effect, total_laps
            )
        }
    )
    figure = build_figure(clean, args.season, session.event["EventName"])
    figure.text(0.5, 0.012, caption(clean, fuel_effect), fontsize=7.8,
                color="#555555", ha="center", va="bottom", linespacing=1.6)
    figure.subplots_adjust(top=0.86, bottom=0.21, left=0.07, right=0.98, wspace=0.13)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
