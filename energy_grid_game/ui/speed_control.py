"""Visible game-speed ticker: click - / + (or press the existing -/= keys) to
step through SPEED_STEPS, click the speed readout itself to pause/resume.
"""
import pygame

BG = (24, 30, 46)
BORDER = (60, 68, 88)
TEXT = (225, 230, 240)
DIM = (140, 148, 168)
ACCENT = (110, 220, 160)

BTN_W, BTN_H = 22, 22
GAP = 6


class SpeedControl:
    def __init__(self, pos, font_small, font):
        self.pos = pos  # top-left
        self.font_small = font_small
        self.font = font
        self._minus_rect = pygame.Rect(0, 0, BTN_W, BTN_H)
        self._plus_rect = pygame.Rect(0, 0, BTN_W, BTN_H)
        self._label_rect = pygame.Rect(0, 0, 0, 0)

    def _layout(self):
        x, y = self.pos
        label_w = 64
        self._minus_rect.topleft = (x, y)
        self._label_rect = pygame.Rect(x + BTN_W + GAP, y, label_w, BTN_H)
        self._plus_rect.topleft = (x + BTN_W + GAP + label_w + GAP, y)

    def bounds(self) -> pygame.Rect:
        """Bounding rect of the whole widget, including the SPEED caption."""
        self._layout()
        rect = self._minus_rect.union(self._label_rect).union(self._plus_rect)
        return rect.inflate(0, 22).move(0, 11)  # room for the caption underneath

    def handle_mouse_down(self, pos, state):
        self._layout()
        if self._minus_rect.collidepoint(pos):
            state.speed_down()
            return True
        if self._plus_rect.collidepoint(pos):
            state.speed_up()
            return True
        if self._label_rect.collidepoint(pos):
            state.paused = not state.paused
            return True
        return False

    def draw(self, surface, state):
        self._layout()

        for rect, label in ((self._minus_rect, "-"), (self._plus_rect, "+")):
            pygame.draw.rect(surface, BG, rect, border_radius=4)
            pygame.draw.rect(surface, BORDER, rect, width=1, border_radius=4)
            txt = self.font.render(label, True, TEXT)
            surface.blit(txt, (rect.centerx - txt.get_width() // 2, rect.centery - txt.get_height() // 2))

        pygame.draw.rect(surface, BG, self._label_rect, border_radius=4)
        pygame.draw.rect(surface, BORDER, self._label_rect, width=1, border_radius=4)
        speed_color = (240, 200, 90) if state.paused else ACCENT
        label = "PAUSED" if state.paused else f"{state.game_speed:g}x"
        txt = self.font_small.render(label, True, speed_color)
        surface.blit(txt, (self._label_rect.centerx - txt.get_width() // 2,
                            self._label_rect.centery - txt.get_height() // 2))

        hint = self.font_small.render("SPEED", True, DIM)
        surface.blit(hint, (self._minus_rect.left, self._minus_rect.bottom + 3))
