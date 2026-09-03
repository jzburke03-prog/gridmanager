# In-Game Voxel Map Elevation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elevate the game's isometric map with a flat-but-slightly-isometric, leaning-voxel look — fix the countryside regression, add edge mountains, a compact city-hero composition, tamed transmission, and season-driven ground palettes riding the existing day/night bake.

**Architecture:** Add a focused, unit-tested module `energy_grid_game/ui/voxel_terrain.py` (voxel drawing primitives, terrain material classification, mountain elevation, season palettes). `iso_city.py` stays the orchestrator and calls into it from `_layout` (tile generation) and `_bake` (drawing). Reuse — never replace — the existing day/night layer bake, ring-light layers, plants, camera, and transmission routing.

**Tech Stack:** Python 3.12, pygame 2.6 (SDL2), numpy (already a dep). Tests: pytest is NOT installed in the venv; use plain `assert`-based test modules runnable with the project's `.venv39` python, matching the existing `test_*.py` files in `energy_grid_game/` (they are plain scripts / pytest-style functions run via the repo's harness). Visual checks: `tools/capture_moments.py`.

## Global Constraints

- **Tile geometry:** `TW, TH = 16, 8` (defined in `ui/iso_city.py`). All voxel primitives must use these; ground-slab voxel depth is small (`VOX_DEPTH = 3` px) — "leaning voxel", not chunky cubes.
- **Reuse, don't replace:** extend the existing `_bake` day/night layers, `daylight()` cross-fade, ring-light layers, `_place_plants`, `_route_transmission`. Plants' live animation (steam, blades, spillway) must keep working.
- **Buildings & plants:** kept; may be *conservatively* enhanced for cohesion, never rewritten in a way that breaks animation or tests.
- **Determinism:** layout is seeded (`random.Random(20260730)` in `_layout`); keep it deterministic so `test_urban_layout_selection_is_deterministic_for_its_seed` and the capture harness stay stable.
- **GIT (standing user instruction this session): DO NOT run `git commit`, `git branch`, `git checkout`, or `git push`.** Where a task says "Commit", instead run the **checkpoint**: `git add -A && git status` to stage-and-review only. Do not create commits unless the user explicitly authorizes it.
- **Run python** via `.venv39/Scripts/python.exe` from repo root `D:/Github/gridmanager`.

---

## File Structure

- **Create** `energy_grid_game/ui/voxel_terrain.py` — voxel primitives (`slab`, `column`), material classification (`material_at`), `elevation`, value noise, season palettes (`SEASONS`, `season_of`, `palette`), `should_rebake_for_season`. One responsibility: the new voxel/terrain/season art logic.
- **Create** `energy_grid_game/test_voxel_terrain.py` — unit tests for the pure functions above.
- **Modify** `energy_grid_game/ui/iso_city.py`:
  - `_layout` (~1735–1805): restore countryside fill, tag mountain tiles, compact plant ring.
  - `_bake` (~2054–2235): draw ground/mountains via `voxel_terrain` with the season palette; thin the transmission towers.
  - `prepare`/bake-trigger: rebuild when the season boundary is crossed.
- **Modify** `energy_grid_game/test_city_model.py` — update assertions that intentionally change (countryside counts, plant ring, transmission density).

---

## Task 1: voxel_terrain module — seasons + palettes (pure, TDD)

**Files:**
- Create: `energy_grid_game/ui/voxel_terrain.py`
- Test: `energy_grid_game/test_voxel_terrain.py`

**Interfaces:**
- Produces: `season_of(month:int)->str` in {"winter","spring","summer","fall"}; `SEASONS: dict[str, dict[str,tuple]]` with keys `grass field water road pad rock snow tree`; `palette(season:str)->dict[str,tuple]`; `should_rebake_for_season(prev:str|None, cur:str)->bool`.

- [ ] **Step 1: Write the failing test**

