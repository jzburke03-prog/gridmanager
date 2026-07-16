"""Time-of-day sky colors, driven by the simulation clock (state.sim_hour) —
never the real-world wall clock.

Keyframe data is kept separate from any draw loop: get_time_of_day_colors() is a
pure hour -> (top, bottom) function, and SkyGradient owns the cached surface.
"""
import numpy as np
import pygame

# (hour, top_color, bottom_color), ascending. Interpolation wraps 22:00 -> 00:00.
KEYFRAMES = [
    (0.0, (12, 18, 38), (25, 31, 55)),      # night
    (5.0, (52, 49, 83), (164, 91, 82)),     # dawn
    (8.0, (94, 155, 204), (157, 198, 222)),  # morning
    (12.0, (91, 166, 219), (176, 211, 228)),  # daytime
    (17.0, (103, 141, 184), (205, 151, 108)),  # late afternoon
    (19.5, (63, 53, 94), (180, 87, 72)),    # dusk
    (22.0, (18, 25, 51), (39, 42, 68)),     # evening
]

_DAY = 24.0


def _smoothstep(t: float) -> float:
    """Ease the crossfade so keyframes don't arrive as visible linear kinks."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def get_time_of_day_colors(game_hour: float):
    """Sim hour (may be any real number; wraps mod 24) -> (top_rgb, bottom_rgb)."""
    h = game_hour % _DAY

    for i, frame in enumerate(KEYFRAMES):
        if frame[0] > h:
            lo, hi = KEYFRAMES[i - 1], frame
            break
    else:
        # after the last keyframe (22:00): wrap across midnight to the first
        lo, hi = KEYFRAMES[-1], KEYFRAMES[0]

    span = (hi[0] - lo[0]) % _DAY or _DAY
    into = (h - lo[0]) % _DAY
    t = _smoothstep(into / span)
    return _lerp(lo[1], hi[1], t), _lerp(lo[2], hi[2], t)


class SkyGradient:
    """Cached vertical gradient. The gradient is generated one pixel wide with
    NumPy and then stretched horizontally, so a rebuild costs a single scale
    blit instead of a per-pixel Python loop over the whole window. It rebuilds
    only when the window size or the rounded colors actually change, which the
    clock only does every few frames."""

    def __init__(self):
        self._surface = None
        self._key = None

    def surface(self, width: int, height: int, top, bottom) -> pygame.Surface:
        key = (width, height, top, bottom)
        if key == self._key and self._surface is not None:
            return self._surface

        column = np.zeros((1, height, 3), dtype=np.uint8)
        for c in range(3):
            column[0, :, c] = np.linspace(top[c], bottom[c], height).astype(np.uint8)
        strip = pygame.Surface((1, height))
        pygame.surfarray.blit_array(strip, column)
        # nearest-neighbor horizontal stretch of a 1px column: no banding, and
        # far cheaper than filling width*height from Python
        self._surface = pygame.transform.scale(strip, (width, height))
        self._key = key
        return self._surface

    def draw(self, surface: pygame.Surface, rect: pygame.Rect, game_hour: float):
        top, bottom = get_time_of_day_colors(game_hour)
        surface.blit(self.surface(rect.width, rect.height, top, bottom), rect.topleft)
