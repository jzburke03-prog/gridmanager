# Real-Time 3D Terrain — Phase 3a Implementation Plan (Power Plant Billboards)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render each plant's existing static pygame sprite as a camera-facing, depth-tested billboard inside the moderngl pass, proving correct occlusion against 3D terrain/roads/buildings, without yet changing what's visibly drawn by default.

**Architecture:** A billboard is a procedurally-generated quad (no baked mesh) whose plane is computed once from the fixed camera's rotation matrix, with a runtime-created GL texture from the plant's existing pygame `Surface`. Each plant gets its own small draw call (plant counts are always ≤8, no instancing needed). Billboards share the existing shader/program and draw in the same pass as terrain/road/building instances, so they share the depth buffer.

**Tech Stack:** Same as Phase 1/2 — no new dependencies.

## Global Constraints

- `TILE_SPACING = 3.2` and `PX_PER_UNIT` (from the Phase 1 camera fix) are the source of truth for world-unit conversion — reuse them, don't redefine.
- World position for a plant uses `(-row*TILE_SPACING, 0, col*TILE_SPACING)` — the exact same formula terrain/road/building instances use, sourced from `PlantSite.col`/`.row`, NOT the clamped 2D `sx`/`sy`.
- The 2D static plant sprite draw in `IsoCity._draw_plants`/`_plant_static_sprite` call sites is NOT hidden/modified by this phase — billboards render into the 3D pass but the 2D city still draws its plant sprite on top afterward, same as it does today. This phase proves the mechanism; it does not flip visibility.
- The live/animated plant overlay (`_draw_plant_live`) is untouched.
- `GRIDMANAGER_TERRAIN3D` stays default-off; this phase doesn't touch the flag.
- Tests are plain scripts (`test_*` via `globals()` reflection).
- Venv: `.codex_portable_build_20260804_001\venv\Scripts\python.exe`.
- Git hygiene is not a concern in this repo.

---

### Task 1: Public `IsoCity.plants` accessor

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Produces: `IsoCity.plants -> list[PlantSite]` (read-only view of `self._plants`).

- [ ] **Step 1: Write the failing test**

Add to `energy_grid_game/test_city_model.py`, following the same pattern as the existing
`test_tiles_and_layout_key_are_publicly_readable` test (find it and reuse its `IsoCity`/`prepare()`
construction pattern):

```python
def test_plants_is_publicly_readable():
    city = IsoCity(None, None)
    rect = pygame.Rect(0, 0, 1400, 700)
    state = SimpleNamespace(population=200_000, sources=("gas", "solar"))
    city.prepare(rect, state)
    assert city.plants is city._plants
    assert len(city.plants) >= 1
```

