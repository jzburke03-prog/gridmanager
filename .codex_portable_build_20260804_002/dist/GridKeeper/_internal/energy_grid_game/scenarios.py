"""Run configuration: regions, difficulty tiers, historical scenarios, and the
RunConfig object that seeds a GameState.

A RunConfig fully describes one playable grid:
  * which capacities each spigot has,
  * where each spigot starts,
  * the demand shape over the day (real EIA data or a synthetic seasonal curve),
  * solar/wind availability over the day (real or synthetic),
  * the difficulty band that governs scoring and blackout/meltdown.

Three ways to build one:
  make_standard(...)  - the original national-average 1000 MW grid,
  make_region(...)    - a real region + date, seeded from EIA data,
  make_scenario(...)  - a curated historical grid-stress event.
"""
import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

import eia
import noaa
from sources.generic import GENERIC_MAX_MW

SOURCE_KEYS = ["nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro"]
DAY_START_HOUR = 4  # the sim day begins at 04:00, so seed from that data hour

# Instructional Mode: which sources the player has on each day (SPEC-1.1 §3.2).
# Cumulative by construction — each day's set is the whole fleet available that
# day, not the delta — so GameState can gate straight off it without bookkeeping.
INSTRUCTIONAL_UNLOCKS = {
    1: ["generic"],
    2: ["gas", "peaker"],
    3: ["gas", "peaker", "coal", "nuclear"],
    4: ["gas", "peaker", "coal", "nuclear", "solar", "wind", "hydro"],
}
INSTRUCTIONAL_FINAL_DAY = max(INSTRUCTIONAL_UNLOCKS)

# Per-day capacities. Days 1-3 each hand the player the same 1500 MW, just
# split across more plants as the fleet is revealed, so the total available
# never changes underneath them while they are still learning to balance.
# Day 4 is filled in below with the real Standard fleet — the grid they
# graduate into — once STANDARD_CAPACITIES exists.
INSTRUCTIONAL_CAPACITIES = {
    1: {"generic": 1500.0},
    2: {"gas": 1400.0, "peaker": 100.0},
    3: {"nuclear": 200.0, "coal": 300.0, "gas": 900.0, "peaker": 100.0},
}

# Days 1-3 run without weather: an unexplained heat wave while the player is
# still learning what a demand curve is reads as noise, not as teaching. Day 4 is
# where intermittency IS the lesson, so events come on with the renewables.
INSTRUCTIONAL_EVENTS_FROM_DAY = 4


# --------------------------------------------------------------------------
# Regions (EIA balancing-authority respondents)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Region:
    code: str          # EIA respondent code, e.g. "ERCO"
    label: str         # display name
    blurb: str         # one-line character note


REGIONS = [
    Region("ERCO", "ERCOT (Texas)", "Islanded grid, gas-heavy, booming wind"),
    Region("CAL", "California (CISO)", "Massive solar, steep evening duck curve"),
    Region("NYIS", "New York (NYISO)", "Hydro + nuclear north, dense demand south"),
    Region("PJM", "PJM (Mid-Atlantic)", "Largest US market, coal + gas + nuclear"),
    Region("MISO", "MISO (Midwest)", "Wind belt, long coal fleet"),
    Region("ISNE", "ISO New England", "Gas-dependent, tight winter margins"),
    Region("SWPP", "SPP (Great Plains)", "Wind-record grid, thin firm capacity"),
]
REGION_BY_CODE = {r.code: r for r in REGIONS}


# --------------------------------------------------------------------------
# Difficulty tiers
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Difficulty:
    name: str
    ideal_low: float     # supply/demand ratio band that scores positively
    ideal_high: float
    blackout: float      # sustained below this -> blackout game over
    meltdown: float      # sustained above this -> meltdown game over
    danger_grace: float  # seconds past a hard threshold before it ends the run
    penalty_scale: float # multiplies out-of-band score bleed
    blurb: str


DIFFICULTIES = {
    "easy": Difficulty("Easy", 0.78, 1.22, 0.30, 2.10, 6.0, 0.8,
                       "Wide margins. Lots of room to react."),
    "moderate": Difficulty("Moderate", 0.87, 1.13, 0.40, 1.75, 4.0, 1.0,
                           "A fair balance. The standard grid day."),
    "hard": Difficulty("Hard", 0.92, 1.09, 0.52, 1.40, 2.5, 1.4,
                       "Tight band. Drift is punished quickly."),
    "expert": Difficulty("Expert", 0.95, 1.06, 0.60, 1.15, 2.0, 1.9,
                         "Razor margins. Sit past 110% and you'll trip the grid."),
}
DIFFICULTY_ORDER = ["easy", "moderate", "hard", "expert"]


