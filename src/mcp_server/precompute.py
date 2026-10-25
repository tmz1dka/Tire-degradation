"""Precompute the model results the MCP server serves.

This is the only part of the server that touches FastF1. It fits the model
once, writes everything the tools need to a single JSON file, and is run by
hand whenever the analysis changes. The tools then read that file, so a tool
call is a dictionary lookup rather than a model fit, and the server works with
no cache, no network and no Formula 1 account.

The file carries the bootstrap draws as well as the summary intervals. That is
what lets the server put an interval on a strategy comparison it has never seen
before: the same idea as tyre_deg.model.derived_interval, applied offline.

Usage:
    python -m mcp_server.precompute
    python -m mcp_server.precompute --resamples 2000 --output data/x.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from tyre_deg.cleaning import clean_laps
from tyre_deg.config import (
    MIN_LAPS_FOR_SLOPE,
    MIN_LAPS_FOR_STINT_TREND,
    MODELLED_COMPOUNDS,
    MODELLING_SEASONS,
    PILOT_CIRCUIT,
    TEST_SEASON,
    TRAFFIC_GAP_THRESHOLD_S,
    TRAIN_SEASONS,
)
from tyre_deg.diagnostics import uncontrolled_slope
from tyre_deg.fuel import fuel_corrected_lap_time, physical_fuel_effect
from tyre_deg.loading import load_race, race_lap_count, race_laps
from tyre_deg.model import (
    BootstrapResult,
    CoefficientInterval,
    DegradationEstimate,
    bootstrap_degradation,
)
from tyre_deg.strategy import measure_pit_loss

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_OUTPUT = Path("data/model_outputs.json")
PLACES = 6


def interval_to_dict(interval: CoefficientInterval) -> dict[str, float]:
    """Render a coefficient and its interval as plain JSON values.

    Args:
        interval: A fitted coefficient with its bootstrap interval.

    Returns:
        The estimate with the low and high ends of the interval.
    """
    return {
        "estimate": round(interval.point, PLACES),
        "low": round(interval.low, PLACES),
        "high": round(interval.high, PLACES),
    }


def compound_entry(
    compound: str,
    result: BootstrapResult,
    clean: pd.DataFrame,
) -> dict[str, object]:
    """Describe one compound's degradation, or why it has no estimate.

    A compound the model does not cover still gets an entry, carrying its lap
    count and the threshold it failed, so the server can explain the gap rather
    than leaving the agent to guess.

    Args:
        compound: Tyre compound name.
        result: The fitted model for this race.
        clean: Clean laps for this race.

    Returns:
        The compound's entry for the output file.
    """
    laps = clean[clean["Compound"] == compound]
    entry: dict[str, object] = {
        "compound": compound,
        "clean_laps": int(len(laps)),
        "stints": int(laps.groupby(["Driver", "Stint"]).ngroups),
    }
    if compound in result.degradation:
        entry["degradation_s_per_lap"] = interval_to_dict(result.degradation[compound])
    else:
        entry["degradation_s_per_lap"] = None
        entry["no_estimate_because"] = (
            f"only {len(laps)} clean racing laps on this compound, against the "
            f"{MIN_LAPS_FOR_SLOPE} needed to fit a degradation rate, so this "
            "compound is not modelled"
        )
    return entry


def stint_trends(
    clean: pd.DataFrame,
    total_race_laps: int,
) -> dict[tuple[str, float], tuple[int, float | None]]:
    """Return each stint's clean lap count and its own fuel corrected trend.

    Args:
        clean: The racing laps that survived cleaning.
        total_race_laps: Laps in the race, for the fuel correction.

    Returns:
        Clean lap count and trend, keyed by driver and stint. The trend is None
        where the stint was too short for even a descriptive slope.
    """
    fuel = physical_fuel_effect(total_race_laps)
    corrected = clean.assign(
        corrected_s=fuel_corrected_lap_time(clean, fuel, total_race_laps)
    )
    return {
        key: (
            len(group),
            uncontrolled_slope(
                group["TyreLife"],
                group["corrected_s"],
                min_laps=MIN_LAPS_FOR_STINT_TREND,
            ),
        )
        for key, group in corrected.groupby(["Driver", "Stint"])
    }


def stint_rows(
    raw: pd.DataFrame,
    clean: pd.DataFrame,
    total_race_laps: int,
) -> list[dict[str, object]]:
    """Describe every stint in a race, with its own fuel corrected trend.

    The trend is one stint's slope of lap time against tyre age. It is a
    description of what that stint did, not an estimate of how the compound
    behaves: a short stint can easily come out negative. Stints too short for
    even that get no trend rather than a noisy one.

    Args:
        raw: Every lap of the race, so stint lengths include pit laps.
        clean: The racing laps that survived cleaning.
        total_race_laps: Laps in the race, for the fuel correction.

    Returns:
        One entry per driver and stint.
    """
    trends = stint_trends(clean, total_race_laps)
    rows = []
    for (driver, stint), group in raw.groupby(["Driver", "Stint"]):
        clean_laps_count, trend = trends.get((driver, stint), (0, None))
        rows.append(
            {
                "driver": str(driver),
                "stint": int(stint),
                "compound": str(group["Compound"].iloc[0]),
                "laps": int(len(group)),
                "clean_laps": int(clean_laps_count),
                "trend_s_per_lap": None if trend is None else round(trend, PLACES),
            }
        )
    return rows


def build_race(
    year: int,
    raw: pd.DataFrame,
    clean: pd.DataFrame,
    resamples: int,
    seed: int,
) -> dict[str, object]:
    """Summarise one race: its degradation, its fuel effect and its stints.

    Args:
        year: Season.
        raw: Every lap of the race.
        clean: The racing laps that survived cleaning.
        resamples: Bootstrap resamples for the intervals.
        seed: Seed for those resamples.

    Returns:
        The race's entry for the output file. ``clean_laps`` counts every
        racing lap that survived cleaning; ``laps_fitted`` counts only those on
        a modelled compound, so the two differ by the soft tyre laps.
    """
    total_laps = race_lap_count(raw)
    result = bootstrap_degradation(clean, resamples=resamples, seed=seed)
    compounds = sorted(set(clean["Compound"].dropna().unique()))
    logger.info("%s: fitted on %d clean laps", raw["race_id"].iloc[0], len(clean))
    return {
        "race_id": str(raw["race_id"].iloc[0]),
        "season": year,
        "role": "held out" if year == TEST_SEASON else "training",
        "total_laps": total_laps,
        "clean_laps": int(len(clean)),
        "laps_fitted": int(result.estimate.laps),
        "drivers": sorted(str(d) for d in raw["Driver"].dropna().unique()),
        "fuel_s_per_lap": interval_to_dict(result.fuel),
        "compounds": [compound_entry(c, result, clean) for c in compounds],
        "stints": stint_rows(raw, clean, total_laps),
    }


def build_pooled(
    clean: pd.DataFrame,
    raw: pd.DataFrame,
    resamples: int,
    seed: int,
) -> dict[str, object]:
    """Fit the pooled training model and keep every resampled fit.

    The draws are what let the server put an interval on a strategy comparison
    computed later, without refitting anything.

    Args:
        clean: Clean laps from the training races, concatenated.
        raw: Every lap of those races, for measuring the pit loss.
        resamples: Bootstrap resamples.
        seed: Seed for those resamples.

    Returns:
        The pooled model's entry for the output file.
    """
    result = bootstrap_degradation(clean, resamples=resamples, seed=seed)
    pit_loss = measure_pit_loss(raw, result.estimate)
    return {
        "fitted_on": sorted(str(r) for r in clean["race_id"].unique()),
        "clean_laps": int(len(clean)),
        "laps_fitted": int(result.estimate.laps),
        "pit_loss_s": round(pit_loss, PLACES),
        "fuel_s_per_lap": interval_to_dict(result.fuel),
        "degradation_s_per_lap": {
            compound: interval_to_dict(interval)
            for compound, interval in result.degradation.items()
        },
        "compound_offset_s": {
            compound: round(value, PLACES)
            for compound, value in result.estimate.compound_offset_s.items()
        },
        "draws": [draw_to_dict(draw) for draw in result.draws],
    }


def draw_to_dict(draw: DegradationEstimate) -> dict[str, object]:
    """Render one resampled fit as plain JSON values.

    Args:
        draw: Coefficients from a single bootstrap resample.

    Returns:
        The coefficients the server needs to recost a strategy.
    """
    return {
        "fuel": round(draw.fuel_s_per_lap, PLACES),
        "degradation": {
            c: round(v, PLACES) for c, v in draw.degradation_s_per_lap.items()
        },
        "offset": {
            c: round(v, PLACES) for c, v in draw.compound_offset_s.items()
        },
    }


def settings_used(circuit: str, resamples: int, seed: int) -> dict[str, object]:
    """Record how the results were produced, so they can be reproduced.

    Args:
        circuit: Circuit the results cover.
        resamples: Bootstrap resamples behind every interval.
        seed: Seed for those resamples.

    Returns:
        The settings block of the output file.
    """
    return {
        "circuit": circuit,
        "train_seasons": list(TRAIN_SEASONS),
        "test_season": TEST_SEASON,
        "modelled_compounds": list(MODELLED_COMPOUNDS),
        "resamples": resamples,
        "seed": seed,
        "confidence": 0.95,
        "traffic_gap_threshold_s": TRAFFIC_GAP_THRESHOLD_S,
        "min_laps_for_slope": MIN_LAPS_FOR_SLOPE,
        "min_laps_for_stint_trend": MIN_LAPS_FOR_STINT_TREND,
        "generated_by": "python -m mcp_server.precompute",
    }


def build_outputs(circuit: str, resamples: int, seed: int) -> dict[str, object]:
    """Build the whole output file.

    Args:
        circuit: Circuit name FastF1 recognises.
        resamples: Bootstrap resamples for every interval.
        seed: Seed for those resamples.

    Returns:
        The output file's contents.
    """
    loaded = {}
    for year in MODELLING_SEASONS:
        raw = race_laps(load_race(year, circuit))
        loaded[year] = (raw, clean_laps(raw).laps)
    training = [loaded[year] for year in TRAIN_SEASONS]
    return {
        "schema_version": SCHEMA_VERSION,
        "settings": settings_used(circuit, resamples, seed),
        "pooled_model": build_pooled(
            pd.concat([clean for _, clean in training], ignore_index=True),
            pd.concat([raw for raw, _ in training], ignore_index=True),
            resamples,
            seed,
        ),
        "races": [
            build_race(year, raw, clean, resamples, seed)
            for year, (raw, clean) in sorted(loaded.items())
        ],
    }


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--circuit", default=PILOT_CIRCUIT)
    parser.add_argument("--resamples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    """Build the output file and write it to disk."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    outputs = build_outputs(args.circuit, args.resamples, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(outputs, indent=1) + "\n", encoding="utf-8")
    size_kb = args.output.stat().st_size / 1024
    logger.info("Wrote %s (%.0f KB)", args.output, size_kb)


if __name__ == "__main__":
    main()
