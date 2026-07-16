"""Pre-rendered gradient warning border around the play area.

This replaces the four flat solid-color rects the HUD used to rebuild and blit
every frame. The band is built from concentric 1px rectangle outlines walking
inward from the window edge: consecutive rings tile exactly, including through
the corners (each ring is the set of pixels at a given Chebyshev distance from
the edge), so corners mitre naturally and there are no seams. Color ramps dark
at the exterior to a brighter, less saturated red at the interior, and alpha
fades to nothing at the inner edge so the band dissolves into the scene.

Performance notes, all measured against a 1400x900 24-bit frame:

  * The old per-frame rebuild + full blit cost ~15.2 ms/frame.
  * Caching the band and modulating it with Surface.set_alpha is a trap: mixing
    per-surface alpha with per-pixel alpha drops SDL onto a slow blitter and
    costs ~26 ms/frame -- worse than the code it replaced. BLEND_ALPHA_SDL2
    (~25 ms) and BLEND_RGBA_MULT (~30-42 ms) are no better.
  * Baking the intensity into the cached surface and blitting it plainly costs
    ~1.5 ms, and blitting only the four edge strips (the middle is entirely
    transparent, so blending it is pure waste) costs ~0.83 ms.

So intensity is baked in and quantized, and only the ring is stored and blitted.
Quantizing means the pulse steps in ~3% opacity increments rather than being
continuous, which is imperceptible but keeps the cache to a bounded handful of
entries instead of one per frame.
"""
from collections import OrderedDict

import pygame

# exterior -> middle -> interior. Restrained, not neon: the outer edge is nearly
# black-red and the interior only lifts to a muted brick.
RED = ((82, 10, 20), (145, 24, 38), (205, 55, 65))

# The overload/meltdown warning keeps its amber identity (it has to stay visually
# distinct from the blackout warning) but is built the same way.
AMBER = ((92, 40, 6), (162, 82, 16), (232, 158, 62))

_THICKNESS_MIN = 70
_THICKNESS_STEP = 30
_THICKNESS_MAX = 160

_INTENSITY_STEP = 8   # ~3% opacity granularity on the pulse
_CACHE_LIMIT = 24     # comfortably covers one pulse cycle's worth of buckets


def _quantize_thickness(thickness: float) -> int:
    """Snap to 70/100/130/160. The band pulses anyway, so a <=15px quantization
    of its width is invisible, and it keeps the cache small."""
    t = max(_THICKNESS_MIN, min(_THICKNESS_MAX, thickness))
    bucket = round((t - _THICKNESS_MIN) / _THICKNESS_STEP)
    return int(_THICKNESS_MIN + bucket * _THICKNESS_STEP)


def _quantize_intensity(intensity: float) -> int:
    i = max(0, min(255, int(intensity)))
    return min(255, round(i / _INTENSITY_STEP) * _INTENSITY_STEP)


def _ramp(palette, t: float):
    """t: 0.0 at the exterior edge, 1.0 at the interior edge."""
    exterior, middle, interior = palette
    if t < 0.5:
        a, b, local = exterior, middle, t / 0.5
    else:
        a, b, local = middle, interior, (t - 0.5) / 0.5
    return tuple(int(round(a[i] + (b[i] - a[i]) * local)) for i in range(3))


def _edge_strips(width, height, thickness):
    """The four rects covering the ring, tiling it exactly with no overlap (so
    nothing is blended twice) and no gap (so no seam)."""
    t = thickness
    if height <= 2 * t or width <= 2 * t:
        return [pygame.Rect(0, 0, width, height)]  # band meets in the middle
    return [
        pygame.Rect(0, 0, width, t),
        pygame.Rect(0, height - t, width, t),
        pygame.Rect(0, t, t, height - 2 * t),
        pygame.Rect(width - t, t, t, height - 2 * t),
    ]


class GradientBorder:
    def __init__(self):
        self._cache = OrderedDict()

    def _build(self, width, height, thickness, palette, intensity):
        band = pygame.Surface((width, height), pygame.SRCALPHA)
        span = max(1, thickness - 1)
        scale = intensity / 255.0
        for i in range(thickness):
            t = i / span
            color = _ramp(palette, t)
            # Linear fade toward the interior so the band dissolves instead of
            # ending on a hard line. Deliberately linear rather than eased: a
            # steeper curve drops alpha to 0 well before the ramp reaches its
            # brighter reds, so the interior color would never show.
            alpha = int(round(255 * (1.0 - t) * scale))
            if alpha <= 0:
                continue
            ring = pygame.Rect(i, i, width - 2 * i, height - 2 * i)
            if ring.width <= 0 or ring.height <= 0:
                break
            # drawing on an SRCALPHA surface overwrites rather than blends, which
            # is what we want: each ring is disjoint from its neighbours
            pygame.draw.rect(band, (*color, alpha), ring, width=1)

        # keep only the ring; the transparent middle is never worth blitting
        return [(rect.topleft, band.subsurface(rect).copy())
                for rect in _edge_strips(width, height, thickness)]

    def strips(self, width, height, thickness, palette, intensity):
        thickness = _quantize_thickness(thickness)
        intensity = _quantize_intensity(intensity)
        key = (width, height, thickness, palette, intensity)

        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit

        # a resize invalidates every cached band; drop them rather than keep a
        # full set of ring surfaces per stale window size
        for stale in [k for k in self._cache if k[0] != width or k[1] != height]:
            del self._cache[stale]

        built = self._build(width, height, thickness, palette, intensity)
        self._cache[key] = built
        while len(self._cache) > _CACHE_LIMIT:
            self._cache.popitem(last=False)
        return built

    def draw(self, target: pygame.Surface, thickness: int, intensity: int, palette=RED):
        """intensity: 0-255 overall opacity, baked into the cached band."""
        if intensity <= 0:
            return
        w, h = target.get_size()
        for pos, strip in self.strips(w, h, thickness, palette, intensity):
            target.blit(strip, pos)
