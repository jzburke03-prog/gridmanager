# Real-Time 3D Terrain Phase 3b Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render high-voltage transmission towers and conductor lines in the opt-in 3D terrain layer, using the existing 2D transmission routes as the source of truth.

**Architecture:** `IsoCity` exposes a read-only transmission snapshot produced during `_bake()`. `ui/terrain3d.py` converts that snapshot into tower billboards and procedural conductor strip meshes, then `main.py` rebuilds/releases those GL resources alongside plant billboards whenever `city.layout_key` changes.

**Tech Stack:** Python 3.12, pygame 2.6, numpy, moderngl. No new dependencies.

## Global Constraints

- `GRIDMANAGER_TERRAIN3D` stays default-off.
- Existing simulation, plant placement, `_route_transmission`, `_build_distribution`, and `Flow` semantics remain unchanged.
- Distribution feeders, service poles, transformer fires, and building-lighting behavior stay 2D in this phase.
- 3D animated electrons are out of scope; existing 2D `Flow` particles remain active.
- Use `.codex_portable_build_20260804_001/venv/Scripts/python.exe`; `.venv39` is currently unusable.
- Do not hide the old 2D transmission layer in this phase.

---

## File Structure

- Modify `energy_grid_game/ui/iso_city.py`: capture `tower_points` and `conductor_paths` during `_bake()` and expose `IsoCity.transmission3d`.
- Modify `energy_grid_game/ui/terrain3d.py`: add screen/world conversion helpers, tower billboard construction, conductor strip geometry, GL resource loading, drawing, and release helpers.
- Modify `energy_grid_game/main.py`: rebuild/release transmission GL resources with `city.layout_key`; pass them into `terrain3d.draw`.
- Modify `energy_grid_game/test_terrain3d.py`: pure and GL tests for conversion, route geometry, and draw output.
- Modify `energy_grid_game/test_city_model.py`: small accessor test for `IsoCity.transmission3d`.

---

### Task 1: Expose a read-only transmission snapshot from IsoCity

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Produces: `IsoCity.transmission3d -> tuple[dict, ...]`
- Each dict has exact keys: `key`, `substation_index`, `tower_points`, `conductor_paths`

- [ ] **Step 1: Write the failing test**

Add to `energy_grid_game/test_city_model.py`:

```python
def test_transmission3d_snapshot_is_publicly_readable():
    import pygame
    from game_state import GameState
    import scenarios
    from ui.iso_city import IsoCity

    pygame.init()
    city = IsoCity(None)
    rect = pygame.Rect(0, 0, 1400, 700)
    state = GameState(scenarios.make_standard())
    city.prepare(rect, state)

    snapshot = city.transmission3d
    assert isinstance(snapshot, tuple)
    assert snapshot
    first = snapshot[0]
    assert set(first) == {"key", "substation_index", "tower_points", "conductor_paths"}
    assert first["tower_points"]
    assert set(first["conductor_paths"]) == {-6, 6}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
```

Expected: the new test fails with `AttributeError: 'IsoCity' object has no attribute 'transmission3d'`. The pre-existing `test_layout_reserves_city_center_sprites_near_downtown` may still fail; do not fix it in this task.

- [ ] **Step 3: Store snapshot records during `_bake()`**

In `energy_grid_game/ui/iso_city.py`, initialize `self._transmission3d = ()` in `IsoCity.__init__` next to `self._transmission_routes`.

In `_bake()`, immediately after `conductor_paths[(key, i)] = arm_paths`, append a dict to a local list:

```python
        transmission3d = []
        ...
            conductor_paths[(key, i)] = arm_paths
            transmission3d.append({
                "key": key,
                "substation_index": i,
                "tower_points": tuple((float(x), float(y)) for x, y in route_towers),
                "conductor_paths": {
                    arm: tuple((float(x), float(y)) for x, y in pts)
                    for arm, pts in arm_paths.items()
                },
            })
```

Place `transmission3d = []` before the `for key, i, path in self._routes:` loop. After the loop, set:

```python
        self._transmission3d = tuple(transmission3d)
```

Add the property near the existing `plants`/`tiles` accessors:

```python
    @property
    def transmission3d(self):
        """Read-only 3D transmission geometry snapshot built during bake."""
        return self._transmission3d
```

