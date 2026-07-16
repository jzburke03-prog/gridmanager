"""Abstract EnergySource: shared ramping, latency, and status-machine logic."""
from enum import Enum


class SourceStatus(Enum):
    OFFLINE = "OFFLINE"
    RAMPING = "RAMPING"
    ONLINE = "ONLINE"
    COOLDOWN = "COOLING DOWN"
    DEPLETED = "DEPLETED"
    SCRAM = "SCRAM"
    MAINTENANCE = "MAINTENANCE"


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


class EnergySource:
    def __init__(self, name, key, max_output_mw, ramp_up_latency, ramp_down_latency,
                 min_stable_output, can_shut_down, availability_fn, color,
                 startup_cost_penalty=0.0, has_cooldown_mechanic=False, price_fn=None):
        self.name = name
        self.key = key
        self.max_output_mw = max_output_mw
        self.ramp_up_latency = max(ramp_up_latency, 0.05)
        self.ramp_down_latency = max(ramp_down_latency, 0.05)
        self.min_stable_output = min_stable_output
        self.can_shut_down = can_shut_down
        self.availability_fn = availability_fn
        self.color = color
        self.startup_cost_penalty = startup_cost_penalty
        self.has_cooldown_mechanic = has_cooldown_mechanic
        # $/MWh as a function of grid demand_level (0..1); defaults to a flat
        # $0 for sources that don't set one (shouldn't happen in practice —
        # every concrete source below provides a real price_fn)
        self.price_fn = price_fn or (lambda demand_level: 0.0)

        self.requested_pct = 0.0
        self.actual_pct = 0.0
        self.availability = 1.0
        self.status = SourceStatus.OFFLINE

        self.forced_offline_timer = 0.0   # SCRAM / maintenance lockout
        self.cooldown_timer = 0.0
        self.pending_score_penalty = 0.0  # one-shot penalty for game_state to consume
        self.pending_flash = None         # e.g. "SCRAM EVENT" for HUD banner
        self.event_availability_override = None  # grid events pin availability (0.0 cloud cover, 1.0 wind gust)

    # -- public API -----------------------------------------------------
    def set_handle(self, pct: float):
        if self.forced_offline_timer > 0 or self.status == SourceStatus.COOLDOWN:
            return
        self.requested_pct = clamp(pct)

    @property
    def effective_max_mw(self) -> float:
        return self.max_output_mw * self.availability

    @property
    def current_output_mw(self) -> float:
        return self.actual_pct * self.effective_max_mw

    def price_at(self, demand_level: float) -> float:
        return self.price_fn(demand_level)

    @property
    def is_ramping(self) -> bool:
        return abs(self.actual_pct - self._effective_request()) > 0.002

    def time_to_target(self) -> float:
        diff = abs(self.actual_pct - self._effective_request())
        if diff <= 0.002:
            return 0.0
        rate = 1.0 / self.ramp_up_latency if self._effective_request() > self.actual_pct \
            else 1.0 / self.ramp_down_latency
        return diff / rate

    # -- update loop ------------------------------------------------------
    def update(self, dt: float, t_hours: float):
        self.availability = clamp(self.availability_fn(t_hours))
        self._pre_update(dt, t_hours)
        if self.event_availability_override is not None:
            self.availability = clamp(self.event_availability_override)

        if self.forced_offline_timer > 0:
            self.forced_offline_timer = max(0.0, self.forced_offline_timer - dt)
            self._ramp_toward(0.0, dt)
            if self.forced_offline_timer == 0:
                self.status = SourceStatus.OFFLINE
            return

        effective_request = self._effective_request()

        if self.status == SourceStatus.COOLDOWN:
            self._ramp_toward(0.0, dt)
            self.cooldown_timer = max(0.0, self.cooldown_timer - dt)
            if self.actual_pct <= 0.001 and self.cooldown_timer <= 0:
                self.status = SourceStatus.OFFLINE
                self.requested_pct = 0.0
            return

        self._check_scram_and_cooldown(effective_request)
        if self.status in (SourceStatus.SCRAM, SourceStatus.COOLDOWN):
            return

        self._ramp_toward(effective_request, dt)
        self._update_status(effective_request)
        self._post_update(dt, t_hours)

    def _effective_request(self) -> float:
        """Requested pct, clamped by min-stable-once-online and availability caps."""
        req = self.requested_pct
        if self.actual_pct > 0.01 and req > 0:
            req = max(req, self.min_stable_output) if req >= self.min_stable_output * 0.5 else req
        return clamp(req)

    def _ramp_toward(self, target: float, dt: float):
        rate = (1.0 / self.ramp_up_latency) if target > self.actual_pct else (1.0 / self.ramp_down_latency)
        diff = target - self.actual_pct
        step = rate * dt
        if abs(diff) <= step:
            self.actual_pct = target
        else:
            self.actual_pct += step if diff > 0 else -step
        self.actual_pct = clamp(self.actual_pct)

    def _check_scram_and_cooldown(self, effective_request: float):
        improper_shutdown = (self.actual_pct > self.min_stable_output * 0.5 and
                              effective_request < self.min_stable_output)
        if not improper_shutdown:
            return
        if not self.can_shut_down:
            self._trigger_scram()
        elif self.has_cooldown_mechanic:
            self.status = SourceStatus.COOLDOWN
            self.cooldown_timer = 30.0

    def _trigger_scram(self):
        self.status = SourceStatus.SCRAM
        self.forced_offline_timer = 90.0
        self.requested_pct = 0.0
        self.pending_score_penalty = -150.0
        self.pending_flash = f"{self.name} SCRAM EVENT"

    def _update_status(self, effective_request: float):
        if self.actual_pct <= 0.001 and effective_request <= 0.001:
            self.status = SourceStatus.OFFLINE
        elif self.is_ramping:
            self.status = SourceStatus.RAMPING
        else:
            self.status = SourceStatus.ONLINE

    # -- hooks for subclasses --------------------------------------------
    def _pre_update(self, dt: float, t_hours: float):
        pass

    def _post_update(self, dt: float, t_hours: float):
        pass

    def force_offline(self, seconds: float, reason_status=SourceStatus.MAINTENANCE):
        self.forced_offline_timer = max(self.forced_offline_timer, seconds)
        self.status = reason_status
