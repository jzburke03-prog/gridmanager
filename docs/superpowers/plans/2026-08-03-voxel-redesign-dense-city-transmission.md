# Voxel Redesign: Dense City + Transmission/Distribution Clarity — Plan

> **For agentic workers:** execute task-by-task; verify each with `tools/capture_moments.py` frames and the model tests. Steps use `- [ ]`.

**Goal:** Redesign the in-game map on the new cohesive voxel asset library — a dense downtown, matching voxel power plants, and a clean, *accurate* transmission→switchyard→distribution chain where transmission (electron-flow, no pulse) and distribution (pulsing) are visually distinct and never overlap the dials. Demo-ready.

**Architecture:** Keep `iso_city.py` as orchestrator; load the sliced voxel sprites via a small `ui/voxel_assets.py` loader + `assets/voxel/manifest.json`. Replace procedural buildings with block-placed voxel building sprites; replace plant art with voxel generation sprites; rebuild the transmission bake into two clearly-distinct systems around a new switchyard node.

**Tech Stack:** Python 3.12, pygame 2.6, numpy, PIL. Tests: plain assert modules run via `.venv39`. Visuals: `tools/capture_moments.py`.

## Global Constraints
- Tile geometry `TW,TH = 16,8`. Voxel sprites are large; scale to target tile-footprints, depth-sorted.
- **GIT: do not commit/branch/push** (standing instruction). "Checkpoint" = `git add -A && git status` only.
- Animation of the plant sprites is deferred (static one rotation now).
- Reuse the existing day/night bake, season palette, ring-lights, camera, `plant_markers`/dials.
- Run python via `.venv39/Scripts/python.exe` from `D:/Github/gridmanager`.

---

## Task 1 — Voxel sprite library (DONE)
Sliced `newassets/generating and town` → `energy_grid_game/assets/voxel/{generation,town,tiles}/*_r{0..3}.png` + `manifest.json` (`tools/slice_voxel_sprites.py`). Verified via `_library.png`.

- [x] Library sliced, keyed, trimmed, manifest written.

## Task 2 — `ui/voxel_assets.py` loader
**Files:** Create `energy_grid_game/ui/voxel_assets.py`; Test `energy_grid_game/test_voxel_assets.py`.
**Produces:** `sprite(slug, rot=0) -> pygame.Surface` (cached), `has(slug)`, `TOWN_SLUGS`, `GEN_FOR_PLANT` mapping game plant keys → generation slugs:
`{"nuclear":"nuclear","hydro":"hydro","solar":"solar","coal":"thermal","gas":"cogeneration","peaker":"geothermal","wind":None}` (wind keeps its procedural turbine for now — no wind voxel asset).
- [ ] Test: `voxel_assets.sprite("apartment").get_width() > 0`; `GEN_FOR_PLANT["coal"] == "thermal"`.
- [ ] Implement lazy `pygame.image.load(...).convert_alpha()` keyed by (slug,rot), reading `assets/voxel/manifest.json`.
- [ ] Run test → pass. Checkpoint.

## Task 3 — Plant art swap to voxel sprites
**Files:** Modify `iso_city.py` `_plant_static_sprite`/`_manifest_plant_sprite` path (~1330) to prefer `voxel_assets.GEN_FOR_PLANT[key]` sprite (scaled to a target width per tech), falling back to the existing procedural art when the mapping is `None` (wind) or missing.
- [ ] Scale each gen sprite to a target footprint (nuclear/hydro/thermal wider, solar mid). Anchor bottom-centre on the plant's cleared pad.
- [ ] Capture `06_game` — plants read as cohesive voxel structures on their pads.
- [ ] Checkpoint.

