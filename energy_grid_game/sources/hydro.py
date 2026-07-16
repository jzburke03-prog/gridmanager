from .base_source import EnergySource
from pricing import HYDRO_PRICE_PER_MWH


class HydroSource(EnergySource):
    def __init__(self):
        super().__init__(
            name="Hydro", key="hydro", max_output_mw=150,
            ramp_up_latency=5, ramp_down_latency=5,
            min_stable_output=0.05, can_shut_down=True,
            availability_fn=lambda t: 1.0,
            color=(33, 150, 243), startup_cost_penalty=10.0,
            price_fn=lambda demand_level: HYDRO_PRICE_PER_MWH,
        )
        self.rain_multiplier = 1.0  # temporary boost above baseline during a RAIN event

    @property
    def effective_max_mw(self) -> float:
        return self.max_output_mw * self.availability * self.rain_multiplier
