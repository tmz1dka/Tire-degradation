"""Project constants.

Every value here traces to a numbered section in docs/decisions.md. The section
is named next to each constant so a reader can find the reasoning rather than
guessing at a magic number.
"""

from pathlib import Path

# FastF1 writes raw session data here and this project only ever reads it back.
CACHE_DIR = Path("cache")

# Decision 3: the Hungaroring is the pilot circuit, 2023 the pilot race.
PILOT_CIRCUIT = "Hungary"
PILOT_SEASON = 2023

# Decision 2: 2022 and 2026 sit across regulation changes, so the modelling
# window is 2023-2025. Other seasons still load, for reproducing that evidence.
MODELLING_SEASONS: tuple[int, ...] = (2023, 2024, 2025)

# Decision 8: train on these, evaluate the test season exactly once.
TRAIN_SEASONS: tuple[int, ...] = (2023, 2024)
TEST_SEASON = 2025

# Decision 4: the soft has 45 clean laps across three races, too few to fit.
MODELLED_COMPOUNDS: tuple[str, ...] = ("MEDIUM", "HARD")

# Decision 5: a lap within this gap of the car ahead is showing dirty air rather
# than tyre state. A judgement call, so results are reported against a range.
TRAFFIC_GAP_THRESHOLD_S = 1.0
TRAFFIC_GAP_SENSITIVITY_S: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0)

# Decision 5: FastF1's TrackStatus concatenates every status seen during a lap,
# so these digits are tested for membership, never compared for equality.
# 4 = safety car, 5 = red flag, 6 = virtual safety car, 7 = VSC ending.
NON_GREEN_STATUS_DIGITS = "4567"

# Decision 4: a compound needs at least this many clean laps before a slope is
# worth quoting. The soft has 9 to 19 clean laps per race at the Hungaroring and
# falls below this, which is why it is not modelled.
MIN_LAPS_FOR_SLOPE = 40

# Decision 6: fuel mass burned over a race and the lap time cost per kilogram.
# Both are physical estimates taken from outside the data, used only as the
# centre of a sensitivity band. The fitted model estimates this effect instead.
RACE_FUEL_MASS_KG = 100.0
FUEL_SECONDS_PER_KG = 0.03
# Outer values of the sensitivity band only. The central value is the
# physical estimate, computed by fuel.physical_fuel_effect from the two
# constants above, so it is not repeated here.
FUEL_SENSITIVITY_S_PER_LAP: tuple[float, ...] = (0.030, 0.055)
