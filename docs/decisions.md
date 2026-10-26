# Decisions

The main choices in this project: what was decided, why, and which options were
rejected.

## 1. FastF1 as the data source

**Decision.** Use FastF1 for all lap data.

**Why.** It reads Formula 1's own timing archive and gives, for every lap, the
tyre compound, tyre age, stint number, pit in and out times, and track status.
Tyre age and stint boundaries are the core inputs for this project, and no other
free source carries them per lap.

**Not chosen.**
- *Ergast API.* Offline. The endpoint returns HTTP 404. It also never had
  per-lap tyre data, so it could not have been the main source anyway.
- *Jolpica mirror as the main source.* It works, and it is a reasonable fallback
  for results and schedules, but it copies the Ergast schema and so has no
  per-lap tyre data either. FastF1 already routes its own result lookups there.
- *Scraping the official timing pages.* Fragile, and it duplicates what FastF1
  already does.

## 2. Seasons 2023 to 2025 only

**Decision.** Use the 2023, 2024 and 2025 races.

**Why.** Degradation is a property of a particular car and tyre, so data from
either side of a rules change is not comparable. The 2022 rules introduced
ground-effect cars and 18-inch tyres. The 2026 rules introduced new engines and
active aerodynamics. Within 2023 to 2025 the Hungaroring layout is unchanged,
and the race fastest laps are close together at 80.50s, 80.31s and 79.41s.

**Not chosen.**
- *2018 to 2025.* More data, but it mixes two tyre sizes and two aerodynamic
  eras, so the pooled coefficient would describe no real car.
- *Adding 2022.* Tempting, because training only has two races. Measured rather
  than assumed: Hungary 2022 had rain in 46 of 167 weather samples, 7.2% of laps
  under safety car or similar, and a track at 23 to 29C against 46 to 51C in
  2023. Degradation is strongly temperature dependent, so this race measures
  something the others do not.

**Cost accepted.** Two training races and one test race is thin. The model has
to stay simple, and the reported intervals will be wide.

## 3. Hungaroring as the pilot circuit

**Decision.** Build the pipeline on the Hungarian GP, starting with the 2023
race. Barcelona was picked first and then dropped after comparing six circuits.

**Why.** All three races are dry with no safety car or virtual safety car laps at
all. Both compounds that matter are well covered every year: 337, 335 and 332
clean medium laps, and 660, 697 and 585 clean hard laps. Degradation is clearly
measurable, at 0.0715 s/lap on the hard and 0.0530 s/lap on the medium in 2023
after the fuel correction. Most importantly, the 2025 race splits the field
between strategies, with 11 drivers stopping once and 9 stopping twice, and the
top two finishers split them in the same car: Norris won on a one-stop (medium
31 laps, then hard 39) and Piastri was second on a two-stop (medium 18, hard 27,
hard 25), 0.698s behind. That is the claim the project is built to test, and it
sits in the held-out season.

**Not chosen.**
- *Barcelona.* Three measured problems. The 2022 race fastest lap was 84.108s
  against 76.330s in 2023, because the chicane was removed and the track was
  much hotter, so 2022 cannot be pooled. The 2025 race has only 11 hard-tyre
  laps, so a hard compound could not be tested out of sample. And no driver ran
  a one-stop there between 2023 and 2025, so the question that motivated the
  choice is not in the data.
- *Bahrain.* The strongest degradation on the calendar and four clean dry races,
  but medium laps fall to 10 in 2023 and 0 in 2024, so half the window cannot
  support a per-compound model. It is also a two versus three stop race.
- *Austria, Circuit of the Americas, Zandvoort.* Austria has almost no soft
  running, at 2, 9 and 74 laps, plus safety car laps every year. At COTA the
  corrected slopes come out at 0.014 to 0.023 s/lap, too weak to separate from
  noise. Zandvoort 2023 was wet, with rain in 23% of weather samples and 13.6%
  non-green laps, and 2025 had 20.3% non-green laps, which leaves one usable race.

**Cost accepted.** The 0.698s gap is not a pure strategy effect. Piastri
finished in Norris's dirty air at a track where passing is hard, so the real gap
mixes strategy with track position. The model predicts a free-air difference,
and the two numbers are compared rather than treated as the same thing.

## 4. Model the medium and hard compounds only

**Decision.** Fit a degradation curve for the medium and the hard. Leave the
soft out.

