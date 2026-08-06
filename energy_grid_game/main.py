"""Grid Keeper: entry point and game loop."""
import os
import random
import sys
import pygame

from game_state import (GameState, WINDOW_WIDTH, WINDOW_HEIGHT, FPS,
                         DEMAND_MIN_MW, DEMAND_PEAK_MW,
                         SEVERE_LOW_THRESHOLD, SEVERE_HIGH_THRESHOLD, MAX_FILL_PCT,
                         instructional_complete, mark_instructional_complete)
from ui import gl_context, instructional_data, terrain3d
from ui.demand_chart import DemandChart
from ui.iso_city import IsoCity
from ui.plant_pins import PlantPins
from ui.speed_control import SpeedControl
from ui.hud import HUD, hud_hit_test, hud_panel_rects
from ui.atmosphere import AtmosphereLayer, sample_atmosphere
from ui.tutorial import TutorialManager
from ui.day_panel import DayCompletePanel
from ui.menu import MenuSystem
from audio import AudioManager

BG_COLOR = (13, 17, 23)

# Phase 1 stopgap: the 3D terrain layer renders correctly but is fully
# hidden behind IsoCity's existing opaque 2D countryside sprites (a later
# phase will stop drawing those so the 3D layer becomes visible), so it's
# opt-in and OFF by default -- normal players pay none of its GPU/CPU cost
# and don't need a working OpenGL driver until that later phase lands.
def _terrain3d_enabled():
    return terrain3d.is_enabled()


TERRAIN3D_ENABLED = _terrain3d_enabled()

# Resizes are clamped before the HUD and city become unusably small.
MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT = 1000, 680

# Demand chart and the homes readout are small inset cards floating over the
# city, which occupies the entire frame behind the three HUD islands.
CHART_W, CHART_H = 292, 158
CHART_MARGIN = 28


def clear_frame(frame):
    frame.fill(BG_COLOR)

def compute_layout(screen_w, screen_h):
    """-> (city_rect, chart_rect, readout_rect, hud_height).

    The regional stage owns the full frame. `hud_h` remains a compatibility
    value for callers that reserve tutorial space, not a world-stage boundary.
    """
    city_rect = pygame.Rect(0, 0, screen_w, screen_h)
    panels = hud_panel_rects(screen_w, screen_h)
    hud_h = max(rect.bottom for rect in panels.values()) + 42
    cw = max(196, min(CHART_W, int(screen_w * 0.22)))
    ch = max(112, min(CHART_H, int(city_rect.height * 0.34)))
    chart_rect = pygame.Rect(city_rect.left + CHART_MARGIN,
                              city_rect.bottom - ch - CHART_MARGIN, cw, ch)
    readout_rect = pygame.Rect(city_rect.right - cw - CHART_MARGIN,
                                city_rect.bottom - ch - CHART_MARGIN, cw, ch)
    return city_rect, chart_rect, readout_rect, hud_h


