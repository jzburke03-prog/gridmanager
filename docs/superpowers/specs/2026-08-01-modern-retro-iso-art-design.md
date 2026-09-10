# Modern-retro isometric art overhaul

## Context

The current game has a strong systems foundation: the city renderer is a
deterministic baked isometric world, plant controls attach through `PlantSite`
markers, transmission routes are drawn and animated from baked geometry, and
the newest congestion/transmission work is concentrated in `game_state.py`,
`ui/grid_flow.py`, and `ui/iso_city.py`.

The visual problem is now mostly presentation. The town center still reads as a
small procedural settlement, the generating technologies look less polished
than the rest of the UI, and several large structures sit close enough to the
render bounds that clipping remains a recurring risk. The target is a more
polished indie modern-retro look: still pixel-art and readable at gameplay
scale, but richer, busier, and less placeholder-like.

The user provided five approved source PNG collections:

- `C:/Users/sycho/Downloads/1x1x1.png`
- `C:/Users/sycho/Downloads/1x1x2.png`
- `C:/Users/sycho/Downloads/2x2x2.png`
- `C:/Users/sycho/Downloads/citycenters.png`
- `C:/Users/sycho/Downloads/buildings.png`

These sheets are the source of truth for the visual overhaul. They must be
spliced into curated repo assets before use.

## Goals

1. Replace the current generating-technology static art with curated sprites
   sliced from the provided open-source-style asset sheets.
2. Upgrade the town center into a busier city core using the provided
   city-center, tower, and midrise art.
3. Keep the current city simulation, congestion behavior, transmission routing,
   power-flow timing, plant pins, and scenario/gameplay code behavior intact.
4. Reduce clipping by using actual sprite bounds, visual-center metadata, and
   increased top/edge breathing room where large assets require it.
5. Preserve the current isometric renderer's deterministic bake model and
   visual-regression workflow.
6. Land the result as a modern-retro pixel-art pass, not a fully different
   visual language.

## Non-goals

- No changes to congestion math, pricing, scoring, demand curves, source
  physics, or line-capacity calculations.
- No rewrite of `IsoCity` into a new rendering engine.
- No runtime dependency on the original sheets outside the repo. The game
  should load curated assets from `assets/`.
- No broad UI redesign of HUD panels, menus, tutorial dialogue, or charts.
- No large new animation framework. Live plant cues should remain small,
  procedural, and tied to existing source output.

## Approved Approach

Use a curated slice pack.

The five provided PNG collections will be copied into a documented source
location under `assets/iso/source/` or recorded in an asset README, then sliced
into individual transparent sprites under `assets/iso/`. A small manifest will
map semantic game roles to those sprites and their draw metadata. The renderer
will consume the curated sprites; it will not hard-code sprite-sheet rectangles
throughout gameplay code.

This approach gives a strong visual upgrade while preserving the game's current
rendering contracts. It also makes future replacement or retuning possible
without hiding magic crop coordinates inside the city renderer.

## Asset Pipeline

### Source Preservation

Add an asset note documenting the five user-provided sheets as the approved
source art for this pass. The note should include source filenames, expected
dimensions, and the date they were added. If a later pass identifies the
original library/license URL, that information can be appended without changing
runtime behavior.

Expected dimensions from inspection:

- `1x1x1.png`: 560 x 135
- `1x1x2.png`: 560 x 240
- `2x2x2.png`: 672 x 55
- `citycenters.png`: 280 x 55
- `buildings.png`: 504 x 310

### Curated Output

Create this curated sprite set:

- `assets/iso/buildings/`
- `assets/iso/city_center/`
- `assets/iso/plants/`
- `assets/iso/manifest.json`
- `assets/iso/README.txt`

Each sliced PNG should be tight-cropped to non-transparent pixels, but should
keep enough transparent registration padding if two related variants need a
stable shared origin. The manifest is responsible for metadata that cannot be
inferred safely from pixels.

### Manifest Shape

The manifest should describe sprites by semantic role, not sheet position.
Minimum metadata:

