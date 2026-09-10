# Deliberate Grid Diagram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: this plan is executed by the
> controller directly, iteratively, with the capture-harness render/eyeball
> loop as the verification method for visual tasks (the same approach used
> successfully for the prior transmission-hero pass in this project) — NOT
> dispatched to fresh subagents. See "Execution note" at the end.

**Goal:** Make the electricity delivery chain (generation → switchyard →
transmission → substation → distribution) the unmistakable, accurate, visual
subject of the isometric city scene, in clean flat pixel art — replacing the
previous session's bright/glowing "SCADA hero" treatment.

**Architecture:** Targeted evolution of `ui/iso_city.py`, not a rewrite.
`_layout`/`_place_plants`/`_route_transmission`/`_build_distribution` already
place the city, plants, and substations **deterministically** from a fixed
seed and fixed bearings — every game already renders the same composition for
a given viewport/fleet, satisfying "fixed composed tableau" as-is. The real
gaps are: (1) strip the additive glow/bright-cyan styling back to flat and
accurate, (2) give distribution real pole art distinct from transmission
towers, (3) confine electron animation to near the generating plants only,
(4) tighten the palette/density so the town reads clean and compact.

**Tech Stack:** Python 3.9 (`.venv39`), pygame 2.6. Tests are plain-assert
self-runner modules (no pytest), run via
`./.venv39/Scripts/python.exe energy_grid_game/<test>.py` from
`D:/Github/gridmanager`. No git operations — the user handles version control.

## Global Constraints

