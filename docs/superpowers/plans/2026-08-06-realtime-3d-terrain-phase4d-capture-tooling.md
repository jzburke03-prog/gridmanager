# Real-Time 3D Terrain Phase 4d Capture Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `tools/capture_moments.py` produce opt-in 3D terrain review frames without changing the default 2D capture path.

**Architecture:** Keep the existing capture script as the owner of all visual-regression frames. Add a small optional 3D resource bundle inside the harness that mirrors `main.py`'s terrain path: set up a headless GL context, load terrain meshes, upload instances when `IsoCity.layout_key` changes, render to an FBO, read back to a pygame surface, blit that surface before `city.draw()`, and release resources when the harness rebuilds games. `CAPTURE_TERRAIN3D=1` forces `GRIDMANAGER_TERRAIN3D=1` before importing game modules so `IsoCity._bake()` suppresses 2D layers covered by the 3D pass.

**Tech Stack:** Python 3.12, pygame 2.6, numpy, moderngl. No new dependencies and no new assets.

## Global Constraints

- Default capture behavior stays 2D unless `CAPTURE_TERRAIN3D=1` or `GRIDMANAGER_TERRAIN3D=1`.
- `CAPTURE_TERRAIN3D=1` must enable `terrain3d.is_enabled()` before `main`, `IsoCity`, or `terrain3d` are imported.
- Reuse `terrain3d.lighting_for_state(state)` so day/night/snow capture frames exercise Phase 4c.
- Do not change gameplay, HUD layout, camera behavior, or the list/order of saved capture names.
- Release per-layout billboard/transmission/FBO resources when rebuilding captures.
- Use `.codex_portable_build_20260804_001/venv/Scripts/python.exe`; `.venv39` is currently unusable.

---

## File Structure

- Modify `tools/capture_moments.py`
  - Add env helper for `CAPTURE_TERRAIN3D`.
  - Add optional 3D init/render/release helpers.
  - Integrate the 3D surface into `render_game()` before `city.draw()`.
  - Release resources before replacing `w` in `fresh_game()` and at the end of `capture()`.
- Modify `energy_grid_game/test_city_model.py`
  - Add a source-level regression that capture tooling supports `CAPTURE_TERRAIN3D`, wires `terrain3d.lighting_for_state`, and keeps `.draw_homes_label(` absent.

---

### Task 1: Add Opt-In 3D Rendering To Capture Harness

**Files:**
- Modify: `tools/capture_moments.py`
- Modify: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Env: `CAPTURE_TERRAIN3D=1` enables the 3D capture path and forces `GRIDMANAGER_TERRAIN3D=1`.
- Existing CLI stays: `python tools/capture_moments.py [out_dir]`.

- [x] **Step 1: Write failing source-level regression**

In `energy_grid_game/test_city_model.py`, extend or add a test that reads `tools/capture_moments.py` and asserts:

- `"CAPTURE_TERRAIN3D"` appears;
- `"GRIDMANAGER_TERRAIN3D"` appears;
- `"terrain3d.lighting_for_state"` appears;
- `"load_transmission"` or `"build_transmission_geometry"` appears;
- `".draw_homes_label("` remains absent.

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
```

Expected: the new source assertions fail before implementation.

- [x] **Step 2: Implement env gate before game imports**

At the top of `tools/capture_moments.py`, add a truthy env helper and, when `CAPTURE_TERRAIN3D=1`, set:

```python
os.environ["GRIDMANAGER_TERRAIN3D"] = "1"
```

This must happen before `_build()` imports `main`, `IsoCity`, or `terrain3d`.

- [x] **Step 3: Implement optional 3D resource helpers**

Add helpers in `tools/capture_moments.py`:

- `_init_terrain3d_capture()` returns `None` when disabled, otherwise creates:
  - `ctx = gl_context.create_context()`
  - `prog = terrain3d.create_program(ctx)`
  - `meshes = terrain3d.load_meshes(ctx, prog)`
  - `layout_key = None`
  - `fbo = None`
  - `plant_meshes = []`
  - `transmission_meshes = None`
- `_release_terrain3d_capture(bundle)` releases plant meshes, transmission meshes, FBO attachments, terrain meshes, and context.
- `_render_terrain3d_capture(bundle, city, city_rect, state)` mirrors `main.py`:
  - upload instances when `city.layout_key` changes;
  - rebuild plant billboards and transmission meshes;
  - recreate FBO when size changes;
  - call `terrain3d.draw(..., billboard_meshes=..., transmission_meshes=..., world_origin=city._origin, **terrain3d.lighting_for_state(state))`;
  - return `terrain3d.to_surface(...)`.

- [x] **Step 4: Integrate with render/rebuild lifecycle**

In `_build()`, include the optional bundle in `w`.

In `render_game(frame, st, w)`:

- clear the frame;
- sample atmosphere;
- call `w["city"].prepare(city_rect, st)`;
- render/blit the optional 3D surface before `w["city"].draw(...)`;
- then continue with atmosphere, chart, pins, HUD, speed, audio indicator as before.

In `fresh_game()`, release the current bundle before replacing `w = _build()`.

At the end of `capture()`, release the current bundle in a `finally`-style path.

- [x] **Step 5: Verify green and smoke capture**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
git diff --check -- tools/capture_moments.py energy_grid_game/test_city_model.py
```

Then run a low-resolution 3D capture smoke:

```powershell
$env:CAPTURE_TERRAIN3D='1'
$env:CAPTURE_W='800'
$env:CAPTURE_H='520'
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe tools\capture_moments.py C:\Users\sycho\.codex\visualizations\2026\08\06\019fd881-e6aa-71d0-bc4a-35bd1769f801\captures_phase4d_3d
Remove-Item Env:\CAPTURE_TERRAIN3D
Remove-Item Env:\CAPTURE_W
Remove-Item Env:\CAPTURE_H
```

Expected: tests pass, diff check has no whitespace errors beyond existing line-ending warnings, and the smoke capture writes the normal capture set without crashing.

## Self-Review

- **Spec coverage:** Covers the Phase 4 capture tooling requirement for opt-in 3D day/night/weather/zoom frames. Visual inspection and material-specific snow remain subsequent QA/polish work.
- **Placeholder scan:** No placeholder markers are expected.
- **Default compatibility:** Running the capture script without env vars should use the existing 2D path.
