"""Compact plant controls pinned directly to the isometric map."""
import math

import pygame

from sources.base_source import SourceStatus

PIN_W, PIN_H = 148, 94
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


def strict_above_keys_for_zoom(zoom):
    return ("solar",) if zoom == 4 else ()

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

    def layout(self, sources, anchors, obstacles, viewport, strict_above_keys=()):
        """Pure pin placement shared by drawing and hit-testing."""
        blocked = [pygame.Rect(r) for r in obstacles if r is not None]
        result = {}
        # Solar's only acceptable slot is centred above its broad field, so it
        # claims that slot before flexible cards search around it.
        strict_above_keys = frozenset(strict_above_keys)
        ordered_sources = (sorted(sources, key=lambda source: source.key not in strict_above_keys)
                           if strict_above_keys else sources)
        for source in ordered_sources:
            anchor = anchors.get(source.key)
            if anchor is None:
                continue
            candidates = self._candidates(anchor, viewport)
            if source.key in strict_above_keys:
                # Its field is broad and asymmetric: a side/below fallback
                # reads as an unrelated floating control over the panels.
                # Keep the card centred above the field or omit it until the
                # camera provides that clean slot.
                candidate = next(candidates)
                rect = (candidate if not any(candidate.colliderect(other)
                                             for other in blocked) else None)
            else:
                rect = next((candidate for candidate in candidates
                             if not any(candidate.colliderect(other)
                                        for other in blocked)), None)
            if rect is None:
                if source.key in strict_above_keys:
                    continue
                rect = pygame.Rect(viewport.left, viewport.top, PIN_W, PIN_H)
                rect.clamp_ip(viewport)
            blocked.append(rect)
            result[source.key] = {
                "anchor": anchor,
                "rect": rect,
                "dial_center": (rect.left + 36, rect.bottom - 31),
            }
        return result

    def handle_mouse_down(self, pos, sources, anchors, obstacles, viewport,
                          strict_above_keys=()):
        layout = self.layout(sources, anchors, obstacles, viewport,
                             strict_above_keys)
        for source in sources:
            item = layout.get(source.key)
            if item is None:
                continue
            cx, cy = item["dial_center"]
            if math.hypot(pos[0] - cx, pos[1] - cy) <= TRACK_R + 10:
                self.dragging_key = source.key
                source.set_handle(_angle_to_pct(pos[0], pos[1], cx, cy))
                return True
        return False

    def handle_mouse_motion(self, pos, sources, anchors, obstacles, viewport,
                            strict_above_keys=()):
        if self.dragging_key is None:
            return
        layout = self.layout(sources, anchors, obstacles, viewport,
                             strict_above_keys)
        for source in sources:
            if source.key == self.dragging_key and source.key in layout:
                cx, cy = layout[source.key]["dial_center"]
                source.set_handle(_angle_to_pct(pos[0], pos[1], cx, cy))
                return

    def handle_mouse_up(self):
        self.dragging_key = None

    def draw(self, surface, sources, anchors, obstacles, viewport,
             demand_level=0.5, show_price=True, strict_above_keys=()):
        layout = self.layout(sources, anchors, obstacles, viewport,
                             strict_above_keys)
        for source in sources:
            item = layout.get(source.key)
            if item is None:
                continue
            anchor, rect = item["anchor"], item["rect"]
            pygame.draw.line(surface, (*source.color, 170), anchor, rect.center, 2)
        for source in sources:
            item = layout.get(source.key)
            if item is not None:
                self._draw_pin(surface, source, item, demand_level, show_price)
        return layout

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
