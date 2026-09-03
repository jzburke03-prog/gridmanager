# Terrain3D Default + Full Terrain Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Terrain3D the default renderer and implement the entire `newassets/terrain/gltf` kit as baked, cataloged runtime assets.

**Architecture:** Add a full-kit bake tool that writes `.npz` artifacts plus a manifest for all source glTF files. Keep runtime efficient by proving full catalog availability while loading semantic active meshes, not every source mesh at launch. Flip Terrain3D to default-on with `GRIDMANAGER_TERRAIN3D=0` as the opt-out.

**Tech Stack:** Python 3.12, pygame 2.6, numpy, moderngl, existing hand-rolled glTF loader. No new dependencies and no source asset edits.

## Global Constraints

- `newassets/terrain/gltf` is the canonical full terrain-kit source.
- Raw glTF is bake-time only; runtime reads `.npz` and manifest files.
- `GRIDMANAGER_TERRAIN3D=0`, `false`, `no`, or `off` disables Terrain3D.
- Default game and default capture behavior should use Terrain3D unless explicitly disabled.
- Do not load all 373 GL meshes every game frame; use semantic active sets.
- Use `.codex_portable_build_20260804_001/venv/Scripts/python.exe`; `.venv39` is currently unusable in this workspace.

---

## File Structure

- Create `tools/bake_terrain_kit_meshes.py`
  - Discover all `.gltf` sources.
  - Bake one `.npz` per source to `energy_grid_game/assets/terrain3d/kit`.
  - Write `energy_grid_game/assets/terrain3d/kit_manifest.json`.
- Create `tools/test_bake_terrain_kit_meshes.py`
  - Coverage, uniqueness, manifest, and sample-bake tests.
- Modify `energy_grid_game/ui/terrain3d.py`
  - Default-on `is_enabled()`.
  - Catalog/manifest helpers.
  - Semantic kit source constants and tests.
- Modify `energy_grid_game/test_terrain3d.py`
  - Default/opt-out behavior tests.
  - Catalog coverage and semantic mesh availability tests.
- Modify `tools/capture_moments.py`
  - Keep `CAPTURE_TERRAIN3D=1`; do not force 2D by default.
- Modify `energy_grid_game/test_city_model.py`
  - Source assertions for default-on/opt-out/capture behavior if needed.
- Modify `run_game.py`
  - Fall back to current interpreter when `.venv39` is absent but dependencies are importable.

---

### Task 1: Full Terrain Kit Bake Tool And Manifest

**Files:**
- Create: `tools/bake_terrain_kit_meshes.py`
- Create: `tools/test_bake_terrain_kit_meshes.py`
- Generate: `energy_grid_game/assets/terrain3d/kit/**/*.npz`
- Generate: `energy_grid_game/assets/terrain3d/kit_manifest.json`

**Interfaces:**
- Produces: `discover_assets(src=SRC) -> list[AssetSpec]`
- Produces: `asset_key(rel_path: Path | str) -> str`
- Produces: `bake_asset(spec, out_root=KIT_OUT) -> Path`
- Produces: `write_manifest(specs, out_path=MANIFEST) -> Path`

- [x] **Step 1: Write failing tests**

Create tests that assert:

- discovered asset count equals the number of `.gltf` files under `newassets/terrain/gltf`;
- keys are unique and path-safe;
- expected folders (`Roads`, `Tracks`, `ForestWater`, `Mountains`, `Trees`) are present;
- a sample bake writes a loadable `.npz`;
- manifest entries contain `key`, `family`, `source`, and `artifact`.

- [x] **Step 2: Implement bake tool**

Use `tools.bake_gltf_terrain.load_gltf` and the same `.npz` schema as existing terrain assets: `pos`, `nrm`, `uv`, `idx`, `tex`.

- [x] **Step 3: Run tests and bake all assets**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe tools\test_bake_terrain_kit_meshes.py
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe tools\bake_terrain_kit_meshes.py
```

Expected: tests pass; script writes one artifact for every glTF source plus manifest.

---

### Task 2: Default-On Terrain3D And Launcher Compatibility

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/main.py`
- Modify: `run_game.py`
- Modify: `energy_grid_game/test_terrain3d.py`
- Modify: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Changes: `terrain3d.is_enabled()` returns true by default, false only for explicit false env values.

- [x] **Step 1: Write failing tests**

Add tests for:

- no `GRIDMANAGER_TERRAIN3D` env means `terrain3d.is_enabled()` is true;
- `0`, `false`, `no`, `off` disable it;
- `1`, `true`, `yes`, `on` enable it;
- `run_game.py` contains a current-interpreter fallback when `.venv39` is absent.

- [x] **Step 2: Implement default-on and update comments**

Change `terrain3d.is_enabled()` and stale comments in `main.py`.

- [x] **Step 3: Implement launcher fallback**

If `.venv39` is absent, try to import `pygame` and run `energy_grid_game/main.py`
with the current interpreter. If imports fail, keep the existing readable setup
message.

---

### Task 3: Runtime Catalog Helpers And Semantic Kit Availability

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Produces: `load_kit_manifest(manifest_path=KIT_MANIFEST) -> dict[str, dict]`
- Produces: `KIT_SEMANTIC_SOURCES` mapping runtime semantic names to manifest keys.
- Produces: `available_kit_semantics() -> dict[str, str]`

- [x] **Step 1: Write failing tests**

Tests should assert:

- manifest covers all source glTF files;
- semantic mappings for terrain bases, roads, tracks, water, trees, bushes, stones, cactus, and city building exist in the manifest;
- no semantic mapping points to a missing artifact.

- [x] **Step 2: Implement helpers**

Add manifest loading and semantic mapping. Keep it pure and cheap; do not create
GL meshes in these helpers.

---

### Task 4: Major QC

**Files:**
- Modify docs/plan checkboxes only if needed.
- Generate capture folder under the shared visualization workspace.

**Verification:**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe tools\test_bake_terrain_kit_meshes.py
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
git diff --check -- tools/bake_terrain_kit_meshes.py tools/test_bake_terrain_kit_meshes.py energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py energy_grid_game/test_city_model.py energy_grid_game/main.py run_game.py tools/capture_moments.py docs/superpowers/specs/2026-08-06-terrain3d-default-full-kit-design.md docs/superpowers/plans/2026-08-06-terrain3d-default-full-kit.md
```

Run capture smoke:

```powershell
$env:CAPTURE_W='800'
$env:CAPTURE_H='520'
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe tools\capture_moments.py C:\Users\sycho\.codex\visualizations\2026\08\06\019fd881-e6aa-71d0-bc4a-35bd1769f801\captures_full_kit_3d
Remove-Item Env:\CAPTURE_W
Remove-Item Env:\CAPTURE_H
```

Expected: tests pass, diff check has no whitespace errors beyond line-ending
warnings, capture writes all 28 frames, and visual spot checks confirm Terrain3D
appears by default.

- [x] Bake tests passed.
- [x] Terrain3D tests passed.
- [x] City model tests passed.
- [x] Diff check passed with only CRLF conversion warnings.
- [x] Capture smoke wrote 28 frames to the shared visualization workspace.
- [x] Visual spot checks covered gameplay, night, snow, and overload captures.

## Self-Review

- **Spec coverage:** Covers default-on behavior, full glTF kit bake/catalog, launcher compatibility, semantic runtime availability, and QC.
- **Placeholder scan:** No placeholder markers remain.
- **Type consistency:** Helper names match across tasks.
