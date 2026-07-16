from .base_source import EnergySource
from pricing import gas_price


class GasSource(EnergySource):
    def __init__(self):
        super().__init__(
            name="Natural Gas", key="gas", max_output_mw=800,
            ramp_up_latency=3, ramp_down_latency=3,
            min_stable_output=0.0, can_shut_down=True,
            availability_fn=lambda t: 1.0,
            color=(255, 140, 66), startup_cost_penalty=5.0,
            price_fn=gas_price,
        )
