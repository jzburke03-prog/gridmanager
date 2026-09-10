"""Slice the approved iso sprite sheets into curated repo assets.

Run from repo root:
    .venv39\\Scripts\\python.exe tools\\slice_iso_assets.py

Outputs:
    assets/iso/source/
    assets/iso/buildings/
    assets/iso/city_center/
    assets/iso/plants/
    assets/iso/manifest.json
    assets/iso/README.txt

The slicer uses alpha-connected components and a curated component map. It is
deterministic: running it twice produces the same files and manifest.
"""
from __future__ import annotations

import json
import shutil
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import pygame

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "assets" / "iso"
SOURCE_OUT = OUT / "source"

SOURCES = {
    "1x1x1": Path("C:/Users/sycho/Downloads/1x1x1.png"),
    "1x1x2": Path("C:/Users/sycho/Downloads/1x1x2.png"),
    "2x2x2": Path("C:/Users/sycho/Downloads/2x2x2.png"),
    "citycenters": Path("C:/Users/sycho/Downloads/citycenters.png"),
    "buildings": Path("C:/Users/sycho/Downloads/buildings.png"),
}
SOURCES.update({
    "municipal": Path("C:/Users/sycho/Downloads/municipal buildings.png"),
    "hjm_iso_houses": Path("C:/Users/sycho/Downloads/hjm-iso-houses.png"),
    "road_2": Path("C:/Users/sycho/Downloads/spr_road_2_strip29.png"),
    "roads_1": Path("C:/Users/sycho/Downloads/spr_roads_1_strip15.png"),
    "gui": Path("C:/Users/sycho/Downloads/gui.png"),
})

EXPECTED_SIZES = {
    "1x1x1": (560, 135),
    "1x1x2": (560, 240),
    "2x2x2": (672, 55),
    "citycenters": (280, 55),
    "buildings": (504, 310),
}
EXPECTED_SIZES.update({
    "municipal": (316, 226),
    "hjm_iso_houses": (768, 400),
    "road_2": (320, 192),
    "roads_1": (192, 160),
    "gui": (650, 200),
})

CURATION = {
    "buildings": {
        "house": [("1x1x1", 5), ("1x1x1", 6), ("1x1x1", 46)],
        "shop": [("buildings", 17), ("buildings", 18), ("buildings", 19)],
        "block": [("buildings", 32), ("buildings", 36), ("buildings", 39)],
        "midrise": [("buildings", 47), ("buildings", 54), ("buildings", 55)],
        "tower": [("buildings", 41), ("buildings", 42), ("buildings", 43)],
    },
    "city_center": [("citycenters", 0), ("buildings", 44), ("buildings", 43)],
    "plants": {
        "nuclear": ("buildings", 66),
        "coal": ("buildings", 68),
        "gas": ("buildings", 70),
        "peaker": ("2x2x2", 8),
        "solar": ("buildings", 69),
        "wind": ("buildings", 67),
        "hydro": ("citycenters", 0),
        "generic": ("buildings", 32),
    },
}

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
    "graveyard": ("municipal", (228, 160, 80, 62), ["civic", "green"]),
}

DETAIL_CROPS = {
    "pavement": ("gui", (195, 112, 24, 24), ["paved"]),
    "parking": ("gui", (222, 112, 24, 24), ["paved", "parking"]),
    "service_yard": ("gui", (276, 112, 24, 24), ["paved", "utility"]),
    "street_tree": ("buildings", (4, 3, 28, 20), ["green", "street_tree"]),
}


@dataclass(frozen=True)
class Component:
    rect: pygame.Rect
    area: int


def ensure_dirs() -> None:
    for rel in ("source", "buildings", "city_center", "plants", "roads", "municipal", "details"):
        (OUT / rel).mkdir(parents=True, exist_ok=True)


def copy_sources() -> None:
    ensure_dirs()
    for name, src in SOURCES.items():
        if not src.is_file():
            raise FileNotFoundError(f"missing approved source sheet: {src}")
        shutil.copy2(src, SOURCE_OUT / f"{name}.png")


def is_foreground(surface: pygame.Surface, x: int, y: int) -> bool:
    return surface.get_at((x, y)).a > 0


def components(surface: pygame.Surface, min_area: int = 12) -> list[Component]:
    width, height = surface.get_size()
    seen = [[False] * width for _ in range(height)]
    found: list[Component] = []

    for y in range(height):
        for x in range(width):
            if seen[y][x] or not is_foreground(surface, x, y):
                seen[y][x] = True
                continue
            queue = deque([(x, y)])
            seen[y][x] = True
            min_x = max_x = x
            min_y = max_y = y
            area = 0
            while queue:
                px, py = queue.popleft()
                area += 1
                min_x, max_x = min(min_x, px), max(max_x, px)
                min_y, max_y = min(min_y, py), max(max_y, py)
                for nx, ny in (
                    (px + 1, py),
                    (px - 1, py),
                    (px, py + 1),
                    (px, py - 1),
                ):
                    if 0 <= nx < width and 0 <= ny < height and not seen[ny][nx]:
                        seen[ny][nx] = True
                        if is_foreground(surface, nx, ny):
                            queue.append((nx, ny))
            if area >= min_area:
                found.append(
                    Component(
                        pygame.Rect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1),
                        area,
                    )
                )
    return sorted(found, key=lambda c: (c.rect.y, c.rect.x, c.rect.width, c.rect.height))


