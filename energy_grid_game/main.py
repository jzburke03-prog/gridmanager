"""Grid Keeper: entry point and game loop."""
import math
import random
import sys
import pygame

from game_state import (GameState, WINDOW_WIDTH, WINDOW_HEIGHT, FPS,
                         MAX_BOX_HEIGHT_PX, MAX_BOX_FOOTPRINT_PX,
                         DEMAND_MIN_MW, DEMAND_PEAK_MW,
                         SEVERE_LOW_THRESHOLD, SEVERE_HIGH_THRESHOLD, MAX_FILL_PCT)
from ui.demand_box import DemandBox
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

# Demand chart is now a small inset card tucked in the corner (per the pipes
# layout sketch) instead of a full-width strip, freeing the whole lower area
# for the box + its feeder pipes.
CHART_W, CHART_H = 300, 170
CHART_MARGIN = 18

# Isometric box clearance: the box's on-screen footprint extends the vessel's
# silhouette well past its "height" alone (its nearest corner drops another
# footprint/2 px below center, and it spans footprint*sqrt(3) px wide), so the
# scale-to-fit math has to account for the whole diamond, not just height vs.
# box_rect.height, or the box clips into the panels above/below it.
BOX_TOP_MARGIN = 20
BOX_BOTTOM_MARGIN = 24
BOX_SIDE_MARGIN = 40
ISO_HALF_WIDTH_RATIO = math.cos(math.radians(30))  # x-extent of footprint_px per side


def _supply_mix_tint(sources):
    """Blend each source's color weighted by its share of current output, so
    the tank visibly reflects what's actually filling it right now."""
    total = sum(s.current_output_mw for s in sources)
    if total <= 1.0:
        return None
    r = g = b = 0.0
    for s in sources:
        weight = s.current_output_mw / total
        r += s.color[0] * weight
        g += s.color[1] * weight
        b += s.color[2] * weight
    return (r, g, b)