# --------------------------------------------------------------------------
# National-average "Standard" grid (no region selected)
# --------------------------------------------------------------------------
STANDARD_DEMAND_PEAK_MW = 1000.0
STANDARD_DEMAND_MIN_MW = 430.0

# Rough national capacity mix scaled to a ~1000 MW-peak grid, 1750 MW total
# (SPEC-1.1 §2.1). Sized so _ensure_playable never has to fire: firm capacity is
# 1350 MW against a worst-case (July) requirement of 1160 * 1.15 = 1334 MW, so
# the table below is exactly what a Standard run loads.
#
# That clears by only 16 MW. Raise the July _SEASON multiplier past ~1.17, raise
# the 1.15 headroom in _ensure_playable, or cut firm capacity, and it starts
# silently padding gas again — at which point these numbers stop being true.
# test_capacities.py guards the margin.
STANDARD_CAPACITIES = {
    "nuclear": 150.0, "coal": 250.0, "gas": 750.0, "peaker": 50.0,
    "solar": 175.0, "wind": 225.0, "hydro": 150.0,
}

# Seasonal shaping for the synthetic Standard grid (no real data to lean on).
# (demand multiplier, solar multiplier) by month.
_SEASON = {
    12: (1.12, 0.55), 1: (1.14, 0.52), 2: (1.10, 0.60),   # winter: heating load, weak sun
    3: (0.96, 0.85), 4: (0.94, 0.95), 5: (0.97, 1.02),    # spring
    6: (1.10, 1.08), 7: (1.16, 1.10), 8: (1.15, 1.06),    # summer: AC load, strong sun
    9: (1.00, 0.92), 10: (0.95, 0.82), 11: (0.99, 0.68),  # fall
}

# Instructional day 4 graduates onto the real Standard fleet, so the grid the
# player finishes on is the grid free play hands them.
INSTRUCTIONAL_CAPACITIES[INSTRUCTIONAL_FINAL_DAY] = dict(STANDARD_CAPACITIES)

_DISPATCHABLE = ["nuclear", "coal", "gas", "peaker", "hydro"]


def _ensure_playable(caps: dict, demand_peak: float) -> dict:
    """Guarantee the player can physically meet peak demand from firm
    (dispatchable) capacity alone — renewables are a bonus, never a requirement.
    Any shortfall is added to gas (the swing plant, and the real-world stand-in
    for the imports the game has no model for)."""
    caps = dict(caps)
    firm = sum(caps.get(k, 0.0) for k in _DISPATCHABLE)
    needed = demand_peak * 1.15
    if firm < needed:
        caps["gas"] = caps.get("gas", 0.0) + (needed - firm)
    return caps


# --------------------------------------------------------------------------
# RunConfig
# --------------------------------------------------------------------------
@dataclass
class RunConfig:
    mode: str                       # "standard" | "region" | "scenario" | "instructional"
    label: str
    date: _dt.date
    difficulty: Difficulty
    demand_peak_mw: float
    demand_min_mw: float
    capacities: dict                # source_key -> max MW
    start_mix: dict                 # source_key -> starting fraction 0..1
    region_code: Optional[str] = None
    demand_hourly: Optional[list] = None   # 24 normalized 0..1, or None -> synthetic
    solar_hourly: Optional[list] = None    # 24 availability 0..1, or None -> synthetic
    wind_hourly: Optional[list] = None
    season_solar_scale: float = 1.0        # synthetic-solar multiplier (Standard)
    intro: Optional[str] = None
    data_source: str = "synthetic"         # "api" | "cache" | "synthetic"
    # Real historical weather (NOAA, scenario mode). None -> synthetic seasonal.
    temps_hourly: Optional[list] = None    # 24 ambient temps, °F
    forced_event_kinds: Optional[list] = None  # event kinds the real day favors
    weather_source: str = "synthetic"      # "noaa" | "cache" | "synthetic"
    events_enabled: bool = True            # title-screen toggle: random events on/off
    # Instructional Mode only: day -> source keys available that day. None means
    # every source is available from the start, which is every other mode.
    unlocks: Optional[dict] = None
    # Instructional Mode only: day -> {source_key: max MW} for that day.
    day_capacities: Optional[dict] = None

    @property
    def date_label(self) -> str:
        return self.date.strftime("%d %b %Y")

    @property
    def is_instructional(self) -> bool:
        return self.mode == "instructional"

    def sources_for_day(self, day: int):
        """Source keys the player can see and touch on `day`. Past the last
        scripted day the whole fleet stays unlocked."""
        if not self.unlocks:
            return None            # no gating
        if day in self.unlocks:
            return self.unlocks[day]
        return self.unlocks[max(self.unlocks)]

    def capacities_for_day(self, day: int):
        """Per-day capacities, or None when the run uses one fixed fleet."""
        if not self.day_capacities:
            return None
        if day in self.day_capacities:
            return self.day_capacities[day]
        return self.day_capacities[max(self.day_capacities)]


