"""Opening tutorial: mentor portrait + pixel dialogue box, typewriter reveal,
highlighted targets, and steps that gate on real game state.

Gameplay is frozen while a step is just talking (main.py skips state.update),
and released for steps that ask the player to actually do something — those stay
active until their condition in tutorial_data.CONDITIONS is satisfied.
"""
import math

import pygame

from ui import portraits
from ui.tutorial_data import CONDITIONS, STEPS

CHARS_PER_SEC = 55.0
SUCCESS_TIME = 2.0       # how long the thumbs-up confirmation holds
CORRECTION_TIME = 2.6    # how long a corrective line holds

MARGIN = 24
PORTRAIT_COL_W = 210
BOX_MAX_W = 880
CHATBOX_ASPECT = 1546 / 622.0  # cropped frame, measured off the asset

INK = (58, 46, 32)          # dialogue text on the cream chatbox
INK_DIM = (120, 104, 84)
PLATE_BG = (28, 44, 82)     # matches the chatbox's dark blue frame
PLATE_TEXT = (238, 226, 196)
SKIP_BG = (18, 22, 34)
SKIP_BORDER = (120, 132, 160)
SKIP_TEXT = (218, 226, 240)
HIGHLIGHT = (255, 214, 120)


def _wrap(text, font, max_w):
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


