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

**Status.** The data pipeline and the fuel correction are built and tested. The
degradation model, the strategy simulation and the held-out test below are still
to come. The slopes above pool every driver with no control for pace, so they
are a diagnostic of the problem rather than this project's estimate of
degradation.

## The test this is building towards

At the 2025 Hungarian GP, McLaren split their strategies:

| Driver  | Result        | Strategy                                  |
|---------|---------------|-------------------------------------------|
| Norris  | P1            | 1 stop: medium 31 laps, then hard 39      |
| Piastri | P2, +0.698 s  | 2 stops: medium 18, hard 27, hard 25      |

Same car, opposite strategies, seven tenths apart after 70 laps. The model is
fitted on the 2023 and 2024 races only, then asked what the two-stop cost
against a one-stop, without ever having seen the 2025 race.

The observed 0.698 s gap is not a pure strategy effect: it also includes track
position and dirty air at a circuit where overtaking is rare. The model
estimates a free-air difference, and the write-up compares the two numbers
instead of claiming they are the same thing.

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
```

FastF1 caches downloaded sessions in `cache/` (gitignored), so each race is
downloaded once.
