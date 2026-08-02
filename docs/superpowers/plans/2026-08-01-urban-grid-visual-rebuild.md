# Urban Grid Visual Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the isometric game view so it reads as a real urban grid with city-edge utility campuses, varied city blocks, road-first composition, and minimal rural filler.

**Architecture:** Extend the current curated iso asset pipeline, then introduce a small urban layout/model layer that generates deterministic districts, roads, blocks, civic anchors, utility campuses, and sparse intentional greenery. Adapt `IsoCity` to bake composed urban blocks and city-edge plant campuses while preserving existing plant controls, flow pulses, congestion, pricing, demand, and source behavior.

**Tech Stack:** Python 3.12 runtime for local verification, Pygame 2.6.1, stdlib `json`/`pathlib`/`dataclasses`/`random`, existing headless test files and capture harness.

## Global Constraints

- Work locally only. Do not run git commands.
- No changes to power simulation, congestion math, pricing, scoring, source ramping, line capacity, or demand curves.
- No rural biome polish. Forest, farmland, and grass filler should be removed from the primary gameplay composition.
- No visual approach that requires thousands of individual buildings or trees to make the city look full.
- No fully dynamic road simulation. Roads are visual/gameplay structure, not a new traffic-management system.
- Use approved source/reference assets:
  `C:/Users/sycho/Downloads/municipal buildings.png`,
  `C:/Users/sycho/Downloads/hjm-iso-houses.png`,
  `C:/Users/sycho/Downloads/spr_road_2_strip29.png`,
  `C:/Users/sycho/Downloads/spr_roads_1_strip15.png`,
  `C:/Users/sycho/Downloads/gui.png`,
  `C:/Users/sycho/Downloads/1x1x1.png`,
  `C:/Users/sycho/Downloads/1x1x2.png`,
  `C:/Users/sycho/Downloads/2x2x2.png`,
  `C:/Users/sycho/Downloads/citycenters.png`,
  `C:/Users/sycho/Downloads/buildings.png`.
- Keep Pygame asset loading lazy; do not call `convert_alpha()` at import time outside functions/scripts with an initialized display.
- Keep plant controls attached to plant visual centers and transmission routes attached to switchyard/substation anchors.
- Use local verification checkpoints instead of commits.

---

## File Structure

- Modify `tools/slice_iso_assets.py`: add the five new sources, road component curation, municipal fixed-rectangle crops with white-background alpha cleanup, and expanded manifest families.
- Modify `assets/iso/**`: regenerated curated assets under `roads/`, `municipal/`, `details/`, and updated `manifest.json`/`README.txt`.
- Modify `energy_grid_game/ui/assets.py`: add lazy helpers for `roads`, `municipal`, `details`, and semantic manifest families.
- Create `energy_grid_game/ui/urban_blocks.py`: deterministic urban layout data structures and pure functions for roads, districts, block archetypes, utility campuses, and greenery classification.
- Create `energy_grid_game/ui/urban_render.py`: drawing helpers for road tiles, composed block surfaces, paved lots, sidewalks, street details, parks, and municipal anchors.
- Modify `energy_grid_game/ui/iso_city.py`: replace terrain-first layout/bake paths with urban block model output while retaining `PlantSite`, camera, marker, flow, live plant, outage, fire, and HUD integration contracts.
- Modify `energy_grid_game/test_city_model.py`: add tests for manifest families, road grid continuity, low greenery ratio, block variety, utility campus context, performance caps, plant marker alignment, and no simulation regressions.
- Keep verification artifacts in `captures/modern_retro_iso_art/` unless a later task creates `captures/urban_grid_visual_rebuild/`.

---

### Task 1: Expand the Iso Asset Manifest for Urban Sources

**Files:**
- Modify: `tools/slice_iso_assets.py`
- Modify generated: `assets/iso/source/*.png`
- Create generated: `assets/iso/roads/*.png`
- Create generated: `assets/iso/municipal/*.png`
- Create generated: `assets/iso/details/*.png`
- Modify generated: `assets/iso/manifest.json`
- Modify generated: `assets/iso/README.txt`
- Test: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: approved source paths from Global Constraints.
- Produces: manifest top-level keys `buildings`, `city_center`, `plants`, `roads`, `municipal`, `details`, and `block_palettes`.
- Produces helper-visible entries with this shape:

```python
{
    "file": "roads/road_straight_ne_01.png",
    "size": [46, 24],
    "alpha_bounds": [0, 0, 46, 24],
    "base": [23, 20],
    "tags": ["road", "straight", "ne"],
}
```

- [ ] **Step 1: Write failing manifest-family test**

Add this test to `energy_grid_game/test_city_model.py` near `test_iso_manifest_exposes_buildings_plants_and_city_center`:

```python
def test_urban_iso_manifest_exposes_roads_municipal_and_details():
    manifest = assets.iso_manifest()
    assert {"roads", "municipal", "details", "block_palettes"} <= set(manifest)
    assert {"straight_ne", "straight_nw", "cross", "tee_ne", "corner_ne"} <= set(manifest["roads"])
    assert {"police_station", "hospital", "fire_station", "school"} <= set(manifest["municipal"])
    assert {"pavement", "parking", "street_tree", "service_yard"} <= set(manifest["details"])
    for family in ("roads", "municipal", "details"):
        for entries in manifest[family].values():
            if isinstance(entries, dict):
                entries = [entries]
            assert entries
            for entry in entries:
                sprite = assets.iso_sprite(entry["file"])
                assert sprite.get_bounding_rect().width > 0
                assert sprite.get_bounding_rect().height > 0
```

- [ ] **Step 2: Run the failing manifest-family test**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import test_city_model as t; t.test_urban_iso_manifest_exposes_roads_municipal_and_details()"
```

Expected: fail because the current manifest lacks `roads`, `municipal`, `details`, or `block_palettes`.

- [ ] **Step 3: Add new source paths and expected sizes**

In `tools/slice_iso_assets.py`, extend `SOURCES` and `EXPECTED_SIZES`:

```python
SOURCES.update({
    "municipal": Path("C:/Users/sycho/Downloads/municipal buildings.png"),
    "hjm_iso_houses": Path("C:/Users/sycho/Downloads/hjm-iso-houses.png"),
    "road_2": Path("C:/Users/sycho/Downloads/spr_road_2_strip29.png"),
    "roads_1": Path("C:/Users/sycho/Downloads/spr_roads_1_strip15.png"),
    "gui": Path("C:/Users/sycho/Downloads/gui.png"),
})

