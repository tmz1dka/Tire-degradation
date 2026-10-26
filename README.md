# F1 Tyre Degradation & Pit Strategy

How much lap time does a Formula 1 car lose each lap as its tyres wear, and does
that make a one-stop or a two-stop pit strategy faster?

## What the data shows so far

![Two panels of lap time against tyre age at the 2023 Hungarian Grand Prix. In
the raw panel the medium tyre's fitted line slopes downwards. After correcting
for fuel load, both compounds slope upwards.](figures/fuel_correction.png)

The raw lap times say the medium tyre gets **faster** as it wears, at -0.0072
seconds per lap. It does not. A car starts the race carrying about 100kg of fuel
and gets quicker as that burns off, and over a stint that improvement is large
enough to hide tyre wear completely. Correcting for it turns the medium from
-0.0072 to +0.0530 seconds per lap, and the hard from +0.0248 to +0.0715.

The size of that correction matters as much as its direction. Across the range
of fuel effects worth considering, the hard tyre's degradation runs anywhere
from +0.0248 to +0.0847 seconds per lap, a spread of more than three times. The
assumption would be doing more work than the data. That is why the model
estimates the fuel effect rather than assuming one, and reports the range
alongside the answer.

The slopes on that chart pool every driver with no control for pace, so they
diagnose the problem rather than answer the question. The model below does that.

## What the model estimates

![Left: the fitted fuel effect and the two compounds' degradation rates, each
with its confidence interval. A star marks the physical estimate of the fuel
effect, which falls inside the fitted interval. The two compound intervals
overlap. Right: the running time difference between the two 2025 strategies
across the race, stepping up at each pit stop and falling back on fresher
tyres, ending about nine seconds in favour of the two
stop.](figures/model_results.png)

The right panel is the whole argument in one picture. Each pit stop costs the
two stop about twenty seconds, which is the near vertical jump, and it then
earns the time back on younger tyres. After two stops it is nine seconds ahead
on pace. The diamond is where the race actually finished.

Fitted on the 2023 and 2024 races, 2029 clean laps, with one intercept per
driver per race. Intervals come from resampling whole stints 1000 times, not
individual laps, because laps within a stint share a driver, a car, a tyre set
and a fuel load.

| Term | Estimate | 95% interval |
|---|---|---|
| Fuel effect, per lap of fuel remaining | +0.0437 s | +0.0395 to +0.0484 |
| Medium degradation, per lap of tyre age | +0.0649 s | +0.0515 to +0.0825 |
| Hard degradation, per lap of tyre age | +0.0784 s | +0.0680 to +0.0904 |

Two things worth drawing out.

**The fuel effect was measured, not assumed.** Nothing told the model that a
Formula 1 car burns about 100kg of fuel worth roughly 0.03 seconds a kilogram.
It arrived at 0.0437 seconds per lap from the lap times alone, and the interval
contains the 0.0429 that physics predicts. Two independent routes to the same
number is the strongest check available here.

What makes that possible is the shape of a race. Within one driver's race, lap
number climbs steadily while tyre age drops back to zero at every pit stop. A
ramp and a sawtooth can be told apart, so one race is enough to separate fuel
from tyre wear. A single stint is not, and the test suite checks exactly that.

**The two compounds cannot be told apart.** The hard appears to degrade faster
than the medium, which is the wrong way round for a harder tyre. But the
difference is +0.0135 s/lap with an interval of -0.0070 to +0.0309, which
includes zero. The honest conclusion is that this data cannot separate them, not
that the hard is worse. Judging that by eye from the two rows above would have
been wrong: intervals can overlap while a difference is still clearly real, and
can look separate when it is not. The difference has to be recomputed inside
every resample, which is what the code does.

## The held-out test

The model was fitted on 2023 and 2024 only. The 2025 race supplied two things it
could not have known: which strategies were run, and how it finished.

| | Strategy | |
|---|---|---|
| Norris | one stop: medium 31 laps, hard 39 | won |
| Piastri | two stops: medium 18, hard 27, hard 25 | +0.698 s |

Pit loss, measured from the training races rather than assumed: 19.60 s.

**The model says the two stop had about nine seconds more pace**, at -9.00 s
with an interval of -13.30 to -4.77. Norris won on the one stop.

Both of those can be true at once, and the distance between them is the most
interesting thing in this project. The arithmetic is simple enough to check by
hand: the second stop buys 28.6 s of tyre wear and pays 19.6 s of pit lane for
it, so on raw pace it is 9 s ahead. Three reasons that did not win the race.

