from .base_source import EnergySource
from pricing import COAL_PRICE_PER_MWH


class CoalSource(EnergySource):
    def __init__(self):
        super().__init__(
            name="Coal", key="coal", max_output_mw=250,
            ramp_up_latency=20, ramp_down_latency=25,
            min_stable_output=0.20, can_shut_down=True,
            availability_fn=lambda t: 1.0,
            color=(92, 92, 92), startup_cost_penalty=60.0,
            has_cooldown_mechanic=True,
            price_fn=lambda demand_level: COAL_PRICE_PER_MWH,
        )