EXPECTED_SIZES.update({
    "municipal": (316, 226),
    "hjm_iso_houses": (768, 400),
    "road_2": (320, 192),
    "roads_1": (192, 160),
    "gui": (650, 200),
})
```

- [ ] **Step 4: Add output directories**

Update `ensure_dirs()`:

```python
for rel in ("source", "buildings", "city_center", "plants", "roads", "municipal", "details"):
    (OUT / rel).mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 5: Add fixed crop support for white-background sheets**

Add these helpers below `tight_crop()`:

```python
def whitened_to_alpha(sprite: pygame.Surface, tolerance: int = 8) -> pygame.Surface:
    out = sprite.convert_alpha()
    for y in range(out.get_height()):
        for x in range(out.get_width()):
            r, g, b, a = out.get_at((x, y))
            if a and r >= 255 - tolerance and g >= 255 - tolerance and b >= 255 - tolerance:
                out.set_at((x, y), (255, 255, 255, 0))
    bounds = out.get_bounding_rect()
    if bounds.width <= 0 or bounds.height <= 0:
        raise ValueError("fixed crop produced empty alpha bounds")
    return out.subsurface(bounds).copy()


def save_fixed_crop(sheet: pygame.Surface, rect_tuple: tuple[int, int, int, int], relpath: str) -> dict:
    target = OUT / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    sprite = whitened_to_alpha(sheet.subsurface(pygame.Rect(*rect_tuple)).copy())
    pygame.image.save(sprite, str(target))
    bounds = sprite.get_bounding_rect()
    return {
        "file": relpath.replace("\\", "/"),
        "size": [sprite.get_width(), sprite.get_height()],
        "alpha_bounds": [bounds.x, bounds.y, bounds.w, bounds.h],
    }
```

- [ ] **Step 6: Add concrete curation maps**

Add these constants after `CURATION`:

```python
ROAD_CURATION = {
    "roads_1": {
        "straight_ne": 0,
        "straight_nw": 1,
        "corner_ne": 2,
        "corner_nw": 3,
        "tee_ne": 6,
        "tee_nw": 7,
        "cross": 10,
    },
    "road_2": {
        "avenue_ne": 6,
        "avenue_nw": 7,
        "avenue_cross": 10,
        "avenue_tee_ne": 5,
        "avenue_corner_ne": 9,
    },
}

MUNICIPAL_CROPS = {
    "police_station": ("municipal", (10, 22, 60, 42), ["civic", "police"]),
    "hospital": ("municipal", (88, 21, 62, 45), ["civic", "medical"]),
    "fire_station": ("municipal", (168, 22, 50, 44), ["civic", "fire"]),
    "school": ("municipal", (246, 22, 60, 44), ["civic", "school"]),
    "clinic": ("municipal", (96, 80, 42, 34), ["civic", "medical"]),
    "small_fire_station": ("municipal", (174, 78, 42, 38), ["civic", "fire"]),
    "schoolhouse": ("municipal", (254, 80, 50, 36), ["civic", "school"]),
    "industrial_unit": ("municipal", (88, 139, 60, 36), ["industrial"]),
    "storage_inc": ("municipal", (94, 178, 38, 42), ["industrial", "utility"]),
    "graveyard": ("municipal", (250, 174, 54, 35), ["civic", "green"]),
}

DETAIL_CROPS = {
    "pavement": ("gui", (195, 112, 24, 24), ["paved"]),
    "parking": ("gui", (222, 112, 24, 24), ["paved", "parking"]),
    "service_yard": ("gui", (276, 112, 24, 24), ["paved", "utility"]),
    "street_tree": ("buildings", (4, 3, 28, 20), ["green", "street_tree"]),
}
```

- [ ] **Step 7: Extend `build_manifest()`**

Inside `build_manifest()`, initialize:

```python
manifest = {
    "buildings": {},
    "city_center": [],
    "plants": {},
    "roads": {},
    "municipal": {},
    "details": {},
    "block_palettes": {},
}
```

After plants are added, append:

```python
for sheet_name, roles in ROAD_CURATION.items():
    for role, index in roles.items():
        component = pick(component_map, sheet_name, index, f"road:{role}")
        entry = save_crop(sheets[sheet_name], component, f"roads/{role}_01.png", pad=0)
        entry["base"] = [entry["size"][0] // 2, max(1, entry["size"][1] - 4)]
        entry["tags"] = ["road"] + role.split("_")
        manifest["roads"][role] = [entry]

for role, (sheet_name, rect, tags) in MUNICIPAL_CROPS.items():
    entry = save_fixed_crop(sheets[sheet_name], rect, f"municipal/{role}_01.png")
    entry["base"] = base_for(entry)
    entry["footprint"] = [2, 2]
    entry["tags"] = tags
    manifest["municipal"][role] = [entry]

for role, (sheet_name, rect, tags) in DETAIL_CROPS.items():
    entry = save_fixed_crop(sheets[sheet_name], rect, f"details/{role}_01.png")
    entry["base"] = base_for(entry)
    entry["tags"] = tags
    manifest["details"][role] = [entry]

manifest["block_palettes"] = {
    "core": ["tower", "midrise", "shop"],
    "mixed": ["midrise", "block", "shop", "house"],
    "residential": ["house", "shop", "block"],
    "civic": ["municipal", "midrise", "shop"],
    "industrial": ["municipal", "block", "shop"],
    "utility": ["plants", "municipal", "details"],
}
```

- [ ] **Step 8: Update README output**

Change `write_readme()` text so it lists all ten source sheets and explains that municipal/houses/gui may be curated from fixed rectangles while road sheets are component-sliced.

