from .base_source import EnergySource, SourceStatus, clamp
from pricing import HYDRO_PRICE_PER_MWH


class HydroSource(EnergySource):
    RESERVOIR_DEPLETION_RATE = 1.4     # % reservoir per second at full (100%) output
    RESERVOIR_REFILL_RATE = 0.4        # % reservoir per second of natural river inflow

    def __init__(self):
        super().__init__(
            name="Hydro", key="hydro", max_output_mw=700,
            ramp_up_latency=5, ramp_down_latency=5,
            min_stable_output=0.05, can_shut_down=True,
            availability_fn=lambda t: 1.0,
            color=(33, 150, 243), startup_cost_penalty=10.0,
            price_fn=lambda demand_level: HYDRO_PRICE_PER_MWH,
        )
        self.reservoir_pct = 70.0

    def _effective_request(self):
        if self.reservoir_pct <= 0.01:
            return 0.0
        return super()._effective_request()

    def _pre_update(self, dt, t_hours):
        if self.actual_pct > 0.01:
            self.reservoir_pct -= self.actual_pct * self.RESERVOIR_DEPLETION_RATE * dt
        self.reservoir_pct = clamp(self.reservoir_pct + self.RESERVOIR_REFILL_RATE * dt, 0.0, 100.0)

    def _post_update(self, dt, t_hours):
        if self.reservoir_pct <= 0.01 and self.actual_pct <= 0.01:
            self.status = SourceStatus.DEPLETED
