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

import game_state
import scenarios
from ui import assets
from ui import pixel_art as pa
from ui.splash import PixelSplash

# scenario id -> scenario_cards/<file>.png (thematic; elliott reuses blackout)
_SCENARIO_CARD = {
    "uri": "blackout", "ca_heat_2020": "heatwave", "ne_cold_2018": "fuel_shortage",
    "spp_2021": "renewable_transition", "elliott": "blackout",
}

# palette (industrial pixel console: brass, oxidized steel, signal lamps)
PANEL = (38, 45, 34)
PANEL_HI = (54, 62, 42)
BORDER = (116, 100, 70)
TEXT = (222, 228, 240)
DIM = (168, 166, 142)
ACCENT = (255, 211, 96)
ACCENT_WARM = (255, 142, 84)
GOOD = (110, 220, 160)

_DIFF_ACCENT = {
    "easy": (110, 210, 150),
    "moderate": (255, 211, 96),
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

# Instructional Mode has no configuration screen of its own — it launches
# straight from MODE with a fixed grid — so it never becomes a `state`.


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
        # Persisted completion marker, re-read whenever the menu reopens so
        # finishing a run updates the card without restarting the app.
        self._instructional_done = game_state.instructional_complete()

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
        self._instructional_done = game_state.instructional_complete()

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
        elif kind == "start_instructional":
            self._start_instructional()
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
    def _start_instructional(self):
        """Synthetic and fixed — no region, date, difficulty or network fetch.

        _launch_state is MODE rather than a screen of its own: backing out of the
        run has to land somewhere that exists, and Instructional has no
        configuration screen to return to.
        """
        self._launch_state = MODE
        self.result_config = scenarios.make_instructional()
        self.active = False

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
        dock_w = min(680, w - 88)
        dock = pygame.Rect(cx - dock_w // 2, h - 124, dock_w, 94)
        _notched_panel(surface, dock, (28, 36, 28), (88, 164, 112), width=2)

        status = self.font_small.render("SYSTEM READY", True, GOOD)
        surface.blit(status, (dock.left + 18, dock.top + 13))
        meter = pygame.Rect(dock.left + 18, dock.top + 32, 124, 6)
        pygame.draw.rect(surface, (30, 52, 38), meter)
        fill_w = 70 + int(40 * abs(math.sin(self._t * 1.7)))
        pygame.draw.rect(surface, GOOD, (meter.left, meter.top, fill_w, meter.height))
        pygame.draw.rect(surface, (82, 142, 100), meter, width=1)

        self._btn(surface, pygame.Rect(dock.centerx - 126, dock.top + 16, 252, 48),
                  "START DISPATCH", ("goto", MODE), accent=GOOD, big=False)

        # random-events toggle (click to flip; carried into the run's RunConfig)
        er = pygame.Rect(dock.right - 214, dock.top + 20, 184, 34)
        on = self.events_enabled
        ecol = GOOD if on else (150, 158, 176)
        hover = er.collidepoint(self._mouse)
        _pixel_panel(surface, er, PANEL_HI if hover else (35, 40, 30), ecol, width=2)
        lamp = pygame.Rect(er.left + 11, er.centery - 5, 10, 10)
        surface.fill(ecol, lamp)
        pygame.draw.rect(surface, _shade(ecol, 0.45), lamp, width=1)
        etxt = self.font_small.render(f"EVENTS {'ON' if on else 'OFF'}", True, ecol)
        surface.blit(etxt, (er.left + 30, er.centery - etxt.get_height() // 2))
        self._targets.append((er, ("toggle_events",)))

        tip = self.font_small.render("any key starts - Esc quits", True, (188, 194, 166))
        surface.blit(tip, (dock.centerx - tip.get_width() // 2, dock.bottom - 22))

    def _draw_mode(self, surface):
        w, h = surface.get_size()
        cx = w // 2
        self._header(surface, "CHOOSE YOUR SHIFT", "Pick the grid desk you want to run")
        board_w = min(880, w - 140)
        bay_h = 132 if h >= 760 else 116
        gap = 14
        board_h = bay_h * 3 + gap * 2 + 44
        board = pygame.Rect(cx - board_w // 2, 128, board_w, board_h)
        _notched_panel(surface, board, (24, 31, 26), (86, 104, 78), width=2)
        y = board.top + 22
        rects = [pygame.Rect(board.left + 24, y + i * (bay_h + gap),
                             board.width - 48, bay_h) for i in range(3)]

        done = self._instructional_done
        self._run_bay(surface, rects[0],
                      "TRAINING GRID" + ("  COMPLETE" if done else ""), GOOD,
                      "Four guided days. Learn balance, spending, events, then renewables.",
                      ("start_instructional",), emblem="grid")
        self._run_bay(surface, rects[1], "FREE PLAY DISPATCH", ACCENT,
                      "Choose region, date, difficulty, then keep demand and spend in line.",
                      ("goto", FREEPLAY), emblem="grid")
        self._run_bay(surface, rects[2], "BLACKOUT SCENARIOS", ACCENT_WARM,
                      "Historic stress days: storms, heat waves, fuel shortages, tight margins.",
                      ("goto", SCENARIOS), emblem="flame")
        self._toolbar(surface)

    def _draw_freeplay(self, surface):
        w, h = surface.get_size()
        self._header(surface, "FREE PLAY", "Region · Difficulty · Date")
        # region tiles grid (Standard + 7 regions), two columns each side of the
        # calendar so the layout reads like a console character-select screen
        compact = w < 1180 or h < 760
        tile_w = 238 if compact else 250
        tile_h = 76 if compact else 92
        gapy = 8 if compact else 14
        y0 = 126 if compact else 150
        col_x = [
            max(36, w // 2 - tile_w - 300),
            min(w - tile_w - 36, w // 2 + 300),
        ]
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
        self._calendar(surface, w // 2, y0 + (58 if compact else 80))
        # difficulty row below everything
        dy = y0 + 4 * (tile_h + gapy) + (20 if compact else 26)
        self._difficulty_row(surface, w // 2, dy)
        # elevated START button
        self._start_button(surface, pygame.Rect(w // 2 - 135, h - (78 if compact else 92), 270, 52 if compact else 58))
        self._toolbar(surface)

    def _draw_scenarios(self, surface):
        w, h = surface.get_size()
        self._header(surface, "SCENARIOS", "Historic grid-stress events")
        card_w = min(760, w - 120)
        x0 = w // 2 - card_w // 2
        count = max(1, len(scenarios.SCENARIOS))
        available = h - 162
        card_h = min(120, max(86, (available - (count - 1) * 8) // count))
        gap = 10 if card_h < 110 else 12
        y = 124
        for i, sc in enumerate(scenarios.SCENARIOS):
            r = pygame.Rect(x0, y, card_w, card_h)
            self._scenario_card(surface, r, sc, ("start_scenario", i))
            y += card_h + gap
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
        header = pygame.Rect(rect.left + 8, rect.top + 8, rect.width - 16, 20)
        surface.fill(_shade(accent, 0.22), header)
        pygame.draw.line(surface, accent, (header.left, header.bottom),
                         (header.right - 1, header.bottom))
        for px, py in ((rect.left + 8, rect.top + 8), (rect.right - 18, rect.top + 8),
                       (rect.left + 8, rect.bottom - 18), (rect.right - 18, rect.bottom - 18)):
            pygame.draw.line(surface, accent, (px, py), (px + 8, py))
            pygame.draw.line(surface, accent, (px, py), (px, py + 8))
        if emblem:
            emb = pa.emblem(emblem, scale=3)
            surface.blit(emb, (rect.centerx - emb.get_width() // 2, rect.top + 22))
        tw = self.font_big.size(title)[0]
        _pixel_text(surface, self.font_big, title, (rect.centerx - tw // 2, rect.top + 76), accent)
        y = rect.top + 126
        for ln in lines:
            s = self.font_small.render(ln, True, DIM)
            surface.blit(s, (rect.centerx - s.get_width() // 2, y))
            y += s.get_height() + 4
        self._targets.append((rect, action))

    def _run_bay(self, surface, rect, title, accent, blurb, action, emblem=None):
        hover = rect.collidepoint(self._mouse)
        _notched_panel(surface, rect, PANEL_HI if hover else PANEL, accent, width=3 if hover else 2)
        pygame.draw.rect(surface, _shade(accent, 0.22), (rect.left + 12, rect.top + 10, 8, rect.height - 20))
        if emblem:
            emb = pa.emblem(emblem, scale=4)
            surface.blit(emb, (rect.left + 48, rect.centery - emb.get_height() // 2))
        tx = rect.left + 128
        _pixel_text(surface, self.font_big, title, (tx, rect.top + 24), accent)
        for i, line in enumerate(_wrap(self.font_small, blurb, rect.width - 280, max_lines=2)):
            surface.blit(self.font_small.render(line, True, DIM),
                         (tx, rect.top + 66 + i * (self.font_small.get_height() + 3)))
        tag = self.font_small.render("OPEN", True, (14, 22, 16))
        button = pygame.Rect(rect.right - 106, rect.centery - 18, 74, 36)
        _pixel_panel(surface, button, accent, _shade(accent, 0.45), shadow=False)
        surface.blit(tag, (button.centerx - tag.get_width() // 2,
                           button.centery - tag.get_height() // 2))
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
            thumb_h = max(58, min(104, rect.height - 16))
            thumb_w = int(78 * thumb_h / 104)
            thumb = assets.scaled(f"scenario_cards/{card_name}_scenario_card.png",
                                  (thumb_w, thumb_h), smooth=True)
            surface.blit(thumb, (rect.left + 8, rect.centery - thumb.get_height() // 2))
            tx = rect.left + 8 + thumb.get_width() + 14
        title_y = rect.top + max(14, (rect.height - 56) // 2)
        t = _pixel_text(surface, self.font_big, sc.title, (tx, title_y), TEXT)
        s = self.font_small.render(sc.subtitle, True, accent)
        surface.blit(s, (tx, title_y + t.get_height() + 4))
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


def _notched_panel(surface, rect, fill, edge, *, width=2):
    """Chunkier beveled console face with clipped pixel corners."""
    _shadow(surface, rect.move(5, 5))
    pts = [
        (rect.left + 10, rect.top), (rect.right - 1, rect.top),
        (rect.right - 1, rect.bottom - 11), (rect.right - 11, rect.bottom - 1),
        (rect.left, rect.bottom - 1), (rect.left, rect.top + 10),
    ]
    pygame.draw.polygon(surface, fill, pts)
    pygame.draw.lines(surface, edge, True, pts, width)
    pygame.draw.line(surface, _shade(fill, 1.35), pts[0], pts[1])
    pygame.draw.line(surface, _shade(fill, 0.48), pts[3], pts[4])
    pygame.draw.line(surface, GOOD, (rect.left + 12, rect.top + 12),
                     (rect.left + 36, rect.top + 12), 1)


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
