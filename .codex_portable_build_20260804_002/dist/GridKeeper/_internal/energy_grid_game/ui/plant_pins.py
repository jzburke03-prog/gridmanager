"""Compact plant controls pinned directly to the isometric map."""
import math

import pygame

from sources.base_source import SourceStatus

PIN_W, PIN_H = 168, 94
TAB_W, TAB_H = 116, 28
DIAL_R = 22
TRACK_R = 29
TRACK_WIDTH = 4

BG = (18, 23, 36, 226)
EDGE = (86, 96, 118)
TEXT = (218, 224, 236)
DIM = (142, 152, 174)
TRACK_BG = (48, 56, 76)
KNOB_FACE = (54, 62, 84)
KNOB_EDGE = (18, 22, 34)
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

INSTRUCTIONAL_NOTES = {
    "generic": "TRAINING BUS",
    "gas": "GAS CC FLEX",
    "peaker": "FAST PEAK",
    "coal": "COAL SLOW",
    "nuclear": "STRICT MIN",
    "solar": "SOLAR WEATHER",
    "wind": "WIND WEATHER",
    "hydro": "HYDRO READY",
}


def _pct_to_angle(pct):
    return math.radians((1.0 - max(0.0, min(1.0, pct))) * 180.0)


def _angle_to_pct(mx, my, cx, cy):
    angle = math.degrees(math.atan2(-(my - cy), mx - cx))
    if angle < 0:
        angle = 0.0 if mx >= cx else 180.0
    return max(0.0, min(1.0, (180.0 - angle) / 180.0))


def _fit_text(font, text, max_w):
    if font.size(text)[0] <= max_w:
        return text
    suffix = "..."
    while text and font.size(text + suffix)[0] > max_w:
        text = text[:-1]
    return text + suffix if text else ""


