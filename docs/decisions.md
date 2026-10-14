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
tyre was used rather than the tyre alone.

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

**Cost accepted.** Two training races means only two cross-validation folds,
which is very little to choose a model form with, and one test race means the
out-of-sample error is a noisy estimate. A single good prediction cannot tell a
good model from a lucky one.
