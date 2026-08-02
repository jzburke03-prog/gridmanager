# Power-Flow Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Per the approved spec's "Plugin usage" section, use the `engineering:gameplay-coder` agent type as the implementer for Tasks 1, 2, and 3 (in place of a generic implementer) — its stated remit is exactly this class of work.

**Goal:** Fix electrons to travel the exact drawn conductor geometry and
terminate exactly at the substation; make pulse speed reflect each plant's
real ramp responsiveness (not a physically-meaningless "electron speed");
replace all downstream (distribution/service) particle animation with a
phase-staggered traveling brightness wave along the static line.

**Architecture:** `ui/grid_flow.py` gains a `speed_px_s` field on `Flow`
(replacing the old output-driven step calculation), a `ramp_speed_px_s()`
mapping function, and a new `LinePulse` class (traveling-wave brightness
overlay, no particles). `ui/iso_city.py`'s `_bake` is rewritten to construct
the electron `Flow`s from the *same* elevated/offset point sequence already
used to draw the double-circuit conductors (currently two independently
computed, silently mismatched geometries), and `_build_distribution` is
rewritten to build `LinePulse`s instead of particle `Flow`s.

**Tech Stack:** Python 3.9 (`.venv39`), pygame 2.6. Tests are plain-assert
self-runner modules (no pytest), run via
`./.venv39/Scripts/python.exe energy_grid_game/<test>.py` from
`D:/Github/gridmanager`. No git operations — the user handles version control.

## Global Constraints

- Electrons travel the **exact drawn conductor geometry** (both parallel
  wires of the double-circuit bundle), at every tower span, and **terminate
  exactly at the substation** — no partial-reach fade (supersedes the prior
  session's `ELECTRON_REACH` truncation, which is removed).
- Pulse **rate** (particles/sec) scales with `actual_pct` (plant output) —
  already correct; verify with a monotonicity test now that geometry is
  fixed and testable end to end.
- Pulse **speed** (px/sec) is derived from the plant's real
  `ramp_up_latency` (seconds, declared on every `sources/*.py` class),
  log-scaled across the fleet's actual range: 0.05s (generic) .. 45s
  (nuclear). Fast-ramping plants (peaker, gas) read as brisk; slow ones
  (nuclear, coal) read as a crawl. `output` no longer drives speed.
- Distribution (substation → neighbourhood transformer) and service
  (transformer → house) lines carry **no individual particles**. Instead: a
  soft brightness **wave** travels along the static line, originating at
  that branch's own source end (substation for a distribution branch,
  transformer for a service branch) — "radiates outward from source," not a
  uniform blink.
- A branch only pulses while actually energised (reuse the existing
  served/priority gate: `transformer.priority < served_fraction(...)`, the
  same condition the illumination-ring model already uses) — a dead feeder
  stays fully static/dark.