**Track position.** The model estimates a difference in free air. Piastri spent
the end of the race behind Norris at a circuit where overtaking is close to
impossible, so pace he may have had was pace he could not use. A model of lap
times cannot see this, and at the Hungaroring it is decisive.

**Tyre management.** A driver committed to a one stop drives to protect the
tyre. The model charges him the field average degradation rate, which is
measured mostly from cars not doing that. This is not a flaw that more data
fixes: how hard a driver pushes is chosen along with the strategy, so the two
cannot be separated from race data alone.

**A straight line charges full price for every lap**, which was the third
explanation until it was tested. If real wear eased off with age, the 28.6 s
would be overstated and the one stop would be cheaper than the model thinks. A
quadratic and five hinge shapes were scored against held-out races: the best
beat the straight line by 0.0012 s, 0.2% of its error, and three were worse. So
this explanation does not survive. If anything it points the other way, because
the straight line's errors at high tyre age are positive, meaning it predicts
long stints as faster than they really were.

So the honest summary is that the model answers a narrower question than "who
wins": it estimates the pace difference between two strategies in clear air,
and it says the two stop was worth about nine seconds of it.

## Limitations

The confounders that could not be removed, and which way each one pushes, then
what the project depends on outside itself.

- **Compound choice is not random.** Teams pick tyres to suit the car, the
  track position and the plan. A degradation rate therefore partly measures how
  a tyre was used. The fitted difference between the medium and the hard
  includes zero, which is consistent with this.
- **Tyre management is tied to the strategy being judged.** A driver nursing a
  long stint shows less degradation. This biases the cost of long stints upward,
  which means the one stop is probably treated worse than it deserves.
- **Degradation is modelled as a straight line.** Curved shapes were tested on
  held-out races and none improved on it by more than 0.2%, so the line stays.
  Its errors do show a pattern it cannot capture, strongest at tyre ages the
  data barely covers.
- **Track position is not modelled at all.** At this circuit that is the
  difference between a faster strategy and a winning one.
- **Two training races.** Only two cross-validation folds are available inside
  the training set, so model form cannot be chosen with much confidence, and
  one test race makes the out-of-sample check noisy.
- **The pit loss is a single measured number.** Its uncertainty is not carried
  through the intervals. Moving it by two seconds either way moves the answer
  by about two seconds, which is reported alongside.
- **Track temperature is not in the fitted model.** Within a race it moves
  almost in step with fuel burn, so including it on this data would have made
  the two impossible to separate.

**The data source closed partway through this project.** Formula 1 put its
timing archive behind a login in late 2026, and the endpoint used here now
answers with HTTP 401. FastF1 3.9 can sign in with a free F1 account, which is
why that version is pinned; every number published here was regenerated from the
cache after the upgrade and none of them moved. Anyone who already has the cache
is unaffected, and the tests never touched the data at all, so they still pass on
a fresh clone with no account, no network and no cache. But reproducing the
analysis from scratch now depends on a third party that has already changed the
rules once, and could again.

**Status.** The pipeline, the fuel correction, the degradation model, the
strategy comparison and the test of curved degradation shapes are all built and
tested. What remains unresolved is track position, which lap time modelling
alone cannot reach.

## Approach