**Why.** After cleaning, the soft has 9, 19 and 17 clean racing laps in the three
races, 45 in total, across 14 stints none longer than 17 laps. At this circuit
the soft is a qualifying tyre. The medium and hard have about a thousand clean
laps each and cover every strategy actually run in 2025.

**Not chosen.**
- *All three compounds.* A curve fitted to 45 short-stint laps would have
  intervals too wide to support any claim while still looking like a result.
- *One curve for all compounds with a per-compound offset.* This assumes every
  compound degrades at the same rate and differs only in grip, which is the
  assumption the project exists to test.
- *Borrowing soft data from other circuits.* The compound names are allocation
  slots, not fixed rubber. A soft here is a different compound from a soft
  elsewhere.

**Cost accepted.** Compound choice is not random. Teams pick tyres to suit the
car, the track position and the plan, so a coefficient partly reflects how that
tyre was used rather than the tyre alone. This shows up in the fitted result:
the two compounds' degradation rates cannot be told apart. See section 7.

## 5. Which laps go into the fit

**Decision.** Drop pit in-laps and out-laps, lap 1, laps run under safety car or
red flag, and laps within 1.0s of the car ahead.

**Why.** Raw lap times are not a degradation signal. Measured against the median
clean lap of the same driver's own stint in 2023, an out-lap is 18.97s slow, lap
1 is 7.28s slow, and an in-lap is 2.69s slow, on a lap of about 80s. Left in,
those laps drive the curve fit on their own. Safety car laps are run to a
delta, not at racing pace, and a car within a second of the one ahead is showing
the air it is in rather than the state of its tyres. The filters keep 80%, 78%
and 68% of laps in the three races, which is plenty.

One detail worth recording: the track status field concatenates every status
seen during a lap, so a single lap can read 671, meaning virtual safety car
deployed, then ending, then clear. It has to be tested for containing the digits
4, 5, 6 or 7, never compared for equality. Comparing for equality silently keeps
safety car laps.

**Not chosen.**
- *Keep every lap.* An out-lap is 19s off. No sensible error model treats that
  as noise.
- *Use only the fastest few laps of each stint.* This selects on the thing being
  measured. The fastest laps of a stint are its least worn laps, so it removes
  the signal and biases degradation towards zero.
- *Remove statistical outliers by interquartile range.* A purely statistical
  rule cannot tell a pit lap from a genuinely worn tyre, and late-stint laps are
  exactly the ones it would discard.
- *A 2.0s traffic threshold.* Safer against dirty air, but it removes 33.1% of
  green laps in 2023 and 50.8% in 2025, which is half the test race.

**Cost accepted.** The traffic measure is the gap at the timing line, once per
lap, so it misses a car that closed up mid-lap or lost time in one corner
sequence. The traffic filter also costs the most in 2025, where 30.1% of green
laps are within a second against 15.2% in 2023, so the test race is the most
heavily filtered of the three.

**Reproduce.** `python scripts/cleaning_report.py` prints the lap counts,
retained shares, traffic shares and per-compound counts quoted above, for all
three races.

## 6. Estimate the fuel effect instead of assuming it

**Decision.** Estimate the fuel coefficient from the data, and report fits at
fixed values of 0.030, 0.0429 and 0.055 s/lap alongside it as a sensitivity band.

**Why.** A car starts a race about 100kg heavy and gets faster as that burns off,
while the tyre gets slower as it ages. Both effects move with the lap counter.
Fitted on 2023 with no fuel term, the medium comes out at -0.0072 s/lap, meaning
the raw data says the tyre gets faster the longer it is used. That is not a small
bias, it is the wrong sign. The correction also goes into the answer one for one,
so the constant chosen is the result:

| Assumed fuel effect | Resulting hard-tyre degradation |
|---|---|
| none | 0.0248 s/lap |
| 0.0300 s/lap | 0.0575 s/lap |
| 0.0429 s/lap | 0.0715 s/lap |
| 0.0550 s/lap | 0.0847 s/lap |

That is a 3.4 times spread driven entirely by an assumption. Drivers pit on
different laps, so at any given race lap the field covers a range of tyre ages,
and that spread is what lets the data separate a lap-number effect from a
tyre-age effect.

