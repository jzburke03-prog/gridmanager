"""Central state: time-of-day, demand level, fill level, score, grid events."""
import json
import os
import random

from demand_curve import demand_at_hour
from physics.water_sim import track_fill
from pricing import EVENT_SCARCITY_MULTIPLIER
from sources.base_source import SourceStatus
from sources.nuclear import NuclearSource
from sources.coal import CoalSource
from sources.natural_gas import GasSource
from sources.solar import SolarSource
from sources.wind import WindSource
from sources.hydro import HydroSource

WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900
FPS = 60
GAME_DAY_REAL_SECONDS = 120       # How long 1 in-game day lasts
MAX_BOX_HEIGHT_PX = 300
MIN_BOX_HEIGHT_PX = 100
MAX_BOX_FOOTPRINT_PX = 300
MIN_BOX_FOOTPRINT_PX = 130
BOX_LERP_SPEED = 0.06             # per-second smoothing factor
WATER_LERP_SPEED = 1.2            # per-second smoothing factor
TOTAL_GRID_CAPACITY_MW = 1725      # sum of all max source outputs

DEMAND_MIN_MW = 370.0
DEMAND_PEAK_MW = 1400.0
FILL_TRACK_SPEED = 2.0              # per-second smoothing toward the LIVE supply/demand ratio
MAX_FILL_PCT = 2.0                  # headroom above 100% so overflow can keep visibly escalating
BLACKOUT_THRESHOLD = 0.40
STARTUP_GRACE = 3.0                 # seconds before a fresh game can blackout/meltdown —
                                     # fill_pct starts below BLACKOUT_THRESHOLD and needs
                                     # time to track toward the real supply/demand ratio
SEVERE_LOW_THRESHOLD = 0.75         # below this (-25% of demand): dramatic "the city is dying" escalation
SEVERE_HIGH_THRESHOLD = 1.25        # above this (+25% of demand): dramatic "grid is melting down" escalation

HOUSEHOLDS_PER_MW = 1000            # 1000 MW ~ 1,000,000 households

SPEED_STEPS = [0.25, 0.5, 1.0, 2.0, 4.0, 8.0]

HIGHSCORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "highscore.json")

# Random grid events (spec 7.4). Cooldown window between spawns keeps them
# occasional rather than constant chaos.
EVENT_MIN_GAP = 25.0
EVENT_MAX_GAP = 55.0
GRACE_PERIOD = 30.0                # no events during the opening moments of a session


class GridEvent:
    """An active disturbance: applies its effect while remaining > 0, then reverts."""

    def __init__(self, name, kind, duration, demand_multiplier=1.0,
                 solar_override=None, wind_override=None, hydro_boost=1.0,
                 maintenance_target=None):
        self.name = name
        self.kind = kind  # stable tag for UI/pricing dispatch: HEAT_WAVE, CLOUD_COVER, WIND_GUST, RAIN, MAINTENANCE
        self.duration = duration
        self.remaining = duration
        self.demand_multiplier = demand_multiplier
        self.solar_override = solar_override
        self.wind_override = wind_override
        self.hydro_boost = hydro_boost
        self.maintenance_target = maintenance_target  # source forced offline, if any


def _roll_event(sources):
    """Pick a random event definition; maintenance targets a random running source."""
    kind = random.choice(["HEAT WAVE", "CLOUD COVER", "WIND GUST", "RAIN", "GRID MAINTENANCE"])
    if kind == "HEAT WAVE":
        return GridEvent("⚠ HEAT WAVE — demand surging", "HEAT_WAVE", 30.0, demand_multiplier=1.3)
    if kind == "CLOUD COVER":
        return GridEvent("☁ CLOUD COVER — solar offline", "CLOUD_COVER", 20.0, solar_override=0.0)
    if kind == "WIND GUST":
        return GridEvent("💨 WIND GUST — wind at maximum", "WIND_GUST", 10.0, wind_override=1.0)
    if kind == "RAIN":
        return GridEvent("🌧 RAIN — solar dimmed, hydro boosted", "RAIN", 25.0,
                         solar_override=0.15, hydro_boost=1.15)
    # grid maintenance: only sources actually producing are interesting targets
    candidates = [s for s in sources if s.actual_pct > 0.05 and s.forced_offline_timer <= 0]
    if not candidates:
        return None
    target = random.choice(candidates)
    return GridEvent(f"🔧 GRID MAINTENANCE — {target.name} offline", "MAINTENANCE", 45.0,
                     maintenance_target=target)