class TutorialManager:
    def __init__(self, font, font_small, font_big):
        self.font = font
        self.font_small = font_small
        self.font_big = font_big

        self.active = True
        self.current_step = 0
        self.dialogue_index = 0
        self.displayed_text = ""
        self.text_reveal_timer = 0.0
        self.waiting_for_action = False
        self.portrait = STEPS[0]["portrait"]
        self.highlight_rect = None

        self._t = 0.0
        self._regions = {}
        self._ctx = {}
        self._success_timer = 0.0
        self._correction_timer = 0.0
        self._wrapped = None
        self._wrap_key = None
        self._panel_rect = pygame.Rect(0, 0, 0, 0)
        self._skip_rect = pygame.Rect(0, 0, 0, 0)
        self._entered = False

    # -- step access ------------------------------------------------------

    @property
    def step(self):
        return STEPS[self.current_step]

    @property
    def _lines(self):
        return self.step["lines"]

    @property
    def _full_text(self):
        if self._correction_timer > 0:
            return self.step.get("correction", {}).get("text", "")
        if self._success_timer > 0:
            return self.step.get("success", {}).get("text", "")
        return self._lines[self.dialogue_index]

    @property
    def _fully_revealed(self):
        return len(self.displayed_text) >= len(self._full_text)

    def blocks_gameplay(self) -> bool:
        """True while the tutorial is narrating. Action steps release the sim so
        the player can actually perform the thing being asked of them."""
        return self.active and not self.waiting_for_action

    # -- lifecycle --------------------------------------------------------

    def _enter_step(self, state):
        self.dialogue_index = 0
        self.displayed_text = ""
        self.text_reveal_timer = 0.0
        self.waiting_for_action = False
        self._success_timer = 0.0
        self._correction_timer = 0.0
        self._ctx = {
            "baseline_requested": {s.key: s.requested_pct for s in state.sources},
        }
        self._entered = True

    def advance(self):
        """Space / Enter / click: finish the reveal, then move on."""
        if not self.active:
            return
        if not self._fully_revealed:
            self.displayed_text = self._full_text
            return
        if self._correction_timer > 0:
            self._correction_timer = 0.0
            self.displayed_text = self._full_text
            return
        if self._success_timer > 0:
            self._success_timer = 0.0
            self._next_step()
            return
        if self.waiting_for_action:
            return  # an action step can't be talked past; do the thing
        if self.dialogue_index < len(self._lines) - 1:
            self.dialogue_index += 1
            self.displayed_text = ""
            self.text_reveal_timer = 0.0
            return
        if self.step.get("wait_for"):
            self.waiting_for_action = True
            return
        self._next_step()

    def _next_step(self):
        if self.current_step >= len(STEPS) - 1:
            self.finish()
            return
        self.current_step += 1
        self._entered = False  # re-enter on the next update, with fresh baselines

    def complete_step(self):
        """The step's condition came true: confirm it, then continue."""
        self.waiting_for_action = False
        self._correction_timer = 0.0
        if self.step.get("success"):
            self._success_timer = SUCCESS_TIME
            self.displayed_text = ""
            self.text_reveal_timer = 0.0
        else:
            self._next_step()

    def _correct(self):
        if not self.step.get("correction") or self._correction_timer > 0:
            return
        self._correction_timer = CORRECTION_TIME
        self.displayed_text = ""
        self.text_reveal_timer = 0.0

    def finish(self):
        self.active = False
        self.waiting_for_action = False
        self.highlight_rect = None

    def skip(self):
        self.finish()

    # -- update -----------------------------------------------------------

    def update(self, dt, state, regions):
        if not self.active:
            return
        self._t += dt
        self._regions = regions or {}

        if not self._entered:
            self._enter_step(state)

        step = self.step
        self.highlight_rect = self._regions.get(step.get("highlight"))

        if self._correction_timer > 0:
            self.portrait = step["correction"]["portrait"]
        elif self._success_timer > 0:
            self.portrait = step["success"]["portrait"]
        else:
            self.portrait = step["portrait"]

        # typewriter
        target = self._full_text
        if len(self.displayed_text) < len(target):
            self.text_reveal_timer += dt
            chars = int(self.text_reveal_timer * CHARS_PER_SEC)
            self.displayed_text = target[:chars]

        # last line finished revealing on an action step -> hand control back
        if (step.get("wait_for") and not self.waiting_for_action
                and self._correction_timer <= 0 and self._success_timer <= 0
                and self.dialogue_index == len(self._lines) - 1 and self._fully_revealed):
            self.waiting_for_action = True

        # Checked before the correction/success early-outs on purpose: a player
        # who does the right thing while a corrective line is still on screen
        # must be credited immediately, not ignored until the line times out.
        if self.waiting_for_action:
            condition = CONDITIONS.get(step["wait_for"])
            if condition and condition(state, self._ctx):
                self.complete_step()
                return

        if self._correction_timer > 0:
            self._correction_timer = max(0.0, self._correction_timer - dt)
            if self._correction_timer == 0.0:
                self.displayed_text = ""
                self.text_reveal_timer = 0.0
            return

        if self._success_timer > 0:
            self._success_timer = max(0.0, self._success_timer - dt)
            if self._success_timer == 0.0 and self._fully_revealed:
                self._next_step()

    # -- input ------------------------------------------------------------

    def handle_event(self, event) -> bool:
        """Returns True if the tutorial consumed the event."""
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER):
                self.advance()
                return True
            return False  # ESC / R / speed keys stay live

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._skip_rect.collidepoint(event.pos):
                self.skip()
                return True
            if self._panel_rect.collidepoint(event.pos):
                self.advance()
                return True
            if self.waiting_for_action:
                target = self.highlight_rect
                if target and target.collidepoint(event.pos):
                    return False  # the click we asked for: let gameplay have it
                self._correct()
                return True       # stray click: don't let it reach the grid
            self.advance()
            return True

        return False

    # -- draw -------------------------------------------------------------

    def _layout(self, screen_w, screen_h):
        box_w = min(BOX_MAX_W, screen_w - PORTRAIT_COL_W - 3 * MARGIN)
        box_w = max(320, box_w)
        box_h = int(box_w / CHATBOX_ASPECT)
        box = pygame.Rect(MARGIN * 2 + PORTRAIT_COL_W, screen_h - MARGIN - box_h, box_w, box_h)

        max_h = max(170, min(330, int(screen_h * 0.34)))
        src = portraits.load(self.portrait)
        sw, sh = src.get_size()
        scale = min(PORTRAIT_COL_W / sw, max_h / sh)
        p_surf = portraits.scaled_to_height(self.portrait, max(1, int(sh * scale)))
        p_rect = p_surf.get_rect()
        p_rect.centerx = MARGIN + PORTRAIT_COL_W // 2
        p_rect.bottom = box.bottom
        return box, p_surf, p_rect

    def draw(self, surface):
        if not self.active:
            return
        screen_w, screen_h = surface.get_size()
        box, p_surf, p_rect = self._layout(screen_w, screen_h)

        self._panel_rect = box.union(p_rect)
        self._skip_rect = pygame.Rect(0, 0, 132, 24)
        self._skip_rect.topright = (box.right, box.top - 28)

        if self.highlight_rect:
            self._draw_highlight(surface, self.highlight_rect)

        surface.blit(portraits.scaled_to_width(portraits.CHATBOX, box.width), box.topleft)
        surface.blit(p_surf, p_rect.topleft)

        self._draw_name_plate(surface, box)
        self._draw_skip(surface)
        self._draw_text(surface, box)

    def _draw_highlight(self, surface, rect):
        pulse = 0.5 + 0.5 * math.sin(self._t * 3.0)
        alpha = int(90 + 110 * pulse)
        pad = 6
        glow = pygame.Surface((rect.width + pad * 2 + 8, rect.height + pad * 2 + 8), pygame.SRCALPHA)
        local = pygame.Rect(4, 4, rect.width + pad * 2, rect.height + pad * 2)
        pygame.draw.rect(glow, (*HIGHLIGHT, alpha // 3), local, width=8, border_radius=10)
        pygame.draw.rect(glow, (*HIGHLIGHT, alpha), local, width=3, border_radius=8)
        surface.blit(glow, (rect.left - pad - 4, rect.top - pad - 4))

    def _draw_name_plate(self, surface, box):
        name = self.step.get("speaker", "")
        if not name:
            return
        txt = self.font.render(name, True, PLATE_TEXT)
        plate = pygame.Rect(box.left + 14, box.top - 28, txt.get_width() + 22, 26)
        pygame.draw.rect(surface, PLATE_BG, plate, border_radius=5)
        pygame.draw.rect(surface, (198, 158, 74), plate, width=2, border_radius=5)
        surface.blit(txt, (plate.left + 11, plate.centery - txt.get_height() // 2))

    def _draw_skip(self, surface):
        pygame.draw.rect(surface, SKIP_BG, self._skip_rect, border_radius=5)
        pygame.draw.rect(surface, SKIP_BORDER, self._skip_rect, width=1, border_radius=5)
        txt = self.font_small.render("SKIP TUTORIAL", True, SKIP_TEXT)
        surface.blit(txt, (self._skip_rect.centerx - txt.get_width() // 2,
                           self._skip_rect.centery - txt.get_height() // 2))

    def _draw_text(self, surface, box):
        pad = 20
        cream = pygame.Rect(
            box.left + int(box.width * portraits.CHATBOX_INSET_X) + pad,
            box.top + int(box.height * portraits.CHATBOX_INSET_TOP) + pad,
            box.width - 2 * int(box.width * portraits.CHATBOX_INSET_X) - 2 * pad,
            box.height - int(box.height * portraits.CHATBOX_INSET_TOP)
            - int(box.height * portraits.CHATBOX_INSET_BOTTOM) - 2 * pad,
        )

        full = self._full_text
        key = (full, cream.width)
        if key != self._wrap_key:
            self._wrapped = _wrap(full, self.font_big, cream.width)
            self._wrap_key = key

        # reveal character budget across the wrapped lines
        budget = len(self.displayed_text)
        y = cream.top
        for line in self._wrapped:
            if budget <= 0:
                break
            shown = line[:budget]
            budget -= len(line) + 1  # +1 for the space the wrap consumed
            surface.blit(self.font_big.render(shown, True, INK), (cream.left, y))
            y += self.font_big.get_height() + 4

        hint = None
        if self.waiting_for_action and self._fully_revealed:
            hint = self.step.get("action_hint", "Complete the highlighted action")
        elif self._fully_revealed and self._success_timer <= 0 and self._correction_timer <= 0:
            hint = "SPACE / CLICK to continue"
        if hint and (self._t * 2) % 2 < 1.4:
            txt = self.font_small.render(hint, True, INK_DIM)
            surface.blit(txt, (cream.left, cream.bottom - txt.get_height()))
