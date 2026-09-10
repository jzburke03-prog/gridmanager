# Real-Time 3D Terrain Phase 4a Dense Downtown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing dense downtown (`vroad` / `voxel_bldg`) visible through the opt-in 3D terrain renderer so Phase 4 no longer depends on old 2D downtown branches for the central city.

**Architecture:** Keep the dense downtown stamp in `IsoCity` as the semantic source of truth. `ui/terrain3d.py` maps dense downtown tile kinds into existing road and building mesh buckets, then exposes one helper that tells `IsoCity._bake()` which 2D tile branches are covered by the 3D pass. `test_city_model.py` replaces the stale old-`bldg` downtown assertion with a dense-downtown contract so the city-model suite can go green for this architecture slice.

**Tech Stack:** Python 3.12, pygame 2.6, numpy, moderngl. No new dependencies and no new baked mesh assets in Phase 4a.

## Global Constraints

- `GRIDMANAGER_TERRAIN3D` stays default-off.
- Keep the dense downtown layout as the current visible city and gameplay-lighting source.
- Reuse existing `ROAD_MATERIALS` and `BUILDING_MATERIALS`; do not add bespoke downtown `.npz` assets in this slice.
- Keep `_priority`, building illumination, distribution service groups, traffic occlusion, and plant-control avoidance semantically unchanged.
- Do not touch day/night/season lighting, snow, capture tooling, or billboard unlit shaders in this slice.
- Use `.codex_portable_build_20260804_001/venv/Scripts/python.exe`; `.venv39` is currently unusable.

---

## File Structure

- Modify `energy_grid_game/ui/terrain3d.py`
  - Add `DOWNTOWN_BUILDING_MATERIAL_FOR_SLUG`.
  - Add `downtown_vroad_shape_yaw(col, row)`.
  - Add `covers_tile_kind(kind)`.
  - Extend `build_instances()` to emit instances for `vroad` and `voxel_bldg`.
- Modify `energy_grid_game/ui/iso_city.py`
  - Replace the hard-coded terrain3d skip tuple in `_bake()` with `terrain3d.covers_tile_kind(kind)`.
- Modify `energy_grid_game/test_terrain3d.py`
  - Add pure tests for dense downtown mapping and real-layout 3D building coverage.
- Modify `energy_grid_game/test_city_model.py`
  - Replace `test_layout_reserves_city_center_sprites_near_downtown` with a dense-downtown city-center contract that matches the current layout.

---

### Task 1: Map Dense Downtown Tiles Into 3D Instance Buckets

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Produces: `DOWNTOWN_BUILDING_MATERIAL_FOR_SLUG: dict[str, str]`
- Produces: `downtown_vroad_shape_yaw(col: int, row: int) -> tuple[str, float]`
- Changes: `build_instances(tiles)` includes `vroad` and `voxel_bldg`.

- [ ] **Step 1: Write failing pure tests**

Add to `energy_grid_game/test_terrain3d.py` near the existing `build_instances` tests:

```python
def test_build_instances_maps_dense_downtown_voxel_buildings():
    tiles = {
        (0, 0): ("voxel_bldg", "apartment"),
        (1, 0): ("voxel_bldg", "market"),
        (2, 0): ("voxel_bldg", "school"),
    }
    instances = build_instances(tiles)
    assert instances["tower"].shape == (1, 4)
    assert instances["shop"].shape == (1, 4)
    assert instances["block"].shape == (1, 4)
```

Add:

```python
def test_build_instances_maps_dense_downtown_vroads_by_grid_role():
    tiles = {
        (0, 0): ("vroad", None),
        (4, 1): ("vroad", None),
        (1, 4): ("vroad", None),
    }
    instances = build_instances(tiles)
    assert instances["cross"].shape == (1, 4)
    assert instances["straight"].shape == (2, 4)
    assert set(instances["straight"][:, 3]) == {0.0, 90.0}
```

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: both new tests fail because `voxel_bldg` and `vroad` are still skipped.

- [ ] **Step 2: Implement downtown mapping helpers**

In `energy_grid_game/ui/terrain3d.py`, import the pure dense downtown constants:

```python
from ui import voxel_city as vc
```

Add near `BUILDING_MATERIALS`:

```python
DOWNTOWN_BUILDING_MATERIAL_FOR_SLUG = {
    "house": "house",
    "market": "shop",
    "school": "block",
    "mall": "midrise",
    "department_store": "midrise",
    "apartment": "tower",
    "building_2": "midrise",
    "building_3": "midrise",
    "building_4": "tower",
    "building_5": "tower",
}
```

Add after `ROAD_ROLE_TO_SHAPE_YAW`:

```python
def downtown_vroad_shape_yaw(col, row):
    if col % vc.BLOCK == 0 and row % vc.BLOCK == 0:
        return "cross", 0.0
    if col % vc.BLOCK == 0:
        return "straight", 0.0
    if row % vc.BLOCK == 0:
        return "straight", 90.0
    return "cross", 0.0
```

In `build_instances()`, after the existing `road` branch:

```python
        elif kind == "vroad":
            shape, yaw = downtown_vroad_shape_yaw(col, row)
            buckets[shape].append((x, 0.0, z, yaw))
```

After the existing `urban_block` branch:

```python
        elif kind == "voxel_bldg":
            archetype = DOWNTOWN_BUILDING_MATERIAL_FOR_SLUG.get(extra)
            if archetype is None:
                raise ValueError(f"unrecognized downtown building slug: {extra!r}")
            buckets[archetype].append((x, 0.0, z, 0.0))
```

- [ ] **Step 3: Verify green for Task 1**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: all terrain3d checks pass.

- [ ] **Step 4: Checkpoint diff**

Run:

```powershell
git diff -- energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
```