```python
# energy_grid_game/test_voxel_terrain.py
from ui import voxel_terrain as vt

def test_season_of_boundaries():
    assert vt.season_of(12) == "winter" and vt.season_of(1) == "winter" and vt.season_of(2) == "winter"
    assert vt.season_of(3) == "spring" and vt.season_of(5) == "spring"
    assert vt.season_of(6) == "summer" and vt.season_of(8) == "summer"
    assert vt.season_of(9) == "fall" and vt.season_of(11) == "fall"

def test_palette_has_all_materials():
    keys = {"grass", "field", "water", "road", "pad", "rock", "snow", "tree"}
    for s in ("winter", "spring", "summer", "fall"):
        assert keys <= set(vt.palette(s)), s

def test_should_rebake_for_season():
    assert vt.should_rebake_for_season(None, "summer") is True
    assert vt.should_rebake_for_season("summer", "summer") is False
    assert vt.should_rebake_for_season("summer", "fall") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv39/Scripts/python.exe -m pytest energy_grid_game/test_voxel_terrain.py -q` (if pytest missing, run: `.venv39/Scripts/python.exe -c "import sys; sys.path.insert(0,'energy_grid_game'); import test_voxel_terrain as t; t.test_season_of_boundaries()"`)
Expected: FAIL / ModuleNotFoundError: No module named 'ui.voxel_terrain'

- [ ] **Step 3: Write minimal implementation**

```python
# energy_grid_game/ui/voxel_terrain.py
"""Voxel-hybrid terrain art for the iso map: thin-depth ground slabs, edge
mountains, and season palettes. Pure helpers here are unit-tested; the pygame
drawing primitives are exercised by the capture harness. Called from iso_city."""
from ui.iso_city import TW, TH  # 16, 8 -- single source of truth for tile size

_SEASON_BY_MONTH = {12: "winter", 1: "winter", 2: "winter",
                    3: "spring", 4: "spring", 5: "spring",
                    6: "summer", 7: "summer", 8: "summer",
                    9: "fall", 10: "fall", 11: "fall"}

def season_of(month):
    return _SEASON_BY_MONTH[int(month)]

# material colours per season (top-face colour; sides are shaded from it)
SEASONS = {
    "spring": dict(grass=(96,158,84), field=(150,178,92), water=(60,120,196),
                   road=(110,112,116), pad=(120,122,128), rock=(112,108,102),
                   snow=(232,238,246), tree=(70,140,70)),
    "summer": dict(grass=(112,158,80), field=(196,178,98), water=(58,110,190),
                   road=(112,112,110), pad=(120,120,124), rock=(122,114,102),
                   snow=(236,240,246), tree=(56,120,58)),
    "fall":   dict(grass=(150,150,78), field=(198,150,78), water=(58,110,182),
                   road=(104,98,90), pad=(122,116,106), rock=(114,100,86),
                   snow=(232,236,244), tree=(176,96,52)),
    "winter": dict(grass=(224,230,238), field=(214,222,232), water=(150,182,206),
                   road=(150,152,158), pad=(158,160,166), rock=(150,156,166),
                   snow=(244,248,252), tree=(64,110,80)),
}

def palette(season):
    return SEASONS[season]

def should_rebake_for_season(prev, cur):
    return prev != cur
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv39/Scripts/python.exe -c "import sys; sys.path.insert(0,'energy_grid_game'); import test_voxel_terrain as t; [f() for n,f in vars(t).items() if n.startswith('test_')]; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Checkpoint** (git per Global Constraints — stage only)

Run: `git add -A && git status`

---

## Task 2: voxel_terrain — value noise + elevation (pure, TDD)

**Files:**
- Modify: `energy_grid_game/ui/voxel_terrain.py`
- Test: `energy_grid_game/test_voxel_terrain.py`

**Interfaces:**
- Produces: `elevation(col:int, row:int, cx:float, cy:float, start:float, full:float)->int` (voxel px height; 0 inside `start` radius, rising to noisy peaks by `full`). `vnoise(x:float,y:float)->float` in [0,1].

- [ ] **Step 1: Write the failing test**

```python
# add to test_voxel_terrain.py
def test_elevation_zero_in_play_area():
    assert vt.elevation(0, 0, 0.0, 0.0, 24.0, 42.0) == 0
    assert vt.elevation(10, 10, 0.0, 0.0, 24.0, 42.0) == 0   # d~14 < 24

def test_elevation_rises_at_edge():
    h = vt.elevation(50, 50, 0.0, 0.0, 24.0, 42.0)           # d~70 > full
    assert h > 0

