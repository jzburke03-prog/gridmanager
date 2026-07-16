import math
import random
from .base_source import EnergySource, clamp
from pricing import WIND_PRICE_PER_MWH

# Diurnal wind speed profile (hour -> normalized 0..1 availability), traced
# from a real daily wind-speed curve: calm overnight, a morning ramp with a
# local peak around 9am, a wobbly midday plateau, then the day's main peak
# in the early evening (~7-8pm) before tapering back down overnight.
_ANCHORS = [
    (0, 0.31), (2, 0.35), (5, 0.35), (7, 0.40), (9, 0.76), (10, 0.69),
    (11, 0.75), (13, 0.66), (15, 0.69), (17, 0.85), (19, 1.00),
    (21, 0.79), (22, 0.84), (24, 0.31),
]

_PHASES = [random.uniform(0, math.tau) for _ in range(2)]
_FREQS = [0.53, 1.7]
_AMPS = [0.06, 0.04]  # light gust texture layered on top of the diurnal shape


def _diurnal_wind(t: float) -> float:
    t = t % 24
    for (h0, v0), (h1, v1) in zip(_ANCHORS, _ANCHORS[1:]):
        if h0 <= t <= h1:
            frac = (t - h0) / (h1 - h0)
            eased = 0.5 - 0.5 * math.cos(math.pi * frac)
            return v0 + (v1 - v0) * eased
    return _ANCHORS[-1][1]


def wind_availability(t: float) -> float:
    """Real-world-shaped diurnal wind curve with a light noise texture layered on top."""
    v = _diurnal_wind(t)
    for amp, freq, phase in zip(_AMPS, _FREQS, _PHASES):
        v += amp * math.sin(freq * t + phase)
    return clamp(v)


class WindSource(EnergySource):
    def __init__(self):
        super().__init__(
            name="Wind", key="wind", max_output_mw=200,
            ramp_up_latency=2, ramp_down_latency=2,
            min_stable_output=0.0, can_shut_down=True,
            availability_fn=wind_availability,
            color=(168, 218, 220), startup_cost_penalty=0.0,
            price_fn=lambda demand_level: WIND_PRICE_PER_MWH,
        )
