# Real-Time 3D Terrain - Phase 4 Design (Polish + Architecture Debt)

**Date:** 2026-08-06
**Status:** Scope confirmation after Phase 3b handoff

## Summary

Phase 4 is not only visual polish. It is the point where the opt-in 3D renderer
stops being a proof layer hidden under 2D duplicates and becomes the coherent
world renderer for the parts already migrated.

The explicit architecture debt is part of this phase: the current dense downtown
system (`vroad` / `voxel_bldg` / `pad`) overwrites the older road-network
`urban_block` path in the city core. Phase 2 correctly wired `urban_block`
buildings into `terrain3d`, but those 3D buildings are mostly invisible in the
real dense downtown because the dense 2D system wins first. Phase 4 must
reconcile those two systems instead of leaving the 3D building path technically
working but visually irrelevant.

## Goals

- Add day/night and seasonal lighting controls to the 3D terrain pass.
- Add snow/ice material response for terrain, roofs/buildings, plants, and
  transmission infrastructure where reasonable.
- Add an unlit/full-bright billboard material path so plant and tower billboards
  no longer render roughly 30 percent darker than their source art.
- Update `tools/capture_moments.py` so visual captures can include the opt-in 3D
  renderer, not only the legacy 2D stack.
- Reconcile dense downtown architecture so one semantic city layout feeds both
  gameplay and 3D rendering.
- Decide and implement which legacy 2D layers are hidden when
  `GRIDMANAGER_TERRAIN3D` is enabled.

## Architecture Debt: Dense Downtown Reconciliation

Current state:

- `road_network.py` grows roads and `IsoCity` places road-adjacent
  `urban_block` buildings.
- `terrain3d.build_instances()` renders `road` and `urban_block` tiles.
- The dense downtown stamp then writes `vroad`, `voxel_bldg`, and `pad` tiles in
  the center.
- `_bake()` draws `voxel_bldg` and `vroad` in 2D, but `terrain3d` skips them.
- Result: Phase 2 building meshes are real and tested, but the dominant downtown
  remains a separate 2D-only path.

Phase 4 resolution:

- Pick one semantic downtown source. The recommended direction is to keep the
  dense downtown layout because it is the current visible city and gameplay
  lighting already counts it, then teach `terrain3d` to consume it.
- Convert `voxel_bldg` slugs into 3D building archetype/material buckets or bake
  a focused set of downtown meshes matching those slugs.
- Convert `vroad` into the existing road-shape/yaw system where possible, or add
  a small downtown-road mesh bucket if its grid semantics do not match
  `UrbanRoad.role`.
- Once 3D downtown output is visually validated, suppress the 2D `voxel_bldg`
  and `vroad` draw branches under `GRIDMANAGER_TERRAIN3D`.
- Keep `_priority`, building illumination, distribution service groups, traffic
  occlusion, and plant-control avoidance semantically unchanged.

## Lighting and Weather

The 3D shader needs material controls that match `ui.atmosphere.sample_atmosphere`
and `ui.voxel_terrain.palette`:

- ambient/light color changes by time of day;
- winter/snow tint on terrain and building roofs;
- rain and ice darken/desaturate road and roof materials;
- night preserves readable silhouettes without washing out HUD contrast;
- billboard unlit mode keeps authored plant/tower colors stable, while still
  allowing a separate optional global tint if the whole world is night/snow.

## Capture Tooling

`tools/capture_moments.py` currently calls `city.draw()` directly and never
replays `main.py`'s 3D FBO path. Phase 4 must add a 3D capture mode:

- enable via `GRIDMANAGER_TERRAIN3D=1` or `CAPTURE_TERRAIN3D=1`;
- create/release the GL context and 3D resources the same way `main.py` does;
- save comparable day/night/weather/zoom frames;
- keep the default 2D capture path available until 3D becomes default.

## Non-Goals

- No new gameplay simulation, transmission economics, or user-built routes.
- No camera orbit or perspective camera.
- No full physically based rendering.
- No rewrite of HUD, plant controls, or demand chart.

## Acceptance Criteria

- With `GRIDMANAGER_TERRAIN3D=1`, the visual downtown is not dependent on the old
  2D `voxel_bldg`/`vroad` draw branches.
- 3D terrain, roads, downtown buildings, plant billboards, and transmission
  infrastructure respond coherently to day/night and winter/snow.
- Plant and tower billboards no longer render noticeably darker than their 2D
  source art under neutral daylight.
- Capture tooling can produce 3D day, night, snow, and zoom review frames.
- `energy_grid_game/test_terrain3d.py` passes.
- `energy_grid_game/test_city_model.py` has no failures caused by the Phase 4
  changes; the existing downtown-reservation failure must be either fixed by the
  architecture cleanup or explicitly replaced with a sharper passing assertion.