- [ ] **Step 4: Run tests**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
```

Expected: the new test passes. The only acceptable failure is the known pre-existing downtown test.

- [ ] **Step 5: Checkpoint**

Run:

```powershell
git diff -- energy_grid_game/ui/iso_city.py energy_grid_game/test_city_model.py
```

---

### Task 2: Add screen/world conversion helpers and pure transmission geometry

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Produces: `screen_px_to_world(screen_point: tuple[float, float], origin: tuple[float, float], y_world=0.0) -> tuple[float, float, float]`
- Produces: `build_transmission_geometry(snapshot, origin) -> dict`
- Return shape: `{"towers": list[dict], "conductors": list[dict]}`

- [ ] **Step 1: Write failing pure tests**

Add to `energy_grid_game/test_terrain3d.py`:

```python
def test_screen_px_to_world_round_trips_iso_projected_tile_center():
    from ui.iso_city import iso_xy
    col, row = 7, -3
    origin = (700.0, 392.0)
    sx, sy = iso_xy(col, row)
    world = screen_px_to_world((sx + origin[0], sy + origin[1]), origin)
    expected = (-float(row) * TILE_SPACING, 0.0, float(col) * TILE_SPACING)
    assert np.allclose(world, expected, atol=1e-5)


def test_build_transmission_geometry_creates_towers_and_conductors():
    snapshot = ({
        "key": "gas",
        "substation_index": 0,
        "tower_points": ((700.0, 392.0), (716.0, 400.0)),
        "conductor_paths": {
            -6: ((694.0, 376.0), (710.0, 384.0)),
            6: ((706.0, 376.0), (722.0, 384.0)),
        },
    },)
    geom = build_transmission_geometry(snapshot, origin=(700.0, 392.0))
    assert len(geom["towers"]) == 2
    assert len(geom["conductors"]) == 2
    assert geom["towers"][0]["key"] == "gas"
    assert geom["conductors"][0]["key"] == "gas"
```

Update the import block to include `screen_px_to_world` and `build_transmission_geometry`.

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: import/name failure for the new helpers.

- [ ] **Step 3: Implement conversion and pure geometry**

In `energy_grid_game/ui/terrain3d.py`, add after `build_plant_billboards`:

```python
def screen_px_to_world(screen_point, origin, y_world=0.0):
    """Convert an IsoCity screen-space point back into terrain3d world X/Y/Z.

    This is the inverse of iso_xy plus build_instances' world convention:
    sx = (col - row) * TW/2 + origin_x
    sy = (col + row) * TH/2 + origin_y
    x = -row * TILE_SPACING
    z = col * TILE_SPACING
    """
    sx = (float(screen_point[0]) - float(origin[0])) / (TW / 2.0)
    sy = (float(screen_point[1]) - float(origin[1])) / (TH / 2.0)
    col = (sx + sy) / 2.0
    row = (sy - sx) / 2.0
    return (-row * TILE_SPACING, float(y_world), col * TILE_SPACING)


def build_transmission_geometry(snapshot, origin):
    towers = []
    conductors = []
    for route in snapshot:
        key = route["key"]
        sub_index = route["substation_index"]
        for point in route["tower_points"]:
            towers.append({
                "key": key,
                "substation_index": sub_index,
                "offset": screen_px_to_world(point, origin),
            })
        for arm, points in route["conductor_paths"].items():
            world_points = tuple(screen_px_to_world(point, origin, y_world=0.0)
                                 for point in points)
            if len(world_points) >= 2:
                conductors.append({
                    "key": key,
                    "substation_index": sub_index,
                    "arm": arm,
                    "points": world_points,
                })
    return {"towers": towers, "conductors": conductors}
