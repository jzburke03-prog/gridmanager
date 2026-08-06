# Real-Time 3D Terrain — Phase 3a Design (Power Plant Billboards)

**Date:** 2026-08-05
**Status:** Design (autonomous, per user's "keep going" direction)

## Scope note

Phase 3 as originally scoped covers plants AND transmission (towers + conductor lines). Given how
much larger transmission turned out to be on inspection (no ready 3D assets at all, and a
non-trivial procedural routing system to convert), this document covers **Phase 3a: power plant
billboards only**. Transmission is Phase 3b, a separate follow-on spec.

## Carried-forward goals

- Fixed isometric camera, low-fi flat/banded lighting — unchanged.
- Plants keep their existing hand-drawn pygame art (already decided) — no new art, no re-skinning.
- `GRIDMANAGER_TERRAIN3D` stays default-off.
- Existing plant simulation/placement logic (`IsoCity._place_plants`, `PlantSite`) is untouched —
  only how a plant's *existing* sprite gets composited changes.

## Goal

Render each plant's existing static sprite (`_plant_static_sprite`, already a pygame `Surface`) as
a camera-facing quad ("billboard") inside the same moderngl pass that draws terrain/roads/
buildings, so a plant is genuinely depth-tested against 3D geometry — a plant behind a 3D building,
from the fixed camera's perspective, is occluded correctly, instead of a 2D sprite that always
draws on top of everything regardless of what's "in front" of it.

## Explicit scope decision: static art only, not the live/animated overlay

`IsoCity._draw_plants`/`_draw_plant_live` draws a *second*, continuously-animated layer on top of
the static sprite (steam puffs, spinning turbine blades, a status glow) positioned using the
plant's clamped 2D screen anchor (`site.sx`/`site.sy`, which can differ slightly from a pure
`iso_xy(col, row)` position because `_place_plants` clamps it to stay inside the viewport). Making
*that* layer a correctly-positioned 3D billboard too is a separate, harder problem (a moving part
whose screen anchor doesn't cleanly map to a single static world position) and is explicitly out of
scope for 3a — the live overlay keeps drawing in 2D, unchanged, on top of everything, exactly as it
does today. This phase only billboards the static base sprite.

## Explicit scope decision: prove the mechanism, don't flip visibility yet

Unlike Phase 1/2's terrain/roads (which got a 2D-hiding pass once proven correct), this phase does
**not** hide `IsoCity`'s existing 2D static plant sprite draw. Reason: plants sit outside the built
city ring by design (`_place_plants`'s docstring — "outside the built edge"), so they rarely
visually overlap a 3D building on today's map layouts, meaning there's no easy "before/after"
visual proof from real gameplay the way terrain had. This phase proves the billboard mechanism is
correct — right position, right size, right depth-test behavior — via a synthetic test (a fake
billboard placed deliberately behind a fake building in world space, confirming the building wins
the depth test) and a real-layout screenshot, but leaves the 2D sprite as the actual visible layer
for now. Flipping visibility (hiding the 2D static sprite) is Phase 3b/4 work, once the live-overlay
positioning problem above is solved and both parts can be hidden/replaced together.

## Architecture

- **Billboard geometry is procedural, not baked from `newassets`.** A billboard's quad must always
  face the camera; since the camera is fixed (never rotates), this reduces to a constant, computed
  once from `CAM_ROT`: `right_world = CAM_ROT.T @ (1,0,0)`, `up_world = (0,1,0)` (already vertical —
  a billboard stands upright in world Y, matching how the 2D sprite reads as a flat cutout standing
  on the ground). Four corners = `anchor ± (width/2)*right_world` at `y=0` and `y=height`, so the
  sprite's bottom edge sits on the ground plane.
- **Each plant gets its own texture and its own `GLMesh`-like draw target**, unlike terrain/road/
  building materials (which share one mesh across many instances). Plant count is always small
  (at most 8, one per fuel type in a fleet), so no instancing/batching complexity is needed — one
  quad + one texture per plant, drawn individually.
- **Texture is created at runtime from the existing pygame `Surface`** (`site.sprite`), not baked
  offline — `pygame.image.tostring(surface, "RGBA", True) -> ctx.texture(...)`, done once per bake
  (cached alongside the sprite itself, same lifetime as `IsoCity._plants`).
- **World position** uses `IsoCity._plants`'s `.col`/`.row` (added via a new public `IsoCity.plants`
  accessor, same pattern as `.tiles`/`.layout_key`) through the *same* `(-row*TILE_SPACING, 0,
  col*TILE_SPACING)` formula terrain/roads/buildings already use — not the clamped 2D `sx`/`sy` —
  so a plant lands in the same world-space grid as everything else.
- **Sizing**: sprite pixel width/height (screen-space, from `.sprite.get_size()`) converted to
  world units by dividing by `PX_PER_UNIT` (Phase 1's camera-fix constant), so a plant billboard's
  on-screen footprint roughly matches its existing 2D sprite's footprint.
- **Depth compositing**: billboards draw in the *same* `terrain3d.draw()` call, after terrain/road/
  building instances, sharing the same depth buffer/test — this is what makes occlusion "free."

## Non-goals (3a)

- Live/animated plant overlay (steam, blades, glow) — stays 2D.
- Hiding the 2D static plant sprite — stays visible; this phase only proves the 3D mechanism.
- Transmission (towers, conductor lines) — Phase 3b.
- Any change to plant placement/simulation logic.

## Testing

`build_plant_instances()`-style logic (converting `PlantSite` list to world position + size) is
pure and unit-testable without GL, same pattern as `build_instances()`. The camera-facing basis
vector computation (`right_world`/`up_world` from `CAM_ROT`) is pure numpy, unit-testable. The
depth-occlusion claim gets a real GL test: render a synthetic scene with one billboard positioned
behind one building instance (same world Z ordering a real fixed camera would resolve via the
depth buffer) and confirm the building's pixels win at the overlapping screen location.
