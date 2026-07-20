"""Front-end menu flow that runs before (and between) game sessions:

    TITLE ─▶ MODE ─┬─▶ FREE PLAY  (region + date + difficulty) ─▶ FETCH ─▶ game
                   └─▶ SCENARIOS  (curated historical grid crises) ─▶ FETCH ─▶ game

MenuSystem owns all the pre-game screens. It draws itself full-screen, hit-tests
clicks against buttons it rebuilds each frame, and — when the player commits —
produces a scenarios.RunConfig for main.py to hand to a fresh GameState. Region
and scenario picks need a live EIA pull, which runs on a daemon thread so the
menu keeps animating a "fetching…" screen instead of freezing.
"""
import datetime
import math
import threading

import pygame

import scenarios

# palette (matches the in-game dark UI)
BG_TOP = (16, 22, 38)
BG_BOT = (10, 14, 24)
PANEL = (28, 36, 56)
PANEL_HI = (40, 52, 80)
BORDER = (60, 74, 108)
TEXT = (222, 228, 240)
DIM = (150, 160, 182)
ACCENT = (90, 170, 240)
ACCENT_WARM = (240, 180, 90)
GOOD = (110, 220, 160)

_DIFF_ACCENT = {
    "easy": (110, 210, 150),
    "moderate": (120, 180, 240),
    "hard": (240, 180, 90),
    "expert": (240, 110, 90),
}

# playable EIA date window: v2 hourly data starts July 2018; there's a ~1 day
# publication lag, so cap the selectable date a couple days back.
_MIN_DATE = datetime.date(2019, 1, 1)
_MAX_DATE = datetime.date.today() - datetime.timedelta(days=2)

TITLE, MODE, FREEPLAY, SCENARIOS, FETCHING = range(5)


