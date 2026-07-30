# Seamless Regional Stage Implementation Plan

> **For Codex:** Use the executing-plans workflow to implement this plan task by
> task, and use test-driven development for each behavior change.

**Goal:** Replace the floating finite city rectangle with a seamless regional
stage that fills the viewport at 1x, integrates time/weather into the world,
adds zoom-aware visual detail, and shows power moving from plants through
switchyards, substations, transformers, homes, and businesses.

**Architecture:** Keep `IsoCity` as the semantic region owner and the existing
`Camera` as the world/screen transform. Size the region from minimum-zoom camera
coverage, build one deterministic layout, and compose shared plus 1x/2x/4x
cached art layers. Move full-frame sky behavior into a small atmosphere model:
the city consumes its palette/material response, while a renderer draws only
clipped dynamic weather overlays. Extend existing `Flow` routes into a
deterministic distribution graph; switchyards remain render-only anchors.

**Tech Stack:** Python 3, pygame, existing procedural isometric renderer, direct
assertion-based test scripts, and the existing headless screenshot harness.

**Design reference:**
`docs/superpowers/specs/2026-07-30-seamless-regional-stage-design.md`

---

## Task 1: Lock the Seamless-World and LOD Contracts in Tests

**Files:**

- Modify: `energy_grid_game/test_city_model.py`
- Modify: `energy_grid_game/ui/iso_city.py`

### Step 1: Add failing coverage tests

Add pure tests for:

- minimum world size at 1x for several viewport sizes;
- legal camera centers never exposing outside-world pixels;
- the visible world rectangle matching the full viewport at 1x;
- exact zoom-to-LOD mapping for 1, 2, and 4;
- additive detail policy: 1x shared/regional, 2x shared/regional/gameplay,
  4x shared/regional/gameplay/inspection.

Prefer small pure helpers such as `required_world_size(viewport, min_zoom,
overscan)` and `detail_levels_for_zoom(zoom)` so tests do not need a full bake.

### Step 2: Run the focused test and confirm failure

Run:

```bash
.venv/bin/python energy_grid_game/test_city_model.py
```

Expected: new assertions fail because world sizing still divides the stage by
the default 2x zoom and no explicit LOD contract exists.

### Step 3: Implement the minimum pure helpers

In `energy_grid_game/ui/iso_city.py`:

- define the region overscan policy in one place;
- compute world dimensions from 1x coverage;
- expose a direct 1/2/4-to-detail-layer mapping;
- keep unsupported zoom handling with the existing `ZOOMS` contract.

Do not change rendering yet.

### Step 4: Re-run the focused test

Run:

```bash
.venv/bin/python energy_grid_game/test_city_model.py
```

Expected: all city model tests pass.

## Task 2: Make the Regional World Fill Every Legal Camera View

**Files:**

- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/test_city_model.py`

### Step 1: Add an integration-style surface coverage test

Bake a small deterministic region, draw at 1x, 2x, and 4x, move the camera to
each legal extreme, and assert every pixel of the stage receives an opaque
world result. Use a sentinel color behind the stage so exposed gaps are easy to
detect.

Include at least 1000x680, 1400x900, and a wide aspect ratio.

### Step 2: Confirm the test fails at 1x

Run the focused test and verify it reproduces the current centered rectangle
with exposed sentinel pixels.

### Step 3: Replace default-zoom world sizing

Update `_bake()` and `prepare()` so:

- `_world_rect` is derived from minimum-zoom coverage plus overscan;
- layout dimensions and the cache key use the same helper;
- the initial camera center composes city and countryside correctly;
- camera clamp works from the visible rectangle at the active zoom;
- `_present()` always blits a crop large enough to fill the stage.

Retain deterministic layout and avoid a separate concealment fill.

### Step 4: Re-run tests and capture a temporary 1x frame

Run:

```bash
.venv/bin/python energy_grid_game/test_city_model.py
SDL_VIDEODRIVER=dummy .venv/bin/python tools/capture_moments.py /tmp/grid-keeper-region-task2
```

Expected: tests pass and the 1x stage contains continuous terrain with no
visible outer boundary.

## Task 3: Integrate Time and Weather into the World

**Files:**

- Add: `energy_grid_game/ui/atmosphere.py`
- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/main.py`
- Modify: `tools/capture_moments.py`
- Modify: `energy_grid_game/test_city_model.py`
- Remove after migration: `energy_grid_game/ui/sky.py`

### Step 1: Add failing atmosphere tests

Test a pure atmosphere sample for representative dawn, day, dusk, and night
hours plus rain, snow, ice, wind, cloud, and heat events. Assert:

- stable palette/material parameters for the same inputs;
- no API requests a full-frame gradient background;
- precipitation and surface-response flags match the event;
- cloud-shadow and wind directions remain bounded.

