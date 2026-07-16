import math
import random
from .base_source import EnergySource, clamp
from pricing import WIND_PRICE_PER_MWH

_PHASES = [random.uniform(0, math.tau) for _ in range(4)]
_FREQS = [0.11, 0.27, 0.53, 1.7]
_AMPS = [0.45, 0.25, 0.18, 0.12]


def wind_availability(t: float) -> float:
    """Smoothed multi-octave noise over the 24h day; deliberately uncorrelated with time-of-day."""
    v = 0.5
    for amp, freq, phase in zip(_AMPS, _FREQS, _PHASES):
        v += amp * math.sin(freq * t + phase)
    return clamp(v)


class WindSource(EnergySource):
    def __init__(self):
        super().__init__(
            name="Wind", key="wind", max_output_mw=400,
            ramp_up_latency=2, ramp_down_latency=2,
            min_stable_output=0.0, can_shut_down=True,
            availability_fn=wind_availability,
            color=(168, 218, 220), startup_cost_penalty=0.0,
            price_fn=lambda demand_level: WIND_PRICE_PER_MWH,
        )

    def forecast(self, t_hours: float, lookahead_hours: float = 2.0, n: int = 12):
        """2-hour lookahead mini-forecast for the HUD."""
        return [wind_availability((t_hours + lookahead_hours * i / (n - 1)) % 24) for i in range(n)]
