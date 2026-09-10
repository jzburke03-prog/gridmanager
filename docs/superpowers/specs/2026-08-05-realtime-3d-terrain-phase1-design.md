# Real-Time 3D Terrain — Phase 1 Design

**Date:** 2026-08-05
**Status:** Design (awaiting review)

## Summary

This is Phase 1 of a multi-phase "full revamp" moving the city view from pygame's
2D sprite blitting to a real-time 3D renderer built on `newassets/terrain/gltf`
(373 curated voxel meshes: terrain biomes, roads, water, generic city buildings).

The full revamp is:

1. **Phase 1 (this spec): GL scaffolding + terrain only.** Prove the rendering
   pipeline end-to-end: 3D ground plane (grass/farm/tree/water/mountain), fixed
   isometric camera, low-fidelity pixel/voxel look, composited under the
   existing 2D sprite city.
2. **Phase 2: Roads + buildings** as instanced 3D meshes, fed by the existing
   `road_network.py`/urban-block layout logic (unchanged).
3. **Phase 3: Power plants + transmission** — billboarded plant sprites and 3D
   transmission towers/lines, occlusion-correct against the 3D terrain.
4. **Phase 4: Polish** — day/night and seasonal lighting on the 3D terrain,
   snow, and updating `tools/capture_moments.py` for visual-regression capture
   against the new renderer.

Each phase gets its own spec/plan/implementation cycle. This document covers
**Phase 1 only**.

## Goals (Phase 1)

- Real-time 3D rendering (not baked-to-sprite) using moderngl, which is
  already a project dependency used offline by `tools/bake_gltf_terrain.py`.
- Fixed isometric camera — same viewing angle as today's `iso_xy` projection.
  No orbit/rotation.
- Low-fidelity pixel/voxel aesthetic: flat/banded lighting (not PBR), internal
  render resolution matched to today's effective sprite pixel density so
  terrain and the (still-2D) city read as the same art style.
- Terrain materials sourced from `newassets/terrain/gltf`: grass (base plane),
  `Dirt` → "farm", `Forest` → "tree" clusters, `Water` → "water", `Mountains`
  → edge terrain. One base mesh variant per material for Phase 1; edge/corner
  connector variants are deferred.
- The existing sprite-rendered city (roads, buildings, plants, HUD) keeps
  rendering exactly as it does today, on top of the new 3D terrain layer.
  Nothing about `_layout()`, `road_network.py`, or existing tests changes.
- Fail fast and clearly if the driver doesn't support the OpenGL version
  moderngl requires — no fallback 2D-terrain renderer to build or maintain.

## Non-goals (Phase 1)

- Roads, buildings, plants, or transmission becoming 3D (Phases 2–3).
- Day/night or seasonal lighting on the 3D terrain (Phase 4) — a single
  fixed light works for Phase 1.
- Orbit/rotation camera, zoom-dependent level-of-detail for 3D meshes.
- Full pixel-diff visual regression coverage of the 3D output (Phase 4);
  Phase 1 testing is a basic headless smoke check.

## Architecture

`main.py` opens the pygame window with `pygame.OPENGL | pygame.DOUBLEBUF`
flags instead of the current software-surface mode. A new `ui/gl_context.py`
wraps moderngl context creation and runs once at startup: it probes the
driver's OpenGL version and, if unsupported, prints a clear error message
(e.g. `"Grid Manager requires OpenGL 3.3+; your driver reports 2.1"`) and
exits cleanly — no fallback renderer.

A new `ui/terrain3d.py` owns everything GPU-side for terrain: loading curated
meshes, building per-tile instance buffers from the existing tile grid, and
drawing them into a fixed-size offscreen framebuffer sized to match today's
effective sprite resolution. That framebuffer is upscaled with
nearest-neighbor filtering and blitted to the window *before* the existing
pygame sprite-based city and HUD draw on top, unchanged.