(Adjust `state`'s shape to match whatever the real `prepare()`/`_bake()` signature actually needs —
read the existing `test_tiles_and_layout_key_are_publicly_readable` test for the confirmed-working
pattern rather than guessing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python energy_grid_game/test_city_model.py`
Expected: `AttributeError: 'IsoCity' object has no attribute 'plants'`

- [ ] **Step 3: Add the property**

In `energy_grid_game/ui/iso_city.py`, near the existing `tiles`/`layout_key` properties (added in
Phase 1's Task 3 — find them and add this alongside), add:

```python
    @property
    def plants(self):
        """Read-only view of the current plant placements: list[PlantSite]."""
        return self._plants
```

- [ ] **Step 4: Run test to verify it passes, commit**

Run: `python energy_grid_game/test_city_model.py`
Expected: passes (plus the one known pre-existing unrelated failure,
`test_layout_reserves_city_center_sprites_near_downtown` — nothing else new).

```bash
git add energy_grid_game/ui/iso_city.py energy_grid_game/test_city_model.py
git commit -m "Expose IsoCity.plants as a public read accessor"
```

---

### Task 2: Camera-facing billboard geometry + runtime texture creation

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Produces: `camera_basis() -> (right_world: np.ndarray(3,), up_world: np.ndarray(3,), facing_normal: np.ndarray(3,))` — pure numpy, derived once from `CAM_ROT`.
- Produces: `billboard_quad(width_world, height_world, basis=None) -> (pos, nrm, uv, idx)` — pure numpy, same 5-tuple-minus-tex shape `GLMesh` expects (4 verts, 2 triangles), anchored so the quad's bottom edge sits at local `y=0` and top edge at local `y=height_world`, centered on `x=0` (i.e. corners at `x = ±width_world/2`), using `right_world`/`up_world` to place the quad in world-facing orientation, with `nrm` set to `facing_normal` at every vertex.
- Produces: `create_dynamic_texture(ctx, surface) -> moderngl.Texture` — converts a pygame `Surface` to a GL texture at runtime (not from a baked `.npz`).

- [ ] **Step 1: Write the failing tests**

Add to `energy_grid_game/test_terrain3d.py`:

```python
def test_camera_basis_vectors_are_orthonormal():
    right, up, facing = camera_basis()
    for v in (right, up, facing):
        assert abs(np.linalg.norm(v) - 1.0) < 1e-6
    assert abs(np.dot(right, up)) < 1e-6
    assert abs(np.dot(right, facing)) < 1e-6
    assert abs(np.dot(up, facing)) < 1e-6
    # up should be world-vertical: billboards stand upright, matching the
    # existing 2D sprites' "flat cutout standing on the ground" convention.
    assert np.allclose(up, np.array([0.0, 1.0, 0.0]), atol=1e-6)


def test_billboard_quad_has_four_verts_and_two_triangles():
    pos, nrm, uv, idx = billboard_quad(2.0, 3.0)
    assert pos.shape == (4, 3)
    assert nrm.shape == (4, 3)
    assert uv.shape == (4, 2)
    assert idx.shape == (2, 3)
    # bottom edge at y=0, top edge at y=height, centered on x=0 in the
    # camera-facing basis (before the per-instance world offset is added)
    assert np.isclose(pos[:, 1].min(), 0.0)
    assert np.isclose(pos[:, 1].max(), 3.0)


def test_create_dynamic_texture_matches_surface_size():
    ctx = create_context()
    try:
        surf = pygame.Surface((17, 23), pygame.SRCALPHA)
        surf.fill((255, 0, 0, 255))
        tex = create_dynamic_texture(ctx, surf)
        assert tex.size == (17, 23)
    finally:
        ctx.release()
```

(Add `import numpy as np` and the pygame import already present in the file if not already there;
this file already imports `pygame` and `create_context` from earlier tasks.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: `ImportError`/`NameError` (functions don't exist yet).

- [ ] **Step 3: Implement**

Add to `energy_grid_game/ui/terrain3d.py` (after `CAM_ROT` is defined):

```python
def camera_basis():
    """World-space basis for a camera-facing billboard, derived once from
    the fixed CAM_ROT. right_world/up_world span the billboard's plane;
    facing_normal points back toward the camera (used so a billboard's
    fragment lighting reads as close to fully lit/undistorted as the
    shared banded-lighting shader allows, keeping the plant sprite's
    original colors close to their 2D appearance). CAM_ROT is orthonormal,
    so its inverse is its transpose."""
    inv = CAM_ROT.T
    right_world = inv @ np.array([1.0, 0.0, 0.0])
    facing_normal = inv @ np.array([0.0, 0.0, -1.0])
    up_world = np.array([0.0, 1.0, 0.0])
    return right_world / np.linalg.norm(right_world), up_world, facing_normal / np.linalg.norm(facing_normal)


def billboard_quad(width_world, height_world, basis=None):
    """A single camera-facing quad: bottom edge at local y=0 (ground),
    top edge at y=height_world, centered on x=0. `basis` overrides
    camera_basis() for testing; production callers use the default."""
    right_world, up_world, facing_normal = basis or camera_basis()
    half_w = width_world / 2.0
    bottom_left = -half_w * right_world
    bottom_right = half_w * right_world
    top_left = bottom_left + height_world * up_world
    top_right = bottom_right + height_world * up_world
    pos = np.array([bottom_left, bottom_right, top_right, top_left], dtype="f4")
    nrm = np.tile(facing_normal.astype("f4"), (4, 1))
    uv = np.array([[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]], dtype="f4")
    idx = np.array([[0, 1, 2], [0, 2, 3]], dtype="i4")
    return pos, nrm, uv, idx


def create_dynamic_texture(ctx, surface):
    """Runtime GL texture from a pygame Surface (plant sprites are drawn
    procedurally at bake time, not baked offline like terrain/road/building
    meshes -- there is no .npz for these)."""
    w, h = surface.get_size()
    data = pygame.image.tostring(surface.convert_alpha(), "RGBA", False)
    tex = ctx.texture((w, h), 4, data)
    tex.filter = moderngl.NEAREST, moderngl.NEAREST
    return tex
```

- [ ] **Step 4: Run tests to verify they pass, commit**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: all pass.

```bash
git add energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
git commit -m "Add camera-facing billboard geometry and runtime texture creation"
```

---

### Task 3: Pure plant-to-billboard-placement mapping

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Consumes: `IsoCity.plants` (Task 1) — a list of `PlantSite` objects with `.key`, `.col`, `.row`, `.sprite` (pygame `Surface`).
- Produces: `build_plant_billboards(plants) -> list[dict]`, pure (no GL calls), one dict per plant:
  `{"key": str, "offset": (x, y, z) float tuple, "width_world": float, "height_world": float, "surface": pygame.Surface}`.
  World offset uses `(-row*TILE_SPACING, 0.0, col*TILE_SPACING)`; `width_world`/`height_world` are
  `sprite.get_width() / PX_PER_UNIT` and `sprite.get_height() / PX_PER_UNIT`.

- [ ] **Step 1: Write the failing test**

Add to `energy_grid_game/test_terrain3d.py`:

```python
class _FakePlantSite:
    def __init__(self, key, col, row, w, h):
        self.key = key
        self.col, self.row = col, row
        self.sprite = pygame.Surface((w, h), pygame.SRCALPHA)


def test_build_plant_billboards_converts_col_row_and_sprite_size():
    plants = [_FakePlantSite("gas", 3, -5, 32, 64)]
    billboards = build_plant_billboards(plants)
    assert len(billboards) == 1
    b = billboards[0]
    assert b["key"] == "gas"
    assert np.allclose(b["offset"], (5.0 * TILE_SPACING, 0.0, 3.0 * TILE_SPACING))
    assert np.isclose(b["width_world"], 32 / PX_PER_UNIT)
    assert np.isclose(b["height_world"], 64 / PX_PER_UNIT)
    assert b["surface"] is plants[0].sprite


def test_build_plant_billboards_handles_multiple_plants():
    plants = [_FakePlantSite("gas", 0, 0, 10, 10), _FakePlantSite("solar", 5, 5, 20, 20)]
    assert len(build_plant_billboards(plants)) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: `NameError: name 'build_plant_billboards' is not defined`.

- [ ] **Step 3: Implement**

Add to `energy_grid_game/ui/terrain3d.py` (near `build_instances`):

```python
def build_plant_billboards(plants):
    """Pure PlantSite-list -> billboard placement data. No GL calls. Uses
    the same (-row*TILE_SPACING, 0, col*TILE_SPACING) world convention as
    build_instances(), NOT the clamped 2D sx/sy IsoCity uses for its own
    on-screen anchor (see Phase 3a design doc's scope note)."""
    billboards = []
    for site in plants:
        w, h = site.sprite.get_size()
        billboards.append({
            "key": site.key,
            "offset": (-float(site.row) * TILE_SPACING, 0.0, float(site.col) * TILE_SPACING),
            "width_world": w / PX_PER_UNIT,
            "height_world": h / PX_PER_UNIT,
            "surface": site.sprite,
        })
    return billboards
```

- [ ] **Step 4: Run tests to verify they pass, commit**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: all pass.

```bash
git add energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
git commit -m "Add pure plant-to-billboard placement mapping"
```

---

### Task 4: GL billboard draw path + depth-occlusion proof + main.py wiring

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`
- Modify: `energy_grid_game/main.py`

**Interfaces:**
- Produces: `load_billboards(ctx, prog, billboards) -> list[GLMesh]` (one `GLMesh`-like object per
  plant, each with its own 1-vertex-quad geometry from `billboard_quad()` and its own texture from
  `create_dynamic_texture()`, each carrying exactly 1 instance at the plant's world offset with
  yaw=0.0).
- Modifies `draw(ctx, prog, meshes, fbo, camera, ...)`'s call sites in `main.py` to additionally
  draw plant billboards in the same pass (same depth buffer), OR extends `draw()` itself to accept
  an optional `billboard_meshes` list — pick whichever keeps `terrain3d.py`'s existing `draw()`
  signature least disrupted; document your choice.

- [ ] **Step 1: Write the failing GL depth-occlusion test**

Add to `energy_grid_game/test_terrain3d.py`:

```python
def test_billboard_is_occluded_by_a_nearer_building_instance():
    """Synthetic proof of the core Phase 3a claim: a billboard placed
    BEHIND a building (from the fixed camera's view) is hidden by it,
    because both share the same depth buffer. Uses a real 'tower' building
    mesh and a synthetic solid-color billboard surface so the two are
    visually distinguishable in the readback."""
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        upload_instances(ctx, meshes, {"tower": np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4")})

        red_surface = pygame.Surface((32, 64), pygame.SRCALPHA)
        red_surface.fill((255, 0, 0, 255))
        # Placed at the SAME (x,z) as the tower instance but further from
        # the camera along the tower's depth axis, so the tower's nearer
        # fragments must win the depth test at any overlapping pixel.
        billboards = [{"key": "test", "offset": (0.0, 0.0, 5.0),
                       "width_world": 2.0, "height_world": 2.0, "surface": red_surface}]
        billboard_meshes = load_billboards(ctx, prog, billboards)

        camera = _FakeCamera(center=(0.0, 0.0), zoom=1.0)
        fbo = create_framebuffer(ctx, (128, 128))
        draw(ctx, prog, meshes, fbo, camera, billboard_meshes=billboard_meshes)
        rgba, size = read_rgba(fbo)
        pixels = np.frombuffer(rgba, dtype="u1").reshape(size[1], size[0], 4)
        # No pure-red pixel should be visible anywhere -- if the billboard
        # were drawn without depth testing (or after, ignoring depth), its
        # solid red fill would show through/around the tower.
        is_red = (pixels[:, :, 0] > 200) & (pixels[:, :, 1] < 60) & (pixels[:, :, 2] < 60)
        assert not is_red.any()
    finally:
        ctx.release()
```

(This test's exact `offset`/camera values may need adjusting once you see real render output —
the point is: billboard and building must overlap in screen space with the building nearer to the
camera, so the assertion meaningfully exercises depth testing rather than trivially passing because
the two never overlap on screen. Adjust coordinates as needed, but keep the assertion checking
actual pixel content, not just "no exception.")

- [ ] **Step 2: Run test to verify it fails**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: `NameError`/`TypeError` (`load_billboards`/`draw`'s new parameter don't exist yet).

- [ ] **Step 3: Implement**

In `energy_grid_game/ui/terrain3d.py`, add:

```python
def load_billboards(ctx, prog, billboards):
    meshes = []
    for b in billboards:
        pos, nrm, uv, idx = billboard_quad(b["width_world"], b["height_world"])
        tex_surface = b["surface"]
        w, h = tex_surface.get_size()
        tex_data = np.frombuffer(
            pygame.image.tostring(tex_surface.convert_alpha(), "RGBA", False), dtype="u1"
        ).reshape(h, w, 4)
        mesh = GLMesh(ctx, prog, pos, nrm, uv, idx, tex_data)
        mesh.set_instances(np.array([[*b["offset"], 0.0]], dtype="f4"))
        meshes.append(mesh)
    return meshes
```

Modify `draw()`'s signature to accept billboards, drawn after the material meshes (same fbo, same
depth state, no `ctx.clear()` between the two -- billboards must render into the SAME framebuffer
pass, not a fresh one):

```python
def draw(ctx, prog, meshes, fbo, camera, px_per_unit=PX_PER_UNIT, ambient=0.55, billboard_meshes=None):
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
    for mesh in (billboard_meshes or []):
        mesh.render()
```

(This keeps `draw()` backward compatible — existing callers that don't pass `billboard_meshes`
behave exactly as before.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python energy_grid_game/test_terrain3d.py`
Expected: all pass, including the new depth-occlusion test. If it fails, debug the actual geometry
(billboard position/size, camera framing) rather than weakening the assertion — this test is the
core proof-of-correctness for this phase.

- [ ] **Step 5: Wire into `main.py` (proof-of-mechanism only, does not change default visible output)**

In `energy_grid_game/main.py`'s existing `GRIDMANAGER_TERRAIN3D`-gated per-frame block (where
`terrain3d.draw(...)` is already called), add plant billboard loading/drawing:

```python
        if city.layout_key != terrain3d_key:
            terrain3d.upload_instances(gl_ctx, terrain3d_meshes,
                                        terrain3d.build_instances(city.tiles))
            terrain3d_plant_meshes = terrain3d.load_billboards(
                gl_ctx, terrain3d_prog, terrain3d.build_plant_billboards(city.plants))
            terrain3d_key = city.layout_key
        ...
        terrain3d.draw(gl_ctx, terrain3d_prog, terrain3d_meshes, terrain3d_fbo, city.camera,
                        billboard_meshes=terrain3d_plant_meshes)
```

(Match this against the ACTUAL current structure of that block — read it first, don't assume line
numbers; initialize `terrain3d_plant_meshes = []` alongside the other `terrain3d_*` state
variables at startup.) This makes billboards render into the 3D pass and get properly depth-tested,
but since the 2D `city.draw()` call still draws the plant's static+live sprite on top afterward
(per this plan's Global Constraints — untouched), nothing about the default visible output changes
yet. This step exists so the mechanism runs against real game state end-to-end, not just in tests.

- [ ] **Step 6: Verify end-to-end with a real layout**

Write a standalone script (scratchpad, not committed) building a real `IsoCity`+`GameState` with
`GRIDMANAGER_TERRAIN3D=1`, calling the same sequence `main.py` now does (including the new billboard
loading/draw), and confirm no exceptions occur and `city.plants` billboards get created for a real
fleet. A full visual proof isn't required here (Task 4's Step 4 GL test already proves depth
correctness synthetically) — this step is a smoke check that the real-data path doesn't crash and
produces a sane (non-empty, for a fleet with plants) billboard list.

- [ ] **Step 7: Run full regression check, commit**

```bash
python energy_grid_game/test_terrain3d.py
python energy_grid_game/test_city_model.py
```

Expected: all pass (city_model: same one known pre-existing unrelated failure, nothing new).

```bash
git add energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py energy_grid_game/main.py
git commit -m "Wire plant billboards into the 3D render pass with depth occlusion"
```

---

## Self-review notes

- **Spec coverage:** camera-facing billboard geometry, runtime texture creation, world-position
  reuse of the established `(-row*TILE_SPACING, 0, col*TILE_SPACING)` formula, depth-tested
  compositing, and the explicit "don't flip visibility yet" scope boundary are all covered.
- **Deliberately deferred, not a gap:** live/animated plant overlay, hiding the 2D static sprite,
  transmission (towers/lines) — all Phase 3b/4 per the design doc.
