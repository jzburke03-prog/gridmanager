"""Checks for the iso city view's illumination and layout model.

Run: python test_city_model.py
"""
import math
import os
import random
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

pygame.init()
pygame.display.set_mode((1, 1))     # sprite baking needs a video surface

from ui.iso_city import (AWAKE_MIN, FEEDER_SIZE, FIRE_FROM,
                         ILLUSTRATIVE_POPULATION, Camera, IsoCity,
                         PlantSite, TW, TH,
                         _Vehicle,
                         _fire_reach, _ignite_rate, _max_fires,
                         _draw_plant_live, _plant_static_sprite, _vehicle_sprite,
                         activity_level, lit_fraction, overload_level,
                         parabolic_peak, served_fraction, state_population,
                         traffic_level,
                         detail_levels_for_zoom, required_world_size,
                         vehicle_density_for_zoom, distribution_level)
from ui.iso_city import (street_route, cooling_tower_width, solar_panel_layout,
                         gas_cc_train_layout, centered_ellipse_rect,
                         solar_lot_polygon)
from ui.grid_flow import Flow
from ui.time_of_day import daylight
from ui.plant_pins import PIN_W, PlantPins
from ui.atmosphere import AtmosphereLayer, sample_atmosphere
from ui.hud import HUD, hud_hit_test, hud_panel_rects
from game_state import GameState
from sources.base_source import SourceStatus
import scenarios
from main import (BG_COLOR, cancel_map_interaction, clear_frame,
                  compute_layout)

RECT = pygame.Rect(0, 0, 1400, 410)


def _font(size):
    return pygame.font.Font(
        pygame.font.match_font("menlo,consolas,couriernew,monospace"), size)


def _pin_source(key):
    names = {"gas": "Gas (CC)", "nuclear": "Nuclear", "wind": "Wind"}
    capacities = {"gas": 750.0, "nuclear": 150.0, "wind": 225.0}
    source = SimpleNamespace(
        key=key,
        name=names[key],
        color=(90, 180, 220),
        requested_pct=0.5,
        actual_pct=0.5,
        current_output_mw=capacities[key] * 0.5,
        max_output_mw=capacities[key],
        status=SourceStatus.ONLINE,
        time_to_target=lambda: 0.0,
        price_at=lambda _demand: 42.0,
    )
    source.set_handle = lambda value: setattr(source, "requested_pct", value)
    return source


def test_region_world_size_covers_minimum_zoom_with_overscan():
    for viewport in (pygame.Rect(0, 0, 1000, 460),
                     pygame.Rect(0, 0, 1400, 680),
                     pygame.Rect(0, 0, 1800, 500)):
        width, height = required_world_size(viewport)
        assert width >= viewport.width + 100
        assert height >= viewport.height + 50

        world = pygame.Rect(0, 0, width, height)
        camera = Camera(world.center, zoom=1)
        camera.clamp(viewport, world)
        visible = camera.visible_world_rect(viewport)
        assert visible.size == viewport.size
        assert world.contains(visible)


def test_hud_is_one_centered_panel_with_three_contiguous_zones():
    layout = hud_panel_rects(1400, 900)
    outer = layout["outer"]
    left, center, right = (layout[k] for k in ("left", "center", "right"))
    assert outer.centerx == 700
    assert outer.height == 150
    assert left.left == outer.left
    assert left.right == center.left
    assert center.right == right.left
    assert right.right == outer.right
    assert outer.contains(left) and outer.contains(center) and outer.contains(right)
    assert hud_hit_test(layout, (left.right, outer.centery))


def test_hud_draws_panel_across_the_old_gaps():
    width, height = 1000, 680
    layout = hud_panel_rects(width, height)
    hud = HUD(pygame.font.Font(None, 16), pygame.font.Font(None, 13),
              pygame.font.Font(None, 24), pygame.font.Font(None, 40))
    state = GameState(scenarios.make_standard())
    state.flash_messages.clear()
    frame = pygame.Surface((width, height), depth=24)
    world = (71, 109, 63)
    frame.fill(world)
    hud.draw(frame, state, layout)
    seam = (layout["left"].right, layout["outer"].top + 8)
    assert frame.get_at(seam)[:3] != world


def test_zoom_levels_reveal_additive_detail():
    assert detail_levels_for_zoom(1) == ("regional",)
    assert detail_levels_for_zoom(2) == ("regional", "gameplay")
    assert detail_levels_for_zoom(4) == ("regional", "gameplay", "inspection")