- Accessibility (non-negotiable, from `iso_city.py`'s module docstring): all
  effects stay smooth, low-contrast, capped well under 3Hz, and must never
  read as a large-area synchronized flash. The traveling-wave design
  satisfies this by construction (only a soft band is ever bright at once);
  a small deterministic per-branch time offset is layered on as a defensive
  guard against same-length branches coincidentally lighting in lockstep.
- Congestion's hot-color lerp (`overload=` on `Flow.update_and_draw`) is
  unaffected — still applies only to the transmission (electron) layer.
- No git operations — every "Commit" step is a "Checkpoint": run the
  verification and confirm green, do not `git add`/`commit`.
- Keep all six existing test files green throughout:
  `test_pricing.py`, `test_congestion.py`, `test_dialogue_schema.py`,
  `test_capacities.py`, `test_instructional.py`, `test_city_model.py`.

---

## Task 1: `grid_flow.py` — ramp-derived speed, and `LinePulse`

**Files:**
- Modify: `energy_grid_game/ui/grid_flow.py`
- Test: `energy_grid_game/test_grid_flow.py` (create)

**Interfaces:**
- Produces: `Flow.__init__(self, path, cap=24, seed=0, speed_px_s=90.0)` —
  `speed_px_s` is a new keyword arg, fixed for the Flow's lifetime.
- Produces: `ramp_speed_px_s(ramp_up_latency_s: float) -> float` — module
  function, pure, no pygame dependency.
- Produces: `LinePulse(path, seed=0)` with `.draw(surf, t, energised)`.
- Consumes: `path_length(path)` (existing helper, unchanged).

- [ ] **Step 1: Write the failing tests** — create
  `energy_grid_game/test_grid_flow.py`:

```python
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
    faster_than_anything = ramp_speed_px_s(0.001)
    slower_than_anything = ramp_speed_px_s(1000.0)
    assert faster_than_anything == ramp_speed_px_s(0.05)
    assert slower_than_anything == ramp_speed_px_s(45.0)


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
    # The bright band must actually travel -- sampling two different times
    # should not always light the same pixel (a static/uniform pulse would).
    pulse = LinePulse([(0, 0), (100, 0)], seed=7)
    surf_a = pygame.Surface((110, 10), pygame.SRCALPHA)
    surf_b = pygame.Surface((110, 10), pygame.SRCALPHA)
    pulse.draw(surf_a, t=0.0, energised=True)
    pulse.draw(surf_b, t=0.9, energised=True)
    row_a = [surf_a.get_at((x, 0))[3] for x in range(0, 100, 2)]
    row_b = [surf_b.get_at((x, 0))[3] for x in range(0, 100, 2)]
    assert row_a != row_b


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall grid_flow checks passed")
```

- [ ] **Step 2: Run it — must FAIL**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_grid_flow.py`
Expected: `ImportError: cannot import name 'LinePulse'` (or `ramp_speed_px_s`).

- [ ] **Step 3: Add `speed_px_s` to `Flow`**

In `ui/grid_flow.py`, change the `Flow.__init__` signature and slots:

```python
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
```

Then in `update_and_draw`, replace the output-driven step calculation:

```python
        step = (60.0 + output * 90.0) / self.total * dt      # constant px/s
```

with:

```python
        step = self.speed_px_s / self.total * dt   # fixed per-Flow speed
```

Leave everything else in `update_and_draw` unchanged (spawn-rate-by-output,
radius, alpha, trail, arrival flashes all stay as they are).

- [ ] **Step 4: Add `ramp_speed_px_s()`**

Add near the top of `ui/grid_flow.py`, below the existing `PULSE`/
`OVERLOAD_HOT`/`FLASH_LIFE`/`REFERENCE_LEN` constants:

```python
# Real ramp_up_latency range across the fleet (seconds; see sources/*.py):
# generic 0.05, solar 1, peaker 1.5, wind 2, gas 3, hydro 5, coal 20, nuclear
# 45. Literal electron speed can't carry "accuracy by technology" -- AC drift
# velocity is ~0 and signal propagation is ~50-90% light speed on every line
# regardless of voltage class, both effectively instantaneous at game scale.
# Ramp responsiveness is the honest, already-researched, already-in-the-
# codebase signal instead: fast-reacting plants (peaker, gas) read as brisk,
# slow ones (nuclear, coal) read as a crawl -- which is literally what the
# tutorial dialogue already tells the player.
RAMP_LATENCY_MIN_S = 0.05
RAMP_LATENCY_MAX_S = 45.0
SPEED_MIN_PX_S = 40.0
SPEED_MAX_PX_S = 220.0


def ramp_speed_px_s(ramp_up_latency_s: float) -> float:
    """A plant's electron travel speed from its real ramp-up latency,
    log-scaled since the fleet's latencies span three orders of magnitude."""
    lo, hi = math.log(RAMP_LATENCY_MIN_S), math.log(RAMP_LATENCY_MAX_S)
    latency = max(RAMP_LATENCY_MIN_S, min(RAMP_LATENCY_MAX_S, ramp_up_latency_s))
    t = (math.log(latency) - lo) / (hi - lo)   # 0 (fast) .. 1 (slow)
    return SPEED_MAX_PX_S - (SPEED_MAX_PX_S - SPEED_MIN_PX_S) * t
```

- [ ] **Step 5: Add `LinePulse`**

Add at the end of `ui/grid_flow.py`:

```python
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

    def draw(self, surf, t, energised):
        if self.total <= 0 or not energised:
            return
        band = max(1.0, self.total * PULSE_BAND_FRAC)
        period_px = self.total + band
        wave = ((t + self._t_offset) * PULSE_SPEED_PX_S) % period_px - band
        for (a, b, _d), mid in zip(self.segs, self.mids):
            dist = abs(mid - wave)
            if dist >= band:
                continue
            k = 1.0 - dist / band
            bright = k * k * (3.0 - 2.0 * k)   # smoothstep ease, no hard edge
            alpha = int(PULSE_MAX_ALPHA * bright)
            if alpha <= 2:
                continue
            pygame.draw.line(surf, (*PULSE_GLOW, alpha), a, b, 1)
```

`math` is already imported at the top of `grid_flow.py` — no new import needed.

- [ ] **Step 6: Run the tests — must PASS**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_grid_flow.py`
Expected: all 6 tests print `ok`, then "all grid_flow checks passed".

- [ ] **Step 7: Checkpoint** — confirm `Flow`'s existing behaviour (spawn
  rate by output, radius/alpha, arrival flashes, overload color lerp) is
  otherwise untouched by re-reading the diff before moving to Task 2.