Add a render-stack test proving the stage is drawn before clipped dynamic
weather and the HUD is not tinted by world weather.

### Step 2: Implement a minimal atmosphere model

Create `energy_grid_game/ui/atmosphere.py` with:

- a small immutable atmosphere sample derived from `sim_hour` and event kind;
- reusable cloud-shadow and precipitation particles;
- a method that draws only dynamic effects clipped to `city_rect`;
- no gradient background fill and no sun/moon body behind the terrain.

Reuse `ui/time_of_day.py` color calculations rather than duplicating them.

### Step 3: Apply the sample inside the region renderer

In `IsoCity.draw()`:

- use the atmosphere sample for day/night blend and material wash;
- add wet-road/roof, snow/ice, cloud-shadow, and heat response as restrained
  cached or dynamic overlays;
- keep window lighting tied to time and served power;
- avoid allocating a new world-sized wash surface every frame.

### Step 4: Replace the main render order

Change `energy_grid_game/main.py` and `tools/capture_moments.py` to:

1. draw the regional stage;
2. draw clipped atmosphere effects;
3. draw chart, readout, plant pins, HUD, and controls.

Once no imports remain, delete `energy_grid_game/ui/sky.py`.

### Step 5: Verify

Run:

```bash
.venv/bin/python energy_grid_game/test_city_model.py
.venv/bin/python energy_grid_game/test_instructional.py
SDL_VIDEODRIVER=dummy .venv/bin/python tools/capture_moments.py /tmp/grid-keeper-atmosphere
rg -n "SkyLayer|ui\.sky|sky\.draw" energy_grid_game tools
```

Expected: tests pass, captures show weather embedded in terrain, HUD remains
clear, and the final search returns no stale sky-layer references.

## Task 4: Build the Shared Layout and Additive LOD Layer Cache

**Files:**

- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/test_city_model.py`

### Step 1: Add failing LOD cache tests

Assert that:

- zoom changes do not regenerate `_layout()`;
- 1x, 2x, and 4x select the approved additive layer sets;
- repeated draws reuse cached static surfaces;
- resize, population change, or fleet change invalidates all required layers;
- dynamic vehicles, flow, weather, and emergencies are absent from static
  caches.

### Step 2: Split static baking by responsibility

Refactor `_bake()` into the smallest useful set of helpers:

- semantic region layout;
- shared terrain and major road/water layer;
- regional 1x silhouettes and landmarks;
- gameplay 2x detail overlay;
- inspection 4x detail overlay;
- existing day/night and ring-light variants where required.

Do not create three independent world layouts or full-world temporary surfaces
during steady-state rendering.

### Step 3: Compose layers by zoom

In `draw()`, select the additive static layers from `camera.zoom`, then add the
existing dynamic overlay. Preserve cursor-anchored zoom, pan, pin anchors, and
camera clamps.

### Step 4: Verify

Run:

```bash
.venv/bin/python energy_grid_game/test_city_model.py
```

Expected: all cache and camera assertions pass.

## Task 5: Improve Terrain, Districts, Buildings, Roads, and Vehicles

**Files:**

- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/test_city_model.py`
- Modify: `tools/capture_moments.py`

### Step 1: Add deterministic layout assertions

Test that a fixed seed produces stable counts and placement categories for:

- downtown, mixed-use, residential, industrial, and park districts;
- arterial, local, and regional roads;
- farms, woods, water, and open terrain;
- vehicle archetypes and legal road routes.

Tests should validate semantic structure, not fragile pixel hashes.

### Step 2: Improve the regional composition

Using the existing layout rather than a second generator:

- strengthen district identity through building footprints, height, roof type,
  and material families;
- add coherent regional connectors, parking/service areas, parks, and terrain
  parcels;
- reserve transmission corridors and plant access routes;
- maintain negative space around plant controls and inset cards.

### Step 3: Add zoom-aware city art

- 1x: roof/building masses and major-road readability only;
- 2x: facade divisions, selected windows/storefronts, lanes, intersections,
  parking, and sidewalks;
- 4x: entrances, signs, vents, rooftop equipment, balconies, crosswalks, turns,
  curbs, signals, parked vehicles, and sparse pedestrians.

Keep a consistent light direction and original visual language.

### Step 4: Expand vehicle sprites

Create cached procedural sprites for car, van, bus, box truck, and service
vehicle. Higher LODs reveal cabs, wheels, windows, lights, cargo, and shadows;
1x uses simplified marks and fewer vehicles.

### Step 5: Verify visually and behaviorally

Run:

```bash
.venv/bin/python energy_grid_game/test_city_model.py
SDL_VIDEODRIVER=dummy .venv/bin/python tools/capture_moments.py /tmp/grid-keeper-city-art
```

Inspect 1x, 2x, and 4x daytime and nighttime frames for clear hierarchy and no
vehicle traversal through buildings, water, or off-road gaps.

