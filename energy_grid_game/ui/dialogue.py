"""Shared dialogue plumbing: placement, the compact box renderer, and the
typewriter state machine every dialogue-ish overlay is built on.

The state machine exists because of a real bug. The first version derived *which*
string was on screen from whichever timer happened to be non-zero
(`if success_timer > 0: return success_text`). update() zeroed that timer with
max(0.0, t - dt) and then read "is the text fully revealed?" in the same frame --
at which point the getter had already switched identity back to the previous
line. The comparison was made against the wrong string, the step never advanced,
the typewriter re-revealed the old line, the completion condition was still true,
and the step re-fired forever.

So: the text being revealed is stored, once, on entry, and the state is explicit.
Nothing infers what is showing from a timer.
"""
from enum import Enum

import pygame

from ui import portraits


class DialogueState(Enum):
    CLOSED = "CLOSED"
    OPENING = "OPENING"
    REVEALING_TEXT = "REVEALING_TEXT"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    WAITING_FOR_GAME_ACTION = "WAITING_FOR_GAME_ACTION"
    CLOSING = "CLOSING"
    COMPLETE = "COMPLETE"


CHARS_PER_SEC = 55.0

INK = (58, 46, 32)          # dialogue text on the cream chatbox
INK_DIM = (120, 104, 84)
PLATE_BG = (28, 44, 82)     # matches the chatbox's dark blue frame
PLATE_GOLD = (198, 158, 74)
PLATE_TEXT = (238, 226, 196)

PAD = 12                    # inner padding between the frame and the text
FRAME_CORNER_MIN, FRAME_CORNER_MAX = 10, 18


def get_dialogue_rect(screen_rect, portrait_size, blocked_rects, box_size, margin=16):
    """Pick a bottom corner for a (portrait + box) cluster that avoids the tank
    and any other critical rect.

    Tries lower-left, then lower-right, then the upper corners, and returns the
    first candidate that collides with nothing. If every candidate is blocked
    (a very small window), returns the one overlapping the least, still clamped
    inside the screen -- never off-screen.
    """
    pw, ph = portrait_size
    bw, bh = box_size
    cluster_w = pw + bw + margin // 2
    cluster_h = max(ph, bh)

    left = screen_rect.left + margin
    right = screen_rect.right - margin - cluster_w
    bottom = screen_rect.bottom - margin - cluster_h
    top = screen_rect.top + margin

    candidates = [
        pygame.Rect(left, bottom, cluster_w, cluster_h),   # lower-left
        pygame.Rect(right, bottom, cluster_w, cluster_h),  # lower-right
        pygame.Rect(left, top, cluster_w, cluster_h),      # upper-left
        pygame.Rect(right, top, cluster_w, cluster_h),     # upper-right
    ]

    blocked = [r for r in blocked_rects if r is not None]
    best, best_overlap = None, None
    for cand in candidates:
        cand = cand.clamp(screen_rect)
        overlap = 0
        for rect in blocked:
            clipped = cand.clip(rect)
            overlap += clipped.width * clipped.height
        if overlap == 0:
            return cand
        if best_overlap is None or overlap < best_overlap:
            best, best_overlap = cand, overlap
    return best


def wrap_text(text, font, max_w):
    """Greedy word wrap to max_w pixels."""
    words = text.split()
    if not words:
        return [""]
    lines, current = [], words[0]
    for word in words[1:]:
        trial = current + " " + word
        if font.size(trial)[0] <= max_w:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class TypewriterText:
    """Reveals one stored string. The string is set once by `start()`; nothing
    here ever re-derives it, which is what makes the reveal non-looping."""

    def __init__(self):
        self.full = ""
        self.shown = ""
        self.timer = 0.0

    def start(self, text):
        self.full = text or ""
        self.shown = ""
        self.timer = 0.0

    def update(self, dt):
        if self.done:
            return
        self.timer += dt
        self.shown = self.full[:int(self.timer * CHARS_PER_SEC)]

    def finish(self):
        self.shown = self.full

    @property
    def done(self):
        return len(self.shown) >= len(self.full)