```

- [ ] **Step 4: Run tests**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: all terrain3d tests pass.

- [ ] **Step 5: Checkpoint**

Run:

```powershell
git diff -- energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
```

---

### Task 3: Build procedural conductor strip meshes

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Produces: `conductor_strip_mesh(conductors, width_world=0.16) -> (pos, nrm, uv, idx, tex)`

- [ ] **Step 1: Write failing tests**

Add to `energy_grid_game/test_terrain3d.py`:

```python
def test_conductor_strip_mesh_builds_quads_for_each_segment():
    conductors = [{
        "key": "gas",
        "substation_index": 0,
        "arm": -6,
        "points": ((0.0, 0.0, 0.0), (3.2, 0.0, 0.0), (6.4, 0.0, 0.0)),
    }]
    pos, nrm, uv, idx, tex = conductor_strip_mesh(conductors)
    assert pos.shape == (8, 3)      # two segments, four verts each
    assert idx.shape == (4, 3)      # two triangles per segment
    assert tex.shape == (1, 1, 4)
```

Update imports to include `conductor_strip_mesh`.

- [ ] **Step 2: Run test to verify it fails**

Expected: name/import failure.

- [ ] **Step 3: Implement conductor strips**

Add to `energy_grid_game/ui/terrain3d.py`:

```python
def conductor_strip_mesh(conductors, width_world=0.16):
    verts = []
    normals = []
    uvs = []
    indices = []
    normal = np.array([0.0, 1.0, 0.0], dtype="f4")
    half = width_world / 2.0
    for conductor in conductors:
        pts = conductor["points"]
        for a, b in zip(pts, pts[1:]):
            a = np.array(a, dtype="f4")
            b = np.array(b, dtype="f4")
            direction = b - a
            length = np.linalg.norm(direction[[0, 2]])
            if length <= 1e-6:
                continue
            side = np.array([-direction[2], 0.0, direction[0]], dtype="f4")
            side = side / max(np.linalg.norm(side), 1e-6) * half
            base = len(verts)
            verts.extend([a - side, a + side, b + side, b - side])
            normals.extend([normal, normal, normal, normal])
            uvs.extend([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
            indices.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])
    if not verts:
        verts = [np.zeros(3, dtype="f4")] * 4
        normals = [normal] * 4
        uvs = [(0.0, 0.0)] * 4
        indices = [(0, 1, 2), (0, 2, 3)]
    tex = np.array([[[116, 122, 132, 255]]], dtype="u1")
    return (np.array(verts, dtype="f4"),
            np.array(normals, dtype="f4"),
            np.array(uvs, dtype="f4"),
            np.array(indices, dtype="i4"),
            tex)
```

- [ ] **Step 4: Run tests**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: all terrain3d tests pass.

- [ ] **Step 5: Checkpoint**

Run:

```powershell
git diff -- energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
```

---

### Task 4: Build tower billboard resources and transmission GL loader

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Produces: `tower_billboard_surface() -> pygame.Surface`
- Produces: `build_tower_billboards(towers) -> list[dict]`
- Produces: `load_transmission(ctx, prog, geometry) -> dict`
- Produces: `release_transmission(transmission_meshes) -> None`

- [ ] **Step 1: Write failing tests**

Add to `energy_grid_game/test_terrain3d.py`:

```python
def test_tower_billboards_use_shared_surface_and_offsets():
    towers = [{"key": "gas", "substation_index": 0, "offset": (1.0, 0.0, 2.0)}]
    billboards = build_tower_billboards(towers)
    assert len(billboards) == 1
    assert billboards[0]["offset"] == (1.0, 0.0, 2.0)
    assert billboards[0]["surface"].get_width() > 0
    assert billboards[0]["surface"].get_height() > 0


def test_load_transmission_creates_releasable_resources():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        geometry = {
            "towers": [{"key": "gas", "substation_index": 0, "offset": (0.0, 0.0, 0.0)}],
            "conductors": [{
                "key": "gas", "substation_index": 0, "arm": -6,
                "points": ((0.0, 0.0, 0.0), (3.2, 0.0, 0.0)),
            }],
        }
        tx = load_transmission(ctx, prog, geometry)
        assert tx["towers"]
        assert tx["conductors"] is not None
        release_transmission(tx)
    finally:
        ctx.release()
```

Update imports for the four new functions.

- [ ] **Step 2: Run tests to verify they fail**

Expected: name/import failure.

- [ ] **Step 3: Implement tower billboards and GL loader**

Add to `energy_grid_game/ui/terrain3d.py`:

```python
_TOWER_SURFACE = None