class MenuSystem:
    def __init__(self, font, font_small, font_big, font_title):
        self.font = font
        self.font_small = font_small
        self.font_big = font_big
        self.font_title = font_title

        self.active = True
        self.state = TITLE
        self.result_config = None

        # free-play selections: option 0 is the synthetic national Standard grid,
        # the rest are EIA regions
        self.freeplay_options = [None] + scenarios.REGIONS
        self.sel_option = 0
        self.sel_difficulty = "moderate"
        self.sel_date = min(_MAX_DATE, datetime.date(2024, 8, 14))

        self._targets = []           # [(rect, action)] rebuilt every draw
        self._mouse = (0, 0)
        self._t = 0.0

        # async EIA fetch
        self._pending = None
        self._fetch_label = ""

    # -- lifecycle ---------------------------------------------------------
    def open_menu(self):
        """Return to the front end (e.g. from a finished/failed game)."""
        self.active = True
        self.state = TITLE
        self.result_config = None
        self._pending = None

    def take_config(self):
        cfg = self.result_config
        if cfg is not None:
            self.result_config = None
            self.active = False
        return cfg

    # -- events / update ---------------------------------------------------
    def handle_event(self, event):
        if not self.active:
            return
        if event.type == pygame.MOUSEMOTION:
            self._mouse = event.pos
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, action in self._targets:
                if rect.collidepoint(event.pos):
                    self._do(action)
                    return

    def update(self, dt):
        self._t += dt
        if self.state == FETCHING and self._pending is not None:
            self.result_config = self._pending
            self._pending = None

    def _do(self, action):
        kind = action[0]
        if kind == "goto":
            self.state = action[1]
        elif kind == "quit_to_title":
            self.state = TITLE
        elif kind == "option":
            self.sel_option = action[1]
        elif kind == "difficulty":
            self.sel_difficulty = action[1]
        elif kind == "date":
            self._step_date(action[1], action[2])
        elif kind == "start_freeplay":
            self._start_freeplay()
        elif kind == "start_scenario":
            self._start_scenario(action[1])

    def _step_date(self, field, delta):
        d = self.sel_date
        try:
            if field == "day":
                d = d + datetime.timedelta(days=delta)
            elif field == "month":
                m = d.month - 1 + delta
                y = d.year + m // 12
                m = m % 12 + 1
                day = min(d.day, _days_in_month(y, m))
                d = datetime.date(y, m, day)
            elif field == "year":
                y = d.year + delta
                day = min(d.day, _days_in_month(y, d.month))
                d = datetime.date(y, d.month, day)
        except ValueError:
            return
        self.sel_date = max(_MIN_DATE, min(_MAX_DATE, d))

    # -- start a run -------------------------------------------------------
    def _start_freeplay(self):
        opt = self.freeplay_options[self.sel_option]
        if opt is None:  # Standard national grid — synthetic, no network
            self.result_config = scenarios.make_standard(self.sel_date, self.sel_difficulty)
            self.active = False
            return
        self._begin_fetch(f"Fetching {opt.label} · {self.sel_date:%d %b %Y}",
                          lambda: scenarios.make_region(opt, self.sel_date, self.sel_difficulty))

    def _start_scenario(self, idx):
        sc = scenarios.SCENARIOS[idx]
        self._begin_fetch(f"Loading {sc.title} · {sc.date:%d %b %Y}",
                          lambda: scenarios.make_scenario(sc))

    def _begin_fetch(self, label, builder):
        self.state = FETCHING
        self._fetch_label = label
        self._pending = None

        def work():
            self._pending = builder()

        threading.Thread(target=work, daemon=True).start()

    # -- drawing -----------------------------------------------------------
    def draw(self, surface):
        self._targets = []
        _vgradient(surface, BG_TOP, BG_BOT)
        if self.state == TITLE:
            self._draw_title(surface)
        elif self.state == MODE:
            self._draw_mode(surface)
        elif self.state == FREEPLAY:
            self._draw_freeplay(surface)
        elif self.state == SCENARIOS:
            self._draw_scenarios(surface)
        elif self.state == FETCHING:
            self._draw_fetching(surface)

    def _draw_title(self, surface):
        w, h = surface.get_size()
        cx = w // 2
        title = self.font_title.render("GRID MANAGER", True, TEXT)
        title_y = h // 2 - 185
        surface.blit(title, (cx - title.get_width() // 2, title_y))
        sub = self.font.render("Balance supply against a living demand curve.", True, DIM)
        # anchor below the title's real rendered box so the two never collide
        surface.blit(sub, (cx - sub.get_width() // 2, title_y + title.get_height() + 10))
        self._btn(surface, pygame.Rect(cx - 120, h // 2 - 24, 240, 60), "PLAY",
                  ("goto", MODE), accent=ACCENT, big=True)
        tip = self.font_small.render("Esc to quit", True, DIM)
        surface.blit(tip, (cx - tip.get_width() // 2, h // 2 + 60))

    def _draw_mode(self, surface):
        w, h = surface.get_size()
        cx = w // 2
        self._header(surface, "SELECT MODE", None)
        col_w, col_h, gap = 320, 200, 40
        left = pygame.Rect(cx - col_w - gap // 2, h // 2 - col_h // 2, col_w, col_h)
        right = pygame.Rect(cx + gap // 2, h // 2 - col_h // 2, col_w, col_h)
        self._card(surface, left, "FREE PLAY", ACCENT,
                   ["Pick any region and date.", "Real EIA grid data seeds",
                    "the day. Or play the national", "Standard grid."],
                   ("goto", FREEPLAY))
        self._card(surface, right, "SCENARIOS", ACCENT_WARM,
                   ["Relive historic moments of", "grid stress — winter storms,",
                    "heat waves, deep freezes.", "Can you keep the lights on?"],
                   ("goto", SCENARIOS))
        self._back(surface, ("goto", TITLE))

    def _draw_freeplay(self, surface):
        w, h = surface.get_size()
        self._header(surface, "FREE PLAY", "Region · Date · Difficulty")
        # region tiles grid (Standard + 7 regions)
        cols, tile_w, tile_h, gapx, gapy = 4, 250, 74, 16, 14
        grid_w = cols * tile_w + (cols - 1) * gapx
        x0 = w // 2 - grid_w // 2
        y0 = 150
        for i, opt in enumerate(self.freeplay_options):
            r = pygame.Rect(x0 + (i % cols) * (tile_w + gapx),
                            y0 + (i // cols) * (tile_h + gapy), tile_w, tile_h)
            label = "Standard (National)" if opt is None else opt.label
            blurb = "1000 MW · synthetic seasonal" if opt is None else opt.blurb
            self._tile(surface, r, label, blurb, selected=(i == self.sel_option),
                       action=("option", i))
        # difficulty row
        dy = y0 + 2 * (tile_h + gapy) + 24
        self._difficulty_row(surface, w // 2, dy)
        # date stepper
        self._date_stepper(surface, w // 2, dy + 92)
        # start
        self._btn(surface, pygame.Rect(w // 2 - 110, h - 96, 220, 52), "START GRID",
                  ("start_freeplay",), accent=GOOD, big=True)
        self._back(surface, ("goto", MODE))

    def _draw_scenarios(self, surface):
        w, h = surface.get_size()
        self._header(surface, "SCENARIOS", "Historic grid-stress events")
        card_w = min(760, w - 120)
        x0 = w // 2 - card_w // 2
        y = 140
        for i, sc in enumerate(scenarios.SCENARIOS):
            r = pygame.Rect(x0, y, card_w, 88)
            self._scenario_card(surface, r, sc, ("start_scenario", i))
            y += 98
        self._back(surface, ("goto", MODE))

    def _draw_fetching(self, surface):
        w, h = surface.get_size()
        dots = "." * (1 + int(self._t * 3) % 3)
        msg = self.font_big.render("Contacting EIA" + dots, True, TEXT)
        surface.blit(msg, (w // 2 - msg.get_width() // 2, h // 2 - 30))
        sub = self.font_small.render(self._fetch_label, True, DIM)
        surface.blit(sub, (w // 2 - sub.get_width() // 2, h // 2 + 6))
        # spinner
        cx, cy = w // 2, h // 2 + 60
        for k in range(8):
            a = self._t * 4 + k * math.pi / 4
            alpha = 60 + int(195 * (k / 8.0))
            px, py = cx + math.cos(a) * 16, cy + math.sin(a) * 16
            pygame.draw.circle(surface, (alpha, alpha, alpha), (int(px), int(py)), 3)

    # -- widgets -----------------------------------------------------------
    def _header(self, surface, title, sub):
        w = surface.get_width()
        t = self.font_big.render(title, True, TEXT)
        surface.blit(t, (w // 2 - t.get_width() // 2, 54))
        if sub:
            s = self.font_small.render(sub, True, DIM)
            surface.blit(s, (w // 2 - s.get_width() // 2, 54 + t.get_height() + 4))

    def _btn(self, surface, rect, label, action, *, accent=ACCENT, big=False):
        hover = rect.collidepoint(self._mouse)
        base = tuple(min(255, c + (28 if hover else 0)) for c in accent)
        pygame.draw.rect(surface, base, rect, border_radius=10)
        pygame.draw.rect(surface, (255, 255, 255) if hover else BORDER, rect, width=2, border_radius=10)
        f = self.font_big if big else self.font
        t = f.render(label, True, (12, 16, 24))
        surface.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))
        self._targets.append((rect, action))

    def _card(self, surface, rect, title, accent, lines, action):
        hover = rect.collidepoint(self._mouse)
        pygame.draw.rect(surface, PANEL_HI if hover else PANEL, rect, border_radius=12)
        pygame.draw.rect(surface, accent, rect, width=2 if not hover else 3, border_radius=12)
        t = self.font_big.render(title, True, accent)
        surface.blit(t, (rect.centerx - t.get_width() // 2, rect.top + 22))
        y = rect.top + 74
        for ln in lines:
            s = self.font_small.render(ln, True, DIM)
            surface.blit(s, (rect.centerx - s.get_width() // 2, y))
            y += s.get_height() + 4
        self._targets.append((rect, action))

    def _tile(self, surface, rect, label, blurb, selected, action):
        hover = rect.collidepoint(self._mouse)
        bg = PANEL_HI if (hover or selected) else PANEL
        pygame.draw.rect(surface, bg, rect, border_radius=8)
        edge = GOOD if selected else (BORDER if not hover else ACCENT)
        pygame.draw.rect(surface, edge, rect, width=3 if selected else 1, border_radius=8)
        t = self.font.render(_fit(self.font, label, rect.width - 18), True, TEXT)
        surface.blit(t, (rect.left + 12, rect.top + 12))
        s = self.font_small.render(_fit(self.font_small, blurb, rect.width - 18), True, DIM)
        surface.blit(s, (rect.left + 12, rect.top + 12 + t.get_height() + 6))
        self._targets.append((rect, action))

    def _difficulty_row(self, surface, cx, y):
        label = self.font_small.render("DIFFICULTY", True, DIM)
        surface.blit(label, (cx - label.get_width() // 2, y - 22))
        keys = scenarios.DIFFICULTY_ORDER
        bw, gap = 150, 12
        total = len(keys) * bw + (len(keys) - 1) * gap
        x = cx - total // 2
        for k in keys:
            d = scenarios.DIFFICULTIES[k]
            r = pygame.Rect(x, y, bw, 46)
            sel = (k == self.sel_difficulty)
            accent = _DIFF_ACCENT[k]
            hover = r.collidepoint(self._mouse)
            pygame.draw.rect(surface, PANEL_HI if (sel or hover) else PANEL, r, border_radius=8)
            pygame.draw.rect(surface, accent if sel else BORDER, r, width=3 if sel else 1, border_radius=8)
            t = self.font.render(d.name, True, accent if sel else TEXT)
            surface.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))
            self._targets.append((r, ("difficulty", k)))
            x += bw + gap
        # blurb for the current difficulty
        d = scenarios.DIFFICULTIES[self.sel_difficulty]
        b = self.font_small.render(d.blurb, True, DIM)
        surface.blit(b, (cx - b.get_width() // 2, y + 52))

    def _date_stepper(self, surface, cx, y):
        label = self.font_small.render("DATE", True, DIM)
        surface.blit(label, (cx - label.get_width() // 2, y - 22))
        d = self.sel_date
        fields = [("day", f"{d.day:02d}", 46), ("month", d.strftime("%b"), 60),
                  ("year", f"{d.year}", 74)]
        total = sum(f[2] for f in fields) + (len(fields) - 1) * 22 + 2 * 0
        x = cx - total // 2
        for field, text, fw in fields:
            up = pygame.Rect(x, y - 4, fw, 22)
            box = pygame.Rect(x, y + 20, fw, 30)
            down = pygame.Rect(x, y + 52, fw, 22)
            self._chevron(surface, up, "▲", ("date", field, 1))
            self._chevron(surface, down, "▼", ("date", field, -1))
            pygame.draw.rect(surface, PANEL, box, border_radius=6)
            pygame.draw.rect(surface, BORDER, box, width=1, border_radius=6)
            t = self.font.render(text, True, TEXT)
            surface.blit(t, (box.centerx - t.get_width() // 2, box.centery - t.get_height() // 2))
            x += fw + 22

    def _chevron(self, surface, rect, glyph, action):
        hover = rect.collidepoint(self._mouse)
        t = self.font_small.render(glyph, True, ACCENT if hover else DIM)
        surface.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))
        self._targets.append((rect, action))

    def _scenario_card(self, surface, rect, sc, action):
        hover = rect.collidepoint(self._mouse)
        pygame.draw.rect(surface, PANEL_HI if hover else PANEL, rect, border_radius=10)
        accent = _DIFF_ACCENT[sc.difficulty_key]
        pygame.draw.rect(surface, accent if hover else BORDER, rect, width=2 if hover else 1, border_radius=10)
        t = self.font_big.render(sc.title, True, TEXT)
        surface.blit(t, (rect.left + 18, rect.top + 12))
        s = self.font_small.render(sc.subtitle, True, accent)
        surface.blit(s, (rect.left + 18, rect.top + 12 + t.get_height() + 2))
        d = scenarios.DIFFICULTIES[sc.difficulty_key]
        tag = self.font_small.render(d.name.upper(), True, accent)
        pill = pygame.Rect(rect.right - tag.get_width() - 34, rect.centery - 13, tag.get_width() + 20, 26)
        pygame.draw.rect(surface, (accent[0] // 4, accent[1] // 4, accent[2] // 4), pill, border_radius=13)
        pygame.draw.rect(surface, accent, pill, width=1, border_radius=13)
        surface.blit(tag, (pill.centerx - tag.get_width() // 2, pill.centery - tag.get_height() // 2))
        self._targets.append((rect, action))

    def _back(self, surface, action):
        r = pygame.Rect(28, surface.get_height() - 60, 120, 40)
        hover = r.collidepoint(self._mouse)
        pygame.draw.rect(surface, PANEL_HI if hover else PANEL, r, border_radius=8)
        pygame.draw.rect(surface, BORDER, r, width=1, border_radius=8)
        t = self.font.render("‹ Back", True, TEXT)
        surface.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))
        self._targets.append((r, action))


# -- helpers ----------------------------------------------------------------
def _days_in_month(y, m):
    if m == 12:
        return 31
    return (datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)).day


def _vgradient(surface, top, bot):
    h = surface.get_height()
    for y in range(h):
        f = y / max(1, h - 1)
        col = (int(top[0] + (bot[0] - top[0]) * f),
               int(top[1] + (bot[1] - top[1]) * f),
               int(top[2] + (bot[2] - top[2]) * f))
        pygame.draw.line(surface, col, (0, y), (surface.get_width(), y))


def _fit(font, text, max_w):
    """Truncate text with an ellipsis so it fits max_w pixels."""
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "…")[0] > max_w:
        text = text[:-1]
    return text + "…"
