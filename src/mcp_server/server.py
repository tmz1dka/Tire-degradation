"""An MCP server exposing the tyre degradation results.

Four tools, each a thin wrapper over `mcp_server.data`. All the work happened in
`mcp_server.precompute`; these read the file it wrote, so a call is a lookup and
needs no network, no FastF1 cache and no Formula 1 account.

Two things shape how this is written.

Docstrings are the tool descriptions the model reads, so they are written as
instructions to a model rather than notes to a maintainer. They say when to use
a tool and what its numbers do not mean, because an agent that is not told will
state a noisy single-stint slope as fact.

Errors are raised as `ToolError`, never returned as a string. A returned string
is reported as a successful result, so the model would treat the error text as
an answer. `ToolError` marks the call as failed while still showing the model
the message, which is what lets it retry with a valid argument.

Run it directly over stdio:
    python -m mcp_server.server
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from mcp_server import data
from mcp_server.data import ModelOutputs, UnknownValue

logger = logging.getLogger(__name__)

mcp = MCPServer("tyre-degradation")

_outputs: ModelOutputs | None = None


def outputs() -> ModelOutputs:
    """Return the precomputed results, loading them once and reusing them.

    Returns:
        The loaded results.

    Raises:
        ToolError: If the results file is missing or unreadable, with the
            command that rebuilds it.
    """
    global _outputs
    if _outputs is None:
        try:
            _outputs = ModelOutputs.from_file()
        except (FileNotFoundError, ValueError, KeyError) as error:
            raise ToolError(str(error)) from error
        logger.info("Loaded results for %d races", len(_outputs.races))
    return _outputs


RaceArg = Annotated[
    str,
    Field(
        description=(
            "Race to look at, either the full identifier such as "
            "'2023 Hungarian Grand Prix' or just the season, such as '2023'. "
            "Call list_races first if unsure."
        )
    ),
]
DriverArg = Annotated[
    str,
    Field(description="Three letter driver code, such as NOR or PIA.")
]


@mcp.tool()
def list_races() -> dict[str, Any]:
    """List the races in this dataset, with their drivers and lap counts.

    Call this first when you do not know which races or drivers exist. Every
    other tool takes a race from this list. The dataset covers one circuit
    only, so do not assume any other race is available.
    """
    return data.list_races(outputs())


@mcp.tool()
def get_degradation(
    compound: Annotated[
        str,
        Field(description="Tyre compound: SOFT, MEDIUM or HARD."),
    ],
    race: RaceArg,
) -> dict[str, Any]:
    """Get how fast a tyre compound lost lap time in one race.

    Returns seconds lost per lap of tyre age, with a 95% confidence interval
    and the number of clean laps behind it. Always report the interval, not
    just the estimate.

    Some compounds have no estimate. When degradation_s_per_lap is null, read
    no_estimate_because and say the data is insufficient. Do not substitute a
    figure from another race or another compound, and do not describe the
    compound as having low degradation: nothing is known about it.

    Intervals that overlap do not mean two compounds behave the same, and
    non-overlapping ones do not prove they differ. To compare two compounds
    properly you would need the difference recomputed with its own interval,
    which this tool does not provide.
    """
    try:
        return data.get_degradation(outputs(), compound, race)
    except UnknownValue as error:
        raise ToolError(str(error)) from error


@mcp.tool()
def compare_stints(
    driver_a: DriverArg,
    driver_b: DriverArg,
    race: RaceArg,
) -> dict[str, Any]:
    """Show two drivers' stints side by side: compound, length and pace trend.

    Use this to see what strategy each driver actually ran, and how their tyres
    behaved within each stint.

    trend_s_per_lap is descriptive only. It is one stint's slope of fuel
    corrected lap time against tyre age, and on a short stint it is mostly
    noise: a negative value does not mean the tyre improved with age. Read
    trend_caveat in the result and pass that caution on. For how a compound
    behaves, use get_degradation instead.
    """
    try:
        return data.compare_stints(outputs(), driver_a, driver_b, race)
    except UnknownValue as error:
        raise ToolError(str(error)) from error


@mcp.tool()
def compare_strategies(
    race: RaceArg,
    driver_a: DriverArg,
    driver_b: DriverArg,
) -> dict[str, Any]:
    """Work out what two drivers' pit strategies were worth against each other.

    Costs each driver's actual stints with the fitted model and a pit loss
    measured from the races, and returns the difference in seconds with a 95%
    confidence interval. Positive means driver_b's strategy cost more time.

    This is a difference in pace in clear air. It does not include track
    position, so a strategy that comes out quicker here can still lose the
    race: at the 2025 Hungarian Grand Prix the quicker strategy on pace
    finished second, stuck behind the car it could not pass. Always say which
    of the two you are reporting, and never present this number as a prediction
    of who would have won.
    """
    try:
        return data.compare_strategies(outputs(), race, driver_a, driver_b)
    except UnknownValue as error:
        raise ToolError(str(error)) from error


@mcp.tool()
def compare_degradation(
    race_a: RaceArg,
    compound_a: Annotated[
        str, Field(description="Compound for the first rate: SOFT, MEDIUM or HARD.")
    ],
    race_b: RaceArg,
    compound_b: Annotated[
        str, Field(description="Compound for the second rate.")
    ],
) -> dict[str, Any]:
    """Compare two degradation rates and get an interval on the difference.

    Use this whenever the question is whether one tyre degraded faster than
    another, whether that is two compounds in the same race or the same
    compound in two different races. Do not answer such a question by comparing
    two separate get_degradation results: overlapping intervals do not mean two
    rates are the same, and separated ones do not prove they differ. Only the
    difference, recomputed with its own interval, settles it.

    Read difference_is_distinguishable_from_zero before saying anything. When
    it is false, the honest answer is that this data cannot tell the two apart,
    not that they are equal and not that the larger estimate is the real one.

    When one side has too little data, difference_s_per_lap is null and
    no_comparison_because says which side and why. Report that as it stands.
    """
    try:
        return data.compare_degradation(
            outputs(), race_a, compound_a, race_b, compound_b
        )
    except UnknownValue as error:
        raise ToolError(str(error)) from error


if __name__ == "__main__":
    mcp.run()