def load_high_score() -> float:
    try:
        with open(HIGHSCORE_PATH) as f:
            return float(json.load(f).get("high_score", 0.0))
    except (OSError, ValueError):
        return 0.0


def save_high_score(score: float):
    try:
        with open(HIGHSCORE_PATH, "w") as f:
            json.dump({"high_score": score}, f)
    except OSError:
        pass  # a failed save should never crash the game loop


def score_delta(fill_pct: float) -> float:
    """fill_pct is the live supply/demand ratio (1.0 == exactly meeting demand),
    so the ideal band is centered on 1.0, not on some mid-range buffer level.
    Tuned so +/-25% of demand is the hard line between "recoverable miss" and
    "actively bleeding score" — tight enough that drifting off target actually
    hurts, without the buffer band being so thin it's not fun."""
    if fill_pct < BLACKOUT_THRESHOLD:
        return -50   # blackout: barely any demand being met
    elif fill_pct < 0.75:
        return -20   # danger zone: more than 25% short of demand
    elif fill_pct < 0.90:
        return -3    # underpowered, mildly costly
    elif fill_pct <= 1.10:
        return +10   # ideal: within 10% of demand
    elif fill_pct <= 1.25:
        return -3    # oversupplied, mildly wasteful
    elif fill_pct < MAX_FILL_PCT:
        return -20   # danger zone: more than 25% over demand
    else:
        return -50   # meltdown: wildly overproducing