## Task 6: Rebuild Power Sources as Recognizable Campuses

**Files:**

- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/test_city_model.py`

### Step 1: Add plant-campus contract tests

For nuclear, coal, combined-cycle gas, peaker, solar, wind, and hydro, assert:

- a deterministic footprint and local sprite bounds;
- a switchyard visual anchor;
- a service-road or transmission connection anchor;
- zoom-specific detail groups;
- no switchyard simulation fields or input targets are introduced.

### Step 2: Implement original campus silhouettes

Build each approved campus from small cached procedural primitives. Keep each
campus on a tight local surface and retain recognizable 1x silhouettes.

### Step 3: Add gameplay and inspection detail

Add the structures listed in the design specification at 2x and 4x. Include a
fenced switchyard with transformers, breakers, busbars, insulators, and gantries
for every source, but keep it render-only.

### Step 4: Preserve output-driven animation

Keep turbine rotation, exhaust, cooling activity, work lights, and similar live
effects tied to actual source output. Avoid decorative animation that implies a
plant is producing while offline.

### Step 5: Verify

Run:

```bash
.venv/bin/python energy_grid_game/test_city_model.py
```

Inspect a fleet containing every source at all three zooms.

## Task 7: Extend the Electrical Delivery Graph to Buildings

**Files:**

- Modify: `energy_grid_game/ui/grid_flow.py`
- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/test_city_model.py`

### Step 1: Add failing graph and flow tests

For a deterministic region, assert:

- every active plant route reaches a plant switchyard anchor and regional
  substation;
- every served district transformer is reachable from a substation;
- every residential, commercial, and industrial building cluster maps to one
  transformer/feeder branch;
- routes avoid building footprints and prohibited water crossings;
- offline plants produce zero new markers;
- plant-route marker density follows actual output;
- downstream branch activity follows delivered/served power;
- undersupply de-energizes deterministic branches matching the same feeder
  priorities used for building illumination.

### Step 2: Introduce a minimal distribution graph

In `IsoCity`, retain semantic records for:

- plant switchyard visual anchors;
- high-voltage routes;
- regional substations;
- street- or corridor-aligned feeder routes;
- neighborhood transformer sites;
- building clusters served by each transformer.

Keep switchyards out of simulation state. They are waypoints and art anchors
only.

### Step 3: Extend `Flow` without adding a physics engine

Keep the existing arc-length pulse behavior. Add only what the visual chain
needs, such as LOD-dependent marker size/trail, deterministic branch enablement,
and arrival pulses at transformers. Do not add capacity, voltage, loss, or
failure mechanics.

### Step 4: Draw physical infrastructure by LOD

- 1x: major pylons/corridors, substations, simple transformer markers, sparse
  blue flow;
- 2x: conductors, branch routes, switchyards, distribution equipment, and clear
  flow splitting;
- 4x: insulators, crossarms, busbars, cabinets, coils, service pads, fencing,
  and fine flow trails toward building clusters.

Ensure infrastructure is depth-ordered correctly against terrain, buildings,
plants, and vehicles.

### Step 5: Verify

Run:

```bash
.venv/bin/python energy_grid_game/test_city_model.py
```

Visually trace at least one active source all the way to homes and businesses,
then repeat with that source offline and with the grid undersupplied.

## Task 8: Reconcile Plant Pins, Insets, Tutorial Targets, and Resize

**Files:**

- Modify: `energy_grid_game/ui/plant_pins.py`
- Modify: `energy_grid_game/main.py`
- Modify if copy/targets change: `energy_grid_game/ui/instructional_data.py`
- Modify if copy/targets change: `energy_grid_game/ui/tutorial_data.py`
- Modify: `energy_grid_game/test_city_model.py`
- Modify: `energy_grid_game/test_instructional.py`

### Step 1: Add interaction/layout regressions

At each zoom and supported viewport size, assert:

- all 1x plant controls remain within the stage;
- controls do not overlap each other, the chart, or the homes readout;
- controls use the true top-center of asymmetric campus art;
- 2x/4x controls disappear when their campus visual center leaves the view;
- full plant artwork bounds remain inside the baked region at 1x;
- zoom and pan retain the expected anchor under the cursor;
- weather overlays do not intercept clicks;
- tutorial target regions still resolve.

### Step 2: Adjust layout only where evidence requires it

Tune pin de-confliction, artwork-aware anchors, visibility margins, and reserved
regional negative space. Keep the existing plant-control interaction itself.

### Step 3: Verify

Run:

```bash
.venv/bin/python energy_grid_game/test_city_model.py
.venv/bin/python energy_grid_game/test_instructional.py
```

Expected: all interaction and tutorial tests pass.

## Task 9: Replace the Opaque Top Band with Three HUD Islands

**Files:**