- **Data:** lap-by-lap timing from [FastF1](https://github.com/theOehrly/Fast-F1)
  for the 2023 to 2025 Hungarian GPs. Earlier seasons are excluded because the
  2022 regulations, ground-effect cars and 18-inch tyres, changed the problem.
- **Cleaning:** remove lap 1, pit in and out laps, safety car and red flag laps,
  and laps run within 1.0s of the car ahead. That keeps 68% to 80% of laps,
  depending on the race.
- **Model:** lap time = driver pace + fuel burn + tyre degradation by compound
  and tyre age + track temperature + residual traffic.
- **Validation:** train on 2023 and 2024, test once on 2025. No random lap
  splits: laps within a stint are strongly correlated, so a random split leaks.
- **Uncertainty:** intervals from a bootstrap that resamples whole stints,
  carried through to the strategy comparison.
- **Scope:** medium and hard tyres only. The soft is a qualifying tyre here,
  with 45 clean racing laps across three seasons, far too few to model.

## Decisions

The main choices in this project, the reasoning behind them, and the options
that were rejected, are written up in [docs/decisions.md](docs/decisions.md).
That includes the pilot circuit, which was changed after the data contradicted
the first pick.

## Setup

Requires Python 3.11.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt       # runtime
.venv/bin/python -m pip install -r requirements-dev.txt   # tests, linting, audit
.venv/bin/python -m pip install -e .                      # the tyre_deg package
```

Run the tests, and regenerate every figure and number quoted above:

```bash
.venv/bin/python -m pytest
.venv/bin/python scripts/cleaning_report.py
.venv/bin/python scripts/fuel_sensitivity.py
.venv/bin/python scripts/plot_fuel_correction.py
.venv/bin/python scripts/fit_model.py
.venv/bin/python scripts/strategy_test.py
.venv/bin/python scripts/compare_forms.py
.venv/bin/python scripts/plot_model_results.py
```

FastF1 caches downloaded sessions in `cache/` (gitignored), so each race is
downloaded once.

## Asking an agent about the results

The repository ships an MCP server, so a coding agent can query the model
rather than being told about it. Four tools:

| Tool | Answers |
|---|---|
| `list_races` | which races and drivers exist |
| `get_degradation` | how fast a compound lost lap time in a race, with its interval |
| `compare_stints` | two drivers' stints side by side |
| `compare_strategies` | what two drivers' pit strategies were worth against each other |
| `compare_degradation` | whether one tyre really degraded faster than another |

Install the extra dependency and register it:

```bash
.venv/bin/python -m pip install -r requirements-mcp.txt
claude mcp add tyre-degradation -s local -- \
  "$PWD/.venv/bin/python" "$PWD/src/mcp_server/server.py"
```

The results it serves are committed, so this works straight after a clone. To
rebuild them after changing the analysis:

```bash
.venv/bin/python -m mcp_server.precompute
```

### An example exchange

> **How fast did the medium degrade at the 2023 race?**
>
> 0.0564 seconds per lap of tyre age, with a 95% interval of 0.0403 to 0.0780.
> That comes from 337 clean racing laps, and the interval is built by resampling
> whole stints rather than individual laps.
>
> **And the soft?**
>
> There is no estimate. The soft has 9 clean racing laps in that race against
> the 40 needed to fit a rate, so it is not modelled. That is not a claim that
> it degraded slowly: nothing is known about it.
>
> **Did the medium degrade faster in 2024 than in 2023?**
>
> The estimates differ, 0.0755 against 0.0564, but the difference is +0.0191
> seconds per lap with an interval of -0.0125 to 0.0469. That includes zero, so
> this data cannot tell the two races apart. Comparing the two intervals by eye
> would not have settled it either way.
>
> **Was Piastri's two-stop quicker than Norris's one-stop in 2025?**
>
> On pace, yes, by about 9.0 seconds, with a 95% interval of 4.8 to 13.3
> seconds in his favour. But that is a difference in clear air. It excludes
> track position, and Piastri finished second, stuck behind the car he could
> not pass.

### Design decisions

**The results are precomputed into `data/model_outputs.json`.** A tool call is a
lookup, not a model fit, so calls are fast and need no FastF1 cache, no network
and no Formula 1 account. It is the one piece of derived data in the repository
that is committed, because without it nobody could run the server from a clone
now that the data source needs a login.

**The file carries the 1000 bootstrap fits, not just the summary intervals.**
That is what lets `compare_strategies` put a real interval on a pairing it has
never seen: the difference is recomputed inside every resample, in plain
arithmetic, offline.

**Every answer carries its uncertainty.** Each tool returns the interval and the
number of laps behind it, and a compound with too little data returns an
explanation instead of a number. The aim is that an agent cannot state a result
more confidently than the data allows.

**The logic sits behind the tools, not inside them.** `mcp_server/data.py` is
standard library only, with no MCP and no pandas, so it is tested directly and
the server cannot accidentally start refitting a model. `server.py` is four thin
wrappers that turn its errors into `ToolError`, which is what makes an agent
retry with a valid argument instead of reading an error string as an answer.

### Getting the data

Formula 1 put its timing archive behind a login in late 2026. FastF1 3.9 can
sign in with a free F1 account, so the first run needs credentials in the
environment:

```bash
export F1_USERNAME="your F1 account email"
export F1_PASSWORD="your F1 account password"
```

Put them in the environment or a local `.env`, never in the repository. After
the first run the data is cached and the credentials are no longer needed.

The tests do not need any of this. They build their own lap data, so
`pytest` passes on a fresh clone with no account, no network and no cache.