- No SCADA-style bright glow layer, no haloed "bus node" markers. Conductors
  are flat steel-grey; a plant's colour is reserved for its electron dots and
  the (unchanged) HUD/dial UI — never painted onto the wires. (Spec §"Design/
  the delivery chain".)
- Electrons: small warm dots, spawn at each plant's switchyard, rate ∝
  `actual_pct`, fade to nothing **well before** the substation (a fixed
  fraction of the corridor, not the whole run). **No** particle animation on
  distribution/service lines — those show state only via window-lighting.
  (Spec §"Electrons".)
- Distribution must be a **visually distinct, real pole structure** — short,
  single crossarm, single thin conductor, roughly 1/3 the height of a
  transmission tower (`_pylon` uses `h=18`) — not a bare line. (Spec §"The
  delivery chain".)
- The height/scale difference between transmission towers and distribution
  poles, and between a substation yard and a single pole, IS the voltage
  lesson — must read at a glance. (Spec Goal 1.)
- Congestion's hot-colour overload cue on a plant's own transmission corridor
  is explicitly **exempt** from "no glow" — it signals a real fault state and
  must keep working via `state.line_overload_frac`. (Spec §"What's
  preserved".)
- Preserve unchanged: simulation (`game_state.py`), plant dials
  (`ui/plant_pins.py`), the two-input illumination model (`activity`/
  `served`), the HUD goal-framing/time-of-day demand curve from the prior
  session, and `IsoCity`'s public interface (`draw`, `prepare`,
  `plant_markers`, `draw_homes_label`, `pan_by`, `zoom_at`, `focus_plant`,
  `.camera`).
- All severity/overload animation stays smooth, capped near/under ~3 Hz, no
  large-area strobe (existing module-docstring rule; must survive).
- Keep `test_city_model.py` green throughout; extend it where behaviour
  changes (electron fade truncation, no-distribution-particles, pole
  drawing) rather than deleting coverage.

---

## Task 1 — Revert the glow/SCADA styling to flat and accurate

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
  - constants block (~L350-370): `CONDUCTOR`, `NODE_CORE`, `NODE_HOT`,
    `CITY_BACKDROP_SCRIM`, `TRANSMISSION_GLOW_MULT`
  - `_node()` (~L956-964)
  - `IsoCity.__init__` (~L1483-1487): `_transmission_glow`, `_backdrop_scrim`
    fields
  - `_bake()` transmission section (~L1959-2000): the glow-bake and
    scrim-bake blocks
  - `draw()` composite (~L2170-2186): the scrim-blit and additive-glow-blit
    lines

**Interfaces:** None new. Removes fields/constants other tasks don't depend
on (confirmed: no other code in the file reads `_transmission_glow` or
`_backdrop_scrim` outside `_bake`/`draw`).

- [ ] **Step 1: Flatten the conductor and node colours**

Replace the constants block:

```python
# Transmission-hero line + node colours: a luminous steel-cyan that reads as
# both a physical energised conductor and a bright trace on an operator's
# one-line diagram (the middle ground between the two references).
CONDUCTOR = (120, 200, 210)
NODE_CORE = (170, 234, 230)
NODE_HOT = (245, 255, 252)
```

with:

```python
# Transmission conductor + junction-marker colours: flat steel, not glowing —
# the delivery chain is legible through accurate shape and scale (tall lattice
# tower vs. short pole vs. a substation yard), not through decorative light.
CONDUCTOR = (94, 100, 110)
JUNCTION = (150, 154, 162)
```

- [ ] **Step 2: Simplify `_node` into a plain junction marker**

Replace `_node` (currently draws three concentric glow rings plus a hot
centre):

```python
def _node(surf, x, y, r=3, color=NODE_CORE):
    """A bright SCADA-style bus/connection node: a soft ring, a filled marker and
    a hot centre, so every connection point on the grid reads as a node on a
    one-line diagram. `surf` must be SRCALPHA."""
    pygame.draw.circle(surf, (*color, 60), (x, y), r + 3)
    pygame.draw.circle(surf, (*color, 120), (x, y), r + 1)
    pygame.draw.circle(surf, color, (x, y), r)
    pygame.draw.circle(surf, NODE_HOT, (x, y), max(1, r - 2))
```

with:

```python
def _node(surf, x, y, r=3, color=JUNCTION):
    """A small flat junction marker at a connection point — a plain filled
    circle with a dark edge, matching the rest of the kit's flat pixel style.
    Not a glow: the delivery chain reads through shape and scale, not light."""
    pygame.draw.circle(surf, STEEL_DARK, (x, y), r + 1)
    pygame.draw.circle(surf, color, (x, y), r)
```

- [ ] **Step 3: Remove the glow-bake and backdrop-scrim bake**

In `_bake`, delete these lines (the additive-glow build and the scrim build):

```python
        # Additive glow, baked once (downscale/upscale blur). Under additive
        # blending the dark steel towers add ~nothing, so the halo reads off the
        # bright conductors and node markers — the operator-screen glow.
        gw, gh = max(1, w // 2), max(1, h // 2)
        blur = pygame.transform.smoothscale(grid, (gw, gh))
        glow = pygame.transform.smoothscale(blur, (w, h))
        glow.fill((TRANSMISSION_GLOW_MULT,) * 3, None, pygame.BLEND_RGB_MULT)
        self._transmission_glow = glow
        # Dark scrim that knocks the whole city backdrop back so the grid is the
        # hero. Cached once; one blit per frame.
        self._backdrop_scrim = pygame.Surface((w, h), pygame.SRCALPHA)
        self._backdrop_scrim.fill((6, 8, 14, CITY_BACKDROP_SCRIM))
```

Also delete the now-unused constants `CITY_BACKDROP_SCRIM` and
`TRANSMISSION_GLOW_MULT` from the constants block, and delete the
`self._transmission_glow = None` / `self._backdrop_scrim = None` lines from
`__init__`.

- [ ] **Step 4: Remove the scrim/glow composite in `draw()`**

Find and delete these lines from `draw()` (they sit between the vehicle/
lights block and the `layer = self._overlay` block):

```python
        # --- city recedes: a dark scrim knocks the whole backdrop back so the
        #     transmission grid is the hero (the SCADA-wall read) ---
        world.blit(self._backdrop_scrim, (0, 0))

        # --- transmission hero: bright glowing grid over the dimmed city. Glow
        #     first (additive), then the crisp towers / conductors / nodes. ---
        world.blit(self._transmission_glow, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
        world.blit(self._transmission, (0, 0))
```

Replace with a plain composite (transmission drawn crisp, no scrim, no glow):

```python
        # Transmission is composited plainly over the city — flat and legible,
        # not glowing. Its accuracy (real shapes, real scale) is the teaching
        # device, not decorative light.
        world.blit(self._transmission, (0, 0))
```

- [ ] **Step 5: Render and eyeball**

Run: `cd D:/Github/gridmanager && ./.venv39/Scripts/python.exe tools/capture_moments.py /tmp/grid_t1`
(or any writable dir). Expected: "captured NN moments", no traceback. Open
`06_game.png` and `16_region_night.png`: conductors are flat grey, no bloom/
glow around the wires, junction markers are small plain dots, city is at
normal brightness (no dark scrim). Nuclear/gas/etc. dials still float on
their plants (unrelated to this task; just confirm nothing else broke).

- [ ] **Step 6: Run the full test suite**

Run each from `D:/Github/gridmanager`:
```
./.venv39/Scripts/python.exe energy_grid_game/test_pricing.py
./.venv39/Scripts/python.exe energy_grid_game/test_congestion.py
./.venv39/Scripts/python.exe energy_grid_game/test_dialogue_schema.py
./.venv39/Scripts/python.exe energy_grid_game/test_capacities.py
./.venv39/Scripts/python.exe energy_grid_game/test_instructional.py
./.venv39/Scripts/python.exe energy_grid_game/test_city_model.py
```
Expected: all six print their "all ... checks passed" line.

---

## Task 2 — Real distribution-pole art, distinct from transmission towers

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
  - new primitive near `_pylon`/`_span` (~L902-937)
  - `_bake()` distribution-line section (~L2020-2026)

**Interfaces:**
- Consumes: `Flow.segs` (list of `(a, b, length)` 3-tuples — already produced
  by `Flow.__init__` via `path_length`, unchanged) on
  `self._distribution_flows` / `self._service_flows` (list of
  `(index, Flow)` tuples, unchanged).
- Produces: `_pole(surf, x, y, h=6)` — a new module-level drawing function,
  callable by any later task the same way `_pylon` is.

- [ ] **Step 1: Add the `_pole` primitive**

Insert directly after `_pylon` (before `_span`):

```python
def _pole(surf, x, y, h=6):
    """A distribution pole: one short post, one crossarm, two insulators.
    Deliberately small and plain next to `_pylon` — the height difference
    between a transmission tower (h=18, three crossarms, splayed lattice legs)
    and this single post is the step-down lesson made visible without a label."""
    pygame.draw.line(surf, STEEL_DARK, (x, y), (x, y - h), 1)
    half = 3
    pygame.draw.line(surf, shade(STEEL_DARK, 0.85), (x - half, y - h + 1),
                     (x + half, y - h + 1), 1)
    pygame.draw.line(surf, (150, 154, 162), (x - half, y - h + 1),
                     (x - half, y - h + 3), 1)
    pygame.draw.line(surf, (150, 154, 162), (x + half, y - h + 1),
                     (x + half, y - h + 3), 1)
```

- [ ] **Step 2: Draw poles along every distribution and service route**

In `_bake`, replace the distribution-line block:

```python
        for _index, flow in self._distribution_flows:
            for a, b, _length in flow.segs:
                pygame.draw.line(detail_day["gameplay"], (82, 88, 92), a, b, 1)
        for _index, flow in self._service_flows:
            for a, b, _length in flow.segs:
                pygame.draw.line(detail_day["inspection"], (104, 110, 112), a, b, 1)
```

with (poles at each segment start, spaced by walking segments — routes are
already short polylines from `street_route`, so one pole per segment
endpoint reads as a real pole line without needing sub-segment interpolation):

```python
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

(Service-branch poles are drawn slightly shorter, `h=4`, since they are the
final hop into a block — the smallest structure in the whole chain.)

- [ ] **Step 3: Render and eyeball**

Run the capture harness again. Zoom in on `21_delivery_chain_close.png` and a
2x/4x zoom shot (`12_zoom_2x_day.png`, `13_zoom_4x_day.png`): distribution
routes now show small poles with a crossarm, visually distinct from (and much
shorter than) the transmission towers on the same frame; the substation yard
is still clearly the largest piece of kit.

- [ ] **Step 4: Run `test_city_model.py`**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_city_model.py`
Expected: still passes (no assertions reference the removed literal colours
`(82, 88, 92)` / `(104, 110, 112)` — confirm with a quick grep first:
`grep -n "82, 88, 92\|104, 110, 112" energy_grid_game/test_city_model.py`
should return nothing; if it does, update that assertion to check for
`CONDUCTOR` instead of the old literal).

---

## Task 3 — Confine electrons to the plant end; kill distribution particles

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
  - new helper near `Flow` usage (~L15-20, or directly above `_bake`)
  - `_bake()` flow-construction line (~L2018)
  - `_draw_transmission()` (~L2272-2304)
- Test: `energy_grid_game/test_city_model.py` (add coverage)

**Interfaces:**
- Consumes: `ui.grid_flow.Flow(path, cap=24, seed=0)` (unchanged constructor —
  do not modify `grid_flow.py`) and `Flow.update_and_draw(surf, output, dt,
  color=PULSE, overload=0.0)` (unchanged).
- Produces: `_truncate_path(path, frac) -> list[tuple[float, float]]` — a new
  module-level helper other rendering code may reuse.

- [ ] **Step 1: Add a path-truncation helper**

Insert above `_bake` (or near `street_route`, which it complements):

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

- [ ] **Step 2: Build transmission flows from the truncated path**

In `_bake`, change:

```python
        self._flows = {(k, i): Flow(path, seed=abs(hash((k, i))) & 0xFFFF)
                       for k, i, path in self._routes}
```

to:

```python
        # Electrons only travel the first slice of each corridor, near the
        # plant — the point is "this plant is generating," not an animated
        # flow all the way to the substation.
        ELECTRON_REACH = 0.4
        self._flows = {(k, i): Flow(_truncate_path(path, ELECTRON_REACH),
                                    seed=abs(hash((k, i))) & 0xFFFF)
                       for k, i, path in self._routes}
```

- [ ] **Step 3: Stop animating distribution/service particles**

In `_draw_transmission`, remove the distribution/service particle loops
(everything from `if self.camera.zoom < 2:` to the end of the method):

```python
        if self.camera.zoom < 2:
            return
        served = served_fraction(state.fill_pct_display)
        branch_levels = {}
        for index, flow in self._distribution_flows:
            transformer = self._transformers[index]
            got, cap = load.get(transformer.sub_index, (0.0, 0.0))
            upstream = got / cap if cap > 0 else 0.0
            level = distribution_level(transformer.priority, served, upstream)
            branch_levels[index] = level
            flow.update_and_draw(layer, level, dt)
        for index, flow in self._service_flows:
            flow.update_and_draw(layer, branch_levels.get(index, 0.0), dt)
```

Replace with nothing (delete the block) and update the method's docstring:

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

The `load` dict built earlier in the method (`load = {}` plus the
`load[i] = (...)` accumulation inside the `for (key, i), flow in
self._flows.items():` loop) was only ever read by the deleted block — remove
that dict and its accumulation too, since the transmission loop no longer
needs it for anything. The transmission loop itself becomes just the four
lines shown in the replacement above (no `load = {}`, no `load[i] = ...`).

`served_fraction` stays (still used by `_draw_lights`). `distribution_level`
becomes fully dead — its only call site was the block just deleted, and
nothing else in the file calls it. Per YAGNI, delete it too:

```python
def distribution_level(priority, served, upstream):
    """Visible downstream flow for one feeder branch."""
    return _clamp01(upstream) if priority < served else 0.0
```

Remove this function definition (currently directly below `served_fraction`)
entirely. Then in `test_city_model.py`, remove `distribution_level` from its
import line (`from ui.iso_city import (..., vehicle_density_for_zoom,
distribution_level)` — drop just that name, keep the rest) and delete the
test function that exercises it:

```python
def test_distribution_level_gates_on_priority_vs_served():
    assert distribution_level(0.2, 0.5, 0.8) == 0.8
    assert distribution_level(0.7, 0.5, 0.8) == 0.0
    assert distribution_level(0.2, 0.5, 0.0) == 0.0
```

(Find this test by its assertions — `distribution_level(0.2, 0.5, 0.8) ==
0.8` — the exact function name in the file may differ slightly; delete
whichever `test_` function contains these three assertions.)

- [ ] **Step 4: Add test coverage for the truncation helper**

In `test_city_model.py`, add (near other pure-function tests — check the
file's existing import block for what's already imported from `ui.iso_city`
and extend it rather than duplicating an import line):

```python
def test_truncate_path_stops_short_of_the_end():
    from ui.iso_city import _truncate_path
    path = [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]
    half = _truncate_path(path, 0.5)
    assert half[-1] == (100.0, 0.0)
    quarter = _truncate_path(path, 0.25)
    assert quarter[-1] == (50.0, 0.0)
    full = _truncate_path(path, 1.0)
    assert full[-1] == (200.0, 0.0)
```

Add `test_truncate_path_stops_short_of_the_end` to the file's `__main__`
test-collection loop if that loop is a fixed list rather than an automatic
`test_`-prefix scan (check the bottom of the file first — the project's other
test files auto-collect via `globals().items()` starting with `test_`, so this
likely needs no registration, only confirm by reading the file's tail).

- [ ] **Step 5: Run and verify**

```
./.venv39/Scripts/python.exe energy_grid_game/test_city_model.py
```
Expected: includes `ok  test_truncate_path_stops_short_of_the_end` and ends
with the file's existing "all city model checks passed" line.

- [ ] **Step 6: Render and eyeball**

Run the capture harness. On `06_game.png`/`21_delivery_chain_close.png`,
confirm: electron dots appear only near each plant's switchyard end of its
corridor and vanish partway along, never reaching the substation; the
distribution poles/lines from Task 2 are present but completely static (no
dots on them at any zoom).

---

## Task 4 — Clean, compact palette and density

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
  - `CAPACITY` (~L241-247), `ILLUSTRATIVE_POPULATION` (~L225),
    `MAX_EXTENT` (~L257)
  - `HOUSE_SETS` / `SHOP_SETS` (search for these constants near the palette
    block) and `CANOPY_DARK`/`CANOPY_MID`/`CANOPY_LIGHT`, `GRASS`, `FIELDS`
  - `_woodland` density constant (the `< 10` threshold at ~L345, already
    tuned once this session — revisit only if the render still looks busy)

**Interfaces:** None — pure constant tuning, no signature changes.

This task is **render-verified iteration**, not a fixed prescription — the
brainstorming spec explicitly leaves exact counts open ("left to
implementation to converge visually... via the capture harness"). Steps below
give a concrete starting point and the loop to run; do not treat the numeric
deltas as final without rendering.

- [ ] **Step 1: Establish a before snapshot**

Run the capture harness to a fresh dir and keep it for comparison (e.g.
`/tmp/grid_before`).

- [ ] **Step 2: Reduce built-up extent and building capacity ceiling**

Try `MAX_EXTENT = 0.58` (from `0.66`) so the town occupies noticeably less of
the frame, leaving more open country for the plants to stand out in (this
directly serves Goal 2, "clean pixel isometric city ... not a dense
procedural sprawl").

- [ ] **Step 3: Tighten the roof/wall palette**

Open the `HOUSE_SETS`/`SHOP_SETS` constant (a list of `(roof, wall_light,
wall_dark)` tuples). Reduce to 3 sets each instead of the current count, and
nudge each set's saturation/value closer together (fewer competing hues) —
render and compare against `/tmp/grid_before` after this change.

- [ ] **Step 4: Render, compare, iterate**

Run the capture harness to a new dir. Open `06_game.png` side by side with
the before snapshot. If the town still reads busy/sprawling: lower
`ILLUSTRATIVE_POPULATION` (from `15_000`) in increments of ~2000, re-render
each time, until the town reads as a compact, legible place with the plants
and transmission corridors clearly the dominant visual elements. Stop once
that's true — do not over-shrink to the point the city looks empty.

- [ ] **Step 5: Confirm the accessibility rule survived**

Open `24_overload_150.png` / `25_overload_200.png`: the overload/fire wash
must still be smooth, no new flashing introduced by any palette change.

- [ ] **Step 6: Run the full test suite**

Run all six test files listed in Task 1 Step 6. Expected: all pass. (Density/
palette constants are not asserted on by name in `test_city_model.py`, but
population-driven building counts might interact with
`test_baked_region_covers_the_full_stage_at_one_x` or similar — if any test
fails, read its assertion, and adjust the new constant value rather than the
test, unless the test is asserting a specific number that this task
legitimately changes, in which case update the test's expected number to
match and say so in the final report.)

---

## Task 5 — Final verification pass

**Files:** none changed; this task only runs and inspects.

- [ ] **Step 1: Full test suite, one more time**

Run all six test files from Task 1 Step 6. Expected: all six print their
pass line.

- [ ] **Step 2: Full capture set, eyeballed**

Run the capture harness to a fresh directory. Open and check:
- `06_game.png` — day: flat conductors, real poles, compact clean city,
  plants and switchyards clearly the focal infrastructure.
- `16_region_night.png` — night: city lights show served/activity as before
  (unchanged illumination model); transmission is flat-lit, not glowing.
- `11/12/13_zoom_*` — zoom tiers still add detail correctly (regional →
  gameplay → inspection), poles and towers both legible at 4x.
- `21_delivery_chain_close.png` — the full chain (switchyard → tower →
  conductor → substation → pole → building) is traceable in one glance.
- `23/24/25_overload_*` — congestion's hot-corridor cue and the fire/smoke
  overload effects still read clearly (both are exempt from "no glow").
- `17-20_weather_*`, `27/28_*_rush` — nothing else regressed.

- [ ] **Step 3: Confirm mechanics untouched**

Spot-check (reading the diff, not re-deriving): `game_state.py`,
`ui/plant_pins.py`, `ui/hud.py`, `ui/demand_chart.py` have zero changes from
this plan — only `ui/iso_city.py` and `energy_grid_game/test_city_model.py`
were touched.

---

## Execution note

Given this is a single cohesive, taste-driven visual subsystem (palette,
proportion, and spacing consistency benefit from one continuous hand with a
live render-feedback loop, not a blind spec handed to a fresh subagent with
no visual feedback), execute this plan directly and iteratively — render
after each task, compare against the reference mockups and prior captures,
and adjust constants inline before moving on. This mirrors how the prior
transmission-hero increment in this project was executed, which worked well.