def cancel_map_interaction(plant_pins):
    """Release every mouse-driven map control when gameplay loses focus."""
    plant_pins.handle_mouse_up()
    return False


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

    city_rect, chart_rect, readout_rect, hud_h = compute_layout(WINDOW_WIDTH, WINDOW_HEIGHT)
    hud_panels = hud_panel_rects(WINDOW_WIDTH, WINDOW_HEIGHT)
    plant_pins = PlantPins(font, font_small, font_bold)
    demand_chart = DemandChart(chart_rect, font_small)
    city = IsoCity(font_small, font)
    gl_ctx = terrain3d_prog = terrain3d_meshes = None
    terrain3d_key = None
    terrain3d_fbo = None
    terrain3d_plant_meshes = []
    if TERRAIN3D_ENABLED:
        try:
            gl_ctx = gl_context.create_context()
        except gl_context.UnsupportedGLError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        terrain3d_prog = terrain3d.create_program(gl_ctx)
        terrain3d_meshes = terrain3d.load_meshes(gl_ctx, terrain3d_prog)
    speed_control = SpeedControl((hud_panels["left"].left + 10,
                                  hud_panels["left"].top + 60), font_small, font)
    hud = HUD(font, font_small, font_big, font_mono_big)
    atmosphere_layer = AtmosphereLayer()
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
                                   skip_label="SKIP DIALOGUE")
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
        if cfg.mode in ("region", "scenario") and cfg.data_source == "synthetic":
            state.flash_messages.append(["LIVE DATA UNAVAILABLE: SYNTHETIC GRID", 6.0])
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
    # the many SRCALPHA sub-surfaces used throughout (city, particles, overflow)
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
    city_dragging = False

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        tutorial_on = (scene == "game" and state is not None
                       and state.config.mode in ("standard", "instructional"))
        if (scene != "game" or state.game_over or day_panel.blocks_gameplay()
                or (tutorial_on and tutorial.blocks_gameplay())):
            city_dragging = cancel_map_interaction(plant_pins)

        # Input priority: outcome screen > day panel > tutorial > gameplay. Once
        # a layer claims an event nothing below it sees that event at all.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue

            # Resizing is honoured, but not below the point where the HUD would
            # leave the city too little room.
            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode(
                    (max(MIN_WINDOW_WIDTH, event.w), max(MIN_WINDOW_HEIGHT, event.h)),
                    pygame.DOUBLEBUF | pygame.HWSURFACE | pygame.RESIZABLE,
                )
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
                elif event.key == pygame.K_LEFT:
                    city.pan_by(32, 0, city_rect)
                elif event.key == pygame.K_RIGHT:
                    city.pan_by(-32, 0, city_rect)
                elif event.key == pygame.K_UP:
                    city.pan_by(0, 32, city_rect)
                elif event.key == pygame.K_DOWN:
                    city.pan_by(0, -32, city_rect)
            elif event.type == pygame.MOUSEWHEEL:
                mouse = pygame.mouse.get_pos()
                if city_rect.collidepoint(mouse) and not hud_hit_test(hud_panels, mouse):
                    city.zoom_at(event.y, mouse, city_rect)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if hud.audio_rect and hud.audio_rect.collidepoint(event.pos):
                    audio.toggle_mute()
                elif speed_control.handle_mouse_down(event.pos, state):
                    audio.play("ui_click")
                else:
                    markers = city.plant_markers(city_rect)
                    obstacles = (chart_rect, readout_rect, hud_panels["outer"])
                    action = plant_pins.handle_mouse_down(
                        event.pos, state.active_sources, markers, obstacles,
                        city_rect)
                    if action:
                        kind, key = action
                        if kind == "focus":
                            city.focus_plant(key, city_rect)
                        audio.play("ui_click")
                    elif (city_rect.collidepoint(event.pos)
                          and not hud_hit_test(hud_panels, event.pos)):
                        city_dragging = True
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                plant_pins.handle_mouse_up()
                city_dragging = False
            elif event.type == pygame.MOUSEMOTION:
                markers = city.plant_markers(city_rect)
                obstacles = (chart_rect, readout_rect, hud_panels["outer"])
                if plant_pins.dragging_key is not None and event.buttons[0]:
                    plant_pins.handle_mouse_motion(event.pos, state.active_sources,
                                                   markers, obstacles, city_rect)
                elif city_dragging and event.buttons[0]:
                    city.pan_by(event.rel[0], event.rel[1], city_rect)
                elif not event.buttons[0]:
                    city_dragging = cancel_map_interaction(plant_pins)

        # Keep the offscreen frame the same size as the window. This has to
        # happen BEFORE the menu branch: the menu used to draw into a frame that
        # was only ever resized further down, in the game path, so resizing the
        # window at the title screen left the menu rendered for the old size —
        # PLAY ended up drawn outside the visible area.
        screen_w, screen_h = screen.get_size()
        if frame.get_size() != (screen_w, screen_h):
            frame = pygame.Surface((screen_w, screen_h), depth=24)

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
        city_rect, chart_rect, readout_rect, hud_h = compute_layout(screen_w, screen_h)
        hud_panels = hud_panel_rects(screen_w, screen_h)
        speed_control.pos = (hud_panels["left"].left + 10,
                             hud_panels["left"].top + 60)
        demand_chart.rect = chart_rect
        city.prepare(city_rect, state)
        terrain3d_surface = None
        if TERRAIN3D_ENABLED:
            if city.layout_key != terrain3d_key:
                terrain3d.upload_instances(gl_ctx, terrain3d_meshes,
                                            terrain3d.build_instances(city.tiles))
                # Release the OLD billboard meshes' GL resources before
                # replacing the list -- GLMesh holds a VBO/IBO/instance
                # VBO/VAO/texture per plant, and layout_key can change many
                # times per second during a window resize (same pattern as
                # the FBO release a few lines below), so skipping this leaks
                # N GL resource sets per change.
                for old_mesh in terrain3d_plant_meshes:
                    old_mesh.release()
                terrain3d_plant_meshes = terrain3d.load_billboards(
                    gl_ctx, terrain3d_prog, terrain3d.build_plant_billboards(city.plants))
                terrain3d_key = city.layout_key
            if terrain3d_fbo is None or terrain3d_fbo.size != city_rect.size:
                if terrain3d_fbo is not None:
                    # Framebuffer.release() does not release its attachments;
                    # do that explicitly or every resize leaks a texture and
                    # a depth renderbuffer.
                    terrain3d_fbo.color_attachments[0].release()
                    terrain3d_fbo.depth_attachment.release()
                    terrain3d_fbo.release()
                terrain3d_fbo = terrain3d.create_framebuffer(gl_ctx, city_rect.size)
            terrain3d.draw(gl_ctx, terrain3d_prog, terrain3d_meshes, terrain3d_fbo, city.camera,
                            billboard_meshes=terrain3d_plant_meshes)
            rgba, size = terrain3d.read_rgba(terrain3d_fbo)
            # Rendered here (right after city.prepare, off the pygame surface) but
            # blitted onto `frame` later, right before city.draw -- clear_frame(frame)
            # runs between here and there and would otherwise wipe this out.
            terrain3d_surface = terrain3d.to_surface(rgba, size)
        markers = city.plant_markers(city_rect)
        pin_obstacles = (chart_rect, readout_rect, hud_panels["outer"])
        pin_layout = plant_pins.layout(state.active_sources, markers,
                                       pin_obstacles, city_rect)
        pin_rects = [item["rect"] for item in pin_layout.values()]
        pins_rect = pin_rects[0].unionall(pin_rects[1:]) if pin_rects else None

        # Named screen regions: highlight targets for the tutorial, and the rects
        # overlays must not cover. Taken from the real layout so they stay correct
        # through a resize instead of being guessed.
        regions = {
            "supply_demand": hud_panels["center"],
            "hud_left": hud_panels["left"],
            "hud_right": hud_panels["right"],
            "pins": pins_rect,
            "city": city_rect,
            # The dialogue box may sit over the city — it's the backdrop — but
            # not over the readouts floating on it, so those are listed
            # separately for the placement logic to avoid.
            "chart": chart_rect,
            "readout": readout_rect,
            "speed_control": speed_control.bounds(),
        }
        regions.update({f"pin_{key}": item["rect"]
                        for key, item in pin_layout.items()})

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
        clear_frame(frame)
        # 1. The region owns every pixel, including those behind the HUD
        #    islands. Time and weather alter its materials; only clipped
        #    particles are drawn over it.
        environment = sample_atmosphere(
            state.sim_hour, state.active_event.kind if state.active_event else None)
        if terrain3d_surface is not None:
            frame.blit(terrain3d_surface, city_rect.topleft)
        city.draw(frame, city_rect, state, environment)
        atmosphere_layer.draw(frame, city_rect, environment, dt)

        # 2. inset cards and controls floating over the city
        demand_chart.draw(frame, state.sim_hour, state.sources, state.history,
                          state.demand_mw, state.demand_min_mw, state.demand_peak_mw)
        plant_pins.draw(frame, state.active_sources, city.plant_markers(city_rect),
                        pin_obstacles, city_rect, state.demand_level,
                        show_price=state.show_economics,
                        instructional=state.config.is_instructional)

        # 5. normal HUD
        hud.draw(frame, state, hud_panels)
        speed_control.draw(frame, state)
        hud.draw_audio_indicator(frame, audio,
                                 (hud_panels["left"].left + 10,
                                  speed_control.bounds().bottom + 6))

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
