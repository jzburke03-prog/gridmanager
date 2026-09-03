# Real-Time 3D Terrain Phase 4c Lighting And Weather Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the opt-in 3D terrain pass respond to the existing simulation clock, calendar season, and snow/ice events without changing gameplay or enabling 3D by default.

**Architecture:** Keep `terrain3d.draw()` backward-compatible under neutral daylight defaults, then add explicit shader uniforms for global color tint and snow mix. Add a pure `lighting_for_state(state)` helper that derives those draw parameters from `state.sim_hour`, `state.date.month`, and `state.active_event.kind`. `main.py` passes those parameters into the 3D draw path only when `GRIDMANAGER_TERRAIN3D` is enabled.

**Tech Stack:** Python 3.12, pygame 2.6, numpy, moderngl. No new dependencies and no new assets.

## Global Constraints

- `GRIDMANAGER_TERRAIN3D` stays default-off.
- Do not change capture tooling in this slice.
- Do not change camera behavior, transmission routing, downtown mapping, or billboard unlit defaults.
- Neutral/default `terrain3d.draw()` remains visually compatible for existing tests and call sites.
- Billboard meshes remain unlit for directional lighting, but global tint/snow can still affect the whole 3D world.
- Use `.codex_portable_build_20260804_001/venv/Scripts/python.exe`; `.venv39` is currently unusable.

---

## File Structure

- Modify `energy_grid_game/ui/terrain3d.py`
  - Import existing day/season helpers as needed.
  - Add pure `lighting_for_state(state)`.
  - Add `uniform vec3 light_tint` and `uniform float snow_mix` to `_FRAGMENT_SHADER`.
  - Apply tint/snow after the per-mesh directional/unlit brightness calculation.
  - Add draw parameters for `light_tint` and `snow_mix`, with neutral defaults.
- Modify `energy_grid_game/main.py`
  - Pass `**terrain3d.lighting_for_state(state)` into the opt-in 3D draw call.
- Modify `energy_grid_game/test_terrain3d.py`
  - Add pure helper coverage for day/night/winter/weather lighting values.
  - Add a GL smoke test proving global tint applies to unlit billboards without reintroducing directional darkening.

---

### Task 1: Add State-Derived Lighting Controls To The 3D Pass

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/main.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Add: `terrain3d.lighting_for_state(state) -> dict`
- Change: `terrain3d.draw(..., ambient=0.55, light_tint=(1.0, 1.0, 1.0), snow_mix=0.0, ...)`

- [x] **Step 1: Write failing tests**

Add a pure test that builds simple state objects and asserts:

- noon/summer has higher ambient than night/summer;
- night tint is cooler/dimmer than noon tint;
- winter has non-zero `snow_mix`;
- active `SNOW` or `ICE_STORM` raises `snow_mix` above plain winter.

Add a GL smoke test using a red billboard with `unlit=True`, `ambient=0.0`, and `light_tint=(0.5, 1.0, 1.0)`. Assert the rendered red channel is about half-bright, proving global tint applies while the existing full-bright unlit directional bypass remains intact.

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: new tests fail before implementation because `lighting_for_state`, `light_tint`, and `snow_mix` do not exist.

- [x] **Step 2: Implement pure lighting derivation**

In `terrain3d.py`, add `lighting_for_state(state)`:

- Use `ui.time_of_day.daylight(state.sim_hour)` for the day factor.
- Use `ui.voxel_terrain.season_of(state.date.month)` for season when a date exists; default to summer.
- Return at least:
  - `ambient`: readable night floor and brighter daylight ceiling;
  - `light_tint`: neutral in daylight, cooler/dimmer at night, slightly cool in winter;
  - `snow_mix`: 0 in non-winter clear weather, modest in winter, stronger for `SNOW`/`ICE_STORM`.

- [x] **Step 3: Implement shader and draw uniforms**

In `_FRAGMENT_SHADER`:

- Add `uniform vec3 light_tint;`
- Add `uniform float snow_mix;`
- Keep existing `unlit` behavior for directional lighting.
- Mix `texel.rgb` toward a pale snow color by `snow_mix`.
- Multiply the resulting color by `bright * light_tint` and clamp to `[0, 1]`.

In `draw()`:

- Add neutral default parameters.
- Set the new uniforms before rendering any meshes.

- [x] **Step 4: Wire main loop**

In `main.py`, pass `**terrain3d.lighting_for_state(state)` into `terrain3d.draw()` in the `TERRAIN3D_ENABLED` branch.

- [x] **Step 5: Verify green**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
git diff --check -- energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py energy_grid_game/main.py
```

Expected: terrain3d and city-model checks pass; diff check has no whitespace errors beyond existing line-ending warnings.

## Self-Review

- **Spec coverage:** Covers Phase 4 day/night, season, and first-pass snow response for the 3D layer. Capture tooling and more material-specific snow remain separate slices.
- **Placeholder scan:** No placeholder markers are expected.
- **Default compatibility:** Existing tests that omit lighting args should continue to use neutral daylight defaults.
