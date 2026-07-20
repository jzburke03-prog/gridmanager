"""Small corner widget: stacked generation-mix chart (styled after a utility
"duck curve" dispatch diagram) with the actual day-so-far output per source
filled in layers. The demand line itself is real recorded demand (including
any event spikes) for hours already lived, and only falls back to the
theoretical baseline curve as a preview for hours not yet reached.
"""
import math
import pygame
from demand_curve import demand_curve_samples

BG = (16, 20, 32)
BORDER = (55, 64, 86)
DEMAND_LINE = (225, 230, 240)
DOT_COLOR = (255, 255, 255)
LABEL_HOURS = [0, 6, 12, 18, 24]

# bottom -> top stacking order: firm baseload first, variable/peaking last,
# echoing the classic utility dispatch-stack chart
STACK_ORDER = ["nuclear", "coal", "gas", "peaker", "hydro", "wind", "solar"]


class DemandChart:
    def __init__(self, rect: pygame.Rect, font: pygame.font.Font):
        self.rect = rect
        self.font = font
        self.demand_hours, self.demand_levels = demand_curve_samples(288)
        self._t = 0.0

    def _plot_max_mw(self, peak_mw: float) -> float:
        return peak_mw * 1.15  # headroom so the peak doesn't touch the top edge

    def _x(self, hour):
        pad = 6
        return self.rect.left + pad + (hour / 24.0) * (self.rect.width - 2 * pad)

    def _y(self, mw, max_mw, top_pad, bottom_pad):
        usable = self.rect.height - top_pad - bottom_pad
        return self.rect.bottom - bottom_pad - (mw / max_mw) * usable

    def draw(self, surface: pygame.Surface, current_hour: float, sources, history,
             demand_mw_now, min_mw, peak_mw):
        self._t += 1 / 60.0
        top_pad, bottom_pad = 16, 18

        pygame.draw.rect(surface, BG, self.rect, border_radius=6)
        pygame.draw.rect(surface, BORDER, self.rect, width=1, border_radius=6)

        title = self.font.render("DEMAND CURVE", True, (150, 158, 176))
        surface.blit(title, (self.rect.left + 8, self.rect.top + 4))

        max_mw = self._plot_max_mw(peak_mw)
        colors = {s.key: s.color for s in sources}

        # Theoretical demand silhouette for hours NOT YET reached — a preview
        # of the day's expected shape, since we don't know future events.
        # Hours already lived are instead drawn from the real recorded demand
        # below (which includes any event spikes), so the two don't fight —
        # previously the whole line used this theoretical curve even for the
        # past, so a heat wave's demand spike would diverge sharply from this
        # static baseline and the chart looked broken.
        future_pts = [(self._x(h), self._y(min_mw + (peak_mw - min_mw) * v, max_mw, top_pad, bottom_pad))
                      for h, v in zip(self.demand_hours, self.demand_levels) if h >= current_hour]
        if len(future_pts) >= 2:
            pygame.draw.lines(surface, (70, 80, 105), False, future_pts, 1)

        # stacked actual output for the portion of the day already lived
        if len(history) >= 2:
            hours = [pt[0] for pt in history]
            baseline = [self._y(0, max_mw, top_pad, bottom_pad)] * len(history)
            cum = [0.0] * len(history)
            stack_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            for key in STACK_ORDER:
                top_line = []
                bottom_line = []
                for i, (hour, snapshot, _dmw) in enumerate(history):
                    mw = snapshot.get(key, 0.0)
                    bottom_line.append((self._x(hour), self._y(cum[i], max_mw, top_pad, bottom_pad)))
                    cum[i] += mw
                    top_line.append((self._x(hour), self._y(cum[i], max_mw, top_pad, bottom_pad)))
                poly = top_line + bottom_line[::-1]
                color = colors.get(key, (120, 120, 120))
                pygame.draw.polygon(stack_surf, (*color, 210), poly)
            surface.blit(stack_surf, (0, 0))
            # crisp cap line on top of the stack (the "actual total output so far")
            cap_line = [(self._x(h), self._y(c, max_mw, top_pad, bottom_pad)) for h, c in zip(hours, cum)]
            pygame.draw.lines(surface, (235, 240, 250), False, cap_line, 2)

        # bright demand line for hours already lived — the REAL recorded
        # demand (from history, which already includes any event multiplier
        # like a heat wave), not the theoretical baseline, so it tracks
        # exactly what the stacked output below had to actually meet
        if len(history) >= 2:
            actual_demand_pts = [(self._x(hour), self._y(dmw, max_mw, top_pad, bottom_pad))
                                  for hour, _snapshot, dmw in history]
            pygame.draw.lines(surface, DEMAND_LINE, False, actual_demand_pts, 2)

        dx = self._x(current_hour)
        dy = self._y(demand_mw_now, max_mw, top_pad, bottom_pad)
        pulse = 4 + 3 * abs(math.sin(self._t * 3))
        halo = pygame.Surface((36, 36), pygame.SRCALPHA)
        pygame.draw.circle(halo, (255, 255, 255, 70), (18, 18), 8 + pulse)
        surface.blit(halo, (dx - 18, dy - 18))
        pygame.draw.circle(surface, DOT_COLOR, (int(dx), int(dy)), 4)

        for h in LABEL_HOURS:
            x = self._x(h % 24)
            label = f"{h % 24:02d}" if h != 24 else "24"
            txt = self.font.render(label, True, (110, 118, 138))
            surface.blit(txt, (x - txt.get_width() / 2, self.rect.bottom - 15))