- Modify: `energy_grid_game/main.py`
- Modify: `energy_grid_game/ui/hud.py`
- Modify: `energy_grid_game/ui/speed_control.py` only if panel-local placement requires it
- Modify: `tools/capture_moments.py`
- Modify: `energy_grid_game/test_city_model.py`
- Modify: `energy_grid_game/test_instructional.py`

### Step 1: Add full-screen composition and panel-layout tests

Assert that:

- `city_rect` covers the full screen rather than beginning below a HUD band;
- left, center, and right HUD island rectangles remain inside every supported
  viewport and do not overlap;
- HUD islands expose named tutorial target regions;
- the city is drawn before all three panels and weather remains clipped to the
  full-screen stage;
- event and warning banners remain within their owning island's column.

### Step 2: Draw the landscape behind the HUD

Change `compute_layout()` and the render order so `IsoCity` and the atmosphere
layer use the full frame. Keep the bottom chart/readout insets and plant pins as
screen-space overlays. Remove the opaque/gradient top scrim as a structural
separator.

### Step 3: Build three reusable rounded glass panels

Add a small cached panel primitive in `ui/hud.py` and group existing readouts:

- left operations (time/date/weather and controls);
- center grid status (balance, MW, price, warning);
- right score/economics.

Keep the current type hierarchy and semantic colors. Use consistent padding,
corner radius, alpha, border treatment, and compact shared height. Center the
content-sized three-panel group with equal 24px gaps and equal outer margins.
Place active-event and critical warning banners directly below their owning
island without a full-width band.

### Step 4: Reconcile input and tutorial regions

Move speed/zoom/audio click targets with the left island. Update named tutorial
regions from actual layout rectangles, not hard-coded approximations. Confirm
that transparent panel pixels do not intercept map input outside their bounds.

### Step 5: Verify visually and behaviorally

Run:

```bash
.venv/bin/python energy_grid_game/test_city_model.py
.venv/bin/python energy_grid_game/test_instructional.py
SDL_VIDEODRIVER=dummy .venv/bin/python tools/capture_moments.py /tmp/grid-keeper-hud-islands
```

Inspect 1x/2x/4x, noon, night, rain, and snow captures. The terrain must reach
the top edge, all text must remain legible, the three panels must read as
separate islands, and no hidden plant may leave an orphaned control or leader.

## Task 10: Expand Visual Regression Coverage and Performance Checks

**Files:**

- Modify: `tools/capture_moments.py`
- Modify: `SPEC-1.1.md`
- Modify: `README.md` only if run/capture instructions are stale

### Step 1: Add a zoom/time/weather capture matrix

Retain the existing ten moments and add named captures for:

- 1x, 2x, and 4x daytime;
- 1x regional overview at dawn and night;
- rain, snow/ice, wind, and heat at representative zooms;
- balanced, undersupplied, oversupplied, and one-offline-plant states;
- a close view that shows plant -> switchyard -> substation -> transformer ->
  buildings.

Seed all semantic layout and particle randomness. Document which live effects
remain non-byte-stable.

### Step 2: Add or retain a steady-state benchmark

Measure 300 steady-state frames at 1400x900 for each zoom after warm-up. Report
median and worst-frame time. Investigate any default-view median above 16.7 ms
or a material regression from the current approximately 10 ms/frame 4x result.

### Step 3: Update the specification

Document:

- seamless minimum-zoom region coverage;
- time/weather material integration;
- the 1x/2x/4x LOD contract;
- plant campus and switchyard scope;
- the visual distribution chain and blue flow semantics;
- switchyards as aesthetic-only non-gameplay objects.

### Step 4: Run the full verification suite

Run:

```bash
.venv/bin/python -m py_compile \
  energy_grid_game/main.py \
  energy_grid_game/ui/iso_city.py \
  energy_grid_game/ui/atmosphere.py \
  energy_grid_game/ui/grid_flow.py \
  energy_grid_game/ui/plant_pins.py
.venv/bin/python energy_grid_game/test_city_model.py
.venv/bin/python energy_grid_game/test_capacities.py
.venv/bin/python energy_grid_game/test_instructional.py
SDL_VIDEODRIVER=dummy .venv/bin/python tools/capture_moments.py /tmp/grid-keeper-final-captures
git diff --check
```

Expected: compilation and all tests pass, captures complete, no whitespace
errors appear, every stage pixel is covered, and visual inspection confirms the
accepted design at all zooms.

## Execution Notes

- Implement tasks in order; world sizing and atmosphere composition underpin
  every later art task.
- Keep each task reviewable and run its focused verification before continuing.
- Preserve unrelated dirty-worktree changes and existing user artifacts.
- Do not pull, merge, commit, push, or open a pull request without a separate
  user request.
- Do not copy or trace the supplied reference art.
- If performance requires simplification, reduce decorative object density
  before weakening world coverage, operational readability, or input access.