def tight_crop(surface: pygame.Surface, rect: pygame.Rect, pad: int = 1) -> pygame.Surface:
    padded = rect.inflate(pad * 2, pad * 2).clip(surface.get_rect())
    return surface.subsurface(padded).copy()


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


def save_crop(sheet: pygame.Surface, component: Component, relpath: str, pad: int = 1) -> dict:
    target = OUT / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    sprite = tight_crop(sheet, component.rect, pad=pad)
    pygame.image.save(sprite, str(target))
    bounds = sprite.get_bounding_rect()
    return {
        "file": relpath.replace("\\", "/"),
        "size": [sprite.get_width(), sprite.get_height()],
        "alpha_bounds": [bounds.x, bounds.y, bounds.w, bounds.h],
    }


def pick(
    component_map: dict[str, list[Component]],
    sheet_name: str,
    index: int,
    role: str,
) -> Component:
    items = component_map[sheet_name]
    if index >= len(items):
        raise IndexError(f"{role} requested {sheet_name}[{index}], only {len(items)} components found")
    return items[index]


def base_for(entry: dict) -> list[int]:
    w, h = entry["size"]
    return [w // 2, h - 2]


def switchyard_for(entry: dict) -> list[int]:
    w, h = entry["size"]
    return [min(w - 2, round(w * 0.72)), max(2, round(h * 0.70))]


def build_manifest(
    component_map: dict[str, list[Component]],
    sheets: dict[str, pygame.Surface],
) -> dict:
    manifest = {
        "buildings": {},
        "city_center": [],
        "plants": {},
        "roads": {},
        "municipal": {},
        "details": {},
        "block_palettes": {},
    }
    for tier, selections in CURATION["buildings"].items():
        manifest["buildings"][tier] = []
        for n, (sheet_name, index) in enumerate(selections, 1):
            component = pick(component_map, sheet_name, index, f"building:{tier}")
            entry = save_crop(sheets[sheet_name], component, f"buildings/{tier}_{n:02}.png")
            entry["capacity_tier"] = tier
            entry["base"] = base_for(entry)
            manifest["buildings"][tier].append(entry)

    for n, (sheet_name, index) in enumerate(CURATION["city_center"], 1):
        component = pick(component_map, sheet_name, index, "city_center")
        entry = save_crop(sheets[sheet_name], component, f"city_center/core_{n:02}.png")
        entry["base"] = base_for(entry)
        entry["footprint"] = [2, 2]
        manifest["city_center"].append(entry)

    for key, (sheet_name, index) in CURATION["plants"].items():
        component = pick(component_map, sheet_name, index, f"plant:{key}")
        entry = save_crop(sheets[sheet_name], component, f"plants/{key}_01.png", pad=0)
        entry["base"] = base_for(entry)
        entry["switchyard_anchor"] = switchyard_for(entry)
        entry["visual_center"] = [entry["size"][0] // 2, max(0, entry["alpha_bounds"][1])]
        manifest["plants"][key] = entry

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
    return manifest


def write_readme() -> None:
    text = """MODERN-RETRO ISO ART PACK

Generated from the ten user-approved source sheets on 2026-08-01:
- 1x1x1.png
- 1x1x2.png
- 2x2x2.png
- citycenters.png
- buildings.png
- municipal buildings.png
- hjm-iso-houses.png
- spr_road_2_strip29.png
- spr_roads_1_strip15.png
- gui.png

Run tools/slice_iso_assets.py from the repository root to regenerate the curated sprites.
Runtime code loads only the curated sprites and manifest in assets/iso/.
Municipal, houses, and GUI sheets may be curated from fixed rectangles; road sheets are component-sliced.
"""
    (OUT / "README.txt").write_text(text, encoding="utf-8")


def main() -> None:
    pygame.init()
    pygame.display.set_mode((1, 1))
    copy_sources()
    sheets = {}
    component_map = {}
    for name in SOURCES:
        path = SOURCE_OUT / f"{name}.png"
        sheet = pygame.image.load(str(path)).convert_alpha()
        if sheet.get_size() != EXPECTED_SIZES[name]:
            raise ValueError(f"{name} expected {EXPECTED_SIZES[name]}, got {sheet.get_size()}")
        sheets[name] = sheet
        component_map[name] = components(sheet)
    manifest = build_manifest(component_map, sheets)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_readme()


if __name__ == "__main__":
    main()
