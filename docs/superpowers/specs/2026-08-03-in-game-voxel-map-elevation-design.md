# In-Game Voxel Map Elevation — Design

**Date:** 2026-08-03
**Status:** Design (awaiting review)

## Summary

Elevate the actual game's isometric map (`energy_grid_game/ui/iso_city.py`) with a
"flat but slightly isometric, leaning-voxel" look, and fix the current visual
regressions. This is an **elevation, not a reset**: every existing system —
the day/night bake, season data, procedural animated plants, camera, transmission
routing — is **reused and extended**, never replaced.

Four outcomes, all in scope for this first version:

1. **Voxel-hybrid terrain + restore the map.** Fix the regression where the
   countryside stopped rendering (city floating on a black void), and give ground
   tiles subtle voxel thickness.
2. **Edge mountains.** Voxel mountain ranges frame the map so it fills the frame
   (no floating island).
3. **Seasons + time-of-day.** Ground palette by calendar season and continuous
   day/night lighting, driven by the existing sim clock and the existing
   day/night bake.
4. **Tame transmission + compact layout.** Far fewer, bolder transmission towers
   (conductor lines do the work) and plants pulled into a tight, city-hero
   composition.

## Root cause of the current regression (confirmed)

In `iso_city._layout` the tile dict is populated only with roads, urban blocks,
parks, and campuses. The countryside fill (farm/grass/tree/water via the still-defined
but unused `river_v`) was dropped when the road-network layout landed, and a leftover
filter removes `"farm"/"grass"/"tree"` tiles that are never added. `_bake` still knows
how to draw those materials — it just never receives any — so the surround renders as
black void. Restoring the countryside generation fixes it.

## Architecture (Approach B — extract a focused module)

`iso_city.py` is already ~2,700 lines. Rather than grow it further, add a focused,
unit-testable module:

**`ui/voxel_terrain.py`** owns the new, pure-ish pieces:
- **Drawing primitives**: `slab(surf, sx, sy, color, depth)` (ground tile with thin
  voxel thickness) and `column(surf, sx, sy, height, color)` (extruded block, 3 shaded
  faces). Tuned modest — leaning voxel, not chunky cubes.
- **Terrain materials**: `material_at(col, row, ...)` → grass / field / water / road /
  pad / rock / snow, plus the river shape and per-tile brightness jitter.
- **Mountains**: `elevation(col, row, extent)` → voxel height on the edges, noisy
  ridgelines, snow above a snowline.
- **Seasons**: `SEASONS` palettes, `season_of(month)`, `palette(season)`.

`iso_city.py` remains the orchestrator and calls into `voxel_terrain`:
- `_layout` uses it to refill countryside + mountain tiles into `self._tiles`
  (each tile carries material + elevation).
- `_bake` uses `slab`/`column` to draw tiles/mountains with the current season palette
  instead of flat diamonds.
- Plants, transmission, camera, ring-lights, day/night cross-fade are unchanged in
  ownership; only their inputs/tuning shift.

## Component design

### C1. Terrain restore + voxel-hybrid ground
- `_layout`: after roads/blocks/campus/greenery, fill every in-viewport tile not
  otherwise occupied with a countryside material (river via `river_v`, else
  clustered woodland vs field vs grass). Remove the dead farm/grass/tree filter.
- Generation extends beyond the play area and culls off-frame tiles so terrain
  reaches every edge.
- `_bake`: draw each ground tile as a `slab` (thin thickness + jitter) rather than a
  flat diamond, with a subtle base platform under structures.
- **Both city buildings and plants are kept but fair game to improve.** The
  implementer has latitude to restyle them toward the voxel-hybrid look (thicker forms,
  cleaner shading/roofs, better height grading, better grounding on the voxel terrain)
  where it improves cohesion. **Conservatively** — do not destabilise what already
  works, especially the plants' live animated parts (steam, spinning blades, spillway).
  Enhancement, not rewrite; judged by the capture-frame look, and kept behind
  passing tests.

