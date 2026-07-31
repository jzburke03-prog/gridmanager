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


def _pct_to_angle(pct):
    return math.radians((1.0 - max(0.0, min(1.0, pct))) * 180.0)


def _angle_to_pct(mx, my, cx, cy):
    angle = math.degrees(math.atan2(-(my - cy), mx - cx))
    if angle < 0:
        angle = 0.0 if mx >= cx else 180.0
    return max(0.0, min(1.0, (180.0 - angle) / 180.0))


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
        blocked = [pygame.Rect(r) for r in obstacles if r is not None]
        result = {}
        for source in sources:
            marker = markers.get(source.key)
            if marker is None:
                continue

            if marker["visible"]:
                candidates = self._candidates(marker["anchor"], viewport)
                rect = next((candidate for candidate in candidates
                             if not any(candidate.colliderect(other)
                                        for other in blocked)), None)
                if rect is None:
                    rect = pygame.Rect(viewport.left, viewport.top, PIN_W, PIN_H)
                    rect.clamp_ip(viewport)
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
            blocked.append(rect)
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
             demand_level=0.5, show_price=True):
        layout = self.layout(sources, markers, obstacles, viewport)
        self._t += 1.0 / 60.0
        bob = round(2 * math.sin(self._t * math.tau / 1.8))
        for source in sources:
            item = layout.get(source.key)
            if item is None:
                continue
            drawn = dict(item)
            drawn["rect"] = item["rect"].move(0, bob)
            if item["kind"] == "card":
                cx, cy = item["dial_center"]
                drawn["dial_center"] = (cx, cy + bob)
                self._draw_pin(surface, source, drawn, demand_level, show_price)
                self._draw_card_chevron(surface, drawn["rect"], source.color)
            else:
                self._draw_tab(surface, source, drawn)
        return layout

    @staticmethod
    def _draw_card_chevron(surface, rect, color):
        pygame.draw.polygon(surface, color, [
            (rect.centerx - 5, rect.bottom),
            (rect.centerx + 5, rect.bottom),
            (rect.centerx, rect.bottom + 6),
        ])

    def _draw_tab(self, surface, source, item):
        rect = item["rect"]
        panel = pygame.Surface(rect.size, pygame.SRCALPHA)
        panel.fill(BG)
        pygame.draw.rect(panel, source.color, panel.get_rect(), 2, border_radius=5)
        surface.blit(panel, rect)

        name = self.font_small.render(source.key.upper(), True, TEXT)
        output = self.font_small.render(
            f"{source.current_output_mw:.0f} MW", True, TEXT)
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

    def _draw_pin(self, surface, source, item, demand_level, show_price):
        rect = item["rect"]
        panel = pygame.Surface(rect.size, pygame.SRCALPHA)
        panel.fill(BG)
        pygame.draw.rect(panel, source.color, panel.get_rect(), 2, border_radius=6)
        surface.blit(panel, rect)

        name = self.font_bold.render(source.name.upper(), True, TEXT)
        surface.blit(name, (rect.left + 8, rect.top + 6))
        pct = self.font_small.render(f"{round(source.requested_pct * 100)}%", True, PCT_ON)
        surface.blit(pct, (rect.right - pct.get_width() - 8, rect.top + 7))

        cx, cy = item["dial_center"]
        self._draw_dial(surface, source, cx, cy)

        status = source.status.value
        remaining = source.time_to_target()
        if remaining > 0.05:
            status = f"{status} {remaining:.0f}s"
        status_text = self.font_small.render(
            status, True, STATUS_COLORS.get(source.status, DIM))
        surface.blit(status_text, (rect.left + 70, rect.top + 34))
        mw = self.font_small.render(
            f"{source.current_output_mw:.0f}/{source.max_output_mw:.0f} MW", True, TEXT)
        surface.blit(mw, (rect.left + 70, rect.top + 52))
        if show_price:
            price = self.font_small.render(f"${source.price_at(demand_level):.0f}/MWh", True, DIM)
            surface.blit(price, (rect.left + 70, rect.top + 70))

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
