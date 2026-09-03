"""Clock, score, supply/demand readout, reservoir badge, and warning overlays."""
import math
import pygame

from game_state import SEVERE_LOW_THRESHOLD, SEVERE_HIGH_THRESHOLD, MAX_FILL_PCT
from ui import assets, portraits
from ui.gradient_border import AMBER, RED, GradientBorder

# event kind -> hud_icons/<name>_icon.png shown on the alert banner
EVENT_ICON = {
    "HEAT_WAVE": "warning", "ICE_STORM": "warning", "MAINTENANCE": "maintenance",
    "CLOUD_COVER": "notification", "WIND_GUST": "notification",
    "RAIN": "notification", "SNOW": "notification",
}

TEXT = (225, 230, 240)
DIM = (150, 158, 176)
SUPPLY_COLOR = (110, 220, 160)
DEMAND_COLOR = (255, 170, 90)
OK = (100, 220, 140)
WARN = (240, 170, 80)
BAD = (230, 90, 90)

PANEL_TOP = 14
HUD_W = 900
LEFT_W = 300
CENTER_W = 400
RIGHT_W = 200
PANEL_H = 150
PANEL_BG = (10, 14, 22, 205)
PANEL_EDGE = (156, 174, 196, 92)


def hud_panel_rects(width, height):
    """One centered HUD chassis, divided into adaptive instrument zones."""
    outer_w = min(max(HUD_W, int(width * 0.82)), width - 40)
    left_w = min(320, max(280, int(outer_w * 0.28)))
    right_w = min(340, max(300, int(outer_w * 0.30)))
    center_w = outer_w - left_w - right_w
    outer = pygame.Rect((width - outer_w) // 2, PANEL_TOP, outer_w, PANEL_H)
    left = pygame.Rect(outer.left, outer.top, left_w, PANEL_H)
    center = pygame.Rect(left.right, outer.top, center_w, PANEL_H)
    right = pygame.Rect(center.right, outer.top, right_w, PANEL_H)
    return {"outer": outer, "left": left, "center": center, "right": right}


def hud_hit_test(layout, pos):
    return layout["outer"].collidepoint(pos)

# Concise, honest cause-of-death text for each failure the sim can actually
# produce, keyed by GameState.game_over_reason.
FAILURE_EXPLANATIONS = {
    "TOTAL BLACKOUT": "Supply fell under 40% of demand. The city went dark.",
    "GRID MELTDOWN": "You ran supply to double demand. The grid cooked itself.",
    "NUCLEAR MELTDOWN": "The reactor was cut below its minimum stable output.",
}


def _homes_out_status(homes_out: float, homes_total: float):
    if homes_out <= 500:
        return "0", OK
    if homes_total > 0 and homes_out > homes_total * 0.5:
        return f"{homes_out:,.0f}", BAD
    return f"{homes_out:,.0f}", WARN


def _money_status(price: float):
    return _price_color(price)


def _balance_color(ratio: float):
    if ratio < 0.80:
        return (230, 80, 80)      # undersupplied — blackout risk
    if ratio <= 1.08:
        return (100, 220, 140)    # balanced
    return (240, 200, 70)         # oversupplied — tank will fill/overflow


def _format_money(dollars: float) -> str:
    if dollars >= 1_000_000:
        return f"${dollars / 1_000_000:,.2f}M"
    if dollars >= 1_000:
        return f"${dollars / 1_000:,.1f}K"
    return f"${dollars:,.0f}"


def _fit_text(font, text, max_width):
    if font.size(text)[0] <= max_width:
        return text
    ellipsis = "..."
    while text and font.size(text + ellipsis)[0] > max_width:
        text = text[:-1]
    return text + ellipsis if text else ellipsis


def _bevel_notch_rect(surface, rect, fill, edge, accent=None, alpha=210):
    pts = [
        (rect.left + 8, rect.top), (rect.right - 1, rect.top),
        (rect.right - 1, rect.bottom - 9), (rect.right - 9, rect.bottom - 1),
        (rect.left, rect.bottom - 1), (rect.left, rect.top + 8),
    ]
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    local_pts = [(x - rect.left, y - rect.top) for x, y in pts]
    pygame.draw.polygon(panel, (*fill, alpha), local_pts)
    pygame.draw.lines(panel, (*edge, min(255, alpha + 25)), True, local_pts, 2)
    pygame.draw.line(panel, (235, 210, 150, 120), local_pts[0], local_pts[1])
    pygame.draw.line(panel, (10, 12, 8, 160), local_pts[3], local_pts[4])
    if accent is not None:
        pygame.draw.line(panel, (*accent, 145), (10, 7), (34, 7), 1)
    surface.blit(panel, rect.topleft)


def _price_color(price: float):
    if price < 40:
        return (110, 220, 160)
    if price < 80:
        return (240, 200, 90)
    return (240, 100, 90)


def _balance_label(ratio: float) -> str:
    if ratio < 0.60:
        return "SEVERE SHORTFALL"
    if ratio < 0.80:
        return "UNDERSUPPLIED"
    if ratio <= 1.08:
        return "BALANCED"
    if ratio <= 1.3:
        return "OVERSUPPLIED"
    return "MASSIVE OVERSUPPLY"


class HUD:
    def __init__(self, font, font_small, font_big, font_mono_big):
        self.font = font
        self.font_small = font_small
        self.font_big = font_big
        self.font_mono_big = font_mono_big
        self._t = 0.0
        self._prev_fill = None
        self._ratio_display = 1.0
        self._border = GradientBorder()
        self._panel_cache = {}
        self.audio_rect = None    # click target for the sound toggle, set in draw
        # Not every matched monospace font ships the degree glyph; drop it
        # rather than rendering a missing-glyph box next to the temperature.
        try:
            m = self.font_small.metrics("°")
            self._degree_ok = bool(m and m[0])
        except Exception:
            self._degree_ok = False

    def _top_scrim(self, width):
        """A light pixel haze so instruments read without hiding the world."""
        scrim = self._panel_cache.get(("scrim", width))
        if scrim is None:
            h = 172
            scrim = pygame.Surface((width, h), pygame.SRCALPHA)
            for yy in range(h):
                a = int(92 * (1.0 - yy / h) ** 1.55)
                pygame.draw.line(scrim, (30, 28, 20, a), (0, yy), (width, yy))
            self._panel_cache[("scrim", width)] = scrim
        return scrim

    def _draw_chassis(self, surface, outer, left, center, right):
        rail = pygame.Rect(outer.left - 8, outer.top - 4, outer.width + 16, outer.height - 2)
        _bevel_notch_rect(surface, rail, (28, 38, 35), (70, 92, 82), None, alpha=108)
        for x in (left.right - 4, center.right - 4):
            pygame.draw.line(surface, (86, 116, 98, 105), (x, outer.top + 7), (x, outer.bottom - 18))
            pygame.draw.line(surface, (10, 12, 8, 145), (x + 2, outer.top + 9), (x + 2, outer.bottom - 16))

    def _draw_metric_plate(self, surface, rect, label, value, color, icon=None, sub=None):
        _bevel_notch_rect(surface, rect, (30, 43, 39), (72, 102, 88), color, alpha=184)

        x = rect.left + 12
        if icon is not None:
            surface.blit(icon, (x, rect.top + 10))
            x += icon.get_width() + 6

        max_w = rect.right - x - 10
        label_txt = self.font_small.render(_fit_text(self.font_small, label, max_w), True, (206, 210, 184))
        value_font = self.font_big if self.font_big.size(value)[0] <= max_w else self.font
        value_txt = value_font.render(_fit_text(value_font, value, max_w), True, color)
        surface.blit(label_txt, (x, rect.top + 7))
        surface.blit(value_txt, (x, rect.top + 7 + label_txt.get_height()))
        if sub:
            sub_txt = self.font_small.render(_fit_text(self.font_small, sub, max_w), True, (186, 194, 176))
            surface.blit(sub_txt, (x, rect.bottom - sub_txt.get_height() - 5))

    def draw(self, surface, state, panels=None):
        self._t += 1 / 60.0
        w, h = surface.get_size()
        panels = panels if isinstance(panels, dict) else hud_panel_rects(w, h)
        outer = panels["outer"]
        left, center, right = (panels[name] for name in ("left", "center", "right"))
        surface.blit(self._top_scrim(w), (0, 0))
        self._draw_chassis(surface, outer, left, center, right)

        clock_txt = self.font_big.render(state.clock_string(), True, TEXT)
        clock_pos = (left.left + 10, left.top + 9)
        surface.blit(clock_txt, clock_pos)

        # date + season stacked just right of the clock (left column stays free
        # for the event banner). The date advances one day per in-game day.
        date_txt = self.font_small.render(state.date_string(), True, TEXT)
        season_txt = self.font_small.render(state.season_string().upper(), True, DIM)
        dx = clock_pos[0] + clock_txt.get_width() + 12
        dy = left.top + 10
        surface.blit(date_txt, (dx, dy))
        surface.blit(season_txt, (dx, dy + date_txt.get_height() + 1))

        # ambient temperature beside the season: blue in a freeze, red in a
        # scorcher, so severe-weather events read at a glance
        temp_color = ((120, 190, 255) if state.temp_f < 32.0
                      else (240, 110, 90) if state.temp_f > 90.0 else DIM)
        deg = "°F" if self._degree_ok else "F"
        temp_txt = self.font_small.render(f"{state.temp_f:0.0f}{deg}", True, temp_color)
        surface.blit(temp_txt, (dx + season_txt.get_width() + 10,
                                dy + date_txt.get_height() + 1))

        # Region/scenario run that fell back to synthetic curves: keep the
        # status visible after the launch flash message has faded.
        # Instructional Mode is synthetic by design, not by fallback — warning
        # about it would report a failure that never happened.
        if (state.config.mode not in ("standard", "instructional")
                and state.config.data_source == "synthetic"):
            synth_txt = self.font_small.render("SYNTHETIC DATA", True, (240, 200, 90))
            surface.blit(synth_txt, (dx, dy + date_txt.get_height()
                                     + season_txt.get_height() + 2))

        plate_w = right.width - 14
        plate_x = right.left + 7
        homes_value, homes_color = _homes_out_status(
            state.homes_without_power, state.homes_total)
        self._draw_metric_plate(
            surface, pygame.Rect(plate_x, right.top + 7, plate_w, 46),
            "HOMES WITHOUT POWER", homes_value, homes_color,
            assets.resource_icon("population", 14))

        # Instructional Day 1 teaches balance alone -- no price, no spend.
        if state.show_economics:
            money_sub = f"${state.grid_price:0.0f}/MWh  {_format_money(state.cost_per_hour)}/hr"
            self._draw_metric_plate(
                surface, pygame.Rect(plate_x, right.top + 58, plate_w, 54),
                "TOTAL SPENT", _format_money(state.total_cost), (240, 200, 90),
                assets.resource_icon("money", 14), money_sub)
            score_y, score_h = right.top + 114, 38
        else:
            score_y, score_h = right.top + 60, 46

        self._draw_metric_plate(
            surface, pygame.Rect(plate_x, score_y, plate_w, score_h),
            "SCORE", f"{int(state.score):,}", TEXT)

        # --- supply/demand fulfillment: the big top-center number now answers
        # "am I meeting demand right now", not the tank's slow-accumulating
        # reservoir level (that's a different question, shown as a small badge
        # below) ---
        supply_mw = state.effective_supply_mw
        demand_mw = state.demand_mw
        raw_ratio = supply_mw / demand_mw if demand_mw > 0 else 1.0
        self._ratio_display += (raw_ratio - self._ratio_display) * min(1.0, 6.0 * (1 / 60.0))
        ratio_color = _balance_color(self._ratio_display)
        balance_rect = pygame.Rect(center.left + 14, center.top + 5,
                                   center.width - 28, 112)
        _bevel_notch_rect(surface, balance_rect, (28, 41, 37),
                          (70, 104, 88), ratio_color, alpha=142)

        trend = "▼" if raw_ratio < (self._prev_fill or raw_ratio) else "▲"
        self._prev_fill = raw_ratio
        ratio_str = f"{min(self._ratio_display, 9.99) * 100:0.0f}% {trend}"
        ratio_txt = self.font_mono_big.render(ratio_str, True, ratio_color)
        center_x = center.centerx
        ratio_y = center.top + 7
        surface.blit(ratio_txt, (center_x - ratio_txt.get_width() // 2, ratio_y))

        balance_txt = self.font.render(_balance_label(self._ratio_display), True, ratio_color)
        surface.blit(balance_txt, (center_x - balance_txt.get_width() // 2,
                                   ratio_y + ratio_txt.get_height()))

        y = ratio_y + ratio_txt.get_height() + balance_txt.get_height() + 7

        # prominent SUPPLY / DEMAND MW readout, side by side
        supply_lbl = self.font_small.render("SUPPLY NOW", True, DIM)
        demand_lbl = self.font_small.render("DEMAND TARGET", True, DIM)
        value_font = self.font_big
        supply_text = f"{supply_mw:,.0f} MW"
        demand_text = f"{demand_mw:,.0f} MW"
        sep_text = "/"

        gap = 14
        supply_val = value_font.render(supply_text, True, SUPPLY_COLOR)
        demand_val = value_font.render(demand_text, True, DEMAND_COLOR)
        sep = value_font.render(sep_text, True, DIM)
        block_w = supply_val.get_width() + sep.get_width() + demand_val.get_width() + gap * 2
        if block_w > balance_rect.width - 20:
            value_font = self.font
            gap = 10
            supply_val = value_font.render(supply_text, True, SUPPLY_COLOR)
            demand_val = value_font.render(demand_text, True, DEMAND_COLOR)
            sep = value_font.render(sep_text, True, DIM)
            block_w = supply_val.get_width() + sep.get_width() + demand_val.get_width() + gap * 2
        if block_w > balance_rect.width - 20:
            max_each = max(40, (balance_rect.width - sep.get_width() - gap * 2 - 20) // 2)
            supply_text = _fit_text(value_font, supply_text, max_each)
            demand_text = _fit_text(value_font, demand_text, max_each)
            supply_val = value_font.render(supply_text, True, SUPPLY_COLOR)
            demand_val = value_font.render(demand_text, True, DEMAND_COLOR)
            block_w = supply_val.get_width() + sep.get_width() + demand_val.get_width() + gap * 2
        bx = center_x - block_w // 2
        energy_icon = assets.resource_icon("energy", 14)
        supply_lbl_x = bx + supply_val.get_width() // 2 - supply_lbl.get_width() // 2
        surface.blit(energy_icon, (supply_lbl_x - energy_icon.get_width() - 3,
                                   y + (supply_lbl.get_height() - 14) // 2))
        surface.blit(supply_lbl, (supply_lbl_x, y))
        surface.blit(supply_val, (bx, y + supply_lbl.get_height() + 1))
        sep_x = bx + supply_val.get_width() + gap
        surface.blit(sep, (sep_x, y + supply_lbl.get_height() + 1))
        demand_x = sep_x + sep.get_width() + gap
        demand_lbl_x = demand_x + demand_val.get_width() // 2 - demand_lbl.get_width() // 2
        surface.blit(demand_lbl, (demand_lbl_x, y))
        surface.blit(demand_val, (demand_x, y + supply_lbl.get_height() + 1))

        y += supply_lbl.get_height() + supply_val.get_height() + 6

        # Live price and hourly burn are shown in the right-side spending module.
        if state.show_economics:
            if state.congestion_overload_mw > 1.0:
                warn = self.font_small.render(
                    f"CONGESTION  -{state.congestion_loss_mw:,.0f} MW", True, (255, 140, 90))
                surface.blit(warn, (center_x - warn.get_width() // 2, y))
                y += warn.get_height() + 4

        # The reservoir badge used to sit here. It was redundant with the big
        # ratio readout above (both answer "am I meeting demand"), and the tank
        # itself already shows the same thing in water — the mechanic and its
        # graphic are untouched, only this duplicate metric is gone.
        # "Homes without power" also used to sit here; it is a fact about the
        # city, so it is now drawn above the city graphic (see ui/iso_city).
        # `y` is a running cursor, so both removals close up automatically and
        # everything below simply moves up.

        # active grid event banner (pixel-art banner + kind icon + countdown)
        event_banner_bottom = None
        if state.active_event:
            ev = state.active_event
            bh = 32
            max_bw = max(160, right.left - left.left - 12)
            max_text_w = max_bw - 28
            event_text = _fit_text(self.font, f"{ev.name}  ({ev.remaining:0.0f}s)", max_text_w)
            text = self.font.render(event_text, True, (255, 236, 224))
            content = text.get_width() + 28
            bw = (content + 7) // 8 * 8    # quantize width so the countdown reuses the cache
            bw = min(max_bw, bw)
            br = pygame.Rect(left.left, left.bottom + 7, bw, bh)
            pts = [
                (br.left + 8, br.top), (br.right - 1, br.top),
                (br.right - 1, br.bottom - 8), (br.right - 8, br.bottom - 1),
                (br.left, br.bottom - 1), (br.left, br.top + 8),
            ]
            alert_alpha = int(190 + 45 * abs(math.sin(self._t * 3)))
            banner = pygame.Surface(br.size, pygame.SRCALPHA)
            local = [(x - br.left, y - br.top) for x, y in pts]
            pygame.draw.polygon(banner, (154, 60, 46, alert_alpha), local)
            pygame.draw.lines(banner, (224, 112, 86, 230), True, local, 2)
            pygame.draw.line(banner, (250, 188, 122, 170), local[0], local[1])
            marker = self.font.render("!", True, (255, 236, 180))
            banner.blit(marker, (10, (bh - marker.get_height()) // 2))
            banner.blit(text, (24, (bh - text.get_height()) // 2))
            surface.blit(banner, br.topleft)
            event_banner_bottom = br.bottom

        message_y = max(center.bottom + 7,
                        event_banner_bottom + 5 if event_banner_bottom else center.bottom + 7)
        flash_y = message_y
        for text, ttl in state.flash_messages:
            alpha = min(255, int(ttl * 150))
            flash_surf = self.font_big.render(text, True, (255, 90, 90))
            fs = pygame.Surface(flash_surf.get_size(), pygame.SRCALPHA)
            fs.blit(flash_surf, (0, 0))
            fs.set_alpha(alpha)
            surface.blit(fs, (center_x - flash_surf.get_width() // 2, flash_y))
            flash_y += flash_surf.get_height() + 4

        if state.paused:
            pause_txt = self.font_big.render("PAUSED", True, (255, 255, 255))
            surface.blit(pause_txt, (w // 2 - pause_txt.get_width() // 2, h // 2 - 100))

        # Severity escalates continuously past either extreme, not just a flat
        # on/off warning — a 20% blackout and a 200% meltdown should both look
        # unmistakably catastrophic, and more so the further they go.
        fill_pct = state.fill_pct_display
        if fill_pct < SEVERE_LOW_THRESHOLD:
            severity = (SEVERE_LOW_THRESHOLD - max(0.0, fill_pct)) / SEVERE_LOW_THRESHOLD
            self._draw_vignette(surface, RED, severity)
            label = "CATASTROPHIC BLACKOUT" if severity > 0.7 else "BLACKOUT RISK"
            self._draw_warning(surface, label, (255, 120, 120), message_y, severity,
                               center_x)
        elif fill_pct > SEVERE_HIGH_THRESHOLD:
            span = MAX_FILL_PCT - SEVERE_HIGH_THRESHOLD
            severity = min(1.0, (fill_pct - SEVERE_HIGH_THRESHOLD) / max(0.01, span))
            self._draw_vignette(surface, AMBER, severity)
            label = "GRID MELTDOWN IMMINENT" if severity > 0.6 else "CRITICAL OVERLOAD"
            self._draw_warning(surface, label, (255, 190, 110), message_y, severity,
                               center_x)
        elif state.blackout:
            self._draw_vignette(surface, RED, 0.3)
            self._draw_warning(surface, "BLACKOUT RISK", (255, 120, 120), message_y,
                               0.3, center_x)

        if state.celebrate_high_score > 0:
            self._draw_success_toast(surface)

    def draw_audio_indicator(self, surface, audio, pos):
        """Clickable sound toggle (pixel button) + '(M)' hotkey hint. When no
        audio device is present it degrades to the old dim text."""
        self.audio_rect = None
        if not audio.available:
            txt = self.font_small.render("NO AUDIO DEVICE", True, (110, 116, 130))
            surface.blit(txt, pos)
            return
        btn = assets.scaled_to_height(
            f"buttons/sound_{'off' if audio.muted else 'on'}_button_idle.png", 32)
        surface.blit(btn, pos)
        self.audio_rect = pygame.Rect(pos, btn.get_size())
        hint = self.font_small.render("(M)", True, DIM)
        surface.blit(hint, (pos[0] + btn.get_width() + 6,
                            pos[1] + (btn.get_height() - hint.get_height()) // 2))

    def _draw_success_toast(self, surface):
        """Thumbs-up beside the game's existing new-personal-best event. The
        numeric BEST readout above is untouched; this only adds a reaction."""
        _, h = surface.get_size()
        portrait = portraits.scaled_to_height(portraits.HAPPY, 150)
        p_rect = portrait.get_rect()
        p_rect.left = 24
        p_rect.bottom = h - 210
        surface.blit(portrait, p_rect.topleft)

        txt = self.font.render("NEW PERSONAL BEST", True, (255, 236, 170))
        plate = pygame.Rect(0, 0, txt.get_width() + 20, txt.get_height() + 12)
        plate.midleft = (p_rect.right + 4, p_rect.centery)
        plate_surf = pygame.Surface(plate.size, pygame.SRCALPHA)
        pygame.draw.rect(plate_surf, (34, 30, 12, 220), plate_surf.get_rect(), border_radius=6)
        pygame.draw.rect(plate_surf, (255, 215, 90, 220), plate_surf.get_rect(), width=1, border_radius=6)
        plate_surf.blit(txt, (10, 6))
        surface.blit(plate_surf, plate.topleft)

    def _draw_warning(self, surface, text, color, y, severity, center_x=None):
        # Warning icon + text, breathing together. Slow, smooth brightness —
        # no positional jitter, capped well under 1 Hz — since large warning
        # text is exactly the kind of element that shouldn't be strobing.
        w, _ = surface.get_size()
        warn = self.font_big.render(text, True, color)
        icon = assets.hud_icon("warning", 32)
        gap = 10
        total_w = icon.get_width() + gap + warn.get_width()
        row_h = max(icon.get_height(), warn.get_height())
        ws = pygame.Surface((total_w, row_h), pygame.SRCALPHA)
        ws.blit(icon, (0, (row_h - icon.get_height()) // 2))
        ws.blit(warn, (icon.get_width() + gap, (row_h - warn.get_height()) // 2))
        ws.set_alpha(int(170 + 85 * abs(math.sin(self._t * (1.2 + 0.8 * severity)))))
        surface.blit(ws, ((center_x if center_x is not None else w // 2)
                          - total_w // 2, y))

    def draw_game_over(self, surface, state):
        w, h = surface.get_size()
        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((8, 9, 14, 200))
        surface.blit(dim, (0, 0))

        reason_labels = {
            "TOTAL BLACKOUT": "TOTAL BLACKOUT",
            "GRID MELTDOWN": "GRID MELTDOWN",
            "NUCLEAR MELTDOWN": "NUCLEAR MELTDOWN",
        }
        panel = pygame.Rect(0, 0, min(680, w - 160), 286)
        panel.center = (min(w - panel.width // 2 - 36, w // 2 + 92), h // 2)
        shadow = pygame.Surface(panel.size, pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 125))
        surface.blit(shadow, panel.move(8, 8).topleft)
        _bevel_notch_rect(surface, panel, (34, 34, 28), (146, 118, 78), (255, 110, 100), alpha=245)
        alert = pygame.Rect(panel.left + 8, panel.top + 8, panel.width - 16, 36)
        _bevel_notch_rect(surface, alert, (94, 24, 26), (210, 72, 60),
                          (255, 218, 110), alpha=238)
        for x in range(alert.left + 14, alert.right - 20, 28):
            pygame.draw.rect(surface, (255, 218, 110), (x, alert.top + 8, 10, 4))
        # Gattie reacts to the failure. Bottom-anchored to the left of the
        # centered text block, clamped so a narrow window can't push him off.
        portrait = portraits.scaled_to_height(portraits.ANGRY, min(300, max(150, h // 3)))
        p_rect = portrait.get_rect()
        p_rect.right = max(portrait.get_width() + 16, panel.left - 26)
        p_rect.centery = panel.centery + 8
        surface.blit(portrait, p_rect.topleft)

        title = reason_labels.get(state.game_over_reason, "GRID FAILURE")
        title_txt = self.font_mono_big.render(title, True, (255, 110, 100))
        # failure icon left of the title (nuclear gets the reactor icon)
        if state.game_over_reason == "NUCLEAR MELTDOWN":
            icon = assets.resource_icon("nuclear", 48)
        else:
            icon = assets.hud_icon("warning", 48)
        block_w = icon.get_width() + 12 + title_txt.get_width()
        bx = panel.centerx - block_w // 2
        title_y = panel.top + 58
        surface.blit(icon, (bx, title_y + (title_txt.get_height() - icon.get_height()) // 2))
        surface.blit(title_txt, (bx + icon.get_width() + 12, title_y))

        explanation = FAILURE_EXPLANATIONS.get(state.game_over_reason, "The grid did not survive.")
        sub = self.font.render(explanation, True, DIM)
        surface.blit(sub, (panel.centerx - sub.get_width() // 2,
                           title_y + title_txt.get_height() + 8))

        score_plate = pygame.Rect(panel.centerx - 180, panel.top + 150, 360, 62)
        _bevel_notch_rect(surface, score_plate, (46, 48, 34), (132, 112, 74),
                          (255, 218, 110), alpha=226)
        score_txt = self.font_big.render(f"FINAL SCORE  {int(state.score):,}", True, TEXT)
        surface.blit(score_txt, (score_plate.centerx - score_txt.get_width() // 2,
                                 score_plate.top + 8))

        best_color = (255, 215, 90) if state.new_high_score else DIM
        best_txt = self.font.render(f"BEST {int(state.high_score):,}", True, best_color)
        surface.blit(best_txt, (score_plate.centerx - best_txt.get_width() // 2,
                                score_plate.top + 15 + score_txt.get_height()))

        hint = self.font.render("Press R to retry  ·  ESC for menu", True, DIM)
        hint_plate = pygame.Rect(0, 0, hint.get_width() + 34, hint.get_height() + 16)
        hint_plate.center = (panel.centerx, panel.bottom - 34)
        _bevel_notch_rect(surface, hint_plate, (42, 46, 34), (118, 102, 70),
                          (110, 220, 160), alpha=216)
        surface.blit(hint, (hint_plate.centerx - hint.get_width() // 2,
                            hint_plate.centery - hint.get_height() // 2))

    def _draw_vignette(self, surface, palette, severity=0.3):
        """Warning band around the play area. Previously four flat solid-color
        rects rebuilt every frame; now a pre-rendered gradient (dark exterior ->
        brighter interior) that only re-renders when the window size or the
        quantized thickness changes. Position, thickness and pulse timing are
        unchanged."""
        thickness = int(28 + 42 * severity)
        pulse_speed = 1.0 + 1.0 * severity  # capped well under 1 Hz
        pulse = int((30 + 60 * severity) * abs(math.sin(self._t * pulse_speed)))
        base_alpha = int(50 + 130 * severity)
        self._border.draw(surface, thickness, min(255, base_alpha + pulse), palette)
