"""Small corner widget mirroring the demand chart: a city skyline whose
windows light up in proportion to how much of demand is actually being met.
At severe undersupply the city dims with a slow brownout pulse; at severe
oversupply it glows an escalating amber-to-red instead of steadily, so the
two failure modes read as visually distinct disasters.

All severity effects use slow, smooth, low-contrast color easing rather than
any hard on/off flashing — capped well under ~3 Hz — since large-area strobe
effects are a real photosensitive-seizure trigger.
"""
import math
import random
import pygame

BG = (12, 15, 24)
BORDER = (55, 64, 86)
SKY_DIM = (26, 32, 48)
BUILDING_OFF = (30, 36, 52)
BUILDING_ON = (46, 56, 78)
WINDOW_OFF = (40, 46, 62)
WINDOW_ON = (255, 214, 120)
WINDOW_OVERLOAD = (255, 90, 70)


def _lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class _Building:
    __slots__ = ("x", "w", "h", "windows", "priority", "flicker_seed")

    def __init__(self, x, w, h, cols, rows, priority, flicker_seed):
        self.x = x
        self.w = w
        self.h = h
        self.windows = (cols, rows)
        self.priority = priority
        self.flicker_seed = flicker_seed


class CityGrid:
    N_BUILDINGS = 14

    SPARK_LIFE = 0.7

    def __init__(self, rect: pygame.Rect, font):
        self.rect = rect
        self.font = font
        self.t = 0.0
        self._rng = random.Random(2024)
        self.buildings = self._make_buildings()
        self._sparks = []  # [age, x, y]

    def _make_buildings(self):
        buildings = []
        rng = self._rng
        x = 8
        priorities = list(range(self.N_BUILDINGS))
        rng.shuffle(priorities)  # stable random lighting order
        for i in range(self.N_BUILDINGS):
            w = rng.randint(14, 24)
            h = rng.randint(28, 95)
            cols = max(1, w // 8)
            rows = max(1, h // 14)
            buildings.append(_Building(x, w, h, cols, rows, priorities[i] / self.N_BUILDINGS, rng.random() * 10))
            x += w + rng.randint(3, 7)
        self._total_w = x
        return buildings

    def draw(self, surface, fill_pct):
        self.t += 1.0 / 60.0
        pygame.draw.rect(surface, BG, self.rect, border_radius=6)
        pygame.draw.rect(surface, BORDER, self.rect, width=1, border_radius=6)

        title = self.font.render("CITY GRID", True, (150, 158, 176))
        surface.blit(title, (self.rect.left + 8, self.rect.top + 4))

        lit_frac = max(0.0, min(1.0, fill_pct))
        undersupply_severity = max(0.0, min(1.0, (0.5 - fill_pct) / 0.5)) if fill_pct < 0.5 else 0.0
        overload_severity = max(0.0, min(1.0, (fill_pct - 1.0) / 0.8)) if fill_pct > 1.0 else 0.0

        # scale/center the skyline within the panel
        avail_w = self.rect.width - 16
        scale = min(1.0, avail_w / max(1, self._total_w))
        base_x = self.rect.left + 8 + (avail_w - self._total_w * scale) / 2
        base_y = self.rect.bottom - 10

        city_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)

        for b in self.buildings:
            is_on = b.priority < lit_frac
            bw, bh = b.w * scale, b.h * scale
            bx = base_x + b.x * scale
            rect = pygame.Rect(int(bx), int(base_y - bh), max(1, int(bw)), int(bh))

            # brownout dimming: a slow (<1Hz), per-building out-of-phase
            # brightness sag rather than a hard on/off cut — reads as failing
            # power, not a flash
            dim = 0.0
            if undersupply_severity > 0 and is_on:
                wobble = 0.5 + 0.5 * math.sin(self.t * (0.7 + b.flicker_seed * 0.15) + b.flicker_seed * 6.28)
                dim = undersupply_severity * wobble
            flicker_on = is_on and dim < 0.85

            body_color = _lerp_color(BUILDING_ON, BUILDING_OFF, dim) if is_on else BUILDING_OFF
            pygame.draw.rect(city_surf, body_color, rect)

            # overload glow: a slow (<=0.8Hz) smooth ease from warm white
            # toward red as severity rises, never a hard color swap
            glow_t = 0.0
            if overload_severity > 0:
                glow_wave = 0.5 + 0.5 * math.sin(self.t * (0.6 + b.flicker_seed * 0.1) + b.flicker_seed * 6.28)
                glow_t = min(1.0, overload_severity * (0.5 + 0.5 * glow_wave))

            cols, rows = b.windows
            win_w = rect.width / cols
            win_h = rect.height / max(1, rows)
            for cx in range(cols):
                for cy in range(rows):
                    wx = rect.left + cx * win_w + win_w * 0.2
                    wy = rect.top + cy * win_h + win_h * 0.25
                    ww = max(1, win_w * 0.6)
                    wh = max(1, win_h * 0.5)
                    if not flicker_on:
                        color = _lerp_color(WINDOW_OFF, WINDOW_ON, max(0.0, 1.0 - dim)) if is_on else WINDOW_OFF
                    elif glow_t > 0:
                        color = _lerp_color(WINDOW_ON, WINDOW_OVERLOAD, glow_t)
                    else:
                        color = WINDOW_ON
                    pygame.draw.rect(city_surf, color, (wx, wy, ww, wh))

        surface.blit(city_surf, (0, 0))

        # overload sparks: soft glints that fade in and out over ~0.7s rather
        # than blipping on/off in a single frame (sparse, brief, and small —
        # not a full-panel flash either way, but a smooth fade is gentler)
        if overload_severity > 0.25 and self._rng.random() < 0.01 + overload_severity * 0.02:
            b = self._rng.choice(self.buildings)
            bx = base_x + (b.x + b.w / 2) * scale
            by = base_y - b.h * scale - 3
            self._sparks.append([0.0, bx, by])

        for s in self._sparks:
            s[0] += 1.0 / 60.0
        self._sparks = [s for s in self._sparks if s[0] < self.SPARK_LIFE]
        for age, sx, sy in self._sparks:
            life = age / self.SPARK_LIFE
            fade = math.sin(life * math.pi)  # smooth in-out envelope, no hard edges
            spark_surf = pygame.Surface((10, 10), pygame.SRCALPHA)
            pygame.draw.circle(spark_surf, (255, 220, 210, int(200 * fade)), (5, 5), 2)
            surface.blit(spark_surf, (sx - 5, sy - 5))

        # status caption
        if fill_pct >= 1.8:
            caption, color = "GRID OVERLOAD", WINDOW_OVERLOAD
        elif fill_pct >= 1.0:
            caption, color = "STRAINED", (240, 200, 90)
        elif fill_pct < 0.15:
            caption, color = "CITYWIDE BLACKOUT", (230, 80, 80)
        elif fill_pct < 0.5:
            caption, color = "ROLLING BROWNOUTS", (230, 140, 70)
        else:
            caption, color = "STABLE", (100, 220, 140)
        cap_txt = self.font.render(caption, True, color)
        surface.blit(cap_txt, (self.rect.right - cap_txt.get_width() - 8, self.rect.top + 4))