## Task 4 — Dense downtown (block-placed voxel buildings)
**Files:** Modify `_layout` (city tile generation) + `_bake` (draw), add `ui/voxel_city.py` for block→building assignment.
**Design:**
- Partition the built area into **blocks** on the existing road grid (`ROAD_SPACING`); each block = a footprint of a few tiles.
- Assign a building slug per block by distance-from-centre: centre → `apartment` (towers); mid → `department_store`/`mall`/`school`; fringe → `house`/`market`. Deterministic by block hash.
- Draw one voxel building sprite per block, bottom-centre anchored at the block's front tile, depth-sorted with the rest of `_bake`'s painter order. Ground under blocks uses `floor1/floor2` tiles.
- Density target: enough blocks/buildings that `len(_buildings)`-equivalent city reads dense and the two "small city" tests pass (`test_priority...` ≥300 lightable; downtown landmarks near centre).
- [ ] Implement block partition + slug assignment (pure, testable) in `voxel_city.py`; unit-test the assignment gradient (centre=apartment, fringe=house).
- [ ] Wire draw into `_bake`; window/night lights ride the existing ring layers by block.
- [ ] Capture — dense, varied skyline; update `test_priority_actually_lights_that_fraction` + `test_layout_reserves_city_center_sprites_near_downtown` to the new dense city (should now pass with a real downtown).
- [ ] Checkpoint.

## Task 5 — Switchyard node adjacent to the city
**Files:** `iso_city.py` transmission section; a `_switchyard(surf,x,y)` voxel-styled draw (reuse/upgrade existing).
**Design:** Choose ONE switchyard tile just outside the built edge, between the plant ring and the city (a clear pad). It is the single hub: every plant's transmission corridor ends here; every distribution line starts here into downtown.
- [ ] Compute `self._switchyard` (col,row + screen) on a clear pad adjacent to downtown; draw a distinct switchyard structure.
- [ ] Checkpoint.

## Task 6 — TRANSMISSION lines (plant → switchyard): flow, no pulse, sparse bold towers
**Files:** `_route_transmission` + transmission bake.
**Design (exact):**
- Route each plant → the single switchyard (not to city blocks).
- Towers: **one bold tower at the plant end (start)** + **sparse towers (~1 mid-corridor)** by cumulative distance; switchyard end handled by the yard itself.
- **Line look (redesign allowed):** a distinct transmission conductor — e.g. a brighter/thicker double line on tall pylons — carrying **electron Flow dots that move steadily (NO pulse)**. Keep `Flow` (electrons), drop any pulsing on these lines.
- **Dial-avoidance:** before finalising a corridor, check it against every dial's bounding box (`plant_markers`/pin rects) and nudge control points so no conductor segment crosses a dial box. Dials draw last regardless.
- [ ] Implement single-hub routing + start-tower + sparse towers + dial-avoidance.
- [ ] Confirm electrons flow (no pulse) along transmission; capture shows clean corridors clear of dials.
- [ ] Checkpoint.

## Task 7 — DISTRIBUTION lines (switchyard → city): pulsing, distinct
**Files:** `_build_distribution` + draw + per-frame pulse.
**Design (exact):**
- From the switchyard, a few distribution feeders into downtown blocks.
- **Visually distinct from transmission:** thinner, different colour (e.g. warm amber), lower poles, and they **PULSE** (`LinePulse` travelling pulses) — no steady electron dots. This is the "power reaching homes" read.
- [ ] Implement switchyard→city distribution with pulsing; ensure the transmission↔distribution distinction is obvious (flow vs pulse, colour, pole height).
- [ ] Capture a short sequence to confirm pulses travel yard→city while transmission electrons flow plant→yard.
- [ ] Checkpoint.

## Task 8 — Verification + test reconciliation
- [ ] Full `test_city_model` + `test_voxel_terrain` + new tests green except any genuinely-superseded ones (update with comments).
- [ ] Capture day/night/winter; confirm: dense downtown, voxel plants, switchyard, transmission (flow/no-pulse) vs distribution (pulse), dials never blocked.
- [ ] Checkpoint; report staged diff.

## Notes / risks
- Large voxel sprites: watch bake time; scale sprites down and cache. Only surface detail matters at map zoom.
- If block placement can't reach ≥300 lightable cheaply, raise block density before touching the test.
- Wind has no voxel asset — keep its procedural turbine; flag for a future asset.
