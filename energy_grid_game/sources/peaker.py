from .base_source import EnergySource
from pricing import peaker_price


class PeakerSource(EnergySource):
    """Simple-cycle gas peaker turbines: a small, very expensive, very fast
    plant. Split out from the combined-cycle gas fleet — these are the last,
    priciest MW on the grid, dispatched to cover the top slice of peak demand.
    They cost far more than combined-cycle at every demand level, but respond
    almost instantly (their whole reason for existing), so they're the tool of
    last resort when demand spikes faster than the CC fleet can ramp."""

    def __init__(self):
        super().__init__(
            name="Gas Peaker", key="peaker", max_output_mw=50,
            ramp_up_latency=1.5, ramp_down_latency=1.5,
            min_stable_output=0.0, can_shut_down=True,
            availability_fn=lambda t: 1.0,
            color=(255, 95, 45), startup_cost_penalty=8.0,
            price_fn=peaker_price,
        )