def make_standard(date: Optional[_dt.date] = None, difficulty_key: str = "moderate") -> RunConfig:
    date = date or _dt.date.today()
    diff = DIFFICULTIES[difficulty_key]
    dmul, smul = _SEASON.get(date.month, (1.0, 1.0))
    peak = STANDARD_DEMAND_PEAK_MW * dmul
    dmin = STANDARD_DEMAND_MIN_MW * dmul
    caps = _ensure_playable(STANDARD_CAPACITIES, peak)
    start_mix = {
        "nuclear": 0.5, "coal": 0.5, "gas": 0.15, "peaker": 0.0,
        "solar": 1.0, "wind": 1.0, "hydro": 0.0,
    }
    return RunConfig(
        mode="standard", label="Standard Grid", date=date, difficulty=diff,
        demand_peak_mw=peak, demand_min_mw=dmin, capacities=caps,
        start_mix=start_mix, season_solar_scale=smul, data_source="synthetic",
    )


def make_instructional(date: Optional[_dt.date] = None) -> RunConfig:
    """The four-day guided grid (SPEC-1.1 §3).

    Standard's capacities and demand curve, on Easy, with the fleet revealed a
    day at a time. Everything starts shut: Day 1 is a single generic valve at
    zero, and each later day's new plants arrive off so the player opens them
    deliberately rather than inheriting a running grid they didn't build.
    """
    date = date or _dt.date.today()
    dmul, smul = _SEASON.get(date.month, (1.0, 1.0))
    # Union of every day's fleet, so each source exists from the start; the
    # per-day table below is what actually sets its capacity each morning.
    caps = dict(STANDARD_CAPACITIES)
    caps["generic"] = GENERIC_MAX_MW
    return RunConfig(
        mode="instructional", label="Instructional", date=date,
        difficulty=DIFFICULTIES["easy"],
        demand_peak_mw=STANDARD_DEMAND_PEAK_MW * dmul,
        demand_min_mw=STANDARD_DEMAND_MIN_MW * dmul,
        capacities=caps,
        start_mix={k: 0.0 for k in SOURCE_KEYS + ["generic"]},
        season_solar_scale=smul, data_source="synthetic",
        events_enabled=False,          # per-day; see INSTRUCTIONAL_EVENTS_FROM_DAY
        unlocks=INSTRUCTIONAL_UNLOCKS,
        day_capacities=INSTRUCTIONAL_CAPACITIES,
    )


def _build_from_eia(eia_day, difficulty, label, region_code, date, intro, mode):
    """Turn a fetched EIA day into a fully-seeded RunConfig."""
    demand_mw = eia_day["demand_hourly"]
    fuel = eia_day["fuel_hourly"]
    peak = max(demand_mw)
    dmin = min(demand_mw)
    span = max(1.0, peak - dmin)
    demand_norm = [max(0.0, min(1.0, (d - dmin) / span)) for d in demand_mw]

    # capacities: observed peak generation scaled down for game capacity, with
    # per-source floors. A source's daily peak generation is not the same thing
    # as nameplate supply available to the player, so real-data fleets use half
    # the observed source peak before the playability guard adds any needed
    # firm reserve.
    floors = {"nuclear": 0.05, "coal": 0.05, "gas": 0.40,
              "hydro": 0.03, "wind": 0.05, "solar": 0.05}
    caps = {}
    for key in ("nuclear", "coal", "gas", "hydro", "wind", "solar"):
        arr = fuel.get(key)
        observed = max(arr) if arr else 0.0
        caps[key] = max(observed * 0.5, floors[key] * peak)
    caps["peaker"] = max(20.0, peak * 0.05)
    caps = _ensure_playable(caps, peak)

    # starting mix: dispatchables seeded from their real output at the start
    # hour; peaker off; renewables opened wide (their availability curve caps
    # them to the real generation shape anyway)
    h = DAY_START_HOUR
    start_mix = {}
    for key in ("nuclear", "coal", "gas", "hydro"):
        arr = fuel.get(key)
        gen = arr[h] if arr else 0.0
        start_mix[key] = max(0.0, min(1.0, gen / caps[key])) if caps[key] > 0 else 0.0
    start_mix["peaker"] = 0.0
    start_mix["solar"] = 1.0
    start_mix["wind"] = 1.0

    # renewable availability curves straight from the real generation shape
    def _avail(key):
        arr = fuel.get(key)
        if not arr or caps[key] <= 0:
            return None
        return [max(0.0, min(1.0, v / caps[key])) for v in arr]

    return RunConfig(
        mode=mode, label=label, date=date, difficulty=difficulty,
        demand_peak_mw=peak, demand_min_mw=dmin, capacities=caps,
        start_mix=start_mix, region_code=region_code,
        demand_hourly=demand_norm, solar_hourly=_avail("solar"),
        wind_hourly=_avail("wind"), intro=intro,
        data_source=eia_day.get("source", "api"),
    )


