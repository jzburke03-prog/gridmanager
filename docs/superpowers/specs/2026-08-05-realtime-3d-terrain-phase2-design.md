# Real-Time 3D Terrain — Phase 2 Design (Roads + Buildings)

**Date:** 2026-08-05
**Status:** Design (implementing directly per user's "go through all phases" direction — see note below)

## Note on process

Phase 1's design went through full interactive brainstorming (multiple `AskUserQuestion` rounds).
For Phase 2-4 the user asked to "go through all of the phases and report back... when its
complete," i.e. proceed autonomously. This spec applies the same goals and constraints Phase 1
already established (see `docs/superpowers/plans/2026-08-05-realtime-3d-terrain-phase1.md`'s
ledger notes) without re-asking already-settled questions; judgment calls specific to this phase
are made explicitly below rather than left implicit.

## Carried-forward goals (unchanged, confirmed during Phase 1 brainstorming)

- Fixed isometric camera — no orbit/rotation.
- Low-fidelity pixel/voxel look: flat/banded lighting, chunky, not photorealistic.
- Keep existing layout/simulation logic unchanged — only the rendering backend changes.
- Power plants stay as 2D sprites (Phase 3), not touched here.
- The whole pipeline stays behind `GRIDMANAGER_TERRAIN3D` (default off) until a later phase
  retires the corresponding 2D sprite layers — Phase 2 does NOT flip that switch.

## Summary

Extend the Phase 1 3D terrain pipeline (`ui/terrain3d.py`) to also render **roads** (from
`road_network.py`'s tile placement, unchanged) and **buildings** (from `IsoCity`'s outer
"urban_block" archetype tiles, unchanged) as instanced 3D meshes, using the same camera, shader,
and compositing approach Phase 1 established.

## Explicit scope decision: outer suburban ring only, not the dense downtown

`_layout()` produces two distinct building/road systems (this is pre-existing architecture, not
something Phase 2 introduces):
1. **Outer ring**: `road_network.py`'s grown road cells (`kind == "road"`) and
   `IsoCity._pick_archetype`'s suburban buildings (`kind == "urban_block"`, archetypes
   `house`/`shop`/`block`/`midrise`/`tower`).
2. **Dense downtown**: a separate, static `voxel_city.py` grid stamp within a fixed radius of
   city origin (`kind in ("vroad", "voxel_bldg", "pad")`), which — per the code review earlier in
   this session — already overrides most of what `road_network.py` computes near the center and
   is a known pre-existing architectural overlap.

Phase 2 renders **only the outer ring** (`road` + `urban_block` tiles) in 3D. The dense downtown
stays 2D-sprite-rendered for now. Reconciling the two building/road systems is out of scope here —
it's a pre-existing issue, not one this phase should silently absorb. Revisit in Phase 4 or a
dedicated cleanup, not folded into this phase's scope.

## Road meshes: 4 shapes, not 7 roles

`road_network.assign_roles` (`ui/road_network.py:168-216`) emits 7 role strings — `cross`,
`tee_ne`, `tee_nw`, `straight_ne`, `straight_nw`, `corner_ne`, `corner_nw` — but these are just 4
geometric shapes (cross / tee / straight / corner) at one of {0°, 90°, 180°}. Bake **4 base
meshes**, not 7, and apply per-instance yaw at render time:

| shape | source glTF | roles → yaw |
|---|---|---|
| straight | `Roads/road-straight-1.gltf` | `straight_ne`→0°, `straight_nw`→90° |
| corner | `Roads/road-edgy-curve-1.gltf` | `corner_ne`→0°, `corner_nw`→180° |
| tee | `Roads/road-edgy-3-way-crossing-1.gltf` | `tee_ne`→180°, `tee_nw`→270° |
| cross | `Roads/road-edgy-4-way-crossing-1.gltf` | `cross`→0° (rotationally symmetric) |

