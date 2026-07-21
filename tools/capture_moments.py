"""Headless screenshot harness for every game "moment".

Renders the title/menu screens and the in-game world (plus event, warning,
day-complete and game-over overlays) to PNGs under captures/, without opening a
window or needing audio. This is the project's visual-regression tool: capture
before a change (the baseline) and after, then eyeball the diff.

Run:  .venv39\\Scripts\\python.exe tools\\capture_moments.py [out_dir]

It composes the in-game frame by replaying main.py's own render stack
(main.render order, lines ~323-359) against a synthetic Standard grid, so the
captures track what the real game draws.

Determinism note: the menu frames (01-05) and the calm game frame (06) are
byte-stable run to run; the frames with live weather particles or pulsing
warnings (07-10) carry animation noise, so compare those by eye, not by hash.
"""
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "energy_grid_game"))

import pygame  # noqa: E402

W, H = 1400, 900


def _fonts():
    p = pygame.font.match_font("menlo,consolas,couriernew,monospace")
    return {
        "font": pygame.font.Font(p, 16),
        "font_small": pygame.font.Font(p, 13),
        "font_bold": pygame.font.Font(p, 16),
        "font_big": pygame.font.Font(p, 24),
        "font_mono_big": pygame.font.Font(p, 40),
        "font_title": pygame.font.Font(p, 64),
    }


