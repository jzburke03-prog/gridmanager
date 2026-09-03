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
  * Per-source colour on plant→substation transmission corridors so the fuel
    type is visible at a glance. Downstream distribution and service flows stay
    neutral blue, since that power is a blend of all sources.

A Flow is per-route, which is what a future carrying-capacity/congestion model
attaches to: each path can be given its own limit without touching this file.
"""
import math
import random

import pygame

PULSE = (120, 200, 255)       # electric blue
OVERLOAD_HOT = (255, 120, 60)   # colour an overloaded corridor lerps toward
FLASH_LIFE = 0.4              # seconds, arrival ring at the far end
REFERENCE_LEN = 260.0         # the pipe length the original rates were tuned at

# Real ramp_up_latency range across the DISPATCHABLE fleet (seconds; see
# sources/*.py): peaker 1.5 (fastest), gas 3, hydro 5, coal 20, nuclear 45
# (slowest). Literal electron speed can't carry "accuracy by technology" --
# AC drift velocity is ~0 and signal propagation is ~50-90% light speed on
# every line regardless of voltage class, both effectively instantaneous at
# game scale. Ramp responsiveness is the honest, already-researched,
# already-in-the-codebase signal instead: fast-reacting plants (peaker, gas)
# read as brisk, slow ones (nuclear, coal) read as a crawl -- which is
# literally what the tutorial dialogue already tells the player.
#
# The floor is anchored to the peaker's real 1.5s, not the instructional-only
# "generic" valve's 0.05s or solar/wind's ~1-2s: generic never appears
# alongside another plant to contrast against (Instructional Day 1 is a
# single-valve grid), and solar/wind's `ramp_up_latency` represents how fast
# the player's throttle takes effect, not a real generation-ramp
# characteristic being taught (same reasoning that excludes them from the
# congestion mechanic). Anchoring to 0.05s left peaker at only t=0.50 of the
# domain (130px/s, not 220) with just a 16% gap to gas -- imperceptible at
# 1.5-3.3px particle size. Anchoring to peaker's real value gives the
# dispatchable fleet (the one this speed story is actually about) its full
# intended contrast, confirmed via a juice:juice-consultant feel-pass on the
# running result.
RAMP_LATENCY_MIN_S = 1.5
RAMP_LATENCY_MAX_S = 45.0
SPEED_MIN_PX_S = 40.0
SPEED_MAX_PX_S = 220.0

# Solar and wind are excluded from the ramp-speed story entirely (mirrors
# CONGESTION_EXCLUDED_KEYS in game_state.py, same reasoning): their
# ramp_up_latency represents how fast the player's throttle takes effect,
# not a real generation-ramp characteristic being taught, so routing them
# through ramp_speed_px_s would either silently clamp them onto the
# peaker's speed (their real latencies are near the fleet floor) or
# otherwise misrepresent the dispatchable-fleet responsiveness story this
# whole model exists to tell. They get one fixed, deliberately-neutral
# speed instead -- distinct from both extremes, claiming neither
# "peaker-fast" nor "nuclear-slow".
NON_RAMP_SPEED_PX_S = 120.0


def ramp_speed_px_s(ramp_up_latency_s: float) -> float:
    """A plant's electron travel speed from its real ramp-up latency,
    log-scaled since the fleet's latencies span three orders of magnitude."""
    lo, hi = math.log(RAMP_LATENCY_MIN_S), math.log(RAMP_LATENCY_MAX_S)
    latency = max(RAMP_LATENCY_MIN_S, min(RAMP_LATENCY_MAX_S, ramp_up_latency_s))
    t = (math.log(latency) - lo) / (hi - lo)   # 0 (fast) .. 1 (slow)
    return SPEED_MAX_PX_S - (SPEED_MAX_PX_S - SPEED_MIN_PX_S) * t


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
    """Pulses travelling one path, at a rate set by how hard its plant is run
    and a speed set by that plant's real ramp responsiveness."""

    __slots__ = ("segs", "total", "end", "pulses", "flashes", "_acc", "cap",
                "_rng", "speed_px_s")

    def __init__(self, path, cap=24, seed=0, speed_px_s=90.0):
        self.segs, self.total = path_length(path)
        self.end = path[-1] if path else (0.0, 0.0)
        self.pulses = []      # [progress, size_jitter]
        self.flashes = []     # [age]
        self._acc = 0.0
        self.cap = cap
        self._rng = random.Random(seed)
        self.speed_px_s = speed_px_s

    def update_and_draw(self, surf, output, dt, color=PULSE, overload=0.0):
        """`output` is 0..1 — the plant's actual (ramped) throttle, so a plant
        that is offline leaves its line dark without any special-casing."""
        if self.total <= 0:
            return
        ov = max(0.0, min(1.0, overload))
        color = tuple(int(color[j] + (OVERLOAD_HOT[j] - color[j]) * ov) for j in range(3))
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

        step = self.speed_px_s / self.total * dt   # fixed per-Flow speed
        alive = []
        for p in self.pulses:
            p[0] += step
            if p[0] >= 1.0:
                self.flashes.append([0.0])
                continue
            alive.append(p)
        self.pulses = alive

        radius = 1.5 + output * 1.8 + ov * 2.0
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