def make_region(region: Region, date: _dt.date, difficulty_key: str = "moderate") -> RunConfig:
    """Free-play a real region on a real date. Fetches EIA data; on any failure
    falls back to the synthetic Standard curves (still labeled for the region)."""
    diff = DIFFICULTIES[difficulty_key]
    eia_day = eia.fetch_region_day(region.code, date)
    label = f"{region.label} — {date.strftime('%d %b %Y')}"
    if eia_day:
        return _build_from_eia(eia_day, diff, label, region.code, date, None, "region")
    # offline / no-data fallback
    cfg = make_standard(date, difficulty_key)
    cfg.mode = "region"
    cfg.region_code = region.code
    cfg.label = label + "  (offline data)"
    cfg.data_source = "synthetic"
    return cfg


# --------------------------------------------------------------------------
# Historical scenarios
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    region_code: str
    date: _dt.date
    difficulty_key: str
    subtitle: str
    intro: str


SCENARIOS = [
    Scenario(
        "uri", "Winter Storm Uri", "ERCO", _dt.date(2021, 2, 15), "expert",
        "ERCOT — 15 Feb 2021",
        "A historic Arctic blast drives Texas demand to an all-time winter peak "
        "while gas wellheads and plants freeze offline. ERCOT was minutes from a "
        "months-long total collapse. Keep the lights on as firm capacity crumbles.",
    ),
    Scenario(
        "ca_heat_2020", "California Heat Wave", "CAL", _dt.date(2020, 8, 14), "hard",
        "CAISO — 14 Aug 2020",
        "A record West-wide heat wave spikes evening demand just as the enormous "
        "solar fleet drops off at sunset — the duck curve at its most brutal. "
        "CAISO ordered its first rolling blackouts since 2001.",
    ),
    Scenario(
        "elliott", "Winter Storm Elliott", "PJM", _dt.date(2022, 12, 24), "hard",
        "PJM — 24 Dec 2022",
        "A Christmas-Eve flash freeze forces the largest US grid into emergency "
        "operations as gas and coal units trip on the cold and demand rockets. "
        "PJM issued its first-ever max-generation emergency.",
    ),
    Scenario(
        "spp_2021", "Great Plains Deep Freeze", "SWPP", _dt.date(2021, 2, 15), "expert",
        "SPP — 15 Feb 2021",
        "The same February 2021 cold snap that broke Texas forces SPP into rolling "
        "blackouts across the wind belt — with turbines iced and demand soaring, "
        "thin firm capacity leaves almost no room for error.",
    ),
    Scenario(
        "ne_cold_2018", "New England Cold Snap", "ISNE", _dt.date(2018, 1, 5), "hard",
        "ISO-NE — 5 Jan 2018",
        "A prolonged deep freeze during the 'bomb cyclone' pushes gas-dependent New "
        "England to burn oil for a large share of its power as pipeline gas runs "
        "scarce. Hold the winter peak on a fuel-starved grid.",
    ),
]
SCENARIO_BY_ID = {s.id: s for s in SCENARIOS}


def make_scenario(scenario: Scenario) -> RunConfig:
    """Build a scenario run. Fetches its historical EIA day; on failure falls
    back to a difficulty-matched synthetic grid so the scenario is still
    playable offline. Also seeds real NOAA weather for the date when
    available (needs a NOAA_TOKEN or a warm cache; otherwise the run keeps
    its synthetic seasonal weather)."""
    diff = DIFFICULTIES[scenario.difficulty_key]
    eia_day = eia.fetch_region_day(scenario.region_code, scenario.date)
    if eia_day:
        cfg = _build_from_eia(eia_day, diff, scenario.title, scenario.region_code,
                              scenario.date, scenario.intro, "scenario")
    else:
        cfg = make_standard(scenario.date, scenario.difficulty_key)
        cfg.mode = "scenario"
        cfg.region_code = scenario.region_code
        cfg.label = scenario.title + "  (offline data)"
        cfg.intro = scenario.intro

    weather = noaa.fetch_weather_day(scenario.region_code, scenario.date)
    if weather:
        cfg.temps_hourly = noaa.hourly_temps_f(weather["tmax_f"], weather["tmin_f"])
        cfg.forced_event_kinds = noaa.derive_event_kinds(
            weather["tmax_f"], weather["tmin_f"],
            weather["prcp_in"], weather["snow_in"])
        cfg.weather_source = weather["source"]
    return cfg