class GameState:
    def __init__(self):
        self.sim_hour = 4.0        # game begins at 04:00 AM
        self.game_speed = 1.0
        self.paused = False

        self.demand_level = demand_at_hour(self.sim_hour)
        self.box_scale = 0.0             # smoothed 0..1 size fraction (drives height AND footprint)
        self.box_height_px = MIN_BOX_HEIGHT_PX
        self.box_footprint_px = MIN_BOX_FOOTPRINT_PX

        self.fill_pct = 0.30
        self.fill_pct_display = 0.30
        self.fill_pct_prev = 0.30
        self.session_elapsed = 0.0   # blocks blackout/meltdown checks until
                                      # fill_pct has had time to track reality

        self.score = 0.0
        self.score_delta_per_sec = 0.0
        self.high_score = load_high_score()
        self.new_high_score = False
        self.celebrate_high_score = 0.0   # seconds left on the personal-best reaction

        self.blackout = False
        self.overflow = False
        self.flash_messages = []   # list of [text, ttl]

        self.game_over = False
        self.game_over_reason = None

        self.total_cost = 0.0
        self.cost_per_hour = 0.0     # current $/hr burn rate, for display
        self.grid_price = 0.0        # system marginal price ($/MWh) — the
                                      # cost of the most expensive source
                                      # currently dispatched, same logic real
                                      # merit-order markets use to set price

        self.active_event = None
        self.next_event_in = GRACE_PERIOD + random.uniform(EVENT_MIN_GAP, EVENT_MAX_GAP)

        # per-source output history for the day, used to draw the stacked
        # generation-mix chart: list of (hour, {source_key: mw}, demand_mw)
        self.history = []
        self._history_last_hour = None

        self.sources = [
            NuclearSource(), CoalSource(), GasSource(),
            SolarSource(), WindSource(), HydroSource(),
        ]
        # pre-warm baseload per spec 7.2
        for s in self.sources[:2]:  # nuclear, coal
            s.requested_pct = 0.5
            s.actual_pct = 0.5
            s.status = SourceStatus.ONLINE

    def speed_up(self):
        idx = min(SPEED_STEPS.index(self.game_speed), len(SPEED_STEPS) - 1) if self.game_speed in SPEED_STEPS else 2
        self.game_speed = SPEED_STEPS[min(idx + 1, len(SPEED_STEPS) - 1)]

    def speed_down(self):
        idx = SPEED_STEPS.index(self.game_speed) if self.game_speed in SPEED_STEPS else 2
        self.game_speed = SPEED_STEPS[max(idx - 1, 0)]

    @property
    def homes_total(self) -> float:
        return self.demand_mw * HOUSEHOLDS_PER_MW

    @property
    def homes_powered(self) -> float:
        return min(self.total_actual_mw, self.demand_mw) * HOUSEHOLDS_PER_MW

    @property
    def homes_without_power(self) -> float:
        return max(0.0, self.homes_total - self.homes_powered)

    @property
    def demand_mw(self) -> float:
        base = DEMAND_MIN_MW + (DEMAND_PEAK_MW - DEMAND_MIN_MW) * self.demand_level
        if self.active_event:
            base *= self.active_event.demand_multiplier
        return base

    @property
    def total_actual_mw(self) -> float:
        return sum(s.current_output_mw for s in self.sources)

    def seconds_per_sim_hour(self) -> float:
        return GAME_DAY_REAL_SECONDS / 24.0

    def _trigger_game_over(self, reason: str):
        if self.game_over:
            return
        self.game_over = True
        self.game_over_reason = reason
        self.persist_high_score()

    def update(self, dt: float):
        if self.paused or self.game_over:
            return
        dt *= self.game_speed
        self.session_elapsed += dt

        self.sim_hour = (self.sim_hour + dt / self.seconds_per_sim_hour()) % 24.0
        self.demand_level = demand_at_hour(self.sim_hour)

        self._update_events(dt)

        for s in self.sources:
            s.update(dt, self.sim_hour)
            if s.pending_score_penalty:
                self.score += s.pending_score_penalty
                s.pending_score_penalty = 0.0
            if s.pending_flash:
                self.flash_messages.append([s.pending_flash, 3.0])
                s.pending_flash = None
            if s.key == "nuclear" and s.status == SourceStatus.SCRAM:
                self._trigger_game_over("NUCLEAR MELTDOWN")

        self._update_pricing(dt)

        # box size (height AND footprint) follows demand, animated as one uniform scale factor
        # so the vessel grows outward in x/y/z together rather than just stretching taller.
        self.box_scale += (self.demand_level - self.box_scale) * min(1.0, BOX_LERP_SPEED * 60 * dt)
        self.box_height_px = MIN_BOX_HEIGHT_PX + self.box_scale * (MAX_BOX_HEIGHT_PX - MIN_BOX_HEIGHT_PX)
        self.box_footprint_px = MIN_BOX_FOOTPRINT_PX + self.box_scale * (
            MAX_BOX_FOOTPRINT_PX - MIN_BOX_FOOTPRINT_PX)

        # The box directly tracks the LIVE supply/demand ratio (smoothed only
        # enough to avoid jitter) rather than integrating surplus/deficit over
        # time — a slow-draining buffer meant the box could stay flooded at
        # 200% for minutes after supply had already dropped back to balanced,
        # completely decoupled from what the HUD's live ratio was showing.
        self.fill_pct_prev = self.fill_pct
        self.fill_pct = track_fill(self.fill_pct, self.total_actual_mw, self.demand_mw,
                                    dt, FILL_TRACK_SPEED, MAX_FILL_PCT)
        self.fill_pct_display += (self.fill_pct - self.fill_pct_display) * min(1.0, WATER_LERP_SPEED * dt)

        self.blackout = self.fill_pct < BLACKOUT_THRESHOLD
        self.overflow = self.fill_pct >= 1.0

        if self.session_elapsed >= STARTUP_GRACE:
            if self.blackout:
                self._trigger_game_over("TOTAL BLACKOUT")
            elif self.fill_pct >= MAX_FILL_PCT - 0.01:
                self._trigger_game_over("GRID MELTDOWN")
        if self.game_over:
            return

        delta = score_delta(self.fill_pct) * dt
        self.score += delta
        self.score_delta_per_sec = score_delta(self.fill_pct)

        if self.score > self.high_score:
            if not self.new_high_score and self.high_score > 0:
                self.flash_messages.append(["★ NEW HIGH SCORE", 3.0])
                self.celebrate_high_score = 3.0
            self.high_score = self.score
            self.new_high_score = True

        self.celebrate_high_score = max(0.0, self.celebrate_high_score - dt)
        self.flash_messages = [[t, ttl - dt] for t, ttl in self.flash_messages if ttl - dt > 0]

        self._record_history()

    def _update_pricing(self, dt: float):
        """Each source has its own $/MWh (gas scales with demand_level, the
        rest are flat). The grid's displayed price is the marginal price —
        the cost of the most expensive source currently actually dispatched
        — the same merit-order logic real wholesale markets use to set a
        single system price. Total spend accrues at each source's own cost
        for the MW it actually produced, converted from real seconds elapsed
        into equivalent simulated hours so a full sim-day accrues a
        realistic-looking daily fuel bill instead of a tiny fraction."""
        scarcity = bool(self.active_event and self.active_event.kind == "HEAT_WAVE")
        sim_hours_elapsed = dt / self.seconds_per_sim_hour()

        cost_rate = 0.0
        marginal_price = 0.0
        for s in self.sources:
            price = s.price_at(self.demand_level)
            if s.key == "gas" and scarcity:
                price *= EVENT_SCARCITY_MULTIPLIER
            if s.current_output_mw > 1.0:
                cost_rate += s.current_output_mw * price
                marginal_price = max(marginal_price, price)

        self.cost_per_hour = cost_rate
        self.grid_price = marginal_price
        self.total_cost += cost_rate * sim_hours_elapsed

    def _record_history(self):
        """Sample actual per-source output roughly every 0.15 sim-hours so the
        stacked generation-mix chart can render the day's actual dispatch."""
        if self._history_last_hour is not None and self.sim_hour < self._history_last_hour - 12:
            self.history = []  # a new day started; start the chart over
            self._history_last_hour = None

        if self._history_last_hour is None or abs(self.sim_hour - self._history_last_hour) >= 0.15:
            snapshot = {s.key: s.current_output_mw for s in self.sources}
            self.history.append((self.sim_hour, snapshot, self.demand_mw))
            self._history_last_hour = self.sim_hour

    def _update_events(self, dt: float):
        solar = next(s for s in self.sources if s.key == "solar")
        wind = next(s for s in self.sources if s.key == "wind")
        hydro = next(s for s in self.sources if s.key == "hydro")

        if self.active_event:
            ev = self.active_event
            ev.remaining -= dt
            if ev.remaining <= 0:
                solar.event_availability_override = None
                wind.event_availability_override = None
                hydro.rain_multiplier = 1.0
                self.active_event = None
                self.next_event_in = random.uniform(EVENT_MIN_GAP, EVENT_MAX_GAP)
            else:
                solar.event_availability_override = ev.solar_override
                wind.event_availability_override = ev.wind_override
                hydro.rain_multiplier = ev.hydro_boost
            return

        self.next_event_in -= dt
        if self.next_event_in > 0:
            return
        ev = _roll_event(self.sources)
        if ev is None:  # nothing sensible to disrupt right now; retry shortly
            self.next_event_in = 10.0
            return
        self.active_event = ev
        self.flash_messages.append([ev.name, 3.0])
        if ev.maintenance_target is not None:
            ev.maintenance_target.force_offline(ev.duration)

    def persist_high_score(self):
        save_high_score(self.high_score)

    def clock_string(self) -> str:
        h24 = int(self.sim_hour)
        m = int((self.sim_hour - h24) * 60)
        period = "AM" if h24 < 12 else "PM"
        h12 = h24 % 12
        if h12 == 0:
            h12 = 12
        return f"{h12:02d}:{m:02d} {period}"