- [ ] **Step 9: Regenerate assets**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'tools\slice_iso_assets.py'
```

Expected: command exits `0`, `assets/iso/manifest.json` includes the new families.

- [ ] **Step 10: Run manifest-family test**

Run the command from Step 2 again.

Expected: pass.

- [ ] **Step 11: Local checkpoint**

Do not stage or commit. Record in the task notes that Task 1 completed locally and list regenerated directories.

---

### Task 2: Add Lazy Asset Loader Helpers for Urban Families

**Files:**
- Modify: `energy_grid_game/ui/assets.py`
- Test: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: manifest keys produced by Task 1.
- Produces:
  - `iso_road_entries(role: str) -> list[dict]`
  - `iso_municipal_entries(role: str) -> list[dict]`
  - `iso_detail_entries(role: str) -> list[dict]`
  - `iso_block_palette(role: str) -> list[str]`

- [ ] **Step 1: Write failing loader helper test**

Add near the manifest tests:

```python
def test_urban_asset_helpers_return_manifest_families():
    road = assets.iso_road_entries("cross")[0]
    civic = assets.iso_municipal_entries("hospital")[0]
    detail = assets.iso_detail_entries("parking")[0]
    palette = assets.iso_block_palette("mixed")

    assert road["file"].startswith("roads/")
    assert civic["file"].startswith("municipal/")
    assert detail["file"].startswith("details/")
    assert "shop" in palette

    for entry in (road, civic, detail):
        sprite = assets.iso_sprite(entry["file"])
        assert sprite.get_masks()[3] != 0
```

- [ ] **Step 2: Run the failing loader helper test**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import test_city_model as t; t.test_urban_asset_helpers_return_manifest_families()"
```

Expected: fail with `AttributeError` for the new helpers.

- [ ] **Step 3: Implement helper functions**

Append to `energy_grid_game/ui/assets.py`:

```python
def _iso_family_entries(family: str, role: str) -> list:
    items = iso_manifest().get(family, {}).get(role, ())
    if isinstance(items, dict):
        items = [items]
    if not items:
        raise KeyError(f"missing iso {family} role: {role}")
    return items


def iso_road_entries(role: str) -> list:
    return _iso_family_entries("roads", role)


def iso_municipal_entries(role: str) -> list:
    return _iso_family_entries("municipal", role)


def iso_detail_entries(role: str) -> list:
    return _iso_family_entries("details", role)


def iso_block_palette(role: str) -> list:
    palette = iso_manifest().get("block_palettes", {}).get(role, ())
    if not palette:
        raise KeyError(f"missing iso block palette: {role}")
    return list(palette)
```

- [ ] **Step 4: Run loader helper test**

Run the command from Step 2 again.

Expected: pass.

- [ ] **Step 5: Local checkpoint**

Do not stage or commit. Note that loader helpers are available for renderer tasks.

---

### Task 3: Add Pure Urban Layout Model

**Files:**
- Create: `energy_grid_game/ui/urban_blocks.py`
- Test: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: viewport `pygame.Rect`, fleet key iterable, deterministic seed.
- Produces:
  - `UrbanBlock(col: int, row: int, district: str, archetype: str, variant: int, greenery: float, buildings: tuple[str, ...])`
  - `UrbanRoad(col: int, row: int, role: str, avenue: bool)`
  - `UrbanCampus(key: str, col: float, row: float, district: str, radius: int)`
  - `UrbanLayout(blocks: list[UrbanBlock], roads: dict[tuple[int, int], UrbanRoad], campuses: dict[str, UrbanCampus], civic: dict[tuple[int, int], str], green_tiles: set[tuple[int, int]], buildable_tiles: set[tuple[int, int]])`
  - `build_urban_layout(rect: pygame.Rect, fleet: tuple[str, ...], seed: int = 20260801) -> UrbanLayout`

- [ ] **Step 1: Write failing urban layout test**

Add imports:

```python
from ui.urban_blocks import build_urban_layout
```

Add tests:

```python
def test_urban_layout_is_road_first_and_low_greenery():
    layout = build_urban_layout(pygame.Rect(0, 0, 1365, 900),
                                ("nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro"))
    assert len(layout.roads) > len(layout.green_tiles) * 6
    assert len(layout.blocks) >= 90
    assert len(layout.blocks) <= 220
    assert len(layout.green_tiles) <= max(12, len(layout.blocks) // 8)
    assert {"core", "mixed", "civic", "industrial", "utility"} <= {
        block.district for block in layout.blocks
    }


def test_urban_layout_places_all_generators_in_city_edge_campuses():
    fleet = ("nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro")
    layout = build_urban_layout(pygame.Rect(0, 0, 1365, 900), fleet)
    assert set(layout.campuses) == set(fleet)
    for key, campus in layout.campuses.items():
        assert campus.district == "utility"
        assert campus.radius >= 2
        nearby_road_count = sum(
            1 for pos in layout.roads
            if abs(pos[0] - round(campus.col)) + abs(pos[1] - round(campus.row)) <= 5
        )
        assert nearby_road_count >= 3, (key, nearby_road_count)
```

