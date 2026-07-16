"""Clock, score, supply/demand readout, reservoir badge, and warning overlays."""
import math
import pygame

from game_state import SEVERE_LOW_THRESHOLD, SEVERE_HIGH_THRESHOLD, MAX_FILL_PCT
from ui import portraits
from ui.gradient_border import AMBER, RED, GradientBorder

TEXT = (225, 230, 240)
DIM = (150, 158, 176)
SUPPLY_COLOR = (110, 220, 160)
DEMAND_COLOR = (255, 170, 90)

# The time-of-day sky now runs genuinely bright at midday (see ui/time_of_day),
# and this readout is drawn straight onto it with no panel behind it. A scrim
# under the top HUD band keeps the light text legible against a noon sky without
# tinting any actual UI panel.
SCRIM_COLOR = (10, 13, 21)
SCRIM_PEAK_ALPHA = 165

# Concise, honest cause-of-death text for each failure the sim can actually
# produce, keyed by GameState.game_over_reason.
FAILURE_EXPLANATIONS = {
    "TOTAL BLACKOUT": "Supply fell under 40% of demand. The city went dark.",
    "GRID MELTDOWN": "You ran supply to double demand. The grid cooked itself.",
    "NUCLEAR MELTDOWN": "The reactor was cut below its minimum stable output.",
}


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
        self._scrim = None
        self._scrim_key = None

    def _top_scrim(self, width, band_h):
        """Cached legibility gradient behind the top HUD band. Built one pixel
        wide and stretched, so a resize costs one scale blit and a normal frame
        costs nothing."""
        key = (width, band_h)
        if key != self._scrim_key:
            column = pygame.Surface((1, band_h), pygame.SRCALPHA)
            for y in range(band_h):
                alpha = int(SCRIM_PEAK_ALPHA * (1.0 - y / band_h) ** 1.5)
                column.set_at((0, y), (*SCRIM_COLOR, alpha))
            self._scrim = pygame.transform.scale(column, (width, band_h))
            self._scrim_key = key
        return self._scrim

    def draw(self, surface, state, rim_color, fill_label, hud_band_height=220):
        self._t += 1 / 60.0
        w, h = surface.get_size()

        surface.blit(self._top_scrim(w, hud_band_height), (0, 0))

        clock_txt = self.font_big.render(state.clock_string(), True, TEXT)
        surface.blit(clock_txt, (24, 20))

        score_label = self.font_small.render("SCORE", True, DIM)
        score_txt = self.font_big.render(f"{int(state.score):,}", True, TEXT)
        surface.blit(score_label, (w - score_label.get_width() - 24, 18))
        surface.blit(score_txt, (w - score_txt.get_width() - 24, 18 + score_label.get_height() + 1))
        arrow = "▲" if state.score_delta_per_sec > 0 else ("▼" if state.score_delta_per_sec < 0 else "►")
        delta_color = (100, 220, 140) if state.score_delta_per_sec > 0 else (
            (230, 90, 90) if state.score_delta_per_sec < 0 else DIM)
        delta_txt = self.font_small.render(f"{state.score_delta_per_sec:+0.0f}/s {arrow}", True, delta_color)
        surface.blit(delta_txt, (w - delta_txt.get_width() - 24,
                                  18 + score_label.get_height() + score_txt.get_height() + 3))

        hs_color = (255, 215, 90) if state.new_high_score else DIM
        hs_txt = self.font_small.render(f"BEST {int(state.high_score):,}", True, hs_color)
        surface.blit(hs_txt, (w - hs_txt.get_width() - 24,
                               18 + score_label.get_height() + score_txt.get_height()
                               + delta_txt.get_height() + 6))

        spent_label = self.font_small.render("TOTAL SPENT", True, DIM)
        spent_txt = self.font.render(_format_money(state.total_cost), True, (240, 200, 90))
        spent_y = 18 + score_label.get_height() + score_txt.get_height() + delta_txt.get_height() + hs_txt.get_height() + 14
        surface.blit(spent_label, (w - spent_label.get_width() - 24, spent_y))
        surface.blit(spent_txt, (w - spent_txt.get_width() - 24, spent_y + spent_label.get_height() + 1))

        # --- supply/demand fulfillment: the big top-center number now answers
        # "am I meeting demand right now", not the tank's slow-accumulating
        # reservoir level (that's a different question, shown as a small badge
        # below) ---
        supply_mw = state.total_actual_mw
        demand_mw = state.demand_mw
        raw_ratio = supply_mw / demand_mw if demand_mw > 0 else 1.0
        self._ratio_display += (raw_ratio - self._ratio_display) * min(1.0, 6.0 * (1 / 60.0))
        ratio_color = _balance_color(self._ratio_display)

        trend = "▼" if raw_ratio < (self._prev_fill or raw_ratio) else "▲"
        self._prev_fill = raw_ratio
        ratio_str = f"{min(self._ratio_display, 9.99) * 100:0.0f}% {trend}"
        ratio_txt = self.font_mono_big.render(ratio_str, True, ratio_color)
        surface.blit(ratio_txt, (w // 2 - ratio_txt.get_width() // 2, 20))

        balance_txt = self.font.render(_balance_label(self._ratio_display), True, ratio_color)
        surface.blit(balance_txt, (w // 2 - balance_txt.get_width() // 2, 20 + ratio_txt.get_height()))

        y = 20 + ratio_txt.get_height() + balance_txt.get_height() + 8

        # prominent SUPPLY / DEMAND MW readout, side by side
        supply_lbl = self.font_small.render("SUPPLY", True, DIM)
        demand_lbl = self.font_small.render("DEMAND", True, DIM)
        supply_val = self.font_big.render(f"{supply_mw:,.0f} MW", True, SUPPLY_COLOR)
        demand_val = self.font_big.render(f"{demand_mw:,.0f} MW", True, DEMAND_COLOR)
        sep = self.font_big.render("/", True, DIM)

        gap = 14
        block_w = supply_val.get_width() + sep.get_width() + demand_val.get_width() + gap * 2
        bx = w // 2 - block_w // 2
        supply_lbl_x = bx + supply_val.get_width() // 2 - supply_lbl.get_width() // 2
        surface.blit(supply_lbl, (supply_lbl_x, y))
        surface.blit(supply_val, (bx, y + supply_lbl.get_height() + 1))
        sep_x = bx + supply_val.get_width() + gap
        surface.blit(sep, (sep_x, y + supply_lbl.get_height() + 1))
        demand_x = sep_x + sep.get_width() + gap
        demand_lbl_x = demand_x + demand_val.get_width() // 2 - demand_lbl.get_width() // 2
        surface.blit(demand_lbl, (demand_lbl_x, y))
        surface.blit(demand_val, (demand_x, y + supply_lbl.get_height() + 1))

        y += supply_lbl.get_height() + supply_val.get_height() + 2

        # live grid price: the marginal cost of the priciest source actually
        # dispatched right now — cheap when only baseload runs, expensive the
        # moment demand forces peaker gas online, same as a real merit-order
        # market clearing price
        price_txt = self.font_small.render(
            f"GRID PRICE ${state.grid_price:0.0f}/MWh  ·  {_format_money(state.cost_per_hour)}/hr",
            True, _price_color(state.grid_price))
        surface.blit(price_txt, (w // 2 - price_txt.get_width() // 2, y))
        y += price_txt.get_height() + 6

        # households without power — the human stakes of the shortfall, not
        # just an abstract MW gap
        homes_out = state.homes_without_power
        if homes_out > 500:
            homes_color = (230, 90, 90) if homes_out > state.homes_total * 0.5 else (240, 170, 80)
            homes_txt = self.font.render(f"🏠 {homes_out / 1_000_000:,.2f}M HOMES WITHOUT POWER",
                                          True, homes_color)
        else:
            homes_txt = self.font.render("🏠 ALL HOMES POWERED", True, (100, 220, 140))
        surface.blit(homes_txt, (w // 2 - homes_txt.get_width() // 2, y))
        y += homes_txt.get_height() + 6

        # reservoir tank badge — smaller, secondary: this is the box's own
        # buffered fill level (can lag well behind the live ratio above)
        tank_txt = self.font_small.render(
            f"RESERVOIR {min(state.fill_pct_display, 9.99) * 100:0.0f}%  ·  {fill_label}", True, rim_color)
        surface.blit(tank_txt, (w // 2 - tank_txt.get_width() // 2, y))
        y += tank_txt.get_height() + 10

        # active grid event banner with live countdown
        if state.active_event:
            ev = state.active_event
            banner = self.font.render(f"{ev.name}  ({ev.remaining:0.0f}s)", True, (255, 200, 90))
            pad = 10
            bw, bh = banner.get_width() + pad * 2, banner.get_height() + pad
            banner_bg = pygame.Surface((bw, bh), pygame.SRCALPHA)
            pulse = int(150 + 60 * abs(math.sin(self._t * 3)))
            pygame.draw.rect(banner_bg, (60, 45, 15, pulse), banner_bg.get_rect(), border_radius=6)
            pygame.draw.rect(banner_bg, (255, 200, 90, 200), banner_bg.get_rect(), width=1, border_radius=6)
            banner_bg.blit(banner, (pad, pad // 2))
            surface.blit(banner_bg, (24, 20 + clock_txt.get_height() + 8))

        flash_y = y
        for text, ttl in state.flash_messages:
            alpha = min(255, int(ttl * 150))
            flash_surf = self.font_big.render(text, True, (255, 90, 90))
            fs = pygame.Surface(flash_surf.get_size(), pygame.SRCALPHA)
            fs.blit(flash_surf, (0, 0))
            fs.set_alpha(alpha)
            surface.blit(fs, (w // 2 - flash_surf.get_width() // 2, flash_y))
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
            label = "☠ CATASTROPHIC BLACKOUT" if severity > 0.7 else "⚠ BLACKOUT RISK"
            self._draw_warning(surface, label, (255, 120, 120), y, severity)
        elif fill_pct > SEVERE_HIGH_THRESHOLD:
            span = MAX_FILL_PCT - SEVERE_HIGH_THRESHOLD
            severity = min(1.0, (fill_pct - SEVERE_HIGH_THRESHOLD) / max(0.01, span))
            self._draw_vignette(surface, AMBER, severity)
            label = "☠ GRID MELTDOWN IMMINENT" if severity > 0.6 else "⚠ CRITICAL OVERLOAD"
            self._draw_warning(surface, label, (255, 190, 110), y, severity)
        elif state.blackout:
            self._draw_vignette(surface, RED, 0.3)
            self._draw_warning(surface, "⚠ BLACKOUT RISK", (255, 120, 120), y, 0.3)

        if state.celebrate_high_score > 0:
            self._draw_success_toast(surface)

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

    def _draw_warning(self, surface, text, color, y, severity):
        # Slow, smooth brightness breathing — no positional jitter, and
        # capped well under 1 Hz — since large warning text is exactly the
        # kind of element that shouldn't be strobing.
        w, _ = surface.get_size()
        warn = self.font_big.render(text, True, color)
        alpha = int(170 + 85 * abs(math.sin(self._t * (1.2 + 0.8 * severity))))
        ws = pygame.Surface(warn.get_size(), pygame.SRCALPHA)
        ws.blit(warn, (0, 0))
        ws.set_alpha(alpha)
        surface.blit(ws, (w // 2 - warn.get_width() // 2, y))

    def draw_game_over(self, surface, state):
        w, h = surface.get_size()
        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((8, 9, 14, 215))
        surface.blit(dim, (0, 0))

        reason_labels = {
            "TOTAL BLACKOUT": "☠ TOTAL BLACKOUT",
            "GRID MELTDOWN": "☠ GRID MELTDOWN",
            "NUCLEAR MELTDOWN": "☢ NUCLEAR MELTDOWN",
        }
        # Gattie reacts to the failure. Bottom-anchored to the left of the
        # centered text block, clamped so a narrow window can't push him off.
        portrait = portraits.scaled_to_height(portraits.ANGRY, min(300, max(150, h // 3)))
        p_rect = portrait.get_rect()
        p_rect.right = max(portrait.get_width() + 12, w // 2 - 250)
        p_rect.centery = h // 2 - 10
        surface.blit(portrait, p_rect.topleft)

        title = reason_labels.get(state.game_over_reason, "☠ GRID FAILURE")
        title_txt = self.font_mono_big.render(title, True, (255, 110, 100))
        surface.blit(title_txt, (w // 2 - title_txt.get_width() // 2, h // 2 - 110))

        explanation = FAILURE_EXPLANATIONS.get(state.game_over_reason, "The grid did not survive.")
        sub = self.font.render(explanation, True, DIM)
        surface.blit(sub, (w // 2 - sub.get_width() // 2, h // 2 - 110 + title_txt.get_height() + 6))

        score_txt = self.font_big.render(f"FINAL SCORE  {int(state.score):,}", True, TEXT)
        surface.blit(score_txt, (w // 2 - score_txt.get_width() // 2, h // 2 - 20))

        best_color = (255, 215, 90) if state.new_high_score else DIM
        best_txt = self.font.render(f"BEST {int(state.high_score):,}", True, best_color)
        surface.blit(best_txt, (w // 2 - best_txt.get_width() // 2, h // 2 + 20 + score_txt.get_height()))

        hint = self.font.render("Press R to restart  ·  ESC to quit", True, DIM)
        surface.blit(hint, (w // 2 - hint.get_width() // 2, h // 2 + 70 + score_txt.get_height()))

    def _draw_vignette(self, surface, palette, severity=0.3):
        """Warning band around the play area. Previously four flat solid-color
        rects rebuilt every frame; now a pre-rendered gradient (dark exterior ->
        brighter interior) that only re-renders when the window size or the
        quantized thickness changes. Position, thickness and pulse timing are
        unchanged."""
        thickness = int(70 + 90 * severity)
        pulse_speed = 1.0 + 1.0 * severity  # capped well under 1 Hz
        pulse = int((30 + 60 * severity) * abs(math.sin(self._t * pulse_speed)))
        base_alpha = int(50 + 130 * severity)
        self._border.draw(surface, thickness, min(255, base_alpha + pulse), palette)
