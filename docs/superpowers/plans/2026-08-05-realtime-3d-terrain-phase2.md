# Real-Time 3D Terrain — Phase 2 Implementation Plan (Roads + Buildings)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render outer-ring roads (`road_network.py`, unchanged) and suburban buildings (`IsoCity`'s `urban_block` archetypes, unchanged) as instanced, per-instance-rotatable 3D meshes, extending Phase 1's terrain pipeline rather than duplicating it.

**Architecture:** Generalize Phase 1's instance format from `(N,3)` positions to `(N,4)` `[x,y,z,yaw_degrees]` for every material (terrain tiles keep `yaw=0`), so one GL code path (`GLMesh`, shader, `draw`) serves terrain, roads, and buildings uniformly. Bake 4 road-shape meshes and 5 building meshes the same way Phase 1 baked terrain meshes. Dense-downtown reconciliation is explicitly out of scope (see spec).

**Tech Stack:** Same as Phase 1 (moderngl, numpy, pygame) — no new dependencies.

## Global Constraints

- `TILE_SPACING = 3.2` (existing) still applies to road/building placement — one road or building instance per tile, at the same grid pitch as terrain.
- Instance format changes from `(N,3)` to `(N,4)` for **every** material, including Phase 1's existing terrain materials — do not special-case terrain vs. road/building instance shapes.
- Road role → shape/yaw mapping (exact, from the spec): `straight_ne`→(straight, 0°), `straight_nw`→(straight, 90°), `corner_ne`→(corner, 0°), `corner_nw`→(corner, 90°), `tee_ne`→(tee, 0°), `tee_nw`→(tee, 90°), `cross`→(cross, 0°).
- Building archetype → mesh (exact, from the spec): `house`→Building01, `shop`→Building02, `block`→Building03, `midrise`→Building04, `tower`→Building05, all from `newassets/City Voxel Pack/OBJ/`.
- Road source meshes (exact, from the spec): straight=`Roads/road-straight-1.gltf`, corner=`Roads/road-edgy-curve-1.gltf`, tee=`Roads/road-edgy-3-way-crossing-1.gltf`, cross=`Roads/road-edgy-4-way-crossing-1.gltf`.
- `GRIDMANAGER_TERRAIN3D` stays default-off; this phase does not change that or touch `main.py`'s gating logic.
- Dense downtown tiles (`vroad`, `voxel_bldg`, `pad`) are NOT rendered in 3D this phase — `build_instances` must continue skipping them (already true, since they're not in any bucket).
- Tests are plain scripts (`test_*` via `globals()` reflection), same convention as Phase 1.
- Venv: `.codex_portable_build_20260804_001\venv\Scripts\python.exe`.
- Git hygiene is not a concern in this repo (confirmed by the user) — normal commits are fine even if a touched file has unrelated pre-existing content.

---

### Task 1: Bake road and building meshes

**Files:**
- Create: `tools/bake_road_building_meshes.py`
- Test: `tools/test_bake_road_building_meshes.py`

**Interfaces:**
- Consumes: `load_gltf` and `load_obj` from `tools/bake_gltf_terrain.py` (both already exist, unchanged; `load_obj` already used there for `Building02-05.obj`).
- Produces: 4 files `energy_grid_game/assets/terrain3d/roads/{straight,corner,tee,cross}.npz` and 5 files `energy_grid_game/assets/terrain3d/buildings/{house,shop,block,midrise,tower}.npz`, same `.npz` schema as Phase 1 (`pos`, `nrm`, `uv`, `idx`, `tex`).

- [ ] **Step 1: Write the failing test**

Create `tools/test_bake_road_building_meshes.py`:

```python
"""Road/building mesh bake checks. Run: python test_bake_road_building_meshes.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from bake_road_building_meshes import ROAD_SOURCES, BUILDING_SOURCES, bake_road, bake_building


def test_road_sources_cover_the_four_shapes():
    assert set(ROAD_SOURCES) == {"straight", "corner", "tee", "cross"}
    for rel_path in ROAD_SOURCES.values():
        assert rel_path.endswith(".gltf")


def test_building_sources_cover_the_five_archetypes():
    assert set(BUILDING_SOURCES) == {"house", "shop", "block", "midrise", "tower"}
    for rel_path in BUILDING_SOURCES.values():
        assert rel_path.endswith(".obj")


def test_bake_road_writes_a_loadable_npz():
    import tempfile
    from pathlib import Path
    out_dir = Path(tempfile.mkdtemp())
    out_path = bake_road("straight", out_dir)
    assert out_path.exists()
    data = np.load(out_path)
    assert data["pos"].shape[1] == 3
    assert data["idx"].shape[1] == 3
    assert data["tex"].ndim == 3 and data["tex"].shape[2] == 4


def test_bake_building_writes_a_loadable_npz():
    import tempfile
    from pathlib import Path
    out_dir = Path(tempfile.mkdtemp())
    out_path = bake_building("house", out_dir)
    assert out_path.exists()
    data = np.load(out_path)
    assert data["pos"].shape[1] == 3
    assert data["idx"].shape[1] == 3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall bake_road_building_meshes checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tools/test_bake_road_building_meshes.py`
Expected: `ModuleNotFoundError: No module named 'bake_road_building_meshes'`

- [ ] **Step 3: Write the implementation**

Create `tools/bake_road_building_meshes.py`:

```python
#!/usr/bin/env python3
"""Bake the 4 road-shape meshes and 5 building-archetype meshes Phase 2 needs
into .npz files, the same way tools/bake_terrain_meshes.py baked Phase 1's
terrain materials. Road shapes: one mesh per SHAPE (straight/corner/tee/
cross), not one per road_network.py role string -- roles like straight_ne
vs straight_nw are the same shape at a different yaw, applied per-instance
at render time by ui/terrain3d.py, not baked as separate meshes. See
docs/superpowers/specs/2026-08-05-realtime-3d-terrain-phase2-design.md.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bake_gltf_terrain import load_gltf, load_obj  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GLTF_SRC = ROOT / "newassets" / "terrain" / "gltf"
OBJ_SRC = ROOT / "newassets" / "City Voxel Pack" / "OBJ"
OUT = ROOT / "energy_grid_game" / "assets" / "terrain3d"

ROAD_SOURCES = {
    "straight": "Roads/road-straight-1.gltf",
    "corner": "Roads/road-edgy-curve-1.gltf",
    "tee": "Roads/road-edgy-3-way-crossing-1.gltf",
    "cross": "Roads/road-edgy-4-way-crossing-1.gltf",
}

BUILDING_SOURCES = {
    "house": "Building01.obj",
    "shop": "Building02.obj",
    "block": "Building03.obj",
    "midrise": "Building04.obj",
    "tower": "Building05.obj",
}


def _save(out_path, pos, nrm, uv, idx, tex):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out_path,
              pos=pos.astype("f4"), nrm=nrm.astype("f4"),
              uv=uv.astype("f4"), idx=idx.astype("i4"),
              tex=tex.astype("u1"))
    return out_path


def bake_road(shape, out_dir=OUT / "roads"):
    pos, nrm, uv, idx, tex = load_gltf(GLTF_SRC / ROAD_SOURCES[shape])
    return _save(out_dir / f"{shape}.npz", pos, nrm, uv, idx, tex)


def bake_building(archetype, out_dir=OUT / "buildings"):
    pos, nrm, uv, idx, tex = load_obj(OBJ_SRC / BUILDING_SOURCES[archetype])
    return _save(out_dir / f"{archetype}.npz", pos, nrm, uv, idx, tex)


def main():
    for shape in ROAD_SOURCES:
        out_path = bake_road(shape)
        print(f"baked road/{shape} -> {out_path.relative_to(ROOT)}")
    for archetype in BUILDING_SOURCES:
        out_path = bake_building(archetype)
        print(f"baked building/{archetype} -> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tools/test_bake_road_building_meshes.py`
Expected: all 4 tests pass.

- [ ] **Step 5: Run the bake and commit**

```bash
python tools/bake_road_building_meshes.py
git add tools/bake_road_building_meshes.py tools/test_bake_road_building_meshes.py energy_grid_game/assets/terrain3d/roads/ energy_grid_game/assets/terrain3d/buildings/
git commit -m "Bake road and building meshes for Phase 2"
```

---

### Task 2: Extend the instance format to carry per-instance yaw

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Changes `build_instances(tiles) -> dict[str, np.ndarray]` output shape from `(N,3)` to `(N,4)` (`[x,y,z,yaw_degrees]`) for every material key it returns, including the existing Phase 1 terrain materials (which always get `yaw=0.0`).
- Changes `GLMesh`'s instance vertex format from `"3f/i"` (`in_offset` only) to `"3f 1f/i"` (`in_offset` vec3 + `in_yaw` float), and `_VERTEX_SHADER` gains a per-instance Y-axis rotation applied to `in_pos`/`in_normal` before adding `in_offset`.
- `upload_instances`'s empty-array fallback changes from `np.zeros((0,3))` to `np.zeros((0,4))`.

This task has no NEW automated GL behavior test beyond updating existing ones (Task 5 adds the rotation-specific GL smoke test) — the goal here is "instance format now carries yaw, terrain still renders identically since yaw=0 is a no-op rotation."

- [ ] **Step 1: Update `build_instances` to emit yaw=0 for terrain materials**

In `energy_grid_game/ui/terrain3d.py`, change `build_instances`:

```python
def build_instances(tiles):
    """Pure tile-dict -> per-material instance offsets. No GL calls.

    `tiles` is shaped like IsoCity.tiles: {(col, row): (kind, extra)}.
    Returns {material: (N,4) float32 array of [x, y, z, yaw_degrees]} --
    every material uses this 4-column format (Phase 2 generalization),
    even terrain materials that never rotate (yaw always 0.0 for them).
    col and row are swapped (col feeds world Z, row feeds world -X) so the
    projected result matches ui.iso_city.iso_xy's (col - row, col + row)
    diamond axes -- see test_build_instances_matches_iso_xy_sign_convention.
    """
    buckets = {material: [] for material in MATERIALS}
    for (col, row), (kind, _extra) in tiles.items():
        if kind in buckets:
            buckets[kind].append(
                (-float(row) * TILE_SPACING, 0.0, float(col) * TILE_SPACING, 0.0))
    return {
        material: np.array(offsets, dtype="f4").reshape(-1, 4)
        for material, offsets in buckets.items()
        if offsets
    }
```

- [ ] **Step 2: Update existing tests for the new 4-column shape**

In `energy_grid_game/test_terrain3d.py`, update every assertion that checks `instances[material].shape` or exact offset values to expect 4 columns instead of 3, and to include a trailing `0.0` yaw in expected tuples. For example, `test_build_instances_offset_matches_col_row` should assert:

```python
assert np.array_equal(
    instances["grass"][0],
    np.array([0.0, 0.0, 3 * 3.2, 0.0], dtype="f4"))
```

(adjust the exact expected numbers to whatever `(col, row)` that test already uses — keep the test's existing `(col, row)` input, just append the `0.0` yaw column and recompute `x`/`z` with the existing `TILE_SPACING`/swap-and-negate formula, which is unchanged). Do the same for `test_build_instances_matches_iso_xy_sign_convention` (unpack `cam = CAM_ROT @ offset[:3]`, ignoring the 4th/yaw column) and any shape assertion (`instances[material].shape == (1, 3)` becomes `(1, 4)`).

- [ ] **Step 3: Update `GLMesh` and the shader for per-instance yaw**

In `energy_grid_game/ui/terrain3d.py`, change the `_VERTEX_SHADER` string:

```python
_VERTEX_SHADER = """
#version 330
uniform mat3 cam_rot;
uniform float px_per_unit;
uniform float zoom;
uniform vec2 img_size;
uniform vec2 origin;
in vec3 in_pos;
in vec3 in_normal;
in vec2 in_uv;
in vec3 in_offset;
in float in_yaw;
out vec2 v_uv;
out vec3 v_normal;
void main() {
    float rad = radians(in_yaw);
    float c = cos(rad);
    float s = sin(rad);
    mat3 yaw_rot = mat3(c, 0.0, -s,
                         0.0, 1.0, 0.0,
                         s, 0.0, c);
    vec3 local = yaw_rot * in_pos;
    vec3 normal = yaw_rot * in_normal;
    vec3 world = local + in_offset;
    vec3 cam = cam_rot * world;
    float sx = cam.x * px_per_unit * zoom;
    float sy = -cam.y * px_per_unit * zoom;
    float depth = -cam.y + 0.35 * cam.z;
    vec2 screen_px = vec2(sx, sy) - origin;
    float ndc_x = screen_px.x / img_size.x * 2.0 - 1.0;
    float ndc_y = screen_px.y / img_size.y * 2.0 - 1.0;
    gl_Position = vec4(ndc_x, ndc_y, -depth * 0.01, 1.0);
    v_uv = in_uv;
    v_normal = normal;
}
"""
```

Change `GLMesh.__init__`'s vertex_array content list and buffer reserve size:

```python
        self.instance_vbo = ctx.buffer(reserve=16)  # 1 instance (x,y,z,yaw) placeholder
        self.vao = ctx.vertex_array(
            prog,
            [(self.vbo, "3f 3f 2f", "in_pos", "in_normal", "in_uv"),
             (self.instance_vbo, "3f 1f/i", "in_offset", "in_yaw")],
            self.ibo,
        )
```

Change `GLMesh.set_instances`'s minimum reserve size from `12` to `16` (bytes for one `(x,y,z,yaw)` float32 instance):

```python
    def set_instances(self, offsets):
        data = offsets.astype("f4").tobytes()
        self.instance_vbo.orphan(max(len(data), 16))
        if len(data):
            self.instance_vbo.write(data)
        self.instance_count = len(offsets)
```

- [ ] **Step 4: Update `upload_instances`'s empty-array fallback**

```python
def upload_instances(ctx, meshes, instances):
    empty = np.zeros((0, 4), dtype="f4")
    for material, mesh in meshes.items():
        mesh.set_instances(instances.get(material, empty))
```

- [ ] **Step 5: Run tests, fix any failures, commit**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: all tests pass (yaw=0 rotation is a no-op, so terrain rendering output should be
unchanged — if `test_draw_produces_a_readable_framebuffer_with_visible_content` was passing
`np.array([[0.0, 0.0, 0.0]], dtype="f4")` as a test instance array, update it to
`np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4")` to match the new 4-column format).

```bash
git add energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
git commit -m "Extend terrain3d instance format to carry per-instance yaw"
```

---

### Task 3: Bucket road and building tiles in `build_instances`

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Consumes: `IsoCity.tiles` entries with `kind == "road"` (payload is the role string, e.g.
  `"straight_ne"`, per `ui/iso_city.py:1855` `tiles[pos] = ("road", road)` where `road` is
  whatever `road_network.py`'s role assignment produced) and `kind == "urban_block"` (payload is
  whatever `_building_tile` returns — read `ui/iso_city.py:219-231` to confirm the exact shape of
  that payload and how to extract the archetype name string from it before writing this task's
  code; the plan's earlier description said "archetype_name" is embedded via
  `_building_tile(col, row, district, archetype_name)`, but confirm exactly how to read it back
  out of the tile payload rather than assuming).
- Adds `ROAD_MATERIALS = ("straight", "corner", "tee", "cross")` and
  `BUILDING_MATERIALS = ("house", "shop", "block", "midrise", "tower")` constants.
- Adds `ROAD_ROLE_TO_SHAPE_YAW = {"straight_ne": ("straight", 0.0), "straight_nw": ("straight", 90.0), "corner_ne": ("corner", 0.0), "corner_nw": ("corner", 90.0), "tee_ne": ("tee", 0.0), "tee_nw": ("tee", 90.0), "cross": ("cross", 0.0)}`.
- `build_instances` now also populates `ROAD_MATERIALS` and `BUILDING_MATERIALS` buckets (in
  addition to the existing `MATERIALS` terrain buckets), still returning one flat
  `dict[str, (N,4) array]` covering all of them.

- [ ] **Step 1: Confirmed `urban_block` tile payload shape (no investigation needed)**

`ui/iso_city.py:225-231`'s `_building_tile(col, row, district, archetype_name)` returns
`UrbanBlock(..., buildings=(archetype_name,))` — a `ui.urban_blocks.UrbanBlock` instance whose
`.buildings` attribute is a 1-tuple containing the archetype name string
(`house`/`shop`/`block`/`midrise`/`tower`). So for a `("urban_block", extra)` tile, the archetype
name is `extra.buildings[0]`. This is confirmed, not a guess — use it directly in Step 4, no
`hasattr` hedging needed.

- [ ] **Step 2: Write the failing tests**

Add to `energy_grid_game/test_terrain3d.py`:

```python
from ui.terrain3d import (BUILDING_MATERIALS, ROAD_MATERIALS,
                           ROAD_ROLE_TO_SHAPE_YAW)


def test_build_instances_buckets_road_tiles_by_shape_with_correct_yaw():
    tiles = {
        (0, 0): ("road", "straight_ne"),
        (1, 0): ("road", "straight_nw"),
        (2, 0): ("road", "cross"),
    }
    instances = build_instances(tiles)
    assert instances["straight"].shape == (2, 4)
    yaws = sorted(instances["straight"][:, 3].tolist())
    assert yaws == [0.0, 90.0]
    assert instances["cross"].shape == (1, 4)
    assert instances["cross"][0, 3] == 0.0


def test_road_role_to_shape_yaw_covers_all_seven_roles():
    assert set(ROAD_ROLE_TO_SHAPE_YAW) == {
        "straight_ne", "straight_nw", "corner_ne", "corner_nw",
        "tee_ne", "tee_nw", "cross"}
    for shape, yaw in ROAD_ROLE_TO_SHAPE_YAW.values():
        assert shape in ROAD_MATERIALS
        assert yaw in (0.0, 90.0)


def test_build_instances_buckets_urban_block_tiles_by_archetype():
    # Build a real urban_block tile the same way IsoCity does, so this test
    # breaks (loudly) if _building_tile's payload shape ever changes.
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ui.iso_city import _building_tile
    tile = _building_tile(0, 0, "Downtown", "house")
    tiles = {(0, 0): ("urban_block", tile)}
    instances = build_instances(tiles)
    assert "house" in instances
    assert instances["house"].shape == (1, 4)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: `ImportError` or `AssertionError`/`KeyError` (road/building materials not yet bucketed).

- [ ] **Step 4: Implement the bucketing**

In `energy_grid_game/ui/terrain3d.py`, add the new constants near `MATERIALS`:

```python
ROAD_MATERIALS = ("straight", "corner", "tee", "cross")
BUILDING_MATERIALS = ("house", "shop", "block", "midrise", "tower")

ROAD_ROLE_TO_SHAPE_YAW = {
    "straight_ne": ("straight", 0.0), "straight_nw": ("straight", 90.0),
    "corner_ne": ("corner", 0.0), "corner_nw": ("corner", 90.0),
    "tee_ne": ("tee", 0.0), "tee_nw": ("tee", 90.0),
    "cross": ("cross", 0.0),
}
```

Rewrite `build_instances` to also handle `road`/`urban_block` tiles, using the confirmed
`extra.buildings[0]` extraction from Step 1:

```python
def build_instances(tiles):
    """... (keep the existing docstring, extend it to mention road/building
    bucketing was added in Phase 2) ..."""
    buckets = {m: [] for m in MATERIALS + ROAD_MATERIALS + BUILDING_MATERIALS}
    for (col, row), (kind, extra) in tiles.items():
        x = -float(row) * TILE_SPACING
        z = float(col) * TILE_SPACING
        if kind in MATERIALS:
            buckets[kind].append((x, 0.0, z, 0.0))
        elif kind == "road" and extra in ROAD_ROLE_TO_SHAPE_YAW:
            shape, yaw = ROAD_ROLE_TO_SHAPE_YAW[extra]
            buckets[shape].append((x, 0.0, z, yaw))
        elif kind == "urban_block":
            archetype = extra.buildings[0]
            if archetype in BUILDING_MATERIALS:
                buckets[archetype].append((x, 0.0, z, 0.0))
    return {
        m: np.array(offsets, dtype="f4").reshape(-1, 4)
        for m, offsets in buckets.items()
        if offsets
    }
```

- [ ] **Step 5: Run tests to verify they pass, commit**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: all tests pass, including the 3 new ones plus all previously-passing ones.

```bash
git add energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
git commit -m "Bucket road and urban_block tiles into road/building instance materials"
```

---

### Task 4: Load road/building meshes and wire into the existing render path

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- `load_meshes(ctx, prog, mesh_dir=MESH_DIR)` now also loads `ROAD_MATERIALS` from
  `mesh_dir / "roads" / f"{shape}.npz"` and `BUILDING_MATERIALS` from
  `mesh_dir / "buildings" / f"{archetype}.npz"`, merged into the same returned `dict[str, GLMesh]`
  Phase 1 already returns for terrain materials — `upload_instances`/`draw` need NO changes,
  since they already iterate whatever's in the `meshes` dict generically.

- [ ] **Step 1: Write the failing test**

Add to `energy_grid_game/test_terrain3d.py`:

```python
def test_load_meshes_covers_terrain_road_and_building_materials():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        assert set(meshes) == set(MATERIALS) | set(ROAD_MATERIALS) | set(BUILDING_MATERIALS)
    finally:
        ctx.release()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: `AssertionError` (road/building materials missing from `load_meshes`'s output) —
requires Task 1's baked `.npz` files to already exist on disk.

- [ ] **Step 3: Implement**

In `energy_grid_game/ui/terrain3d.py`, change `load_meshes`:

```python
def load_meshes(ctx, prog, mesh_dir=MESH_DIR):
    meshes = {}
    for material in MATERIALS:
        data = np.load(mesh_dir / f"{material}.npz")
        meshes[material] = GLMesh(ctx, prog, data["pos"], data["nrm"],
                                    data["uv"], data["idx"], data["tex"])
    for shape in ROAD_MATERIALS:
        data = np.load(mesh_dir / "roads" / f"{shape}.npz")
        meshes[shape] = GLMesh(ctx, prog, data["pos"], data["nrm"],
                                 data["uv"], data["idx"], data["tex"])
    for archetype in BUILDING_MATERIALS:
        data = np.load(mesh_dir / "buildings" / f"{archetype}.npz")
        meshes[archetype] = GLMesh(ctx, prog, data["pos"], data["nrm"],
                                     data["uv"], data["idx"], data["tex"])
    return meshes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: all tests pass.

- [ ] **Step 5: Confirm `main.py` needs no change**

Read `energy_grid_game/main.py`'s terrain3d integration block (search for `terrain3d.load_meshes`,
`terrain3d.upload_instances`, `terrain3d.draw`). Confirm none of these calls hardcode a material
list or assume exactly 5 materials — they should already be generic over whatever `load_meshes`/
`build_instances` return. If you find a hardcoded assumption, fix it minimally; if not, no
`main.py` change is needed for this task (there is no code to write in that case — just confirm
and note it in your report).

- [ ] **Step 6: Commit**

```bash
git add energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
git commit -m "Load road and building meshes alongside terrain in load_meshes"
```

---

### Task 5: GL smoke test verifying per-instance rotation actually rotates

**Files:**
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- No new production interfaces — this is a verification-only task confirming Task 2's rotation
  math actually works end-to-end through the real GL pipeline, not just unit-tested in isolation.

- [ ] **Step 1: Write the test**

Add to `energy_grid_game/test_terrain3d.py`:

```python
def test_instance_yaw_actually_rotates_the_rendered_mesh():
    """The `straight` road mesh is longer along one axis than the other (a
    road segment, not a symmetric tile) -- render it once at yaw=0 and once
    at yaw=90 into separate framebuffers and confirm the rendered alpha
    footprints differ, proving the shader's per-instance rotation actually
    executes rather than being a no-op."""
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        camera = _FakeCamera(center=(0.0, 0.0), zoom=1.0)

        upload_instances(ctx, meshes, {"straight": np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4")})
        fbo_a = create_framebuffer(ctx, (128, 128))
        draw(ctx, prog, meshes, fbo_a, camera)
        rgba_a, _ = read_rgba(fbo_a)

        upload_instances(ctx, meshes, {"straight": np.array([[0.0, 0.0, 0.0, 90.0]], dtype="f4")})
        fbo_b = create_framebuffer(ctx, (128, 128))
        draw(ctx, prog, meshes, fbo_b, camera)
        rgba_b, _ = read_rgba(fbo_b)

        assert rgba_a != rgba_b
    finally:
        ctx.release()
```

- [ ] **Step 2: Run and verify it passes**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: all tests pass, including this one. If it fails, the rotation matrix in `_VERTEX_SHADER`
(Task 2) has a bug — debug that shader code, don't weaken this test.

- [ ] **Step 3: Commit**

```bash
git add energy_grid_game/test_terrain3d.py
git commit -m "Add GL smoke test verifying per-instance yaw rotation"
```

---

## Self-review notes

- **Spec coverage:** road baking (Task 1), instance format generalization (Task 2), road/building
  bucketing with the exact role→shape/yaw and archetype→mesh tables from the spec (Task 3), mesh
  loading integration (Task 4), rotation correctness verification (Task 5). Dense-downtown
  exclusion is structural (those `kind`s were never in any bucket) rather than a separate task —
  confirmed no task adds them.
- **Payload shape risk resolved during planning:** the `urban_block` extraction (`extra.buildings[0]`)
  was confirmed by reading `ui/iso_city.py:225-231` directly rather than left as an assumption.