```json
{
  "buildings": {
    "house": [{"file": "buildings/house_red_01.png", "capacity_tier": "house"}],
    "shop": [{"file": "buildings/shop_main_01.png", "capacity_tier": "shop"}],
    "block": [{"file": "buildings/block_01.png", "capacity_tier": "block"}],
    "midrise": [{"file": "buildings/midrise_01.png", "capacity_tier": "midrise"}],
    "tower": [{"file": "buildings/tower_01.png", "capacity_tier": "tower"}]
  },
  "city_center": [
    {"file": "city_center/core_01.png", "base": [14, 43], "footprint": [2, 2]}
  ],
  "plants": {
    "coal": {"file": "plants/coal_01.png", "base": [44, 48], "switchyard_anchor": [64, 45]},
    "nuclear": {"file": "plants/nuclear_01.png", "base": [50, 48], "switchyard_anchor": [70, 45]},
    "gas": {"file": "plants/gas_01.png", "base": [44, 48], "switchyard_anchor": [64, 45]},
    "peaker": {"file": "plants/peaker_01.png", "base": [34, 38], "switchyard_anchor": [50, 35]},
    "solar": {"file": "plants/solar_01.png", "base": [44, 38], "switchyard_anchor": [64, 35]},
    "wind": {"file": "plants/wind_01.png", "base": [52, 45], "switchyard_anchor": [72, 32]},
    "hydro": {"file": "plants/hydro_01.png", "base": [44, 40], "switchyard_anchor": [62, 40]},
    "generic": {"file": "plants/generic_01.png", "base": [36, 38], "switchyard_anchor": [52, 35]}
  }
}
```

Exact filenames and numbers will be chosen during slicing. The important design
point is the contract: `base` is the map anchor, `switchyard_anchor` preserves
transmission takeoff behavior, and building groups map to the existing
population tiers.

## Renderer Design

### Asset Loading

Extend `energy_grid_game/ui/assets.py` with a small `iso_sprite()` or
`iso_manifest()` loader, mirroring existing lazy loading and caching patterns.
It should:

- Load from `assets/iso/`.
- Assert RGBA alpha like the existing asset loader.
- Cache native and scaled surfaces.
- Provide tight bounds or manifest metadata to `iso_city.py`.
- Avoid loading at import time, since Pygame conversion requires a display.

The loader should stay generic enough for city and plant sprites, but small
enough that it does not become a new asset framework.

### Building Sprites

Keep the existing population model:

- `CAPACITY` remains the population-to-footprint contract.
- `_mix()`, `_tier()`, `_density()`, and the solved city extent remain the
  source of layout truth.
- The existing shed-order/light-ring model remains untouched.

Replace or wrap the current procedural `BUILDERS` so each tier can select from
curated sprites. Each building builder should still return `(structure,
lights)` because the renderer depends on a separate light surface for outage
rings. If a sliced sprite has no built-in separate window-light layer, generate
a small procedural light layer aligned to the sprite's visible facade using
manifest hints or conservative window pixels.

For safety, the first implementation can keep the old procedural builders as a
fallback when a sprite is missing. The preferred runtime path should use the
curated art.

### Bustling City Core

Add a city-core placement pass near downtown:

- Reserve a small number of central non-road, non-water tiles for special core
  sprites from `citycenters.png` and high-density building sprites.
- Keep this pass inside the existing layout/bake flow so deterministic captures
  remain stable.
- Do not alter population capacity math in a way that makes city radius shrink
  or jump. If a landmark replaces multiple tiles, account for it as an
  equivalent tower/midrise capacity tier or treat it as visual dressing on top
  of normal buildings.
- Add denser downtown details: more bright windows, a few rooftop accents, and
  stronger but still non-blown-out glow in the existing ring system.

The city should read as a proper busy center at default gameplay zoom, with
recognizable taller structures and more visual variety than the current
procedural polygon buildings.

### Plant Sprites

Replace `_draw_plant_static()` and `_plant_static_sprite()` behavior with
curated plant sprites where available. Preserve the `PlantSite` contract:

- `site.key` continues to map to gameplay source keys.
- `site.sx` and `site.sy` remain logical world anchors.
- `site.sprite` and `site.sprite_offset` remain available for bounds and
  marker visibility.
- `site.visual_dx` and `site.visual_dy` continue to drive pin target placement.
- `site.switchyard_anchor()` continues to return a decorative takeoff point for
  transmission routes.

`SWITCHYARD_TAKEOFF` can be replaced or supplemented by manifest metadata, but
the rest of the routing code should still receive a point in the same
coordinate space. This keeps the transmission overhaul intact.

Live output effects remain procedural and small:

- Steam/smoke for thermal plants.
- Beacons on tall assets at night.
- Solar glint tied to output level.
- Wind blade or sparkle cues only if they do not fight the sliced art.
- Hydro water cue if an appropriate anchor exists.

If a sliced plant sprite already includes a visual feature that conflicts with
the current live effect, tune the effect down rather than changing source
behavior.

### Clipping and Composition

Large city-center and plant sprites should be placed by actual bounds, not
guessed radii.

Changes:

