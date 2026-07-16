"""Opening tutorial: mentor portrait + compact dialogue box, typewriter reveal,
highlighted targets, and steps that gate on real game state.

Gameplay is frozen while a step is talking (main.py skips state.update) and
released only for steps that ask the player to do something; those sit in
WAITING_FOR_GAME_ACTION until their condition in tutorial_data.CONDITIONS holds.

State is explicit and one-way. `phase` records WHICH text is on screen (the step
line, a success line, or a corrective line) instead of inferring it from whichever
timer happens to be non-zero -- the previous version did infer it, and a timer
hitting zero silently swapped the text's identity mid-frame, which made completed
steps re-fire forever. Steps are also recorded in `completed_step_ids` and never
re-entered.
"""
import math

import pygame

from ui.dialogue import (DialogueBox, DialogueState, TypewriterText,
                         get_dialogue_rect)
from ui.tutorial_data import CONDITIONS, STEPS

SUCCESS_HOLD = 1.6       # how long the thumbs-up confirmation holds
CORRECTION_HOLD = 2.2    # how long a corrective line holds

PORTRAIT_MAX_H = 150
HIGHLIGHT = (255, 214, 120)

# which text is currently on screen -- stored, never derived
PHASE_LINE = "line"
PHASE_SUCCESS = "success"
PHASE_CORRECTION = "correction"


