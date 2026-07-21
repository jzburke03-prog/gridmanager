"""Full-width city skyline drawn as a faint backdrop behind the gameplay.

Its windows light up in proportion to how much of demand is being met, so the
city's glow doubles as an at-a-glance supply readout: it dims to a slow brownout
when undersupplied and eases toward red when overloaded. Rendered at low opacity
so it sits behind the tank without competing with it.

All severity effects use slow, smooth, low-contrast easing rather than any hard
on/off flashing — capped well under ~3 Hz — since large-area strobe effects are a
real photosensitive-seizure trigger.
"""
import math
import random
import pygame

from ui import assets

LABEL_DIM = (150, 158, 176)
LABEL_OK = (100, 220, 140)
LABEL_WARN = (240, 170, 80)
LABEL_BAD = (230, 90, 90)
BUILDING = (18, 22, 36)
WINDOW_ON = (255, 214, 120)
WINDOW_OVERLOAD = (255, 90, 70)

BODY_ALPHA = 48          # faint silhouette
WINDOW_ALPHA = 150       # the lit windows are the prominent, supply-tracking part


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
    N_BUILDINGS = 46

    def __init__(self, font, font_label=None):
        self.font = font
        self.font_label = font_label or font
        self.t = 0.0
        self._rng = random.Random(2024)
        self.buildings = self._make_buildings()
        self._surf = None   # cached full-screen scratch surface

    def _make_buildings(self):
        rng = self._rng
        buildings = []
        x = 0
        priorities = list(range(self.N_BUILDINGS))
        rng.shuffle(priorities)  # stable random lighting order
        for i in range(self.N_BUILDINGS):
            w = rng.randint(18, 40)
            h = rng.randint(70, 240)
            cols = max(1, w // 9)
            rows = max(2, h // 18)
            buildings.append(_Building(x, w, h, cols, rows,
                                       priorities[i] / self.N_BUILDINGS, rng.random() * 10))
            x += w + rng.randint(4, 12)
        self._total_w = x
        return buildings

    def draw_backdrop(self, surface, rect, fill_pct):
        """Draw the skyline rising from rect.bottom across rect.width, its lit
        windows tracking fill_pct (1.0 = meeting demand)."""
        self.t += 1.0 / 60.0
        lit_frac = max(0.0, min(1.0, fill_pct))
        under = max(0.0, min(1.0, (0.5 - fill_pct) / 0.5)) if fill_pct < 0.5 else 0.0
        over = max(0.0, min(1.0, (fill_pct - 1.0) / 0.8)) if fill_pct > 1.0 else 0.0

        if self._surf is None or self._surf.get_size() != surface.get_size():
            self._surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        city = self._surf
        city.fill((0, 0, 0, 0))

        scale = rect.width / self._total_w
        base_y = rect.bottom
        for b in self.buildings:
            is_on = b.priority < lit_frac
            bw, bh = b.w * scale, b.h * scale
            bx = rect.left + b.x * scale
            br = pygame.Rect(int(bx), int(base_y - bh), max(1, int(bw)), int(bh))
            pygame.draw.rect(city, (*BUILDING, BODY_ALPHA), br)
            if not is_on:
                continue

            # brownout dimming (slow, out-of-phase per building) and overload
            # glow (warm -> red) reuse the corner widget's easing feel.
            dim = 0.0
            if under > 0:
                wob = 0.5 + 0.5 * math.sin(self.t * (0.7 + b.flicker_seed * 0.15) + b.flicker_seed * 6.28)
                dim = under * wob
            glow = 0.0
            if over > 0:
                gw = 0.5 + 0.5 * math.sin(self.t * (0.6 + b.flicker_seed * 0.1) + b.flicker_seed * 6.28)
                glow = min(1.0, over * (0.5 + 0.5 * gw))

            cols, rows = b.windows
            ww = br.width / cols
            wh = br.height / max(1, rows)
            base = _lerp_color(WINDOW_ON, WINDOW_OVERLOAD, glow) if glow > 0 else WINDOW_ON
            alpha = int(WINDOW_ALPHA * max(0.15, 1.0 - dim))
            for cxi in range(cols):
                for cyi in range(rows):
                    wx = br.left + cxi * ww + ww * 0.25
                    wy = br.top + cyi * wh + wh * 0.25
                    pygame.draw.rect(city, (*base, alpha),
                                     (wx, wy, max(1, ww * 0.5), max(1, wh * 0.5)))
        surface.blit(city, (0, 0))

    def draw_homes_label(self, surface, anchor, homes_out: float, homes_total: float):
        """"Homes Without Power" readout, centred on the anchor rect's column."""
        if homes_out > 500:
            color = LABEL_BAD if homes_out > homes_total * 0.5 else LABEL_WARN
            value = f"{homes_out:,.0f}"
        else:
            color, value = LABEL_OK, "0"
        cap_txt = self.font.render("HOMES WITHOUT POWER", True, LABEL_DIM)
        val_txt = self.font_label.render(value, True, color)
        pop_icon = assets.resource_icon("population", 14)
        cx = anchor.centerx
        cap_x = cx - cap_txt.get_width() // 2
        # dark scrim so the readout stays legible over the lit city behind it
        block_h = cap_txt.get_height() + val_txt.get_height() + 4
        block_w = max(cap_txt.get_width() + 20, val_txt.get_width()) + 24
        scrim = pygame.Surface((block_w, block_h + 10), pygame.SRCALPHA)
        scrim.fill((10, 13, 21, 165))
        surface.blit(scrim, (cx - block_w // 2, anchor.top - 5))
        surface.blit(pop_icon, (cap_x - pop_icon.get_width() - 4,
                                anchor.top + (cap_txt.get_height() - 14) // 2))
        surface.blit(cap_txt, (cap_x, anchor.top))
        surface.blit(val_txt, (cx - val_txt.get_width() // 2, anchor.top + cap_txt.get_height() + 2))
