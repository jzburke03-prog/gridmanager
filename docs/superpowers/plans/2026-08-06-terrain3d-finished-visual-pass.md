# Terrain3D Finished Visual Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the default Terrain3D frame from a demo-board look into a finished visual presentation with asset variety, real roads, downtown variety, and terrain elevation.

**Architecture:** Keep the full kit manifest as the asset catalog. Expand only the active runtime mesh set needed for the current semantic scene, then deterministically choose variants per tile in `build_instances()` and place terrain at varied/elevated heights. Replace the circular dense-downtown mask with a larger non-circular metro footprint so the populated area dominates the playfield.

**Tech Stack:** Python 3.12, pygame 2.6, numpy, moderngl, existing custom glTF-to-npz kit pipeline.

## Global Constraints

- `newassets/terrain/gltf` remains the canonical terrain-kit source.
- Runtime reads `.npz` artifacts and `kit_manifest.json`, not raw glTF.
- Do not load all 373 GL meshes at launch.
- Terrain3D remains default-on with explicit env opt-out.
- Tests must be written and observed failing before production changes.
- Use `.\.codex_portable_build_20260804_001\venv\Scripts\python.exe` for verification.

---

### Task 1: Visual Regression Tests

**Files:**
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Consumes: `terrain3d.build_instances()`, `terrain3d.load_meshes()`, `terrain3d.KIT_ACTIVE_MESH_SOURCES`.
- Produces: failing tests for active kit source richness, instance elevation variance, and downtown building bucket variety.

- [x] **Step 1: Add failing tests**

Add tests that assert:

- active mesh sources include at least 24 distinct kit keys;
- a real city layout produces more than 20 runtime mesh buckets;
- real city terrain instances include non-zero Y offsets;
- dense downtown maps into at least 8 building mesh buckets.
- sparse terrain decoration props appear in real layouts.
- dense downtown footprint is bigger than the old radius-24 circle and has axis/corner extension.

- [x] **Step 2: Run terrain tests and verify failure**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: fails on the new visual richness tests.

---

### Task 2: Expanded Runtime Kit Variants

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Produces: `TERRAIN_VARIANT_SOURCES`, `ROAD_VARIANT_SOURCES`, `DOWNTOWN_BUILDING_VARIANT_SOURCES`, `RUNTIME_MESH_NAMES`.
- Changes: `load_meshes()` loads a richer active set from the kit manifest.
- Changes: `build_instances()` selects stable variants per tile and applies terrain elevation.
- Changes: `IsoCity._layout()` uses a larger non-circular dense metro footprint.

- [x] **Step 1: Implement minimal variant tables**
- [x] **Step 2: Update `load_meshes()` for variant mesh names**
- [x] **Step 3: Update `build_instances()` for stable variant choice and Y offsets**
- [x] **Step 4: Run terrain tests and verify green**
- [x] **Step 5: Replace circular dense downtown mask with larger metro footprint**

---

### Task 3: Major Visual QC

**Files:**
- Modify: plan checkboxes only if needed.
- Generate: capture folder under shared visualization workspace.

**Verification:**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
git diff --check -- energy_grid_game\ui\terrain3d.py energy_grid_game\test_terrain3d.py energy_grid_game\test_city_model.py docs\superpowers\specs\2026-08-06-terrain3d-finished-visual-pass-design.md docs\superpowers\plans\2026-08-06-terrain3d-finished-visual-pass.md
```

Run capture smoke:

```powershell
$env:CAPTURE_W='800'
$env:CAPTURE_H='520'
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe tools\capture_moments.py C:\Users\sycho\.codex\visualizations\2026\08\06\019fd881-e6aa-71d0-bc4a-35bd1769f801\captures_finished_visual_pass
Remove-Item Env:\CAPTURE_W
Remove-Item Env:\CAPTURE_H
```

Expected: tests pass, capture writes 28 frames, and spot checks show richer downtown, varied terrain/roads, and visible elevation.

- [x] Terrain3D tests passed.
- [x] City model tests passed.
- [x] Diff check passed with only CRLF warnings.
- [x] Capture smoke wrote 28 frames to the shared visualization workspace.
- [x] Visual spot checks covered gameplay, night, snow, and overload captures.