**Not chosen.**
- *Ignore fuel.* Gives a negative degradation slope on the medium.
- *Fix the constant at 0.03 s/lap.* A figure often quoted in commentary, but
  nothing in the data supports it over nearby values, and the choice moves the
  answer by a factor of two. Kept as one end of the band.
- *Fix it at the physical estimate.* About 0.03s per kg of fuel over roughly
  100kg and 70 laps gives 0.0429 s/lap. A good prior and a useful check, but
  still an assumption brought in from outside. Kept as the middle of the band.

**Cost accepted.** Pit timing is strategic rather than random, and cars often
stop early because they are struggling, so the variation used to identify the
fuel effect is not clean. A single linear fuel term also cannot capture the fact
that a heavier car wears its tyres faster, so any such effect is credited to
tyre age instead.

**Reproduce.** `python scripts/fuel_sensitivity.py` prints the slope for every
compound at each assumed fuel effect, including the negative uncorrected medium.
The soft is reported as having too few laps rather than quietly left out.
`python scripts/plot_fuel_correction.py` draws the chart at the top of the
README from the same numbers.

## 7. One curve per compound, pooled across drivers

**Decision.** Fit pooled across the whole field with a separate baseline pace
for each driver. Start with a straight line in tyre age, and test curved and
two-piece forms against held-out races before adding them.

**Why.** Drivers and cars differ in pace by far more than a tyre degrades over a
stint, so that has to be removed first. A per-driver baseline costs about twenty
parameters and does it without touching the slope. Pooling also keeps the
cross-driver spread in pit timing that the fuel estimate depends on.

**Not chosen.**
- *A separate curve per driver.* Degradation really does differ by driver, but
  each driver has only tens of clean laps per compound, so the intervals would be
  too wide to use, and estimating fuel burn inside one driver's stints runs into
  the collinearity that pooling avoids.
- *A per-team slope.* Interesting, and it would show which cars are kind to
  their tyres, but it adds parameters before the simple version has been
  validated. Worth revisiting later.
- *Pooling with no driver baselines.* Already visibly wrong. Fitted raw on 2023,
  the hard comes out degrading faster than the medium, 0.0715 against 0.0530
  s/lap, which is the wrong way round for a harder tyre. The compounds are run
  by different cars at different points in the race, so an uncontrolled slope
  partly measures who was on which tyre and when.

The code keeps this distinction visible. The uncontrolled estimator lives in
`src/tyre_deg/diagnostics.py`, its functions are named "uncontrolled", and the
module docstring says not to quote them as the project's estimate. It exists to
reproduce the evidence in section 6, not to answer the question.

**What the fitted model actually gave.** Driver and race intercepts did not
restore the expected ordering. Fitted on 2023 and 2024, the hard still comes out
steeper than the medium, 0.0784 against 0.0649 s/lap. The difference is 0.0135
s/lap with an interval of -0.0070 to 0.0309, which includes zero, so the honest
reading is that this data cannot tell the two compounds apart, not that the hard
degrades faster. The fuel effect came out at 0.0437 s/lap, and its interval of
0.0395 to 0.0484 contains the physical estimate of 0.0429 that section 6 would
otherwise have assumed. Two independent routes to the same number.

**Reproduce.** `python scripts/fit_model.py`.

**Cost accepted.** A per-driver baseline removes each driver's average pace, not
changes in how they drove during the race. A driver nursing the tyres to make a
one-stop work shows less degradation, and that driving is tied to the very
strategy being judged. This is the hardest confounder here and it cannot be
removed with this data.

## 8. Test on a held-out race, not a random split

**Decision.** Train on 2023 and 2024, choose the model form by cross-validation
grouped by race inside those two, and evaluate the 2025 race once. Get intervals
by resampling whole stints rather than single laps, and carry them through to the
strategy comparison.

**Why.** The model is meant to judge a race it has not seen, so the test has to
work the same way. Laps within a stint share the driver, the car, the tyre set,
the fuel load and the track, so they are strongly correlated. That makes a random
split leak, and it makes ordinary standard errors far too narrow.

**Not chosen.**
- *A random split across laps.* Laps from the same stint end up in both halves,
  so the model is tested on near-copies of its training data. It would report
  excellent accuracy and mean nothing.
- *Cross-validation grouped by driver.* Better, but every fold still shares the
  same race conditions, so it measures how well the model carries over to a new
  driver, not to a new race.
- *Leave one race out across all three.* This puts 2025 into training and
  destroys the held-out status of the Norris and Piastri comparison, which is the
  whole point of it.
