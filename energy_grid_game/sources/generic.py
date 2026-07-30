"""The Day 1 valve for Instructional Mode: electricity with nothing attached.

Deliberately featureless. No ramp latency, no minimum stable output, no
availability curve, no price, no failure mode — turning the handle moves supply
immediately and nothing else happens. It exists so a player's first minutes teach
exactly one idea (supply has to track demand, continuously) without ramp
behaviour, economics or plant personality competing for attention.

Days 2-4 retire it and hand the same job to the real fleet.
"""
from sources.base_source import EnergySource

# The whole day-1 fleet in one handle, matching the 1500 MW the player is
# given on days 2 and 3. Comfortably over peak demand: a day-1 player must
# never be unable to win.
GENERIC_MAX_MW = 1500


class GenericSource(EnergySource):
    def __init__(self):
        super().__init__(
            name="Electricity", key="generic", max_output_mw=GENERIC_MAX_MW,
            ramp_up_latency=0.05, ramp_down_latency=0.05,
            min_stable_output=0.0, can_shut_down=True,
            availability_fn=lambda t: 1.0,
            color=(240, 208, 70), startup_cost_penalty=0.0,
            price_fn=lambda demand_level: 0.0,
        )
