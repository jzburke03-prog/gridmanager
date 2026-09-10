# Real-Time 3D Terrain — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the countryside terrain (grass/farm/tree/water/mountain tiles) as real 3D instanced voxel meshes from `newassets/terrain/gltf`, composited under the existing 2D sprite city, with a fixed isometric camera and flat/banded (non-PBR) lighting.

**Architecture:** A headless `moderngl` context (no GL window — see mechanism note below) renders the 3D terrain each frame into an offscreen framebuffer sized to the city viewport; the framebuffer is read back to CPU and blitted as an ordinary pygame `Surface` into the existing software-rendered window, exactly like any other sprite. `_layout()`'s tile dict is read but never modified, so all existing layout/simulation logic and tests are untouched. A one-time bake script converts curated glTF meshes into compact `.npz` files the runtime loads; the running game never parses raw glTF/JSON.

**Tech Stack:** Python, pygame 2.6, numpy, moderngl (new runtime dependency), Pillow (new runtime dependency, already used offline by `tools/bake_gltf_terrain.py`).

## Mechanism note (refines the spec's Architecture section)

The spec described opening the pygame window with `pygame.OPENGL | pygame.DOUBLEBUF`. That flag makes SDL hand pygame a true GL-backed display surface, and **`Surface.blit()` no longer works on it** — the entire window would have to be drawn via GL calls, which would break every existing 2D system (HUD, menus, dialogue, charts) that this phase is explicitly supposed to leave untouched.

This plan uses `moderngl.create_standalone_context()` instead — a headless GL context with no window attached, exactly what `tools/bake_gltf_terrain.py` already uses successfully for offline baking. The main pygame window stays exactly as it is today (`pygame.display.set_mode(...)`, no new flags). Each frame, the 3D pass renders into an offscreen framebuffer, `fbo.read()` pulls the pixels back to CPU, and the result is blitted onto the normal software display surface like any other sprite. Same end result (3D terrain composited under 2D UI, single window), safer mechanism.

## Global Constraints

- `TW = 16, TH = 8` (tile screen dimensions) must stay consistent with `ui.iso_city.TW`/`TH` — `ui/voxel_terrain.py` already duplicates these with a comment enforcing this; any new module referencing tile scale must match.
- `_layout()`'s tile dict contract (`tiles[(col, row)] = (kind, extra)`) must not change. This phase only reads it.
- New dependencies (`moderngl`, `Pillow`) must be pinned to an exact version in `requirements.txt`, matching the repo's existing exact-pin style (`pygame==2.6.1`, `numpy==2.0.2`).
- GL failures (unsupported version, missing baked assets) must fail fast at startup with a human-readable message. No fallback 2D-terrain renderer.
- Tests in this repo are plain scripts, not pytest: functions named `test_*` in a module, collected via `globals()` reflection and run from an `if __name__ == "__main__":` block at the bottom, executed as `python path/to/test_file.py`. Pygame-touching tests set `os.environ.setdefault("SDL_VIDEODRIVER", "dummy")` before `import pygame`. Follow this exact convention — do not introduce pytest.

---

### Task 1: Pin moderngl and Pillow as runtime dependencies

**Files:**
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `moderngl` and `Pillow` importable in the runtime environment for all later tasks.

- [ ] **Step 1: Install the packages and capture their exact versions**

```bash
pip install moderngl Pillow
pip freeze | grep -iE "^(moderngl|pillow)=="
```

