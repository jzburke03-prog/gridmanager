"""Animated power flow along a transmission path.

Lifted from the 1.1 water-pipe droplet system (`ui/pipes.py`, now deleted) —
the arc-length parameterisation and the spawn/advance/retire loop were the only
real particle code in the project and they were already good. Four things
changed on the way across, all because these are wires and not pipes:

  * Spawn rate scales with the path's LENGTH. The old rate was tuned for a
    ~250px pipe; transmission runs are 150-400px, so a fixed rate left the long
    ones visibly sparse.
  * Speed is constant in PIXELS per second, not in fraction-of-path per second,
    so a pulse crosses a short line and a long one at the same apparent pace.
  * No gravity easing. Water accelerates downhill; current does not.
  * One colour for everything. Per-source colour belonged to the fluid
    metaphor — you can already see which plant a line leaves from.

A Flow is per-route, which is what a future carrying-capacity/congestion model
attaches to: each path can be given its own limit without touching this file.
"""
import math
import random

import pygame

PULSE = (120, 200, 255)       # electric blue
FLASH_LIFE = 0.4              # seconds, arrival ring at the far end
REFERENCE_LEN = 260.0         # the pipe length the original rates were tuned at


def path_length(path):
    """-> (segments, total px). Each segment is (a, b, length)."""
    total = 0.0
    segs = []
    for a, b in zip(path, path[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        segs.append((a, b, d))
        total += d
    return segs, total


def point_at(segs, total, frac):
    """Position at `frac` (0..1) along the polyline, by arc length."""
    dist = max(0.0, min(1.0, frac)) * total
    acc = 0.0
    for a, b, d in segs:
        if acc + d >= dist:
            f = (dist - acc) / d if d > 0 else 0.0
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        acc += d
    return segs[-1][1] if segs else (0.0, 0.0)


class Flow:
    """Pulses travelling one path, at a rate set by how hard its plant is run."""

    __slots__ = ("segs", "total", "end", "pulses", "flashes", "_acc", "cap", "_rng")

    def __init__(self, path, cap=24, seed=0):
        self.segs, self.total = path_length(path)
        self.end = path[-1] if path else (0.0, 0.0)
        self.pulses = []      # [progress, size_jitter]
        self.flashes = []     # [age]
        self._acc = 0.0
        self.cap = cap
        self._rng = random.Random(seed)

    def update_and_draw(self, surf, output, dt, color=PULSE):
        """`output` is 0..1 — the plant's actual (ramped) throttle, so a plant
        that is offline leaves its line dark without any special-casing."""
        if self.total <= 0:
            return
        if output > 0.01:
            rate = (0.8 + output * 7.0) * (self.total / REFERENCE_LEN)
            self._acc += rate * dt
            while self._acc >= 1.0:
                self._acc -= 1.0
                if len(self.pulses) >= self.cap:
                    break
                self.pulses.append([0.0, 0.7 + self._rng.random() * 0.6])
        else:
            self._acc = 0.0

        step = (60.0 + output * 90.0) / self.total * dt      # constant px/s
        alive = []
        for p in self.pulses:
            p[0] += step
            if p[0] >= 1.0:
                self.flashes.append([0.0])
                continue
            alive.append(p)
        self.pulses = alive

        radius = 1.5 + output * 1.8
        alpha = int(150 + 90 * output)
        trail = 8.0 / self.total
        for prog, jitter in self.pulses:
            x, y = point_at(self.segs, self.total, prog)
            r = max(1, int(radius * jitter))
            pygame.draw.circle(surf, (*color, alpha), (int(x), int(y)), r)
            tx, ty = point_at(self.segs, self.total, max(0.0, prog - trail))
            pygame.draw.line(surf, (*color, alpha // 2),
                             (int(tx), int(ty)), (int(x), int(y)), 1)

        # arrival: a ring expanding at the substation, so the far end of the
        # line reads as somewhere power is actually landing
        ex, ey = self.end
        for f in self.flashes:
            f[0] += dt
            k = f[0] / FLASH_LIFE
            if k >= 1.0:
                continue
            pygame.draw.circle(surf, (*color, int(200 * (1.0 - k))),
                               (int(ex), int(ey)), int(3 + 12 * k), 2)
        self.flashes = [f for f in self.flashes if f[0] < FLASH_LIFE]