---

## Task 2: `iso_city.py` — real conductor geometry, ramp speed, wave pulses

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
  - `__init__` (~L1500-1526): field renames
  - `_build_distribution` (~L1831-1867): build `LinePulse`s, not `Flow`s
  - `_bake` (~L1886-2068): dual-conductor elevated paths, ramp speed
    threading, remove `_truncate_path`/`ELECTRON_REACH`
  - `prepare` (~L2154-2162): thread `ramp_by_key` through to `_bake`
  - `_draw_transmission` → renamed `_draw_power_flow` (~L2287+): draw both
    conductor `Flow`s per corridor, draw `LinePulse`s for distribution/service
  - one call site in `draw()` (~L2205)
  - remove `_truncate_path` (~L277-303)

**Interfaces:**
- Consumes: `Flow(path, cap=, seed=, speed_px_s=)`, `ramp_speed_px_s(latency)`,
  `LinePulse(path, seed=)`, `.draw(surf, t, energised)` — all from Task 1.
- Produces: `IsoCity._flows: dict[(key, i), list[Flow]]` (2 entries per
  corridor, was 1 `Flow` per entry before).
- Produces: `IsoCity._distribution_pulses`, `IsoCity._service_pulses` (renamed
  from `_distribution_flows`/`_service_flows`; same `[(index, obj), ...]`
  shape, `obj` is now `LinePulse` not `Flow`).

- [ ] **Step 1: Rename the fields in `__init__`**

In `ui/iso_city.py`, change:

```python
        self._distribution_flows = []
        self._service_flows = []
```

to:

```python
        self._distribution_pulses = []
        self._service_pulses = []
```

- [ ] **Step 2: Rewrite `_build_distribution` to construct `LinePulse`s**

Add `LinePulse` to the existing import line near the top of the file:

```python
from ui.grid_flow import Flow, LinePulse, ramp_speed_px_s
```

In `_build_distribution`, change the two field-name references and swap
`Flow(...)` for `LinePulse(...)` (drop the `cap=` argument — it was a
particle-pool cap, meaningless for a wave with no particles):

```python
    def _build_distribution(self, ox, oy):
        """Connect each feeder-sized building cluster to its nearest substation."""
        self._transformers = []
        self._distribution_pulses = []
        self._service_pulses = []
        if not self._subs_used:
            return
        groups = {}
        for col, row, _kind, _e in self._buildings:
            groups.setdefault((col // FEEDER_SIZE, row // FEEDER_SIZE), []).append((col, row))
        for group_key in sorted(groups):
            buildings = groups[group_key]
            col, row = min(buildings, key=lambda cr: self._priority.get(cr, 1.0))
            sx, sy = iso_xy(col, row)
            point = (sx + ox + TW // 2, sy + oy + TH // 2)
            sub_index = min(self._subs_used,
                            key=lambda i: math.hypot(self._sub_screen[i][0] - point[0],
                                                     self._sub_screen[i][1] - point[1]))
            priority = sum(self._priority.get(cr, 1.0) for cr in buildings) / len(buildings)
            site = TransformerSite(sub_index, (col, row), point, priority, buildings)
            index = len(self._transformers)
            self._transformers.append(site)
            route = street_route(self._sub_sites[sub_index], (col, row),
                                 self._sub_screen[sub_index], point, (ox, oy))
            self._distribution_pulses.append(
                (index, LinePulse(route, seed=abs(hash(("tx", group_key))) & 0xFFFF)))
            # A couple of endpoint branches make the final hop into the blocks
            # legible without covering the whole city in animated lines.
            for end_col, end_row in buildings[::max(1, len(buildings) // 2)][:2]:
                ex, ey = iso_xy(end_col, end_row)
                end = (ex + ox + TW // 2, ey + oy + TH // 2)
                route = street_route((col, row), (end_col, end_row),
                                     point, end, (ox, oy))
                self._service_pulses.append(
                    (index, LinePulse(route, seed=abs(hash(("svc", end_col, end_row))) & 0xFFFF)))
```