class TutorialManager:
    def __init__(self, font, font_small, font_body):
        self.box = DialogueBox(font, font_small, font_body)
        self.typed = TypewriterText()

        self.state = DialogueState.OPENING
        self.current_step = 0
        self.dialogue_index = 0
        self.phase = PHASE_LINE
        self.completed_step_ids = set()
        self.portrait = STEPS[0]["portrait"]
        self.highlight_rect = None

        self._hold = 0.0
        self._regions = {}
        self._ctx = {}
        self._p_rect = pygame.Rect(0, 0, 0, 0)

    # -- introspection ----------------------------------------------------

    @property
    def step(self):
        return STEPS[self.current_step]

    @property
    def active(self) -> bool:
        return self.state not in (DialogueState.CLOSED, DialogueState.COMPLETE)

    @property
    def finished(self) -> bool:
        return self.state == DialogueState.COMPLETE

    @property
    def _lines(self):
        return self.step["lines"]

    @property
    def _on_last_line(self):
        return self.dialogue_index >= len(self._lines) - 1

    def blocks_gameplay(self) -> bool:
        """True while the tutorial is narrating. Action steps release the sim so
        the player can actually perform the thing being asked of them."""
        return self.active and self.state != DialogueState.WAITING_FOR_GAME_ACTION

    # -- transitions ------------------------------------------------------

    def _enter_step(self, state):
        self.dialogue_index = 0
        self._ctx = {
            "baseline_requested": {s.key: s.requested_pct for s in state.sources},
        }
        self._begin_line()

    def _begin_line(self):
        self.phase = PHASE_LINE
        self.typed.start(self._lines[self.dialogue_index])
        self.state = DialogueState.REVEALING_TEXT

    def _next_step(self):
        """Walk forward to the next step that has not already been completed."""
        index = self.current_step + 1
        while index < len(STEPS) and STEPS[index]["id"] in self.completed_step_ids:
            index += 1
        if index >= len(STEPS):
            self.state = DialogueState.CLOSING
            return
        self.current_step = index
        self.state = DialogueState.OPENING

    def complete_step(self, audio=None):
        """The step's condition came true: record it, confirm, then continue."""
        self.completed_step_ids.add(self.step["id"])
        success = self.step.get("success")
        if not success:
            self._next_step()
            return
        if audio:
            audio.play("correct")
        self.phase = PHASE_SUCCESS
        self.portrait = success["portrait"]
        self.typed.start(success["text"])
        self._hold = SUCCESS_HOLD
        self.state = DialogueState.REVEALING_TEXT

    def _correct(self, audio=None):
        correction = self.step.get("correction")
        if not correction or self.phase == PHASE_CORRECTION:
            return
        if audio:
            audio.play("invalid")
        self.phase = PHASE_CORRECTION
        self.portrait = correction["portrait"]
        self.typed.start(correction["text"])
        self._hold = CORRECTION_HOLD
        self.state = DialogueState.REVEALING_TEXT

    def _resume_after_correction(self):
        """Back to the instruction, already fully revealed. Re-typing it would
        read as the dialogue repeating itself."""
        self.phase = PHASE_LINE
        self.portrait = self.step["portrait"]
        self.typed.start(self._lines[self.dialogue_index])
        self.typed.finish()
        self.state = DialogueState.WAITING_FOR_GAME_ACTION

    def finish(self):
        self.state = DialogueState.COMPLETE
        self.highlight_rect = None

    def close_for_retry(self):
        """A retry after failure returns straight to gameplay: the tutorial does
        not reopen, and whatever was already completed stays completed. Only a
        brand-new TutorialManager (i.e. a fresh launch) replays it."""
        if self.state != DialogueState.COMPLETE:
            self.state = DialogueState.CLOSED
        self.highlight_rect = None

    def skip(self):
        """Skip closes the whole tutorial and marks every step done, so nothing
        can re-open later."""
        self.completed_step_ids.update(s["id"] for s in STEPS)
        self.state = DialogueState.CLOSING

    # -- update -----------------------------------------------------------

    def update(self, dt, state, regions, audio=None):
        if not self.active:
            return
        self._regions = regions or {}

        if self.state == DialogueState.OPENING:
            self._enter_step(state)

        self.highlight_rect = self._regions.get(self.step.get("highlight"))
        if self.phase == PHASE_LINE:
            self.portrait = self.step["portrait"]

        if self.state == DialogueState.REVEALING_TEXT:
            if not self.typed.done:
                self.typed.update(dt)
            elif self.phase == PHASE_LINE:
                self.state = (DialogueState.WAITING_FOR_GAME_ACTION
                              if self._on_last_line and self.step.get("wait_for")
                              else DialogueState.WAITING_FOR_INPUT)
            else:
                self._hold -= dt
                if self._hold <= 0:
                    if self.phase == PHASE_SUCCESS:
                        self._next_step()
                    else:
                        self._resume_after_correction()

        elif self.state == DialogueState.WAITING_FOR_GAME_ACTION:
            condition = CONDITIONS.get(self.step["wait_for"])
            if condition and condition(state, self._ctx):
                self.complete_step(audio)

        if self.state == DialogueState.CLOSING:
            self.finish()

    # -- input ------------------------------------------------------------

    def advance(self, audio=None):
        """Exactly one step of progress. Called once per input event."""
        if not self.active:
            return
        if self.state == DialogueState.REVEALING_TEXT:
            if not self.typed.done:
                self.typed.finish()   # first press completes the reveal
                return
            if self.phase == PHASE_SUCCESS:
                self._next_step()
            elif self.phase == PHASE_CORRECTION:
                self._resume_after_correction()
            return
        if self.state == DialogueState.WAITING_FOR_INPUT:
            if audio:
                audio.play("dialogue_advance")
            if not self._on_last_line:
                self.dialogue_index += 1
                self._begin_line()
            else:
                self.completed_step_ids.add(self.step["id"])
                self._next_step()
        # WAITING_FOR_GAME_ACTION: can't be talked past; do the thing

    def handle_event(self, event, audio=None) -> bool:
        """Returns True if the tutorial consumed the event."""
        if not self.active:
            return False

        if event.type == pygame.KEYDOWN:
            # pygame does not auto-repeat KEYDOWN unless key.set_repeat is on, so
            # holding a key yields exactly one event and cannot skip lines.
            if event.key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER):
                self.advance(audio)
                return True
            return False  # ESC / R / speed keys stay live

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.box.skip_rect.collidepoint(event.pos):
                if audio:
                    audio.play("ui_click")
                self.skip()
                return True
            if self.box.cluster_rect.collidepoint(event.pos):
                self.advance(audio)
                return True
            if self.state == DialogueState.WAITING_FOR_GAME_ACTION:
                target = self.highlight_rect
                if target and target.collidepoint(event.pos):
                    return False  # the click we asked for: let gameplay have it
                self._correct(audio)
                return True       # stray click: don't let it reach the grid
            self.advance(audio)
            return True

        return False

    # -- draw -------------------------------------------------------------

    def draw_highlight(self, surface):
        if not self.active or not self.highlight_rect:
            return
        rect = self.highlight_rect
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 1000.0 * 3.0)
        alpha = int(90 + 110 * pulse)
        pad = 6
        glow = pygame.Surface((rect.width + pad * 2 + 8, rect.height + pad * 2 + 8),
                              pygame.SRCALPHA)
        local = pygame.Rect(4, 4, rect.width + pad * 2, rect.height + pad * 2)
        pygame.draw.rect(glow, (*HIGHLIGHT, alpha // 3), local, width=8, border_radius=10)
        pygame.draw.rect(glow, (*HIGHLIGHT, alpha), local, width=3, border_radius=8)
        surface.blit(glow, (rect.left - pad - 4, rect.top - pad - 4))

    def draw(self, surface):
        if not self.active:
            return
        screen_rect = surface.get_rect()
        portrait, box_size = self.box.measure(screen_rect, self.portrait, PORTRAIT_MAX_H)

        # The box must never sit on the tank; the highlight it is pointing at is
        # blocked too, so it can't cover the thing it is asking the player to use.
        blocked = [self._regions.get(k) for k in ("tank", "city", "spigot_panel",
                                                  "speed_control")]
        blocked.append(self.highlight_rect)
        cluster = get_dialogue_rect(screen_rect, portrait.get_size(), blocked, box_size)
        self._p_rect = self.box.layout(cluster, portrait, box_size)

        hint = None
        if self.state == DialogueState.WAITING_FOR_GAME_ACTION:
            hint = self.step.get("action_hint", "Complete the highlighted action")
        elif self.state == DialogueState.WAITING_FOR_INPUT:
            hint = "SPACE / CLICK to continue"

        self.box.draw(surface, portrait, self._p_rect, self.step.get("speaker"),
                      self.typed, hint=hint, skip_label="SKIP TUTORIAL")
