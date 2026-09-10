"""Small corner widget: stacked generation-mix chart (styled after a utility
"duck curve" dispatch diagram) with the actual day-so-far output per source
filled in layers. The demand line itself is real recorded demand (including
any event spikes) for hours already lived, and only falls back to the
theoretical baseline curve as a preview for hours not yet reached.
"""
import math
import pygame
from demand_curve import demand_curve_samples
from game_state import DAY_START_HOUR
from ui.time_of_day import SkyGradient, get_time_of_day_colors

BG = (25, 34, 30)
BORDER = (94, 114, 96)
DEMAND_LINE = (235, 222, 154)
DOT_COLOR = (235, 244, 210)
# X-axis tick positions as offsets into the played day (which runs 04:00 ->
# 04:00, not midnight to midnight); rendered as clock hours.
LABEL_OFFSETS = [0, 6, 12, 18, 24]

# bottom -> top stacking order: firm baseload first, variable/peaking last,
# echoing the classic utility dispatch-stack chart
# "generic" is Instructional day 1's single valve. It has to be here or that
# day's chart never fills and the player gets no read on how they did.
STACK_ORDER = ["generic", "nuclear", "coal", "gas", "peaker", "hydro", "wind", "solar"]


class DemandChart:
    def __init__(self, rect: pygame.Rect, font: pygame.font.Font):
        self.rect = rect
        self.font = font
        self.demand_hours, self.demand_levels = demand_curve_samples(288)
        self._t = 0.0
        # Background tracks the time of day but is passed through an
        # industrial monitor tint so the chart feels like grid hardware, not a
        # generic translucent dashboard.
        self._sky = SkyGradient()
        self._bg_cache = None
        self._bg_key = None
        self._plot_rect = rect

    def _plot_max_mw(self, peak_mw: float) -> float:
        return peak_mw * 1.15  # headroom so the peak doesn't touch the top edge

    def _x(self, hour):
        pad = 6
        plot = getattr(self, "_plot_rect", self.rect)
        return plot.left + pad + (hour / 24.0) * (plot.width - 2 * pad)

    def _day_x(self, hour):
        """X position for a sim clock hour, in day-relative space: the played
        day runs 04:00 -> 04:00, so hour 4 is the left edge and the post-
        midnight stretch (0-4h) lands at the right — previously the axis was
        anchored at midnight, which left a blank 12am-4am band at the left of
        the chart every time a new day began."""
        return self._x((hour - DAY_START_HOUR) % 24.0)

    def _y(self, mw, max_mw, top_pad, bottom_pad):
        plot = getattr(self, "_plot_rect", self.rect)
        usable = plot.height - top_pad - bottom_pad
        return plot.bottom - bottom_pad - (mw / max_mw) * usable

    def _monitor_rects(self):
        outer = self.rect
        header = pygame.Rect(outer.left + 2, outer.top + 2, outer.width - 4, 22)
        screen = outer.inflate(-10, -34)
        screen.top = header.bottom + 5
        screen.height = outer.bottom - screen.top - 7
        return header, screen

    def _draw_dynamic_bg(self, surface, hour):
        """Pixel utility-monitor shell with a time-of-day screen inset."""
        top, bottom = get_time_of_day_colors(hour)
        d = 0.28
        warm_top = (34, 43, 32)
        warm_bottom = (48, 47, 34)
        top = tuple(int(c * d + warm_top[i] * (1.0 - d)) for i, c in enumerate(top))
        bottom = tuple(int(c * d + warm_bottom[i] * (1.0 - d)) for i, c in enumerate(bottom))
        header, screen = self._monitor_rects()
        self._plot_rect = screen

        shell = [
            (self.rect.left + 8, self.rect.top), (self.rect.right - 1, self.rect.top),
            (self.rect.right - 1, self.rect.bottom - 9),
            (self.rect.right - 9, self.rect.bottom - 1),
            (self.rect.left, self.rect.bottom - 1), (self.rect.left, self.rect.top + 8),
        ]
        pygame.draw.polygon(surface, (37, 44, 34), shell)
        pygame.draw.lines(surface, (104, 112, 84), True, shell, 2)
        pygame.draw.line(surface, (130, 138, 100),
                         (self.rect.left + 8, self.rect.top), (self.rect.right - 1, self.rect.top))
        pygame.draw.line(surface, (11, 16, 12),
                         (self.rect.left, self.rect.bottom - 1),
                         (self.rect.right - 9, self.rect.bottom - 1))
        pygame.draw.rect(surface, (45, 55, 42), header)
        pygame.draw.line(surface, (105, 194, 134),
                         (header.left, header.bottom), (header.right - 1, header.bottom))
        pygame.draw.line(surface, (96, 190, 124),
                         (self.rect.left + 10, self.rect.top + 8),
                         (self.rect.left + 34, self.rect.top + 8))

        w, h = screen.size
        key = (w, h, top, bottom)
        if key != self._bg_key:
            grad = self._sky.surface(w, h, top, bottom).convert_alpha()
            self._bg_cache = grad
            self._bg_key = key
        surface.blit(self._bg_cache, screen.topleft)
        pygame.draw.rect(surface, (102, 116, 88), screen, width=2)

        grid = pygame.Surface(screen.size, pygame.SRCALPHA)
        for off in LABEL_OFFSETS:
            x = round((off / 24.0) * screen.width)
            pygame.draw.line(grid, (166, 160, 110, 24), (x, 0), (x, screen.height))
        for frac in (0.33, 0.66):
            y = round(screen.height * frac)
            pygame.draw.line(grid, (120, 220, 150, 26), (0, y), (screen.width, y))
        surface.blit(grid, screen.topleft)

    def draw(self, surface: pygame.Surface, current_hour: float, sources, history,
             demand_mw_now, min_mw, peak_mw):
        self._t += 1 / 60.0
        top_pad, bottom_pad = 16, 24

        self._draw_dynamic_bg(surface, current_hour)

        title = self.font.render("DEMAND LOAD", True, (184, 238, 178))
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
        # "not yet reached" is judged in day-relative hours, and the remapped
        # sample order is no longer monotonic in x, so sort before drawing.
        cur_day_h = (current_hour - DAY_START_HOUR) % 24.0
        future_pts = sorted(
            (self._day_x(h), self._y(min_mw + (peak_mw - min_mw) * v, max_mw, top_pad, bottom_pad))
            for h, v in zip(self.demand_hours, self.demand_levels)
            if (h - DAY_START_HOUR) % 24.0 >= cur_day_h)
        if len(future_pts) >= 2:
            pygame.draw.lines(surface, (126, 112, 76), False, future_pts, 1)

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
                    bottom_line.append((self._day_x(hour), self._y(cum[i], max_mw, top_pad, bottom_pad)))
                    cum[i] += mw
                    top_line.append((self._day_x(hour), self._y(cum[i], max_mw, top_pad, bottom_pad)))
                poly = top_line + bottom_line[::-1]
                color = colors.get(key, (120, 120, 120))
                pygame.draw.polygon(stack_surf, (*color, 210), poly)
            surface.blit(stack_surf, (0, 0))
            # crisp cap line on top of the stack (the "actual total output so far")
            cap_line = [(self._day_x(h), self._y(c, max_mw, top_pad, bottom_pad)) for h, c in zip(hours, cum)]
            pygame.draw.lines(surface, (235, 240, 250), False, cap_line, 2)

        # bright demand line for hours already lived — the REAL recorded
        # demand (from history, which already includes any event multiplier
        # like a heat wave), not the theoretical baseline, so it tracks
        # exactly what the stacked output below had to actually meet
        if len(history) >= 2:
            actual_demand_pts = [(self._day_x(hour), self._y(dmw, max_mw, top_pad, bottom_pad))
                                  for hour, _snapshot, dmw in history]
            pygame.draw.lines(surface, DEMAND_LINE, False, actual_demand_pts, 2)

        dx = self._day_x(current_hour)
        dy = self._y(demand_mw_now, max_mw, top_pad, bottom_pad)
        pulse = 2 + 2 * abs(math.sin(self._t * 3))
        halo = pygame.Surface((28, 28), pygame.SRCALPHA)
        pygame.draw.circle(halo, (214, 226, 150, 58), (14, 14), 6 + pulse)
        surface.blit(halo, (dx - 14, dy - 14))
        pygame.draw.circle(surface, DOT_COLOR, (int(dx), int(dy)), 4)

        plot = getattr(self, "_plot_rect", self.rect)
        for off in LABEL_OFFSETS:
            x = self._x(off)
            label = f"{int(off + DAY_START_HOUR) % 24:02d}"
            txt = self.font.render(label, True, (150, 144, 112))
            x = max(plot.left + txt.get_width() / 2 + 3,
                    min(plot.right - txt.get_width() / 2 - 3, x))
            surface.blit(txt, (x - txt.get_width() / 2,
                               plot.bottom - txt.get_height() - 3))