# Distribution/service "flow" indicator: a soft brightness WAVE travelling
# along a static line, not individual particles (downstream power is a blend
# of every source -- there is no single electron to show) and not a uniform
# blink (that reads as a warning light, not flow). Design consulted with
# technical-art:shader-architect during planning: a traveling band, not a
# global pulse, is what makes the eye read "current flowing" rather than
# "line blinking" -- and by construction only a soft band is ever bright at
# once, which is *more* accessibility-compliant than a whole-line blink.
PULSE_GLOW = (255, 240, 210)    # near-white, slight warm bias: "energised"
PULSE_SPEED_PX_S = 50.0         # wave travel speed -- one speed for all branch lengths
PULSE_BAND_FRAC = 0.20          # bright band width as a fraction of the branch's length
PULSE_MAX_ALPHA = 90            # overlay peak alpha; the baked base line stays visible under it


class LinePulse:
    """A travelling brightness wave over an already-baked static line. Each
    branch's wave originates at arc-length 0 -- the substation end for a
    distribution branch, the neighbourhood-transformer end for a service
    branch -- so waves visibly radiate outward from source. A small
    deterministic per-branch time offset (from `seed`) is layered on purely
    as a defensive guard against same-length branches lighting in lockstep;
    it does not replace the distance-based origin, which is what gives the
    effect its "flow" read."""

    __slots__ = ("segs", "total", "mids", "_t_offset")

    def __init__(self, path, seed=0):
        self.segs, self.total = path_length(path)
        acc = 0.0
        mids = []
        for a, b, d in self.segs:
            mids.append(acc + d / 2.0)
            acc += d
        self.mids = mids
        period_s = (self.total / PULSE_SPEED_PX_S) if self.total > 0 else 1.0
        self._t_offset = (seed % 997) / 997.0 * period_s

    def draw(self, surf, t, energised, color=None):
        # `energised` may be a bool OR a 0..1 power intensity: more electricity
        # flowing -> faster, brighter pulses. This is what makes distribution read
        # as "power reaching the city", scaled to how much is actually delivered.
        intensity = float(energised)
        if self.total <= 0 or intensity <= 0.02:
            return
        glow = color or PULSE_GLOW
        band = max(1.0, self.total * PULSE_BAND_FRAC)
        period_px = self.total + band
        speed = PULSE_SPEED_PX_S * (0.45 + 0.75 * intensity)      # rate ~ power
        wave = ((t + self._t_offset) * speed) % period_px - band
        for (a, b, _d), mid in zip(self.segs, self.mids):
            dist = abs(mid - wave)
            if dist >= band:
                continue
            k = 1.0 - dist / band
            bright = k * k * (3.0 - 2.0 * k)   # smoothstep ease, no hard edge
            alpha = int(PULSE_MAX_ALPHA * bright * (0.35 + 0.65 * intensity))
            if alpha <= 2:
                continue
            pygame.draw.line(surf, (*glow, alpha), a, b, 2)
