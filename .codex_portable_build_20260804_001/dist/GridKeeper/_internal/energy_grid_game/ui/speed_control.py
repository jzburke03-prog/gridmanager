"""Visible game-speed ticker: a pause/resume button, left/right arrows to step
through SPEED_STEPS (or the existing -/= keys), and the speed readout (which also
toggles pause when clicked).
"""
import pygame

from ui import assets

BG = (24, 30, 46)
BORDER = (60, 68, 88)
TEXT = (225, 230, 240)
DIM = (140, 148, 168)
ACCENT = (110, 220, 160)

PAUSE_W, BTN, LABEL_W, ROW_H = 48, 24, 56, 24
GAP = 6


class SpeedControl:
    def __init__(self, pos, font_small, font):
        self.pos = pos  # top-left
        self.font_small = font_small
        self.font = font
        self._pause_rect = pygame.Rect(0, 0, PAUSE_W, ROW_H)
        self._minus_rect = pygame.Rect(0, 0, BTN, ROW_H)
        self._plus_rect = pygame.Rect(0, 0, BTN, ROW_H)
        self._label_rect = pygame.Rect(0, 0, LABEL_W, ROW_H)

    def _layout(self):
        x, y = self.pos
        self._pause_rect.topleft = (x, y)
        self._minus_rect.topleft = (self._pause_rect.right + GAP, y)
        self._label_rect.topleft = (self._minus_rect.right + GAP, y)
        self._plus_rect.topleft = (self._label_rect.right + GAP, y)

    def bounds(self) -> pygame.Rect:
        """Bounding rect of the whole widget, including the SPEED caption."""
        self._layout()
        rect = self._pause_rect.union(self._label_rect).union(self._plus_rect)
        return rect.inflate(0, 22).move(0, 11)  # room for the caption underneath

    def handle_mouse_down(self, pos, state):
        self._layout()
        if self._pause_rect.collidepoint(pos) or self._label_rect.collidepoint(pos):
            state.paused = not state.paused
            return True
        if self._minus_rect.collidepoint(pos):
            state.speed_down()
            return True
        if self._plus_rect.collidepoint(pos):
            state.speed_up()
            return True
        return False

    def draw(self, surface, state):
        self._layout()
        mouse = pygame.mouse.get_pos()

        # pause/resume button (shows resume art while paused), hover-lit
        name = "resume" if state.paused else "pause"
        btn_state = "hover" if self._pause_rect.collidepoint(mouse) else "idle"
        surface.blit(assets.scaled(f"buttons/{name}_button_{btn_state}.png",
                                   self._pause_rect.size), self._pause_rect.topleft)

        # speed -/+ arrows
        for rect, arrow in ((self._minus_rect, "arrow_left"), (self._plus_rect, "arrow_right")):
            surface.blit(assets.scaled(f"navigation/{arrow}.png", rect.size), rect.topleft)

        # speed readout (procedural: the pack has no numeric-label asset)
        pygame.draw.rect(surface, BG, self._label_rect, border_radius=4)
        pygame.draw.rect(surface, BORDER, self._label_rect, width=1, border_radius=4)
        speed_color = (240, 200, 90) if state.paused else ACCENT
        label = "PAUSED" if state.paused else f"{state.game_speed:g}x"
        txt = self.font_small.render(label, True, speed_color)
        surface.blit(txt, (self._label_rect.centerx - txt.get_width() // 2,
                            self._label_rect.centery - txt.get_height() // 2))

        hint = self.font_small.render("SPEED", True, DIM)
        surface.blit(hint, (self._pause_rect.left, self._pause_rect.bottom + 3))