- *Ordinary least squares standard errors.* The default, and badly understated
  when laps are serially correlated.

**Comparing two coefficients.** Checking whether two intervals overlap is not a
test of whether two coefficients differ: intervals can overlap while the
difference is clearly non-zero, and the reverse happens too. The difference is
therefore recomputed inside every resample and reported with its own interval.
The same machinery carries the strategy comparison, which is a function of
several coefficients at once.

**Cost accepted.** Two training races means only two cross-validation folds,
which is very little to choose a model form with, and one test race means the
out-of-sample error is a noisy estimate. A single good prediction cannot tell a
good model from a lucky one.

## 9. Cleaning code as a tested library, not a notebook

**Decision.** Put loading and cleaning in `src/tyre_deg/`, with each filter
written as a function that returns a true or false mask per lap, and keep the
scripts in `scripts/` thin. `scripts/cleaning_report.py` regenerates the numbers
in section 5.

The fuel correction in `src/tyre_deg/fuel.py`, the slope diagnostics in
`src/tyre_deg/diagnostics.py` and the model in `src/tyre_deg/model.py` follow
the same pattern: pure functions, tested against lap times built with a known
degradation rate and a known fuel effect so the maths can be checked against an
answer known in advance. The model tests also check that a single stint cannot
separate fuel from tyre age, and that two stints can, which is the property the
whole design rests on.

**Why.** Masks compose, and each one can be tested on its own against a small
hand-built table of laps. Applying them one at a time also lets the pipeline
count how many laps each filter removed, which is what produces the table in
section 5. The 33 tests build their own data, so they need no network access and
no cached sessions and will run on a fresh clone. Running the script reproduces
every lap count in section 5 exactly.

**Not chosen.**
- *Do the cleaning in a notebook.* Fast to write, but the logic cannot be tested
  or reused, and the numbers in this file would not be reproducible.
- *A single function that takes laps and returns cleaned laps.* Simpler to call,
  but it cannot report which filter removed what, and a failing test would not
  say which rule broke.
- *Filters that drop rows instead of returning masks.* Each would have to be
  tested through the whole chain, and the order of filtering would be hidden
  inside them rather than visible in one place.

**Cost accepted.** More files than this task strictly needs, and carrying the
full lap table through every filter instead of shrinking it as it goes. At about
1,300 laps per race, that costs nothing measurable.

## 10. How two strategies are compared

**Decision.** Compare two strategies by the part of race time that depends on
them: tyre wear, the compound baselines and the pit stops. Measure the pit loss
from the races rather than assuming a value. Refuse to simulate a stint longer
than the oldest tyre in the data.

**Why.** Two strategies over the same race carry the same fuel on each lap and
belong to the same driver, so pace and fuel are identical in both and cancel in
the difference. What is left is the tyre and the pit lane, which means the
answer does not depend on how quick the driver was. The pit loss comes out at
19.60 s, measured by comparing every real in lap and out lap against what the
model says those same laps would have taken had the car stayed out on its old
tyres. The median across stops is used so one slow stop cannot drag it. The
interval on the comparison is rebuilt inside the same resampled fits that give
the coefficients their intervals, because the comparison is a function of
several coefficients at once.

**Not chosen.**
- *Simulate full race times.* Needs the driver's absolute pace, which cancels
  anyway, and invites comparing two cars rather than two strategies.
- *Assume a pit loss of about 20 seconds.* The measured value is 19.60 s, so
  the guess would have been close, but there is no reason to guess when the
  races contain the answer.
- *Let the model extrapolate freely.* A straight line will happily price a 60
  lap stint from 30 laps of evidence. The simulator refuses any stint longer
  than the oldest tyre observed for that compound.
- *Bootstrap the pit loss as well.* It would be more complete, but measuring it
  requires predicting every lap of every training race, and doing that inside
  1000 resamples costs far more than the answer is worth. Its effect is reported
  as a sensitivity instead: two seconds on the pit loss moves the comparison by
  about two seconds.

**Cost accepted.** Track position is not modelled, and at this circuit that is
the difference between a faster strategy and a winning one. The held-out test
makes the point: the model puts the 2025 two stop about nine seconds ahead on
pace, and the one stop won the race by 0.698 s. The model answers the narrower
question of which strategy was quicker in clear air. Two other things push the
same way and cannot be separated from this data: a driver committed to a one
stop manages the tyre, and a straight line charges full price for every lap of a
long stint. Both make the one stop look worse than it was.

