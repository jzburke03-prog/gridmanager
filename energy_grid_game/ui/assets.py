"""Loader for the assets/ pixel-art pack (buttons, icons, panels, calendar
tiles, scenario cards, tabs, progress bars, stars, and the animated tech
sprites).

Mirrors ui/portraits.py: lazy pygame.image.load, an RGBA-alpha assertion, and
per-shape caches so scaling happens once. Two scaling policies:

  * The 4x-exported UI assets are nearest-neighbor scaled (kept crisp), ideally
    at integer multiples of their native size.
  * The 627x627 tech-plant frames are downscaled ~10x, where nearest-neighbor
    decimates thin blades/smoke differently per frame and the loop shimmers, so
    those use smoothscale.

Everything is loaded lazily inside the functions -- never at import time, since
convert_alpha() requires a display surface to exist first.
"""
import json
from pathlib import Path

import pygame

# energy_grid_game/ui/assets.py -> repo root -> assets
ASSET_DIR = Path(__file__).resolve().parents[2] / "assets"

OPERATOR = "question_mark_operator"

_raw_cache = {}      # relpath -> Surface (convert_alpha, uncropped)
_scaled_cache = {}   # (relpath, w, h, smooth) -> Surface
_slice_cache = {}    # (relpath, w, h) -> Surface
_tech_cache = {}     # (tech, height, dim) -> [Surface x4]
_iso_manifest_cache = None
_iso_sprite_cache = {}


def load(relpath: str) -> pygame.Surface:
    """Load a pack asset at native resolution. UI pieces are NOT cropped so
    idle/hover/pressed variants stay registered to the same canvas."""
    hit = _raw_cache.get(relpath)
    if hit is not None:
        return hit
    path = ASSET_DIR / relpath
    if not path.is_file():
        raise FileNotFoundError(f"asset missing: {path}")
    surface = pygame.image.load(str(path))
    if surface.get_bitsize() != 32 or surface.get_masks()[3] == 0:
        raise ValueError(f"{relpath} has no alpha channel; pack art must be RGBA")
    surface = surface.convert_alpha()
    _raw_cache[relpath] = surface
    return surface


def scaled(relpath: str, size, smooth: bool = False) -> pygame.Surface:
    """Scale a pack asset to (w, h), cached. Nearest by default; smooth for the
    rare non-integer downscale."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    key = (relpath, w, h, smooth)
    hit = _scaled_cache.get(key)
    if hit is not None:
        return hit
    src = load(relpath)
    if src.get_size() == (w, h):
        out = src
    elif smooth:
        out = pygame.transform.smoothscale(src, (w, h))
    else:
        out = pygame.transform.scale(src, (w, h))
    _scaled_cache[key] = out
    return out


def scaled_to_height(relpath: str, height: int, smooth: bool = False) -> pygame.Surface:
    height = max(1, int(height))
    src = load(relpath)
    w, h = src.get_size()
    return scaled(relpath, (round(w * height / h), height), smooth)


def button(name: str, state: str = "idle") -> pygame.Surface:
    """buttons/<name>_button_<state>.png at native size (128x64)."""
    return load(f"buttons/{name}_button_{state}.png")


def hud_icon(name: str, size: int) -> pygame.Surface:
    return scaled(f"hud_icons/{name}_icon.png", (size, size))


def resource_icon(name: str, size: int) -> pygame.Surface:
    return scaled(f"resource_icons/{name}_icon.png", (size, size))


def h_slice(relpath: str, width: int, height: int, cap: int) -> pygame.Surface:
    """3-slice horizontal stretch: left/right caps kept, middle strip stretched.
    For the notification banner, whose rounded ends must not smear. `cap` is the
    native-pixel cap width on each side. Cached per (relpath, width, height)."""
    width, height = max(1, int(width)), max(1, int(height))
    key = (relpath, width, height)
    hit = _slice_cache.get(key)
    if hit is not None:
        return hit
    src = load(relpath)
    sw, sh = src.get_size()
    cap = min(int(cap), sw // 2)
    dst_cap = max(1, round(cap * height / sh))
    dst_cap = min(dst_cap, width // 2)

    out = pygame.Surface((width, height), pygame.SRCALPHA)

    def piece(area, dst_size, dst_pos):
        if dst_size[0] <= 0 or dst_size[1] <= 0:
            return
        part = src.subsurface(pygame.Rect(*area))
        out.blit(pygame.transform.scale(part, dst_size), dst_pos)

    mid_w = width - 2 * dst_cap
    src_mid_w = sw - 2 * cap
    piece((cap, 0, src_mid_w, sh), (mid_w, height), (dst_cap, 0))   # stretched middle
    piece((0, 0, cap, sh), (dst_cap, height), (0, 0))               # left cap
    piece((sw - cap, 0, cap, sh), (dst_cap, height), (width - dst_cap, 0))  # right cap
    _slice_cache[key] = out
    return out


def tech_frames(tech: str, height: int, dim: bool = False) -> list:
    """The 4 animation frames of a tech plant, smoothscaled to `height` and
    union-cropped so the loop stays registered. `dim` returns a darkened copy
    (for idle/offline plants). Cached per (tech, height, dim)."""
    height = max(1, int(height))
    key = (tech, height, dim)
    hit = _tech_cache.get(key)
    if hit is not None:
        return hit

    raws = [load(f"tech/{tech}_frame_0{i}.png") for i in range(1, 5)]
    # union of the 4 alpha bounding rects: cropping each frame to its own bounds
    # would shift the artwork frame-to-frame and make the loop jitter.
    union = raws[0].get_bounding_rect()
    for r in raws[1:]:
        union.union_ip(r.get_bounding_rect())

    out = []
    for raw in raws:
        cropped = raw.subsurface(union)
        w = max(1, round(cropped.get_width() * height / cropped.get_height()))
        surf = pygame.transform.smoothscale(cropped, (w, height))
        if dim:
            surf = surf.copy()
            surf.fill((70, 70, 70), special_flags=pygame.BLEND_RGB_MULT)
        out.append(surf)
    _tech_cache[key] = out
    return out


def iso_manifest() -> dict:
    """Curated isometric art manifest, loaded lazily from assets/iso."""
    global _iso_manifest_cache
    if _iso_manifest_cache is not None:
        return _iso_manifest_cache
    path = ASSET_DIR / "iso" / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"iso manifest missing: {path}")
    _iso_manifest_cache = json.loads(path.read_text(encoding="utf-8"))
    return _iso_manifest_cache


def iso_sprite(relpath: str) -> pygame.Surface:
    """Load one curated isometric sprite by manifest-relative path."""
    hit = _iso_sprite_cache.get(relpath)
    if hit is not None:
        return hit
    surface = load(f"iso/{relpath}")
    bounds = surface.get_bounding_rect()
    if bounds.width <= 0 or bounds.height <= 0:
        raise ValueError(f"iso sprite has empty alpha bounds: {relpath}")
    _iso_sprite_cache[relpath] = surface
    return surface


def iso_building_entries(tier: str) -> list:
    entries = iso_manifest()["buildings"].get(tier, ())
    if not entries:
        raise KeyError(f"missing iso building tier: {tier}")
    return entries


def iso_city_center_entries() -> list:
    entries = iso_manifest().get("city_center", ())
    if not entries:
        raise KeyError("missing iso city_center entries")
    return entries


def iso_plant_entry(key: str) -> dict:
    try:
        return iso_manifest()["plants"][key]
    except KeyError as exc:
        raise KeyError(f"missing iso plant entry: {key}") from exc


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
