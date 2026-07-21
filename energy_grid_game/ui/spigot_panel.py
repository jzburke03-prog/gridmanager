"""Row of spigot controls: one rotary-dial widget per energy source.

Each source is driven by a 180-degree rotary dial: a circular knob with a
triangle pointer that sweeps the top semicircle from 0% (pointing due west) up
through 50% (due north) to 100% (due east). The dial position sets the source's
REQUESTED output; a colored arc fills behind the track to show the ACTUAL output
lagging toward it (that gap is the plant's latency made visible). Above the knob
sits an animated sprite of the actual power plant (its loop speed scales with
output, and it darkens when the plant is idle/offline), and the track is
demarcated at 0 / 25 / 50 / 75 / 100%.
"""
import math
import pygame
from sources.base_source import SourceStatus
from ui import assets

# source key -> resource_icons/<name>_icon.png (peaker shares the gas icon)
_RESOURCE_ICON = {"nuclear": "nuclear", "coal": "coal", "gas": "gas",
                  "peaker": "gas", "solar": "solar", "wind": "wind", "hydro": "hydro"}
# statuses where the plant sprite freezes on a darkened frame
_IDLE_STATUS = (SourceStatus.OFFLINE, SourceStatus.DEPLETED, SourceStatus.SCRAM,
                SourceStatus.MAINTENANCE)

WIDGET_W = 200
WIDGET_GAP = 16

BG = (24, 30, 46)
TEXT = (210, 216, 230)
DIM = (140, 148, 168)
PRICE_CHEAP = (110, 220, 160)
PRICE_MID = (240, 200, 90)
PRICE_EXPENSIVE = (240, 100, 90)

# rotary-dial geometry / palette. The dial is deliberately compact now — the
# animated plant sprite above it is the hero of the card, not the control.
DIAL_R = 22                      # knob radius
TRACK_R = DIAL_R + 7             # radius the arc track rides on
TRACK_BG = (48, 56, 76)
TRACK_WIDTH = 4
KNOB_FACE = (54, 62, 84)
KNOB_EDGE = (18, 22, 34)
KNOB_HILITE = (78, 88, 116)

# requested-% text readout above each dial
PCT_ON = (120, 250, 176)

STATUS_COLORS = {
    SourceStatus.OFFLINE: (110, 116, 130),
    SourceStatus.RAMPING: (240, 200, 80),
    SourceStatus.ONLINE: (100, 220, 140),
    SourceStatus.COOLDOWN: (240, 150, 60),
    SourceStatus.DEPLETED: (230, 80, 80),
    SourceStatus.SCRAM: (230, 40, 40),
    SourceStatus.MAINTENANCE: (200, 100, 220),
}


def _pct_to_angle(pct: float) -> float:
    """Dial value 0..1 -> math angle in radians. 0% = 180deg (west),
    50% = 90deg (north), 100% = 0deg (east); the pointer only ever travels the
    top semicircle."""
    return math.radians((1.0 - max(0.0, min(1.0, pct))) * 180.0)


def _angle_to_pct(mx, my, cx, cy) -> float:
    """Inverse: a mouse position around the knob center -> 0..1, clamped to the
    top semicircle (below-horizontal drags snap to the nearest end)."""
    a = math.degrees(math.atan2(-(my - cy), mx - cx))  # up is positive
    if a < 0:
        a = 0.0 if (mx - cx) >= 0 else 180.0
    return max(0.0, min(1.0, (180.0 - a) / 180.0))


