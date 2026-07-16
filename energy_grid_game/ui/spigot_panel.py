"""Row of spigot controls: one widget per energy source."""
import math
import pygame
from sources.base_source import SourceStatus

SLIDER_H = 60
SLIDER_W = 16
WIDGET_W = 200
WIDGET_GAP = 16

BG = (24, 30, 46)
PANEL = (28, 35, 54)
TEXT = (210, 216, 230)
DIM = (140, 148, 168)
PRICE_CHEAP = (110, 220, 160)
PRICE_MID = (240, 200, 90)
PRICE_EXPENSIVE = (240, 100, 90)

STATUS_COLORS = {
    SourceStatus.OFFLINE: (110, 116, 130),
    SourceStatus.RAMPING: (240, 200, 80),
    SourceStatus.ONLINE: (100, 220, 140),
    SourceStatus.COOLDOWN: (240, 150, 60),
    SourceStatus.DEPLETED: (230, 80, 80),
    SourceStatus.SCRAM: (230, 40, 40),
    SourceStatus.MAINTENANCE: (200, 100, 220),
}


class SpigotPanel:
    def __init__(self, rect: pygame.Rect, font, font_small, font_bold):
        self.rect = rect
        self.font = font
        self.font_small = font_small
        self.font_bold = font_bold
        self.dragging_key = None
        self._slider_rects = {}

    def _layout(self, n):
        # shrink card width when the window is too narrow for six full-size
        # cards, down to a floor that still fits the bars/slider cluster
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

    def handle_mouse_down(self, pos, sources):
        boxes = self._layout(len(sources))
        for src, box in zip(sources, boxes):
            sr = self._slider_rects.get(src.key)
            if sr and sr.inflate(20, 10).collidepoint(pos):
                self.dragging_key = src.key
                self._apply_drag(pos, src, sr)
                return True
        return False

    def handle_mouse_up(self):
        self.dragging_key = None

    def handle_mouse_motion(self, pos, sources):
        if not self.dragging_key:
            return
        for src in sources:
            if src.key == self.dragging_key:
                sr = self._slider_rects.get(src.key)
                if sr:
                    self._apply_drag(pos, src, sr)
                return

    def _apply_drag(self, pos, src, slider_rect):
        rel = (slider_rect.bottom - pos[1]) / slider_rect.height
        src.set_handle(max(0.0, min(1.0, rel)))

    def draw(self, surface, sources, demand_level=0.5):
        pygame.draw.rect(surface, BG, self.rect)
        boxes = self._layout(len(sources))
        self._slider_rects = {}
        for src, box in zip(sources, boxes):
            self._draw_widget(surface, src, box, demand_level)

    def _draw_widget(self, surface, src, box, demand_level):
        card = box.inflate(-10, -10)
        pygame.draw.rect(surface, PANEL, card, border_radius=8)
        pygame.draw.rect(surface, tuple(min(255, c + 30) for c in src.color), card, width=2, border_radius=8)

        cx = card.centerx
        y = card.top + 6

        icon_r = 9
        pygame.draw.circle(surface, src.color, (cx, y + icon_r), icon_r)
        y += icon_r * 2 + 4

        name_txt = self.font_bold.render(src.name, True, TEXT)
        surface.blit(name_txt, (cx - name_txt.get_width() // 2, y))
        y += name_txt.get_height()

        status_color = STATUS_COLORS.get(src.status, DIM)
        status_txt = self.font_small.render(src.status.value, True, status_color)
        surface.blit(status_txt, (cx - status_txt.get_width() // 2, y))
        y += status_txt.get_height() + 2

        # latency countdown badge (reserve the row even when idle, for stable layout)
        ttt = src.time_to_target()
        if ttt > 0.05:
            badge = self.font_small.render(f"⏱ {ttt:0.0f}s", True, (255, 230, 150))
            surface.blit(badge, (cx - badge.get_width() // 2, y))
        y += self.font_small.get_height() + 2

        # bars + slider row
        bars_top = y
        req_x = card.left + 16
        act_x = req_x + 20
        slider_x = act_x + 30

        pygame.draw.rect(surface, (15, 18, 28), (req_x, bars_top, 14, SLIDER_H))
        req_h = int(SLIDER_H * src.requested_pct)
        pygame.draw.rect(surface, (90, 100, 120), (req_x, bars_top + SLIDER_H - req_h, 14, req_h))

        pygame.draw.rect(surface, (15, 18, 28), (act_x, bars_top, 14, SLIDER_H))
        act_h = int(SLIDER_H * src.actual_pct)
        pygame.draw.rect(surface, src.color, (act_x, bars_top + SLIDER_H - act_h, 14, act_h))

        slider_rect = pygame.Rect(slider_x, bars_top, SLIDER_W, SLIDER_H)
        self._slider_rects[src.key] = slider_rect
        pygame.draw.rect(surface, (12, 15, 24), slider_rect, border_radius=4)
        pygame.draw.rect(surface, (70, 78, 96), slider_rect, width=1, border_radius=4)
        handle_y = slider_rect.bottom - int(slider_rect.height * src.requested_pct)
        handle_rect = pygame.Rect(slider_rect.left - 4, handle_y - 5, SLIDER_W + 8, 10)
        pygame.draw.rect(surface, (235, 235, 245), handle_rect, border_radius=3)

        pct_txt = self.font_small.render(f"{src.requested_pct * 100:0.0f}%", True, DIM)
        surface.blit(pct_txt, (slider_x + SLIDER_W // 2 - pct_txt.get_width() // 2, bars_top + SLIDER_H + 2))

        y = bars_top + SLIDER_H + self.font_small.get_height() + 6

        mw_txt = self.font_small.render(f"{src.current_output_mw:0.0f} / {src.max_output_mw:0.0f} MW", True, TEXT)
        surface.blit(mw_txt, (cx - mw_txt.get_width() // 2, y))
        y += mw_txt.get_height() + 1

        price = src.price_at(demand_level)
        price_color = PRICE_CHEAP if price < 40 else (PRICE_MID if price < 80 else PRICE_EXPENSIVE)
        price_txt = self.font_small.render(f"${price:0.0f}/MWh", True, price_color)
        surface.blit(price_txt, (cx - price_txt.get_width() // 2, y))