def tower_billboard_surface():
    global _TOWER_SURFACE
    if _TOWER_SURFACE is None:
        surf = pygame.Surface((24, 42), pygame.SRCALPHA)
        steel = (126, 132, 142, 255)
        dark = (54, 60, 68, 255)
        x, y, h = 12, 38, 34
        pygame.draw.line(surf, dark, (x - 5, y), (x, y - h), 1)
        pygame.draw.line(surf, dark, (x + 5, y), (x, y - h), 1)
        pygame.draw.line(surf, steel, (x - 3, y), (x, y - h + 1), 1)
        for yy in (y - 7, y - 16, y - 25):
            pygame.draw.line(surf, steel, (x - 8, yy), (x + 8, yy), 1)
            pygame.draw.line(surf, (164, 168, 176, 255), (x - 8, yy), (x - 8, yy + 3), 1)
            pygame.draw.line(surf, (164, 168, 176, 255), (x + 8, yy), (x + 8, yy + 3), 1)
        pygame.draw.line(surf, steel, (x, y - h), (x, y - h - 3), 1)
        _TOWER_SURFACE = surf
    return _TOWER_SURFACE


def build_tower_billboards(towers):
    surface = tower_billboard_surface()
    w, h = surface.get_size()
    return [{
        "key": tower["key"],
        "offset": tower["offset"],
        "width_world": w / PX_PER_UNIT,
        "height_world": h / (PX_PER_UNIT * _VERTICAL_FORESHORTENING),
        "surface": surface,
    } for tower in towers]


