"""Water fill physics: the box directly visualizes the LIVE supply/demand
ratio (smoothed just enough to avoid jitter), not an accumulated buffer.

An earlier version integrated net surplus/deficit over time like a real
reservoir. That made physical sense but was a bad game readout: after a
period of oversupply the box could sit flooded at 150-200% for minutes after
supply had already dropped back to balanced, totally decoupled from what the
live SUPPLY/DEMAND numbers were showing right next to it. Players read the
box as "am I meeting demand right now", so it needs to answer that question
directly.

FANCY_PHYSICS can later toggle in a pymunk particle simulation (Option A)
without changing callers.
"""

FANCY_PHYSICS = False


def track_fill(fill_pct: float, total_actual_mw: float, demand_mw: float,
                dt: float, track_speed: float, max_fill_pct: float) -> float:
    """Exponentially smooth fill_pct toward supply/demand, at track_speed per
    second. This is a short visual lag for smooth animation, not a buffer —
    it settles to the live ratio within ~1-2 seconds of a change, not minutes."""
    target = total_actual_mw / demand_mw if demand_mw > 0 else 1.0
    target = max(0.0, min(max_fill_pct, target))
    fill_pct += (target - fill_pct) * min(1.0, track_speed * dt)
    return max(0.0, min(max_fill_pct, fill_pct))
