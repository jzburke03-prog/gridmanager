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
The harness fixes Python's hash seed before importing the city renderer so its
hashed layout and animation seeds are stable across fresh processes.
"""
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, *sys.argv])

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
    from ui.demand_chart import DemandChart
    from ui.iso_city import IsoCity
    from ui.plant_pins import PlantPins
    from ui.speed_control import SpeedControl
    from ui.hud import HUD, hud_panel_rects
    from ui.atmosphere import AtmosphereLayer
    from ui.day_panel import DayCompletePanel
    from ui.menu import MenuSystem
    from audio import AudioManager

    f = _fonts()
    city_rect, chart_rect, readout_rect, hud_h = main.compute_layout(W, H)
    hud_panels = hud_panel_rects(W, H)
    w = {
        "main": main,
        "scenarios": scenarios,
        "GameState": GameState,
        "city_rect": city_rect,
        "chart_rect": chart_rect,
        "readout_rect": readout_rect,
        "hud_h": hud_h,
        "hud_panels": hud_panels,
        "demand_chart": DemandChart(chart_rect, f["font_small"]),
        "city": IsoCity(f["font_small"], f["font"]),
        "plant_pins": PlantPins(f["font"], f["font_small"], f["font_bold"]),
        "speed_control": SpeedControl((hud_panels["left"].left + 10,
                                        hud_panels["left"].top + 60),
                                       f["font_small"], f["font"]),
        "hud": HUD(f["font"], f["font_small"], f["font_big"], f["font_mono_big"]),
        "atmosphere": AtmosphereLayer(),
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
    city_rect = w["city_rect"]

    w["main"].clear_frame(frame)
    from ui.atmosphere import sample_atmosphere
    environment = sample_atmosphere(
        st.sim_hour, st.active_event.kind if st.active_event else None)
    w["city"].draw(frame, city_rect, st, environment)
    w["atmosphere"].draw(frame, city_rect, environment, 1 / 60.0)
    w["demand_chart"].draw(frame, st.sim_hour, st.sources, st.history, st.demand_mw,
                           st.demand_min_mw, st.demand_peak_mw)
    w["city"].draw_homes_label(frame, w["readout_rect"], st.homes_without_power,
                               st.homes_total)
    pin_obstacles = (w["chart_rect"], w["readout_rect"], w["hud_panels"]["outer"])
    w["plant_pins"].draw(frame, st.active_sources, w["city"].plant_markers(city_rect),
                         pin_obstacles, city_rect,
                         st.demand_level, show_price=st.show_economics)
    w["hud"].draw(frame, st, w["hud_panels"])
    w["speed_control"].draw(frame, st)
    w["hud"].draw_audio_indicator(frame, w["audio"],
                                  (w["hud_panels"]["left"].left + 10,
                                   w["speed_control"].bounds().bottom + 6))


def capture(out_dir):
    random.seed(42)
    pygame.init()
    pygame.display.set_mode((W, H))
    frame = pygame.Surface((W, H), depth=24)
    w = _build()
    from ui.menu import TITLE, MODE, FREEPLAY, SCENARIOS, FETCHING
    from ui.day_panel import DayPhase
    import game_state

    saved = []

    def save(name):
        pygame.image.save(frame, str(out_dir / f"{name}.png"))
        saved.append(name)

    def settle(st, frames=24):
        for _ in range(frames):
            render_game(frame, st, w)

    def set_supply_ratio(st, ratio):
        remaining = st.demand_mw * ratio
        for source in st.sources:
            pct = min(1.0, remaining / source.effective_max_mw)
            source.set_handle(pct)
            source.actual_pct = pct
            remaining -= source.current_output_mw
        assert abs(st.total_actual_mw / st.demand_mw - ratio) < 1e-9
        st.fill_pct = st.fill_pct_display = ratio
        st.blackout = False
        st.overflow = ratio >= 1.0
        w["hud"]._ratio_display = ratio

    def fresh_game(sim_hour, zoom):
        nonlocal w
        w = _build()
        st = _new_state(w, sim_hour=sim_hour)
        st.sim_hour = sim_hour
        w["city"].prepare(w["city_rect"], st)
        camera = w["city"].camera
        camera.center[:] = w["city"]._world_rect.center
        camera.set_zoom(zoom, w["city_rect"].center,
                        w["city_rect"], w["city"]._world_rect)
        return st

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

    # --- regional stage / LOD review matrix ---
    st4 = _new_state(w)
    render_game(frame, st4, w)  # ensure the region and camera exist
    for number, zoom in enumerate((1, 2, 4), 11):
        w["city"].camera.set_zoom(zoom, w["city_rect"].center,
                                  w["city_rect"], w["city"]._world_rect)
        settle(st4)
        save(f"{number:02d}_zoom_{zoom}x_day")

    w["city"].camera.set_zoom(1, w["city_rect"].center,
                              w["city_rect"], w["city"]._world_rect)
    st4.sim_hour = 18.5
    settle(st4)
    save("14_zoom_1x_evening")

    for hour, name in ((5.5, "15_region_dawn"), (22.0, "16_region_night")):
        st4.sim_hour = hour
        settle(st4)
        save(name)

    st4.sim_hour = 14.0
    for kind, name in (("RAIN", "17_weather_rain"),
                       ("SNOW", "18_weather_snow"),
                       ("WIND_GUST", "19_weather_wind"),
                       ("HEAT_WAVE", "20_weather_heat")):
        st4.active_event = game_state._make_event(kind, st4.sources)
        settle(st4)
        save(name)
    st4.active_event = None

    # Populate the delivery chain's pulses, then frame one plant and the city.
    st4.sim_hour = 14.0
    w["city"].camera.set_zoom(4, w["city_rect"].center,
                              w["city_rect"], w["city"]._world_rect)
    gas_site = next((site for site in w["city"]._plants if site.key == "gas"), None)
    if gas_site:
        w["city"].camera.center = [gas_site.sx + w["city"]._origin[0],
                                    gas_site.sy + w["city"]._origin[1]]
        w["city"].camera.clamp(w["city_rect"], w["city"]._world_rect)
    settle(st4, 90)
    save("21_delivery_chain_close")

    gas = next((source for source in st4.sources if source.key == "gas"), None)
    if gas:
        gas.set_handle(0.0)
        for _ in range(180):
            st4.update(1 / 60.0)
    settle(st4, 45)
    save("22_offline_plant_flow")

    # Absolute overload ladder: warm voltage tint begins above 101%, local
    # arcing is fully active at 150%, and fires reach the whole city at 200%.
    st4.sim_hour = 4.0
    st4.demand_level = st4.demand_profile.level_at(st4.sim_hour)
    for ratio, frames, name in ((1.01, 1, "23_overload_101"),
                                (1.50, 22, "24_overload_150"),
                                (2.00, 120, "25_overload_200")):
        set_supply_ratio(st4, ratio)
        settle(st4, frames)
        if ratio == 1.50:
            assert w["city"]._arcs
        elif ratio == 2.00:
            assert w["city"]._fires
        save(name)

    # Pan a fresh 4x view so directional tabs can be reviewed together.
    st5 = fresh_game(14.0, 4)
    w["city"].pan_by(800, 100, w["city_rect"])
    markers = w["city"].plant_markers(w["city_rect"])
    assert sum(not marker["visible"] for marker in markers.values()) >= 3
    settle(st5, 1)
    save("26_offscreen_plant_tabs")

    # Rebuild between rush captures so traffic starts from the same seeded
    # road state and only the requested hour differs.
    for hour, name in ((9.0, "27_morning_rush"),
                       (17.0, "28_evening_rush")):
        rush = fresh_game(hour, 2)
        settle(rush, 90)
        save(name)

    print(f"captured {len(saved)} moments to {out_dir}")


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "captures"
    out_dir.mkdir(parents=True, exist_ok=True)
    capture(out_dir)


if __name__ == "__main__":
    main()