---

### Task 2: Prove Real Dense Downtown Produces 3D Roads And Buildings

**Files:**
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Consumes: `build_instances(tiles)` dense downtown behavior from Task 1.

- [ ] **Step 1: Write failing real-layout coverage test**

Update `test_build_instances_produces_road_instances_from_a_real_city_layout()` so the stale comment about zero building instances is removed, then assert real dense downtown building coverage:

```python
def test_build_instances_produces_road_and_building_instances_from_a_real_city_layout():
    rect = pygame.Rect(0, 0, 1400, 410)
    city = IsoCity(None)
    city._layout(rect, 2_000_000, ("gas",))
    instances = build_instances(city.tiles)
    road_instance_count = sum(len(v) for k, v in instances.items() if k in ROAD_MATERIALS)
    building_instance_count = sum(len(v) for k, v in instances.items() if k in BUILDING_MATERIALS)
    assert road_instance_count > 0
    assert building_instance_count > 20
```

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected before Task 1 code: `building_instance_count == 0`. Expected after Task 1 code: this test passes.

- [ ] **Step 2: Verify green for Task 2**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: all terrain3d checks pass.

---

### Task 3: Centralize 2D Suppression For 3D-Covered Tile Kinds

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Produces: `covers_tile_kind(kind: str) -> bool`
- Consumes: `terrain3d.covers_tile_kind(kind)` in `IsoCity._bake()`.

- [ ] **Step 1: Write failing helper test**

Add to `energy_grid_game/test_terrain3d.py`:

```python
def test_covers_tile_kind_includes_dense_downtown_layers():
    from ui import terrain3d
    assert terrain3d.covers_tile_kind("grass")
    assert terrain3d.covers_tile_kind("road")
    assert terrain3d.covers_tile_kind("vroad")
    assert terrain3d.covers_tile_kind("voxel_bldg")
    assert not terrain3d.covers_tile_kind("pad")
    assert not terrain3d.covers_tile_kind("campus")
```

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: import/name failure for `covers_tile_kind`.

- [ ] **Step 2: Implement helper and wire `_bake()`**

In `energy_grid_game/ui/terrain3d.py`, add:

```python
def covers_tile_kind(kind):
    return kind in (
        "grass", "farm", "tree", "water", "mountain", "road",
        "vroad", "voxel_bldg",
    )
```

In `energy_grid_game/ui/iso_city.py`, replace:

```python
            if terrain3d.is_enabled() and kind in ("grass", "farm", "tree", "water", "mountain", "road"):
                continue
```

with:

```python
            if terrain3d.is_enabled() and terrain3d.covers_tile_kind(kind):
                continue
```

- [ ] **Step 3: Verify green for Task 3**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: all terrain3d checks pass.

---

### Task 4: Replace The Stale City-Center Architecture Assertion

**Files:**
- Modify: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: the existing dense downtown tile contract from `IsoCity._layout()`.

- [ ] **Step 1: Rewrite the failing assertion around the current dense downtown contract**

Replace `test_layout_reserves_city_center_sprites_near_downtown()` with:

```python
def test_layout_places_dense_downtown_and_city_centers_near_core():
    city = IsoCity(None)
    city._layout(RECT, 200_000, ("gas",))
    kinds = [kind for kind, _extra in city._tiles.values()]
    assert kinds.count("voxel_bldg") > 20
    assert kinds.count("vroad") > 20
    assert city._city_centers
    for col, row, _entry in city._city_centers:
        assert abs(col - row) <= 10
        assert abs(col + row) <= 10
```

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
```

Expected: the previously known `test_layout_reserves_city_center_sprites_near_downtown` failure is gone. If any failure remains, inspect it before proceeding.

- [ ] **Step 2: Verify city-model suite**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
```

Expected: all city-model checks pass.

---

### Task 5: Final Phase 4a Verification And Review

**Files:**
- Review only:
  - `energy_grid_game/ui/terrain3d.py`
  - `energy_grid_game/ui/iso_city.py`
  - `energy_grid_game/test_terrain3d.py`
  - `energy_grid_game/test_city_model.py`

- [ ] **Step 1: Run final verification**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
git diff --check -- energy_grid_game/ui/terrain3d.py energy_grid_game/ui/iso_city.py energy_grid_game/test_terrain3d.py energy_grid_game/test_city_model.py
git status --short -- energy_grid_game/ui/terrain3d.py energy_grid_game/ui/iso_city.py energy_grid_game/test_terrain3d.py energy_grid_game/test_city_model.py
```

Expected: both Python test files pass; diff check has no whitespace errors; scoped status shows only intended files.

- [ ] **Step 2: Request code review**

Dispatch a read-only reviewer with the Phase 4a plan and scoped diff. Ask specifically whether:

- dense downtown building slug mapping is reasonable for the existing mesh buckets;
- `vroad` orientation matches the 4-tile grid semantics;
- `covers_tile_kind()` does not hide any 2D layer that lacks 3D coverage;
- the city-model test update removes stale architecture debt instead of masking a real regression.

- [ ] **Step 3: Address review findings**

Fix Critical and Important findings with new failing tests first. Re-run the final verification commands after fixes.

## Self-Review

- **Spec coverage:** This plan covers the Phase 4 architecture debt first: dense downtown tile consumption, 2D duplicate suppression under `GRIDMANAGER_TERRAIN3D`, and the stale city-center assertion. Lighting, snow, capture tooling, and unlit billboard shaders remain separate Phase 4 slices.
- **Placeholder scan:** No placeholder markers remain.
- **Type consistency:** `DOWNTOWN_BUILDING_MATERIAL_FOR_SLUG`, `downtown_vroad_shape_yaw`, `covers_tile_kind`, and `build_instances` are consistently named across tasks.