def test_vnoise_range():
    for x, y in ((0.1, 0.2), (3.4, 9.9), (12.0, 0.0)):
        v = vt.vnoise(x, y)
        assert 0.0 <= v <= 1.0
```

- [ ] **Step 2: Run to verify fail** — `AttributeError: module ... has no attribute 'elevation'`.

- [ ] **Step 3: Implement**

```python
# add to voxel_terrain.py
import math

def _h2(a, b):
    n = (int(a) * 374761393 + int(b) * 668265263) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return (n & 0xFFFF) / 65535.0

def vnoise(x, y):
    xi, yi = math.floor(x), math.floor(y)
    xf, yf = x - xi, y - yi
    def sm(t): return t * t * (3 - 2 * t)
    u, v = sm(xf), sm(yf)
    a, b = _h2(xi, yi), _h2(xi + 1, yi)
    c, d = _h2(xi, yi + 1), _h2(xi + 1, yi + 1)
    return (a * (1 - u) + b * u) * (1 - v) + (c * (1 - u) + d * u) * v

def elevation(col, row, cx, cy, start=24.0, full=42.0):
    d = math.hypot(col - cx, row - cy)
    if d <= start:
        return 0
    ramp = min(1.0, (d - start) / (full - start))
    ridge = 0.45 + 0.55 * vnoise(col * 0.16, row * 0.16)
    peak = 0.55 + 0.75 * vnoise(col * 0.24 + 10, row * 0.24 + 10)
    return int(ramp * (3 + 10 * ridge) * peak * 0.9)
