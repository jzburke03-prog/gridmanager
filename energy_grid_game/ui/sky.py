"""Full-frame background: a day/night sky whose color, sun and moon position
track sim_hour, plus animated weather overlays (rain, cloud cover, heat-wave sun
pulses, wind gust streaks) synced to the active grid event.

The flat two-color day/night lerp this used to fill with has been replaced by a
vertical gradient interpolated between time-of-day keyframes (see ui/time_of_day),
driven by the simulation clock rather than the real-world one.
"""
import math
import random
import pygame

from ui.time_of_day import SkyGradient

SUN_COLOR = (255, 209, 102)     # matches SolarSource.color
MOON_COLOR = (200, 210, 225)

CLOUD_COLOR = (130, 140, 160)
RAIN_COLOR = (150, 180, 220)
WIND_STREAK_COLOR = (220, 225, 235)
HEAT_RING_COLOR = (255, 140, 90)
SNOW_COLOR = (235, 240, 250)
ICE_COLOR = (180, 220, 255)
ICE_TINT = (190, 220, 255, 28)   # full-frame blue-white freeze wash

DAY_START, DAY_END = 5.0, 20.0     # sunrise / sunset, mirrors solar_availability
NIGHT_SPAN = 24.0 - (DAY_END - DAY_START)  # 9 hours


def _arc_pos(progress, rect):
    """progress 0..1 across the sky -> (x, y, elevation 0..1)."""
    angle = math.pi * max(0.0, min(1.0, progress))
    x = rect.left + rect.width * progress
    elevation = math.sin(angle)
    y = rect.bottom - elevation * rect.height * 0.85
    return x, y, elevation


class Cloud:
    def __init__(self, rect):
        self.reset(rect, randomize_x=True)

    def reset(self, rect, randomize_x=False):
        self.x = random.uniform(rect.left, rect.right) if randomize_x else rect.left - 60
        self.y = random.uniform(rect.top + 10, rect.top + rect.height * 0.4)
        self.speed = random.uniform(8, 18)
        self.scale = random.uniform(0.8, 1.6)

    def update(self, dt, rect):
        self.x += self.speed * dt
        if self.x > rect.right + 80:
            self.reset(rect)

    def draw(self, surface, alpha):
        lobes = [(-24, 0, 16), (-6, -8, 20), (16, 0, 18), (0, 6, 22)]
        cloud_surf = pygame.Surface((140, 60), pygame.SRCALPHA)
        for lx, ly, lr in lobes:
            r = int(lr * self.scale)
            pygame.draw.circle(cloud_surf, (*CLOUD_COLOR, alpha), (70 + int(lx * self.scale), 30 + ly), r)
        surface.blit(cloud_surf, (self.x - 70, self.y - 30))


class RainDrop:
    def __init__(self, rect):
        self.reset(rect)

    def reset(self, rect):
        self.x = random.uniform(rect.left, rect.right)
        self.y = random.uniform(rect.top, rect.bottom)
        self.speed = random.uniform(420, 620)
        self.length = random.uniform(10, 18)

    def update(self, dt, rect):
        self.y += self.speed * dt
        self.x -= self.speed * 0.15 * dt
        if self.y > rect.bottom:
            self.y = rect.top - self.length
            self.x = random.uniform(rect.left, rect.right)


class Snowflake:
    """Slow-falling flake with a sinusoidal side-to-side drift."""

    def __init__(self, rect):
        self.reset(rect, randomize_y=True)

    def reset(self, rect, randomize_y=False):
        self.x = random.uniform(rect.left, rect.right)
        self.y = random.uniform(rect.top, rect.bottom) if randomize_y else rect.top - 4
        self.speed = random.uniform(30, 70)
        self.radius = random.randint(1, 3)
        self.sway_phase = random.uniform(0.0, math.tau)
        self.sway_freq = random.uniform(0.6, 1.4)
        self.sway_amp = random.uniform(3, 9)

    def update(self, dt, rect):
        self.y += self.speed * dt
        if self.y > rect.bottom:
            self.reset(rect)

    def draw(self, surface, t):
        x = self.x + math.sin(t * self.sway_freq + self.sway_phase) * self.sway_amp
        pygame.draw.circle(surface, SNOW_COLOR, (int(x), int(self.y)), self.radius)


class IceShard:
    """Sleet: faster than snow, slower than rain, with a hard wind slant."""

    def __init__(self, rect):
        self.reset(rect, randomize_y=True)

    def reset(self, rect, randomize_y=False):
        self.x = random.uniform(rect.left, rect.right)
        self.y = random.uniform(rect.top, rect.bottom) if randomize_y else rect.top - 14
        self.speed = random.uniform(250, 380)
        self.length = random.uniform(8, 14)

    def update(self, dt, rect):
        self.y += self.speed * dt
        self.x -= self.speed * 0.3 * dt
        if self.y > rect.bottom:
            self.y = rect.top - self.length
            self.x = random.uniform(rect.left, rect.right)


class WindStreak:
    def __init__(self, rect):
        self.reset(rect, randomize_x=True)

    def reset(self, rect, randomize_x=False):
        self.x = random.uniform(rect.left, rect.right) if randomize_x else rect.left - 100
        self.y = random.uniform(rect.top, rect.bottom)
        self.speed = random.uniform(600, 950)
        self.length = random.uniform(40, 90)

    def update(self, dt, rect):
        self.x += self.speed * dt
        if self.x - self.length > rect.right:
            self.reset(rect)