class DialogueBox:
    """Compact framed box + portrait. Sized to its content: a speaker plate, at
    most MAX_LINES of text, and a one-line hint. Deliberately not tall -- it has
    to share the screen with the tank."""

    MAX_LINES = 3

    def __init__(self, font, font_small, font_body):
        self.font = font
        self.font_small = font_small
        self.font_body = font_body
        self.rect = pygame.Rect(0, 0, 0, 0)        # box only
        self.cluster_rect = pygame.Rect(0, 0, 0, 0)  # box + portrait: blocks clicks
        self.skip_rect = pygame.Rect(0, 0, 0, 0)
        self._wrapped = []
        self._wrap_key = None

    def box_height(self):
        """Just enough for the name plate, MAX_LINES of body, and the hint."""
        line_h = self.font_body.get_height()
        return (PAD * 2 + self.font_small.get_height() + 4
                + line_h * self.MAX_LINES + 6 + self.font_small.get_height())

    def measure(self, screen_rect, portrait_key, portrait_max_h):
        """-> (portrait surface, box size). Cheap; safe to call before layout."""
        portrait = portraits.fit_within(portrait_key, portrait_max_h, portrait_max_h)
        box_w = max(280, min(520, int(screen_rect.width * 0.40)))
        return portrait, (box_w, self.box_height())

    def layout(self, cluster, portrait, box_size):
        """Place the portrait at the cluster's left, the box to its right, both
        bottom-aligned."""
        bw, bh = box_size
        p_rect = portrait.get_rect()
        p_rect.left = cluster.left
        p_rect.bottom = cluster.bottom
        self.rect = pygame.Rect(p_rect.right + 8, cluster.bottom - bh, bw, bh)
        self.cluster_rect = self.rect.union(p_rect)
        return p_rect

    def wrapped(self, text):
        inner_w = self.rect.width - 2 * (self._corner() + PAD)
        key = (text, inner_w)
        if key != self._wrap_key:
            self._wrapped = wrap_text(text, self.font_body, inner_w)[:self.MAX_LINES]
            self._wrap_key = key
        return self._wrapped

    def _corner(self):
        return max(FRAME_CORNER_MIN, min(FRAME_CORNER_MAX, self.rect.height // 9))

    def draw(self, surface, portrait, p_rect, speaker, typed: TypewriterText,
             hint=None, skip_label=None, blink=True):
        corner = self._corner()
        surface.blit(portraits.nine_slice(portraits.CHATBOX, self.rect.size, corner),
                     self.rect.topleft)
        surface.blit(portrait, p_rect.topleft)

        inner_x = self.rect.left + corner + PAD
        y = self.rect.top + corner + PAD // 2

        if speaker:
            plate_txt = self.font_small.render(speaker, True, PLATE_TEXT)
            plate = pygame.Rect(inner_x - 4, y, plate_txt.get_width() + 14,
                                plate_txt.get_height() + 4)
            pygame.draw.rect(surface, PLATE_BG, plate, border_radius=3)
            pygame.draw.rect(surface, PLATE_GOLD, plate, width=1, border_radius=3)
            surface.blit(plate_txt, (plate.left + 7, plate.top + 2))
            y = plate.bottom + 4

        budget = len(typed.shown)
        for line in self.wrapped(typed.full):
            if budget <= 0:
                break
            surface.blit(self.font_body.render(line[:budget], True, INK), (inner_x, y))
            budget -= len(line) + 1  # +1 for the space the wrap consumed
            y += self.font_body.get_height()

        if hint and (not blink or self._blink_on()):
            txt = self.font_small.render(hint, True, INK_DIM)
            surface.blit(txt, (inner_x, self.rect.bottom - corner - PAD // 2 - txt.get_height()))

        if skip_label:
            self.skip_rect = pygame.Rect(0, 0, 118, 22)
            self.skip_rect.topright = (self.rect.right, self.rect.top - 26)
            pygame.draw.rect(surface, (18, 22, 34), self.skip_rect, border_radius=4)
            pygame.draw.rect(surface, (120, 132, 160), self.skip_rect, width=1, border_radius=4)
            txt = self.font_small.render(skip_label, True, (218, 226, 240))
            surface.blit(txt, (self.skip_rect.centerx - txt.get_width() // 2,
                               self.skip_rect.centery - txt.get_height() // 2))
        else:
            self.skip_rect = pygame.Rect(0, 0, 0, 0)

    def _blink_on(self):
        return (pygame.time.get_ticks() // 500) % 2 == 0
