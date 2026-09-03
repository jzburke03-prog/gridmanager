"""End-of-day confirmation: a small paused panel between one sim day and the next.

Kept deliberately separate from the tutorial. Its own state, its own text, its own
input handling -- a day rolling over must never reach into tutorial state or
re-open tutorial dialogue.

    DAY_ACTIVE -> (day completion condition) -> DAY_COMPLETE_PAUSED
               -> (player confirms)          -> ADVANCING_DAY
               -> (day initialised exactly once) -> NEXT_DAY_START -> DAY_ACTIVE

The one-way walk through ADVANCING_DAY is what makes double-advance impossible:
confirm() only fires from DAY_COMPLETE_PAUSED, and the very act of confirming
leaves that state, so a second Enter or click lands on a phase that ignores input.
"""
from enum import Enum

import pygame

from ui import assets
from ui.demand_chart import DemandChart, STACK_ORDER
from ui.dialogue import wrap_text
from ui.instructional_data import DAY_NOTES

PANEL_BG = (30, 42, 36)
PANEL_EDGE = (90, 122, 100)
TITLE = (235, 240, 250)
DIM = (170, 166, 138)
ACCENT = (236, 214, 132)
BTN_BG = (44, 66, 44)
BTN_EDGE = (110, 220, 160)
BTN_TEXT = (215, 245, 228)

# supply-band palette for the time-balance bar and points rows
COL_UNDER = (230, 80, 80)
COL_IDEAL = (100, 220, 140)
COL_OVER = (240, 200, 70)
CARD_BG = (30, 42, 36)
CARD_EDGE = (82, 112, 92)
POS = (120, 220, 150)
NEG = (232, 96, 96)


def _notched_panel(surface, rect, fill, edge, accent=None, alpha=238):
    pts = [
        (rect.left + 10, rect.top), (rect.right - 1, rect.top),
        (rect.right - 1, rect.bottom - 11), (rect.right - 11, rect.bottom - 1),
        (rect.left, rect.bottom - 1), (rect.left, rect.top + 10),
    ]
    local = [(x - rect.left, y - rect.top) for x, y in pts]
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.polygon(panel, (*fill, alpha), local)
    pygame.draw.lines(panel, (*edge, 245), True, local, 2)
    pygame.draw.line(panel, (144, 154, 118, 110), local[0], local[1])
    pygame.draw.line(panel, (6, 14, 18, 175), local[3], local[4])
    if accent is not None:
        pygame.draw.line(panel, (*accent, 150), (14, 10), (42, 10), 1)
    surface.blit(panel, rect.topleft)


def _big_pixel(surface, font, text, pos, color, scale=2):
    raw = font.render(text, True, color)
    shadow = font.render(text, True, (6, 10, 14))
    size = (raw.get_width() * scale, raw.get_height() * scale)
    surface.blit(pygame.transform.scale(shadow, size), (pos[0] + scale * 2, pos[1] + scale * 2))
    surface.blit(pygame.transform.scale(raw, size), pos)
    return pygame.Rect(pos, size)


class DayPhase(Enum):
    DAY_ACTIVE = "DAY_ACTIVE"
    DAY_COMPLETE_PAUSED = "DAY_COMPLETE_PAUSED"
    ADVANCING_DAY = "ADVANCING_DAY"
    NEXT_DAY_START = "NEXT_DAY_START"


