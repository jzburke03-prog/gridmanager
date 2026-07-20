"""Row of spigot controls: one rotary-dial widget per energy source.

Each source is driven by a 180-degree rotary dial: a circular knob with a
triangle pointer that sweeps the top semicircle from 0% (pointing due west) up
through 50% (due north) to 100% (due east). The dial position sets the source's
REQUESTED output; a colored arc fills behind the track to show the ACTUAL output
lagging toward it (that gap is the plant's latency made visible). A small
seven-segment display above the knob reads out the dial's current percentage,
and the track is demarcated at 0 / 25 / 50 / 75 / 100%.
"""
import math
import pygame
from sources.base_source import SourceStatus

WIDGET_W = 200
WIDGET_GAP = 16

BG = (24, 30, 46)
PANEL = (28, 35, 54)
TEXT = (210, 216, 230)
DIM = (140, 148, 168)
PRICE_CHEAP = (110, 220, 160)
PRICE_MID = (240, 200, 90)
PRICE_EXPENSIVE = (240, 100, 90)

# rotary-dial geometry / palette
DIAL_R = 30                      # knob radius
TRACK_R = DIAL_R + 7             # radius the arc track + ticks ride on
TICK_LABEL_R = TRACK_R + 11      # radius the 0/25/.. numbers sit at
TRACK_BG = (48, 56, 76)
TRACK_WIDTH = 5
KNOB_FACE = (54, 62, 84)
KNOB_EDGE = (18, 22, 34)
KNOB_HILITE = (78, 88, 116)

# seven-segment LCD readout. Off-segments are kept only a hair above the LCD
# backing so lit digits stay crisp at this small size (a brighter "ghost 8"
# behind every digit reads as noise here).
SEG_ON = (120, 250, 176)
SEG_OFF = (20, 28, 25)
SEG_BG = (12, 18, 16)
SEG_DIGITS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
    "5": "afgcd", "6": "afgecd", "7": "abc", "8": "abcdefg", "9": "abcdfg",
}

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


def _draw_seven_seg_number(surface, value_int, center, on_color=SEG_ON):
    """Draw an integer (0..100) as a seven-segment readout with a trailing '%',
    horizontally centered on `center`. Returns nothing; purely decorative."""
    digits = str(int(value_int))
    dw, dh, t, gap = 11, 19, 3, 4
    pct_w = 9  # room reserved for the '%' glyph after the digits
    total_w = len(digits) * dw + (len(digits) - 1) * gap + gap + pct_w
    x0 = center[0] - total_w // 2
    y0 = center[1] - dh // 2

    # recessed LCD backing
    pad = 5
    bg_rect = pygame.Rect(x0 - pad, y0 - pad, total_w + 2 * pad, dh + 2 * pad)
    pygame.draw.rect(surface, SEG_BG, bg_rect, border_radius=4)
    pygame.draw.rect(surface, (40, 52, 48), bg_rect, width=1, border_radius=4)

    x = x0
    for ch in digits:
        _draw_seven_seg_digit(surface, ch, x, y0, dw, dh, t, on_color)
        x += dw + gap
    # a compact '%' drawn from two dots and a slash, in the same LCD color
    px = x + 1
    pygame.draw.circle(surface, on_color, (px + 1, y0 + 3), 2)
    pygame.draw.circle(surface, on_color, (px + pct_w - 2, y0 + dh - 3), 2)
    pygame.draw.line(surface, on_color, (px + pct_w - 1, y0 + 2), (px, y0 + dh - 2), 2)


def _draw_seven_seg_digit(surface, ch, x, y, w, h, t, on_color):
    on = SEG_DIGITS.get(ch, "")
    seg_v = (h - 3 * t) / 2.0
    rects = {
        "a": pygame.Rect(x + t, y, w - 2 * t, t),
        "f": pygame.Rect(x, y + t, t, seg_v),
        "b": pygame.Rect(x + w - t, y + t, t, seg_v),
        "g": pygame.Rect(x + t, y + t + seg_v, w - 2 * t, t),
        "e": pygame.Rect(x, y + 2 * t + seg_v, t, seg_v),
        "c": pygame.Rect(x + w - t, y + 2 * t + seg_v, t, seg_v),
        "d": pygame.Rect(x + t, y + h - t, w - 2 * t, t),
    }
    for name, r in rects.items():
        pygame.draw.rect(surface, on_color if name in on else SEG_OFF, r)


class SpigotPanel:
    def __init__(self, rect: pygame.Rect, font, font_small, font_bold):
        self.rect = rect
        self.font = font
        self.font_small = font_small
        self.font_bold = font_bold
        self.dragging_key = None
        self._dial_centers = {}   # source key -> (cx, cy) of its knob

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
            self._draw_widget(surface, src, box, demand_level)

    def _draw_widget(self, surface, src, box, demand_level):
        card = box.inflate(-10, -10)
        pygame.draw.rect(surface, PANEL, card, border_radius=8)
        pygame.draw.rect(surface, tuple(min(255, c + 30) for c in src.color), card, width=2, border_radius=8)

        cx = card.centerx
        y = card.top + 6

        icon_r = 8
        pygame.draw.circle(surface, src.color, (cx, y + icon_r), icon_r)
        y += icon_r * 2 + 3

        name_txt = self.font_bold.render(src.name, True, TEXT)
        surface.blit(name_txt, (cx - name_txt.get_width() // 2, y))
        y += name_txt.get_height()

        status_color = STATUS_COLORS.get(src.status, DIM)
        status_txt = self.font_small.render(src.status.value, True, status_color)
        surface.blit(status_txt, (cx - status_txt.get_width() // 2, y))
        y += status_txt.get_height() + 1

        # latency countdown badge (reserve the row even when idle, for stable layout)
        ttt = src.time_to_target()
        if ttt > 0.05:
            badge = self.font_small.render(f"⏱ {ttt:0.0f}s", True, (255, 230, 150))
            surface.blit(badge, (cx - badge.get_width() // 2, y))
        y += self.font_small.get_height() + 2

        # seven-segment % readout of the dial position (requested output)
        seg_cy = y + 11
        _draw_seven_seg_number(surface, round(src.requested_pct * 100), (cx, seg_cy))
        y = seg_cy + 11 + 8

        # Rotary dial, centered. The knob's TOPMOST element is the "50" tick
        # label riding above it at TICK_LABEL_R, not the knob edge, so anchor
        # the center off that radius — otherwise the top labels ride back up
        # into the seven-seg display above.
        label_h = self.font_small.get_height()
        dial_cy = y + TICK_LABEL_R + label_h // 2 + 2
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

        # -- tick marks + demarcation labels at 0/25/50/75/100 --
        for pct in (0.0, 0.25, 0.5, 0.75, 1.0):
            a = _pct_to_angle(pct)
            ca, sa = math.cos(a), math.sin(a)
            p_in = (cx + ca * (TRACK_R - 1), cy - sa * (TRACK_R - 1))
            p_out = (cx + ca * (TRACK_R + 5), cy - sa * (TRACK_R + 5))
            pygame.draw.line(surface, (150, 160, 182), p_in, p_out, 2)
            lbl = self.font_small.render(f"{int(pct * 100)}", True, DIM)
            lx = cx + ca * TICK_LABEL_R - lbl.get_width() // 2
            ly = cy - sa * TICK_LABEL_R - lbl.get_height() // 2
            surface.blit(lbl, (lx, ly))

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