def compute_layout(screen_w, screen_h):
    spigot_rect = pygame.Rect(0, TOP_HUD_HEIGHT, screen_w, SPIGOT_HEIGHT)
    box_rect = pygame.Rect(0, spigot_rect.bottom, screen_w,
                            max(160, screen_h - TOP_HUD_HEIGHT - SPIGOT_HEIGHT))
    chart_rect = pygame.Rect(box_rect.left + CHART_MARGIN, box_rect.bottom - CHART_H - CHART_MARGIN,
                              CHART_W, CHART_H)
    city_rect = pygame.Rect(box_rect.right - CHART_W - CHART_MARGIN, box_rect.bottom - CHART_H - CHART_MARGIN,
                             CHART_W, CHART_H)
    return spigot_rect, box_rect, chart_rect, city_rect


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

    spigot_rect, box_rect, chart_rect, city_rect = compute_layout(WINDOW_WIDTH, WINDOW_HEIGHT)
    spigot_panel = SpigotPanel(spigot_rect, font, font_small, font_bold)
    demand_box = DemandBox(center=(WINDOW_WIDTH // 2, box_rect.top + box_rect.height - 40))
    demand_chart = DemandChart(chart_rect, font_small)
    city_grid = CityGrid(city_rect, font_small, font)
    speed_control = SpeedControl((24, 96), font_small, font)
    pipes = PipeSystem()
    hud = HUD(font, font_small, font_big, font_mono_big)
    sky = SkyLayer()
    tutorial = TutorialManager(font, font_small, font)
    day_panel = DayCompletePanel(font, font_small, font_big)
    audio = AudioManager()
    menu = MenuSystem(font, font_small, font_big, font_title)
    scene = "menu"   # "menu" | "game"

    def start_game(cfg):
        """Spin up a fresh session from a RunConfig chosen in the menu."""
        nonlocal state, scene
        state = GameState(cfg)
        day_panel.reset()
        # The guided tutorial only runs on the Standard grid; region/scenario
        # players already know the ropes, so close it out of their way.
        if cfg.mode != "standard":
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

        tutorial_on = scene == "game" and state is not None and state.config.mode == "standard"

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
                    start_game(state.config)
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
                if speed_control.handle_mouse_down(event.pos, state):
                    audio.play("ui_click")
                else:
                    spigot_panel.handle_mouse_down(event.pos, state.sources)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                spigot_panel.handle_mouse_up()
            elif event.type == pygame.MOUSEMOTION:
                spigot_panel.handle_mouse_motion(event.pos, state.sources)

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
        spigot_rect, box_rect, chart_rect, city_rect = compute_layout(screen_w, screen_h)
        spigot_panel.rect = spigot_rect
        demand_chart.rect = chart_rect
        city_grid.rect = city_rect

        if frame.get_size() != (screen_w, screen_h):
            frame = pygame.Surface((screen_w, screen_h), depth=24)

        # Fit-to-space scale: sized against the box's absolute MAX height/footprint
        # (not the current instantaneous demand) so it never grows into a clip as
        # demand rises later. Full iso vertical silhouette = height + the WHOLE
        # footprint: the base's near corner hangs footprint/2 below center AND the
        # top diamond's back corner rises footprint/2 above the height line.
        max_vertical_span = MAX_BOX_HEIGHT_PX + MAX_BOX_FOOTPRINT_PX
        max_horizontal_span = MAX_BOX_FOOTPRINT_PX * 2 * ISO_HALF_WIDTH_RATIO
        k_vertical = (box_rect.height - BOX_TOP_MARGIN - BOX_BOTTOM_MARGIN) / max_vertical_span
        k_horizontal = (box_rect.width - 2 * BOX_SIDE_MARGIN) / max_horizontal_span
        box_scale_ui = max(0.4, min(k_vertical, k_horizontal, 3.0))

        box_height_px = state.box_height_px * box_scale_ui
        box_footprint_px = state.box_footprint_px * box_scale_ui

        # Anchor the box to a fixed floor line so it grows upward/outward from
        # a stable base rather than drifting as its footprint changes.
        floor_y = box_rect.bottom - BOX_BOTTOM_MARGIN
        demand_box.center = (screen_w // 2, floor_y - box_footprint_px / 2)
        box_top_point = (demand_box.center[0], demand_box.center[1] - box_height_px)

        # Named screen regions: highlight targets for the tutorial, and the rects
        # overlays must not cover. Taken from the real layout so they stay correct
        # through a resize instead of being guessed. The tank rect is the full
        # isometric silhouette, not just the height.
        tank_half_w = box_footprint_px * ISO_HALF_WIDTH_RATIO
        regions = {
            "supply_demand": pygame.Rect(screen_w // 2 - 190, 14, 380, 150),
            "spigot_panel": spigot_rect,
            "gas_card": spigot_panel.card_rects(state.sources).get("gas"),
            "tank": pygame.Rect(
                demand_box.center[0] - tank_half_w,
                demand_box.center[1] - box_height_px - box_footprint_px / 2,
                tank_half_w * 2,
                box_height_px + box_footprint_px,
            ),
            "city": city_rect.union(city_grid.label_rect()),
            "speed_control": speed_control.bounds(),
        }

        # The outcome screen and the day panel both suppress the tutorial: a
        # failure or a day rollover must never drive tutorial dialogue. The
        # tutorial itself only runs on the Standard grid.
        if tutorial_on and not (state.game_over or day_panel.blocks_gameplay()):
            tutorial.update(dt, state, regions, audio)
        day_panel.update(dt, state, regions, audio)

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
        # 1. time-of-day background
        sky.draw(frame, frame.get_rect(), state.sim_hour, state.active_event)

        # 2. world / game objects
        pygame.draw.rect(frame, PANEL_COLOR, spigot_rect)
        pygame.draw.line(frame, (10, 13, 20), (0, spigot_rect.bottom), (screen_w, spigot_rect.bottom), 2)
        spigot_panel.draw(frame, state.sources, state.demand_level)

        # feeder pipes: drawn before the box so their ends tuck behind the rim.
        # Droplets keep falling past the rim down to the CURRENT water surface
        # (not a fixed point), so they visibly land wherever the tank's fill
        # level actually is instead of splashing in empty space near the top.
        clamped_fill = max(0.0, min(1.0, state.fill_pct_display))
        water_drop_px = box_height_px * (1.0 - clamped_fill)
        source_x = spigot_panel.source_x_centers(state.sources)
        pipes.draw(frame, state.sources, source_x, spigot_rect.bottom, box_top_point, box_rect,
                  water_drop_px)

        # net grid imbalance drives how agitated the water surface is
        agitation = max(-1.5, min(1.5, (state.total_actual_mw - state.demand_mw) / 620.0))
        tint_rgb = _supply_mix_tint(state.sources)

        # 3. water tank and city graphics
        demand_box.draw(frame, box_height_px, box_footprint_px,
                        state.fill_pct_display, agitation, tint_rgb)
        demand_chart.draw(frame, state.sim_hour, state.sources, state.history,
                          state.demand_mw, state.demand_min_mw, state.demand_peak_mw)
        city_grid.draw(frame, state.fill_pct_display)

        # 4. world-attached labels
        city_grid.draw_homes_label(frame, state.homes_without_power, state.homes_total)

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
        severity = 0.0 if state.game_over else _severity(state.fill_pct_display)
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
