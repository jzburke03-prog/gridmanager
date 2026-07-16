"""Demand curve math: the aggregate grid demand as a function of simulated hour."""
import numpy as np


def demand_at_hour(t: float) -> float:
    """
    Returns demand as a value from 0.0 (minimum) to 1.0 (peak).
    Trough ~4am, peak ~4pm, with a secondary shoulder peak ~8pm.
    """
    base = 0.5 - 0.5 * np.cos(2 * np.pi * (t - 4) / 24)       # primary cycle
    shoulder = 0.15 * np.exp(-((t - 20) ** 2) / 8)             # evening shoulder
    noise = 0.02 * np.sin(7 * t) + 0.01 * np.sin(13 * t)       # micro-fluctuation
    return float(np.clip(base + shoulder + noise, 0.0, 1.0))


def demand_curve_samples(n: int = 288):
    """Precompute (hour, demand) samples across a full day for chart rendering."""
    hours = np.linspace(0, 24, n)
    values = [demand_at_hour(h) for h in hours]
    return hours, values
