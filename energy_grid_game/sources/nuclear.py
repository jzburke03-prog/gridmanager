from .base_source import EnergySource
from pricing import NUCLEAR_PRICE_PER_MWH


class NuclearSource(EnergySource):
    def __init__(self):
        super().__init__(
            name="Nuclear", key="nuclear", max_output_mw=150,
            ramp_up_latency=45, ramp_down_latency=60,
            min_stable_output=0.40, can_shut_down=False,
            availability_fn=lambda t: 1.0,
            color=(126, 200, 227), startup_cost_penalty=200.0,
            price_fn=lambda demand_level: NUCLEAR_PRICE_PER_MWH,
        )
