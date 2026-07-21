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

PANEL_BG = (22, 28, 44)
PANEL_EDGE = (120, 132, 160)
TITLE = (235, 240, 250)
DIM = (150, 158, 176)
ACCENT = (255, 215, 90)
BTN_BG = (38, 62, 48)
BTN_EDGE = (110, 220, 160)
BTN_TEXT = (215, 245, 228)

# supply-band palette for the time-balance bar and points rows
COL_UNDER = (230, 80, 80)
COL_IDEAL = (100, 220, 140)
COL_OVER = (240, 200, 70)
CARD_BG = (18, 23, 37)
CARD_EDGE = (52, 62, 88)
POS = (120, 220, 150)
NEG = (232, 96, 96)


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
        self._day_label = ""
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
        self.phase = DayPhase.ADVANCING_DAY

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

    def draw(self, surface):
        if not self.open or self._state is None:
            return
        state = self._state
        w, h = surface.get_size()

        # full-frame dim, then a centered performance card
        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((8, 9, 14, 215))
        surface.blit(dim, (0, 0))

        cw, ch = min(w - 120, 1060), min(h - 100, 640)
        self.rect = pygame.Rect(0, 0, cw, ch)
        self.rect.center = (w // 2, h // 2)
        card = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        pygame.draw.rect(card, (*PANEL_BG, 250), card.get_rect(), border_radius=10)
        pygame.draw.rect(card, PANEL_EDGE, card.get_rect(), width=2, border_radius=10)
        surface.blit(card, self.rect.topleft)

        pad = 26
        inner_l = self.rect.left + pad
        inner_r = self.rect.right - pad

        # --- header -------------------------------------------------------
        title = self.font_big.render(self._day_label, True, ACCENT)
        surface.blit(title, (inner_l, self.rect.top + 20))
        summary = self.font_small.render(
            f"Score {int(state.score):,}   ·   Spent {_money(state.total_cost)}", True, DIM)
        surface.blit(summary, (inner_r - summary.get_width(), self.rect.top + 28))

        # star rating from the fraction of run time spent inside the ideal band
        total_time = state.time_under + state.time_ideal + state.time_over
        frac = state.time_ideal / total_time if total_time > 1e-6 else 0.0
        n_stars = next(n for n, thr in ((5, 0.90), (4, 0.75), (3, 0.55),
                                        (2, 0.35), (1, 0.15), (0, -1.0)) if frac >= thr)
        star_full = assets.scaled_to_height("ratings/star_full.png", 24)
        star_empty = assets.scaled_to_height("ratings/star_empty.png", 24)
        sx = inner_l + title.get_width() + 24
        for i in range(5):
            surface.blit(star_full if i < n_stars else star_empty,
                         (sx + i * 28, self.rect.top + 18))

        body_top = self.rect.top + 64
        body_bottom = self.rect.bottom - 76
        # --- left: demand / generation-mix chart --------------------------
        chart_w = int((inner_r - inner_l) * 0.55)
        chart_rect = pygame.Rect(inner_l, body_top, chart_w, body_bottom - body_top)
        self._chart.rect = chart_rect
        self._chart.draw(surface, state.sim_hour, state.sources, state.history,
                         state.demand_mw, state.demand_min_mw, state.demand_peak_mw)

        # --- right: three stat blocks -------------------------------------
        col_l = chart_rect.right + 28
        col_r = inner_r
        colors = {s.key: s.color for s in state.sources}
        names = {s.key: s.name for s in state.sources}
        y = body_top
        y = self._cost_block(surface, col_l, col_r, y, state, colors, names)
        y = self._time_block(surface, col_l, col_r, y + 18, state)
        self._points_block(surface, col_l, col_r, y + 18, state)

        # --- footer: "Continue to Next Day" label + confirm button --------
        label = self.font.render("Continue to Next Day", True, BTN_TEXT)
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
        h = self.font_small.render(text, True, ACCENT)
        surface.blit(h, (x, y))
        return y + h.get_height() + 8

    def _cost_block(self, surface, x0, x1, y, state, colors, names):
        y = self._heading(surface, x0, y, "SPENT BY SOURCE")
        costs = state.cost_by_source
        peak = max(costs.values()) if costs else 0.0
        bar_x = x0 + 96
        bar_w_max = x1 - bar_x - 78
        for key in STACK_ORDER:
            amount = costs.get(key, 0.0)
            if amount < 1.0:
                continue
            name = self.font_small.render(names.get(key, key), True, DIM)
            surface.blit(name, (x0, y))
            frac = amount / peak if peak > 0 else 0.0
            bar = pygame.Rect(bar_x, y + 1, max(2, int(bar_w_max * frac)), 12)
            pygame.draw.rect(surface, colors.get(key, (120, 120, 120)), bar, border_radius=2)
            val = self.font_small.render(_money(amount), True, TITLE)
            surface.blit(val, (x1 - val.get_width(), y))
            y += 20
        return y

    def _time_block(self, surface, x0, x1, y, state):
        y = self._heading(surface, x0, y, "TIME BY SUPPLY BAND")
        segs = [("under", state.time_under, COL_UNDER),
                ("ideal", state.time_ideal, COL_IDEAL),
                ("over", state.time_over, COL_OVER)]
        total = sum(v for _, v, _ in segs) or 1.0
        bar = pygame.Rect(x0, y, x1 - x0, 20)
        bx = bar.left
        for _key, hours, col in segs:
            seg_w = int(bar.width * hours / total)
            pygame.draw.rect(surface, col, (bx, bar.top, seg_w, bar.height))
            bx += seg_w
        pygame.draw.rect(surface, CARD_EDGE, bar, width=1)
        y = bar.bottom + 8
        for label, hours, col in [("Under-supplied", state.time_under, COL_UNDER),
                                  ("In band", state.time_ideal, COL_IDEAL),
                                  ("Over-supplied", state.time_over, COL_OVER)]:
            pygame.draw.rect(surface, col, (x0, y + 2, 10, 10))
            lab = self.font_small.render(label, True, DIM)
            surface.blit(lab, (x0 + 16, y))
            val = self.font_small.render(f"{hours:.1f} h", True, TITLE)
            surface.blit(val, (x1 - val.get_width(), y))
            y += 18
        return y

    def _points_block(self, surface, x0, x1, y, state):
        y = self._heading(surface, x0, y, "POINTS BREAKDOWN")
        p = state.points
        rows = [("In band", p["ideal"]), ("Under-supply", p["under"]),
                ("Over-supply", p["over"]), ("Source penalties", p["source"])]
        for label, val in rows:
            lab = self.font_small.render(label, True, DIM)
            surface.blit(lab, (x0, y))
            col = POS if val >= 0 else NEG
            num = self.font_small.render(f"{int(val):+,}", True, col)
            surface.blit(num, (x1 - num.get_width(), y))
            y += 18
        pygame.draw.line(surface, CARD_EDGE, (x0, y + 2), (x1, y + 2), 1)
        y += 8
        total = sum(p.values())
        lab = self.font.render("Total", True, TITLE)
        surface.blit(lab, (x0, y))
        num = self.font.render(f"{int(total):+,}", True, POS if total >= 0 else NEG)
        surface.blit(num, (x1 - num.get_width(), y))
        return y


def _money(dollars: float) -> str:
    if dollars >= 1_000_000:
        return f"${dollars / 1_000_000:,.2f}M"
    if dollars >= 1_000:
        return f"${dollars / 1_000:,.1f}K"
    return f"${dollars:,.0f}"