```

- [ ] **Step 4: Run tests** — expect `ok`.
- [ ] **Step 5: Checkpoint** — `git add -A && git status`.

---

## Task 3: voxel_terrain — drawing primitives + material_at

**Files:**
- Modify: `energy_grid_game/ui/voxel_terrain.py`
- Test: `energy_grid_game/test_voxel_terrain.py`

**Interfaces:**
- Produces:
  - `VOX_DEPTH = 3`
  - `slab(surf, sx, sy, top, depth=VOX_DEPTH, jit=1.0)` — draws a thin voxel ground tile whose top diamond's top corner is at `(sx+TW//2, sy)` (matching `iso_city.diamond(sx, sy)` convention).
  - `column(surf, sx, sy, height, top, cap=None, jit=1.0)` — a block rising `height` px above the tile, optional different cap colour (for snow).
  - `material_at(col, row)->str` — deterministic countryside classifier returning "field" | "grass" | "tree" (river handled by caller). Uses parcel clustering like the existing `_woodland`/`FIELDS`.
- Consumes: `TW, TH` (module import).

- [ ] **Step 1: Write the failing test**

```python
# add to test_voxel_terrain.py
import pygame

def test_slab_draws_within_bounds():
    pygame.init()
    surf = pygame.Surface((40, 40), pygame.SRCALPHA)
    vt.slab(surf, 4, 4, (100, 150, 74))
    assert surf.get_bounding_rect().width > 0    # something was drawn

def test_material_at_is_deterministic_and_valid():
    for col, row in ((0, 0), (7, 3), (30, 12)):
        m = vt.material_at(col, row)
        assert m in ("field", "grass", "tree")
        assert vt.material_at(col, row) == m     # stable
```

- [ ] **Step 2: Run to verify fail** — `AttributeError: 'slab'`.

- [ ] **Step 3: Implement**

```python
# add to voxel_terrain.py
VOX_DEPTH = 3
FIELD_SIZE = 6
WOOD_SIZE = 8

def _shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)

def _diamond_pts(sx, sy):
    # matches iso_city.diamond(sx, sy)
    return ((sx + TW // 2, sy), (sx + TW, sy + TH // 2),
            (sx + TW // 2, sy + TH), (sx, sy + TH // 2))

def slab(surf, sx, sy, top, depth=VOX_DEPTH, jit=1.0):
    import pygame
    top = _shade(top, jit)
    T, R, B, L = _diamond_pts(sx, sy)
    Ld, Bd, Rd = (L[0], L[1] + depth), (B[0], B[1] + depth), (R[0], R[1] + depth)
    pygame.draw.polygon(surf, _shade(top, 0.72), [L, B, Bd, Ld])   # left face
    pygame.draw.polygon(surf, _shade(top, 0.55), [B, R, Rd, Bd])   # right face
    pygame.draw.polygon(surf, top, [T, R, B, L])                   # top

def column(surf, sx, sy, height, top, cap=None, jit=1.0):
    import pygame
    top = _shade(top, jit)
    T, R, B, L = _diamond_pts(sx, sy)
    up = (0, -height)
    Tu, Ru, Bu, Lu = ((T[0]+up[0],T[1]+up[1]),(R[0]+up[0],R[1]+up[1]),
                      (B[0]+up[0],B[1]+up[1]),(L[0]+up[0],L[1]+up[1]))
    pygame.draw.polygon(surf, _shade(top, 0.68), [Lu, Bu, B, L])   # left
    pygame.draw.polygon(surf, _shade(top, 0.50), [Bu, Ru, R, B])   # right
    pygame.draw.polygon(surf, _shade(cap or top, 1.0), [Tu, Ru, Bu, Lu])  # top

def material_at(col, row):
    cell = (_h2(col // WOOD_SIZE, row // WOOD_SIZE) * 100)
    if cell < 9:
        return "tree"
    fk = (col // FIELD_SIZE, row // FIELD_SIZE)
    return "field" if (_h2(fk[0], fk[1]) * 3) < 1 else "grass"
```

- [ ] **Step 4: Run tests** — expect `ok`.
- [ ] **Step 5: Checkpoint** — `git add -A && git status`.

---

## Task 4: Restore countryside in `_layout` (fixes the regression)

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py` — `_layout` (the tile-population section ~1735–1799) and remove the dead farm/grass/tree filter (~1760–1764).
- Verify: `tools/capture_moments.py` (frame `06_game.png`).

**Interfaces:**
- Consumes: `voxel_terrain.material_at`, `elevation`; the already-present `river_v(u)` closure and `self._extent`, `u_max`, `v_max` in `_layout`.
- Produces: `self._tiles` now contains countryside tiles again, tagged `("farm"|"grass"|"tree"|"water", None)` and mountain tiles `("mountain", elev_px)`.

- [ ] **Step 1: Add import** at top of `iso_city.py` with the other `ui` imports:

```python
from ui import voxel_terrain as vt
```

- [ ] **Step 2: Replace the dead filter** (lines ~1760–1764) with countryside + mountain fill. Find:

```python
        if self._urban_layout is not None:
            tiles = {
                pos: tile for pos, tile in tiles.items()
                if tile[0] not in ("farm", "grass", "tree")
            }
```

Replace with:

```python
        # Restore the countryside the road-network layout stopped generating, and
        # tag edge mountains. Fills the viewport so the city never floats on void.
        w, h = required_world_size(rect) if rect.width < 50 else (rect.width, rect.height)
        ox, oy = w // 2, int(h * 0.56)
        cx, cy = 0.0, 0.0                     # city is centred on tile (0,0) in iso space
        span = int(w / TW) + 4
        for col in range(-span, span):
            for row in range(-span, span):
                pos = (col, row)
                if pos in tiles:
                    continue
                sx, sy = iso_xy(col, row)
                sx += ox; sy += oy
                if not (-TW * 3 < sx < w + TW * 3 and -400 < sy < h + TH * 3):
                    continue
                elev = vt.elevation(col, row, cx, cy)
                if elev > 0:
                    tiles[pos] = ("mountain", elev)
                    continue
                u = col - row
                if abs((col + row) - river_v(u)) < 2.4:
                    tiles[pos] = ("water", None)
                else:
                    tiles[pos] = (vt.material_at(col, row), None)
```

> Note: in `_layout`, `rect` is the world rect; `required_world_size` is already imported/defined in this module. If `rect` is already the world rect (width >= 50) the guard above uses it directly.

- [ ] **Step 3: Verify it renders the map back**

Run: `.venv39/Scripts/python.exe tools/capture_moments.py voxel_check`
Then open `voxel_check/06_game.png`. Expected: countryside (fields/grass/woodland/river) fills the frame; the city is no longer floating on black. (Ground is still drawn flat here — voxel thickness comes in Task 5.)

- [ ] **Step 4: Run existing model tests to see what moved**

Run: `.venv39/Scripts/python.exe -c "import sys; sys.path.insert(0,'energy_grid_game'); import test_city_model"` (or the repo's test runner). Note which assertions now fail (expected: greenery/countryside counts). Do NOT fix them yet — Task 9 owns test updates.

- [ ] **Step 5: Checkpoint** — `git add -A && git status`.

---

## Task 5: Draw ground as voxel slabs + mountains in `_bake`

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py` — `_bake` ground drawing (~2148–2160) and add a `mountain` branch; thread the season palette in.
- Verify: capture harness.

**Interfaces:**
- Consumes: `voxel_terrain.slab`, `column`, `palette`, `season_of`; `self._bake_season` (set in Task 7, default "summer" until then).
- Produces: voxel-thickened ground + snow-capped edge mountains in the day and night layers.

- [ ] **Step 1: Add a palette lookup near the top of `_bake`** (after `srng = random.Random(4242)`):

```python
        season = getattr(self, "_bake_season", "summer")
        pal = vt.palette(season)
        def _mat_color(mat):
            return {"farm": pal["field"], "grass": pal["grass"], "park": pal["grass"],
                    "tree": pal["grass"], "mountain": pal["rock"]}.get(mat, pal["grass"])
```

- [ ] **Step 2: Replace the flat ground fill** (the block around lines 2148–2160 that does `if kind == "farm": ... pygame.draw.polygon(day, c, d)`). Find the existing farm/park/grass/tree section and replace its drawing with slab calls + a mountain branch. New code:

```python
            if kind == "mountain":
                elev_px = extra
                jit = 0.9 + 0.2 * srng.random()
                snowy = elev_px >= 9
                cap = pal["snow"] if snowy else None
                vt.column(day, sx, sy, elev_px * 2 + vt.VOX_DEPTH, pal["rock"], cap=cap, jit=jit)
                vt.column(night, sx, sy, elev_px * 2 + vt.VOX_DEPTH,
                          shade(pal["rock"], 0.34), cap=shade(cap or pal["rock"], 0.34), jit=jit)
                continue

            if kind == "farm":
                fk = (col // FIELD_SIZE, row // FIELD_SIZE)
                base = pal["field"]
            elif kind == "tree":
                base = pal["grass"]
            else:
                base = pal["park"] if kind == "park" else pal["grass"]
            jit = 0.9 + 0.2 * srng.random()
            vt.slab(day, sx, sy, base, jit=jit)
            vt.slab(night, sx, sy, shade(base, 0.22), jit=jit)

            if kind in ("tree", "park") and (kind == "tree" or srng.random() < 0.55):
                spr, _ = tree(srng)
                self._blit_pair(day, night, spr, sx, sy)
                continue
            if kind != "bldg":
                continue
```

> This replaces the previous `if kind == "farm": c = FIELDS[...]` / `else: c = srng.choice(...)` / `pygame.draw.polygon` lines. Keep the subsequent `bldg` sprite drawing untouched (buildings stay as-is for now).

- [ ] **Step 3: Verify voxel ground + mountains**

Run: `.venv39/Scripts/python.exe tools/capture_moments.py voxel_check` → open `voxel_check/06_game.png`.
Expected: ground tiles have subtle voxel thickness; snow-capped mountains ring the frame; city sits in a filled landscape.

- [ ] **Step 4: Verify night layer** — open `voxel_check/16_region_night.png` (or `10_*`): terrain dims, mountains dark, window lights persist.
- [ ] **Step 5: Checkpoint** — `git add -A && git status`.

---

## Task 6: Compact city-hero composition (pull plants in)

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py` — `_place_plants` ring (line ~1877).
- Test: `energy_grid_game/test_city_model.py` (new assertion) + capture.

**Interfaces:**
- Produces: plants placed at a tighter ring so transmission runs are short and the city dominates.

- [ ] **Step 1: Write the failing test** (add to `test_city_model.py`):

```python
def test_plants_hug_city_edge():
    layout = None
    from ui.iso_city import IsoCity
    import pygame; pygame.init()
    city = IsoCity(pygame.font.SysFont("consolas", 12), pygame.font.SysFont("consolas", 14))
    rect = pygame.Rect(0, 0, 1365, 900)
    from game_state import GameState
    import scenarios
    st = GameState(scenarios.make_standard())
    city.prepare(rect, st)
    # every plant should sit within a compact radius of the world centre
    ox, oy = city._origin
    import math
    for site in city._plants:
        d = math.hypot(site.sx, site.sy)      # sx,sy are relative to origin
        assert d < 420, (site.key, d)
```

- [ ] **Step 2: Run to verify fail** — plants currently ring wider; expect AssertionError with a large `d`.

- [ ] **Step 3: Tighten the ring.** Find (line ~1877):

```python
                ring = max(self._extent * _edge_wobble(a) * 1.18 + 0.05, 0.82)
```

Replace with:

```python
                ring = max(self._extent * _edge_wobble(a) * 1.04 + 0.02, 0.52)
```

And the hydro walk (line ~1860) `r = max(self._extent * 1.45, 0.48)` → `r = max(self._extent * 1.12, 0.40)`.

- [ ] **Step 4: Run test to verify pass**, then capture `voxel_check/06_game.png` — plants now hug the city; corridors short.
- [ ] **Step 5: Checkpoint** — `git add -A && git status`.

---

## Task 7: Season wired to bake + season-boundary re-bake trigger

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py` — `prepare()` (find where it decides whether to rebuild the bake) and `_bake` (set `self._bake_season`).
- Test: `test_city_model.py`.

**Interfaces:**
- Consumes: `state.date.month`, `voxel_terrain.season_of`, `should_rebake_for_season`.
- Produces: bake uses the current season palette; a season change forces exactly one rebuild.

- [ ] **Step 1: In `_bake`, set the season it baked with.** At the start of `_bake` (after computing `season`):

```python
        self._bake_season = season
```

Change the earlier `season = getattr(self, "_bake_season", "summer")` line in Task 5 to derive from state instead:

```python
        season = vt.season_of(getattr(getattr(self, "_bake_state", None), "date", _NOW).month) \
            if getattr(self, "_bake_state", None) else "summer"
```

Simpler and explicit: have `prepare(rect, state)` stash `self._pending_season = vt.season_of(state.date.month)` and read that in `_bake`:

```python
        season = getattr(self, "_pending_season", "summer")
        self._bake_season = season
        pal = vt.palette(season)
```

- [ ] **Step 2: Add the trigger in `prepare()`.** Locate the guard that decides whether to call `_bake` (it already rebuilds on resize/fleet/pop change). Add season to it. Near the top of `prepare`:

```python
        pending_season = vt.season_of(state.date.month)
        season_changed = vt.should_rebake_for_season(getattr(self, "_bake_season", None), pending_season)
        self._pending_season = pending_season
```

Then include `or season_changed` in the existing `if <needs rebuild>:` condition that calls `_bake`.

- [ ] **Step 3: Write the test** (add to `test_city_model.py`):

```python
def test_season_change_triggers_one_rebake(monkeypatch=None):
    import pygame, datetime; pygame.init()
    from ui.iso_city import IsoCity
    from game_state import GameState
    import scenarios
    city = IsoCity(pygame.font.SysFont("consolas", 12), pygame.font.SysFont("consolas", 14))
    rect = pygame.Rect(0, 0, 1365, 900)
    st = GameState(scenarios.make_standard())
    st.date = datetime.date(2026, 7, 15)     # summer
    city.prepare(rect, st)
    assert city._bake_season == "summer"
    st.date = datetime.date(2026, 1, 15)     # winter
    city.prepare(rect, st)
    assert city._bake_season == "winter"
```

- [ ] **Step 4: Run test** — expect pass. Capture a winter frame: temporarily set `st.date` to January in a scratch script and render; confirm snowy ground.
- [ ] **Step 5: Checkpoint** — `git add -A && git status`.

---

## Task 8: Tame transmission (fewer, bolder towers)

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py` — the transmission bake loop (~2205–2225) and `_pylon` (~995) or its call.
- Verify: capture.

**Interfaces:**
- Produces: sparse, bold towers; conductor lines carry the corridors.

- [ ] **Step 1: Thin the towers.** In `_bake`'s transmission section, the loop places a `_pylon` at every interpolated tower (`towers = [...]`, spacing `span/46`). Change the pylon placement so a tower is drawn only at segment ends (bends) plus every Nth interpolated point. Find:

```python
                for tx, ty in towers[1 if first else 0:]:
                    _pylon(grid, int(tx), int(ty))
```

Replace with:

```python
                pts = towers[1 if first else 0:]
                for i, (tx, ty) in enumerate(pts):
                    at_bend = (i == 0 or i == len(pts) - 1)
                    if at_bend or (i % 4 == 0):        # bends + occasional
                        _pylon(grid, int(tx), int(ty), h=22)   # bigger, bolder
```

- [ ] **Step 2: Increase tower spacing** so lines dominate. Change `n = max(1, int(span / 46.0))` (line ~2210) to `n = max(1, int(span / 46.0))` unchanged for line smoothness, but the pylon thinning above is what reduces density. Optionally brighten the conductor: in `_span` (~1033) bump `CONDUCTOR` usage — leave as-is unless the capture reads too dim.

- [ ] **Step 3: Verify** `voxel_check/06_game.png` — few bold towers, clean conductor lines, no lattice wall.
- [ ] **Step 4: Confirm electron flows still ride the wire** (pulses reach substations) — the `conductor_paths`/`Flow` construction is unchanged; visually confirm pulses animate along the lines in a short scripted render or trust unchanged logic.
- [ ] **Step 5: Checkpoint** — `git add -A && git status`.

---

## Task 9: Update existing tests + final verification pass

**Files:**
- Modify: `energy_grid_game/test_city_model.py` — assertions that intentionally changed.
- Verify: full capture harness.

- [ ] **Step 1: Run the full model test module** and list every failure:

Run: `.venv39/Scripts/python.exe -c "import sys; sys.path.insert(0,'energy_grid_game'); import test_city_model as t; import traceback; [(_run(t,n)) for n in dir(t) if n.startswith('test_')]"` where `_run` calls and catches. (Or use the repo's normal test command if one exists — check `README`/CI.)

- [ ] **Step 2: For each failure, decide** intended-change vs real-regression. Expected intended changes: countryside/greenery counts (`test_urban_layout_is_road_first_and_low_greenery`, `test_urban_layout_places_...`), plant ring distances, transmission density. Update those assertions to the new expected values (read the new values from a debug print, then assert them). Do NOT loosen a test to "always pass" — assert the new concrete numbers.

- [ ] **Step 3: Keep deterministic/geometry tests green** — `test_urban_layout_selection_is_deterministic_for_its_seed`, road-network tests, capacity/monotonicity tests must still pass unchanged. If one breaks, it's a real regression — fix the code, not the test.

- [ ] **Step 4: Full visual pass** — `.venv39/Scripts/python.exe tools/capture_moments.py final_check` and inspect `06_game` (day), night, plus a scripted winter and a fall frame. Confirm: filled frame, mountains, voxel ground, compact plants, tamed transmission, seasons, working plant animation.

- [ ] **Step 5: Checkpoint** — `git add -A && git status`. (Do not commit; report the staged diff to the user.)

---

## Self-Review (completed by plan author)

- **Spec coverage:** terrain restore (T4), voxel ground (T5), mountains (T4 tag + T5 draw), compact composition (T6), seasons+time-of-day reuse (T5 palette + T7 trigger; time-of-day rides existing `daylight()` cross-fade — no new task needed), tamed transmission (T8), module extraction (T1–T3), tests (T1–T3 unit, T9 integration). All spec sections mapped.
- **Placeholder scan:** every code step contains concrete code; test steps contain real assertions; commands are exact. Season derivation in T7 is spelled out (the simpler `_pending_season` variant is the one to implement).
- **Type consistency:** `season_of`→str, `palette`→dict, `slab/column` signatures, `elevation`→int, `material_at`→str are used consistently across T4/T5/T7. `self._bake_season` / `self._pending_season` names consistent between T5 and T7.
- **Known ambiguity resolved:** in T7 use the `_pending_season` variant (ignore the `_NOW`/`_bake_state` sketch above it).
