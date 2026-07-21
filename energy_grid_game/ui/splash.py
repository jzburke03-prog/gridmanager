"""16-bit style intro screen for the title menu.

Everything is drawn procedurally onto a tiny 320x180 canvas and upscaled with
nearest-neighbor scaling, so every element lands on a chunky visible pixel grid
— no image assets involved. The scene is a dusk skyline with a power plant:
blinking city windows, smoke puffs, drifting clouds, twinkling stars, and a
power pulse traveling the transmission line, with the game title rendered small
onto the same canvas so the upscale gives it the same pixel chunk.

The static backdrop is built once with a seeded RNG (deterministic between
launches); per-frame work is a copy, a handful of tiny primitives, and one
scale blit.
"""
import math
import random

import pygame

LOW_W, LOW_H = 320, 180
HORIZON = 150          # ground line on the low-res canvas

# dusk palette, echoing ui/time_of_day's dusk/evening keyframes
SKY_BANDS = [
    (18, 25, 51),      # night blue, top
    (34, 36, 68),
    (52, 46, 84),
    (63, 53, 94),      # dusk purple
    (96, 62, 88),
    (140, 74, 80),
    (180, 87, 72),     # ember glow at the horizon
]
SUN_COLOR = (255, 196, 110)
STAR_COLOR = (210, 218, 240)
CLOUD_COLOR = (82, 70, 108)
BACK_BUILDING = (28, 30, 50)
FRONT_BUILDING = (17, 19, 34)
PLANT_COLOR = (40, 44, 62)
PLANT_DARK = (30, 33, 48)
GROUND_COLOR = (13, 15, 26)
GROUND_EDGE = (34, 38, 58)
WINDOW_WARM = (255, 214, 120)
WINDOW_COOL = (150, 210, 235)
SMOKE_NEAR = (172, 172, 184)
SMOKE_FAR = (92, 78, 104)
WIRE_COLOR = (52, 56, 76)
PULSE_COLOR = (140, 220, 255)
TITLE_COLOR = (240, 244, 252)
TITLE_SHADOW = (10, 12, 22)
TAGLINE_COLOR = (196, 170, 150)
PROMPT_COLOR = (255, 214, 120)


def _wire_point(a, c, b, t):
    """Quadratic bezier: pylon top -> sagging control -> pylon top."""
    u = 1.0 - t
    return (u * u * a[0] + 2 * u * t * c[0] + t * t * b[0],
            u * u * a[1] + 2 * u * t * c[1] + t * t * b[1])


