"""Flow speed model + LinePulse checks (grid_flow.py). Run: python test_grid_flow.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
pygame.init()

from ui.grid_flow import Flow, LinePulse, ramp_speed_px_s, PULSE_MAX_ALPHA


def test_ramp_speed_is_monotonic_with_responsiveness():
    # Real ramp_up_latency values from sources/*.py: faster-responding plants
    # (lower latency) must read as FASTER pulses, not slower.
    peaker = ramp_speed_px_s(1.5)
    gas = ramp_speed_px_s(3.0)
    coal = ramp_speed_px_s(20.0)
    nuclear = ramp_speed_px_s(45.0)
    assert peaker > gas > coal > nuclear


def test_ramp_speed_clamps_outside_the_fleet_range():
    from ui.grid_flow import SPEED_MIN_PX_S, SPEED_MAX_PX_S
    assert ramp_speed_px_s(0.001) == SPEED_MAX_PX_S
    assert ramp_speed_px_s(1000.0) == SPEED_MIN_PX_S


def test_flow_speed_is_fixed_not_output_driven():
    fast = Flow([(0, 0), (200, 0)], seed=1, speed_px_s=200.0)
    slow = Flow([(0, 0), (200, 0)], seed=1, speed_px_s=40.0)
    surf = pygame.Surface((220, 20), pygame.SRCALPHA)
    # same output on both -- only speed_px_s should differ their travel
    for _ in range(30):
        fast.update_and_draw(surf, 1.0, 1 / 60.0)
        slow.update_and_draw(surf, 1.0, 1 / 60.0)
    fast_progress = [p[0] for p in fast.pulses]
    slow_progress = [p[0] for p in slow.pulses]
    assert fast_progress and slow_progress
    assert max(fast_progress) > max(slow_progress)


def test_flow_spawn_rate_is_monotonic_in_output():
    """Pulse RATE (particles/sec) must scale with output -- higher output
    means more in-flight pulses over the same window, not just nonzero."""
    def spawn_count(output):
        flow = Flow([(0, 0), (300, 0)], cap=100, seed=5, speed_px_s=90.0)
        surf = pygame.Surface((310, 10), pygame.SRCALPHA)
        for _ in range(30):   # half a second, before any pulse reaches the end
            flow.update_and_draw(surf, output, 1 / 60.0)
        return len(flow.pulses) + len(flow.flashes)

    low = spawn_count(0.2)
    mid = spawn_count(0.6)
    high = spawn_count(1.0)
    assert low < mid < high


def test_line_pulse_silent_when_not_energised():
    pulse = LinePulse([(0, 0), (100, 0)], seed=3)
    surf = pygame.Surface((110, 10), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 0))
    pulse.draw(surf, t=0.5, energised=False)
    assert surf.get_at((50, 0))[3] == 0  # fully transparent -- nothing drawn


def test_line_pulse_alpha_stays_within_bounds_when_energised():
    pulse = LinePulse([(0, 0), (100, 0)], seed=3)
    surf = pygame.Surface((110, 10), pygame.SRCALPHA)
    for tick in range(0, 400):
        t = tick / 60.0
        surf.fill((0, 0, 0, 0))
        pulse.draw(surf, t, energised=True)
        for x in range(0, 100, 5):
            alpha = surf.get_at((x, 0))[3]
            assert 0 <= alpha <= PULSE_MAX_ALPHA


def test_line_pulse_band_moves_over_time():
    # A single short segment gives the wave only one point of resolution (the
    # whole segment lit or not), so this uses a multi-segment path -- matching
    # a real street-routed branch -- and sweeps across several seconds (more
    # than one full wave period) rather than two arbitrary instants, so the
    # assertion doesn't depend on picking lucky t values.
    path = [(0, 0), (25, 0), (50, 0), (75, 0), (100, 0)]
    pulse = LinePulse(path, seed=7)
    surf = pygame.Surface((110, 10), pygame.SRCALPHA)
    samples = []
    for tick in range(0, 240):
        t = tick / 60.0
        surf.fill((0, 0, 0, 0))
        pulse.draw(surf, t, energised=True)
        samples.append(tuple(surf.get_at((x, 0))[3] for x in range(0, 100, 10)))
    assert len(set(samples)) > 1   # the lit pattern actually changes over time


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall grid_flow checks passed")