def _build():
    """Construct the widgets exactly as main.main() does."""
    import main
    import scenarios
    from game_state import GameState
    from ui.spigot_panel import SpigotPanel
    from ui.demand_box import DemandBox
    from ui.demand_chart import DemandChart
    from ui.city_grid import CityGrid
    from ui.speed_control import SpeedControl
    from ui.pipes import PipeSystem
    from ui.hud import HUD
    from ui.sky import SkyLayer
    from ui.day_panel import DayCompletePanel
    from ui.menu import MenuSystem
    from audio import AudioManager

    f = _fonts()
    spigot_rect, box_rect, chart_rect, city_rect = main.compute_layout(W, H)
    w = {
        "main": main,
        "scenarios": scenarios,
        "GameState": GameState,
        "spigot_rect": spigot_rect,
        "box_rect": box_rect,
        "city_rect": city_rect,
        "spigot_panel": SpigotPanel(spigot_rect, f["font"], f["font_small"], f["font_bold"]),
        "demand_box": DemandBox(center=(W // 2, box_rect.top + box_rect.height - 40)),
        "demand_chart": DemandChart(chart_rect, f["font_small"]),
        "city_grid": CityGrid(f["font_small"], f["font"]),
        "speed_control": SpeedControl((24, 96), f["font_small"], f["font"]),
        "pipes": PipeSystem(),
        "hud": HUD(f["font"], f["font_small"], f["font_big"], f["font_mono_big"]),
        "sky": SkyLayer(),
        "day_panel": DayCompletePanel(f["font"], f["font_small"], f["font_big"]),
        "menu": MenuSystem(f["font"], f["font_small"], f["font_big"], f["font_title"]),
        "audio": AudioManager(),
    }
    w.update(f)
    return w


def _new_state(w, sim_hour=14.0, steps=120):
    st = w["GameState"](w["scenarios"].make_standard())
    st.sim_hour = sim_hour
    # nudge a few plants so the world isn't all-idle
    for key, pct in (("nuclear", 0.5), ("gas", 0.6), ("solar", 1.0), ("wind", 1.0)):
        for s in st.sources:
            if s.key == key:
                s.set_handle(pct)
    for _ in range(steps):
        st.update(1 / 60.0)
    w["demand_chart"].demand_hours, w["demand_chart"].demand_levels = \
        st.demand_profile.samples(288)
    return st


def render_game(frame, st, w):
    """Replay main.py's in-game render stack onto `frame`."""
    main = w["main"]
    spigot_rect, box_rect = w["spigot_rect"], w["box_rect"]

    w["sky"].draw(frame, frame.get_rect(), st.sim_hour, st.active_event)
    w["city_grid"].draw_backdrop(frame, box_rect, st.fill_pct_display)
    pygame.draw.rect(frame, main.PANEL_COLOR, spigot_rect)
    pygame.draw.line(frame, (10, 13, 20), (0, spigot_rect.bottom), (W, spigot_rect.bottom), 2)
    w["spigot_panel"].draw(frame, st.sources, st.demand_level)

    # box fit-to-space (mirrors main.py:268-281)
    max_v = main.MAX_BOX_HEIGHT_PX + main.MAX_BOX_FOOTPRINT_PX
    max_h = main.MAX_BOX_FOOTPRINT_PX * 2 * main.ISO_HALF_WIDTH_RATIO
    k_v = (box_rect.height - main.BOX_TOP_MARGIN - main.BOX_BOTTOM_MARGIN) / max_v
    k_h = (box_rect.width - 2 * main.BOX_SIDE_MARGIN) / max_h
    box_scale_ui = max(0.4, min(k_v, k_h, 3.0))
    box_height_px = st.box_height_px * box_scale_ui
    box_footprint_px = st.box_footprint_px * box_scale_ui
    floor_y = box_rect.bottom - main.BOX_BOTTOM_MARGIN
    w["demand_box"].center = (W // 2, floor_y - box_footprint_px / 2)
    box_top_point = (w["demand_box"].center[0], w["demand_box"].center[1] - box_height_px)

    clamped = max(0.0, min(1.0, st.fill_pct_display))
    source_x = w["spigot_panel"].source_x_centers(st.sources)
    w["pipes"].draw(frame, st.sources, source_x, spigot_rect.bottom, box_top_point,
                    box_rect, box_height_px * (1.0 - clamped))
    agitation = max(-1.5, min(1.5, (st.total_actual_mw - st.demand_mw) / 620.0))
    w["demand_box"].draw(frame, box_height_px, box_footprint_px, st.fill_pct_display,
                         agitation, main._supply_mix_tint(st.sources))
    w["demand_chart"].draw(frame, st.sim_hour, st.sources, st.history, st.demand_mw,
                           st.demand_min_mw, st.demand_peak_mw)
    w["city_grid"].draw_homes_label(frame, w["city_rect"], st.homes_without_power, st.homes_total)
    w["hud"].draw(frame, st, main.TOP_HUD_HEIGHT)
    w["speed_control"].draw(frame, st)
    w["hud"].draw_audio_indicator(frame, w["audio"],
                                  (24, w["speed_control"].bounds().bottom + 6))


def capture(out_dir):
    random.seed(42)
    pygame.init()
    pygame.display.set_mode((W, H))
    frame = pygame.Surface((W, H), depth=24)
    w = _build()
    from ui.menu import TITLE, MODE, FREEPLAY, SCENARIOS, FETCHING
    from ui.day_panel import DayPhase
    import game_state

    def save(name):
        pygame.image.save(frame, str(out_dir / f"{name}.png"))

    # --- menu screens ---
    menu = w["menu"]
    for st_id, name in ((TITLE, "01_title"), (MODE, "02_mode"),
                        (FREEPLAY, "03_freeplay"), (SCENARIOS, "04_scenarios")):
        menu.state = st_id
        frame.fill((0, 0, 0))
        for _ in range(140):          # advance past the splash fade-in
            menu.update(1 / 60.0)
            menu.draw(frame)
        save(name)

    menu.state = FETCHING
    menu._fetch_label = "Loading Winter Storm Uri · 15 Feb 2021"
    menu._fetch_from = SCENARIOS
    frame.fill((0, 0, 0))
    for _ in range(30):
        menu.update(1 / 60.0)
        menu.draw(frame)
    save("05_fetching")

    # --- in-game ---
    st = _new_state(w)
    render_game(frame, st, w)
    save("06_game")

    st.active_event = game_state._make_event("ICE_STORM", st.sources)
    for _ in range(10):
        st.update(1 / 60.0)
    render_game(frame, st, w)
    save("07_game_event")

    st.active_event = None
    st.fill_pct_display = 0.5
    render_game(frame, st, w)
    save("08_game_warning")

    # --- day complete takeover ---
    st2 = _new_state(w)
    st2.day_complete = True
    dp = w["day_panel"]
    dp.phase = DayPhase.DAY_COMPLETE_PAUSED
    dp._state = st2
    dp._day_label = f"DAY {st2.day} COMPLETE"
    dp._chart.demand_hours, dp._chart.demand_levels = st2.demand_profile.samples(288)
    render_game(frame, st2, w)
    dp.draw(frame)
    save("09_day_complete")

    # --- game over ---
    st3 = _new_state(w)
    st3.game_over = True
    st3.game_over_reason = "TOTAL BLACKOUT"
    render_game(frame, st3, w)
    w["hud"].draw_game_over(frame, st3)
    save("10_game_over")

    print(f"captured 10 moments to {out_dir}")


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "captures"
    out_dir.mkdir(parents=True, exist_ok=True)
    capture(out_dir)


if __name__ == "__main__":
    main()
