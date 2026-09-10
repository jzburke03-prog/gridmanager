# Terrain3D Default + Full Terrain Kit Design

**Date:** 2026-08-06
**Status:** Approved by user for implementation

## Summary

The 3D terrain renderer is now mature enough to become the default game view.
The remaining asset gap is that `newassets/terrain/gltf` contains 373 terrain
kit meshes, while the runtime currently ships only a curated subset. This work
will make Terrain3D default-on, add an opt-out path, bake every glTF terrain kit
mesh into runtime `.npz` artifacts, and add a manifest/catalog so coverage can
be tested.

## Goals

- `run_game.py` / `energy_grid_game/main.py` should show the 3D terrain layer by
  default.
- `GRIDMANAGER_TERRAIN3D=0` should disable 3D for troubleshooting.
- `run_game.py` should not hard-fail solely because `.venv39` is absent when the
  current interpreter can run the game.
- Every `.gltf` file under `newassets/terrain/gltf` should have a baked runtime
  `.npz` artifact and manifest entry.
- Runtime should use semantic terrain-kit variants where the current layout has
  enough information: terrain/biome bases, roads, paths/tracks where mapped,
  city/forest/desert/water families, and decoration props.
- Major QC should include bake coverage, GL/runtime tests, capture smoke, and
  visual spot checks.

## Non-Goals

- Do not parse raw glTF at runtime.
- Do not load all 373 meshes into GL every game launch unless they are needed.
- Do not add new assets or modify source art.
- Do not implement edge-transition topology that the layout does not yet expose.
  Assets should be baked/cataloged now and hooked in where semantic data exists.
- Do not remove the `GRIDMANAGER_TERRAIN3D` escape hatch.

## Architecture

`tools/bake_terrain_kit_meshes.py` discovers every glTF source file under
`newassets/terrain/gltf`, writes one `.npz` per source under
`energy_grid_game/assets/terrain3d/kit`, and writes a manifest JSON. The manifest
is testable without OpenGL and is the durable proof that the full kit is
implemented as runtime-ready data.

`ui.terrain3d` keeps its existing named mesh buckets for game-critical materials
and adds catalog helpers for terrain-kit availability and deterministic semantic
variant selection. The renderer remains efficient: only active semantic meshes
are loaded/uploaded for the scene, while the full catalog is available for future
placement rules.

`terrain3d.is_enabled()` becomes default-on and opt-out. `CAPTURE_TERRAIN3D=1`
continues to work, and `GRIDMANAGER_TERRAIN3D=0` disables the 3D path in both
game and capture contexts.

## Testing And QC

- Bake tests cover source discovery, key uniqueness, manifest shape, and a real
  sample bake.
- Runtime tests cover default-on/opt-out behavior, catalog coverage, and semantic
  runtime mesh availability.
- Existing `test_terrain3d.py` and `test_city_model.py` remain green.
- Full low-resolution 3D capture should write all 28 frames.
- Visual QA should inspect baseline, zoom, night, rain, snow, and asset-rich city
  frames.

## Residual Risks

The terrain kit contains many transition/edge models that require neighbor-aware
topology not currently represented in every game tile. This work bakes and
catalogs them all and uses semantic subsets now; deeper edge-placement rules can
be added later without revisiting the bake pipeline.
