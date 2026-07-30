"""Checks for the city view's illumination model (SPEC-1.1 §1.4, §1.5).

Pure functions only — no display needed. Run: python test_city_model.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from ui.city_grid import (AWAKE_MIN, CityGrid, lit_fraction, overload_level,
                          traffic_level)
from ui.time_of_day import daylight


def test_lit_fraction():
    # Perfect supply at the trough still leaves most of the city dark: 4 AM has
    # to read as 4 AM, not as a failure.
    assert lit_fraction(0.0, 1.0) == AWAKE_MIN
    # Perfect supply at peak lights everything.
    assert lit_fraction(1.0, 1.0) == 1.0
    # No supply is a blackout at any hour.
    assert lit_fraction(0.0, 0.0) == 0.0
    assert lit_fraction(1.0, 0.0) == 0.0

    # The core asymmetry: the SAME deficit darkens far less of the city at the
    # trough than at the peak. This is the whole lesson of the visualization.
    trough_loss = lit_fraction(0.0, 1.0) - lit_fraction(0.0, 0.5)
    peak_loss = lit_fraction(1.0, 1.0) - lit_fraction(1.0, 0.5)
    assert peak_loss > trough_loss * 3

    # Oversupply must not light more than the whole city.
    assert lit_fraction(1.0, 2.5) == 1.0
    # Monotonic in both inputs.
    assert lit_fraction(0.3, 0.8) < lit_fraction(0.6, 0.8)
    assert lit_fraction(0.6, 0.4) < lit_fraction(0.6, 0.9)


def test_overload_level():
    # Balanced or short: the city is never on fire for being under-supplied.
    assert overload_level(1.0, 1.75) == 0.0
    assert overload_level(0.4, 1.75) == 0.0

    # 1.0 lands exactly on the meltdown line, whatever the difficulty, so the
    # visual peak and the run-ending condition always coincide.
    for meltdown in (1.15, 1.40, 1.75, 2.10):
        assert overload_level(meltdown, meltdown) == 1.0
        assert overload_level(meltdown + 0.5, meltdown) == 1.0  # clamped

    # Same supply ratio, different tiers -> different severity. A fixed 150%
    # threshold would be catastrophic on Easy and already too late on Expert.
    expert = overload_level(1.5, 1.15)
    easy = overload_level(1.5, 2.10)
    assert expert == 1.0
    assert easy < 0.5

    # Fires (>0.55 per _draw_overload) begin near 150% on Moderate, as specced.
    assert 0.5 < overload_level(1.5, 1.75) < 0.8


def test_traffic_level():
    """Traffic follows the clock, not the grid — cars don't run on electricity."""
    # Roads are never completely still, even in a total blackout.
    assert traffic_level(3.0, served=0.0) > 0.0

    # Twin rush hours are the busiest moments of the day.
    morning, evening = traffic_level(9.0), traffic_level(17.0)
    midday, night = traffic_level(13.0), traffic_level(3.0)
    assert morning > midday and evening > midday
    assert midday > 0.6, "midday should stay busy, not just the peaks"

    # Precipitous fall after 23:00 into a deep small-hours trough.
    assert traffic_level(22.0) > traffic_level(23.0) > traffic_level(0.5)
    assert night < 0.12
    assert traffic_level(3.0) < traffic_level(6.5) < traffic_level(8.0)

    # Continuous across the midnight wrap — no discontinuity at the seam.
    assert abs(traffic_level(23.99) - traffic_level(0.01)) < 0.02

    # A shed grid damps activity but never kills it.
    assert traffic_level(9.0, served=0.0) < traffic_level(9.0, served=1.0)
    assert traffic_level(9.0, served=0.0) > 0.0


