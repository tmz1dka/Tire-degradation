"""Read and query the precomputed model results.

This module is deliberately plain: the standard library only, no pandas and no
MCP SDK. It can therefore be tested on its own, and the server it backs cannot
accidentally start refitting a model when someone asks it a question.

Every lookup validates its arguments and raises `UnknownValue` naming the valid
options, because the thing calling these functions is a language model that will
guess a driver code or a race name and needs to be told what exists.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_PATH = Path("data/model_outputs.json")

# Said on every strategy comparison, because the number is easy to
# overstate: it is pace in clear air, not a prediction of the result.
CLEAR_NOTE = "The interval excludes zero, so the data does separate these two."
UNCLEAR_NOTE = (
    "The interval includes zero, so this data cannot tell the two apart. Say "
    "that, rather than reporting the difference as real."
)

STRATEGY_CAVEAT = (
    "A difference in pace in clear air, positive meaning the second "
    "driver's strategy cost more time. It accounts for tyre wear, the "
    "compound baselines and the pit stops. It does not account for track "
    "position: a quicker strategy can still lose the race if it leaves a "
    "driver stuck behind another car, which is what happened at the 2025 "
    "Hungarian Grand Prix."
)
SUPPORTED_SCHEMA = 2


class UnknownValue(ValueError):
    """An argument did not match anything in the precomputed results."""


def _reject(kind: str, given: str, valid: list[str]) -> UnknownValue:
    """Build an error naming what was asked for and what exists instead.

    Args:
        kind: What sort of thing was not found, for example "driver".
        given: The value that was not found.
        valid: Everything that would have been accepted.

    Returns:
        The error to raise.
    """
    return UnknownValue(
        f"Unknown {kind} {given!r}. Valid options: {', '.join(valid)}."
    )


def percentile(values: list[float], fraction: float) -> float:
    """Return a percentile of a list, interpolating between neighbours.

    Written out rather than imported so this module keeps no dependencies. It
    matches the linear interpolation that the rest of the project uses.

    Args:
        values: The sample.
        fraction: Where to cut, between 0 and 1.

    Returns:
        The value at that point in the sorted sample.

    Raises:
        ValueError: If the sample is empty or the fraction is out of range.
    """
    if not values:
        raise ValueError("cannot take a percentile of an empty sample")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"fraction must be between 0 and 1, got {fraction}")
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    below = int(position)
    above = min(below + 1, len(ordered) - 1)
    weight = position - below
    return ordered[below] * (1 - weight) + ordered[above] * weight


@dataclass(frozen=True)
class ModelOutputs:
    """The precomputed results, as read from disk.

    Attributes:
        settings: How the model was fitted, including seeds and thresholds.
        pooled: The pooled training model, with its bootstrap draws.
        races: One entry per race.
    """

    settings: dict[str, Any]
    pooled: dict[str, Any]
    races: tuple[dict[str, Any], ...]

    @classmethod
    def from_file(cls, path: Path = DEFAULT_OUTPUT_PATH) -> ModelOutputs:
        """Load results from a JSON file written by the precompute script.

        Args:
            path: Where the file is.

        Returns:
            The loaded results.

        Raises:
            FileNotFoundError: If the file is absent, with how to rebuild it.
            ValueError: If the file was written by a different schema version.
        """
        if not path.exists():
            raise FileNotFoundError(
                f"No precomputed results at {path}. Build them with "
                "'python -m mcp_server.precompute'."
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        version = raw.get("schema_version")
        if version != SUPPORTED_SCHEMA:
            raise ValueError(
                f"{path} has schema version {version}, this code expects "
                f"{SUPPORTED_SCHEMA}; rebuild it with "
                "'python -m mcp_server.precompute'."
            )
        return cls(
            settings=raw["settings"],
            pooled=raw["pooled_model"],
            races=tuple(raw["races"]),
        )

    @property
    def race_ids(self) -> list[str]:
        """Every race identifier, in order."""
        return [race["race_id"] for race in self.races]

    def race(self, race_id: str) -> dict[str, Any]:
        """Return one race, matched case insensitively on its identifier.

        Args:
            race_id: The race to find.

        Returns:
            That race's entry.

        Raises:
            UnknownValue: If no race matches.
        """
        wanted = race_id.strip().casefold()
        for race in self.races:
            if race["race_id"].casefold() == wanted or str(race["season"]) == wanted:
                return race
        raise _reject("race", race_id, self.race_ids)


def list_races(outputs: ModelOutputs) -> dict[str, Any]:
    """Summarise every race the results cover.

    Args:
        outputs: The precomputed results.

    Returns:
        The races, and the settings the model was fitted under.
    """
    return {
        "circuit": outputs.settings["circuit"],
        "races": [
            {
                "race": race["race_id"],
                "season": race["season"],
                "role": race["role"],
                "total_laps": race["total_laps"],
                "clean_racing_laps": race["clean_laps"],
                "drivers": race["drivers"],
            }
            for race in outputs.races
        ],
        "note": (
            "Races marked 'training' were used to fit the pooled model. The "
            "race marked 'held out' was never seen during fitting, which is "
            "what makes the strategy comparison an out-of-sample result."
        ),
    }


def driver_stints(race: dict[str, Any], driver: str) -> list[dict[str, Any]]:
    """Return one driver's stints in a race.

    Args:
        race: A race entry.
        driver: Driver abbreviation, case insensitive.

    Returns:
        That driver's stints, in order.

    Raises:
        UnknownValue: If the driver did not start this race.
    """
    wanted = driver.strip().upper()
    stints = [s for s in race["stints"] if s["driver"] == wanted]
    if not stints:
        raise _reject(f"driver for {race['race_id']}", driver, race["drivers"])
    return sorted(stints, key=lambda s: s["stint"])


def _find_compound(entry: dict[str, Any], compound: str) -> dict[str, Any]:
    """Return a compound's entry in a race.

    Args:
        entry: A race entry.
        compound: Compound name, case insensitive.

    Returns:
        That compound's entry.

    Raises:
        UnknownValue: If the race has no such compound.
    """
    wanted = compound.strip().upper()
    found = next((c for c in entry["compounds"] if c["compound"] == wanted), None)
    if found is None:
        raise _reject(
            f"compound for {entry['race_id']}",
            compound,
            [c["compound"] for c in entry["compounds"]],
        )
    return found


def _degradation_fields(
    found: dict[str, Any],
    outputs: ModelOutputs,
) -> dict[str, Any]:
    """Return either the rate with its interval, or why there is none.

    Args:
        found: The compound's entry in a race.
        outputs: The precomputed results, for the settings.

    Returns:
        The fields describing this compound's degradation.
    """
    interval = found["degradation_s_per_lap"]
    if interval is None:
        return {
            "degradation_s_per_lap": None,
            "no_estimate_because": found["no_estimate_because"],
        }
    return {
        "degradation_s_per_lap": round(interval["estimate"], 4),
        "confidence_interval_95": [
            round(interval["low"], 4),
            round(interval["high"], 4),
        ],
        "interval_from": (
            f"{outputs.settings['resamples']} resamples of whole stints, not "
            "individual laps, because laps within a stint are not independent"
        ),
    }


def get_degradation(
    outputs: ModelOutputs,
    compound: str,
    race: str,
) -> dict[str, Any]:
    """Return a compound's degradation rate in one race, with its interval.

    Args:
        outputs: The precomputed results.
        compound: Tyre compound, case insensitive.
        race: Race identifier or season.

    Returns:
        The rate and interval, or an explanation of why there is no estimate.

    Raises:
        UnknownValue: If the race or compound is not in the results.
    """
    entry = outputs.race(race)
    found = _find_compound(entry, compound)
    wanted = found["compound"]
    result: dict[str, Any] = {
        "race": entry["race_id"],
        "compound": wanted,
        "clean_racing_laps": found["clean_laps"],
        "stints": found["stints"],
    }
    result.update(_degradation_fields(found, outputs))
    return result


def compare_stints(
    outputs: ModelOutputs,
    driver_a: str,
    driver_b: str,
    race: str,
) -> dict[str, Any]:
    """Put two drivers' stints side by side for one race.

    Args:
        outputs: The precomputed results.
        driver_a: First driver's abbreviation.
        driver_b: Second driver's abbreviation.
        race: Race identifier or season.

    Returns:
        Both drivers' stints, with a caveat about what the trend figure is.

    Raises:
        UnknownValue: If the race or either driver is not in the results.
    """
    entry = outputs.race(race)
    return {
        "race": entry["race_id"],
        "drivers": {
            driver.strip().upper(): driver_stints(entry, driver)
            for driver in (driver_a, driver_b)
        },
        "trend_caveat": (
            "trend_s_per_lap is the slope of that one stint's fuel-corrected "
            "lap times against tyre age. It describes what that stint did and "
            "nothing more. A short stint can come out negative purely through "
            "noise, which does not mean the tyre got faster. For how a compound "
            "behaves, use get_degradation, which fits all stints together and "
            "returns a confidence interval. A trend of null means the stint had "
            f"fewer than {outputs.settings['min_laps_for_stint_trend']} clean "
            "laps, too few for even a descriptive slope."
        ),
    }


def _strategy_cost(
    stints: list[dict[str, Any]],
    degradation: dict[str, float],
    offset: dict[str, float],
    pit_loss_s: float,
) -> float:
    """Return the part of race time that depends on the strategy.

    Driver pace and fuel burn are identical for two strategies over the same
    race, so they cancel and are left out. What remains is tyre wear, the
    compound baselines and the pit stops.

    Args:
        stints: The stints run, in order.
        degradation: Degradation rate per compound.
        offset: Compound baseline offset.
        pit_loss_s: Seconds lost per pit stop.

    Returns:
        Strategy dependent race time in seconds.
    """
    total = (len(stints) - 1) * pit_loss_s
    for stint in stints:
        laps = stint["laps"]
        compound = stint["compound"]
        # Sum of tyre ages 1..laps, in closed form.
        total += degradation[compound] * laps * (laps + 1) / 2
        total += offset[compound] * laps
    return total


def _require_modelled_compounds(
    stints: list[dict[str, Any]],
    driver: str,
    modelled: list[str],
) -> None:
    """Raise if a driver used a compound the model has no rate for.

    Args:
        stints: That driver's stints.
        driver: Driver abbreviation, for the message.
        modelled: Compounds the model covers.

    Raises:
        UnknownValue: If any stint used an unmodelled compound.
    """
    used = {stint["compound"] for stint in stints}
    missing = sorted(used - set(modelled))
    if missing:
        raise UnknownValue(
            f"{driver} ran {', '.join(missing).lower()} in this race, and the "
            f"model only covers {', '.join(modelled).lower()}, so this strategy "
            "cannot be costed. See get_degradation for why that compound has no "
            "rate."
        )


def _costable_stints(
    entry: dict[str, Any],
    names: list[str],
    modelled: list[str],
) -> list[list[dict[str, Any]]]:
    """Return each driver's stints, refusing any the model cannot cost.

    Args:
        entry: The race.
        names: The drivers.
        modelled: Compounds the model covers.

    Returns:
        Each driver's stints, in the order given.

    Raises:
        UnknownValue: If a driver is unknown or used an unmodelled compound.
    """
    stints = [driver_stints(entry, driver) for driver in names]
    for driver, runs in zip(names, stints, strict=True):
        _require_modelled_compounds(runs, driver, modelled)
    return stints


def compare_strategies(
    outputs: ModelOutputs,
    race: str,
    driver_a: str,
    driver_b: str,
) -> dict[str, Any]:
    """Cost two drivers' actual strategies against each other, on pace alone.

    Args:
        outputs: The precomputed results.
        race: Race identifier or season.
        driver_a: Driver the comparison is measured against.
        driver_b: Driver being compared to them.

    Returns:
        The difference in seconds with its interval, and what it accounts for.

    Raises:
        UnknownValue: If the race or a driver is unknown, or a driver used a
            compound the model does not cover.
    """
    entry = outputs.race(race)
    pooled = outputs.pooled
    names = [driver.strip().upper() for driver in (driver_a, driver_b)]
    stints = _costable_stints(entry, names, sorted(pooled["degradation_s_per_lap"]))
    pit_loss = pooled["pit_loss_s"]
    offsets = pooled["compound_offset_s"]
    point = _delta(
        stints,
        {c: v["estimate"] for c, v in pooled["degradation_s_per_lap"].items()},
        offsets,
        pit_loss,
    )
    spread = [
        _delta(stints, draw["degradation"], draw["offset"], pit_loss)
        for draw in pooled["draws"]
    ]
    return _comparison_result(entry, names, stints, point, spread, pit_loss, outputs)


def _delta(
    stints: list[list[dict[str, Any]]],
    degradation: dict[str, float],
    offset: dict[str, float],
    pit_loss_s: float,
) -> float:
    """Return how much more time the second strategy takes than the first.

    Args:
        stints: Each driver's stints, first then second.
        degradation: Degradation rate per compound.
        offset: Compound baseline offset.
        pit_loss_s: Seconds lost per pit stop.

    Returns:
        Seconds. Positive means the second driver's strategy cost more time.
    """
    first, second = stints
    return _strategy_cost(second, degradation, offset, pit_loss_s) - _strategy_cost(
        first, degradation, offset, pit_loss_s
    )


def _strategy_summary(
    names: list[str],
    stints: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    """Describe each driver's strategy as stop count and stint list.

    Args:
        names: The drivers.
        stints: Their stints, in the same order.

    Returns:
        A readable summary per driver.
    """
    return {
        name: {
            "stops": len(runs) - 1,
            "stints": [f"{s['compound'].lower()} {s['laps']}" for s in runs],
        }
        for name, runs in zip(names, stints, strict=True)
    }


def _comparison_result(
    entry: dict[str, Any],
    names: list[str],
    stints: list[list[dict[str, Any]]],
    point: float,
    spread: list[float],
    pit_loss_s: float,
    outputs: ModelOutputs,
) -> dict[str, Any]:
    """Assemble the strategy comparison payload.

    Args:
        entry: The race.
        names: The two drivers.
        stints: Their stints, in the same order.
        point: The difference from the full-data fit.
        spread: That difference recomputed in every resample.
        pit_loss_s: Seconds lost per pit stop.
        outputs: The precomputed results, for the settings.

    Returns:
        The payload the tool returns.
    """
    low, high = percentile(spread, 0.025), percentile(spread, 0.975)
    return {
        "race": entry["race_id"],
        "comparison": f"{names[1]} relative to {names[0]}",
        "strategies": _strategy_summary(names, stints),
        "difference_s": round(point, 2),
        "confidence_interval_95": [round(low, 2), round(high, 2)],
        "quicker_on_pace": names[0] if point > 0 else names[1],
        "pit_loss_s_used": round(pit_loss_s, 2),
        "model_fitted_on": outputs.pooled["fitted_on"],
        "what_this_is": STRATEGY_CAVEAT,
    }


def _side(entry: dict[str, Any], compound: str) -> dict[str, Any]:
    """Describe one side of a comparison, with its draws if it has an estimate.

    Args:
        entry: A race entry.
        compound: Compound name.

    Returns:
        The race, the compound, its entry and its resampled rates.

    Raises:
        UnknownValue: If the race has no such compound.
    """
    found = _find_compound(entry, compound)
    return {
        "race": entry["race_id"],
        "compound": found["compound"],
        "entry": found,
        "draws": entry.get("degradation_draws", {}).get(found["compound"]),
    }


def compare_degradation(
    outputs: ModelOutputs,
    race_a: str,
    compound_a: str,
    race_b: str,
    compound_b: str,
) -> dict[str, Any]:
    """Compare two degradation rates, with an interval on the difference.

    Comparing two rates by eye, by checking whether their intervals overlap, is
    not a test of anything: intervals can overlap while the difference is
    clearly real, and can sit apart when it is not. The difference is therefore
    recomputed inside every resample and reported with its own interval.

    Args:
        outputs: The precomputed results.
        race_a: Race for the first rate.
        compound_a: Compound for the first rate.
        race_b: Race for the second rate.
        compound_b: Compound for the second rate.

    Returns:
        The difference with its interval, or why no comparison is possible.

    Raises:
        UnknownValue: If a race or compound is unknown.
    """
    first = _side(outputs.race(race_a), compound_a)
    second = _side(outputs.race(race_b), compound_b)
    missing = [s for s in (first, second) if not s["draws"]]
    if missing:
        return _no_comparison(first, second, missing)
    return _difference(first, second, outputs)


def _no_comparison(
    first: dict[str, Any],
    second: dict[str, Any],
    missing: list[dict[str, Any]],
) -> dict[str, Any]:
    """Explain why two rates cannot be compared.

    Args:
        first: The first side of the comparison.
        second: The second side.
        missing: The sides that have no estimate.

    Returns:
        A result with no difference and the reason for each missing side.
    """
    return {
        "comparison": _label(first, second),
        "difference_s_per_lap": None,
        "no_comparison_because": [
            f"{s['race']} {s['compound'].lower()}: "
            f"{s['entry'].get('no_estimate_because', 'no estimate available')}"
            for s in missing
        ],
        "warning": (
            "There is no number here and none can be made up. Do not substitute "
            "a rate from another race or compound, and do not describe the "
            "missing compound as degrading slowly: nothing is known about it."
        ),
    }


def _label(first: dict[str, Any], second: dict[str, Any]) -> str:
    """Name a comparison in the order it is reported, second minus first."""
    return (
        f"{second['race']} {second['compound'].lower()} minus "
        f"{first['race']} {first['compound'].lower()}"
    )


def _difference(
    first: dict[str, Any],
    second: dict[str, Any],
    outputs: ModelOutputs,
) -> dict[str, Any]:
    """Compute the difference between two rates and its interval.

    Within one race both rates come from the same fit, so pairing the nth draw
    of each keeps the correlation between them. Across races the fits are
    independent, and pairing by position is one valid way of drawing from both.

    Args:
        first: The first side of the comparison.
        second: The second side.
        outputs: The precomputed results, for the settings.

    Returns:
        The difference with its interval and how to read it.
    """
    spread = [b - a for a, b in zip(first["draws"], second["draws"], strict=True)]
    point = (
        second["entry"]["degradation_s_per_lap"]["estimate"]
        - first["entry"]["degradation_s_per_lap"]["estimate"]
    )
    low, high = percentile(spread, 0.025), percentile(spread, 0.975)
    clear = not low <= 0.0 <= high
    same_race = first["race"] == second["race"]
    return {
        "comparison": _label(first, second),
        "rates_s_per_lap": _rates(first, second),
        "difference_s_per_lap": round(point, 4),
        "confidence_interval_95": [round(low, 4), round(high, 4)],
        "difference_is_distinguishable_from_zero": clear,
        "how_to_read_this": CLEAR_NOTE if clear else UNCLEAR_NOTE,
        "same_race": same_race,
        "method": _method_note(same_race, outputs.settings["resamples"]),
    }


def _rates(first: dict[str, Any], second: dict[str, Any]) -> dict[str, float]:
    """Return each side's rate, keyed by race and compound."""
    return {
        f"{s['race']} {s['compound'].lower()}": round(
            s["entry"]["degradation_s_per_lap"]["estimate"], 4
        )
        for s in (first, second)
    }


def _method_note(same_race: bool, resamples: int) -> str:
    """Say how the difference was computed and what that handles.

    Args:
        same_race: Whether both rates came from the same fit.
        resamples: How many resamples were used.

    Returns:
        A sentence for the payload.
    """
    shared = (
        "Both rates come from the same fit, so their correlation is accounted "
        "for."
        if same_race
        else "The two rates come from separate fits to different races, which "
        "are independent."
    )
    return (
        f"The difference was recomputed inside each of {resamples} resamples "
        f"of whole stints. {shared}"
    )
