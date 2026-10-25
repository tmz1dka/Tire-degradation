# F1 Tyre Degradation & Pit Strategy

**Status: in progress.** The pipeline is being built on one pilot race (2023
Hungarian GP). Once the model has been validated on held-out data, the
headline finding and its chart will go at the top of this page.

## The question

At the Hungaroring, how much lap time does a tyre lose per lap to degradation,
and does that make a one-stop or a two-stop faster?

## The test

At the 2025 Hungarian GP, McLaren split their strategies:

| Driver  | Result        | Strategy                                  |
|---------|---------------|-------------------------------------------|
| Norris  | P1            | 1 stop: Medium 31 laps → Hard 39 laps     |
| Piastri | P2, +0.698 s  | 2 stops: Medium 18 → Hard 27 → Hard 25    |

Same car, opposite strategies, seven tenths apart after 70 laps. The model is
fitted on the 2023 and 2024 races only, then asked what Piastri's two-stop
cost versus a one-stop, without ever having seen the 2025 race.

The observed 0.698 s gap is not a pure strategy effect: it also includes track
position and dirty air at a circuit where overtaking is rare. The model
estimates a free-air strategy delta, and the write-up compares the two numbers
rather than claiming a match.

## Approach

- **Data:** lap-by-lap timing from [FastF1](https://github.com/theOehrly/Fast-F1)
  for the 2023–2025 Hungarian GPs. Earlier seasons are excluded because the
  2022 regulations (ground-effect cars, 18-inch tyres) changed the problem.
- **Cleaning:** remove lap 1, pit in/out laps, safety car / VSC / red flag
  laps, and laps run within 1.0 s of the car ahead (traffic; the threshold's
  effect is reported, not assumed away).
- **Model:** lap time = driver pace + fuel burn + tyre degradation (by compound
  and tyre age) + track temperature + residual traffic. The fuel effect is
  estimated from the data, with fixed-constant fits shown as a sensitivity band.
- **Validation:** train on 2023–2024, test once on 2025. No random lap splits:
  laps within a stint are strongly correlated, so a random split leaks.
- **Uncertainty:** confidence intervals from a bootstrap that resamples whole
  stints, carried through to the strategy comparison.
- **Scope:** medium and hard tyres only. The soft is a qualifying tyre at
  Hungary (14 race stints across three years, none longer than 17 laps), so
  there is too little data to model it.

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

Run the tests, and regenerate the lap cleaning figures quoted in the decisions
file:

```bash
.venv/bin/python -m pytest
.venv/bin/python scripts/cleaning_report.py
.venv/bin/python scripts/fuel_sensitivity.py
```

FastF1 caches downloaded sessions in `cache/` (gitignored), so each race is
downloaded once.