class PlantPins:
    def __init__(self, font, font_small, font_bold):
        self.font = font
        self.font_small = font_small
        self.font_bold = font_bold
        self.dragging_key = None
        self._t = 0.0

    @staticmethod
    def _candidates(anchor, viewport):
        ax, ay = anchor
        gap = 14
        raw = [
            (ax - PIN_W / 2, ay - PIN_H - gap),
            (ax + gap, ay - PIN_H / 2),
            (ax - PIN_W - gap, ay - PIN_H / 2),
            (ax - PIN_W / 2, ay + gap),
            (ax + gap, ay - PIN_H - gap),
            (ax - PIN_W - gap, ay - PIN_H - gap),
            (ax + gap, ay + gap),
            (ax - PIN_W - gap, ay + gap),
        ]
        seen = set()
        for x, y in raw:
            rect = pygame.Rect(round(x), round(y), PIN_W, PIN_H)
            rect.clamp_ip(viewport)
            if rect.topleft not in seen:
                seen.add(rect.topleft)
                yield rect
        # Dense fleets at high zoom can exhaust the nearby choices. Search the
        # viewport in compact rows, nearest slots first.
        slots = []
        for y in range(viewport.top, viewport.bottom - PIN_H + 1, PIN_H + 6):
            for x in range(viewport.left, viewport.right - PIN_W + 1, PIN_W + 6):
                slots.append((math.hypot(x + PIN_W / 2 - ax,
                                         y + PIN_H / 2 - ay),
                              pygame.Rect(x, y, PIN_W, PIN_H)))
        for _distance, rect in sorted(slots, key=lambda item: item[0]):
            if rect.topleft not in seen:
                yield rect

    @staticmethod
    def _tab_candidates(target, viewport):
        cx, cy = viewport.center
        dx, dy = target[0] - cx, target[1] - cy
        length = math.hypot(dx, dy)
        if length == 0:
            dx, dy, length = 0.0, -1.0, 1.0
        direction = (dx / length, dy / length)

        hits = []
        if dx > 0:
            hits.append(((viewport.right - cx) / dx, "right"))
        elif dx < 0:
            hits.append(((viewport.left - cx) / dx, "left"))
        if dy > 0:
            hits.append(((viewport.bottom - cy) / dy, "bottom"))
        elif dy < 0:
            hits.append(((viewport.top - cy) / dy, "top"))
        distance, edge = min((hit for hit in hits if hit[0] >= 0),
                             default=(0.0, "top"))
        edge_order = (edge,) + tuple(
            candidate for candidate in ("left", "right", "top", "bottom")
            if candidate != edge)
        for edge in edge_order:
            if edge in ("left", "right"):
                edge_x = viewport.left if edge == "left" else viewport.right
                scale = (edge_x - cx) / dx if dx else distance
                point = (edge_x, cy + dy * scale)
                base = pygame.Rect(
                    viewport.left if edge == "left" else viewport.right - TAB_W,
                    round(point[1] - TAB_H / 2), TAB_W, TAB_H)
                span = viewport.height
            else:
                edge_y = viewport.top if edge == "top" else viewport.bottom
                scale = (edge_y - cy) / dy if dy else distance
                point = (cx + dx * scale, edge_y)
                base = pygame.Rect(
                    round(point[0] - TAB_W / 2),
                    viewport.top if edge == "top" else viewport.bottom - TAB_H,
                    TAB_W, TAB_H)
                span = viewport.width

            step = TAB_H + 6
            seen = set()
            for index in range(math.ceil(span / step) + 2):
                offsets = (0,) if index == 0 else (index * step, -index * step)
                for offset in offsets:
                    rect = base.move(0, offset) if edge in ("left", "right") \
                        else base.move(offset, 0)
                    rect.clamp_ip(viewport)
                    if rect.topleft not in seen:
                        seen.add(rect.topleft)
                        yield rect, edge, direction

    def layout(self, sources, markers, obstacles, viewport):
        """Pure pin placement shared by drawing and hit-testing."""
        blocked = [pygame.Rect(r).inflate(8, 10) for r in obstacles if r is not None]
        result = {}
        for source in sources:
            marker = markers.get(source.key)
            if marker is None:
                continue

            if marker["visible"]:
                card_viewport = viewport.inflate(-16, -16)
                candidates = self._candidates(marker["anchor"], card_viewport)
                rect = next((candidate for candidate in candidates
                             if not any(candidate.inflate(6, 12).colliderect(other)
                                        for other in blocked)), None)
                if rect is None:
                    rect = pygame.Rect(card_viewport.left, card_viewport.top, PIN_W, PIN_H)
                    rect.clamp_ip(card_viewport)
                item = {
                    "kind": "card",
                    "target": marker["target"],
                    "anchor": marker["anchor"],
                    "visible": True,
                    "rect": rect,
                    "dial_center": (rect.left + 36, rect.bottom - 31),
                }
            else:
                choice = next((
                    candidate for candidate in self._tab_candidates(
                        marker["target"], viewport)
                    if not any(candidate[0].colliderect(other)
                               for other in blocked)
                ), None)
                if choice is None:
                    choice = next(self._tab_candidates(marker["target"], viewport))
                rect, edge, direction = choice
                item = {
                    "kind": "tab",
                    "target": marker["target"],
                    "anchor": marker["anchor"],
                    "visible": False,
                    "rect": rect,
                    "edge": edge,
                    "direction": direction,
                }
            blocked.append(rect.inflate(6, 12))
            result[source.key] = item
        return result

    def handle_mouse_down(self, pos, sources, markers, obstacles, viewport):
        layout = self.layout(sources, markers, obstacles, viewport)
        for source in sources:
            item = layout.get(source.key)
            if item is None:
                continue
            if item["kind"] == "tab" and item["rect"].collidepoint(pos):
                return "focus", source.key
            if item["kind"] != "card":
                continue
            cx, cy = item["dial_center"]
            if math.hypot(pos[0] - cx, pos[1] - cy) <= TRACK_R + 10:
                self.dragging_key = source.key
                source.set_handle(_angle_to_pct(pos[0], pos[1], cx, cy))
                return "dial", source.key
        return None

    def handle_mouse_motion(self, pos, sources, markers, obstacles, viewport):
        if self.dragging_key is None:
            return
        layout = self.layout(sources, markers, obstacles, viewport)
        for source in sources:
            item = layout.get(source.key)
            if (source.key == self.dragging_key and item is not None
                    and item["kind"] == "card"):
                cx, cy = item["dial_center"]
                source.set_handle(_angle_to_pct(pos[0], pos[1], cx, cy))
                return

    def handle_mouse_up(self):
        self.dragging_key = None

    def draw(self, surface, sources, markers, obstacles, viewport,
             demand_level=0.5, show_price=True, instructional=False):
        layout = self.layout(sources, markers, obstacles, viewport)
        self._t += 1.0 / 60.0
        bob = round(2 * math.sin(self._t * math.tau / 1.8))
        for source in sources:
            item = layout.get(source.key)
            if item is None:
                continue
            drawn = dict(item)
            moved = item["rect"].move(0, bob)
            if item["kind"] == "card":
                safe = viewport.inflate(-16, -16)
                moved.clamp_ip(safe)
                dx = moved.left - item["rect"].left
                dy = moved.top - item["rect"].top
                drawn["dial_center"] = (item["dial_center"][0] + dx,
                                        item["dial_center"][1] + dy)
            drawn["rect"] = moved
            if item["kind"] == "card":
                self._draw_pin(surface, source, drawn, demand_level, show_price,
                               instructional)
                self._draw_card_chevron(surface, drawn["rect"], source.color,
                                        drawn["anchor"])
            else:
                self._draw_tab(surface, source, drawn)
        return layout

    @staticmethod
    def _draw_card_chevron(surface, rect, color, anchor):
        ax, ay = anchor
        dx = ax - rect.centerx
        dy = ay - rect.centery
        pad = 12

        if rect.collidepoint(anchor) or abs(dy) * rect.width >= abs(dx) * rect.height:
            x = max(rect.left + pad, min(rect.right - pad, round(ax)))
            if dy < 0 and not rect.collidepoint(anchor):
                pts = [(x - 5, rect.top), (x + 5, rect.top), (x, rect.top - 7)]
            else:
                pts = [(x - 5, rect.bottom), (x + 5, rect.bottom),
                       (x, rect.bottom + 7)]
        else:
            y = max(rect.top + pad, min(rect.bottom - pad, round(ay)))
            if dx < 0:
                pts = [(rect.left, y - 5), (rect.left, y + 5),
                       (rect.left - 7, y)]
            else:
                pts = [(rect.right, y - 5), (rect.right, y + 5),
                       (rect.right + 7, y)]
        pygame.draw.polygon(surface, color, pts)

    def _draw_tab(self, surface, source, item):
        rect = item["rect"]
        panel = pygame.Surface(rect.size, pygame.SRCALPHA)
        panel.fill(BG)
        pygame.draw.rect(panel, source.color, panel.get_rect(), 2, border_radius=5)
        surface.blit(panel, rect)

        name = self.font_small.render(source.key.upper(), True, TEXT)
        output = self.font_small.render(
            f"{source.current_output_mw:.0f} MW", True, TEXT)
        text_width = rect.width - 20
        if name.get_width() + output.get_width() > text_width:
            scale = text_width / (name.get_width() + output.get_width())
            name_width = round(name.get_width() * scale)
            name = pygame.transform.scale(
                name, (name_width, name.get_height()))
            output = pygame.transform.scale(
                output, (text_width - name_width, output.get_height()))
        surface.blit(name, (rect.left + 8, rect.centery - name.get_height() // 2))
        surface.blit(output, (rect.right - output.get_width() - 8,
                              rect.centery - output.get_height() // 2))

        if item["edge"] == "left":
            chevron = [(rect.right - 1, rect.centery - 5),
                       (rect.right - 1, rect.centery + 5),
                       (rect.right + 6, rect.centery)]
        elif item["edge"] == "right":
            chevron = [(rect.left, rect.centery - 5),
                       (rect.left, rect.centery + 5),
                       (rect.left - 6, rect.centery)]
        elif item["edge"] == "top":
            chevron = [(rect.centerx - 5, rect.bottom - 1),
                       (rect.centerx + 5, rect.bottom - 1),
                       (rect.centerx, rect.bottom + 6)]
        else:
            chevron = [(rect.centerx - 5, rect.top),
                       (rect.centerx + 5, rect.top),
                       (rect.centerx, rect.top - 6)]
        pygame.draw.polygon(surface, source.color, chevron)

    def _shadow_label(self, surface, text, font, color, pos):
        """Text with a 1px dark drop-shadow, so a label stays legible floating
        over the bright map with no card behind it."""
        surface.blit(font.render(text, True, (6, 8, 14)), (pos[0] + 1, pos[1] + 1))
        surface.blit(font.render(text, True, color), pos)

    def _draw_pin(self, surface, source, item, demand_level, show_price,
                  instructional):
        rect = item["rect"]
        # No card background: the dial and its labels float against the plant
        # they control, so the control reads as part of the generating
        # technology rather than a boxed HUD widget. The name takes the fuel's
        # colour; a drop-shadow carries legibility that the panel used to.
        self._shadow_label(surface, source.name.upper(), self.font_bold,
                           source.color, (rect.left + 8, rect.top + 6))
        pct = f"{round(source.requested_pct * 100)}%"
        pw = self.font_small.size(pct)[0]
        self._shadow_label(surface, pct, self.font_small, PCT_ON,
                           (rect.right - pw - 8, rect.top + 7))

        cx, cy = item["dial_center"]
        self._draw_dial(surface, source, cx, cy)

        status = source.status.value
        remaining = source.time_to_target()
        if remaining > 0.05:
            status = f"{status} {remaining:.0f}s"
        first_row = INSTRUCTIONAL_NOTES.get(source.key, status) if instructional else status
        first_color = DIM if instructional else STATUS_COLORS.get(source.status, DIM)
        first_row = _fit_text(self.font_small, first_row, rect.width - 78)
        self._shadow_label(surface, first_row, self.font_small,
                           first_color, (rect.left + 70, rect.top + 34))
        self._shadow_label(surface, f"{source.current_output_mw:.0f}/{source.max_output_mw:.0f} MW",
                           self.font_small, TEXT, (rect.left + 70, rect.top + 52))
        if show_price:
            self._shadow_label(surface, f"${source.price_at(demand_level):.0f}/MWh",
                               self.font_small, DIM, (rect.left + 70, rect.top + 70))

    @staticmethod
    def _draw_dial(surface, source, cx, cy):
        arc = pygame.Rect(cx - TRACK_R, cy - TRACK_R, TRACK_R * 2, TRACK_R * 2)
        pygame.draw.arc(surface, TRACK_BG, arc, 0.0, math.pi, TRACK_WIDTH)
        if source.actual_pct > 0.001:
            pygame.draw.arc(surface, source.color, arc,
                            _pct_to_angle(source.actual_pct), math.pi, TRACK_WIDTH)
        pygame.draw.circle(surface, KNOB_EDGE, (cx, cy), DIAL_R + 1)
        pygame.draw.circle(surface, KNOB_FACE, (cx, cy), DIAL_R)
        pygame.draw.circle(surface, KNOB_EDGE, (cx, cy), DIAL_R, 2)
        angle = _pct_to_angle(source.requested_pct)
        ca, sa = math.cos(angle), math.sin(angle)
        tip = (cx + ca * (DIAL_R - 3), cy - sa * (DIAL_R - 3))
        base = (cx + ca * 7, cy - sa * 7)
        perp = (-sa, -ca)
        b1 = (base[0] + perp[0] * 5, base[1] + perp[1] * 5)
        b2 = (base[0] - perp[0] * 5, base[1] - perp[1] * 5)
        pointer = tuple(min(255, channel + 40) for channel in source.color)
        pygame.draw.polygon(surface, pointer, [tip, b1, b2])
        pygame.draw.circle(surface, (230, 234, 244), (cx, cy), 4)
