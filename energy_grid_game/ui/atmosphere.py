"""Time and weather as part of the isometric world, never as a backdrop."""
import math
import random
from dataclasses import dataclass

import pygame

from ui.time_of_day import get_time_of_day_colors


@dataclass(frozen=True)
class Atmosphere:
    world_tint: tuple
    precipitation: str = ""
    wetness: float = 0.0
    snow_cover: float = 0.0
    ice: float = 0.0
    cloud_shadow: float = 0.0
    heat: float = 0.0
    wind: tuple = (0.0, 0.15)


def _mix(a, b, amount):
    return tuple(round(x + (y - x) * amount) for x, y in zip(a, b))


def sample_atmosphere(sim_hour, event_kind):
    """Return deterministic material/particle inputs for one simulation state."""
    _top, bottom = get_time_of_day_colors(sim_hour)
    kind = event_kind or ""
    tint = _mix(bottom, (122, 132, 145), 0.24 if kind in
                ("CLOUD_COVER", "RAIN", "SNOW", "ICE_STORM") else 0.08)
    if kind == "HEAT_WAVE":
        tint = _mix(tint, (255, 135, 82), 0.20)
    if kind in ("SNOW", "ICE_STORM"):
        tint = _mix(tint, (198, 220, 238), 0.24)
    return Atmosphere(
        world_tint=tint,
        precipitation={"RAIN": "rain", "SNOW": "snow",
                       "ICE_STORM": "ice"}.get(kind, ""),
        wetness=0.72 if kind == "RAIN" else 0.20 if kind == "ICE_STORM" else 0.0,
        snow_cover=0.72 if kind == "SNOW" else 0.22 if kind == "ICE_STORM" else 0.0,
        ice=0.75 if kind == "ICE_STORM" else 0.0,
        cloud_shadow=0.62 if kind in ("RAIN", "SNOW", "ICE_STORM")
        else 0.42 if kind == "CLOUD_COVER" else 0.0,
        heat=0.75 if kind == "HEAT_WAVE" else 0.0,
        wind=(0.95, 0.22) if kind == "WIND_GUST" else (-0.18, 0.85),
    )


class AtmosphereLayer:
    """Draw clipped dynamic effects over the stage; owns no background fill."""

    def __init__(self, seed=20260730):
        rng = random.Random(seed)
        self._seeds = [(rng.random(), rng.random(), rng.random()) for _ in range(120)]
        self._t = 0.0
        self._overlay = None

    def draw(self, surface, rect, atmosphere, dt):
        self._t += dt
        if self._overlay is None or self._overlay.get_size() != rect.size:
            self._overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
        layer = self._overlay
        layer.fill((0, 0, 0, 0))

        if atmosphere.cloud_shadow:
            alpha = round(38 * atmosphere.cloud_shadow)
            drift = (self._t * 13) % (rect.width + 220)
            for i in range(4):
                x = int((i * rect.width / 3 + drift) % (rect.width + 220) - 110)
                y = int(rect.height * (0.18 + i * 0.17))
                pygame.draw.ellipse(layer, (18, 28, 38, alpha), (x, y, 190, 62))

        if atmosphere.ice:
            layer.fill((185, 220, 244, round(25 * atmosphere.ice)),
                       special_flags=pygame.BLEND_RGBA_ADD)

        count = 90 if atmosphere.precipitation else 0
        for sx, sy, speed in self._seeds[:count]:
            x = (sx * rect.width + atmosphere.wind[0] * self._t * (55 + 80 * speed)) % rect.width
            y = (sy * rect.height + self._t * (90 + 420 * speed)) % rect.height
            if atmosphere.precipitation == "rain":
                pygame.draw.line(layer, (145, 190, 230, 175), (x, y),
                                 (x - 3, y - 12), 1)
            elif atmosphere.precipitation == "snow":
                pygame.draw.circle(layer, (238, 244, 250, 205), (int(x), int(y)),
                                   1 + int(speed * 2))
            elif atmosphere.precipitation == "ice":
                pygame.draw.line(layer, (205, 232, 250, 190), (x, y),
                                 (x - 5, y - 9), 2)

        if atmosphere.heat:
            alpha = round(34 * atmosphere.heat)
            for i in range(7):
                y = rect.height - 20 - i * 17
                x = int(20 * math.sin(self._t * 1.4 + i))
                pygame.draw.arc(layer, (255, 150, 92, alpha),
                                (x, y, rect.width, 18), 0.15, math.pi - 0.15, 1)

        if atmosphere.wind[0] > 0.8:
            for i in range(12):
                x = int((self._t * 520 + i * 137) % (rect.width + 120) - 120)
                y = int(rect.height * (0.1 + (i * 0.071) % 0.75))
                pygame.draw.line(layer, (220, 230, 238, 120), (x, y), (x + 55, y), 1)

        surface.blit(layer, rect.topleft)
