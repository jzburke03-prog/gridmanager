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
from ui import assets
from ui import pixel_art as pa
from ui.splash import PixelSplash

# scenario id -> scenario_cards/<file>.png (thematic; elliott reuses blackout)
_SCENARIO_CARD = {
    "uri": "blackout", "ca_heat_2020": "heatwave", "ne_cold_2018": "fuel_shortage",
    "spp_2021": "renewable_transition", "elliott": "blackout",
}

# palette (matches the in-game dark UI)
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

# one-level-up map for Esc / the breadcrumb toolbar (FETCHING backs out to
# wherever the fetch was started from — see go_back)
_PARENT = {MODE: TITLE, FREEPLAY: MODE, SCENARIOS: MODE}
_SCREEN_NAMES = {TITLE: "TITLE", MODE: "MODE", FREEPLAY: "FREE PLAY",
                 SCENARIOS: "SCENARIOS", FETCHING: "FETCHING"}


class MenuSystem:
    def __init__(self, font, font_small, font_big, font_title):
        self.font = font
        self.font_small = font_small
        self.font_big = font_big
        self.font_title = font_title
        self.splash = PixelSplash(font, font_small)

        self.active = True
        self.state = TITLE
        self.result_config = None

        # free-play selections: option 0 is the synthetic national Standard grid,
        # the rest are EIA regions
        self.freeplay_options = [None] + scenarios.REGIONS
        self.sel_option = 0
        self.sel_difficulty = "moderate"
        self.sel_date = min(_MAX_DATE, datetime.date(2024, 8, 14))
        self.cal_view = self.sel_date.replace(day=1)   # month shown by the calendar
        self._year_picker_open = False   # calendar header click -> pick a year fast
        self.events_enabled = True   # title-screen toggle: random grid events

        self._targets = []           # [(rect, action)] rebuilt every draw
        self._mouse = (0, 0)
        self._t = 0.0

        # async EIA fetch. _fetch_id orphans in-flight fetches when the player
        # backs out mid-spinner: the worker thread captures the id and only
        # publishes its result while it is still the current fetch.
        self._pending = None
        self._fetch_label = ""
        self._fetch_id = 0
        self._fetch_from = MODE      # screen the current fetch started from
        self._launch_state = None    # screen the last game was launched from

    # -- lifecycle ---------------------------------------------------------
    def open_menu(self):
        """Return to the front end (e.g. from a finished/failed game). Reopens
        on the screen the game was launched from, selections intact, so backing
        out of a run doesn't mean re-navigating from the title."""
        self.active = True
        self.state = self._launch_state if self._launch_state is not None else TITLE
        self.result_config = None
        self._pending = None

    def go_back(self) -> bool:
        """Step one screen up. Returns False when already at TITLE — the caller
        decides whether that quits the app."""
        if self.state == FETCHING:
            self._cancel_fetch()
            self.state = self._fetch_from
            return True
        if self.state == TITLE:
            return False
        self.state = _PARENT.get(self.state, TITLE)
        return True

    def _cancel_fetch(self):
        self._fetch_id += 1
        self._pending = None

    def take_config(self):
        cfg = self.result_config
        if cfg is not None:
            cfg.events_enabled = self.events_enabled   # carry the title toggle in
            self.result_config = None
            self.active = False
        return cfg

    # -- events / update ---------------------------------------------------
    def handle_event(self, event):
        if not self.active:
            return
        if event.type == pygame.MOUSEMOTION:
            self._mouse = event.pos
        elif event.type == pygame.KEYDOWN and self.state == TITLE:
            # intro screen: any key advances (Esc never reaches here — main.py
            # routes it to go_back/quit first)
            self._do(("goto", MODE))
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, action in self._targets:
                if rect.collidepoint(event.pos):
                    self._do(action)
                    return
            if self.state == TITLE:  # a stray click on the intro also advances
                self._do(("goto", MODE))

    def update(self, dt):
        self._t += dt
        if self.state == FETCHING and self._pending is not None:
            self.result_config = self._pending
            self._pending = None

    def _do(self, action):
        kind = action[0]
        if kind == "goto":
            if self.state == FETCHING:   # breadcrumb click mid-spinner
                self._cancel_fetch()
            self.state = action[1]
        elif kind == "quit_to_title":
            self.state = TITLE
        elif kind == "option":
            self.sel_option = action[1]
        elif kind == "difficulty":
            self.sel_difficulty = action[1]
        elif kind == "cal_day":
            self.sel_date = action[1]
        elif kind == "cal_month":
            self._shift_month(action[1])
        elif kind == "cal_today":
            self.sel_date = _MAX_DATE
            self.cal_view = _MAX_DATE.replace(day=1)
        elif kind == "toggle_events":
            self.events_enabled = not self.events_enabled
        elif kind == "start_freeplay":
            self._start_freeplay()
        elif kind == "start_scenario":
            self._start_scenario(action[1])

    def _shift_month(self, delta):
        m = self.cal_view.month - 1 + delta
        y = self.cal_view.year + m // 12
        first = datetime.date(y, m % 12 + 1, 1)
        # clamp to the months the valid EIA date window actually spans
        lo, hi = _MIN_DATE.replace(day=1), _MAX_DATE.replace(day=1)
        self.cal_view = max(lo, min(hi, first))

    # -- start a run -------------------------------------------------------
    def _start_freeplay(self):
        self._launch_state = FREEPLAY
        opt = self.freeplay_options[self.sel_option]
        if opt is None:  # Standard national grid — synthetic, no network
            self.result_config = scenarios.make_standard(self.sel_date, self.sel_difficulty)
            self.active = False
            return
        self._begin_fetch(f"Fetching {opt.label} · {self.sel_date:%d %b %Y}",
                          lambda: scenarios.make_region(opt, self.sel_date, self.sel_difficulty))

    def _start_scenario(self, idx):
        self._launch_state = SCENARIOS
        sc = scenarios.SCENARIOS[idx]
        self._begin_fetch(f"Loading {sc.title} · {sc.date:%d %b %Y}",
                          lambda: scenarios.make_scenario(sc))

    def _begin_fetch(self, label, builder):
        self._fetch_from = self.state
        self.state = FETCHING
        self._fetch_label = label
        self._pending = None
        self._fetch_id += 1
        fid = self._fetch_id

        def work():
            result = builder()
            if fid == self._fetch_id:  # ignore fetches the player backed out of
                self._pending = result

        threading.Thread(target=work, daemon=True).start()

    # -- drawing -----------------------------------------------------------
    def draw(self, surface):
        self._targets = []
        if self.state != TITLE:   # TITLE runs the full animated splash itself
            self.splash.draw_backdrop(surface)
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
        # 16-bit pixel intro scene (owns the title text and full background)
        self.splash.draw(surface, self._t)
        self._btn(surface, pygame.Rect(cx - 120, h // 2 - 24, 240, 60), "PLAY",
                  ("goto", MODE), accent=ACCENT, big=True)
        tip = self.font_small.render("Esc to quit · any key to start", True, DIM)
        surface.blit(tip, (cx - tip.get_width() // 2, h // 2 + 56))

        # random-events toggle (click to flip; carried into the run's RunConfig)
        er = pygame.Rect(cx - 95, h // 2 + 84, 190, 34)
        on = self.events_enabled
        ecol = GOOD if on else (150, 158, 176)
        hover = er.collidepoint(self._mouse)
        _pixel_panel(surface, er, PANEL_HI if hover else PANEL, ecol, width=2)
        etxt = self.font.render(f"EVENTS: {'ON' if on else 'OFF'}", True, ecol)
        surface.blit(etxt, (er.centerx - etxt.get_width() // 2, er.centery - etxt.get_height() // 2))
        self._targets.append((er, ("toggle_events",)))

    def _draw_mode(self, surface):
        w, h = surface.get_size()
        cx = w // 2
        self._header(surface, "SELECT MODE", None)
        col_w, col_h, gap = 320, 224, 40
        left = pygame.Rect(cx - col_w - gap // 2, h // 2 - col_h // 2, col_w, col_h)
        right = pygame.Rect(cx + gap // 2, h // 2 - col_h // 2, col_w, col_h)
        self._card(surface, left, "FREE PLAY", ACCENT,
                   ["Pick any region and date.", "Real EIA grid data seeds",
                    "the day. Or play the national", "Standard grid."],
                   ("goto", FREEPLAY), emblem="grid")
        self._card(surface, right, "SCENARIOS", ACCENT_WARM,
                   ["Relive historic moments of", "grid stress — winter storms,",
                    "heat waves, deep freezes.", "Can you keep the lights on?"],
                   ("goto", SCENARIOS), emblem="flame")
        self._toolbar(surface)

    def _draw_freeplay(self, surface):
        w, h = surface.get_size()
        self._header(surface, "FREE PLAY", "Region · Difficulty · Date")
        # region tiles grid (Standard + 7 regions), two columns each side of the
        # calendar so the layout reads like a console character-select screen
        tile_w, tile_h, gapx, gapy = 250, 92, 16, 14
        col_x = [w // 2 - tile_w - 300, w // 2 + 300]
        y0 = 150
        for i, opt in enumerate(self.freeplay_options):
            side = i % 2
            row = i // 2
            r = pygame.Rect(col_x[side], y0 + row * (tile_h + gapy), tile_w, tile_h)
            label = "Standard (National)" if opt is None else opt.label
            blurb = "1000 MW · synthetic seasonal" if opt is None else opt.blurb
            code = None if opt is None else opt.code
            self._tile(surface, r, label, blurb, selected=(i == self.sel_option),
                       action=("option", i), code=code)
        # calendar sits in the centre column, vertically centred on the tiles
        self._calendar(surface, w // 2, y0 + 80)
        # difficulty row below everything
        dy = y0 + 4 * (tile_h + gapy) + 26
        self._difficulty_row(surface, w // 2, dy)
        # elevated START button
        self._start_button(surface, pygame.Rect(w // 2 - 135, h - 92, 270, 58))
        self._toolbar(surface)

    def _draw_scenarios(self, surface):
        w, h = surface.get_size()
        self._header(surface, "SCENARIOS", "Historic grid-stress events")
        card_w = min(760, w - 120)
        x0 = w // 2 - card_w // 2
        y = 132
        for i, sc in enumerate(scenarios.SCENARIOS):
            r = pygame.Rect(x0, y, card_w, 120)
            self._scenario_card(surface, r, sc, ("start_scenario", i))
            y += 130
        self._toolbar(surface)

    def _draw_fetching(self, surface):
        w, h = surface.get_size()
        # walking hard-hat worker mascot above the text
        frames = assets.tech_frames(assets.OPERATOR, 160)
        mascot = frames[int(self._t * 6) % 4]
        surface.blit(mascot, (w // 2 - mascot.get_width() // 2, h // 2 - 90 - mascot.get_height()))
        dots = "." * (1 + int(self._t * 3) % 3)
        text = "Fetching grid & weather data" + dots
        mw = self.font_big.size(text)[0]
        _pixel_text(surface, self.font_big, text, (w // 2 - mw // 2, h // 2 - 30), TEXT)
        sub = self.font_small.render(self._fetch_label, True, DIM)
        surface.blit(sub, (w // 2 - sub.get_width() // 2, h // 2 + 6))
        # indeterminate progress bar cycling through the pack's fill states
        pct = ("empty", "25", "50", "75", "100")[int(self._t * 2.5) % 5]
        bar = assets.scaled(f"progress/progress_bar_{pct}.png", (128, 24))
        surface.blit(bar, (w // 2 - bar.get_width() // 2, h // 2 + 40))
        self._toolbar(surface)

    # -- widgets -----------------------------------------------------------
    def _header(self, surface, title, sub):
        w = surface.get_width()
        tw = self.font_big.size(title)[0]
        _pixel_text(surface, self.font_big, title, (w // 2 - tw // 2, 54), TEXT)
        if sub:
            sw = self.font_small.size(sub)[0]
            _pixel_text(surface, self.font_small, sub,
                        (w // 2 - sw // 2, 54 + self.font_big.get_height() + 4), DIM)

    def _btn(self, surface, rect, label, action, *, accent=ACCENT, big=False):
        hover = rect.collidepoint(self._mouse)
        base = tuple(min(255, c + (28 if hover else 0)) for c in accent)
        _pixel_panel(surface, rect, base, (255, 255, 255) if hover else _shade(base, 0.45))
        f = self.font_big if big else self.font
        t = f.render(label, True, (12, 16, 24))
        surface.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))
        self._targets.append((rect, action))

    def _card(self, surface, rect, title, accent, lines, action, emblem=None):
        hover = rect.collidepoint(self._mouse)
        _pixel_panel(surface, rect, PANEL_HI if hover else PANEL, accent, width=3 if hover else 2)
        if emblem:
            emb = pa.emblem(emblem, scale=3)
            surface.blit(emb, (rect.centerx - emb.get_width() // 2, rect.top + 18))
        tw = self.font_big.size(title)[0]
        _pixel_text(surface, self.font_big, title, (rect.centerx - tw // 2, rect.top + 68), accent)
        y = rect.top + 118
        for ln in lines:
            s = self.font_small.render(ln, True, DIM)
            surface.blit(s, (rect.centerx - s.get_width() // 2, y))
            y += s.get_height() + 4
        self._targets.append((rect, action))

    def _tile(self, surface, rect, label, blurb, selected, action, code=None):
        hover = rect.collidepoint(self._mouse)
        bg = PANEL_HI if (hover or selected) else PANEL
        edge = GOOD if selected else (ACCENT if hover else BORDER)
        _pixel_panel(surface, rect, bg, edge, width=3 if selected else 2)
        # region emblem on the left, text to its right
        emb = pa.region_emblem(code, scale=3)
        surface.blit(emb, (rect.left + 12, rect.centery - emb.get_height() // 2))
        tx = rect.left + 12 + emb.get_width() + 12
        tw = rect.right - tx - 12
        t = _pixel_text(surface, self.font, _fit(self.font, label, tw), (tx, rect.top + 14), TEXT)
        by = rect.top + 14 + t.get_height() + 6
        for ln in _wrap(self.font_small, blurb, tw, max_lines=2):
            s = self.font_small.render(ln, True, DIM)
            surface.blit(s, (tx, by))
            by += s.get_height() + 2
        self._targets.append((rect, action))

    def _difficulty_row(self, surface, cx, y):
        lw = self.font_small.size("DIFFICULTY")[0]
        _pixel_text(surface, self.font_small, "DIFFICULTY", (cx - lw // 2, y - 22), DIM)
        keys = scenarios.DIFFICULTY_ORDER
        bw, gap = 150, 12
        total = len(keys) * bw + (len(keys) - 1) * gap
        x = cx - total // 2
        for k in keys:
            d = scenarios.DIFFICULTIES[k]
            r = pygame.Rect(x, y, bw, 46)
            sel = (k == self.sel_difficulty)
            accent = _DIFF_ACCENT[k]
            # tab art (active when selected), difficulty icon + name composited on
            tab = "active" if sel else "inactive"
            surface.blit(assets.scaled(f"tabs/scenario_tab_{tab}.png", (bw, 46)), r.topleft)
            ico = pa.difficulty_icon(k, accent if sel else _shade(accent, 0.8), scale=2)
            surface.blit(ico, (r.left + 12, r.centery - ico.get_height() // 2))
            t = self.font.render(d.name, True, accent if sel else TEXT)
            surface.blit(t, (r.left + 14 + ico.get_width() + 8, r.centery - t.get_height() // 2))
            self._targets.append((r, ("difficulty", k)))
            x += bw + gap
        # blurb for the current difficulty
        d = scenarios.DIFFICULTIES[self.sel_difficulty]
        b = self.font_small.render(d.blurb, True, DIM)
        surface.blit(b, (cx - b.get_width() // 2, y + 52))

    def _calendar(self, surface, cx, top):
        """Real month calendar: prev/next-month arrows, a Sunday-first weekday
        grid, the selected day highlighted, days outside the valid EIA window
        greyed and unclickable."""
        view = self.cal_view
        cell = 44
        tile = 40
        grid_w = 7 * cell
        left = cx - grid_w // 2
        lw = self.font_small.size("DATE")[0]
        _pixel_text(surface, self.font_small, "DATE", (cx - lw // 2, top - 22), DIM)

        # header bar with month/year, the month arrows, and a "today" jump
        header = pygame.Rect(left, top, grid_w, 34)
        _pixel_panel(surface, header, PANEL_HI, BORDER, shadow=False)
        title = view.strftime("%B %Y")
        tw = self.font.size(title)[0]
        _pixel_text(surface, self.font, title, (cx - tw // 2, top + 8), TEXT)
        lo, hi = _MIN_DATE.replace(day=1), _MAX_DATE.replace(day=1)
        if view > lo:
            self._cal_button(surface, "calendar/calendar_prev_button.png",
                             pygame.Rect(left + 3, top + 1, 32, 32), ("cal_month", -1))
        if view < hi:
            self._cal_button(surface, "calendar/calendar_next_button.png",
                             pygame.Rect(header.right - 35, top + 1, 32, 32), ("cal_month", 1))
        self._cal_button(surface, "calendar/calendar_today_button.png",
                         pygame.Rect(header.right + 6, top + 1, 48, 32), ("cal_today",))

        # weekday header
        wy = top + 40
        for i, wd in enumerate(("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")):
            s = self.font_small.render(wd, True, DIM)
            surface.blit(s, (left + i * cell + cell // 2 - s.get_width() // 2, wy))

        # day cells: pixel-art tiles, selected/disabled variants, hover highlight
        gy = wy + 20
        start_col = (view.weekday() + 1) % 7   # Monday=0 -> Sunday-first column
        days = _days_in_month(view.year, view.month)
        for day in range(1, days + 1):
            idx = start_col + day - 1
            tx = left + (idx % 7) * cell + (cell - tile) // 2
            ty = gy + (idx // 7) * cell
            r = pygame.Rect(tx, ty, tile, tile)
            date = datetime.date(view.year, view.month, day)
            enabled = _MIN_DATE <= date <= _MAX_DATE
            if date == self.sel_date:
                art, col = "calendar/day_tile_selected.png", (12, 18, 30)
            elif not enabled:
                art, col = "calendar/day_tile_disabled.png", (90, 98, 116)
            else:
                art, col = "calendar/day_tile.png", TEXT
            surface.blit(assets.scaled(art, (tile, tile)), (tx, ty))
            if enabled and date != self.sel_date and r.collidepoint(self._mouse):
                surface.blit(assets.scaled("selection/selection_highlight.png", (tile, tile)), (tx, ty))
            num = self.font_small.render(str(day), True, col)
            surface.blit(num, (r.centerx - num.get_width() // 2, r.centery - num.get_height() // 2))
            if enabled:
                self._targets.append((r, ("cal_day", date)))

    def _cal_button(self, surface, art, rect, action):
        surface.blit(assets.scaled(art, rect.size), rect.topleft)
        self._targets.append((rect, action))

    def _start_button(self, surface, rect):
        """Marquee START button: pulsing glow, chunky pixel bevel, play glyph."""
        hover = rect.collidepoint(self._mouse)
        pulse = int(70 + 45 * abs(math.sin(self._t * 2.0)))
        for i, a in enumerate((pulse, pulse // 2)):
            gr = rect.inflate(10 + i * 12, 10 + i * 12)
            gs = pygame.Surface(gr.size, pygame.SRCALPHA)
            gs.fill((*GOOD, a))
            surface.blit(gs, gr.topleft)
        base = tuple(min(255, c + (30 if hover else 0)) for c in GOOD)
        _pixel_panel(surface, rect, base, (255, 255, 255) if hover else _shade(base, 0.45))
        glyph = pa.play_glyph((14, 22, 16), scale=4)
        lbl = self.font_big.render("START GRID", True, (12, 16, 24))
        total = glyph.get_width() + 12 + lbl.get_width()
        gx = rect.centerx - total // 2
        surface.blit(glyph, (gx, rect.centery - glyph.get_height() // 2))
        surface.blit(lbl, (gx + glyph.get_width() + 12, rect.centery - lbl.get_height() // 2))
        self._targets.append((rect, ("start_freeplay",)))

    def _scenario_card(self, surface, rect, sc, action):
        hover = rect.collidepoint(self._mouse)
        accent = _DIFF_ACCENT[sc.difficulty_key]
        _pixel_panel(surface, rect, PANEL_HI if hover else PANEL,
                     accent if hover else BORDER, width=2)
        # scenario card art thumbnail on the left; text block to its right
        tx = rect.left + 18
        card_name = _SCENARIO_CARD.get(sc.id)
        if card_name:
            thumb = assets.scaled(f"scenario_cards/{card_name}_scenario_card.png",
                                  (78, 104), smooth=True)
            surface.blit(thumb, (rect.left + 8, rect.centery - thumb.get_height() // 2))
            tx = rect.left + 8 + thumb.get_width() + 14
        t = _pixel_text(surface, self.font_big, sc.title, (tx, rect.top + 22), TEXT)
        s = self.font_small.render(sc.subtitle, True, accent)
        surface.blit(s, (tx, rect.top + 22 + t.get_height() + 4))
        d = scenarios.DIFFICULTIES[sc.difficulty_key]
        tag = self.font_small.render(d.name.upper(), True, accent)
        pill = pygame.Rect(rect.right - tag.get_width() - 34, rect.centery - 13, tag.get_width() + 20, 26)
        surface.fill(_shade(accent, 0.22), pill)
        pygame.draw.rect(surface, accent, pill, width=1)
        surface.blit(tag, (pill.centerx - tag.get_width() // 2, pill.centery - tag.get_height() // 2))
        self._targets.append((rect, action))

    def _toolbar(self, surface):
        """Breadcrumb strip at top-left: TITLE › MODE › <here>. Every crumb but
        the current screen is clickable, so the player can jump between menus
        instead of only stepping one level with Esc."""
        anchor = self._fetch_from if self.state == FETCHING else self.state
        chain = [anchor]
        while chain[0] in _PARENT:
            chain.insert(0, _PARENT[chain[0]])
        if self.state == FETCHING:
            chain.append(FETCHING)

        x, y = 28, 22
        for i, screen in enumerate(chain):
            last = i == len(chain) - 1
            t = self.font_small.render(_SCREEN_NAMES[screen], True, TEXT if last else DIM)
            r = pygame.Rect(x - 6, y - 4, t.get_width() + 12, t.get_height() + 8)
            if not last:
                if r.collidepoint(self._mouse):
                    surface.fill(PANEL_HI, r)
                    t = self.font_small.render(_SCREEN_NAMES[screen], True, ACCENT)
                self._targets.append((r, ("goto", screen)))
            surface.blit(self.font_small.render(_SCREEN_NAMES[screen], True, (6, 8, 16)), (x + 1, y + 1))
            surface.blit(t, (x, y))
            x += t.get_width() + 10
            if not last:
                sep = self.font_small.render("›", True, DIM)
                surface.blit(sep, (x, y))
                x += sep.get_width() + 10
        hint = self.font_small.render("Esc ‹ back", True, DIM)
        surface.blit(hint, (x + 14, y))


# -- helpers ----------------------------------------------------------------
def _days_in_month(y, m):
    if m == 12:
        return 31
    return (datetime.date(y, m + 1, 1) - datetime.timedelta(days=1)).day


def _shade(color, f):
    """Scale an RGB toward black (<1) or white-ish (>1) for bevel edges."""
    return tuple(max(0, min(255, int(c * f))) for c in color[:3])


def _shadow(surface, rect):
    """Soft hard-offset drop shadow — the chunky depth cue that reads as a
    16-bit UI panel rather than a flat modern card."""
    sh = pygame.Surface(rect.size, pygame.SRCALPHA)
    sh.fill((0, 0, 0, 95))
    surface.blit(sh, rect.topleft)


def _pixel_panel(surface, rect, fill, edge, *, width=2, shadow=True):
    """Flat-filled panel with square corners, a light/dark bevel and a chunky
    border. Deliberately no border_radius — rounded corners are what made the
    old menus read as a generic default UI."""
    if shadow:
        _shadow(surface, rect.move(5, 5))
    surface.fill(fill, rect)
    light, dark = _shade(fill, 1.5), _shade(fill, 0.55)
    pygame.draw.line(surface, light, (rect.left, rect.top), (rect.right - 1, rect.top))
    pygame.draw.line(surface, light, (rect.left, rect.top), (rect.left, rect.bottom - 1))
    pygame.draw.line(surface, dark, (rect.left, rect.bottom - 1), (rect.right - 1, rect.bottom - 1))
    pygame.draw.line(surface, dark, (rect.right - 1, rect.top), (rect.right - 1, rect.bottom - 1))
    pygame.draw.rect(surface, edge, rect, width=width)


def _pixel_text(surface, font, text, pos, color, shadow=(6, 8, 16)):
    """Text with a 2px hard drop shadow so headings stay legible over the
    pixel backdrop and pick up the same chunky look. Returns the rendered
    glyph surface for height/width use by callers."""
    surface.blit(font.render(text, True, shadow), (pos[0] + 2, pos[1] + 2))
    t = font.render(text, True, color)
    surface.blit(t, pos)
    return t


def _fit(font, text, max_w):
    """Truncate text with an ellipsis so it fits max_w pixels."""
    if font.size(text)[0] <= max_w:
        return text
    while text and font.size(text + "…")[0] > max_w:
        text = text[:-1]
    return text + "…"


def _wrap(font, text, max_w, max_lines):
    """Greedy word wrap into at most max_lines lines. If the text needs more
    lines than that, the last line carries the remainder ellipsis-truncated."""
    words = text.split()
    lines = []
    cur = ""
    for i, word in enumerate(words):
        trial = f"{cur} {word}".strip()
        if cur and font.size(trial)[0] > max_w:
            if len(lines) == max_lines - 1:
                lines.append(_fit(font, " ".join([cur] + words[i:]), max_w))
                return lines
            lines.append(_fit(font, cur, max_w))
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(_fit(font, cur, max_w))
    return lines