class SpigotPanel:
    def __init__(self, rect: pygame.Rect, font, font_small, font_bold):
        self.rect = rect
        self.font = font
        self.font_small = font_small
        self.font_bold = font_bold
        self.dragging_key = None
        self._dial_centers = {}   # source key -> (cx, cy) of its knob
        self._anim_phase = {}     # source key -> running plant-animation frame phase
        # Warm the plant-sprite cache now (once, at construction) so the first
        # game frame doesn't stall ~300ms scaling the 627px source frames.
        for tech in assets.TECH_BY_SOURCE.values():
            assets.tech_frames(tech, 52)
            assets.tech_frames(tech, 52, dim=True)

    def _layout(self, n):
        # shrink card width when the window is too narrow for every full-size
        # card, down to a floor that still fits the dial + its tick labels
        margin = 20
        avail = self.rect.width - 2 * margin - (n - 1) * WIDGET_GAP
        widget_w = max(120, min(WIDGET_W, avail // n))
        total_w = n * widget_w + (n - 1) * WIDGET_GAP
        start_x = self.rect.centerx - total_w // 2
        return [pygame.Rect(start_x + i * (widget_w + WIDGET_GAP), self.rect.top, widget_w, self.rect.height)
                for i in range(n)]

    def source_x_centers(self, sources) -> dict:
        """Card center-x per source key, for routing pipes down from each card."""
        boxes = self._layout(len(sources))
        return {src.key: box.centerx for src, box in zip(sources, boxes)}

    def card_rects(self, sources) -> dict:
        """Card rect per source key, so callers (e.g. the tutorial) can point at
        a specific plant without duplicating the layout math."""
        boxes = self._layout(len(sources))
        return {src.key: box.inflate(-10, -10) for src, box in zip(sources, boxes)}

    # -- interaction --------------------------------------------------------
    def handle_mouse_down(self, pos, sources):
        for src in sources:
            c = self._dial_centers.get(src.key)
            if c and math.hypot(pos[0] - c[0], pos[1] - c[1]) <= DIAL_R + 16:
                self.dragging_key = src.key
                self._apply_drag(pos, src, c)
                return True
        return False

    def handle_mouse_up(self):
        self.dragging_key = None

    def handle_mouse_motion(self, pos, sources):
        if not self.dragging_key:
            return
        for src in sources:
            if src.key == self.dragging_key:
                c = self._dial_centers.get(src.key)
                if c:
                    self._apply_drag(pos, src, c)
                return

    def _apply_drag(self, pos, src, center):
        src.set_handle(_angle_to_pct(pos[0], pos[1], center[0], center[1]))

    # -- drawing ------------------------------------------------------------
    def draw(self, surface, sources, demand_level=0.5):
        pygame.draw.rect(surface, BG, self.rect)
        boxes = self._layout(len(sources))
        self._dial_centers = {}
        for src, box in zip(sources, boxes):
            # a running plant loops faster the harder it's producing; idle plants
            # don't advance (they show a frozen, darkened frame). Fixed 1/60 step,
            # matching the other particle animations (see pipes.py).
            rate = 0.0 if src.actual_pct < 0.02 else (1.5 + 6.0 * src.actual_pct)
            self._anim_phase[src.key] = self._anim_phase.get(src.key, 0.0) + rate / 60.0
            self._draw_widget(surface, src, box, demand_level)

    def _draw_widget(self, surface, src, box, demand_level):
        # No card panel behind the plant — the animated sprite reads directly
        # against the gameplay backdrop so the animation stays the focus.
        card = box.inflate(-10, -10)

        cx = card.centerx
        y = card.top + 4

        # HERO: the animated power-plant sprite, large so the art is the card's
        # focus. Frozen + darkened when the plant is idle or offline.
        idle = src.actual_pct < 0.02 or src.status in _IDLE_STATUS
        sprite_h = 92 if card.width >= 150 else 60
        frames = assets.tech_frames(assets.TECH_BY_SOURCE[src.key], sprite_h, dim=idle)
        spr = frames[int(self._anim_phase.get(src.key, 0.0)) % 4]
        surface.blit(spr, (cx - spr.get_width() // 2, y))
        y += sprite_h + 2

        # resource icon + name, centered as a group
        r_icon = assets.resource_icon(_RESOURCE_ICON[src.key], 16)
        name_txt = self.font_bold.render(src.name, True, TEXT)
        group_w = r_icon.get_width() + 4 + name_txt.get_width()
        gx = cx - group_w // 2
        surface.blit(r_icon, (gx, y + (name_txt.get_height() - 16) // 2))
        surface.blit(name_txt, (gx + r_icon.get_width() + 4, y))
        y += name_txt.get_height()

        # status + requested-% on one compact row (latency merged in when ramping)
        status = src.status.value
        ttt = src.time_to_target()
        if ttt > 0.05:
            status = f"{status} · {ttt:0.0f}s"
        status_txt = self.font_small.render(status, True, STATUS_COLORS.get(src.status, DIM))
        pct_txt = self.font_small.render(f"{round(src.requested_pct * 100)}%", True, PCT_ON)
        row_w = status_txt.get_width() + 8 + pct_txt.get_width()
        rx = cx - row_w // 2
        surface.blit(status_txt, (rx, y))
        surface.blit(pct_txt, (rx + status_txt.get_width() + 8, y))
        y += status_txt.get_height() + 3

        # compact rotary dial (no number labels), anchored off the arc track
        dial_cy = y + TRACK_R + 4
        self._dial_centers[src.key] = (cx, dial_cy)
        self._draw_dial(surface, src, cx, dial_cy)

        y = dial_cy + DIAL_R + 6

        mw_txt = self.font_small.render(f"{src.current_output_mw:0.0f} / {src.max_output_mw:0.0f} MW", True, TEXT)
        surface.blit(mw_txt, (cx - mw_txt.get_width() // 2, y))
        y += mw_txt.get_height() + 1

        price = src.price_at(demand_level)
        price_color = PRICE_CHEAP if price < 40 else (PRICE_MID if price < 80 else PRICE_EXPENSIVE)
        price_txt = self.font_small.render(f"${price:0.0f}/MWh", True, price_color)
        surface.blit(price_txt, (cx - price_txt.get_width() // 2, y))

    def _draw_dial(self, surface, src, cx, cy):
        # -- background track arc (semicircle, west -> north -> east) --
        arc_box = pygame.Rect(cx - TRACK_R, cy - TRACK_R, TRACK_R * 2, TRACK_R * 2)
        pygame.draw.arc(surface, TRACK_BG, arc_box, 0.0, math.pi, TRACK_WIDTH)

        # -- filled arc up to ACTUAL output, in the source color (lags the
        # pointer, which sits at the REQUESTED value -> latency made visible) --
        act_angle = _pct_to_angle(src.actual_pct)
        if src.actual_pct > 0.001:
            # pygame arc sweeps CCW from start to stop; actual fills from west
            # (pi) down to the actual-output angle
            pygame.draw.arc(surface, src.color, arc_box, act_angle, math.pi, TRACK_WIDTH)

        # -- minor orientation ticks at 0/50/100 (no numbers — the % readout
        # above the dial carries the exact value, so the control stays compact) --
        for pct in (0.0, 0.5, 1.0):
            a = _pct_to_angle(pct)
            ca, sa = math.cos(a), math.sin(a)
            p_in = (cx + ca * (TRACK_R - 1), cy - sa * (TRACK_R - 1))
            p_out = (cx + ca * (TRACK_R + 4), cy - sa * (TRACK_R + 4))
            pygame.draw.line(surface, (110, 120, 142), p_in, p_out, 2)

        # -- knob body --
        pygame.draw.circle(surface, KNOB_EDGE, (cx, cy), DIAL_R + 1)
        pygame.draw.circle(surface, KNOB_FACE, (cx, cy), DIAL_R)
        pygame.draw.circle(surface, KNOB_HILITE, (cx, cy - DIAL_R // 3), DIAL_R // 2, width=0)
        pygame.draw.circle(surface, KNOB_FACE, (cx, cy), DIAL_R - 5)
        pygame.draw.circle(surface, KNOB_EDGE, (cx, cy), DIAL_R, width=2)

        # -- triangle pointer at the REQUESTED value --
        a = _pct_to_angle(src.requested_pct)
        ca, sa = math.cos(a), math.sin(a)
        tip = (cx + ca * (DIAL_R - 3), cy - sa * (DIAL_R - 3))
        # base of the triangle sits near the hub, perpendicular to the pointer
        perp = (-sa, -ca)
        base_c = (cx + ca * 7, cy - sa * 7)
        half = 5
        b1 = (base_c[0] + perp[0] * half, base_c[1] + perp[1] * half)
        b2 = (base_c[0] - perp[0] * half, base_c[1] - perp[1] * half)
        point_color = tuple(min(255, c + 40) for c in src.color)
        pygame.draw.polygon(surface, point_color, [tip, b1, b2])
        pygame.draw.polygon(surface, (250, 250, 255), [tip, b1, b2], width=1)
        # hub cap
        pygame.draw.circle(surface, (230, 234, 244), (cx, cy), 4)
        pygame.draw.circle(surface, KNOB_EDGE, (cx, cy), 4, width=1)