(The `route` passed to `LinePulse` runs substation→transformer, and
transformer→house respectively — arc-length 0 in each is the substation or
the transformer, exactly the "originates at source" property the design
needs; nothing else needs to change for that to be true.)

- [ ] **Step 3: Remove `_truncate_path`**

In `ui/iso_city.py`, delete the entire function (it sits right after
`street_route`, before `diamond`):

```python
def _truncate_path(path, frac):
    """First `frac` (0..1) of a polyline's arc length, as a new polyline.
    Used to build a transmission Flow that only animates near the plant end
    of a corridor — the electrons fade out well before the substation rather
    than travelling the whole run."""
    if len(path) < 2:
        return list(path)
    segs = []
    total = 0.0
    for a, b in zip(path, path[1:]):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        segs.append((a, b, d))
        total += d
    if total <= 0:
        return list(path)
    target = total * max(0.0, min(1.0, frac))
    out = [path[0]]
    acc = 0.0
    for a, b, d in segs:
        if acc + d >= target:
            f = (target - acc) / d if d > 0 else 0.0
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            return out
        acc += d
        out.append(b)
    return out
```

Delete this whole block.

- [ ] **Step 4: Rewrite the transmission section of `_bake` — build the real
  conductor paths and use them for both drawing and the electron `Flow`s**

`_bake`'s signature gains an optional 4th parameter (default `None` so the
three direct test call sites in `test_city_model.py` that call `_bake` with
3 args keep working unmodified):

```python
    def _bake(self, rect, population, fleet, ramp_by_key=None):
```

Add right after that line:

```python
        ramp_by_key = ramp_by_key or {}
```

