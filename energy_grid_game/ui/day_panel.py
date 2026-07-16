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

from ui.dialogue import get_dialogue_rect

PANEL_BG = (22, 28, 44)
PANEL_EDGE = (120, 132, 160)
TITLE = (235, 240, 250)
DIM = (150, 158, 176)
ACCENT = (255, 215, 90)
BTN_BG = (38, 62, 48)
BTN_EDGE = (110, 220, 160)
BTN_TEXT = (215, 245, 228)


class DayPhase(Enum):
    DAY_ACTIVE = "DAY_ACTIVE"
    DAY_COMPLETE_PAUSED = "DAY_COMPLETE_PAUSED"
    ADVANCING_DAY = "ADVANCING_DAY"
    NEXT_DAY_START = "NEXT_DAY_START"


class DayCompletePanel:
    WIDTH = 340
    HEIGHT = 132

    def __init__(self, font, font_small, font_big):
        self.font = font
        self.font_small = font_small
        self.font_big = font_big
        self.phase = DayPhase.DAY_ACTIVE
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.button_rect = pygame.Rect(0, 0, 0, 0)
        self._summary = ""
        self._day_label = ""
        self._regions = {}

    def blocks_gameplay(self) -> bool:
        """Pauses the sim: no clock, no consumption, no events, no input through."""
        return self.phase in (DayPhase.DAY_COMPLETE_PAUSED, DayPhase.ADVANCING_DAY)

    @property
    def open(self) -> bool:
        return self.phase == DayPhase.DAY_COMPLETE_PAUSED

    def update(self, dt, state, regions, audio=None):
        self._regions = regions or {}

        if self.phase == DayPhase.DAY_ACTIVE:
            # a failed run is not a completed day; the failure screen owns that
            if state.day_complete and not state.game_over:
                self.phase = DayPhase.DAY_COMPLETE_PAUSED
                self._day_label = f"DAY {state.day} COMPLETE"
                self._summary = f"Score {int(state.score):,}   ·   Spent {_money(state.total_cost)}"
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

    def draw(self, surface):
        if not self.open:
            return
        screen_rect = surface.get_rect()
        blocked = [self._regions.get(k) for k in ("tank", "city", "spigot_panel",
                                                  "speed_control")]
        cluster = get_dialogue_rect(screen_rect, (0, 0), blocked,
                                    (self.WIDTH, self.HEIGHT))
        self.rect = pygame.Rect(cluster.left, cluster.top, self.WIDTH, self.HEIGHT)

        panel = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        pygame.draw.rect(panel, (*PANEL_BG, 245), panel.get_rect(), border_radius=8)
        pygame.draw.rect(panel, PANEL_EDGE, panel.get_rect(), width=2, border_radius=8)
        surface.blit(panel, self.rect.topleft)

        y = self.rect.top + 12
        title = self.font_big.render(self._day_label, True, ACCENT)
        surface.blit(title, (self.rect.centerx - title.get_width() // 2, y))
        y += title.get_height() + 4

        summary = self.font_small.render(self._summary, True, DIM)
        surface.blit(summary, (self.rect.centerx - summary.get_width() // 2, y))
        y += summary.get_height() + 4

        note = self.font_small.render("The grid held. Demand resets at 04:00.", True, DIM)
        surface.blit(note, (self.rect.centerx - note.get_width() // 2, y))
        y += note.get_height() + 8

        self.button_rect = pygame.Rect(0, 0, self.rect.width - 40, 28)
        self.button_rect.midtop = (self.rect.centerx, y)
        pygame.draw.rect(surface, BTN_BG, self.button_rect, border_radius=5)
        pygame.draw.rect(surface, BTN_EDGE, self.button_rect, width=1, border_radius=5)
        label = self.font.render("Continue to Next Day", True, BTN_TEXT)
        surface.blit(label, (self.button_rect.centerx - label.get_width() // 2,
                             self.button_rect.centery - label.get_height() // 2))

        hint = self.font_small.render("ENTER / SPACE / click", True, DIM)
        surface.blit(hint, (self.rect.centerx - hint.get_width() // 2,
                            self.button_rect.bottom + 2))


def _money(dollars: float) -> str:
    if dollars >= 1_000_000:
        return f"${dollars / 1_000_000:,.2f}M"
    if dollars >= 1_000:
        return f"${dollars / 1_000:,.1f}K"
    return f"${dollars:,.0f}"