Expected: two lines like `moderngl==5.11.1` and `pillow==11.0.0` (exact numbers depend on what's current — use whatever `pip freeze` actually reports).

- [ ] **Step 2: Add the exact-pinned versions to `requirements.txt`**

Open `requirements.txt` (currently: `pygame==2.6.1`, `numpy==2.0.2`, `certifi`) and add the two lines reported by `pip freeze` in Step 1, e.g.:

```
pygame==2.6.1
numpy==2.0.2
certifi
moderngl==5.11.1
Pillow==11.0.0
```

(Substitute the real versions from Step 1's output.)

- [ ] **Step 3: Verify a clean install works**

```bash
pip install -r requirements.txt
python -c "import moderngl, PIL; print('ok')"
```

Expected: `ok` with no errors.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "Add moderngl and Pillow as runtime dependencies for 3D terrain"
```

---

### Task 2: Headless GL context with fail-fast version check

**Files:**
- Create: `energy_grid_game/ui/gl_context.py`
- Test: `energy_grid_game/test_gl_context.py`

**Interfaces:**
- Produces: `gl_context.create_context(min_version_code=330) -> moderngl.Context`, `gl_context.UnsupportedGLError`, `gl_context.format_unsupported_message(version_code, min_version_code) -> str` (pure, used by later tasks/tests).

- [ ] **Step 1: Write the failing test**

Create `energy_grid_game/test_gl_context.py`:

```python
"""GL context creation and version fail-fast checks. Run: python test_gl_context.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.gl_context import UnsupportedGLError, create_context, format_unsupported_message


def test_format_unsupported_message_reports_both_versions():
    msg = format_unsupported_message(210, 330)
    assert "3.3" in msg
    assert "2.1" in msg
    assert "Grid Manager" in msg


def test_create_context_returns_a_working_context_on_this_machine():
    # This repo's dev/CI machines are expected to have a GL 3.3+ capable
    # driver (moderngl.create_standalone_context uses Mesa/EGL/ANGLE
    # software fallback where no real GPU is present), matching what
    # tools/bake_gltf_terrain.py already relies on for its offline bake.
    ctx = create_context()
    assert ctx.version_code >= 330
    ctx.release()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall gl_context checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python energy_grid_game/test_gl_context.py`
Expected: `ModuleNotFoundError: No module named 'ui.gl_context'`

- [ ] **Step 3: Write the implementation**

Create `energy_grid_game/ui/gl_context.py`:

```python
"""Headless moderngl context creation for the 3D terrain renderer.

No pygame GL window is used -- see the "Mechanism note" in
docs/superpowers/plans/2026-08-05-realtime-3d-terrain-phase1.md. This is a
standalone (windowless) context, the same kind tools/bake_gltf_terrain.py
already uses successfully for offline baking; the terrain renderer reads its
framebuffer back to CPU each frame and blits it as an ordinary pygame
Surface into the existing software-rendered window.
"""
import moderngl

MIN_VERSION_CODE = 330  # OpenGL 3.3 core, minimum moderngl instancing needs


class UnsupportedGLError(RuntimeError):
    """Raised when the driver's GL context is below MIN_VERSION_CODE."""


def _version_str(version_code):
    major, minor = version_code // 100, (version_code % 100) // 10
    return f"{major}.{minor}"


def format_unsupported_message(version_code, min_version_code):
    return (f"Grid Manager requires OpenGL {_version_str(min_version_code)}+; "
            f"your driver reports {_version_str(version_code)}")


def create_context(min_version_code=MIN_VERSION_CODE):
    """Create a headless GL context, or raise UnsupportedGLError with a
    readable message if the driver's GL version is too old. No fallback
    renderer -- callers should let this propagate to a clean startup exit."""
    ctx = moderngl.create_standalone_context()
    if ctx.version_code < min_version_code:
        version_code = ctx.version_code
        ctx.release()
        raise UnsupportedGLError(format_unsupported_message(version_code, min_version_code))
    return ctx
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python energy_grid_game/test_gl_context.py`
Expected: `ok  test_create_context_returns_a_working_context_on_this_machine`, `ok  test_format_unsupported_message_reports_both_versions`, `all gl_context checks passed`

- [ ] **Step 5: Commit**

```bash
git add energy_grid_game/ui/gl_context.py energy_grid_game/test_gl_context.py
git commit -m "Add headless GL context creation with fail-fast version check"
```

---

### Task 3: Public `tiles` / `layout_key` accessors on `IsoCity`

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py:1740` (near `self._key = None`) and `energy_grid_game/ui/iso_city.py:1970` (near `self._tiles = tiles`)
- Test: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Produces: `IsoCity.tiles -> dict[(int, int), (str, object)]` (read-only view of `self._tiles`), `IsoCity.layout_key -> object` (read-only view of `self._key`, changes exactly when `_layout()` re-runs).

- [ ] **Step 1: Write the failing test**

Add to `energy_grid_game/test_city_model.py` (near the other `_city(...)`-based tests):

```python
def test_tiles_and_layout_key_are_publicly_readable():
    city = _city(50_000)
    rect = pygame.Rect(0, 0, 800, 600)
    state = SimpleNamespace(population=50_000, date=SimpleNamespace(month=6),
                             fleet=[])
    city.prepare(rect, state)
    assert city.tiles is city._tiles
    assert city.layout_key == city._key
    assert city.layout_key is not None
```

(If `_city(...)` in this file already builds a state object and calls `prepare`, reuse that helper instead of constructing `rect`/`state` by hand — check the existing helper's signature before writing this step's final form.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python energy_grid_game/test_city_model.py`
Expected: `AttributeError: 'IsoCity' object has no attribute 'tiles'`

- [ ] **Step 3: Add the properties**

In `energy_grid_game/ui/iso_city.py`, immediately after the `class IsoCity:` `__init__` method's existing attribute assignments (near `self._key = None` at line 1740 and `self._tiles` initialization), add two properties. Find a suitable spot after `__init__` (e.g. right before the `prepare` method at line 2702) and add:

```python
    @property
    def tiles(self):
        """Read-only view of the current tile layout: {(col, row): (kind, extra)}."""
        return self._tiles

    @property
    def layout_key(self):
        """Opaque key that changes exactly when _layout() has re-run (rect
        size, population bucket, fleet). Consumers that cache derived state
        from `tiles` (e.g. terrain3d's instance buffers) should key their
        cache on this."""
        return self._key
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python energy_grid_game/test_city_model.py`
Expected: all tests pass including the new one, ending with `all city model checks passed`.

- [ ] **Step 5: Commit**

```bash
git add energy_grid_game/ui/iso_city.py energy_grid_game/test_city_model.py
git commit -m "Expose IsoCity.tiles and layout_key as public read accessors"
```

---

### Task 4: Bake curated terrain meshes to `.npz`

**Files:**
- Create: `tools/bake_terrain_meshes.py`
- Test: `tools/test_bake_terrain_meshes.py`

**Interfaces:**
- Consumes: `load_gltf(path) -> (pos, nrm, uv, idx, tex)` from `tools/bake_gltf_terrain.py` (unchanged, already exists). Note: importing `bake_gltf_terrain` requires `moderngl` to be importable even though `load_gltf` itself doesn't use it (module-level `import moderngl` at the top of that file) — this is fine, Task 1 already made moderngl a real dependency.
- Produces: five files `energy_grid_game/assets/terrain3d/{grass,farm,tree,water,mountain}.npz`, each an `np.savez` archive with keys `pos` (N,3 float32), `nrm` (N,3 float32), `uv` (N,2 float32), `idx` (M,3 int32), `tex` (H,W,4 uint8).

- [ ] **Step 1: Write the failing test**

Create `tools/test_bake_terrain_meshes.py`:

```python
"""Terrain mesh bake checks. Run: python test_bake_terrain_meshes.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from bake_terrain_meshes import MATERIAL_SOURCES, bake_material


def test_material_sources_cover_the_five_phase1_materials():
    assert set(MATERIAL_SOURCES) == {"grass", "farm", "tree", "water", "mountain"}
    for rel_path in MATERIAL_SOURCES.values():
        assert rel_path.endswith(".gltf")


def test_bake_material_writes_a_loadable_npz(tmp_path=None):
    import tempfile
    from pathlib import Path
    out_dir = Path(tempfile.mkdtemp())
    out_path = bake_material("grass", out_dir)
    assert out_path.exists()
    data = np.load(out_path)
    assert data["pos"].ndim == 2 and data["pos"].shape[1] == 3
    assert data["nrm"].shape == data["pos"].shape
    assert data["uv"].shape[1] == 2
    assert data["idx"].shape[1] == 3
    assert data["tex"].ndim == 3 and data["tex"].shape[2] == 4


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall bake_terrain_meshes checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python tools/test_bake_terrain_meshes.py`
Expected: `ModuleNotFoundError: No module named 'bake_terrain_meshes'`

- [ ] **Step 3: Write the implementation**

Create `tools/bake_terrain_meshes.py`:

```python
#!/usr/bin/env python3
"""Bake curated glTF terrain meshes from newassets/terrain/gltf/ into compact
.npz files the runtime 3D renderer (ui/terrain3d.py) loads directly, so the
running game never parses raw glTF/JSON -- same bake-time-only principle as
tools/bake_gltf_terrain.py's PNG sprite bake, just a different output format
(raw geometry + texture arrays instead of a pre-rendered image).

One base mesh per Phase 1 material -- no edge/corner connector variants and
no decoration compositing yet (e.g. "tree" tiles render as a standalone tree
mesh with no separate ground plane underneath). See the Phase 1 design doc's
Non-goals section.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bake_gltf_terrain import load_gltf  # noqa: E402  (path setup above)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "newassets" / "terrain" / "gltf"
OUT = ROOT / "energy_grid_game" / "assets" / "terrain3d"

MATERIAL_SOURCES = {
    "grass": "Forest/forest-1.gltf",
    "farm": "Dirt/dirt-1.gltf",
    "tree": "Trees/tree-1.gltf",
    "water": "Water/water-1.gltf",
    "mountain": "Mountains/mountain-1.gltf",
}


def bake_material(material, out_dir=OUT):
    rel_path = MATERIAL_SOURCES[material]
    pos, nrm, uv, idx, tex = load_gltf(SRC / rel_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{material}.npz"
    np.savez(out_path,
              pos=pos.astype("f4"), nrm=nrm.astype("f4"),
              uv=uv.astype("f4"), idx=idx.astype("i4"),
              tex=tex.astype("u1"))
    return out_path


def main():
    for material in MATERIAL_SOURCES:
        out_path = bake_material(material)
        print(f"baked {material} -> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python tools/test_bake_terrain_meshes.py`
Expected: both tests pass, ending with `all bake_terrain_meshes checks passed`.

- [ ] **Step 5: Run the bake and commit its output**

```bash
python tools/bake_terrain_meshes.py
```

Expected: five `baked <material> -> energy_grid_game/assets/terrain3d/<material>.npz` lines.

```bash
git add tools/bake_terrain_meshes.py tools/test_bake_terrain_meshes.py energy_grid_game/assets/terrain3d/
git commit -m "Bake curated terrain meshes to .npz for the 3D renderer"
```

---

### Task 5: `terrain3d.build_instances()` — pure tile-to-instance mapping

**Files:**
- Create: `energy_grid_game/ui/terrain3d.py`
- Test: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Consumes: a tile dict shaped like `IsoCity.tiles` (Task 3): `{(col, row): (kind, extra)}`.
- Produces: `MATERIALS = ("grass", "farm", "tree", "water", "mountain")`, `build_instances(tiles: dict) -> dict[str, np.ndarray]` — pure, no GL calls, maps each tile whose `kind` is one of `MATERIALS` to a `(col, 0, row)` float32 world offset, bucketed by material. Tiles with any other `kind` (`"road"`, `"urban_block"`, `"park"`, `"campus"`, `"vroad"`, `"voxel_bldg"`, `"pad"`, `"bldg"` — all still 2D-sprite-rendered in Phase 1) are skipped.

- [ ] **Step 1: Write the failing test**

Create `energy_grid_game/test_terrain3d.py`:

```python
"""3D terrain renderer checks. Run: python test_terrain3d.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from ui.terrain3d import MATERIALS, build_instances


def test_build_instances_buckets_by_material_and_skips_non_terrain_kinds():
    tiles = {
        (0, 0): ("grass", None),
        (1, 0): ("farm", None),
        (2, 0): ("tree", None),
        (3, 0): ("water", None),
        (4, 0): ("mountain", 7),
        (5, 0): ("road", "straight_ne"),      # 2D-sprite-rendered, skip
        (6, 0): ("urban_block", "shop"),      # 2D-sprite-rendered, skip
    }
    instances = build_instances(tiles)
    assert set(instances) == {"grass", "farm", "tree", "water", "mountain"}
    for material in MATERIALS:
        assert instances[material].shape == (1, 3)
        assert instances[material].dtype == np.float32


def test_build_instances_offset_matches_col_row():
    tiles = {(3, 5): ("grass", None)}
    instances = build_instances(tiles)
    assert np.array_equal(instances["grass"][0], np.array([3.0, 0.0, 5.0], dtype="f4"))


def test_build_instances_groups_multiple_tiles_of_the_same_material():
    tiles = {(0, 0): ("grass", None), (1, 1): ("grass", None), (2, 2): ("grass", None)}
    instances = build_instances(tiles)
    assert instances["grass"].shape == (3, 3)


def test_build_instances_omits_materials_with_no_tiles():
    instances = build_instances({(0, 0): ("water", None)})
    assert set(instances) == {"water"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall terrain3d checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: `ModuleNotFoundError: No module named 'ui.terrain3d'`

- [ ] **Step 3: Write the implementation**

Create `energy_grid_game/ui/terrain3d.py`:

```python
"""Real-time 3D terrain rendering: instanced voxel meshes for countryside
tiles (grass/farm/tree/water/mountain), composited under the existing 2D
sprite city. See docs/superpowers/specs/2026-08-05-realtime-3d-terrain-
phase1-design.md.

This module is imported by main.py only; it does not import ui.iso_city, to
avoid a circular import (same discipline as ui.voxel_terrain).
"""
from pathlib import Path

import numpy as np

TW, TH = 16, 8  # MUST match ui.iso_city.TW/TH

MATERIALS = ("grass", "farm", "tree", "water", "mountain")

MESH_DIR = Path(__file__).resolve().parents[1] / "assets" / "terrain3d"


def build_instances(tiles):
    """Pure tile-dict -> per-material instance offsets. No GL calls.

    `tiles` is shaped like IsoCity.tiles: {(col, row): (kind, extra)}. Tiles
    whose kind isn't one of MATERIALS (roads, buildings, parks, etc. -- still
    2D-sprite-rendered in Phase 1) are skipped. Each terrain tile becomes one
    (col, 0, row) world-space offset; y=0 for all materials in Phase 1
    (mountain height/elevation is a Phase 4 polish item, not consumed here
    yet even though the tile payload carries it)."""
    buckets = {material: [] for material in MATERIALS}
    for (col, row), (kind, _extra) in tiles.items():
        if kind in buckets:
            buckets[kind].append((float(col), 0.0, float(row)))
    return {
        material: np.array(offsets, dtype="f4").reshape(-1, 3)
        for material, offsets in buckets.items()
        if offsets
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: all four tests pass, ending with `all terrain3d checks passed`.

- [ ] **Step 5: Commit**

```bash
git add energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
git commit -m "Add pure tile-to-instance mapping for 3D terrain"
```

---

### Task 6: GL mesh loading + instanced draw

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py` (extends Task 5's file)
- Modify: `energy_grid_game/test_terrain3d.py` (extends Task 5's test file)

**Interfaces:**
- Consumes: `MATERIALS`, `MESH_DIR` (Task 5, this file); `moderngl.Context` from `gl_context.create_context()` (Task 2); `.npz` files from `tools/bake_terrain_meshes.py` (Task 4).
- Produces: `create_program(ctx) -> moderngl.Program`, `load_meshes(ctx, prog, mesh_dir=MESH_DIR) -> dict[str, GLMesh]`, `upload_instances(ctx, meshes, instances: dict[str, np.ndarray]) -> None`, `create_framebuffer(ctx, size: (int, int)) -> moderngl.Framebuffer`, `draw(ctx, prog, meshes, fbo, camera, px_per_unit=26.0) -> None`, `read_rgba(fbo) -> (bytes, (int, int))`, `to_surface(rgba_bytes, size) -> pygame.Surface`. `camera` is any object with `.center` (2-tuple of float, screen-space pixels, same convention as `ui.iso_city.Camera`) and `.zoom` (float) attributes.

- [ ] **Step 1: Write the failing tests**

Append to `energy_grid_game/test_terrain3d.py` (add these `import`s to the top, alongside the existing ones):

```python
import os as _os
_os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

from ui.gl_context import create_context
from ui.terrain3d import (create_framebuffer, create_program, draw,
                           load_meshes, read_rgba, to_surface,
                           upload_instances)
```

And these test functions (before the `if __name__ == "__main__":` block):

```python
class _FakeCamera:
    def __init__(self, center=(0.0, 0.0), zoom=1.0):
        self.center = list(center)
        self.zoom = zoom


def test_load_meshes_covers_all_materials():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        assert set(meshes) == set(MATERIALS)
    finally:
        ctx.release()


def test_draw_produces_a_readable_framebuffer_with_visible_content():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        upload_instances(ctx, meshes, {"grass": np.array([[0.0, 0.0, 0.0]], dtype="f4")})
        fbo = create_framebuffer(ctx, (64, 64))
        draw(ctx, prog, meshes, fbo, _FakeCamera(center=(0.0, 0.0), zoom=1.0))
        rgba, size = read_rgba(fbo)
        assert size == (64, 64)
        pixels = np.frombuffer(rgba, dtype="u1").reshape(64, 64, 4)
        # A single grass instance at the origin, camera centered on it, must
        # paint at least some non-background pixels near the middle.
        assert pixels[:, :, 3].max() > 0
    finally:
        ctx.release()


def test_to_surface_returns_a_surface_of_the_requested_size():
    rgba = bytes([255, 0, 0, 255] * (8 * 8))
    surf = to_surface(rgba, (8, 8))
    assert isinstance(surf, pygame.Surface)
    assert surf.get_size() == (8, 8)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: `ImportError: cannot import name 'create_program' from 'ui.terrain3d'`

- [ ] **Step 3: Add the GL-dependent code**

Append to `energy_grid_game/ui/terrain3d.py` (after `build_instances`):

```python
import moderngl
import pygame

LIGHT = np.array([-0.35, 0.8, 0.5])
LIGHT = LIGHT / np.linalg.norm(LIGHT)

# Same fixed true-isometric camera as tools/bake_gltf_terrain.py: rotate 45
# deg around Y, then ~35.264 deg around X, dropped to an orthographic 2:1
# screen -- this is what makes a (col, 0, row) world offset project with the
# same diamond ratio as ui.iso_city.iso_xy(col, row).
_AY = np.deg2rad(45.0)
_AX = np.deg2rad(35.264)
_RY = np.array([[np.cos(_AY), 0, np.sin(_AY)],
                [0, 1, 0],
                [-np.sin(_AY), 0, np.cos(_AY)]])
_RX = np.array([[1, 0, 0],
                [0, np.cos(_AX), -np.sin(_AX)],
                [0, np.sin(_AX), np.cos(_AX)]])
CAM_ROT = _RX @ _RY

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
out vec2 v_uv;
out vec3 v_normal;
void main() {
    vec3 world = in_pos + in_offset;
    vec3 cam = cam_rot * world;
    float sx = cam.x * px_per_unit * zoom;
    float sy = -cam.y * px_per_unit * zoom;
    float depth = -cam.y + 0.35 * cam.z;
    vec2 screen_px = vec2(sx, sy) - origin;
    float ndc_x = screen_px.x / img_size.x * 2.0 - 1.0;
    float ndc_y = 1.0 - screen_px.y / img_size.y * 2.0;
    gl_Position = vec4(ndc_x, ndc_y, -depth * 0.01, 1.0);
    v_uv = in_uv;
    v_normal = in_normal;
}
"""

# Lighting is quantized into 3 discrete bands (not a smooth Lambert term) --
# this is what gives the flat/voxel look the design calls for, deliberately
# different from tools/bake_gltf_terrain.py's smooth-shaded sprite bake.
_FRAGMENT_SHADER = """
#version 330
uniform sampler2D tex;
uniform vec3 light_dir;
uniform float ambient;
in vec2 v_uv;
in vec3 v_normal;
out vec4 f_color;
void main() {
    vec4 texel = texture(tex, v_uv);
    if (texel.a < 0.01) discard;
    vec3 n = normalize(v_normal);
    float lambert = max(dot(n, light_dir), 0.0);
    float banded = floor(lambert * 3.0) / 3.0;
    float bright = ambient + (1.0 - ambient) * banded;
    f_color = vec4(texel.rgb * bright, texel.a);
}
"""


def create_program(ctx):
    return ctx.program(vertex_shader=_VERTEX_SHADER, fragment_shader=_FRAGMENT_SHADER)


class GLMesh:
    def __init__(self, ctx, prog, pos, nrm, uv, idx, tex):
        verts = np.hstack([pos, nrm, uv]).astype("f4")
        self.vbo = ctx.buffer(verts.tobytes())
        self.ibo = ctx.buffer(idx.astype("i4").tobytes())
        self.instance_vbo = ctx.buffer(reserve=12)  # 1 instance placeholder; resized on upload
        self.vao = ctx.vertex_array(
            prog,
            [(self.vbo, "3f 3f 2f", "in_pos", "in_normal", "in_uv"),
             (self.instance_vbo, "3f/i", "in_offset")],
            self.ibo,
        )
        tex_h, tex_w = tex.shape[0], tex.shape[1]
        self.texture = ctx.texture((tex_w, tex_h), 4, tex.astype("u1").tobytes())
        self.texture.filter = moderngl.NEAREST, moderngl.NEAREST
        self.instance_count = 0

    def set_instances(self, offsets):
        data = offsets.astype("f4").tobytes()
        self.instance_vbo.orphan(max(len(data), 12))
        if len(data):
            self.instance_vbo.write(data)
        self.instance_count = len(offsets)

    def render(self):
        if self.instance_count:
            self.texture.use(0)
            self.vao.render(instances=self.instance_count)


def load_meshes(ctx, prog, mesh_dir=MESH_DIR):
    meshes = {}
    for material in MATERIALS:
        data = np.load(mesh_dir / f"{material}.npz")
        meshes[material] = GLMesh(ctx, prog, data["pos"], data["nrm"],
                                    data["uv"], data["idx"], data["tex"])
    return meshes


def upload_instances(ctx, meshes, instances):
    empty = np.zeros((0, 3), dtype="f4")
    for material, mesh in meshes.items():
        mesh.set_instances(instances.get(material, empty))


def create_framebuffer(ctx, size):
    return ctx.framebuffer(
        color_attachments=[ctx.texture(size, 4)],
        depth_attachment=ctx.depth_renderbuffer(size),
    )


def draw(ctx, prog, meshes, fbo, camera, px_per_unit=26.0, ambient=0.55):
    fbo.use()
    ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
    ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
    ctx.clear(0.10, 0.11, 0.13, 1.0)
    prog["cam_rot"].write(CAM_ROT.T.astype("f4").tobytes())
    prog["px_per_unit"].value = float(px_per_unit)
    prog["zoom"].value = float(camera.zoom)
    prog["img_size"].value = (float(fbo.size[0]), float(fbo.size[1]))
    prog["origin"].value = (float(camera.center[0]), float(camera.center[1]))
    prog["tex"].value = 0
    prog["light_dir"].value = tuple(LIGHT.astype("f4"))
    prog["ambient"].value = float(ambient)
    for mesh in meshes.values():
        mesh.render()


def read_rgba(fbo):
    return fbo.read(components=4), fbo.size


def to_surface(rgba_bytes, size):
    """Pure pygame conversion, no GL involved -- FBO reads are bottom-up, so
    flip vertically to match screen orientation (same fix-up
    tools/bake_gltf_terrain.py applies via PIL's FLIP_TOP_BOTTOM)."""
    surf = pygame.image.frombuffer(rgba_bytes, size, "RGBA")
    return pygame.transform.flip(surf, False, True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: all seven tests pass, ending with `all terrain3d checks passed`. (Requires `python tools/bake_terrain_meshes.py` from Task 4 to have already been run so the `.npz` files exist.)

- [ ] **Step 5: Commit**

```bash
git add energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
git commit -m "Add instanced GL rendering for 3D terrain"
```

---

### Task 7: Wire the 3D terrain layer into the main render loop

**Files:**
- Modify: `energy_grid_game/main.py`

**Interfaces:**
- Consumes: `gl_context.create_context`, `gl_context.UnsupportedGLError` (Task 2); `IsoCity.tiles`, `IsoCity.layout_key`, `IsoCity.camera` (Task 3, and the pre-existing public `camera` attribute); `terrain3d.create_program`, `terrain3d.load_meshes`, `terrain3d.build_instances`, `terrain3d.upload_instances`, `terrain3d.create_framebuffer`, `terrain3d.draw`, `terrain3d.read_rgba`, `terrain3d.to_surface` (Tasks 5–6).

This task modifies the live game loop, which the existing test suite doesn't exercise end-to-end (no test drives `main()`). Verification here is a manual run, not a new automated test — the automated coverage lives in Tasks 2–6.

- [ ] **Step 1: Read the current startup and loop structure**

Open `energy_grid_game/main.py` and locate:
- The `IsoCity(...)` construction (around line 95).
- `city.prepare(city_rect, state)` (around line 323).
- `city.draw(frame, city_rect, state, environment)` (around line 396).

- [ ] **Step 2: Add startup GL context creation with fail-fast**

Near the top of `main.py`, add the import:

```python
from ui import gl_context, terrain3d
```

Immediately after the `IsoCity(font_small, font)` construction (around line 95), add:

```python
    try:
        gl_ctx = gl_context.create_context()
    except gl_context.UnsupportedGLError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    terrain3d_prog = terrain3d.create_program(gl_ctx)
    terrain3d_meshes = terrain3d.load_meshes(gl_ctx, terrain3d_prog)
    terrain3d_key = None
    terrain3d_fbo = None
```

(If `main.py` doesn't already `import sys`, add that too.)

- [ ] **Step 3: Render and composite the 3D terrain layer each frame**

Immediately after `city.prepare(city_rect, state)` (around line 323) and before `city.draw(frame, city_rect, state, environment)` (around line 396), add:

```python
        if city.layout_key != terrain3d_key:
            terrain3d.upload_instances(gl_ctx, terrain3d_meshes,
                                        terrain3d.build_instances(city.tiles))
            terrain3d_key = city.layout_key
        if terrain3d_fbo is None or terrain3d_fbo.size != city_rect.size:
            terrain3d_fbo = terrain3d.create_framebuffer(gl_ctx, city_rect.size)
        terrain3d.draw(gl_ctx, terrain3d_prog, terrain3d_meshes, terrain3d_fbo, city.camera)
        rgba, size = terrain3d.read_rgba(terrain3d_fbo)
        frame.blit(terrain3d.to_surface(rgba, size), city_rect.topleft)
```

Place this directly before the existing `city.draw(frame, city_rect, state, environment)` call so the 3D terrain paints first and the existing 2D sprite city/HUD draw on top of it, per the design's "3D terrain under today's flat sprite city" decision. `city.camera` is `None` until `IsoCity.prepare()` has run at least once (see `ui/iso_city.py:1755`) — since this block runs immediately after `city.prepare(...)`, `city.camera` is guaranteed set by this point.

- [ ] **Step 4: Manual verification run**

```bash
python energy_grid_game/main.py
```

Expected: the game launches without a traceback, the city view shows visible 3D terrain (grass/farm/tree/water/mountain patches with visible per-tile depth/shading) under the existing 2D roads/buildings/plants/HUD. Some visual mismatch between the 3D terrain and the 2D city (alignment, scale, color) is expected and acceptable for Phase 1 — note anything that looks badly broken (e.g. terrain not appearing at all, a crash, or terrain rendering far outside the city viewport) for a quick follow-up fix before moving to Phase 2.

If terrain doesn't visually align well with the existing city's screen-space scale, the two tunable knobs are `px_per_unit` (passed to `terrain3d.draw`, default `26.0`) and the world-space tile spacing implicit in `build_instances`' `(col, 0, row)` offsets (currently 1 world unit per tile) — adjust `px_per_unit` first since it doesn't require re-baking meshes.

- [ ] **Step 5: Commit**

```bash
git add energy_grid_game/main.py
git commit -m "Composite 3D terrain layer under the existing 2D sprite city"
```

---

## Self-review notes

- **Spec coverage:** GL scaffolding (Task 2), fixed iso camera + flat/banded lighting (Task 6), terrain materials grass/farm/tree/water/mountain from the five named glTF folders (Task 4), pure `build_instances` unit-testable without GL (Task 5), 3D-under-2D compositing (Task 7), fail-fast GL version check (Task 2) — all covered. Headless smoke-test approach for GL-dependent code (Task 6) matches the spec's testing section.
- **Mechanism correction:** the spec's `pygame.OPENGL` window flag is replaced with a headless standalone context (see "Mechanism note" above) — this is a refinement of *how* the hybrid renders, not a change to *what* it renders or where; flagged explicitly rather than silently diverging from the approved spec.
- **Deferred to later phases (confirmed non-goals, not gaps):** mountain elevation height (payload currently ignored in `build_instances`), edge/corner mesh variants, day/night and seasonal lighting on 3D terrain, pixel-diff visual regression, roads/buildings/plants/transmission as 3D.