class PixelSplash:
    def __init__(self, font, font_small):
        self.font = font
        self.font_small = font_small
        self._t0 = None            # first-draw time, for the one-time fade-in
        self._static = None
        self._backdrop = None      # cached dimmed scene for the menu screens
        self._backdrop_key = None
        self._windows = []         # (x, y, color, phase, period)
        self._stars = []           # (x, y, phase)
        self._wires = []           # (a, c, b) bezier triples
        self._stack_top = (0, 0)
        self._sun = (258, 112)
        self._build_static()

    # -- one-time scene construction --------------------------------------
    def _build_static(self):
        rng = random.Random(7)
        s = pygame.Surface((LOW_W, LOW_H))

        # banded dusk sky: flat horizontal stripes, the 16-bit way
        band_h = HORIZON // len(SKY_BANDS) + 1
        for i, col in enumerate(SKY_BANDS):
            s.fill(col, (0, i * band_h, LOW_W, band_h))

        # stars in the dark upper sky (twinkle drawn per-frame on top)
        for _ in range(46):
            x, y = rng.randrange(2, LOW_W - 2), rng.randrange(2, 74)
            self._stars.append((x, y, rng.uniform(0.0, math.tau)))
            s.set_at((x, y), (120, 128, 156))

        # low setting sun with a stepped "pixel" edge
        sx, sy = self._sun
        for r, col in ((10, (196, 120, 88)), (8, (232, 164, 96)), (6, SUN_COLOR)):
            pygame.draw.circle(s, col, (sx, sy), r)

        # back skyline: taller, hazier towers
        x = -6
        while x < LOW_W:
            w = rng.randrange(16, 30)
            h = rng.randrange(34, 72)
            pygame.draw.rect(s, BACK_BUILDING, (x, HORIZON - h, w, h))
            x += w + rng.randrange(2, 8)

        # front skyline (left 2/3): darker, window-bearing blocks
        x = 2
        while x < 198:
            w = rng.randrange(18, 32)
            h = rng.randrange(22, 52)
            top = HORIZON - h
            pygame.draw.rect(s, FRONT_BUILDING, (x, top, w, h))
            # window grid — each cell may become a live blinking window
            for wx in range(x + 3, x + w - 2, 5):
                for wy in range(top + 4, HORIZON - 4, 6):
                    if rng.random() < 0.55:
                        col = WINDOW_WARM if rng.random() < 0.8 else WINDOW_COOL
                        self._windows.append(
                            (wx, wy, col, rng.uniform(0.0, 1.0), rng.uniform(3.0, 9.0)))
            x += w + rng.randrange(3, 9)

        # power plant, stage right: turbine hall + hyperboloid cooling tower + stack
        pygame.draw.rect(s, PLANT_COLOR, (232, HORIZON - 18, 44, 18))          # hall
        pygame.draw.rect(s, PLANT_DARK, (232, HORIZON - 18, 44, 3))            # roof line
        tower = [(284, HORIZON), (288, HORIZON - 16), (286, HORIZON - 30),
                 (296, HORIZON - 30), (294, HORIZON - 16), (298, HORIZON)]     # cooling tower
        pygame.draw.polygon(s, PLANT_COLOR, tower)
        pygame.draw.rect(s, PLANT_DARK, (240, HORIZON - 44, 4, 26))            # smokestack
        pygame.draw.rect(s, (200, 90, 80), (240, HORIZON - 44, 4, 2))          # beacon stripe
        self._stack_top = (242, HORIZON - 45)

        # transmission pylons with sagging wires
        pylons = [(206, HORIZON - 26), (150, HORIZON - 22)]
        for px, py in pylons:
            pygame.draw.line(s, WIRE_COLOR, (px, HORIZON), (px, py), 1)
            pygame.draw.line(s, WIRE_COLOR, (px - 5, py + 3), (px + 5, py + 3), 1)
            pygame.draw.line(s, WIRE_COLOR, (px - 3, py), (px + 3, py), 1)
        spans = [((150, HORIZON - 22), (206, HORIZON - 26)),
                 ((206, HORIZON - 26), (236, HORIZON - 18))]
        for a, b in spans:
            c = ((a[0] + b[0]) / 2.0, max(a[1], b[1]) + 7)
            self._wires.append((a, c, b))
            steps = 24
            for i in range(steps):
                p0 = _wire_point(a, c, b, i / steps)
                p1 = _wire_point(a, c, b, (i + 1) / steps)
                pygame.draw.line(s, WIRE_COLOR, p0, p1, 1)

        # ground strip
        pygame.draw.rect(s, GROUND_COLOR, (0, HORIZON, LOW_W, LOW_H - HORIZON))
        pygame.draw.line(s, GROUND_EDGE, (0, HORIZON), (LOW_W, HORIZON), 1)

        self._static = s

    def draw_backdrop(self, surface):
        """Dimmed, static version of the pixel scene, shared behind the non-title
        menu screens so they carry the same identity as the intro instead of a
        flat gradient. Cached per window size — one scale + blit per frame."""
        w, h = surface.get_size()
        if self._backdrop_key != (w, h):
            scale = max(w / LOW_W, h / LOW_H)
            tw, th = int(LOW_W * scale + 0.5), int(LOW_H * scale + 0.5)
            scene = pygame.transform.scale(self._static, (tw, th))
            bd = pygame.Surface((w, h))
            bd.fill((8, 10, 20))
            bd.blit(scene, ((w - tw) // 2, (h - th) // 2))
            veil = pygame.Surface((w, h), pygame.SRCALPHA)
            veil.fill((8, 10, 20, 170))   # push the scene back so UI reads clearly
            bd.blit(veil, (0, 0))
            self._backdrop = bd
            self._backdrop_key = (w, h)
        surface.blit(self._backdrop, (0, 0))

    # -- per-frame ---------------------------------------------------------
    def draw(self, surface, t):
        if self._t0 is None:
            self._t0 = t
        frame = self._static.copy()

        # star twinkle: a few bright pixels breathing over the static dim ones
        for x, y, phase in self._stars:
            if math.sin(t * 1.7 + phase) > 0.55:
                frame.set_at((x, y), STAR_COLOR)

        # drifting clouds: flat dark slabs, slow parallax
        for k, (cy, cw, speed) in enumerate(((26, 40, 3.2), (44, 30, 4.6), (62, 24, 6.0))):
            cx = int((k * 90 + t * speed) % (LOW_W + cw)) - cw
            pygame.draw.rect(frame, CLOUD_COLOR, (cx, cy, cw, 3))
            pygame.draw.rect(frame, CLOUD_COLOR, (cx + 4, cy - 2, cw - 10, 2))

        # blinking city windows
        for wx, wy, col, phase, period in self._windows:
            if (t / period + phase) % 1.0 < 0.82:
                frame.fill(col, (wx, wy, 2, 2))

        # smoke puffs rising from the stack
        sx, sy = self._stack_top
        for k in range(4):
            p = (t * 0.16 + k * 0.25) % 1.0
            px = sx + int(math.sin(p * 5.0 + k) * 2) + int(p * 9)
            py = sy - int(p * 26)
            size = 1 + int(p * 3)
            col = tuple(int(SMOKE_NEAR[i] + (SMOKE_FAR[i] - SMOKE_NEAR[i]) * p) for i in range(3))
            frame.fill(col, (px, py, size, size))

        # power pulse traveling the wires
        for k, (a, c, b) in enumerate(self._wires):
            p = (t * 0.35 + k * 0.5) % 1.0
            px, py = _wire_point(a, c, b, p)
            frame.fill(PULSE_COLOR, (int(px), int(py), 2, 2))

        # title block, rendered small so the upscale pixelates it too
        title = self.font.render("GRID MANAGER", True, TITLE_COLOR)
        shadow = self.font.render("GRID MANAGER", True, TITLE_SHADOW)
        tx = LOW_W // 2 - title.get_width() // 2
        frame.blit(shadow, (tx + 1, 25))
        frame.blit(title, (tx, 24))
        # short enough to survive the cover-crop at wide window aspects
        tag = self.font_small.render("Balance a living power grid.", True, TAGLINE_COLOR)
        frame.blit(tag, (LOW_W // 2 - tag.get_width() // 2, 24 + title.get_height() + 4))

        # blinking prompt on the ground band (~1 Hz)
        if (t % 1.0) < 0.62:
            prompt = self.font_small.render("PRESS ANY KEY", True, PROMPT_COLOR)
            frame.blit(prompt, (LOW_W // 2 - prompt.get_width() // 2, HORIZON + 9))

        # one-time fade-in from black on first show
        fade = 1.0 - min(1.0, (t - self._t0) / 1.5)
        if fade > 0:
            veil = pygame.Surface((LOW_W, LOW_H))
            veil.fill((0, 0, 0))
            veil.set_alpha(int(255 * fade))
            frame.blit(veil, (0, 0))

        # nearest-neighbor upscale to COVER the window (square pixels, centered
        # crop) — smoothscale would defeat the whole 16-bit point
        w, h = surface.get_size()
        scale = max(w / LOW_W, h / LOW_H)
        tw, th = int(LOW_W * scale + 0.5), int(LOW_H * scale + 0.5)
        surface.blit(pygame.transform.scale(frame, (tw, th)),
                     ((w - tw) // 2, (h - th) // 2))