**Reproduce.** `python scripts/strategy_test.py`.

## 11. Degradation stays a straight line

**Decision.** Keep degradation linear in tyre age. A quadratic and a range of
hinge shapes were tested against held-out races and none earned its place.

**Why.** Section 7 said a curve would be tested rather than assumed. Each shape
was scored by leaving one training race out, fitting on the other and measuring
the error on the race it had not seen. Only the shape is scored, not absolute
pace: the model fits an intercept per driver per race, so it cannot predict a
race it has never seen, and each driver's own mean error inside the held-out
race is removed first. That is also the part that matters, because intercepts
cancel when two strategies are compared.

| Shape | Extra terms per compound | Held-out error |
|---|---|---|
| quadratic | 1 | 0.6812 s |
| hinge at 15 | 1 | 0.6821 s |
| linear | 0 | 0.6824 s |
| hinge at 20 | 1 | 0.6827 s |
| hinge at 10 | 1 | 0.6846 s |
| hinge at 25 | 1 | 0.6876 s |

The best shape beats the straight line by 0.0012 s, which is 0.2% of its error,
and three of the five curved shapes are worse than it. With two training races
there are only two folds, so a gap that small is not evidence of anything.

**Not chosen.**
- *Adopt the quadratic because it scored best.* 0.2% on two folds is noise, and
  it costs a parameter per compound. Picking the winner of a close race between
  six shapes is how a model gets fitted to its own validation set.
- *Choose the shape on the 2025 race.* That would spend the held-out season on
  model selection and the strategy result would no longer be out of sample.
  See section 8.
- *Fit the knee position freely.* Another parameter chosen from the same two
  folds, with the same problem.

**Cost accepted.** The straight line is not exactly right, and its errors show
where it misses. Mean error by tyre age, on the training races:

| Tyre age | Mean error | Laps |
|---|---|---|
| 0 to 4 | +0.061 s | 139 |
| 5 to 9 | +0.081 s | 385 |
| 10 to 14 | +0.079 s | 425 |
| 15 to 19 | -0.028 s | 395 |
| 20 to 24 | -0.130 s | 327 |
| 25 to 29 | -0.111 s | 212 |
| 30 to 34 | -0.057 s | 93 |
| 35 to 39 | +0.167 s | 43 |
| 40 to 44 | +0.180 s | 10 |

That is a wave rather than a simple curve, which is why a quadratic cannot
capture it. Two things are worth saying about the direction. The error at high
tyre age is positive, meaning the straight line predicts lap times faster than
they really were, so it charges too little for a long stint rather than too
much. And the two oldest buckets hold 43 and 10 laps, and only stints that were
going well last that long, so this is weak evidence either way.

**Reproduce.** `python scripts/compare_forms.py`.

## 12. Keeping up with a data source that closed

**Decision.** Pin FastF1 to 3.9.0, read credentials from the environment, and
fail with a message naming the cause when a race cannot be loaded.

**Why.** Formula 1 put its timing archive behind a login in late 2026. The
endpoint this project had been reading now answers with HTTP 401, and FastF1
3.8.3, the version pinned until now, has no way to sign in. On that version the
project could no longer fetch a single new race.

FastF1 3.9.0 can sign in with a free F1 account using the F1_USERNAME and
F1_PASSWORD environment variables. Before pinning it, every published number was
regenerated from the existing cache under 3.9.0 and all of them matched exactly,
so the upgrade changes nothing about the results.

The failure mode mattered as much as the fix. FastF1 logs a warning and carries
on when a download fails, so the first thing to touch the laps raised an error
with no connection to the real cause. Loading now checks that laps arrived and
raises one message explaining that the archive needs an account.

**Not chosen.**
- *Stay on 3.8.3.* The cache still works, so the analysis would still run, but
  nobody could ever add a race. A pinned version that cannot fetch data is a
  dead end.
- *Commit the cache so the data is always there.* It is 163 MB of someone else's
  data, and a repository is not a data store.
- *Store credentials in the repository.* Never. They stay in the environment,
  and `.env` is ignored.

**Cost accepted.** Reproducing this project from scratch now depends on a free
account with a third party that has already changed the rules once. Anyone with
the cache is unaffected, and the tests never needed the data at all: they build
their own lap times, so they pass on a fresh clone with no account, no network
and no cache.

