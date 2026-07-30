"""Grid Keeper: entry point and game loop."""
import random
import sys
import pygame

from game_state import (GameState, WINDOW_WIDTH, WINDOW_HEIGHT, FPS,
                         DEMAND_MIN_MW, DEMAND_PEAK_MW,
                         SEVERE_LOW_THRESHOLD, SEVERE_HIGH_THRESHOLD, MAX_FILL_PCT,
                         instructional_complete, mark_instructional_complete)
from ui import instructional_data
from ui.demand_chart import DemandChart
from ui.spigot_panel import SpigotPanel
from ui.pipes import PipeSystem
from ui.city_grid import CityGrid
from ui.speed_control import SpeedControl
from ui.hud import HUD
from ui.sky import SkyLayer
from ui.tutorial import TutorialManager
from ui.day_panel import DayCompletePanel
from ui.menu import MenuSystem
from audio import AudioManager

BG_COLOR = (13, 17, 23)
PANEL_COLOR = (28, 35, 51)

TOP_HUD_HEIGHT = 220
SPIGOT_HEIGHT = 250

# Demand chart and the homes readout are small inset cards floating over the
# city, which occupies the entire lower region on its own.
CHART_W, CHART_H = 300, 170
CHART_MARGIN = 18

# How far into the city the trunk mains run before discharging. Has to sit well
# below the manifold height pipes.py derives from the city rect, or the trunks
# would route downward and then back up to meet it.
PIPE_ENTRY_FRAC = 0.38


def compute_layout(screen_w, screen_h):
    spigot_rect = pygame.Rect(0, TOP_HUD_HEIGHT, screen_w, SPIGOT_HEIGHT)
    city_rect = pygame.Rect(0, spigot_rect.bottom, screen_w,
                             max(160, screen_h - TOP_HUD_HEIGHT - SPIGOT_HEIGHT))
    chart_rect = pygame.Rect(city_rect.left + CHART_MARGIN, city_rect.bottom - CHART_H - CHART_MARGIN,
                              CHART_W, CHART_H)
    readout_rect = pygame.Rect(city_rect.right - CHART_W - CHART_MARGIN,
                                city_rect.bottom - CHART_H - CHART_MARGIN, CHART_W, CHART_H)
    return spigot_rect, city_rect, chart_rect, readout_rect


def _severity(fill_pct):
    """0..1 how catastrophic the current fill level is, 0 in the safe middle
    band, ramping up past either extreme. Drives screen shake."""
    if fill_pct < SEVERE_LOW_THRESHOLD:
        return (SEVERE_LOW_THRESHOLD - max(0.0, fill_pct)) / SEVERE_LOW_THRESHOLD
    if fill_pct > SEVERE_HIGH_THRESHOLD:
        return min(1.0, (fill_pct - SEVERE_HIGH_THRESHOLD) / max(0.01, MAX_FILL_PCT - SEVERE_HIGH_THRESHOLD))
    return 0.0


