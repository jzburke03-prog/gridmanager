"""Mentor artwork loading: transparency keying, nearest-neighbor scaling, caching.

The five mentor PNGs in assets/mentor are not uniform. Gattie_GoodJob and
Gattie_Angry are true RGBA with a real alpha channel. Gattie_Explaining_Talking,
Gattie_Explaining_Pointing and chatbox.png are RGB with NO alpha channel at all —
they have the light checkerboard "transparent background" pattern baked into
their pixels (~76% of each portrait). Blitting those as-is would drop a big
opaque near-white slab over the game.

So the matte is keyed off at load: a flood fill from the image border through
near-white pixels only. It has to be a flood fill and not a plain threshold —
Gattie's hair, beard and gingham shirt contain near-white pixels too, and a
threshold key punches holes straight through them. Only background reachable
from the border is cleared; the character's own pixels are never touched.

Scaling is always pygame.transform.scale (nearest-neighbor), never smoothscale,
so the pixel art stays sharp instead of going soft.
"""
from pathlib import Path

import numpy as np
import pygame

# energy_grid_game/ui/portraits.py -> repo root -> assets/mentor
ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "mentor"

# Portrait roles used by the tutorial and the outcome screens. Note there is no
# sad/disappointed artwork in the repo: failure states use ANGRY, success uses
# HAPPY, and ordinary narration uses the two neutral explaining poses.
NEUTRAL = "neutral"
POINTING = "pointing"
HAPPY = "happy"
ANGRY = "angry"
CHATBOX = "chatbox"

_FILES = {
    NEUTRAL: "Gattie_Explaining_Talking.png",
    POINTING: "Gattie_Explaining_Pointing.png",
    HAPPY: "Gattie_GoodJob_Portrait.png",
    ANGRY: "Gattie_Angry_Portait.png",
    CHATBOX: "chatbox.png",
}

# A pixel is background only if every channel is at least this bright AND it is
# reachable from the image border. The baked checkerboard alternates between
# roughly 243 and 255.
_MATTE_THRESHOLD = 238

# chatbox.png: the cream writing area, as a fraction of the cropped frame.
# Measured off the asset itself rather than guessed.
CHATBOX_INSET_X = 0.0278
CHATBOX_INSET_TOP = 0.0772
CHATBOX_INSET_BOTTOM = 0.0723

_raw_cache = {}
_scaled_cache = {}


def _flood_matte(light: np.ndarray) -> np.ndarray:
    """Scanline flood fill. `light` is a (w, h) bool array of near-white pixels;
    returns the subset reachable from the image border. Span-filling a whole row
    at a time keeps this ~30x faster than a per-pixel queue (~0.15s vs ~5s for a
    1086x1448 portrait), which matters because it runs at asset load."""
    w, h = light.shape
    filled = np.zeros_like(light)
    stack = []
    for x in range(w):
        for y in (0, h - 1):
            if light[x, y]:
                stack.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if light[x, y]:
                stack.append((x, y))

    while stack:
        x, y = stack.pop()
        if filled[x, y] or not light[x, y]:
            continue
        row = light[:, y]
        done = filled[:, y]
        x0 = x
        while x0 > 0 and row[x0 - 1] and not done[x0 - 1]:
            x0 -= 1
        x1 = x
        while x1 < w - 1 and row[x1 + 1] and not done[x1 + 1]:
            x1 += 1
        filled[x0:x1 + 1, y] = True
        for ny in (y - 1, y + 1):
            if not (0 <= ny < h):
                continue
            span = light[x0:x1 + 1, ny] & ~filled[x0:x1 + 1, ny]
            idx = np.flatnonzero(span)
            if idx.size == 0:
                continue
            # one seed per contiguous run in the span above/below
            breaks = np.flatnonzero(np.diff(idx) > 1)
            starts = np.concatenate(([idx[0]], idx[breaks + 1]))
            for s in starts:
                stack.append((x0 + int(s), ny))
    return filled


def _key_matte(surface: pygame.Surface) -> pygame.Surface:
    """Clear the baked-in near-white background of an RGB asset to transparent."""
    rgb = pygame.surfarray.array3d(surface)
    light = (rgb >= _MATTE_THRESHOLD).all(axis=2)
    matte = _flood_matte(light)

    out = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    pygame.surfarray.blit_array(out, rgb)
    alpha = pygame.surfarray.pixels_alpha(out)
    alpha[:] = np.where(matte, 0, 255).astype(np.uint8)
    del alpha  # release the surface lock before the surface is used
    return out


def _crop_to_content(surface: pygame.Surface) -> pygame.Surface:
    """Trim fully-transparent margins so layout math works off the artwork
    itself rather than the asset's arbitrary canvas size."""
    rect = surface.get_bounding_rect()  # alpha-aware
    if rect.width == 0 or rect.height == 0:
        return surface
    return surface.subsurface(rect).copy()


def load(key: str) -> pygame.Surface:
    """Load a mentor asset, keyed and cropped, at its native resolution."""
    if key in _raw_cache:
        return _raw_cache[key]
    if key not in _FILES:
        raise KeyError(f"unknown mentor asset {key!r}; have {sorted(_FILES)}")

    path = ASSET_DIR / _FILES[key]
    if not path.is_file():
        raise FileNotFoundError(f"mentor asset missing: {path}")

    surface = pygame.image.load(str(path))
    if surface.get_bitsize() < 32 or surface.get_masks()[3] == 0:
        surface = _key_matte(surface)      # RGB asset: strip the baked matte
    else:
        surface = surface.convert_alpha()  # already has real alpha
    surface = _crop_to_content(surface)
    _raw_cache[key] = surface
    return surface


def scaled_to_height(key: str, height: int) -> pygame.Surface:
    """Nearest-neighbor scale to `height` px, preserving aspect. Cached per
    (asset, height) so a resize rebuilds it but a normal frame never does."""
    height = max(1, int(height))
    cache_key = (key, height)
    hit = _scaled_cache.get(cache_key)
    if hit is not None:
        return hit

    src = load(key)
    w, h = src.get_size()
    width = max(1, round(w * height / h))
    # pygame.transform.scale is nearest-neighbor; smoothscale would blur the
    # pixel art, which the art direction here depends on.
    out = pygame.transform.scale(src, (width, height))
    _scaled_cache[cache_key] = out
    return out


def scaled_to_width(key: str, width: int) -> pygame.Surface:
    """Nearest-neighbor scale to `width` px, preserving aspect."""
    src = load(key)
    w, h = src.get_size()
    return scaled_to_height(key, max(1, round(h * width / w)))