## 13. Serving the results to an agent

**Decision.** Precompute every model output into `data/model_outputs.json`, commit
that file, and have an MCP server read it. The server never imports FastF1 and
never fits anything.

**Why.** A tool call should be a lookup. Fitting the model takes about fifteen
seconds and needs the FastF1 cache; doing that inside a tool call would make the
server slow and would tie it to data that now sits behind a Formula 1 login.
Precomputing also makes the server's answers reproducible: they are whatever was
in the file, and the file records the seed, the number of resamples and the
thresholds used.

The file is committed, which is the one place this project keeps derived data in
git. The reason is the same login: without the file in the repository, nobody
could run the server from a fresh clone. It is 196 KB.

It carries the 1000 bootstrap fits, not only the summary intervals. That is what
lets the server put an interval on a strategy comparison for any pair of
drivers: the difference is recomputed inside every resample, which is the same
reasoning as section 8, done offline in plain arithmetic.

Degradation is fitted per race as well as pooled. A tool answering "how fast did
the medium degrade at the 2023 race" should give that race's number, and a
per-race fit works on all three with no failed resamples. The pooled training
fit is kept separately and is what the strategy comparison uses, because that is
the one validated against a held-out race.

**Not chosen.**
- *Fit on demand inside the tool.* Slow, and it would need the cache and an
  account, so the server would not run for anyone else.
- *Keep the file out of git, as with every other derived artefact.* Consistent,
  but it would make the server unusable from a clone, which defeats the point.
- *Store only the summary intervals.* Smaller, but then any comparison the
  server had not precomputed could only be given as a point estimate, and the
  project's own rule is that a number without an interval is not a result.
- *Let the tools return error messages as text.* An error returned as a string
  is reported as a successful call, so a model treats the message as the answer.
  The tools raise instead, which flags the call as failed while still showing
  the model what went wrong.

**Cost accepted.** The committed file can fall out of step with the code. It is
rebuilt with one command, and a test asserts the published figures still hold,
so drift shows up as a failing test rather than a quietly wrong answer. The
server is also a second thing to keep working: it adds seventeen packages to the
environment, four of which are a web stack the stdio transport never uses.

**Reproduce.** `python -m mcp_server.precompute`, then `pytest tests/test_mcp_server.py`.

## 14. Comparing two degradation rates

**Decision.** Add a tool that returns the difference between two degradation
rates with its own confidence interval, and store each race's bootstrap fits so
it can. It compares any two rates: two compounds in one race, or the same
compound in two races.

**Why.** Section 8 says that checking whether two intervals overlap is not a
test of whether two coefficients differ, and section 7 applies that to the two
compounds. The server could state that caution but could not act on it: a
caller could fetch two rates and was left to eyeball them, which is exactly the
mistake the rest of the project avoids.

The numbers show why it matters. The medium comes out at 0.0564 s/lap in 2023
and 0.0755 in 2024, which looks like a real change. The difference is
+0.0191 s/lap with an interval of -0.0125 to 0.0469, so it is not. Within 2023,
hard minus medium is +0.0110 with an interval of -0.0090 to 0.0326, agreeing
with the pooled fit in section 7.

Which draws are paired matters. Two compounds in one race come from the same
fit, so the nth draw of each must be used together to keep their correlation.
Two races are separate fits and independent, so pairing by position is just one
valid way of drawing from both. The tool says which case it is in its answer.

**Not chosen.**
- *Let the caller compare two separate results.* That is the error the tool
  exists to prevent.
- *Store only summary intervals per race.* Then no difference could be given an
  interval, and the comparison would be a point estimate, which the project
  treats as not a result.
- *Compute differences in the precompute step for every pair.* Three races and
  three compounds give far more pairs than anyone will ask for, and the file
  would grow for no benefit. Carrying the draws covers every pair at a tenth of
  the size.

**Cost accepted.** The results file grew from 200 KB to 284 KB, because it now
carries 1000 degradation draws per compound per race. Comparisons also remain
within one circuit: nothing here compares a tyre at the Hungaroring with the
same tyre anywhere else, and the compound names would not mean the same thing
if it did.

**Reproduce.** `python -m mcp_server.precompute`, then
`pytest tests/test_mcp_server.py`.