def load_transmission(ctx, prog, geometry):
    tower_meshes = load_billboards(ctx, prog, build_tower_billboards(geometry["towers"]))
    pos, nrm, uv, idx, tex = conductor_strip_mesh(geometry["conductors"])
    conductor_mesh = GLMesh(ctx, prog, pos, nrm, uv, idx, tex)
    conductor_mesh.set_instances(np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4"))
    return {"towers": tower_meshes, "conductors": conductor_mesh}


def release_transmission(transmission_meshes):
    if not transmission_meshes:
        return
    for mesh in transmission_meshes.get("towers", []):
        mesh.release()
    conductor = transmission_meshes.get("conductors")
    if conductor is not None:
        conductor.release()
```

- [ ] **Step 4: Run tests**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: all terrain3d tests pass.

- [ ] **Step 5: Checkpoint**

Run:

```powershell
git diff -- energy_grid_game/ui/terrain3d.py energy_grid_game/test_terrain3d.py
```

---

### Task 5: Draw transmission resources in the 3D pass and wire main.py

**Files:**
- Modify: `energy_grid_game/ui/terrain3d.py`
- Modify: `energy_grid_game/main.py`
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- Changes: `draw(..., transmission_meshes=None)` optional parameter

- [ ] **Step 1: Add GL smoke test**

Add to `energy_grid_game/test_terrain3d.py`:

```python
def test_draw_renders_transmission_conductor_pixels():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        upload_instances(ctx, meshes, {})
        geometry = {
            "towers": [],
            "conductors": [{
                "key": "gas", "substation_index": 0, "arm": -6,
                "points": ((-1.6, 0.0, 0.0), (1.6, 0.0, 0.0)),
            }],
        }
        tx = load_transmission(ctx, prog, geometry)
        fbo = create_framebuffer(ctx, (128, 128))
        draw(ctx, prog, meshes, fbo, _FakeCamera(center=(-64.0, -64.0), zoom=4.0),
             transmission_meshes=tx)
        rgba, size = read_rgba(fbo)
        pixels = np.frombuffer(rgba, dtype="u1").reshape(size[1], size[0], 4)
        background = np.array([25, 28, 33], dtype="u1")
        assert np.any(np.abs(pixels[:, :, :3].astype("i2") - background.astype("i2")).sum(axis=2) > 20)
        release_transmission(tx)
    finally:
        ctx.release()
```

- [ ] **Step 2: Run test to verify it fails**

Expected: `draw()` rejects `transmission_meshes`.

- [ ] **Step 3: Extend `draw()`**

In `energy_grid_game/ui/terrain3d.py`, change the signature:

```python
def draw(ctx, prog, meshes, fbo, camera, px_per_unit=PX_PER_UNIT, ambient=0.55,
         billboard_meshes=None, transmission_meshes=None):
```

After rendering base meshes and before plant billboards, render conductors then towers:

```python
    if transmission_meshes:
        conductor = transmission_meshes.get("conductors")
        if conductor is not None:
            conductor.render()
        for mesh in transmission_meshes.get("towers", []):
            mesh.render()
```

Keep plant billboards after transmission so plant billboards still win where they are nearer in depth.

- [ ] **Step 4: Wire `main.py`**

In `energy_grid_game/main.py`, initialize:

```python
    terrain3d_transmission_meshes = None
```

In the `city.layout_key != terrain3d_key` block, release old resources before loading new ones:

```python
                terrain3d.release_transmission(terrain3d_transmission_meshes)
                terrain3d_transmission_meshes = terrain3d.load_transmission(
                    gl_ctx, terrain3d_prog,
                    terrain3d.build_transmission_geometry(city.transmission3d, city._origin))
```

Pass the new resources into draw:

```python
            terrain3d.draw(gl_ctx, terrain3d_prog, terrain3d_meshes, terrain3d_fbo, city.camera,
                            billboard_meshes=terrain3d_plant_meshes,
                            transmission_meshes=terrain3d_transmission_meshes)
```

On shutdown, release the resources before `pygame.quit()`:

```python
    if terrain3d_transmission_meshes is not None:
        terrain3d.release_transmission(terrain3d_transmission_meshes)
```

- [ ] **Step 5: Run tests**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
```

Expected: all terrain3d tests pass. City model may still have only the known pre-existing downtown failure.

- [ ] **Step 6: Checkpoint**

Run:

```powershell
git diff -- energy_grid_game/ui/terrain3d.py energy_grid_game/main.py energy_grid_game/test_terrain3d.py
```

---

### Task 6: Real-layout smoke check

**Files:**
- Modify: `energy_grid_game/test_terrain3d.py`

**Interfaces:**
- No production interface changes.

- [ ] **Step 1: Add real-layout test**

Add to `energy_grid_game/test_terrain3d.py`:

```python
def test_build_transmission_geometry_from_a_real_city_layout():
    from types import SimpleNamespace

    viewport = pygame.Rect(0, 0, 1400, 700)
    gas = SimpleNamespace(
        key="gas", max_output_mw=750.0, ramp_up_latency=3, ramp_down_latency=3)
    solar = SimpleNamespace(
        key="solar", max_output_mw=100.0, ramp_up_latency=1, ramp_down_latency=1)
    state = SimpleNamespace(population=200_000, sources=[gas, solar])
    city = IsoCity(None)
    city.prepare(viewport, state)

    geom = build_transmission_geometry(city.transmission3d, city._origin)
    assert len(geom["towers"]) >= len(city.transmission3d)
    assert len(geom["conductors"]) == len(city.transmission3d) * 2
```

- [ ] **Step 2: Run test**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
```

Expected: all terrain3d tests pass.

- [ ] **Step 3: Optional visual smoke**

Run the game with:

```powershell
$env:GRIDMANAGER_TERRAIN3D='1'
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe run_game.py
```

Expected: no crash; the 3D pass builds terrain, roads, buildings, plant billboards, and transmission resources. The old 2D transmission layer still draws on top by design.

- [ ] **Step 4: Final verification**

Run:

```powershell
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_terrain3d.py
.\.codex_portable_build_20260804_001\venv\Scripts\python.exe energy_grid_game\test_city_model.py
git status --short
```

Expected: terrain3d green; city model has no new failures beyond the known downtown test; git status shows only intentional files.

---

## Self-Review

- **Spec coverage:** snapshot exposure (Task 1), pure conversion and geometry (Task 2), procedural conductors (Task 3), tower billboards and GL resources (Task 4), draw/main wiring (Task 5), real-layout smoke (Task 6).
- **Placeholder scan:** no placeholder tasks; every test and implementation step names exact functions, files, and expected outcomes.
- **Type consistency:** `transmission3d`, `build_transmission_geometry`, `conductor_strip_mesh`, `load_transmission`, and `release_transmission` names match across tasks.
- **Deferred intentionally:** hiding 2D transmission, 3D animated electrons, distribution feeders, unlit billboard shader, day/night/season lighting, snow, capture harness, and dense-downtown architecture cleanup are Phase 4 scope.

