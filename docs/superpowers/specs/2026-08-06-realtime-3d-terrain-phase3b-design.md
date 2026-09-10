# Real-Time 3D Terrain - Phase 3b Design (Transmission)

**Date:** 2026-08-06
**Status:** Design approved from handoff; implementation plan follows

## Summary

Phase 3b moves the visible high-voltage transmission infrastructure into the
opt-in `GRIDMANAGER_TERRAIN3D` renderer. Phase 3a proved that runtime pygame
surfaces can become depth-tested billboards in the moderngl pass. This phase
uses the same idea for transmission towers, and adds procedural 3D conductor
geometry built from the existing `IsoCity._routes` / `Flow` paths.

The 2D transmission system remains the semantic source of truth: plant routing,
switchyard/substation endpoints, overload data, output-dependent flow rate, and
distribution feeders do not change. The 3D layer receives a renderable snapshot
of that already-baked transmission geometry and draws it with correct occlusion.

## Carried-Forward Constraints

- Fixed isometric camera; no orbit, rotation, or new camera modes.
- `GRIDMANAGER_TERRAIN3D` stays default-off.
- Existing simulation, plant placement, `_route_transmission`, `_build_distribution`,
  and `Flow` semantics remain unchanged.
- High-voltage transmission is in scope; distribution feeders, service poles,
  transformer fires, and building-lighting behavior stay 2D until Phase 4 or a
  later focused pass.
- No new external dependencies.
- Run tests with `.codex_portable_build_20260804_001/venv/Scripts/python.exe`;
  `.venv39` is currently unusable on this machine.

## Scope

In scope:

- Camera-facing billboard quads for high-voltage towers, sourced from generated
  pygame tower art matching the existing `_pylon` style.
- Procedural 3D conductor meshes built from the same elevated, offset conductor
  paths that 2D `Flow` already uses.
- A pure geometry builder in `ui/terrain3d.py` so tests can validate tower
  placement, conductor endpoints, and route counts without a GL context.
- GL load/draw wiring through the existing `terrain3d.draw(..., billboard_meshes=...)`
  style, with explicit resource release on layout changes.
- Tests proving transmission geometry is non-empty for a real layout and that
  conductor endpoints match the source route endpoints.

Out of scope:

- Hiding the 2D transmission layer by default. Phase 3b proves and wires the 3D
  version, but Phase 4 decides when the 2D layer is suppressed.
- 3D animated electrons. The current animated `Flow` particles remain 2D, using
  the same visible path. This avoids adding dynamic GL buffers for every frame
  before the static infrastructure is proven.
- Distribution lines and local transformer/service branches.
- User-built routes or new transmission gameplay.

## Architecture

`IsoCity._bake()` already derives all transmission geometry in screen space:

- `self._routes`: `(plant_key, substation_index, [screen points])`
- `conductor_paths[(key, i)][arm]`: elevated, offset conductor points at each
  physical circuit arm
- `self._flows[(key, i)]`: 2D animated particles built from those same points

Phase 3b makes this geometry available as a public, read-only snapshot:

```python
IsoCity.transmission3d -> tuple[dict, ...]
```

The snapshot contains route records with:

- `key: str`
- `substation_index: int`
- `tower_points: tuple[(x_px, y_px), ...]`, using the same sparse pylon
  spacing as the 2D renderer
- `conductor_paths: dict[int, tuple[(x_px, y_px), ...]]`, using the existing
  elevated arm endpoints as the visual source of truth

`ui/terrain3d.py` owns conversion from screen-space route points back into the
renderer's world-space basis. Because `terrain3d` already projects
`(x=-row*TILE_SPACING, z=col*TILE_SPACING)` into the same 2:1 `iso_xy` screen
grid, the conversion can use the inverse of the existing projection formulas
for x/z and use world y for tower/conductor height. Conductor conversion keeps
the screen-space arm offset, removes the 2D vertical lift before deriving
ground x/z, then reapplies that lift as positive world y so the projected 3D
strip lands on the same elevated pixel path without being depth-tested into the
terrain.

The GL side has two products:

- tower billboards: one quad/texture per tower, same resource model as plant
  billboards, but using a shared generated tower surface where possible;
- conductor meshes: thin rectangular strips between consecutive conductor
  points, batched into one or a small number of `GLMesh` instances with an
  unlit or lightly-lit neutral texture.

## Lighting and Visual Style

Transmission should read as physical steel and cable, not glow. Towers use the
existing `_pylon` visual language: splayed dark legs, lit inner edge, crossarms,
and small insulators. Conductors are cool grey and slightly thicker than a
single pixel after projection. Overload color remains on the animated 2D flow
particles for now; the 3D static conductor does not pulse or glow.

Because the tower billboards are art surfaces rather than physical meshes, they
should use the unlit/full-bright path that Phase 4 will generalize for plant
billboards. If Phase 3b lands before that shader path, towers may temporarily
use the current lit billboard shader; the design must document the brightness
gap as known temporary debt rather than tune the art darker to compensate.

## Data Flow

```text
IsoCity._bake()
  -> _route_transmission()
  -> 2D conductor_paths + tower_points
  -> IsoCity.transmission3d snapshot
  -> terrain3d.build_transmission_geometry(snapshot)
  -> terrain3d.load_transmission(...)
  -> terrain3d.draw(..., transmission_meshes=...)
```

`main.py` rebuilds the GL transmission resources whenever `city.layout_key`
changes, in the same block that already rebuilds terrain instances and plant
billboards.

## Testing

- Pure tests for screen/world conversion round trip at representative points.
- Pure tests that every real route produces at least one tower billboard and two
  conductor arms.
- Pure tests that conductor endpoint positions match the source snapshot within
  one projected pixel.
- GL smoke tests that a synthetic conductor strip renders non-background pixels
  and remains visible when drawn over terrain.
- Regression test that `test_terrain3d.py` remains green.

## Phase 4 Handoff

Phase 4 decides when to hide the old 2D static transmission layer under
`GRIDMANAGER_TERRAIN3D`. It also owns the unlit/full-bright billboard shader
path, day/night/season lighting, snow response, capture harness updates, and
the dense-downtown architecture cleanup described in the Phase 4 design.