class DayCompletePanel:
    def __init__(self, font, font_small, font_big):
        self.font = font
        self.font_small = font_small
        self.font_big = font_big
        self.phase = DayPhase.DAY_ACTIVE
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.button_rect = pygame.Rect(0, 0, 0, 0)
        self.return_to_menu = False   # set on confirming the final day
        self._day_label = ""
        self._day_note = None    # instructional-only closing line
        self._compact_stats = False
        # frozen reference to the completed day's GameState, captured on the
        # DAY_ACTIVE -> DAY_COMPLETE_PAUSED transition (the sim is frozen from
        # that point until the player confirms), plus a reusable large chart.
        self._state = None
        self._chart = DemandChart(pygame.Rect(0, 0, 0, 0), font_small)

    def blocks_gameplay(self) -> bool:
        """Pauses the sim: no clock, no consumption, no events, no input through."""
        return self.phase in (DayPhase.DAY_COMPLETE_PAUSED, DayPhase.ADVANCING_DAY)

    @property
    def open(self) -> bool:
        return self.phase == DayPhase.DAY_COMPLETE_PAUSED

    def update(self, dt, state, regions, audio=None):
        if self.phase == DayPhase.DAY_ACTIVE:
            # a failed run is not a completed day; the failure screen owns that
            if state.day_complete and not state.game_over:
                self.phase = DayPhase.DAY_COMPLETE_PAUSED
                self._day_label = f"DAY {state.day} COMPLETE"
                self._day_note = (DAY_NOTES.get(state.day)
                                  if state.config.is_instructional else None)
                # freeze a reference to this day's state for the summary; the
                # completed day's demand shape seeds the chart's future preview
                self._state = state
                self._chart.demand_hours, self._chart.demand_levels = \
                    state.demand_profile.samples(288)
                if audio:
                    audio.play("day_complete")

        elif self.phase == DayPhase.ADVANCING_DAY:
            state.start_next_day()   # exactly once: this phase lasts one frame
            if audio:
                audio.play("next_day")
            self.phase = DayPhase.NEXT_DAY_START

        elif self.phase == DayPhase.NEXT_DAY_START:
            self.phase = DayPhase.DAY_ACTIVE

    def confirm(self, audio=None):
        if self.phase != DayPhase.DAY_COMPLETE_PAUSED:
            return  # already confirmed; ignore repeats
        if audio:
            audio.play("ui_click")
        # Instructional Mode's last day is terminal: confirming returns to the
        # menu instead of rolling into a day the script has nothing to say about.
        if self._state is not None and self._state.is_final_day:
            self.return_to_menu = True
            self.phase = DayPhase.DAY_ACTIVE
            return
        self.phase = DayPhase.ADVANCING_DAY

    def take_return_to_menu(self) -> bool:
        """One-shot: True once after the final day is confirmed."""
        if not self.return_to_menu:
            return False
        self.return_to_menu = False
        return True

    def handle_event(self, event, audio=None) -> bool:
        if not self.blocks_gameplay():
            return False
        if self.phase == DayPhase.ADVANCING_DAY:
            return True  # swallow anything arriving mid-transition

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.confirm(audio)
                return True
            return False  # ESC / R stay live
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.button_rect.collidepoint(event.pos):
                self.confirm(audio)
            return True   # never let a click through to the grid underneath
        if event.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            return True
        return False

    def reset(self):
        self.phase = DayPhase.DAY_ACTIVE
        self._state = None
        self.return_to_menu = False

    def _summary_tile(self, surface, rect, label, value, color, icon=None, sub=None):
        _notched_panel(surface, rect, (34, 48, 40), (80, 112, 92), color, alpha=224)
        x = rect.left + 14
        if icon is not None:
            surface.blit(icon, (x, rect.top + 16))
            x += icon.get_width() + 8
        lab = self.font_small.render(label, True, (214, 204, 152))
        surface.blit(lab, (x, rect.top + 10))
        max_w = rect.right - x - 12
        if self.font.size(value)[0] * 2 <= max_w:
            _big_pixel(surface, self.font, value, (x, rect.top + 28), color, scale=2)
        else:
            val_font = self.font_big if self.font_big.size(value)[0] <= max_w else self.font
            val = val_font.render(value, True, color)
            surface.blit(val, (x, rect.top + 10 + lab.get_height() + 3))
        if sub:
            s = self.font_small.render(sub, True, DIM)
            surface.blit(s, (x, rect.bottom - s.get_height() - 7))

    def draw(self, surface):
        if not self.open or self._state is None:
            return
        state = self._state
        w, h = surface.get_size()
        total_time = state.time_under + state.time_ideal + state.time_over
        frac = state.time_ideal / total_time if total_time > 1e-6 else 0.0
        n_stars = next(n for n, thr in ((5, 0.90), (4, 0.75), (3, 0.55),
                                        (2, 0.35), (1, 0.15), (0, -1.0)) if frac >= thr)

        # full-frame dim, then a centered operations debrief
        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((10, 12, 8, 192))
        surface.blit(dim, (0, 0))

        cw, ch = min(w - 80, 1160), min(h - 40, 800)
        self.rect = pygame.Rect(0, 0, cw, ch)
        self.rect.center = (w // 2, h // 2)
        shadow = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 135))
        surface.blit(shadow, self.rect.move(10, 10).topleft)
        _notched_panel(surface, self.rect, PANEL_BG, PANEL_EDGE, ACCENT, alpha=250)
        header = pygame.Rect(self.rect.left + 12, self.rect.top + 12,
                             self.rect.width - 24, 78)
        _notched_panel(surface, header, (36, 50, 42), (94, 126, 102), ACCENT, alpha=232)

        pad = 30
        inner_l = self.rect.left + pad
        inner_r = self.rect.right - pad

        # --- header -------------------------------------------------------
        title_rect = _big_pixel(surface, self.font_big, self._day_label,
                                (inner_l, header.top + 16), ACCENT, scale=2)
        star_full = assets.scaled_to_height("ratings/star_full.png", 36)
        star_empty = assets.scaled_to_height("ratings/star_empty.png", 36)
        sx = title_rect.right + 28
        for i in range(5):
            surface.blit(star_full if i < n_stars else star_empty,
                         (sx + i * 40, header.top + 22))

        tile_top = header.bottom + 14
        tile_gap = 12
        tile_w = (inner_r - inner_l - tile_gap * 3) // 4
        balance_pct = int(frac * 100)
        self._summary_tile(surface, pygame.Rect(inner_l, tile_top, tile_w, 76),
                           "FINAL SCORE", f"{int(state.score):,}", POS)
        self._summary_tile(surface, pygame.Rect(inner_l + (tile_w + tile_gap), tile_top, tile_w, 76),
                           "BALANCED TIME", f"{balance_pct}%", COL_IDEAL)
        spent_label = _money(state.total_cost) if state.show_economics else "--"
        self._summary_tile(surface, pygame.Rect(inner_l + 2 * (tile_w + tile_gap), tile_top, tile_w, 76),
                           "TOTAL SPENT", spent_label, ACCENT,
                           assets.resource_icon("money", 18) if state.show_economics else None)
        self._summary_tile(surface, pygame.Rect(inner_l + 3 * (tile_w + tile_gap), tile_top, tile_w, 76),
                           "RATING", f"{n_stars}/5", ACCENT)

        body_top = tile_top + 98
        body_bottom = self.rect.bottom - 112
        # --- left: demand / generation-mix chart --------------------------
        chart_w = int((inner_r - inner_l) * 0.55)
        chart_rect = pygame.Rect(inner_l, body_top, chart_w, body_bottom - body_top)
        self._chart.rect = chart_rect
        self._chart.draw(surface, state.sim_hour, state.sources, state.history,
                         state.demand_mw, state.demand_min_mw, state.demand_peak_mw)

        # --- right: three stat blocks -------------------------------------
        col_l = chart_rect.right + 28
        col_r = inner_r
        self._compact_stats = (body_bottom - body_top) < 450
        colors = {s.key: s.color for s in state.sources}
        names = {s.key: s.name for s in state.sources}
        # Blocks flow strictly top-down and the note follows them, so nothing can
        # collide by construction. The note used to be anchored to the column's
        # bottom, which worked only while the blocks above happened to be short
        # enough — adding a row per source ran them straight through it.
        # Day 1 of Instructional Mode has no economics to report on yet.
        y = self._source_block(surface, col_l, col_r, body_top, state, colors, names,
                               show_cost=state.show_economics)
        y = self._time_block(surface, col_l, col_r, y + (10 if self._compact_stats else 16), state)
        y = self._points_block(surface, col_l, col_r, y + (10 if self._compact_stats else 16), state)

        if self._day_note:
            lines = wrap_text(self._day_note, self.font_small, col_r - col_l)
            line_h = self.font_small.get_height() + 2
            note_y = min(y + 16, body_bottom - len(lines) * line_h)
            for line in lines:
                surface.blit(self.font_small.render(line, True, DIM), (col_l, note_y))
                note_y += line_h

        # --- footer: confirm label + button -------------------------------
        label = self.font.render(
            "Finish" if state.is_final_day else "Continue to Next Day", True, BTN_TEXT)
        btn_state = "hover" if self.button_rect.collidepoint(pygame.mouse.get_pos()) else "idle"
        btn = assets.scaled_to_height(f"buttons/confirm_button_{btn_state}.png", 48)
        gap = 14
        group_w = label.get_width() + gap + btn.get_width()
        gx = self.rect.centerx - group_w // 2
        by = self.rect.bottom - 22 - btn.get_height()
        surface.blit(label, (gx, by + (btn.get_height() - label.get_height()) // 2))
        btn_pos = (gx + label.get_width() + gap, by)
        surface.blit(btn, btn_pos)
        # generous click target around the button art
        self.button_rect = pygame.Rect(btn_pos, btn.get_size()).inflate(24, 8)
        hint = self.font_small.render("ENTER / SPACE / click", True, DIM)
        surface.blit(hint, (self.rect.centerx - hint.get_width() // 2,
                            self.rect.bottom - 18))

    # -- stat blocks -------------------------------------------------------
    def _heading(self, surface, x, y, text):
        h = self.font.render(text, True, ACCENT)
        strip = pygame.Rect(x, y - 3, h.get_width() + 18, h.get_height() + 8)
        _notched_panel(surface, strip, (38, 50, 42), (86, 120, 96), ACCENT, alpha=210)
        surface.blit(h, (x + 10, y))
        return y + h.get_height() + (7 if self._compact_stats else 12)

    def _source_block(self, surface, x0, x1, y, state, colors, names, show_cost):
        """One row per source: capacity factor as a bar, then CF% and spend.

        Deliberately a single table. Two stacked per-source tables meant sixteen
        rows in a column with space for about ten, and the overflow ran straight
        through the points breakdown and out of the card.

        Capacity factor is measured against nameplate, not against what the
        weather allowed — a becalmed wind farm SHOULD read low, and that is the
        lesson. Sources with no capacity today are omitted entirely; one left
        idle still shows, because 0% is information too.
        """
        heading = "BY SOURCE — CAPACITY FACTOR" + ("  ·  SPENT" if show_cost else "")
        y = self._heading(surface, x0, y, heading)
        costs = state.cost_by_source
        cost_w = 62 if show_cost else 0
        row_h = 19 if self._compact_stats else 24
        bar_h = 12 if self._compact_stats else 16
        bar_x = x0 + 104
        bar_w_max = max(24, x1 - bar_x - 48 - cost_w)
        for key in STACK_ORDER:
            cf = state.capacity_factor(key)
            if cf is None:
                continue
            pygame.draw.rect(surface, colors.get(key, (120, 120, 120)), (x0, y + 4, 8, 8))
            surface.blit(self.font_small.render(names.get(key, key), True, DIM), (x0 + 14, y))
            track = pygame.Rect(bar_x, y + 2, bar_w_max, bar_h)
            pygame.draw.rect(surface, (44, 50, 36), track)
            fill = pygame.Rect(bar_x, y + 2, max(2, int(bar_w_max * min(1.0, cf))), bar_h)
            pygame.draw.rect(surface, colors.get(key, (120, 120, 120)), fill)
            pygame.draw.rect(surface, (88, 118, 96), track, width=1)
            pct = self.font_small.render(f"{cf * 100:0.0f}%", True, TITLE)
            surface.blit(pct, (bar_x + bar_w_max + 40 - pct.get_width(), y))
            if show_cost:
                val = self.font_small.render(_money(costs.get(key, 0.0)), True, TITLE)
                surface.blit(val, (x1 - val.get_width(), y))
            y += row_h
        return y

    def _time_block(self, surface, x0, x1, y, state):
        y = self._heading(surface, x0, y, "TIME BY SUPPLY BAND")
        segs = [("under", state.time_under, COL_UNDER),
                ("ideal", state.time_ideal, COL_IDEAL),
                ("over", state.time_over, COL_OVER)]
        total = sum(v for _, v, _ in segs) or 1.0
        bar = pygame.Rect(x0, y, x1 - x0, 22 if self._compact_stats else 28)
        bx = bar.left
        for _key, hours, col in segs:
            seg_w = int(bar.width * hours / total)
            pygame.draw.rect(surface, col, (bx, bar.top, seg_w, bar.height))
            bx += seg_w
        pygame.draw.rect(surface, (98, 126, 102), bar, width=2)
        y = bar.bottom + (7 if self._compact_stats else 10)
        for label, hours, col in [("Under-supplied", state.time_under, COL_UNDER),
                                  ("In band", state.time_ideal, COL_IDEAL),
                                  ("Over-supplied", state.time_over, COL_OVER)]:
            pygame.draw.rect(surface, col, (x0, y + 2, 10, 10))
            lab = self.font_small.render(label, True, DIM)
            surface.blit(lab, (x0 + 16, y))
            val = self.font_small.render(f"{hours:.1f} h", True, TITLE)
            surface.blit(val, (x1 - val.get_width(), y))
            y += 15 if self._compact_stats else 18
        return y

    def _points_block(self, surface, x0, x1, y, state):
        y = self._heading(surface, x0, y, "POINTS BREAKDOWN")
        p = state.points
        if self._compact_stats:
            total = sum(p.values())
            lab = self.font.render("Total", True, TITLE)
            surface.blit(lab, (x0, y))
            num = self.font.render(f"{int(total):+,}", True, POS if total >= 0 else NEG)
            surface.blit(num, (x1 - num.get_width(), y))
            return y + lab.get_height()

        rows = [("In band", p["ideal"]), ("Under-supply", p["under"]),
                ("Over-supply", p["over"]), ("Source penalties", p["source"])]
        for label, val in rows:
            lab = self.font_small.render(label, True, DIM)
            surface.blit(lab, (x0, y))
            col = POS if val >= 0 else NEG
            num = self.font_small.render(f"{int(val):+,}", True, col)
            surface.blit(num, (x1 - num.get_width(), y))
            y += 15 if self._compact_stats else 18
        pygame.draw.line(surface, CARD_EDGE, (x0, y + 2), (x1, y + 2), 1)
        y += 8
        total = sum(p.values())
        lab = self.font.render("Total", True, TITLE)
        surface.blit(lab, (x0, y))
        num = self.font.render(f"{int(total):+,}", True, POS if total >= 0 else NEG)
        surface.blit(num, (x1 - num.get_width(), y))
        return y + lab.get_height()


def _money(dollars: float) -> str:
    if dollars >= 1_000_000:
        return f"${dollars / 1_000_000:,.2f}M"
    if dollars >= 1_000:
        return f"${dollars / 1_000:,.1f}K"
    return f"${dollars:,.0f}"