- Use manifest `base` plus sprite bounding rects to compute `sprite_offset`.
- Clamp plant placement against sprite bounds as the current code already does,
  but retune margins based on the larger curated art.
- Increase top breathing room in `required_world_size()` or bake origin if
  tests/captures show tall downtown or power assets clip.
- Keep the existing draw order: terrain/buildings, transmission, plants, then
  live overlays. This preserves conductor readability and plant prominence.

The goal is not to make every sprite tiny enough to fit the old assumptions.
The goal is to let bigger, better art sit naturally on the page.

## Data Flow

1. Source sheets are sliced into curated PNGs and manifest metadata.
2. `assets.py` lazily loads and caches curated iso sprites.
3. `IsoCity._layout()` continues to produce deterministic tile kinds and
   plant sites from population/fleet.
4. `IsoCity._bake()` draws terrain, roads, buildings, city-core sprites,
   light-ring surfaces, transmission, and static plant sprites.
5. `IsoCity.draw()` continues to layer time-of-day, atmosphere, vehicle flow,
   city lights, transmission, plant live effects, and overload effects.
6. `PlantPins` continues to receive marker targets from
   `IsoCity.plant_markers()`.

## Error Handling

Missing or invalid curated assets should fail loudly in development, matching
the existing asset loader behavior. If a manifest entry is absent for a plant
or building tier, the renderer may fall back to the procedural sprite for that
specific role, but missing files referenced by the manifest should raise a
clear error.

The slicing step should be deterministic. If it is implemented as a helper
script, running it twice should produce the same filenames, dimensions, and
manifest output.

## Testing and Verification

Focused tests:

- Asset loader rejects non-alpha iso sprites and loads manifest entries.
- Sliced plant sprites are tight enough to have non-empty alpha bounds.
- Every active plant's baked sprite bounds are contained by `city._world_rect`.
- Plant marker targets follow `visual_dx`/`visual_dy` after the sprite swap.
- `switchyard_anchor()` still matches the first point of each transmission
  route.
- City-center sprites bake without overlapping water/road reservations.
- Population layout tests still pass, especially monotonic city sizing.

Regression tests:

- Run existing city/grid tests, especially `test_city_model.py`,
  `test_grid_flow.py`, and `test_congestion.py`.
- Run `tools/capture_moments.py` and compare the game captures by eye.
- Inspect at default zoom and high zoom for clipping, pin placement, city-core
  density, and plant readability.

## Implementation Boundaries

Files in scope:

- `assets/iso/**` for curated art and manifest.
- `energy_grid_game/ui/assets.py` for iso sprite loading.
- `energy_grid_game/ui/iso_city.py` for sprite-backed buildings, city center,
  and plant static art.
- `energy_grid_game/test_city_model.py` for renderer/anchor tests.
- A small deterministic slicing helper under `tools/`, unless implementation
  discovers the sheets require manual art judgment for every crop.

Files intentionally avoided except for verification-driven fixes:

- `energy_grid_game/game_state.py`
- `energy_grid_game/pricing.py`
- `energy_grid_game/ui/grid_flow.py`
- Source classes under `energy_grid_game/sources/`

## Acceptance Criteria

- The central town reads as a bustling city core, not a sparse procedural town
  center.
- Generating technologies visibly use the provided asset-sheet style.
- Plants remain clickable/focusable through existing pin behavior.
- Transmission conductors, electron flow, congestion visuals, and overload
  effects still line up with the plant switchyard anchors.
- No visible top/side clipping in normal captures.
- Existing tests for city model, grid flow, congestion, and pricing pass.
- New visual captures show a polished indie modern-retro look while preserving
  gameplay readability.

## Risks

- Sprite scale mismatch: the source sheets may contain assets at multiple
  footprint sizes. Mitigation: slice only curated choices first and use manifest
  base metadata.
- City light integration: sliced art may not provide separable windows.
  Mitigation: generate conservative light overlays and keep procedural builders
  as fallback during implementation.
- Plant anchor drift: visually nicer plant sprites may move switchyard takeoff
  points. Mitigation: lock route-start tests to `switchyard_anchor()`.
- Clipping from taller assets: modernized art may exceed current bake extents.
  Mitigation: assert bounds in tests and retune world overscan/origin as needed.

## Open Decisions for Implementation Planning

- Whether the slicing helper is kept permanently under `tools/` or treated as a
  one-time script.
- Exact sprite choices from each sheet for every tier and plant key.
- Whether city-center landmarks replace normal buildings or are layered as
  visual dressing over reserved downtown tiles.

These decisions can be made during the implementation plan because they do not
change the approved architecture or gameplay boundary.
