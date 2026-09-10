# Real-Time 3D Terrain Phase 4e Final Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the remaining 3D polish that is possible without new assets: material-class weather response, hardening tests, and visual capture QA.

**Architecture:** Extend the existing single shader with one per-mesh `weather_role` integer and additional global rain/ice uniforms derived by `lighting_for_state(state)`. Weather response stays mesh-class level because current baked meshes do not expose roof masks or separate roof submeshes. Roads and conductor metal darken/desaturate under rain/ice, buildings and terrain receive snow more strongly than billboards, and unlit billboards keep their directional-light bypass while still accepting global tint.

**Tech Stack:** Python 3.12, pygame 2.6, numpy, moderngl. No new dependencies and no new assets.

## Global Constraints

- `GRIDMANAGER_TERRAIN3D` stays default-off.
- `CAPTURE_TERRAIN3D=1` remains the capture-only opt-in path.
- Do not add new art assets or rebake mesh assets.
- Do not change gameplay, HUD layout, camera behavior, transmission routing, or saved capture names/order.
- Keep neutral/default `terrain3d.draw()` visually compatible for existing tests and call sites.
- Use `.codex_portable_build_20260804_001/venv/Scripts/python.exe`; `.venv39` is currently unusable.

---

## File Structure

- Modify `energy_grid_game/ui/terrain3d.py`
  - Add weather role constants for terrain, road, building, billboard, and metal/conductor meshes.
  - Extend `lighting_for_state(state)` with `wet_mix` and `ice_mix`.
  - Add shader uniforms `weather_role`, `wet_mix`, and `ice_mix`.
  - Add `weather_role` to `GLMesh`, set the uniform in `render()`, and assign roles from loaders.
- Modify `energy_grid_game/test_terrain3d.py`
  - Add a missing-field default test for `lighting_for_state`.
  - Add a mixed lit/unlit draw-order regression test.
  - Add pure/event tests for `wet_mix`/`ice_mix`.
  - Add a GL smoke test that road-role meshes darken/desaturate under wet weather.
- Modify docs only if the final visual QA leaves a residual asset limitation to record.

---