```
_layout() (unchanged)
    -> tile materials (voxel_terrain.material_at, mountain elevation)
    -> terrain3d.build_instances()      [pure, no GL, unit-testable]
    -> GPU instance buffers              [rebuilt only when bake key changes]
    -> terrain3d.draw()                  [per-frame, GL]
    -> offscreen FBO -> nearest-neighbor upscale -> blit
    -> existing sprite city + HUD draw on top     [unchanged]
```

## Components

- **`ui/gl_context.py`** — creates/owns the moderngl context bound to the
  pygame GL window. `create_context()` probes GL version; raises a
  `UnsupportedGLError` with a human-readable message that `main.py` catches
  at startup to print and exit(1), rather than letting a raw GL traceback
  surface.

- **`tools/bake_terrain_meshes.py`** — extends the existing
  `bake_gltf_terrain.py` glTF parser (same hand-rolled JSON+`.bin` reader,
  no new dependency). For each of the five Phase 1 materials, parses one
  curated glTF file and writes a compact `.npz` (positions, normals, UVs,
  indices, texture array) to `energy_grid_game/assets/terrain3d/`. This is a
  bake-time-only tool, run once and the output committed — the running game
  never parses raw glTF/JSON, same principle as the existing sprite bake.

- **`ui/terrain3d.py`** — runtime module:
  - `load_meshes(ctx) -> dict[str, Mesh]` — uploads each `.npz` into a
    moderngl `VertexArray` once at startup, keyed by material name.
  - `build_instances(tiles: dict) -> dict[str, np.ndarray]` — **pure
    function, no GL calls.** Takes the same tile dict `_layout()` already
    produces (material per `(col, row)` from `voxel_terrain.material_at` and
    mountain elevation) and returns, per material, an array of per-instance
    transforms (world position + rotation). Called only when the bake key
    changes, mirroring today's `_layout`/`_bake` caching.
  - `upload_instances(ctx, meshes, instances)` — writes `build_instances()`
    output into per-material instance buffers.
  - `draw(ctx, fbo, camera)` — per-frame: bind the offscreen framebuffer,
    clear, and issue one instanced draw call per material using a simple
    flat/banded-lighting shader (a handful of discrete light levels from a
    single fixed light direction; no PBR, no shadows in Phase 1). Camera
    projection matches the same fixed true-isometric angle
    `tools/bake_gltf_terrain.py` already uses for its offline bake (45°
    around Y, ~35.264° around X, orthographic), kept consistent with
    `iso_xy`'s screen-space diamond ratio.

- **`main.py`** — gains: GL context creation + fail-fast check at startup;
  a per-frame step that draws the 3D terrain FBO and blits it (upscaled)
  before the existing sprite city/HUD draw calls.

## Error handling

- **Unsupported OpenGL version:** `gl_context.create_context()` raises
  `UnsupportedGLError(message)`; `main.py` catches this once at startup,
  prints the message to stderr, and exits with a non-zero code. No retry,
  no degraded rendering path.
- **Missing/corrupt baked `.npz` mesh:** `load_meshes()` raises immediately
  at startup (fail fast, same posture as a missing sprite asset today) —
  these are committed build artifacts, not something to handle gracefully
  at runtime.

## Testing

- **`build_instances()`** is pure Python (dict/array in, arrays out) and
  gets ordinary unit tests with no GL context needed — same style as the
  existing `test_road_network.py`: given a small synthetic tile dict, assert
  the right material buckets and instance counts/positions come out.
- **GL-dependent smoke test:** `moderngl.create_standalone_context()`
  (already used headless by `tools/bake_gltf_terrain.py`, no window
  required) renders a small known tile grid (e.g. one water tile, one grass
  tile) into an offscreen framebuffer and reads back pixels for a basic
  sanity assertion (water tile average color is bluer than grass tile). This
  is a smoke check, not full visual-regression coverage — that's Phase 4,
  alongside updating `tools/capture_moments.py`.
- **No changes** to existing `test_city_model.py`, `test_road_network.py`,
  `test_voxel_terrain.py`, etc. — `_layout()`'s output contract is unchanged,
  so all current layout/simulation tests keep passing unmodified.