def test_zoom_changes_reuse_the_same_semantic_layout_and_detail_cache():
    viewport = pygame.Rect(0, 0, 1000, 460)
    state = SimpleNamespace(population=None, sources=[])
    city = IsoCity(None)
    city.prepare(viewport, state)
    original = (id(city._base_day),
                tuple((name, id(layer)) for name, layer in city._detail_day.items()),
                id(city._tiles))

    for zoom in (1, 2, 4):
        city.camera.set_zoom(zoom, viewport.center, viewport, city._world_rect)
        city.prepare(viewport, state)
        assert (id(city._base_day),
                tuple((name, id(layer)) for name, layer in city._detail_day.items()),
                id(city._tiles)) == original
    assert tuple(city._detail_day) == ("gameplay", "inspection")


def test_vehicle_family_has_readable_local_sprites():
    for kind in ("car", "van", "bus", "truck", "service"):
        sprite = _vehicle_sprite(kind, (92, 132, 184), 1, False)
        bounds = sprite.get_bounding_rect()
        assert bounds.width >= 4 and bounds.height >= 3
        assert sprite.get_rect().contains(bounds)
    assert (vehicle_density_for_zoom(1) < vehicle_density_for_zoom(2)
            < vehicle_density_for_zoom(4))


def test_baked_region_covers_the_full_stage_at_one_x():
    viewport = pygame.Rect(0, 0, 1000, 460)
    state = SimpleNamespace(population=None, sources=[])
    city = IsoCity(None)
    city.prepare(viewport, state)

    assert city._world_rect.size == required_world_size(viewport)
    city.camera.zoom = 1
    city._composite.fill((31, 79, 41, 255))
    frame = pygame.Surface(viewport.size, pygame.SRCALPHA)
    sentinel = (255, 0, 255, 255)
    frame.fill(sentinel)
    city._present(frame, viewport)

    for point in ((0, 0), (viewport.right - 1, 0),
                  (0, viewport.bottom - 1),
                  (viewport.right - 1, viewport.bottom - 1)):
        assert frame.get_at(point) != sentinel


def test_atmosphere_is_stable_and_describes_world_response():
    rain = sample_atmosphere(14.0, "RAIN")
    assert rain == sample_atmosphere(14.0, "RAIN")
    assert rain.precipitation == "rain"
    assert rain.wetness > 0.0
    assert rain.snow_cover == 0.0
    assert rain.cloud_shadow > 0.0

    snow = sample_atmosphere(3.0, "SNOW")
    assert snow.precipitation == "snow"
    assert snow.snow_cover > 0.0
    assert snow.world_tint != sample_atmosphere(14.0, None).world_tint

    wind = sample_atmosphere(14.0, "WIND_GUST")
    assert -1.0 <= wind.wind[0] <= 1.0
    assert -1.0 <= wind.wind[1] <= 1.0
    assert not hasattr(rain, "gradient")


def test_atmosphere_effects_are_clipped_to_the_world_stage():
    frame = pygame.Surface((200, 120), pygame.SRCALPHA)
    untouched = (17, 23, 31, 255)
    frame.fill(untouched)
    stage = pygame.Rect(40, 30, 120, 70)
    layer = AtmosphereLayer(seed=9)
    layer.draw(frame, stage, sample_atmosphere(14.0, "ICE_STORM"), 1 / 60.0)

    for point in ((0, 0), (199, 0), (0, 119), (199, 119), (20, 60), (180, 60)):
        assert frame.get_at(point) == untouched
    assert frame.get_at(stage.center) != untouched


def test_camera_round_trip_zoom_anchor_and_clamp():
    viewport = pygame.Rect(100, 50, 800, 400)
    world = pygame.Rect(0, 0, 1200, 700)
    camera = Camera(world.center, zoom=2)

    for zoom in (1, 2, 4):
        camera.set_zoom(zoom, viewport.center, viewport, world)
        point = (731.25, 412.5)
        screen = camera.world_to_screen(point, viewport)
        restored = camera.screen_to_world(screen, viewport)
        assert abs(restored[0] - point[0]) < 1e-6
        assert abs(restored[1] - point[1]) < 1e-6

    cursor = (260, 170)
    camera.set_zoom(2, viewport.center, viewport, world)
    before = camera.screen_to_world(cursor, viewport)
    camera.set_zoom(4, cursor, viewport, world)
    after = camera.screen_to_world(cursor, viewport)
    assert abs(after[0] - before[0]) < 1e-6
    assert abs(after[1] - before[1]) < 1e-6

    camera.center = [-9999.0, 9999.0]
    camera.clamp(viewport, world)
    visible = camera.visible_world_rect(viewport)
    assert visible.left >= world.left and visible.right <= world.right
    assert visible.top >= world.top and visible.bottom <= world.bottom