class SkyLayer:
    def __init__(self):
        self._t = 0.0
        self._clouds = None
        self._raindrops = None
        self._streaks = None
        self._snow = None
        self._shards = None
        self._ice_tint = None
        self._gradient = SkyGradient()

    def draw(self, surface, rect, sim_hour, active_event):
        self._t += 1 / 60.0
        self._gradient.draw(surface, rect, sim_hour)

        sun_pt = moon_pt = None
        if DAY_START <= sim_hour < DAY_END:
            progress = (sim_hour - DAY_START) / (DAY_END - DAY_START)
            x, y, elevation = _arc_pos(progress, rect)
            sun_pt = (x, y)
            self._draw_body(surface, x, y, 22, SUN_COLOR, glow=1.0)
        else:
            night_progress = ((sim_hour - DAY_END) % 24.0) / NIGHT_SPAN
            x, y, elevation = _arc_pos(night_progress, rect)
            moon_pt = (x, y)
            self._draw_body(surface, x, y, 16, MOON_COLOR, glow=0.6)

        kind = active_event.kind if active_event else None

        if kind in ("CLOUD_COVER", "RAIN"):
            self._draw_clouds(surface, rect, alpha=90 if kind == "RAIN" else 150)
        if kind == "RAIN":
            self._draw_rain(surface, rect)
        if kind == "SNOW":
            self._draw_clouds(surface, rect, alpha=120)
            self._draw_snow(surface, rect)
        if kind == "ICE_STORM":
            self._draw_clouds(surface, rect, alpha=140)
            self._draw_ice(surface, rect)
        if kind == "WIND_GUST":
            self._draw_wind_streaks(surface, rect)
        if kind == "HEAT_WAVE":
            origin = sun_pt or moon_pt
            if origin:
                self._draw_heat_pulses(surface, origin)

    def _draw_body(self, surface, x, y, radius, color, glow):
        halo = pygame.Surface((radius * 6, radius * 6), pygame.SRCALPHA)
        cx = cy = radius * 3
        for i in range(3, 0, -1):
            a = int(40 * glow / i)
            pygame.draw.circle(halo, (*color, a), (cx, cy), int(radius * (1 + i * 0.7)))
        surface.blit(halo, (x - cx, y - cy))
        pygame.draw.circle(surface, color, (int(x), int(y)), radius)

    def _draw_clouds(self, surface, rect, alpha):
        if self._clouds is None:
            self._clouds = [Cloud(rect) for _ in range(4)]
        for c in self._clouds:
            c.update(1 / 60.0, rect)
            c.draw(surface, alpha)

    def _draw_rain(self, surface, rect):
        if self._raindrops is None:
            self._raindrops = [RainDrop(rect) for _ in range(90)]
        for d in self._raindrops:
            d.update(1 / 60.0, rect)
            pygame.draw.line(surface, RAIN_COLOR, (d.x, d.y), (d.x - d.length * 0.15, d.y - d.length), 1)

    def _draw_wind_streaks(self, surface, rect):
        if self._streaks is None:
            band_top = rect.top + rect.height * 0.15
            band_bottom = rect.top + rect.height * 0.55
            band = pygame.Rect(rect.left, band_top, rect.width, band_bottom - band_top)
            self._streaks = [WindStreak(band) for _ in range(14)]
        band_top = rect.top + rect.height * 0.15
        band_bottom = rect.top + rect.height * 0.55
        band = pygame.Rect(rect.left, band_top, rect.width, band_bottom - band_top)
        for s in self._streaks:
            s.update(1 / 60.0, band)
            pygame.draw.line(surface, WIND_STREAK_COLOR, (s.x - s.length, s.y), (s.x, s.y), 2)

    def _draw_snow(self, surface, rect, limit=None):
        if self._snow is None:
            self._snow = [Snowflake(rect) for _ in range(120)]
        for f in (self._snow if limit is None else self._snow[:limit]):
            f.update(1 / 60.0, rect)
            f.draw(surface, self._t)

    def _draw_ice(self, surface, rect):
        # cold blue-white wash over the whole sky, then wind-slanted sleet
        # with a scattering of slow flakes riding along
        if self._ice_tint is None or self._ice_tint.get_size() != rect.size:
            self._ice_tint = pygame.Surface(rect.size, pygame.SRCALPHA)
            self._ice_tint.fill(ICE_TINT)
        surface.blit(self._ice_tint, rect.topleft)
        if self._shards is None:
            self._shards = [IceShard(rect) for _ in range(70)]
        for s in self._shards:
            s.update(1 / 60.0, rect)
            pygame.draw.line(surface, ICE_COLOR, (s.x, s.y),
                             (s.x - s.length * 0.3, s.y - s.length), 1)
        self._draw_snow(surface, rect, limit=40)

    def _draw_heat_pulses(self, surface, origin):
        x, y = origin
        for i in range(3):
            phase = (self._t * 0.8 + i / 3.0) % 1.0
            radius = 20 + phase * 70
            alpha = int(160 * (1.0 - phase))
            if alpha <= 0:
                continue
            ring = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(ring, (*HEAT_RING_COLOR, alpha), (radius + 2, radius + 2), int(radius), width=3)
            surface.blit(ring, (x - radius - 2, y - radius - 2))