### C2. Edge mountains
- Tiles with `elevation(col,row) > 0` (distance-from-center ramp × value noise) render
  as rock `column`s, snow-capped above the snowline. Snow presence increases in winter.
- Mountains sit outside the plant ring so they never swallow a plant.

### C3. Compact, city-hero composition
- Tighten `_place_plants`: reduce the ring multiplier and floor so plants hug the
  built edge (shorter transmission runs, no stranded-at-horizon plants).
- City stays the visual center; camera/zoom levels unchanged.

### C4. Seasons + time-of-day (reuse existing bake + clock)
- The bake already produces a **day layer** and a **night layer** cross-faded by sun
  angle (`daylight()`); night window-glow lives in the ring layers. We **extend** this:
  the ground is baked using the **current season's palette**.
- `season_of(state.date.month)` selects the palette (winter 12–2, spring 3–5,
  summer 6–8, fall 9–11). A **season-boundary crossing** is added to the existing
  rebuild triggers (resize / fleet / population), so a re-bake happens only when the
  season actually changes — cheap.
- Winter additionally applies snow to ground and building/roof tops.
- Time-of-day needs no new system: it continues to ride the day/night cross-fade.
  (Optional, low-risk: a warm-dusk tint pass — deferred unless wanted.)

### C5. Tame transmission
- In the transmission bake, drop tower density dramatically (a tower at corridor
  bends + an occasional straight-run tower) and draw them bigger/bolder with brighter
  conductor lines. Compact plant placement makes corridors shorter and non-crossing.

## Data flow

```
GameState (sim_hour, date.month)
      │ season_of(month) ─────────────► palette
      ▼
_layout ──uses──► voxel_terrain.material_at / elevation ──► self._tiles (+material,+elev)
      ▼
_bake ──uses──► voxel_terrain.slab / column (season palette) ──► day layer + night layer
      │                                                          + ring light layers
      ▼
draw() ──existing──► cross-fade day/night by daylight(sim_hour); plants + vehicles per frame
```

## Rebuild / performance

- Static terrain (now voxel) is baked once into the day/night layers, exactly as
  today. Only vehicles and plant live-parts redraw per frame — unchanged.
- Re-bake triggers: existing (resize, fleet change, population change) **plus** season
  boundary. Mountains add tiles but off-frame culling bounds the count.

## Testing

- **Unit tests** (new, e.g. `test_voxel_terrain.py`): `season_of` boundaries,
  `palette` returns expected material set, `elevation` is 0 in the play area and rises
  at the edge, `material_at` classifies river/field/grass deterministically.
- **Visual regression**: `tools/capture_moments.py` before/after frames, inspected for
  day, night, and each season.
- **Update existing tests** that legitimately change: `test_city_model` assertions on
  countryside/greenery counts, plant ring distances, and any transmission-density
  assertion, since the layout intentionally changes. Keep road-network tests green.

## Non-goals (this version)

- Plants and city buildings are not voxelized or rewritten, but may be conservatively
  enhanced/restyled for cohesion at the implementer's discretion — without breaking the
  plants' live animation.
- Not migrating the engine (stays pygame).
- No AI sprite-sheet assets (explicitly dropped).
- Warm-dusk tint and animated season transitions are optional/deferred.

## Risks

- **Test churn**: layout changes will flip some `test_city_model` expectations; these
  are expected updates, not regressions — review each.
- **Style cohesion**: flat-iso plants on voxel-thickened ground must read together;
  the "leaning voxel / subtle thickness" tuning is deliberately modest to keep them
  cohesive. Verify via capture frames.
- **Season re-bake correctness**: ensure the boundary trigger fires once per crossing,
  not per frame.

## Implementation order (each a verifiable increment)

1. `voxel_terrain.py` primitives + season palettes + unit tests.
2. Restore countryside in `_layout` + draw ground as voxel slabs in `_bake` (fixes the
   regression; frame no longer floats).
3. Edge mountains.
4. Compact composition (`_place_plants` tuning).
5. Seasons wired to the bake + season-boundary re-bake trigger.
6. Tame transmission.
7. Update existing tests; capture-frame verification pass.