def test_plant_markers_follow_camera_and_stay_reachable():
    viewport = pygame.Rect(100, 50, 800, 400)
    city = IsoCity(None)
    city._world_rect = pygame.Rect(0, 0, 600, 350)
    city.camera = Camera(city._world_rect.center, zoom=4)
    city._plants = [SimpleNamespace(key="gas", sx=0, sy=0),
                    SimpleNamespace(key="solar", sx=599, sy=349)]

    markers = city.plant_markers(viewport)
    assert set(markers) == {"gas", "solar"}
    for marker in markers.values():
        assert viewport.left <= marker["anchor"][0] <= viewport.right
        assert viewport.top <= marker["anchor"][1] <= viewport.bottom
        assert set(marker) == {"target", "anchor", "visible"}


def test_plant_static_surfaces_are_local_not_world_sized():
    for key in ("nuclear", "coal", "gas", "peaker", "solar", "wind",
                "hydro", "generic"):
        sprite, offset = _plant_static_sprite(key, random.Random(1))
        assert sprite.get_bounding_rect().size == sprite.get_size()
        assert sprite.get_width() < 220 and sprite.get_height() < 170
        assert offset[0] <= 0 or offset[1] <= 0


def test_baked_plant_art_stays_inside_world_and_pins_use_visual_centres():
    viewport = pygame.Rect(0, 0, 1000, 460)
    city = IsoCity(None)
    city._bake(viewport, 100_000,
               ("nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro"))
    solar = next(site for site in city._plants if site.key == "solar")

    for site in city._plants:
        sprite = site.sprite
        offset = site.sprite_offset
        bounds = pygame.Rect(site.sx + city._origin[0] + offset[0],
                             site.sy + city._origin[1] + offset[1],
                             sprite.get_width(), sprite.get_height())
        assert city._world_rect.contains(bounds)

    expected_world_x = solar.sx + city._origin[0] + solar.visual_dx
    expected_world_y = solar.sy + city._origin[1] + solar.visual_dy
    target = city.plant_markers(viewport)["solar"]["target"]
    expected_screen_x = city.camera.world_to_screen(
        (expected_world_x, solar.sy + city._origin[1]), viewport)[0]
    expected_screen_y = city.camera.world_to_screen(
        (expected_world_x, expected_world_y), viewport)[1]
    assert abs(target[0] - expected_screen_x) <= 1
    assert abs(target[1] - expected_screen_y) <= 1


def test_zoomed_map_marks_fully_offscreen_plants_without_dropping_them():
    viewport = pygame.Rect(0, 0, 1000, 460)
    fleet = ("nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro")
    city = IsoCity(None)
    city._bake(viewport, 100_000, fleet)
    solar = next(site for site in city._plants if site.key == "solar")
    solar_world = (solar.sx + city._origin[0] + solar.visual_dx,
                   solar.sy + city._origin[1])
    city.camera.zoom = 4
    city.camera.center[:] = solar_world
    city.camera.clamp(viewport, city._world_rect)

    markers = city.plant_markers(viewport)
    assert set(markers) == set(fleet)
    assert {key for key, marker in markers.items() if marker["visible"]} == {
        "peaker", "solar"}


def test_every_plant_has_a_decorative_switchyard_anchor_only():
    for key in ("nuclear", "coal", "gas", "peaker", "solar", "wind",
                "hydro", "generic"):
        site = PlantSite(key, 0, 0, 100, 80, 0.0)
        anchor = site.switchyard_anchor()
        assert anchor != (site.sx, site.sy)
        assert not hasattr(site, "capacity")
        assert not hasattr(site, "requested_pct")
        assert not hasattr(site, "click_target")