def main():
    pygame.init()
    pygame.display.set_caption("Grid Keeper: Energy Demand Management")
    screen = pygame.display.set_mode(
        (WINDOW_WIDTH, WINDOW_HEIGHT),
        pygame.DOUBLEBUF | pygame.HWSURFACE | pygame.RESIZABLE,
    )
    clock = pygame.time.Clock()

    mono_path = pygame.font.match_font("menlo,consolas,couriernew,monospace")
    font = pygame.font.Font(mono_path, 16)
    font_small = pygame.font.Font(mono_path, 13)
    font_bold = pygame.font.Font(mono_path, 16)
    font_big = pygame.font.Font(mono_path, 24)
    font_mono_big = pygame.font.Font(mono_path, 40)
    font_title = pygame.font.Font(mono_path, 64)

    # No game exists until the menu produces a RunConfig; the UI widgets below
    # are stateless w.r.t. which grid is loaded, so they're built once.
    state = None

    spigot_rect, city_rect, chart_rect, readout_rect = compute_layout(WINDOW_WIDTH, WINDOW_HEIGHT)
    spigot_panel = SpigotPanel(spigot_rect, font, font_small, font_bold)
    demand_chart = DemandChart(chart_rect, font_small)
    city_grid = CityGrid(font_small, font)
    speed_control = SpeedControl((24, 96), font_small, font)
    pipes = PipeSystem()
    hud = HUD(font, font_small, font_big, font_mono_big)
    sky = SkyLayer()
    tutorial = TutorialManager(font, font_small, font)
    day_panel = DayCompletePanel(font, font_small, font_big)
    audio = AudioManager()
    menu = MenuSystem(font, font_small, font_big, font_title)
    scene = "menu"   # "menu" | "game"

    # Latched once the player finishes or skips the tutorial, so it doesn't
    # replay every time a new Standard game starts this session. Someone who has
    # already completed the four guided days starts latched: walking them through
    # the Standard tutorial again would be condescending.
    tutorial_completed = instructional_complete()
    last_day = 1

    def build_tutorial(cfg, day):
        """The script for the current mode and day, or None when there is none."""
        if cfg.is_instructional:
            steps = instructional_data.DAYS.get(day)
            if not steps:
                return None
            return TutorialManager(font, font_small, font, steps=steps,
                                   conditions=instructional_data.CONDITIONS,
                                   skip_label="SKIP DAY")
        return TutorialManager(font, font_small, font)

    def start_game(cfg, fresh_tutorial=True):
        """Spin up a fresh session from a RunConfig chosen in the menu."""
        nonlocal state, scene, tutorial, tutorial_completed, last_day
        state = GameState(cfg)
        last_day = state.day
        day_panel.reset()
        # Region/scenario runs are supposed to play on real EIA data; if the
        # fetch fell back to the synthetic grid, say so instead of silently
        # serving a 1000 MW stand-in for a 40 GW authority.
        if cfg.mode != "standard" and cfg.data_source == "synthetic":
            state.flash_messages.append(["LIVE DATA UNAVAILABLE — SYNTHETIC GRID", 6.0])
        # The guided tutorial only runs on the Standard grid; region/scenario
        # players already know the ropes, so close it out of their way. A fresh
        # Standard game from the menu gets a brand-new tutorial (the manager is
        # single-use by design) unless it was already finished this session;
        # an R-key retry of the same grid never replays it.
        if tutorial.finished:
            tutorial_completed = True
        if cfg.is_instructional:
            # Every instructional day gets its own script, always — guidance is
            # the entire point of the mode, so it is never latched off.
            tutorial = build_tutorial(cfg, state.day) or tutorial
        elif cfg.mode == "standard" and fresh_tutorial and not tutorial_completed:
            tutorial = TutorialManager(font, font_small, font)
        else:
            tutorial.close_for_retry()
        # feed the chart the actual demand shape for this run
        demand_chart.demand_hours, demand_chart.demand_levels = state.demand_profile.samples(288)
        scene = "game"

    # depth=24 forces NO alpha byte. pygame.Surface() defaults to 32-bit with
    # an alpha channel on this platform (even without SRCALPHA), and blitting
    # the many SRCALPHA sub-surfaces used throughout (pipes, water, overflow)
    # onto a surface that has one overwrites its alpha with the source's —
    # even in fully-transparent regions — instead of leaving it at 255. That
    # silently zeroed frame's alpha wherever anything was drawn, making
    # everything after the first SRCALPHA blit vanish once composited to
    # `screen`.
    frame = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), depth=24)
    shake_x, shake_y = 0.0, 0.0
    was_game_over = False
    was_blackout = False
    was_celebrating = False

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        tutorial_on = (scene == "game" and state is not None
                       and state.config.mode in ("standard", "instructional"))

        # Input priority: outcome screen > day panel > tutorial > gameplay. Once
        # a layer claims an event nothing below it sees that event at all.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue

            # Always-live keys, whatever is on screen.
            if event.type == pygame.KEYDOWN and event.key == pygame.K_m:
                audio.toggle_mute()
                continue

            # ---- MENU scene ----
            if scene == "menu":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    # Esc steps one menu level back; only quits from the title.
                    if not menu.go_back():
                        running = False
                    continue
                menu.handle_event(event)
                continue

            # ---- GAME scene ----
            # Esc backs out to the menu rather than quitting the whole app.
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                scene = "menu"
                menu.open_menu()
                audio.unduck_music()
                continue

            # 1. success/failure screen
            if state.game_over:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    # Retry the SAME grid (same region/date/difficulty).
                    start_game(state.config, fresh_tutorial=False)
                    audio.unduck_music()
                continue  # nothing else reaches the grid behind the overlay

            # 2. day-complete panel
            if day_panel.handle_event(event, audio):
                continue

            # 3. tutorial / dialogue (Standard grid only)
            if tutorial_on and tutorial.handle_event(event, audio):
                continue

            # 4/5. normal gameplay
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    state.paused = not state.paused
                elif event.key in (pygame.K_EQUALS, pygame.K_KP_PLUS):
                    state.speed_up()
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    state.speed_down()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if hud.audio_rect and hud.audio_rect.collidepoint(event.pos):
                    audio.toggle_mute()
                elif speed_control.handle_mouse_down(event.pos, state):
                    audio.play("ui_click")
                else:
                    spigot_panel.handle_mouse_down(event.pos, state.active_sources)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                spigot_panel.handle_mouse_up()
            elif event.type == pygame.MOUSEMOTION:
                spigot_panel.handle_mouse_motion(event.pos, state.active_sources)

        # ---- MENU scene: update, maybe launch a game, draw, present ----
        if scene == "menu":
            menu.update(dt)
            cfg = menu.take_config()
            if cfg is not None:
                start_game(cfg)
            else:
                menu.draw(frame)
                screen.fill(BG_COLOR)
                screen.blit(frame, (0, 0))
                pygame.display.flip()
                continue

        # The tutorial freezes the sim while it's talking and releases it for
        # steps that need the player to act; the day panel and the outcome
        # screen freeze it outright.
        if not ((tutorial_on and tutorial.blocks_gameplay()) or day_panel.blocks_gameplay()
                or state.game_over):
            state.update(dt)

        # Recompute layout every frame from the actual surface size so resizing
        # or maximizing the window never leaves stale/mismatched panel rects.
        screen_w, screen_h = screen.get_size()
        spigot_rect, city_rect, chart_rect, readout_rect = compute_layout(screen_w, screen_h)
        spigot_panel.rect = spigot_rect
        demand_chart.rect = chart_rect

        if frame.get_size() != (screen_w, screen_h):
            frame = pygame.Surface((screen_w, screen_h), depth=24)

        # Named screen regions: highlight targets for the tutorial, and the rects
        # overlays must not cover. Taken from the real layout so they stay correct
        # through a resize instead of being guessed.
        regions = {
            "supply_demand": pygame.Rect(screen_w // 2 - 190, 14, 380, 150),
            "spigot_panel": spigot_rect,
            "gas_card": spigot_panel.card_rects(state.active_sources).get("gas"),
            "city": city_rect,
            # The dialogue box may sit over the city — it's the backdrop — but
            # not over the readouts floating on it, so those are listed
            # separately for the placement logic to avoid.
            "chart": chart_rect,
            "readout": readout_rect,
            "speed_control": speed_control.bounds(),
        }

        # The outcome screen and the day panel both suppress the tutorial: a
        # failure or a day rollover must never drive tutorial dialogue. The
        # tutorial itself only runs on the Standard grid.
        if tutorial_on and not (state.game_over or day_panel.blocks_gameplay()):
            tutorial.update(dt, state, regions, audio)
        day_panel.update(dt, state, regions, audio)

        # Confirming the final instructional day ends the mode: record the
        # completion and go back to the menu rather than rolling into a Day 5.
        if day_panel.take_return_to_menu():
            mark_instructional_complete()
            tutorial_completed = True
            scene = "menu"
            menu.open_menu()
            audio.unduck_music()
            continue

        # A day rolled over: swap in that day's script.
        if state.day != last_day:
            last_day = state.day
            if state.config.is_instructional:
                next_script = build_tutorial(state.config, state.day)
                if next_script is not None:
                    tutorial = next_script

        # --- audio cues, fired on state transitions (never per frame) ---
        audio.play_music("gameplay")  # idempotent: a no-op once it's playing
        if state.game_over and not was_game_over:
            audio.play("failure")
            audio.duck_music()
        was_game_over = state.game_over
        if state.blackout and not was_blackout and not state.game_over:
            audio.play("emergency")
        was_blackout = state.blackout
        celebrating = state.celebrate_high_score > 0
        if celebrating and not was_celebrating:
            audio.play("success")
        was_celebrating = celebrating

        # ---- render, back to front ----
        # 1. time-of-day sky, then the overhead city filling the whole lower
        #    region: how much of it is lit IS the supply/demand readout.
        sky.draw(frame, frame.get_rect(), state.sim_hour, state.active_event)
        city_grid.draw(frame, city_rect, state)

        # 2. world / game objects
        pygame.draw.rect(frame, PANEL_COLOR, spigot_rect)
        pygame.draw.line(frame, (10, 13, 20), (0, spigot_rect.bottom), (screen_w, spigot_rect.bottom), 2)
        spigot_panel.draw(frame, state.active_sources, state.demand_level,
                          show_price=state.show_economics)

        # trunk mains: drawn over the city, discharging part-way into it
        source_x = spigot_panel.source_x_centers(state.active_sources)
        city_entry_y = city_rect.top + city_rect.height * PIPE_ENTRY_FRAC
        pipes.draw(frame, state.active_sources, source_x, spigot_rect.bottom, city_entry_y, city_rect)

        # 3. inset cards floating over the city
        demand_chart.draw(frame, state.sim_hour, state.sources, state.history,
                          state.demand_mw, state.demand_min_mw, state.demand_peak_mw)
        city_grid.draw_homes_label(frame, readout_rect, state.homes_without_power, state.homes_total)

        # 5. normal HUD
        hud.draw(frame, state, TOP_HUD_HEIGHT)
        speed_control.draw(frame, state)
        hud.draw_audio_indicator(frame, audio, (24, speed_control.bounds().bottom + 6))

        # 6. highlights and tutorial indicators (Standard grid only)
        if tutorial_on:
            tutorial.draw_highlight(frame)
            tutorial.draw(frame)

        # 7. end-of-day panel
        day_panel.draw(frame)

        # 8. success / failure overlay
        if state.game_over:
            hud.draw_game_over(frame, state)

        # Screen shake at extreme over/undersupply: the whole frame is drawn
        # to an offscreen surface so it can be jittered as one unit, instead
        # of just flashing a vignette while everything else sits static. The
        # target offset is low-pass filtered rather than applied raw, so it
        # wanders smoothly instead of teleporting to a new random position
        # every single frame (a 60Hz jitter reads as harsh/flickery).
        # keep the centered end-of-day takeover rock-steady even if the day
        # ended mid-crisis (fill_pct_display is frozen at whatever it was)
        severity = 0.0 if (state.game_over or day_panel.blocks_gameplay()) \
            else _severity(state.fill_pct_display)
        if severity > 0.05:
            mag = severity * 6
            target_x = random.uniform(-mag, mag)
            target_y = random.uniform(-mag, mag)
        else:
            target_x = target_y = 0.0
        shake_x += (target_x - shake_x) * 0.3
        shake_y += (target_y - shake_y) * 0.3

        screen.fill(BG_COLOR)
        screen.blit(frame, (int(shake_x), int(shake_y)))

        pygame.display.flip()

    if state is not None:
        state.persist_high_score()
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
