# Changelog

## 2026-08-01 - Urban Grid Visual Rebuild

### Summary

Rebuilt the isometric city presentation from a rural town-in-greenery scene into
a dense modern-retro urban grid. The power plants now sit in city-edge utility
and industrial contexts, transmission corridors follow the city structure, and
the zoomed-out view is dominated by roads, blocks, civic landmarks, and campus
infrastructure instead of forest/farm filler.

### Added

- Curated and sliced uploaded open-source sprite sheets into semantic iso asset
  families for roads, municipal buildings, civic details, plant assets, and
  block palettes.
- Added an urban layout model with deterministic districts, civic anchors,
  utility campuses, buildable blocks, parks, and road metadata.
- Added urban render helpers for paved roads, varied city blocks, municipal
  overlays, and utility campus bases.
- Added contiguous road-path routing for transmission visuals so plant
  conductors follow road corridors instead of jumping across open space.
- Added a 28-shot capture set under `captures/urban_grid_visual_rebuild/`,
  including `14_zoom_1x_evening.png`.

### Changed

- Replaced the primary rural tile composition with urban roads, paved blocks,
  campus tiles, and deliberate park/green details.
- Moved power plant placement to technology-specific city-edge campuses,
  including corrected hydro and plant marker alignment behavior.
- Updated the baked renderer so urban tile kinds draw through urban-specific
  branches before legacy fallback drawing.
- Changed overload/underload warning presentation to remain an edge vignette
  rather than a full-screen gradient wash.
- Updated `tools/capture_moments.py` so the reported capture count reflects the
  actual number of saved screenshots.

### Performance And Safety

- Added renderer budgets:
  - Urban blocks: 220
  - Buildings: 220
  - Campus tiles: 195 in the final captured fleet
  - Road tiles: 2779 in the final captured fleet
  - Rural `farm`/`grass`/`tree` tiles: 0
  - Green tiles: 22
- Capped urban blocks, green tiles, and road tiles to avoid zoom-in lag from
  overpopulation.
- Preserved the existing congestion, pricing, grid-flow, source-control, and
  plant marker systems.

### Verification

Passed:

- `energy_grid_game/test_grid_flow.py`
- `energy_grid_game/test_congestion.py`
- `energy_grid_game/test_pricing.py`
- Focused visual/plant/corridor regressions:
  - `test_baked_zoomed_out_frame_is_not_dominated_by_greenery`
  - `test_urban_renderer_budget_avoids_overpopulation_lag`
  - `test_transmission_routes_follow_urban_corridors_not_open_green`
  - `test_plant_marker_targets_match_manifest_visual_centres`
  - `test_all_plant_pins_stay_reachable_at_every_zoom_and_viewport`
  - `test_focus_plant_centers_camera_on_plant`

Known remaining conflict:

- `energy_grid_game/test_city_model.py` still fails at
  `test_city_size_tracks_population`.
- Reason: the rebuilt visual direction intentionally keeps the gameplay city
  visually full instead of scaling the visible footprint by population.

### Visual Acceptance Captures

Key screenshots:

- `captures/urban_grid_visual_rebuild/11_zoom_1x_day.png`
- `captures/urban_grid_visual_rebuild/14_zoom_1x_evening.png`
- `captures/urban_grid_visual_rebuild/06_game.png`
- `captures/urban_grid_visual_rebuild/25_overload_200.png`

Acceptance notes:

- Roads form a continuous grid.
- Main view is no longer dominated by grass, farm, or forest filler.
- Plants sit in city-edge utility or industrial context.
- Transmission corridors visually follow roads/service corridors.
- Central blocks show visible variety and a busier city core.
- Greenery reads as parks, medians, yards, and street trees.
- Warning states remain readable edge vignettes.