def test_lit_fraction_actually_lights_that_fraction():
    """lit_fraction is only meaningful if `priority < lit_frac` really lights
    that share of the city. Block priority is built from a core-distance score
    that is heavily clustered, so it has to be rank-normalised — without that,
    a nominal 15% lit came out at roughly 1% and the 04:00 city was black.
    """
    city = CityGrid(None)
    # Priority is rank-normalised across EVERYTHING that lights — major road
    # segments and neighbourhoods together — because that combined population is
    # what the player sees illuminate.
    lightable = list(city.segments) + list(city.hoods)
    n = len(lightable)
    for frac in (0.15, 0.25, 0.5, 0.75, 1.0):
        lit = sum(1 for o in lightable if o.priority < frac)
        assert abs(lit / n - frac) < 0.02, f"{frac}: lit {lit}/{n}"

    # Lighting order must still run core-outward: what is lit at the trough
    # should sit nearer downtown than the network as a whole.
    def centre_dist(o):
        mx, my = o.mid if hasattr(o, "mid") else o.pos
        return abs(mx - 0.5) + abs(my - 0.5)

    first_lit = [o for o in lightable if o.priority < AWAKE_MIN]
    assert first_lit, "trough must light something"
    assert (sum(map(centre_dist, first_lit)) / len(first_lit)
            < sum(map(centre_dist, lightable)) / n)

    # Highways must outlast neighbourhood streets in a brownout — the trunks
    # feeding an area should not go dark before the area they feed.
    highway = [s.priority for s in city.segments if s.width >= 3.0]
    hoods = [h.priority for h in city.hoods]
    assert highway and hoods
    assert sum(highway) / len(highway) < sum(hoods) / len(hoods)

    # The renderer breaks out of both loops on the first unlit item, so both
    # lists must be sorted by priority or it would stop early and lose lights.
    for seq in (city.segments, city.hoods):
        assert all(a.priority <= b.priority for a, b in zip(seq, seq[1:]))


def test_time_of_day_never_strands_outlying_towns():
    """Night must dim the whole metro, not shrink it to downtown.

    Brightness (time of day) and reach (supply) are separate inputs. When they
    were multiplied into one number, an outlying town sat at high priority and
    stayed completely dark at 04:00 even on a perfectly supplied grid — a town
    that exists does not stop existing because it is late.
    """
    from ui.city_grid import activity_level, served_fraction

    # Fully supplied: every neighbourhood is energised at every hour.
    assert served_fraction(1.0) == 1.0
    city = CityGrid(None)
    assert all(h.priority < served_fraction(1.0) for h in city.hoods)

    # ...and still carries light at the trough, just less of it.
    assert activity_level(0.0) > 0.0
    assert activity_level(0.0) < activity_level(0.5) < activity_level(1.0)

    # Shortage is what sheds load, and it sheds the fringe before the core.
    shed = [h for h in city.hoods if h.priority >= served_fraction(0.5)]
    kept = [h for h in city.hoods if h.priority < served_fraction(0.5)]
    assert shed and kept

    def centre_dist(h):
        return abs(h.pos[0] - 0.5) + abs(h.pos[1] - 0.5)

    assert (sum(map(centre_dist, kept)) / len(kept)
            < sum(map(centre_dist, shed)) / len(shed))

    # Every town has a core that stays livelier than its own outskirts.
    assert any(h.core_weight > 0.5 for h in city.hoods)
    outlying_cores = [h for h in city.hoods
                      if h.core_weight > 0.5 and centre_dist(h) > 0.3]
    assert outlying_cores, "satellite towns need their own downtowns"


def test_daylight():
    # Sun elevation, shared with the sky so the two can't disagree.
    assert daylight(3.0) == 0.0      # night
    assert daylight(22.0) == 0.0
    assert daylight(12.0) > 0.85     # near solar noon
    assert daylight(3.0) < daylight(8.0) < daylight(12.0)
    # Dawn is a bright warm sky but the sun is barely up: colour luminance would
    # read 05:00 as nearly midday, sun position correctly reads it as ~zero.
    assert daylight(5.0) < 0.05


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall city model checks passed")
