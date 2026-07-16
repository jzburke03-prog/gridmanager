import random
from .base_source import EnergySource, clamp
from pricing import SOLAR_PRICE_PER_MWH


def solar_availability(t: float) -> float:
    """Deterministic base sun curve: dark 8pm-5am, ramp up 5am-noon, full noon-2pm, ramp down 2pm-8pm."""
    if t < 5 or t >= 20:
        return 0.0
    if t < 12:
        return clamp((t - 5) / 7.0)
    if t < 14:
        return 1.0
    return clamp(1.0 - (t - 14) / 6.0)


class SolarSource(EnergySource):
    def __init__(self):
        super().__init__(
            name="Solar", key="solar", max_output_mw=500,
            ramp_up_latency=1, ramp_down_latency=1,
            min_stable_output=0.0, can_shut_down=True,
            availability_fn=solar_availability,
            color=(255, 209, 102), startup_cost_penalty=0.0,
            price_fn=lambda demand_level: SOLAR_PRICE_PER_MWH,
        )
        self.cloud_factor = 1.0
        self._cloud_target = 1.0
        self._cloud_timer = 0.0

    def _pre_update(self, dt, t_hours):
        self._cloud_timer -= dt
        if self._cloud_timer <= 0:
            self._cloud_timer = 15.0
            self._cloud_target = clamp(1.0 + random.uniform(-0.2, 0.2), 0.5, 1.0)
        self.cloud_factor += (self._cloud_target - self.cloud_factor) * min(1.0, dt * 0.5)
        self.availability = clamp(self.availability_fn(t_hours) * self.cloud_factor)

    @property
    def barrel_pct(self) -> float:
        """Visual reservoir gauge: how much sun is available right now."""
        return self.availability