**CORRECTED post-Phase-2-review** (2026-08-05 final review, Finding 2): the table above
originally listed `corner_nw`→90° and `tee_ne`→0°, which is geometrically wrong — those two
yaws don't orient the mesh's open arms to the neighbor directions the role name requires. The
values shown here were independently re-derived by rotating each baked mesh's `pos` bounding-box
"arms" (its open connection directions at yaw=0, read from `assets/terrain3d/roads/*.npz`)
against the up/down/left/right neighbor semantics in `assign_roles`'s docstring, combined with
`terrain3d.py`'s own tile-position formula (`x = -row*TILE_SPACING`, `z = col*TILE_SPACING`, so
up/row-1→+X, down/row+1→-X, left/col-1→-Z, right/col+1→+Z) and the vertex shader's yaw rotation.
`tee_nw`→90° was this review pass's conclusion, but a later independent re-derivation found that
conclusion itself rested on a transposed (sign-flipped) reading of the vertex shader's rotation
matrix: the shader builds `mat3(c,0,-s, 0,1,0, s,0,c)` via GLSL's column-major constructor
argument order, which works out to `new_x = x*cos(yaw) + z*sin(yaw)`, `new_z = -x*sin(yaw) +
z*cos(yaw)` — not the transposed `new_x = x*cos - z*sin, new_z = x*sin + z*cos` this pass used.
Re-applying the correct (non-transposed) rotation to `tee.npz`'s default arms {+X,-X,+Z} confirms
`tee_nw`→270° is the exact match (90° instead yields {-Z,+Z,+X}, which has +X where -X is
required). See `terrain3d.py`'s `ROAD_ROLE_TO_SHAPE_YAW` comment and `test_terrain3d.py`'s
`test_road_mesh_geometry_arms_match_yaw_rotated_role_connectivity`, which checks all six
non-symmetric roles' rotated arms against required connectivity numerically.

This requires the instance format to carry rotation, which Phase 1's format didn't need
(terrain tiles have no orientation). See Component design below.

## Building meshes: 5 archetypes, curated 1:1

`IsoCity`'s suburban archetypes are `house`, `shop`, `block`, `midrise`, `tower`
(`ui/iso_city.py:517-538`, roughly ascending scale). Map each to one mesh from
`newassets/City Voxel Pack/OBJ/` (already loadable via `tools/bake_gltf_terrain.py`'s existing
`load_obj`, used for `Building02-05.obj` in that file's `OBJ_JOBS`):

| archetype | source OBJ |
|---|---|
| house | `Building01.obj` |
| shop | `Building02.obj` |
| block | `Building03.obj` |
| midrise | `Building04.obj` |
| tower | `Building05.obj` |

One mesh per archetype, no variant/rotation randomization — matches Phase 1's "one base mesh per
material" simplification precedent.

## Architecture

Extends (not replaces) Phase 1's pipeline:

- `tools/bake_terrain_meshes.py` gains a companion, `tools/bake_road_building_meshes.py`, baking
  the 4 road shapes (via `load_gltf`) and 5 building meshes (via `load_obj`, both reused unchanged
  from `tools/bake_gltf_terrain.py`) to `.npz` under `energy_grid_game/assets/terrain3d/roads/` and
  `.../buildings/`.
- `ui/terrain3d.py`'s instance format changes from `(N, 3)` positions to `(N, 4)`
  `[x, y, z, yaw_degrees]` **for every material**, not just roads — this keeps `GLMesh` and the
  vertex shader uniform across all mesh types (terrain tiles simply always carry `yaw=0`) rather
  than branching the instance format by material. `build_instances()` is extended to also bucket
  `"road"` tiles (role → shape mesh key + yaw, per the table above) and `"urban_block"` tiles
  (archetype → building mesh key, yaw always 0 — buildings don't need per-tile rotation in this
  phase).
- The vertex shader gains a per-instance yaw: build a Y-axis rotation matrix from `in_yaw` and
  apply it to `in_pos`/`in_normal` before the existing `CAM_ROT` transform.
- `main.py`'s existing per-frame block (already gated behind `GRIDMANAGER_TERRAIN3D`) needs no
  structural change — `load_meshes`/`upload_instances`/`draw` already iterate "all known
  materials," so adding road/building materials to `MATERIALS` is sufficient; the loop doesn't
  need new main.py code.

## Non-goals (this phase)

- Dense downtown (`vroad`/`voxel_bldg`/`pad`) reconciliation — deferred.
- Building archetype variety/randomization beyond 1 mesh per archetype.
- Making any of this visible by default (`GRIDMANAGER_TERRAIN3D` stays default-off).
- Road edge/dead-end pieces, only the 4 shapes needed for a connected network are baked.

## Testing

Same pattern as Phase 1: `build_instances()`'s road/building bucketing logic is pure and
unit-tested without GL (role→yaw mapping, archetype→mesh mapping). The bake script gets the same
structural test as Phase 1's (`bake_material`-style function, loadable `.npz` with correct
array shapes). The GL-dependent instanced-draw-with-rotation path gets a headless smoke test
(a rotated instance's baked footprint differs from an unrotated one at 90°, confirmed via a
mesh with a known asymmetric bounding box — e.g. `straight` is longer along one axis than the
other, so a 90°-rotated instance's projected screen-space bounding box should differ measurably
from a 0° instance).
