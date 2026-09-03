# Real-Time 3D Terrain Phase 4b Unlit Billboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make plant and tower billboards render at their authored texture brightness in the opt-in 3D terrain layer.

**Architecture:** Keep the existing single shader program and add one per-mesh `unlit` uniform path. Terrain, roads, buildings, and conductor strips remain band-lit; `load_billboards()` creates billboard `GLMesh` instances with `unlit=True`, which also covers transmission tower billboards because they reuse `load_billboards()`.

**Tech Stack:** Python 3.12, pygame 2.6, numpy, moderngl. No new dependencies and no new assets.

## Global Constraints

- `GRIDMANAGER_TERRAIN3D` stays default-off.
- Do not change day/night/season lighting, snow, capture tooling, or camera behavior in this slice.
- Keep terrain, road, building, and conductor strip meshes on the existing banded lighting path.
- Only plant and tower billboards use the unlit path in this slice.
- Use `.codex_portable_build_20260804_001/venv/Scripts/python.exe`; `.venv39` is currently unusable.

---

## File Structure

- Modify `energy_grid_game/ui/terrain3d.py`
  - Add a shader uniform named `unlit`.
  - Add `unlit=False` to `GLMesh.__init__()`.
  - Store `self.unlit` and `self.prog`.
  - Set `prog["unlit"].value` in `GLMesh.render()`.
  - Pass `unlit=True` from `load_billboards()`.
- Modify `energy_grid_game/test_terrain3d.py`
  - Add a GL smoke test proving billboards remain full-bright with `ambient=0.0`.
  - Add a small test proving billboard meshes are marked unlit.

---

### Task 1: Add Per-Mesh Unlit Shader Path For Billboards

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Changes: `GLMesh(ctx, prog, pos, nrm, uv, idx, tex, unlit=False)`
- Changes: `load_billboards(ctx, prog, billboards)` creates `GLMesh(..., unlit=True)`.

- [x] **Step 1: Write failing tests**

Add this test near the existing billboard/load tests in `energy_grid_game/test_terrain3d.py`:

```python
def test_load_billboards_marks_meshes_unlit():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        surf = pygame.Surface((8, 8), pygame.SRCALPHA)
        surf.fill((255, 0, 0, 255))
        meshes = load_billboards(ctx, prog, [{
            "key": "test",
            "offset": (0.0, 0.0, 0.0),
            "width_world": 8 / PX_PER_UNIT,
            "height_world": 8 / (PX_PER_UNIT * _VERTICAL_FORESHORTENING),
            "surface": surf,
        }])
        assert meshes[0].unlit is True
        for mesh in meshes:
            mesh.release()
    finally:
        ctx.release()
```

Add this GL smoke test:

```python
def test_billboard_renders_full_brightness_when_ambient_is_zero():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        surf = pygame.Surface((16, 16), pygame.SRCALPHA)
        surf.fill((255, 0, 0, 255))
        billboards = [{
            "key": "test",
            "offset": (0.0, 0.0, 0.0),
            "width_world": 16 / PX_PER_UNIT,
            "height_world": 16 / (PX_PER_UNIT * _VERTICAL_FORESHORTENING),
            "surface": surf,
        }]
        meshes = load_billboards(ctx, prog, billboards)
        fbo = create_framebuffer(ctx, (64, 64))
        draw(ctx, prog, {}, fbo, _FakeCamera(center=(0.0, 0.0), zoom=1.0),
             billboard_meshes=meshes, ambient=0.0)
        rgba, size = read_rgba(fbo)
        pixels = np.frombuffer(rgba, dtype="u1").reshape(size[1], size[0], 4)
        assert pixels[:, :, 0].max() >= 250
        for mesh in meshes:
            mesh.release()
        fbo.release()
    finally:
        ctx.release()
```

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: first test fails with missing `unlit` attribute or false value; second test fails because the lit shader dims red under zero ambient.

- [x] **Step 2: Implement shader and mesh support**

In `_FRAGMENT_SHADER`, add:

```glsl
uniform bool unlit;
```

Change the final brightness block to:

```glsl
    float bright = 1.0;
    if (!unlit) {
        vec3 n = normalize(v_normal);
        float lambert = max(dot(n, light_dir), 0.0);
        float banded = floor(lambert * 3.0) / 3.0;
        bright = ambient + (1.0 - ambient) * banded;
    }
    f_color = vec4(texel.rgb * bright, texel.a);
```

Change `GLMesh.__init__` to accept and store the flag and program:

```python
class GLMesh:
    def __init__(self, ctx, prog, pos, nrm, uv, idx, tex, unlit=False):
        self.prog = prog
        self.unlit = bool(unlit)
```

Keep the existing buffer setup after those assignments.

In `GLMesh.render()`, set the uniform before binding the texture:

```python
            self.prog["unlit"].value = self.unlit
```

In `load_billboards()`, create the mesh with:

```python
        mesh = GLMesh(ctx, prog, pos, nrm, uv, idx, tex_data, unlit=True)
```

- [x] **Step 3: Verify green**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: all terrain3d checks pass.

- [x] **Step 4: Final verification for this slice**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
git diff --check -- energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
```

Expected: city-model remains green; diff check has no whitespace errors.

## Self-Review

- **Spec coverage:** This plan covers the Phase 4 billboard unlit/full-bright requirement for plant and tower billboards. Broader day/night, seasonal tinting, snow, and capture tooling remain separate Phase 4 slices.
- **Placeholder scan:** No placeholder markers remain.
- **Type consistency:** `unlit`, `GLMesh(..., unlit=False)`, and `load_billboards(..., unlit=True)` are named consistently.