### Task 1: Add Mesh-Class Weather Roles And Hardening Tests

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`
- Optionally modify: `docs/superpowers/specs/2026-08-06-realtime-3d-terrain-phase4-design.md`

**Interfaces:**
- Change: `lighting_for_state(state) -> {"ambient", "light_tint", "snow_mix", "wet_mix", "ice_mix"}`
- Change: `GLMesh(ctx, prog, pos, nrm, uv, idx, tex, unlit=False, weather_role=WEATHER_TERRAIN)`
- Change: `draw(..., light_tint=(1.0, 1.0, 1.0), snow_mix=0.0, wet_mix=0.0, ice_mix=0.0, ...)`

- [x] **Step 1: Write failing tests**

Add/extend tests in `energy_grid_game/test_terrain3d.py`:

1. `test_lighting_for_state_defaults_without_complete_state`:
   - Call `terrain3d.lighting_for_state(SimpleNamespace())`.
   - Assert keys include `ambient`, `light_tint`, `snow_mix`, `wet_mix`, `ice_mix`.
   - Assert `0.0 <= ambient <= 1.0`, tint has three values, and all mixes are between 0 and 1.

2. Extend `test_lighting_for_state_derives_day_night_winter_and_storm_snow` or add a sibling:
   - `RAIN` gives `wet_mix > 0.0`.
   - `ICE_STORM` gives `ice_mix > 0.0`.
   - `SNOW` keeps `wet_mix` at or above a light wetness value.

3. `test_mixed_lit_and_unlit_meshes_do_not_leak_unlit_state`:
   - Create one unlit red billboard mesh and one lit blue billboard-quad mesh using `terrain3d.GLMesh`.
   - Render them in order with `ambient=0.0` and a normal that produces no directional light for the lit mesh.
   - Assert red reaches full brightness and blue stays dark, proving `unlit` is set per mesh.

4. `test_road_weather_role_darkens_and_desaturates_under_wet_weather`:
   - Create an unlit colored quad `GLMesh(..., weather_role=terrain3d.WEATHER_ROAD)`.
   - Draw once with default weather and once with `wet_mix=1.0`.
   - Assert the wet frame has lower maximum RGB intensity and a smaller max-min channel spread than the dry frame.

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: new tests fail before implementation due missing `wet_mix`/`ice_mix`, `GLMesh.weather_role`, and shader uniforms.

- [x] **Step 2: Implement lighting event outputs**

In `terrain3d.lighting_for_state(state)`:

- Keep current ambient/tint/snow behavior.
- Add `wet_mix = 0.0` and `ice_mix = 0.0` defaults.
- For `RAIN`, set `wet_mix` to about `0.32`.
- For `SNOW`, set `wet_mix` to about `0.10` and preserve stronger snow mix.
- For `ICE_STORM`, set `wet_mix` to about `0.22` and `ice_mix` to about `0.30`.
- Clamp all mixes to `[0, 1]`.

- [x] **Step 3: Implement mesh weather roles**

In `terrain3d.py`, define:

```python
WEATHER_TERRAIN = 0
WEATHER_ROAD = 1
WEATHER_BUILDING = 2
WEATHER_BILLBOARD = 3
WEATHER_METAL = 4
```

Change `GLMesh.__init__` to accept and store `weather_role`, defaulting to `WEATHER_TERRAIN`, and in `render()` set:

```python
self.prog["weather_role"].value = self.weather_role
```

Assign roles:

- terrain `MATERIALS`: `WEATHER_TERRAIN`
- roads: `WEATHER_ROAD`
- buildings: `WEATHER_BUILDING`
- plant/tower billboards: `WEATHER_BILLBOARD`
- conductor strip mesh: `WEATHER_METAL`

- [x] **Step 4: Implement shader weather response**

In `_FRAGMENT_SHADER`, add:

```glsl
uniform int weather_role;
uniform float wet_mix;
uniform float ice_mix;
```

After sampling `texel` and computing `bright`:

- Use a role-adjusted snow amount:
  - roads: `snow_mix * 0.45`
  - billboards: `snow_mix * 0.35`
  - metal: `snow_mix * 0.60`
  - buildings/terrain: full `snow_mix`
- Mix toward pale snow using that adjusted snow amount.
- For road and metal roles, mix toward grayscale/darker wet color by `wet_mix`.
- For road, metal, and building roles, mix slightly toward pale blue-white by `ice_mix`.
- Keep final clamp and global `light_tint`.

- [x] **Step 5: Verify green and regenerate visual smoke**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
git diff --check -- energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py docs/superpowers/specs/2026-08-06-realtime-3d-terrain-phase4-design.md
```

Run low-resolution 3D capture:

```powershell
$env:CAPTURE_TERRAIN3D='1'
$env:CAPTURE_W='800'
$env:CAPTURE_H='520'
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe tools\capture_moments.py C:\Users\sycho\.codex\visualizations\2026\08\06\019fd881-e6aa-71d0-bc4a-35bd1769f801\captures_phase4e_3d
Remove-Item Env:\CAPTURE_TERRAIN3D
Remove-Item Env:\CAPTURE_W
Remove-Item Env:\CAPTURE_H
```

Expected: tests pass, diff check has no whitespace errors beyond existing line-ending warnings, and capture writes all 28 frames.

## Self-Review

- **Spec coverage:** Covers the remaining hardening and material-class weather polish possible without new assets. Roof-only snow remains an asset/mesh-authoring limitation, not a runtime wiring gap.
- **Placeholder scan:** No placeholder markers remain.
- **Default compatibility:** Existing callers that omit `wet_mix`, `ice_mix`, and `weather_role` keep neutral behavior.