- [ ] **Step 2: Run failing layout tests**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import test_city_model as t; t.test_urban_layout_is_road_first_and_low_greenery(); t.test_urban_layout_places_all_generators_in_city_edge_campuses()"
```

Expected: fail with `ModuleNotFoundError` or missing `build_urban_layout`.

- [ ] **Step 3: Implement dataclasses**

Create `energy_grid_game/ui/urban_blocks.py`:

```python
"""Deterministic city-block layout model for the isometric renderer."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pygame

ROAD_SPACING = 4
AVENUE_SPACING = 12


@dataclass(frozen=True)
class UrbanBlock:
    col: int
    row: int
    district: str
    archetype: str
    variant: int
    greenery: float
    buildings: tuple[str, ...]


@dataclass(frozen=True)
class UrbanRoad:
    col: int
    row: int
    role: str
    avenue: bool


@dataclass(frozen=True)
class UrbanCampus:
    key: str
    col: float
    row: float
    district: str
    radius: int


@dataclass(frozen=True)
class UrbanLayout:
    blocks: list[UrbanBlock]
    roads: dict[tuple[int, int], UrbanRoad]
    campuses: dict[str, UrbanCampus]
    civic: dict[tuple[int, int], str]
    green_tiles: set[tuple[int, int]]
    buildable_tiles: set[tuple[int, int]]
```

- [ ] **Step 4: Implement district and road helpers**

Add:

```python
def _district(e: float, angle: float) -> str:
    if e < 0.22:
        return "core"
    if e < 0.43:
        return "mixed"
    if 1.85 < angle < 2.75:
        return "civic"
    if e > 0.62:
        return "utility"
    if angle < -0.25 or angle > 2.85:
        return "industrial"
    return "mixed"


def _road_role(col: int, row: int) -> str:
    on_col = col % ROAD_SPACING == 0
    on_row = row % ROAD_SPACING == 0
    if on_col and on_row:
        return "cross"
    if on_col:
        return "straight_nw"
    if on_row:
        return "straight_ne"
    return ""
```

- [ ] **Step 5: Implement campus placement**

Add:

```python
def _campuses(fleet: tuple[str, ...], u_max: float, v_max: float) -> dict[str, UrbanCampus]:
    angles = {
        "nuclear": math.radians(205),
        "coal": math.radians(155),
        "hydro": math.radians(188),
        "wind": math.radians(112),
        "solar": math.radians(64),
        "peaker": math.radians(24),
        "gas": math.radians(-28),
        "generic": math.radians(24),
    }
    campuses = {}
    for key in fleet:
        angle = angles.get(key, math.radians(24))
        ring = 0.76
        u = u_max * ring * math.cos(angle)
        v = v_max * ring * math.sin(angle)
        campuses[key] = UrbanCampus(
            key=key,
            col=(u + v) / 2.0,
            row=(v - u) / 2.0,
            district="utility",
            radius=3 if key in ("nuclear", "coal", "hydro") else 2,
        )
    return campuses
```

- [ ] **Step 6: Implement `build_urban_layout()`**

Add:

```python
def build_urban_layout(rect: pygame.Rect, fleet: tuple[str, ...], seed: int = 20260801) -> UrbanLayout:
    rng = random.Random(seed)
    u_max = max(24.0, rect.width * 0.92 / 16)
    v_max = max(18.0, rect.height * 0.64 / 8)
    u_lim = u_max * 0.96
    v_lim = v_max * 0.96
    m = int((u_lim + v_lim) / 2) + 2
    roads: dict[tuple[int, int], UrbanRoad] = {}
    blocks: list[UrbanBlock] = []
    civic: dict[tuple[int, int], str] = {}
    green_tiles: set[tuple[int, int]] = set()
    buildable_tiles: set[tuple[int, int]] = set()
    campuses = _campuses(tuple(fleet), u_max, v_max)

    civic_roles = ("hospital", "police_station", "fire_station", "school", "clinic", "graveyard")
    civic_index = 0

    for col in range(-m, m + 1):
        for row in range(-m, m + 1):
            u, v = col - row, col + row
            if abs(u) > u_lim or abs(v) > v_lim:
                continue
            role = _road_role(col, row)
            if role:
                roads[(col, row)] = UrbanRoad(
                    col=col,
                    row=row,
                    role=role,
                    avenue=(col % AVENUE_SPACING == 0 or row % AVENUE_SPACING == 0),
                )
                continue
            if col % ROAD_SPACING == 1 and row % ROAD_SPACING == 1:
                e = math.hypot(u / u_max, v / v_max)
                if e > 0.92:
                    continue
                angle = math.atan2(v / v_max, u / u_max)
                district = _district(e, angle)
                if district == "utility" and rng.random() < 0.16:
                    green_tiles.add((col, row))
                    continue
                count = 1 + (1 if district in ("core", "mixed") else 0) + (1 if rng.random() < 0.35 else 0)
                palette = {
                    "core": ("tower", "midrise", "shop"),
                    "mixed": ("midrise", "block", "shop", "house"),
                    "civic": ("shop", "midrise"),
                    "industrial": ("block", "shop"),
                    "utility": ("block", "shop"),
                }[district]
                buildings = tuple(palette[(rng.randrange(len(palette)) + i) % len(palette)] for i in range(count))
                archetype = "paved" if district in ("industrial", "utility") else "urban"
                if district == "civic" and civic_index < len(civic_roles):
                    civic[(col, row)] = civic_roles[civic_index]
                    civic_index += 1
                    archetype = "civic"
                blocks.append(UrbanBlock(col, row, district, archetype, rng.randrange(10_000), 0.08, buildings))
                buildable_tiles.add((col, row))

    for campus in campuses.values():
        cc, rr = round(campus.col), round(campus.row)
        for dc in range(-campus.radius - 1, campus.radius + 2):
            roads[(cc + dc, rr - campus.radius - 1)] = UrbanRoad(cc + dc, rr - campus.radius - 1, "straight_ne", True)
            roads[(cc + dc, rr + campus.radius + 1)] = UrbanRoad(cc + dc, rr + campus.radius + 1, "straight_ne", True)
        for dr in range(-campus.radius - 1, campus.radius + 2):
            roads[(cc - campus.radius - 1, rr + dr)] = UrbanRoad(cc - campus.radius - 1, rr + dr, "straight_nw", True)
            roads[(cc + campus.radius + 1, rr + dr)] = UrbanRoad(cc + campus.radius + 1, rr + dr, "straight_nw", True)

    return UrbanLayout(blocks, roads, campuses, civic, green_tiles, buildable_tiles)
```

- [ ] **Step 7: Run layout tests**

Run the command from Step 2 again.

Expected: pass.

- [ ] **Step 8: Local checkpoint**

Do not stage or commit. Note the public dataclasses and `build_urban_layout()` signature.

---

### Task 4: Add Urban Rendering Helpers

**Files:**
- Create: `energy_grid_game/ui/urban_render.py`
- Test: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: `UrbanBlock`, `UrbanRoad`, manifest helpers from `ui.assets`, existing `iso_xy`, `TW`, `TH`, `diamond`, and `shade` concepts.
- Produces:
  - `draw_urban_road(surface: pygame.Surface, x: int, y: int, road: UrbanRoad, night: bool = False) -> None`
  - `draw_urban_block(surface: pygame.Surface, x: int, y: int, block: UrbanBlock, rng: random.Random, night: bool = False) -> list[pygame.Rect]`
  - `draw_utility_campus_base(surface: pygame.Surface, x: int, y: int, radius: int) -> pygame.Rect`

- [ ] **Step 1: Write failing renderer surface tests**

Add:

```python
from ui.urban_blocks import UrbanBlock, UrbanRoad
from ui.urban_render import draw_urban_block, draw_urban_road, draw_utility_campus_base
```

Add tests:

```python
def test_urban_road_draws_paved_iso_tile_not_grass():
    surface = pygame.Surface((120, 80), pygame.SRCALPHA)
    road = UrbanRoad(0, 0, "cross", True)
    draw_urban_road(surface, 50, 30, road)
    bounds = surface.get_bounding_rect()
    assert bounds.width >= 40
    sample = surface.get_at((58, 34))[:3]
    assert sample[0] in range(35, 130)
    assert sample[1] in range(35, 130)
    assert sample[2] in range(35, 130)


def test_urban_block_draws_varied_paved_city_content():
    surface = pygame.Surface((180, 120), pygame.SRCALPHA)
    block = UrbanBlock(0, 0, "mixed", "urban", 17, 0.05, ("house", "shop", "block"))
    rects = draw_urban_block(surface, 70, 40, block, random.Random(4))
    bounds = surface.get_bounding_rect()
    assert len(rects) >= 2
    assert bounds.width >= 40
    assert bounds.height >= 24
    colors = {surface.get_at((x, y))[:3] for x in range(0, 180, 12) for y in range(0, 120, 12) if surface.get_at((x, y)).a}
    assert len(colors) >= 5


def test_utility_campus_base_is_large_paved_not_green():
    surface = pygame.Surface((220, 160), pygame.SRCALPHA)
    bounds = draw_utility_campus_base(surface, 100, 52, 3)
    assert bounds.width >= 80
    assert bounds.height >= 40
    assert surface.get_at(bounds.center).a > 0
```

- [ ] **Step 2: Run failing renderer tests**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import test_city_model as t; t.test_urban_road_draws_paved_iso_tile_not_grass(); t.test_urban_block_draws_varied_paved_city_content(); t.test_utility_campus_base_is_large_paved_not_green()"
```

Expected: fail because `ui.urban_render` does not exist.

- [ ] **Step 3: Implement renderer helpers**

Create `energy_grid_game/ui/urban_render.py`:

```python
"""Drawing helpers for baked urban blocks and roads."""
from __future__ import annotations

import random

import pygame

from ui import assets
from ui.urban_blocks import UrbanBlock, UrbanRoad

TW, TH = 16, 8
ASPHALT = (50, 55, 58)
ASPHALT_LIT = (64, 68, 72)
PAVEMENT = (92, 92, 88)
PAVEMENT_DARK = (64, 66, 68)
LOT = (57, 58, 62)
LINE = (188, 188, 160)
TREE = (56, 100, 62)


def _diamond(x: int, y: int, w: int = 4, d: int = 4) -> list[tuple[int, int]]:
    return [
        (x, y),
        (x + w * TW // 2, y + w * TH // 2),
        (x + (w - d) * TW // 2, y + (w + d) * TH // 2),
        (x - d * TW // 2, y + d * TH // 2),
    ]


def draw_urban_road(surface: pygame.Surface, x: int, y: int, road: UrbanRoad, night: bool = False) -> None:
    color = ASPHALT_LIT if road.avenue else ASPHALT
    pygame.draw.polygon(surface, color, _diamond(x, y, 4, 4))
    if road.role == "cross":
        pygame.draw.line(surface, LINE, (x - 24, y + 14), (x + 24, y + 38), 1)
        pygame.draw.line(surface, LINE, (x + 24, y + 14), (x - 24, y + 38), 1)
    elif road.role == "straight_ne":
        pygame.draw.line(surface, LINE, (x - 22, y + 22), (x + 22, y + 44), 1)
    else:
        pygame.draw.line(surface, LINE, (x + 22, y + 22), (x - 22, y + 44), 1)


def _blit_building(surface: pygame.Surface, tier: str, x: int, y: int, rng: random.Random) -> pygame.Rect:
    entries = assets.iso_building_entries(tier)
    entry = entries[rng.randrange(len(entries))]
    sprite = assets.iso_sprite(entry["file"])
    base = entry.get("base", [sprite.get_width() // 2, sprite.get_height() - 2])
    pos = (round(x - base[0]), round(y + TH - base[1]))
    surface.blit(sprite, pos)
    return pygame.Rect(pos, sprite.get_size())


def draw_urban_block(surface: pygame.Surface, x: int, y: int, block: UrbanBlock, rng: random.Random, night: bool = False) -> list[pygame.Rect]:
    base_color = LOT if block.district in ("industrial", "utility") else PAVEMENT
    pygame.draw.polygon(surface, base_color, _diamond(x, y, 4, 4))
    pygame.draw.lines(surface, PAVEMENT_DARK, True, _diamond(x, y, 4, 4), 1)
    rects: list[pygame.Rect] = []
    offsets = [(-12, 10), (10, 16), (0, 30), (-24, 24)]
    for index, tier in enumerate(block.buildings[:4]):
        dx, dy = offsets[index]
        rects.append(_blit_building(surface, tier, x + dx, y + dy, rng))
    if block.archetype == "civic":
        pygame.draw.circle(surface, TREE, (x - 20, y + 30), 4)
        pygame.draw.circle(surface, TREE, (x + 18, y + 26), 3)
    elif block.district in ("mixed", "core") and block.variant % 3 == 0:
        pygame.draw.rect(surface, (42, 44, 48), (x + 16, y + 30, 12, 6))
        pygame.draw.line(surface, (210, 198, 116), (x + 17, y + 33), (x + 26, y + 33))
    return rects


def draw_utility_campus_base(surface: pygame.Surface, x: int, y: int, radius: int) -> pygame.Rect:
    w = max(5, radius * 3)
    d = max(5, radius * 3)
    poly = _diamond(x, y, w, d)
    pygame.draw.polygon(surface, LOT, poly)
    pygame.draw.lines(surface, (104, 108, 112), True, poly, 2)
    bounds = pygame.Rect(poly[0], (1, 1))
    for point in poly[1:]:
        bounds.union_ip(pygame.Rect(point, (1, 1)))
    return bounds
```

- [ ] **Step 4: Run renderer tests**

Run the command from Step 2 again.

Expected: pass.

- [ ] **Step 5: Local checkpoint**

Do not stage or commit. Note that drawing helpers are pure enough to be called from `IsoCity._bake()`.

---

### Task 5: Integrate Urban Layout into `IsoCity._layout()`

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
- Test: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: `build_urban_layout(rect, fleet)` from Task 3.
- Produces existing `IsoCity` fields, preserving names:
  - `self._tiles: dict[tuple[int, int], tuple[str, object]]`
  - `self._buildings: list[tuple[int, int, str, float]]`
  - `self._city_centers`
  - `self._urban_layout`
  - `self._extent`, `self._u_max`, `self._v_max`
  - `self._plants`

- [ ] **Step 1: Write failing integration tests**

Add:

```python
def test_iso_city_layout_uses_urban_tiles_not_rural_filler():
    viewport = pygame.Rect(0, 0, 1365, 900)
    city = IsoCity(None)
    city._layout(viewport, ILLUSTRATIVE_POPULATION,
                 ("nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro"))
    kinds = [kind for kind, _extra in city._tiles.values()]
    assert kinds.count("road") > kinds.count("farm") * 20
    assert kinds.count("tree") <= max(20, len(city._buildings) // 5)
    assert kinds.count("grass") <= max(30, len(city._buildings) // 4)
    assert hasattr(city, "_urban_layout")
    assert len(city._buildings) <= 260


def test_power_plants_have_urban_campus_context():
    viewport = pygame.Rect(0, 0, 1365, 900)
    city = IsoCity(None)
    city._layout(viewport, ILLUSTRATIVE_POPULATION,
                 ("nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro"))
    for site in city._plants:
        around = []
        for dc in range(-4, 5):
            for dr in range(-4, 5):
                kind = city._tiles.get((round(site.col) + dc, round(site.row) + dr), ("", None))[0]
                around.append(kind)
        assert "campus" in around or "road" in around
        assert around.count("tree") <= 8
```

- [ ] **Step 2: Run failing integration tests**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import test_city_model as t; t.test_iso_city_layout_uses_urban_tiles_not_rural_filler(); t.test_power_plants_have_urban_campus_context()"
```

Expected: fail because current `_layout()` still creates farm/tree/grass filler and no `_urban_layout`.

- [ ] **Step 3: Import urban model**

At the top of `energy_grid_game/ui/iso_city.py`, add:

```python
from ui.urban_blocks import build_urban_layout
```

- [ ] **Step 4: Replace countryside tile population in `_layout()`**

Inside `IsoCity._layout()`, after `u_max, v_max = self._extents(rect)`, create:

```python
urban = build_urban_layout(rect, tuple(fleet))
self._urban_layout = urban
```

Then replace the old `coords` loop and countryside filler with a tile map built from urban output:

```python
tiles = {}
buildings = []
for pos, road in urban.roads.items():
    tiles[pos] = ("road", road)
for block in urban.blocks:
    e = math.hypot((block.col - block.row) / u_max, (block.col + block.row) / v_max)
    tiles[(block.col, block.row)] = ("urban_block", block)
    for tier in block.buildings:
        buildings.append((block.col, block.row, tier, e))
for pos in urban.green_tiles:
    tiles[pos] = ("park", None)
for campus in urban.campuses.values():
    cc, rr = round(campus.col), round(campus.row)
    for dc in range(-campus.radius, campus.radius + 1):
        for dr in range(-campus.radius, campus.radius + 1):
            if abs(dc) + abs(dr) <= campus.radius + 1:
                tiles[(cc + dc, rr + dr)] = ("campus", campus.key)
```

Set layout state:

```python
self._sub_sites = [(block.col, block.row) for block in urban.blocks if block.district in ("core", "mixed")][:3]
self._tiles = tiles
self._buildings = buildings
self._city_centers = self._choose_city_centers(buildings, tiles)
self._extent = 0.72
self._u_max, self._v_max = u_max, v_max
self._place_plants(rect, fleet, rng, river_v)
self._make_roads(rng)
return rng
```

Define `river_v` before `_place_plants()` call:

```python
def river_v(u):
    return 0.34 * v_max + 0.10 * v_max * math.sin(u / max(1.0, u_max * 0.42))
```

- [ ] **Step 5: Place plants from campuses**

At the start of `_place_plants()`, after `u_max, v_max = self._u_max, self._v_max`, read:

```python
urban = getattr(self, "_urban_layout", None)
```

Inside the loop, before existing hydro/non-hydro placement, add:

```python
if urban is not None and key in urban.campuses:
    campus = urban.campuses[key]
    col, row = campus.col, campus.row
elif key == "hydro":
    ...
else:
    ...
```

Keep the existing sprite bounds clamp, `PlantSite` construction, manifest switchyard metadata, and visual-center metadata unchanged.

- [ ] **Step 6: Run integration tests**

Run the command from Step 2 again.

Expected: pass.

- [ ] **Step 7: Run plant marker regression checks**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import test_city_model as t; t.test_plant_marker_targets_match_manifest_visual_centres(); t.test_all_plant_pins_stay_reachable_at_every_zoom_and_viewport(); t.test_focus_plant_centers_camera_on_plant()"
```

Expected: pass.

- [ ] **Step 8: Local checkpoint**

Do not stage or commit. Note whether any old rural helper functions remain unused and leave cleanup for Task 8.

---

### Task 6: Bake Urban Roads, Blocks, Civic Anchors, and Campus Bases

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/ui/urban_render.py`
- Test: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: tile kinds from Task 5: `"road"`, `"urban_block"`, `"campus"`, `"park"`.
- Produces: baked day/night layers that visually use urban roads/blocks instead of rural terrain.

- [ ] **Step 1: Write failing greenery pixel-ratio capture test**

Add:

```python
def test_baked_zoomed_out_frame_is_not_dominated_by_greenery():
    viewport = pygame.Rect(0, 0, 1000, 460)
    state = SimpleNamespace(population=None, sources=[])
    city = IsoCity(None)
    city.prepare(viewport, state)
    frame = pygame.Surface(viewport.size, pygame.SRCALPHA)
    city._present(frame, viewport)
    greenish = 0
    visible = 0
    for x in range(0, viewport.width, 8):
        for y in range(96, viewport.height, 8):
            r, g, b, a = frame.get_at((x, y))
            if a:
                visible += 1
                if g > r + 18 and g > b + 12:
                    greenish += 1
    assert visible > 0
    assert greenish / visible < 0.38
```

- [ ] **Step 2: Run failing greenery pixel-ratio test**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import test_city_model as t; t.test_baked_zoomed_out_frame_is_not_dominated_by_greenery()"
```

Expected: fail if old ground rendering still dominates.

- [ ] **Step 3: Import urban render helpers**

In `iso_city.py`, add:

```python
from ui.urban_render import draw_urban_block, draw_urban_road, draw_utility_campus_base
```

- [ ] **Step 4: Replace tile drawing branches in `_bake()`**

In the `_bake()` loop over `self._tiles`, add branches before legacy kinds:

```python
if kind == "road":
    draw_urban_road(base_day, x, y, extra, night=False)
    draw_urban_road(base_night, x, y, extra, night=True)
    continue
if kind == "urban_block":
    block_rng = random.Random((extra.col * 92821) ^ (extra.row * 68917) ^ extra.variant)
    draw_urban_block(base_day, x, y, extra, block_rng, night=False)
    block_rng = random.Random((extra.col * 92821) ^ (extra.row * 68917) ^ extra.variant)
    draw_urban_block(base_night, x, y, extra, block_rng, night=True)
    continue
if kind == "campus":
    draw_utility_campus_base(base_day, x, y, 3)
    draw_utility_campus_base(base_night, x, y, 3)
    continue
```

Keep old branches temporarily for fallback/test fixtures.

- [ ] **Step 5: Draw municipal anchors inside civic blocks**

In `urban_render.py`, add:

```python
def blit_municipal(surface: pygame.Surface, role: str, x: int, y: int, rng: random.Random) -> pygame.Rect:
    entries = assets.iso_municipal_entries(role)
    entry = entries[rng.randrange(len(entries))]
    sprite = assets.iso_sprite(entry["file"])
    base = entry.get("base", [sprite.get_width() // 2, sprite.get_height() - 2])
    pos = (round(x - base[0]), round(y + TH - base[1]))
    surface.blit(sprite, pos)
    return pygame.Rect(pos, sprite.get_size())
```

In `iso_city._bake()`, when `kind == "urban_block"` and `self._urban_layout.civic` contains `(extra.col, extra.row)`, call `blit_municipal()` after drawing the block.

- [ ] **Step 6: Run greenery pixel-ratio test**

Run the command from Step 2 again.

Expected: pass.

- [ ] **Step 7: Run existing visual renderer tests**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import test_city_model as t; t.test_baked_region_covers_the_full_stage_at_one_x(); t.test_curated_art_stays_inside_world_across_viewports(); t.test_baked_city_center_sprites_have_room_in_world()"
```

Expected: pass.

- [ ] **Step 8: Local checkpoint**

Do not stage or commit. Note the greenery ratio observed in the passing test output if printed during debugging.

---

### Task 7: Route Transmission Through Urban Corridors

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/ui/urban_blocks.py`
- Test: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: `UrbanLayout.roads`, `PlantSite.switchyard_anchor()`, existing `street_route()`.
- Produces: transmission route geometry that follows roads/campuses/substations rather than crossing green filler.

- [ ] **Step 1: Write failing corridor route test**

Add:

```python
def test_transmission_routes_follow_urban_corridors_not_open_green():
    viewport = pygame.Rect(0, 0, 1000, 460)
    city = IsoCity(None)
    city._bake(viewport, ILLUSTRATIVE_POPULATION,
               ("nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro"))
    urban = city._urban_layout
    assert city._transmission_routes
    road_tiles = set(urban.roads)
    for route in city._transmission_routes:
        near_road = 0
        for point in route[::max(1, len(route) // 8)]:
            world = (point[0] - city._origin[0], point[1] - city._origin[1])
            best = min(
                abs((col - row) * TW // 2 - world[0]) + abs((col + row) * TH // 2 - world[1])
                for col, row in road_tiles
            )
            if best <= 48:
                near_road += 1
        assert near_road >= 3
```

- [ ] **Step 2: Run failing corridor route test**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import test_city_model as t; t.test_transmission_routes_follow_urban_corridors_not_open_green()"
```

Expected: fail if routes still use rural/substation geometry.

- [ ] **Step 3: Add road-nearest helper**

In `urban_blocks.py`, add:

```python
def nearest_road_tile(layout: UrbanLayout, col: float, row: float) -> tuple[int, int]:
    if not layout.roads:
        return round(col), round(row)
    return min(layout.roads, key=lambda pos: abs(pos[0] - col) + abs(pos[1] - row))
```

- [ ] **Step 4: Use road-nearest helper in `_route_transmission()`**

Import:

```python
from ui.urban_blocks import build_urban_layout, nearest_road_tile
```

In `_route_transmission()`, when `_urban_layout` exists, replace plant-to-substation candidate selection with road corridor points:

```python
urban = getattr(self, "_urban_layout", None)
if urban is not None:
    for site in self._plants:
        ax, ay = site.switchyard_anchor()
        start = (ax + ox, ay + oy)
        start_tile = nearest_road_tile(urban, site.col, site.row)
        target_tile = min(
            (pos for pos, road in urban.roads.items() if road.avenue),
            key=lambda pos: abs(pos[0]) + abs(pos[1]),
            default=start_tile,
        )
        end = (iso_xy(*target_tile)[0] + ox + TW // 2,
               iso_xy(*target_tile)[1] + oy + TH // 2)
        route = street_route(start_tile, target_tile, start, end, self._origin)
        self._transmission_routes.append(route)
        self._arc_points.extend(route)
    return
```

Keep existing non-urban branch as fallback.

- [ ] **Step 5: Run corridor route test**

Run the command from Step 2 again.

Expected: pass.

- [ ] **Step 6: Run flow and route regressions**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import test_city_model as t; t.test_electron_flows_ride_the_drawn_conductor_geometry(); t.test_distribution_routes_follow_isometric_street_axes(); t.test_flow_only_spawns_pulses_when_output_is_nonzero()"
```

Expected: pass.

- [ ] **Step 7: Local checkpoint**

Do not stage or commit. Note that route geometry changed visually only.

---

### Task 8: Remove Rural Dominance and Add Performance Caps

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
- Modify: `energy_grid_game/ui/urban_blocks.py`
- Test: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: urban tile kinds and block layout from Tasks 3-6.
- Produces: explicit renderer budgets and tests preventing laggy overpopulation or rural filler recurrence.

- [ ] **Step 1: Write failing budget tests**

Add:

```python
def test_urban_renderer_budget_avoids_overpopulation_lag():
    viewport = pygame.Rect(0, 0, 1365, 900)
    city = IsoCity(None)
    city._bake(viewport, ILLUSTRATIVE_POPULATION,
               ("nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro"))
    urban_blocks = [v for k, v in city._tiles.values() if k == "urban_block"]
    campus_tiles = [v for k, v in city._tiles.values() if k == "campus"]
    road_tiles = [v for k, v in city._tiles.values() if k == "road"]
    rural_tiles = [v for k, v in city._tiles.values() if k in ("farm", "grass", "tree")]
    assert len(urban_blocks) <= 220
    assert len(city._buildings) <= 520
    assert len(campus_tiles) <= 220
    assert len(road_tiles) <= 3200
    assert len(rural_tiles) <= 40
```

- [ ] **Step 2: Run failing budget test**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import test_city_model as t; t.test_urban_renderer_budget_avoids_overpopulation_lag()"
```

Expected: fail if old rural or excessive tile counts remain.

- [ ] **Step 3: Add budget constants**

In `urban_blocks.py`, add:

```python
MAX_URBAN_BLOCKS = 220
MAX_GREEN_TILES = 40
```

At the end of `build_urban_layout()`, before returning, cap blocks:

```python
blocks.sort(key=lambda block: (
    0 if block.district == "core" else
    1 if block.district == "mixed" else
    2 if block.district == "civic" else
    3 if block.district == "industrial" else 4,
    abs(block.col) + abs(block.row),
    block.col,
    block.row,
))
blocks = blocks[:MAX_URBAN_BLOCKS]
buildable_tiles = {(block.col, block.row) for block in blocks}
green_tiles = set(sorted(green_tiles)[:MAX_GREEN_TILES])
```

- [ ] **Step 4: Remove rural fallback from primary urban layout**

In `iso_city._layout()`, ensure no loop fills all remaining `coords` with `farm`, `grass`, or `tree` when `_urban_layout` exists. Keep old rural helper code only behind a fallback branch if `build_urban_layout()` is unavailable or explicitly skipped.

- [ ] **Step 5: Run budget test**

Run the command from Step 2 again.

Expected: pass.

- [ ] **Step 6: Run full city model tests**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'energy_grid_game\test_city_model.py'
```

Expected: all city model checks pass.

- [ ] **Step 7: Local checkpoint**

Do not stage or commit. Record final budget counts from the passing test if printed during debugging.

---

### Task 9: Capture and Visual Acceptance Pass

**Files:**
- Modify if needed: `tools/capture_moments.py`
- Generated: `captures/modern_retro_iso_art/*.png` or `captures/urban_grid_visual_rebuild/*.png`
- Test: capture harness

**Interfaces:**
- Consumes: final renderer from Tasks 1-8.
- Produces: screenshots that prove 1x, 2x, and 4x read as an urban grid and not rural filler.

- [ ] **Step 1: Run full non-visual regression suite**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages;D:\Github\gridmanager\energy_grid_game'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'energy_grid_game\test_city_model.py'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'energy_grid_game\test_grid_flow.py'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'energy_grid_game\test_congestion.py'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'energy_grid_game\test_pricing.py'
```

Expected: all pass.

- [ ] **Step 2: Generate captures**

Run:

```powershell
$env:PYTHONPATH='D:\Github\gridmanager\.venv39\Lib\site-packages'
$env:PYTHONHASHSEED='0'
& 'C:\Users\sycho\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -u 'tools\capture_moments.py' 'captures\urban_grid_visual_rebuild'
```

Expected: exits `0` and captures 28 moments.

- [ ] **Step 3: Inspect 1x capture**

Open `captures/urban_grid_visual_rebuild/11_zoom_1x_day.png`.

Acceptance checklist:

```text
[ ] Roads form a continuous grid.
[ ] Main view is not dominated by grass/farm/forest.
[ ] Plants sit in city-edge utility or industrial context.
[ ] Transmission corridors visually follow roads/service corridors.
[ ] Blocks around center have visible variety.
[ ] Greenery appears as parks/medians/yards/street trees, not as filler.
```

- [ ] **Step 4: Inspect normal gameplay capture**

Open `captures/urban_grid_visual_rebuild/06_game.png`.

Acceptance checklist:

```text
[ ] Plant controls point to visible generator centers.
[ ] Labels do not collide badly with buildings or HUD.
[ ] Edge tabs are understandable for offscreen plants.
[ ] City center reads as a busy urban core.
```

- [ ] **Step 5: Inspect overload capture**

Open `captures/urban_grid_visual_rebuild/25_overload_200.png`.

Acceptance checklist:

```text
[ ] Warning is still an edge vignette.
[ ] Center of screen is not covered by a full-screen gradient wash.
[ ] Urban grid remains readable under warning state.
```

- [ ] **Step 6: If visual checklist fails, add a focused test before edits**

For green-dominance failures, add or adjust `test_baked_zoomed_out_frame_is_not_dominated_by_greenery()`.

For plant-context failures, add or adjust `test_power_plants_have_urban_campus_context()`.

For label/pointer failures, add or adjust `test_plant_marker_targets_match_manifest_visual_centres()` or `test_all_plant_pins_stay_reachable_at_every_zoom_and_viewport()`.

- [ ] **Step 7: Final local checkpoint**

Do not stage or commit. Report changed files, verification commands, and capture paths.

---

## Self-Review Notes

- Spec coverage: asset expansion is Task 1; asset loader is Task 2; urban road-first model is Task 3; varied block rendering is Task 4 and Task 6; `IsoCity` integration is Task 5; urban transmission corridors are Task 7; performance caps and rural removal are Task 8; visual acceptance captures are Task 9.
- No git commands are included. Every checkpoint is local-only.
- The plan preserves simulation code by limiting changes to asset tooling, asset loading, urban layout/rendering, and `IsoCity` visual integration.
- Type names used by later tasks are defined in earlier tasks: `UrbanBlock`, `UrbanRoad`, `UrbanCampus`, `UrbanLayout`, `build_urban_layout()`, `nearest_road_tile()`, `draw_urban_block()`, `draw_urban_road()`, and `draw_utility_campus_base()`.