def test_distribution_graph_connects_every_building_cluster():
    viewport = pygame.Rect(0, 0, 1000, 460)
    fleet = ("nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro")
    city = IsoCity(None)
    city._bake(viewport, 100_000, fleet)

    assert city._transformers
    assert len(city._distribution_flows) == len(city._transformers)
    assert city._service_flows
    assigned = {building for transformer in city._transformers
                for building in transformer.buildings}
    assert assigned == {(col, row) for col, row, _kind, _e in city._buildings}
    assert all(transformer.sub_index in city._subs_used
               for transformer in city._transformers)

    routes = {key: path[0] for key, _i, path in city._routes}
    ox, oy = city._origin
    for site in city._plants:
        sx, sy = site.switchyard_anchor()
        assert routes[site.key] == (sx + ox, sy + oy)
    for _key, _i, path in city._routes:
        assert len(path) >= 3
        for a, b in zip(path[1:-2], path[2:-1]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            assert dx and abs(abs(dy / dx) - TH / TW) < 1e-6


def test_distribution_flow_respects_upstream_power_and_shedding():
    assert distribution_level(0.2, 0.5, 0.8) == 0.8
    assert distribution_level(0.7, 0.5, 0.8) == 0.0
    assert distribution_level(0.2, 0.5, 0.0) == 0.0

    surface = pygame.Surface((120, 20), pygame.SRCALPHA)
    offline = Flow([(0, 10), (100, 10)], seed=1)
    for _ in range(120):
        offline.update_and_draw(surface, 0.0, 1 / 60.0)
    assert not offline.pulses
    online = Flow([(0, 10), (100, 10)], seed=1)
    for _ in range(120):
        online.update_and_draw(surface, 1.0, 1 / 60.0)
    assert online.pulses or online.flashes


def test_distribution_routes_follow_isometric_street_axes():
    path = street_route((1, 2), (9, 11), (100, 80), (220, 150), (0, 0))
    assert path[0] == (100, 80)
    assert path[-1] == (220, 150)
    assert len(path) >= 5
    for a, b in zip(path[1:-2], path[2:-1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        assert dx != 0
        assert abs(abs(dy / dx) - TH / TW) < 1e-6


def test_cooling_tower_profile_is_flared_and_pinched():
    base = cooling_tower_width(0.0)
    waist = cooling_tower_width(0.58)
    rim = cooling_tower_width(1.0)
    assert base > rim > waist
    assert cooling_tower_width(0.25) > waist
    assert cooling_tower_width(0.82) > waist


def test_cooling_tower_rim_rect_is_pixel_centered():
    for radius in (7.2, 9.8, 11.4):
        rect = centered_ellipse_rect(60, 40, radius, radius * 0.42)
        assert rect.centerx == 60
        assert rect.width % 2 == 1


def test_nuclear_live_beacon_uses_baked_tower_pixel_x():
    site = PlantSite("nuclear", 0, 0, 270.6, 100, 0.0)
    layer = pygame.Surface((400, 200), pygame.SRCALPHA)
    _draw_plant_live(layer, site, 0.0, 0.0, True)
    baked_tower_x = int(site.sx + 2)  # Pygame truncates the baked sprite blit.
    assert layer.get_at((baked_tower_x, 84))[:3] == (236, 70, 58)


def test_solar_lot_has_four_preserved_corners():
    points = solar_lot_polygon(120, 90)
    assert len(points) == 4
    sprite, offset = _plant_static_sprite("solar", random.Random(7))
    for x, y in points:
        local = (x - 120 - offset[0], y - 90 - offset[1])
        area = pygame.Rect(local[0] - 1, local[1] - 1, 3, 3).clip(sprite.get_rect())
        assert area.width and area.height
        assert sprite.subsurface(area).get_bounding_rect().width > 0


def test_gas_plant_has_no_yellow_pavement_artifact():
    sprite, _offset = _plant_static_sprite("gas", random.Random(7))
    artifact = (206, 170, 74)
    assert all(sprite.get_at((x, y))[:3] != artifact
               for y in range(sprite.get_height())
               for x in range(sprite.get_width()))


def test_solar_campus_uses_separate_panel_blocks_and_service_lanes():
    tables = solar_panel_layout()
    assert len(tables) == 36
    assert {group for group, _x, _y in tables} == {0, 1, 2, 3}
    for group in range(4):
        positions = [(x, y) for g, x, y in tables if g == group]
        assert len(positions) == 9
        assert len(set(positions)) == 9


def test_combined_cycle_campus_is_two_complete_parallel_trains():
    trains = gas_cc_train_layout()
    assert len(trains) == 2
    assert trains[0][0][1] != trains[1][0][1]
    for turbine, recovery, stack in trains:
        assert turbine[1] == recovery[1]
        assert stack[1] == recovery[1] + 1
        assert turbine[0] < recovery[0] < stack[0]


def test_pin_layout_avoids_overlays_and_drags_without_a_prior_draw():
    class Source:
        key = "gas"

        def __init__(self):
            self.requested_pct = 0.0

        def set_handle(self, value):
            self.requested_pct = value

    viewport = pygame.Rect(0, 0, 800, 500)
    obstacle = pygame.Rect(0, 300, 300, 180)
    markers = {
        "gas": {"target": (120, 400), "anchor": (120, 400), "visible": True},
        "coal": {"target": (120, 400), "anchor": (120, 400), "visible": True},
    }
    sources = [Source(), SimpleNamespace(key="coal")]
    pins = PlantPins(None, None, None)

    layout = pins.layout(sources, markers, [obstacle], viewport)
    gas, coal = layout["gas"]["rect"], layout["coal"]["rect"]
    assert viewport.contains(gas) and viewport.contains(coal)
    assert not gas.colliderect(obstacle) and not coal.colliderect(obstacle)
    assert not gas.colliderect(coal)

    dial = layout["gas"]["dial_center"]
    assert pins.handle_mouse_down((dial[0], dial[1] - 20), [sources[0]],
                                  markers, [obstacle], viewport) == ("dial", "gas")
    assert 0.45 < sources[0].requested_pct < 0.55


def test_full_plant_card_fits_longest_mw_line():
    font = pygame.font.Font(pygame.font.match_font("menlo,monospace"), 13)
    assert font.size("450/750 MW")[0] <= PIN_W - 78


def test_offscreen_plants_become_directional_edge_tabs():
    pins = PlantPins(_font(16), _font(13), _font(16))
    viewport = pygame.Rect(0, 0, 800, 500)
    source = _pin_source("gas")
    markers = {"gas": {"target": (1100, 260), "anchor": (774, 260),
                       "visible": False}}
    item = pins.layout([source], markers, (), viewport)["gas"]
    assert item["kind"] == "tab"
    assert item["edge"] == "right"
    assert viewport.contains(item["rect"])
    assert item["direction"][0] > 0


def test_edge_tab_draws_chevron_inward_from_viewport_edge():
    pins = PlantPins(_font(16), _font(13), _font(16))
    viewport = pygame.Rect(0, 0, 800, 500)
    source = _pin_source("gas")
    markers = {"gas": {"target": (1100, 260), "anchor": (774, 260),
                       "visible": False}}
    surface = pygame.Surface(viewport.size, pygame.SRCALPHA)
    item = pins.draw(surface, [source], markers, (), viewport)["gas"]
    assert surface.get_at((item["rect"].left - 5, item["rect"].centery)).a > 0


def test_edge_tab_text_does_not_overlap_at_actual_font():
    class RecordingSurface(pygame.Surface):
        def __init__(self, size):
            super().__init__(size, pygame.SRCALPHA)
            self.blit_rects = []

        def blit(self, source, dest, *args, **kwargs):
            topleft = dest.topleft if isinstance(dest, pygame.Rect) else dest
            self.blit_rects.append(source.get_rect(topleft=topleft))
            return super().blit(source, dest, *args, **kwargs)

    pins = PlantPins(_font(16), _font(13), _font(16))
    viewport = pygame.Rect(0, 0, 800, 500)
    source = _pin_source("nuclear")
    source.current_output_mw = 150.0
    markers = {"nuclear": {"target": (1100, 260), "anchor": (774, 260),
                           "visible": False}}
    surface = RecordingSurface(viewport.size)
    pins.draw(surface, [source], markers, (), viewport)
    name_rect, output_rect = surface.blit_rects[-2:]
    assert name_rect.right + 4 <= output_rect.left


def test_edge_tab_click_requests_camera_focus():
    pins = PlantPins(_font(16), _font(13), _font(16))
    viewport = pygame.Rect(0, 0, 800, 500)
    source = _pin_source("gas")
    markers = {"gas": {"target": (1100, 260), "anchor": (774, 260),
                       "visible": False}}
    item = pins.layout([source], markers, (), viewport)["gas"]
    assert pins.handle_mouse_down(
        item["rect"].center, [source], markers, (), viewport) == ("focus", "gas")


def test_visible_card_draw_has_chevron_and_no_leader_line():
    pins = PlantPins(_font(16), _font(13), _font(16))
    viewport = pygame.Rect(0, 0, 800, 500)
    source = _pin_source("wind")
    markers = {"wind": {"target": (400, 350), "anchor": (400, 350),
                        "visible": True}}
    surface = pygame.Surface(viewport.size, pygame.SRCALPHA)
    layout = pins.draw(surface, [source], markers, (), viewport)
    card = layout["wind"]["rect"]
    assert surface.get_at((card.centerx, card.bottom + 10)).a == 0
    assert surface.get_at((card.centerx, card.bottom + 5)).a > 0


def test_focus_plant_centers_camera_on_plant():
    city = _city(200_000)
    viewport = pygame.Rect(0, 0, 1000, 680)
    assert city.focus_plant("gas", viewport)
    site = next(site for site in city._plants if site.key == "gas")
    expected = (site.sx + city._origin[0], site.sy + city._origin[1])
    assert tuple(city.camera.center) == expected


def test_all_plant_pins_stay_reachable_at_every_zoom_and_viewport():
    keys = ("nuclear", "coal", "gas", "peaker", "solar", "wind", "hydro")
    sources = [SimpleNamespace(key=key) for key in keys]
    pins = PlantPins(None, None, None)
    for size in ((1000, 460), (1400, 680), (1800, 500)):
        viewport = pygame.Rect((0, 0), size)
        obstacles = (pygame.Rect(18, viewport.bottom - 170, 300, 150),
                     pygame.Rect(viewport.right - 318, viewport.bottom - 170, 300, 150))
        world = pygame.Rect(0, 0, *required_world_size(viewport))
        city = IsoCity(None)
        city._world_rect = world
        city._origin = world.center
        city._plants = [PlantSite(key, 0, 0,
                                  -world.width // 2 + i * world.width / 6,
                                  (-1 if i % 2 else 1) * world.height,
                                  0.0)
                        for i, key in enumerate(keys)]
        city.camera = Camera(world.center, zoom=1)
        for zoom in (1, 2, 4):
            city.camera.set_zoom(zoom, viewport.center, viewport, world)
            layout = pins.layout(sources, city.plant_markers(viewport),
                                 obstacles, viewport)
            rects = [item["rect"] for item in layout.values()]
            assert len(rects) == len(keys)
            assert all(viewport.contains(rect) for rect in rects)
            assert all(not rect.collidelist(obstacles) >= 0 for rect in rects)
            for i, rect in enumerate(rects):
                assert all(not rect.colliderect(other) for other in rects[i + 1:])


def test_leaving_game_cancels_map_drag_state():
    pins = PlantPins(None, None, None)
    pins.dragging_key = "gas"
    city_dragging = cancel_map_interaction(pins)
    assert pins.dragging_key is None
    assert city_dragging is False


def test_each_render_starts_from_a_clean_neutral_frame():
    frame = pygame.Surface((40, 30))
    frame.fill((255, 0, 255))
    clear_frame(frame)
    assert frame.get_at((20, 15))[:3] == BG_COLOR


def _city(population):
    city = IsoCity(None)
    city._layout(RECT, population, ("gas",))
    city._world_rect = pygame.Rect(0, 0, RECT.width, 680)
    city._origin = (RECT.width // 2, int(RECT.height * 0.56))
    city.camera = Camera(RECT.center)
    return city


def test_freeplay_city_size_is_decoupled_from_grid_megawatts():
    class State:
        population = None

        def __init__(self, peak):
            self.demand_peak_mw = peak

    assert state_population(State(100.0)) == ILLUSTRATIVE_POPULATION
    assert state_population(State(50_000.0)) == ILLUSTRATIVE_POPULATION

    career = State(100.0)
    career.population = 42_000
    assert state_population(career) == 42_000


def test_lit_fraction():
    # Perfect supply at the trough still leaves most of the city dark: 4 AM has
    # to read as 4 AM, not as a failure.
    assert lit_fraction(0.0, 1.0) == AWAKE_MIN
    # Perfect supply at peak lights everything.
    assert lit_fraction(1.0, 1.0) == 1.0
    # No supply is a blackout at any hour.
    assert lit_fraction(0.0, 0.0) == 0.0
    assert lit_fraction(1.0, 0.0) == 0.0

    # The core asymmetry: the SAME deficit darkens far less of the city at the
    # trough than at the peak. This is the whole lesson of the visualization.
    trough_loss = lit_fraction(0.0, 1.0) - lit_fraction(0.0, 0.5)
    peak_loss = lit_fraction(1.0, 1.0) - lit_fraction(1.0, 0.5)
    assert peak_loss > trough_loss * 3

    # Oversupply must not light more than the whole city.
    assert lit_fraction(1.0, 2.5) == 1.0
    # Monotonic in both inputs.
    assert lit_fraction(0.3, 0.8) < lit_fraction(0.6, 0.8)
    assert lit_fraction(0.6, 0.4) < lit_fraction(0.6, 0.9)


def test_overload_level():
    # Balanced or short: the city is never on fire for being under-supplied.
    assert overload_level(1.0, 1.75) == 0.0
    assert overload_level(0.4, 1.75) == 0.0

    # 1.0 lands exactly on the meltdown line, whatever the difficulty, so the
    # visual peak and the run-ending condition always coincide.
    for meltdown in (1.15, 1.40, 1.75, 2.10):
        assert overload_level(meltdown, meltdown) == 1.0
        assert overload_level(meltdown + 0.5, meltdown) == 1.0  # clamped

    # Same supply ratio, different tiers -> different severity. A fixed 150%
    # threshold would be catastrophic on Easy and already too late on Expert.
    assert overload_level(1.5, 1.15) == 1.0
    assert overload_level(1.5, 2.10) < 0.5

    # Fires (over > FIRE_FROM, see _ignite_rate) begin near 150% on Moderate.
    assert 0.5 < overload_level(1.5, 1.75) < 0.8


def test_overload_escalation():
    """`over` alone saturates at the meltdown line, so it carries no information
    through the window where the player is about to lose — on Expert that line
    is 1.15 while fill_pct runs to 2.3. `crisis` (time spent past the line) is
    the second axis, and every escalation term must rise on BOTH.
    """
    # monotonic in over, at fixed crisis...
    for fn in (_ignite_rate, _max_fires, _fire_reach):
        assert fn(0.6, 0.0) <= fn(0.8, 0.0) <= fn(1.0, 0.0), fn.__name__
        # ...and in crisis, at fixed over — this is the part `over` alone lost
        assert fn(1.0, 0.0) < fn(1.0, 0.5) < fn(1.0, 1.0), fn.__name__

    # A grid inside its limits never burns, however long it has been there.
    assert _ignite_rate(0.0, 0.0) == 0.0
    assert _ignite_rate(FIRE_FROM, 0.0) == 0.0

    # Fires start as a downtown problem and end as a city-wide one, but the
    # reach is a fraction of the building list, so it can never exceed all of it.
    assert _fire_reach(FIRE_FROM, 0.0) < 0.6
    assert _fire_reach(1.0, 1.0) <= 1.0
    for o in (0.0, 0.5, 1.0):
        for c in (0.0, 0.5, 1.0):
            assert 0.0 < _fire_reach(o, c) <= 1.0


def test_traffic_has_smooth_parabolic_rush_hour_peaks():
    assert traffic_level(9.0) > traffic_level(12.0) > traffic_level(3.0)
    assert traffic_level(17.0) > traffic_level(12.0)
    assert traffic_level(8.0) < traffic_level(9.0) > traffic_level(10.0)
    assert traffic_level(16.0) < traffic_level(17.0) > traffic_level(18.0)
    for center in (9.0, 17.0):
        assert abs(traffic_level(center - 0.1) -
                   traffic_level(center + 0.1)) < 0.04


def test_parabolic_peak_falls_smoothly_to_zero_at_its_edges():
    assert parabolic_peak(9.0, 9.0, 1.5) == 1.0
    assert parabolic_peak(9.75, 9.0, 1.5) == 0.75
    assert parabolic_peak(10.5, 9.0, 1.5) == 0.0


def test_priority_actually_lights_that_fraction():
    """`priority < served` is only meaningful if it really lights that share of
    the city, so priority has to be rank-normalised. The raw score is heavily
    clustered, and without ranking a nominal 15% lit came out around 1% and the
    04:00 city was black."""
    city = _city(200_000)
    pri = list(city._priority.values())
    n = len(pri)
    assert n > 300, f"expected a real city, got {n} lightable things"
    for frac in (0.15, 0.25, 0.5, 0.75, 1.0):
        lit = sum(1 for p in pri if p < frac)
        assert abs(lit / n - frac) < 0.02, f"{frac}: lit {lit}/{n}"


def test_shedding_is_patchy_not_a_bullseye():
    """Utilities drop feeder circuits, not concentric rings. A half-supplied
    city must therefore be patchy — dark blocks scattered right across the map
    — rather than a shrinking disc around downtown."""
    city = _city(200_000)
    served = 0.5
    items = [(c, r, p) for (c, r), p in city._priority.items()]
    kept = [(c, r) for c, r, p in items if p < served]
    shed = [(c, r) for c, r, p in items if p >= served]
    assert kept and shed

    def dist(cr):
        u, v = cr[0] - cr[1], cr[0] + cr[1]
        return math.hypot(u / city._u_max, v / city._v_max)

    # Interleaving: a purely radial shed would put EVERY shed block outside
    # every kept block. Plenty of shed blocks must sit nearer the centre than
    # the typical surviving one.
    kept_d = sorted(map(dist, kept))
    median_kept = kept_d[len(kept_d) // 2]
    inner_shed = sum(1 for s in shed if dist(s) < median_kept)
    assert inner_shed / len(shed) > 0.15, (
        f"only {inner_shed}/{len(shed)} shed blocks are inside the kept median "
        "— shedding has collapsed into a bullseye")

    # Outages arrive in PATCHES, not per-building noise: two blocks on the same
    # feeder should usually share a fate. Independent coin-flips would agree
    # about half the time.
    state = {(c, r): p < served for c, r, p in items}
    feeders = {}
    for (c, r), on in state.items():
        feeders.setdefault((c // FEEDER_SIZE, r // FEEDER_SIZE), []).append(on)
    pairs = agree = 0
    for group in feeders.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                pairs += 1
                agree += group[i] == group[j]
    assert pairs > 100
    assert agree / pairs > 0.75, (
        f"same-feeder blocks agree only {agree/pairs:.0%} of the time — "
        "outages are not clustering into circuits")


def test_shedding_still_protects_the_core():
    """Patchy does not mean unbiased: downtown circuits carry hospitals and
    signals, and are shed last."""
    city = _city(200_000)
    served = 0.5

    def dist(cr):
        u, v = cr[0] - cr[1], cr[0] + cr[1]
        return math.hypot(u / city._u_max, v / city._v_max)

    kept = [cr for cr, p in city._priority.items() if p < served]
    shed = [cr for cr, p in city._priority.items() if p >= served]
    assert (sum(map(dist, kept)) / len(kept)
            < sum(map(dist, shed)) / len(shed))


def test_road_graph_contains_only_adjacent_road_tiles():
    city = _city(200_000)
    assert city._road_neighbors
    for tile, neighbors in city._road_neighbors.items():
        assert city._tiles[tile][0] == "road"
        for neighbor in neighbors:
            assert city._tiles[neighbor][0] == "road"
            assert abs(tile[0] - neighbor[0]) + abs(tile[1] - neighbor[1]) == 1


def test_vehicle_turns_without_immediate_uturn_when_exit_exists():
    neighbors = {(0, 0): ((1, 0),),
                 (1, 0): ((0, 0), (2, 0), (1, 1)),
                 (2, 0): ((1, 0),),
                 (1, 1): ((1, 0),)}
    vehicle = _Vehicle((0, 0), (1, 0), random.Random(4))
    vehicle.progress = 0.99
    vehicle.advance(1.0, neighbors, random.Random(4))
    assert vehicle.previous_tile == (1, 0)
    assert vehicle.next_tile in ((2, 0), (1, 1))


def test_vehicle_population_is_intentionally_sparse():
    city = _city(200_000)
    assert 50 <= len(city._vehicles) <= 110
    assert vehicle_density_for_zoom(4) < 0.8


def test_buildings_occlude_traffic():
    """Vehicles draw in the overlay, above the baked city, so anything behind a
    building has to be culled or it drives through the wall. Only the three
    tiles nearer the camera can occlude a given tile."""
    city = _city(200_000)
    roads = [cr for cr, t in city._tiles.items() if t[0] == "road"]
    assert any(city._occluded(*cr) for cr in roads), "nothing is ever occluded"
    assert not all(city._occluded(*cr) for cr in roads), "everything is occluded"
    # a tile with a building on its camera-side neighbour must be occluded
    for (col, row), t in city._tiles.items():
        if t[0] == "bldg":
            assert city._occluded(col - 1, row - 1)
            break


def test_city_size_tracks_population():
    """The view is only an instrument if the town's size means something. City
    radius must rise with every population step — a career town that visibly
    shrinks while it grows would discredit the whole readout."""
    pops = [4_300, 9_890, 17_200, 25_800, 38_700, 49_880,
            86_000, 129_000, 193_500, 249_830, 344_000, 430_000]
    extents, counts = [], []
    for p in pops:
        city = _city(p)
        extents.append(city._extent)
        counts.append(len(city._buildings))
    for a, b, pa, pb in zip(extents, extents[1:], pops, pops[1:]):
        assert b > a, f"{pa} -> {pb}: city shrank ({a:.3f} -> {b:.3f})"
    for a, b in zip(counts, counts[1:]):
        assert b > a, f"building count went backwards: {a} -> {b}"
    # And the whole range has to fit the viewport with countryside left over.
    assert extents[-1] < 0.95


def test_time_of_day_never_strands_outlying_districts():
    """Brightness (time of day) and reach (supply) are separate inputs. When
    they were multiplied into one number, an outlying district sat at high
    priority and stayed completely dark at 04:00 even on a perfectly supplied
    grid — a district that exists does not stop existing because it is late."""
    assert served_fraction(1.0) == 1.0
    city = _city(200_000)
    assert all(p < served_fraction(1.0) for p in city._priority.values())

    # ...and still carries light at the trough, just less of it.
    assert activity_level(0.0) > 0.0
    assert activity_level(0.0) < activity_level(0.5) < activity_level(1.0)


def test_daylight():
    # Sun elevation, shared with the sky so the two can't disagree.
    assert daylight(3.0) == 0.0      # night
    assert daylight(22.0) == 0.0
    assert daylight(12.0) > 0.85     # near solar noon
    assert daylight(3.0) < daylight(8.0) < daylight(12.0)
    # Dawn is a bright warm sky but the sun is barely up: colour luminance would
    # read 05:00 as nearly midday, sun position correctly reads it as ~zero.
    assert daylight(5.0) < 0.05


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall city model checks passed")