Find the current transmission block (starts at the comment "Transmission,
baked BEFORE the plants..." and ends right before "plant structures, drawn
last..."). Replace the whole block:

```python
        # Transmission, baked BEFORE the plants so conductors pass behind the
        # switchyards they leave from rather than over the top of them.
        self._route_transmission(ox, oy)
        grid = pygame.Surface((w, h), pygame.SRCALPHA)
        for i in self._subs_used:
            _substation(grid, *self._sub_screen[i])
        for _key, _i, path in self._routes:
            first = True
            for (x0, y0), (x1, y1) in zip(path, path[1:]):
                span = math.hypot(x1 - x0, y1 - y0)
                n = max(1, int(span / 46.0))
                towers = [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n)
                          for k in range(n + 1)]
                # double-circuit conductors off the upper crossarm tips (+/-6)
                for a, b in zip(towers, towers[1:]):
                    for arm in (-6, 6):
                        _span(grid, (a[0] + arm, a[1] - 16), (b[0] + arm, b[1] - 16))
                for tx, ty in towers[1 if first else 0:]:
                    _pylon(grid, int(tx), int(ty))
                first = False
        # small flat junction markers at every connection point, drawn last so
        # they sit on top of the conductors and substation kit
        for i in self._subs_used:
            _node(grid, int(self._sub_screen[i][0]), int(self._sub_screen[i][1]), r=4)
        for _key, _i, path in self._routes:
            _node(grid, int(path[0][0]), int(path[0][1]))
        # Transmission is not folded into the city bases — it composites flat
        # over the city in draw(), which is a compositing-order convenience,
        # not a brightness effect: no glow, no dimming scrim.
        self._transmission = grid
```

with:

```python
        # Transmission, baked BEFORE the plants so conductors pass behind the
        # switchyards they leave from rather than over the top of them.
        #
        # `conductor_paths[(key, i)][arm]` collects the SAME elevated, offset
        # tower-by-tower point sequence used to draw each conductor (arm=-6 or
        # +6, at crossarm height y-16) — this is what fixes electrons actually
        # riding the drawn wire instead of a separate, silently mismatched
        # ground-level route. Previously the electron Flow was built from the
        # raw `path` (ground level, no offset) while the art used this
        # elevated/offset geometry independently; they had never been the
        # same points.
        self._route_transmission(ox, oy)
        grid = pygame.Surface((w, h), pygame.SRCALPHA)
        for i in self._subs_used:
            _substation(grid, *self._sub_screen[i])
        conductor_paths = {}
        for key, i, path in self._routes:
            arm_paths = {-6: [], 6: []}
            first = True
            for (x0, y0), (x1, y1) in zip(path, path[1:]):
                span = math.hypot(x1 - x0, y1 - y0)
                n = max(1, int(span / 46.0))
                towers = [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n)
                          for k in range(n + 1)]
                # double-circuit conductors off the upper crossarm tips (+/-6)
                for a, b in zip(towers, towers[1:]):
                    for arm in (-6, 6):
                        _span(grid, (a[0] + arm, a[1] - 16), (b[0] + arm, b[1] - 16))
                for tx, ty in towers[1 if first else 0:]:
                    _pylon(grid, int(tx), int(ty))
                first = False
                for arm in (-6, 6):
                    for tx, ty in towers:
                        pt = (tx + arm, ty - 16)
                        if not arm_paths[arm] or arm_paths[arm][-1] != pt:
                            arm_paths[arm].append(pt)
            conductor_paths[(key, i)] = arm_paths
        # small flat junction markers at every connection point, drawn last so
        # they sit on top of the conductors and substation kit
        for i in self._subs_used:
            _node(grid, int(self._sub_screen[i][0]), int(self._sub_screen[i][1]), r=4)
        for _key, _i, path in self._routes:
            _node(grid, int(path[0][0]), int(path[0][1]))
        # Transmission is not folded into the city bases — it composites flat
        # over the city in draw(), which is a compositing-order convenience,
        # not a brightness effect: no glow, no dimming scrim.
        self._transmission = grid
```

- [ ] **Step 5: Build the electron `Flow`s from the real conductor paths, with
  ramp-derived speed**

Find this block later in `_bake` (right after the plant structures loop):

```python
        # One live flow per transmission route, then a visible distribution
        # graph from substations through neighbourhood transformers to blocks.
        # Electrons only travel the first slice of each corridor, near the
        # plant — the point is "this plant is generating," not an animated
        # flow all the way to the substation.
        ELECTRON_REACH = 0.4
        self._flows = {(k, i): Flow(_truncate_path(path, ELECTRON_REACH),
                                    seed=abs(hash((k, i))) & 0xFFFF)
                       for k, i, path in self._routes}
        self._build_distribution(ox, oy)
        for _index, flow in self._distribution_flows:
            for a, b, _length in flow.segs:
                pygame.draw.line(detail_day["gameplay"], CONDUCTOR, a, b, 1)
                _pole(detail_day["gameplay"], int(a[0]), int(a[1]))
            if flow.segs:
                last = flow.segs[-1][1]
                _pole(detail_day["gameplay"], int(last[0]), int(last[1]))
        for _index, flow in self._service_flows:
            for a, b, _length in flow.segs:
                pygame.draw.line(detail_day["inspection"], shade(CONDUCTOR, 1.1), a, b, 1)
                _pole(detail_day["inspection"], int(a[0]), int(a[1]), h=4)
```

Replace with:

```python
        # Two electron Flows per corridor -- one per physical conductor,
        # built from the exact elevated/offset points the wire was drawn
        # with (conductor_paths, above) -- so pulses ride the real wire and
        # arrive exactly at the substation. Speed comes from that plant's
        # real ramp-up latency (see ramp_speed_px_s); rate still comes from
        # output, inside Flow.update_and_draw.
        self._flows = {}
        for key, i, path in self._routes:
            speed = ramp_speed_px_s(ramp_by_key.get(key, RAMP_LATENCY_MAX_S))
            arm_paths = conductor_paths[(key, i)]
            self._flows[(key, i)] = [
                Flow(arm_paths[arm], speed_px_s=speed,
                    seed=abs(hash((key, i, arm))) & 0xFFFF)
                for arm in (-6, 6)
            ]
        self._build_distribution(ox, oy)
        for _index, pulse in self._distribution_pulses:
            for a, b, _length in pulse.segs:
                pygame.draw.line(detail_day["gameplay"], CONDUCTOR, a, b, 1)
                _pole(detail_day["gameplay"], int(a[0]), int(a[1]))
            if pulse.segs:
                last = pulse.segs[-1][1]
                _pole(detail_day["gameplay"], int(last[0]), int(last[1]))
        for _index, pulse in self._service_pulses:
            for a, b, _length in pulse.segs:
                pygame.draw.line(detail_day["inspection"], shade(CONDUCTOR, 1.1), a, b, 1)
                _pole(detail_day["inspection"], int(a[0]), int(a[1]), h=4)
```

Add the import for `RAMP_LATENCY_MAX_S` alongside the other `grid_flow`
imports:

```python
from ui.grid_flow import Flow, LinePulse, ramp_speed_px_s, RAMP_LATENCY_MAX_S
```

(Falling back to `RAMP_LATENCY_MAX_S` — the slowest real value, nuclear's —
for an unknown key is a deliberately conservative default: better to render
an unexpectedly slow pulse than to silently invent a fast one for a plant
whose real latency wasn't found.)

- [ ] **Step 6: Thread `ramp_by_key` through `prepare()`**

In `prepare`, change:

```python
    def prepare(self, rect, state):
        """Ensure camera, world layers, and plant markers exist for this frame."""
        population = state_population(state)
        fleet = tuple(sorted(s.key for s in state.sources if s.max_output_mw > 0))
        world_size = required_world_size(rect)
        key = (world_size, round(population / 5000.0), fleet)
        if key != self._key:
            self._key = key
            self._bake(rect, population, fleet)
```

to:

```python
    def prepare(self, rect, state):
        """Ensure camera, world layers, and plant markers exist for this frame."""
        population = state_population(state)
        fleet = tuple(sorted(s.key for s in state.sources if s.max_output_mw > 0))
        world_size = required_world_size(rect)
        key = (world_size, round(population / 5000.0), fleet)
        if key != self._key:
            self._key = key
            ramp_by_key = {s.key: s.ramp_up_latency for s in state.sources}
            self._bake(rect, population, fleet, ramp_by_key)
```

(Ramp latencies are fixed per source class in this game — no runtime
upgrades — so they don't need to be part of the cache `key` tuple; they only
need to be available *when* a bake actually happens.)

- [ ] **Step 7: Rename and rewrite `_draw_transmission` → `_draw_power_flow`**

Replace:

```python
    def _draw_transmission(self, layer, state, dt):
        """Small electron pulses out along the first slice of each plant's
        transmission corridor (see ELECTRON_REACH in _bake) — the point is
        "this plant is generating power," not an animated flow across the
        whole grid. Distribution shows its state through window-lighting
        only (see _draw_lights); it never animates particles.

        Rate follows `actual_pct` — the ramped output, not what the player just
        asked for — so a plant that has been throttled back keeps its line lit
        until it has actually wound down, which is the lag the whole game is
        about. A plant at zero leaves a dark but still-drawn line: a dead
        circuit is still a circuit.
        """
        by_key = {s.key: s for s in state.sources}
        for (key, i), flow in self._flows.items():
            src = by_key.get(key)
            out = 0.0 if src is None or src.max_output_mw <= 0 else src.actual_pct
            color = src.color if src is not None else (120, 200, 255)
            frac = state.line_overload_frac.get(key, 0.0)
            flow.update_and_draw(layer, out, dt, color=color, overload=frac)
```

with:

```python
    def _draw_power_flow(self, layer, state, dt):
        """Per-frame animation for the whole delivery chain.

        Transmission: individual electron pulses, one Flow per conductor per
        corridor, riding the real elevated/offset conductor geometry and
        arriving exactly at the substation. Rate follows `actual_pct` — the
        ramped output, not what the player just asked for — so a plant that
        has been throttled back keeps its line lit until it has actually
        wound down. A plant at zero leaves a dark but still-drawn line: a
        dead circuit is still a circuit. Speed is fixed per Flow at bake
        time from the plant's real ramp-up latency (see ramp_speed_px_s).

        Distribution and service lines: no discrete particles — a travelling
        LinePulse wave, present only while that branch is actually
        energised (same served/priority gate the window-lighting ring model
        uses), so a dead feeder just stays dark and static.
        """
        by_key = {s.key: s for s in state.sources}
        for (key, i), flows in self._flows.items():
            src = by_key.get(key)
            out = 0.0 if src is None or src.max_output_mw <= 0 else src.actual_pct
            color = src.color if src is not None else (120, 200, 255)
            frac = state.line_overload_frac.get(key, 0.0)
            for flow in flows:
                flow.update_and_draw(layer, out, dt, color=color, overload=frac)

        served = served_fraction(state.fill_pct_display)
        for index, pulse in self._distribution_pulses:
            energised = self._transformers[index].priority < served
            pulse.draw(layer, self.t, energised)
        for index, pulse in self._service_pulses:
            energised = self._transformers[index].priority < served
            pulse.draw(layer, self.t, energised)
```

- [ ] **Step 8: Update the one call site**

In `draw()`, change:

```python
        self._draw_transmission(layer, state, dt)
```

to:

```python
        self._draw_power_flow(layer, state, dt)
```

- [ ] **Step 9: Checkpoint — import check**

Run (from `D:/Github/gridmanager`):
`./.venv39/Scripts/python.exe -c "import sys; sys.path.insert(0,'energy_grid_game'); import ui.iso_city; print('import ok')"`
Expected: `import ok`, no traceback.

---

## Task 3: Update `test_city_model.py` for the renamed/removed pieces

**Files:**
- Modify: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: `IsoCity._flows` (now `dict[(key,i), list[Flow]]`),
  `IsoCity._distribution_pulses`/`_service_pulses` (renamed, `LinePulse`
  contents), from Task 2.

- [ ] **Step 1: Remove the `_truncate_path` import and its test**

Change the import line (currently ends with
`solar_lot_polygon, _truncate_path)`):

```python
from ui.iso_city import (street_route, cooling_tower_width, solar_panel_layout,
                         gas_cc_train_layout, centered_ellipse_rect,
                         solar_lot_polygon, _truncate_path)
```

to:

```python
from ui.iso_city import (street_route, cooling_tower_width, solar_panel_layout,
                         gas_cc_train_layout, centered_ellipse_rect,
                         solar_lot_polygon)
```

Delete this whole test function:

```python
def test_truncate_path_stops_short_of_the_end():
    path = [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]
    half = _truncate_path(path, 0.5)
    assert half[-1] == (100.0, 0.0)
    quarter = _truncate_path(path, 0.25)
    assert quarter[-1] == (50.0, 0.0)
    full = _truncate_path(path, 1.0)
    assert full[-1] == (200.0, 0.0)
```

- [ ] **Step 2: Rename field references**

Find `test_distribution_graph_connects_every_building_cluster` and change:

```python
    assert city._transformers
    assert len(city._distribution_flows) == len(city._transformers)
    assert city._service_flows
```

to:

```python
    assert city._transformers
    assert len(city._distribution_pulses) == len(city._transformers)
    assert city._service_pulses
```

(The rest of that test — everything about `city._routes` and switchyard
anchors — is about the RAW route, which Task 2 does not change, so it stays
exactly as-is.)

- [ ] **Step 3: Add a test that electrons ride the real conductor geometry**

Add near `test_distribution_graph_connects_every_building_cluster`:

```python
def test_electron_flows_ride_the_drawn_conductor_geometry():
    """Each corridor's electron Flows must be built from the SAME elevated,
    offset points the double-circuit wire is drawn with -- not a separate,
    silently mismatched ground-level route (the original bug)."""
    viewport = pygame.Rect(0, 0, 1000, 460)
    fleet = ("nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro")
    city = IsoCity(None)
    city._bake(viewport, 100_000, fleet, {"nuclear": 45, "coal": 20, "gas": 3,
                                          "peaker": 1.5, "solar": 1, "wind": 2,
                                          "hydro": 5})
    assert city._flows
    for (key, i), flows in city._flows.items():
        assert len(flows) == 2   # both conductors of the double-circuit bundle
        route_end = city._sub_screen[i]
        for flow in flows:
            # the Flow's own endpoint (from its own path) must be within one
            # conductor offset (6px) plus crossarm height (16px) of the
            # substation's screen anchor -- i.e. it terminates AT the
            # substation, not partway across open country
            dist = math.hypot(flow.end[0] - route_end[0], flow.end[1] - route_end[1])
            assert dist < 20, f"{key} conductor ends {dist:.1f}px from its substation"
```

`test_city_model.py` already has `import math` at the top of the file (line
5) — no new import needed.

- [ ] **Step 4: Add a test that speed is threaded from real ramp latencies**

Add:

```python
def test_baked_electron_speed_reflects_real_ramp_latency():
    """A fast-ramping plant's electrons must actually travel faster than a
    slow-ramping plant's, using the SAME real ramp_up_latency values the
    simulation itself uses (sources/*.py), not invented numbers."""
    from ui.grid_flow import ramp_speed_px_s
    viewport = pygame.Rect(0, 0, 1000, 460)
    fleet = ("nuclear", "peaker")
    city = IsoCity(None)
    city._bake(viewport, 100_000, fleet, {"nuclear": 45.0, "peaker": 1.5})
    nuclear_speed = next(f.speed_px_s for (key, _i), flows in city._flows.items()
                         if key == "nuclear" for f in flows)
    peaker_speed = next(f.speed_px_s for (key, _i), flows in city._flows.items()
                        if key == "peaker" for f in flows)
    assert peaker_speed > nuclear_speed
    assert nuclear_speed == ramp_speed_px_s(45.0)
    assert peaker_speed == ramp_speed_px_s(1.5)
```

- [ ] **Step 5: Run the updated test file — must PASS**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_city_model.py`
Expected: every test prints `ok`, including the two new ones, ending with
"all city model checks passed".

- [ ] **Step 6: Checkpoint — run the whole suite**

Run all six from `D:/Github/gridmanager`:
```
./.venv39/Scripts/python.exe energy_grid_game/test_pricing.py
./.venv39/Scripts/python.exe energy_grid_game/test_congestion.py
./.venv39/Scripts/python.exe energy_grid_game/test_dialogue_schema.py
./.venv39/Scripts/python.exe energy_grid_game/test_capacities.py
./.venv39/Scripts/python.exe energy_grid_game/test_instructional.py
./.venv39/Scripts/python.exe energy_grid_game/test_city_model.py
./.venv39/Scripts/python.exe energy_grid_game/test_grid_flow.py
```
Expected: all seven print their "all ... checks passed" line.

---

## Task 4: Render-verify pass + feel-pass review

**Files:** none changed; this task only runs, inspects, and (if the feel-pass
finds something) hands back a specific, scoped fix to apply.

- [ ] **Step 1: Render and eyeball the fix directly**

Run: `./.venv39/Scripts/python.exe tools/capture_moments.py <dir>` (any
writable dir) from `D:/Github/gridmanager`. Open `21_delivery_chain_close.png`
and a 2x/4x zoom shot. Confirm: electron dots sit exactly on the two drawn
conductor wires at every tower (not floating off to the side, the original
bug); a plant's electrons visibly arrive at the substation (the existing
arrival-flash ring fires there); distribution and service lines show a soft
traveling brightness wave (not a uniform blink, not discrete dots); an
unserved feeder (drop supply until `homes_without_power` is nonzero, or
inspect a frame where `served_fraction` is low) shows no pulse on its
branches.

- [ ] **Step 2: Compare plant speeds directly**

Render a frame with nuclear and a peaker both online (the existing
`21_delivery_chain_close` capture already runs gas/nuclear/peaker together —
confirm in the harness script, or set them explicitly per
`tools/capture_moments.py`'s existing pattern for nudging plants). Confirm by
eye: the peaker's/gas's electrons visibly move faster along their corridor
than nuclear's along its own.

- [ ] **Step 3: Dispatch a `juice:juice-consultant` feel-pass**

Per the spec's plugin-usage commitment, run a feel-pass review on the
running result (not a spec — the actual rendered captures from Steps 1-2).
Ask specifically: does the ramp-speed contrast (peaker vs. nuclear) read as
intentional or as jitter; does the distribution wave feel alive or
mechanical; is `PULSE_BAND_FRAC` (0.20) / `PULSE_SPEED_PX_S` (50.0) /
`SPEED_MIN_PX_S`/`SPEED_MAX_PX_S` (40/220) tuning off in either direction.
Apply any concrete numeric tuning it recommends directly to the constants in
`ui/grid_flow.py` (Task 1, Steps 4-5), then re-render and re-check Steps 1-2.

- [ ] **Step 4: Final full-suite check**

Re-run all seven test files listed in Task 3 Step 6. Expected: all pass.

---

## Self-review notes

- Spec coverage: Goal 1 (exact geometry, arrives at substation) → Task 2
  Steps 4-5, Task 3 Step 3. Goal 2 (rate = output) → unchanged code, already
  correct, no regression risk since Task 1 only touches speed. Goal 3
  (speed = ramp latency) → Task 1 Steps 3-4, Task 3 Step 4. Goal 4 (full
  chain distinctness, wave not particles downstream) → Task 1 Step 5, Task 2
  Steps 2 and 7. Goal 5 (accessibility) → `LinePulse` design (smoothstep
  easing, band never covers the whole line, deterministic per-branch
  offset) + Task 4 Step 1 visual confirmation.
- No pytest: all new tests are self-running assert modules matching the
  repo's existing convention.
- No git: every "Commit" step became a "Checkpoint" per the repo rule.
- Type consistency: `Flow(path, cap=, seed=, speed_px_s=)`,
  `LinePulse(path, seed=)` / `.draw(surf, t, energised)`, and
  `ramp_speed_px_s(latency_s) -> float` are defined once in Task 1 and used
  identically in Tasks 2 and 3.
- `_bake`'s new 4th parameter (`ramp_by_key=None`) is backward compatible
  with all three existing direct-call test sites in `test_city_model.py`
  that don't pass it — confirmed by grep before writing this plan.
