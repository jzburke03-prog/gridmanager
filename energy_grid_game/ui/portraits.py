"""Mentor artwork: loading, nearest-neighbor scaling, nine-slicing, caching.

Every asset in assets/mentor is expected to be a real transparent RGBA PNG.
Three of them originally shipped as RGB with the light "transparency
checkerboard" baked into their pixels; they were corrected once, permanently, by
tools/fix_portrait_mattes.py rather than being keyed at runtime. If an asset ever
turns up without alpha again, load() says so loudly and names the fix instead of
silently papering over it with a blanket white-removal rule (which would punch
holes through Gattie's hair, beard, eyes and gingham shirt).

Scaling is always pygame.transform.scale (nearest-neighbor), never smoothscale,
so the pixel art stays sharp.
"""
from pathlib import Path

import pygame

# energy_grid_game/ui/portraits.py -> repo root -> assets/mentor
ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "mentor"

# Portrait roles. Note there is no sad/disappointed artwork in the repo: failure
# uses ANGRY, success uses HAPPY, narration uses the two explaining poses.
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

# chatbox.png nine-slice: the frame's border is 43-48px thick in the source art,
# so 48 is the smallest corner that captures a whole corner ornament.
CHATBOX_SRC_CORNER = 48

_raw_cache = {}
_scaled_cache = {}
_slice_cache = {}


def _crop_to_content(surface: pygame.Surface) -> pygame.Surface:
    """Trim fully-transparent margins so layout math works off the artwork
    itself rather than the asset's arbitrary canvas size."""
    rect = surface.get_bounding_rect()  # alpha-aware
    if rect.width == 0 or rect.height == 0:
        return surface
    return surface.subsurface(rect).copy()


def load(key: str) -> pygame.Surface:
    """Load a mentor asset at native resolution, cropped to its artwork."""
    if key in _raw_cache:
        return _raw_cache[key]
    if key not in _FILES:
        raise KeyError(f"unknown mentor asset {key!r}; have {sorted(_FILES)}")

    path = ASSET_DIR / _FILES[key]
    if not path.is_file():
        raise FileNotFoundError(f"mentor asset missing: {path}")

    surface = pygame.image.load(str(path))
    if surface.get_bitsize() != 32 or surface.get_masks()[3] == 0:
        raise ValueError(
            f"{path.name} has no alpha channel. Mentor art must be transparent "
            f"RGBA; run: python tools/fix_portrait_mattes.py"
        )
    surface = _crop_to_content(surface.convert_alpha())
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


def fit_within(key: str, max_w: int, max_h: int) -> pygame.Surface:
    """Largest nearest-neighbor scale of `key` fitting inside the box, aspect
    preserved. The portraits have very different aspect ratios, so callers that
    reserve a slot need to fit both dimensions, not just height."""
    src = load(key)
    w, h = src.get_size()
    scale = min(max_w / w, max_h / h)
    return scaled_to_height(key, max(1, int(h * scale)))


def nine_slice(key: str, size, corner: int) -> pygame.Surface:
    """Rebuild a framed panel at an arbitrary size, keeping the border crisp.

    Plain scaling can't give the dialogue box a short, wide shape: the chatbox
    art is fixed at 2.49:1, and squashing it to fit distorts the border into
    smeared rectangles. Nine-slicing keeps the corners at a fixed size, stretches
    the edges along their own axis only, and fills the middle with the asset's
    own paper color. The middle is filled rather than stretched because the
    source's centre carries a baked decorative arrow that would smear across the
    whole panel; the dialogue draws its own continue indicator instead.
    """
    w, h = int(size[0]), int(size[1])
    corner = max(1, int(corner))
    cache_key = (key, w, h, corner)
    hit = _slice_cache.get(cache_key)
    if hit is not None:
        return hit

    src = load(key)
    sw, sh = src.get_size()
    sc = min(CHATBOX_SRC_CORNER, sw // 2, sh // 2)
    corner = min(corner, w // 2, h // 2)

    out = pygame.Surface((w, h), pygame.SRCALPHA)
    paper = src.get_at((sw // 2, sh // 2))  # clean centre of the cream area
    inner = pygame.Rect(corner, corner, max(0, w - 2 * corner), max(0, h - 2 * corner))
    if inner.width and inner.height:
        out.fill(paper, inner)

    mid_w, mid_h = max(0, w - 2 * corner), max(0, h - 2 * corner)
    src_mid_w, src_mid_h = sw - 2 * sc, sh - 2 * sc

    def piece(area, dst_size, dst_pos):
        if dst_size[0] <= 0 or dst_size[1] <= 0:
            return
        part = src.subsurface(pygame.Rect(*area))
        out.blit(pygame.transform.scale(part, dst_size), dst_pos)

    # edges: stretched along their own axis only
    piece((sc, 0, src_mid_w, sc), (mid_w, corner), (corner, 0))
    piece((sc, sh - sc, src_mid_w, sc), (mid_w, corner), (corner, h - corner))
    piece((0, sc, sc, src_mid_h), (corner, mid_h), (0, corner))
    piece((sw - sc, sc, sc, src_mid_h), (corner, mid_h), (w - corner, corner))
    # corners: never stretched
    piece((0, 0, sc, sc), (corner, corner), (0, 0))
    piece((sw - sc, 0, sc, sc), (corner, corner), (w - corner, 0))
    piece((0, sh - sc, sc, sc), (corner, corner), (0, h - corner))
    piece((sw - sc, sh - sc, sc, sc), (corner, corner), (w - corner, h - corner))

    _slice_cache[cache_key] = out
    return out
