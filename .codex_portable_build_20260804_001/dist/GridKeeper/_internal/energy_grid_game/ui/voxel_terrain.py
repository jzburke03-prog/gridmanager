"""Voxel-hybrid terrain art for the iso map: thin-depth ground slabs, edge
mountains, and season palettes.

This module is imported by ui.iso_city, so it must NOT import iso_city back
(circular import). TW/TH are duplicated here and MUST stay equal to
iso_city.TW/TH (16, 8). The pure helpers are unit-tested in
test_voxel_terrain.py; the pygame drawing primitives are exercised by the
capture harness.
"""
import math

TW, TH = 16, 8          # MUST match ui.iso_city.TW/TH

# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------
_SEASON_BY_MONTH = {12: "winter", 1: "winter", 2: "winter",
                    3: "spring", 4: "spring", 5: "spring",
                    6: "summer", 7: "summer", 8: "summer",
                    9: "fall", 10: "fall", 11: "fall"}


def season_of(month):
    return _SEASON_BY_MONTH[int(month)]


# material top-face colours per season; side faces are shaded from these
SEASONS = {
    "spring": dict(grass=(96, 158, 84), field=(150, 178, 92), water=(60, 120, 196),
                   road=(110, 112, 116), pad=(120, 122, 128), rock=(112, 108, 102),
                   snow=(232, 238, 246), tree=(70, 140, 70)),
    "summer": dict(grass=(112, 158, 80), field=(196, 178, 98), water=(58, 110, 190),
                   road=(112, 112, 110), pad=(120, 120, 124), rock=(122, 114, 102),
                   snow=(236, 240, 246), tree=(56, 120, 58)),
    "fall":   dict(grass=(150, 150, 78), field=(198, 150, 78), water=(58, 110, 182),
                   road=(104, 98, 90), pad=(122, 116, 106), rock=(114, 100, 86),
                   snow=(232, 236, 244), tree=(176, 96, 52)),
    "winter": dict(grass=(224, 230, 238), field=(214, 222, 232), water=(150, 182, 206),
                   road=(150, 152, 158), pad=(158, 160, 166), rock=(150, 156, 166),
                   snow=(244, 248, 252), tree=(64, 110, 80)),
}


def palette(season):
    return SEASONS[season]


def should_rebake_for_season(prev, cur):
    return prev != cur


# ---------------------------------------------------------------------------
# Value noise + mountain elevation
# ---------------------------------------------------------------------------
def _h2(a, b):
    n = (int(a) * 374761393 + int(b) * 668265263) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return (n & 0xFFFF) / 65535.0


def vnoise(x, y):
    xi, yi = math.floor(x), math.floor(y)
    xf, yf = x - xi, y - yi

    def sm(t):
        return t * t * (3 - 2 * t)

    u, v = sm(xf), sm(yf)
    a, b = _h2(xi, yi), _h2(xi + 1, yi)
    c, d = _h2(xi, yi + 1), _h2(xi + 1, yi + 1)
    return (a * (1 - u) + b * u) * (1 - v) + (c * (1 - u) + d * u) * v


def elevation(col, row, cx, cy, start=24.0, full=42.0):
    """Voxel px height for a tile: 0 inside `start` radius of (cx,cy), rising to
    noisy peaks by `full`. Used to ring the map with mountains on the edges."""
    d = math.hypot(col - cx, row - cy)
    if d <= start:
        return 0
    ramp = min(1.0, (d - start) / (full - start))
    ridge = 0.45 + 0.55 * vnoise(col * 0.16, row * 0.16)
    peak = 0.55 + 0.85 * vnoise(col * 0.24 + 10, row * 0.24 + 10)
    return int(ramp * (5 + 15 * ridge) * peak * 1.25)     # taller edge peaks


# ---------------------------------------------------------------------------
# Drawing primitives + material classification
# ---------------------------------------------------------------------------
VOX_DEPTH = 3
FIELD_SIZE = 6
WOOD_SIZE = 8


def _shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def _diamond_pts(sx, sy):
    """Matches iso_city.diamond(sx, sy): top corner at (sx+TW//2, sy)."""
    return ((sx + TW // 2, sy), (sx + TW, sy + TH // 2),
            (sx + TW // 2, sy + TH), (sx, sy + TH // 2))


def slab(surf, sx, sy, top, depth=VOX_DEPTH, jit=1.0):
    """A thin voxel ground tile (top diamond + two short side faces)."""
    import pygame
    top = _shade(top, jit)
    T, R, B, L = _diamond_pts(sx, sy)
    Ld, Bd, Rd = (L[0], L[1] + depth), (B[0], B[1] + depth), (R[0], R[1] + depth)
    pygame.draw.polygon(surf, _shade(top, 0.72), [L, B, Bd, Ld])   # left face
    pygame.draw.polygon(surf, _shade(top, 0.55), [B, R, Rd, Bd])   # right face
    pygame.draw.polygon(surf, top, [T, R, B, L])                   # top


def column(surf, sx, sy, height, top, cap=None, jit=1.0):
    """A voxel block rising `height` px above the tile (for mountains)."""
    import pygame
    top = _shade(top, jit)
    T, R, B, L = _diamond_pts(sx, sy)
    Tu = (T[0], T[1] - height)
    Ru = (R[0], R[1] - height)
    Bu = (B[0], B[1] - height)
    Lu = (L[0], L[1] - height)
    pygame.draw.polygon(surf, _shade(top, 0.68), [Lu, Bu, B, L])   # left
    pygame.draw.polygon(surf, _shade(top, 0.50), [Bu, Ru, R, B])   # right
    pygame.draw.polygon(surf, _shade(cap or top, 1.0), [Tu, Ru, Bu, Lu])  # top/cap


def material_at(col, row):
    """Deterministic countryside classifier -> the tile KIND used by iso_city:
    clustered woodland ("tree") vs cultivated fields ("farm") vs "grass"
    (the river is handled by the caller). NOTE: fields use the existing "farm"
    kind, matching iso_city._bake and the carve/tests."""
    if (_h2(col // WOOD_SIZE, row // WOOD_SIZE) * 100) < 9:
        return "tree"
    fk = (col // FIELD_SIZE, row // FIELD_SIZE)
    return "farm" if (_h2(fk[0], fk[1]) * 3) < 1 else "grass"
