# UI and Traffic Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the eight reported map/UI defects, replace chaotic traffic with sparse routed traffic and rush-hour peaks, and make city overload damage scale from 101% to 200% supply.

**Architecture:** Keep the existing Pygame renderer and its baked static layers. Extend `IsoCity` with camera-aware plant markers and a small road graph, let `PlantPins` render either full controls or edge tabs from those markers, and replace the three HUD surfaces with one outer surface containing three zones. Visual overload severity is derived from the live supply/demand ratio and remains separate from difficulty and loss mechanics.

**Tech Stack:** Python 3.9, Pygame 2.6, the existing script-style test suites, and the existing headless capture harness.

## Global Constraints

- Do not add dependencies or raster assets.
- Do not change plant capacities, prices, ramp rates, demand simulation, difficulty loss thresholds, or switchyard gameplay.
- Preserve the supported 1000x680 minimum viewport and zoom levels 1x, 2x, and 4x.
- Keep full-screen pulse timing slow and photosensitivity-conscious; severity may change amplitude and local effect count, not whole-screen flash frequency.
- Use test-first red/green cycles for every behavioral change.
- Do not pull, merge, push, or open a pull request during implementation without a separate user request.

---

### Task 1: Unified HUD panel

**Files:**
- Modify: `energy_grid_game/ui/hud.py:20-130`
- Modify: `energy_grid_game/main.py:35-50, 315-335, 400-420`
- Modify: `energy_grid_game/test_city_model.py:50-105`
- Modify: `tools/capture_moments.py:55-130`

**Interfaces:**
- Produces: `hud_panel_rects(width: int, height: int) -> dict[str, pygame.Rect]` containing `outer`, `left`, `center`, and `right`.
- Produces: `hud_hit_test(layout: dict, pos: tuple[int, int]) -> bool`, testing `layout["outer"]` only.
- Consumers use `outer` as the single plant-card obstacle and retain the three inner zones for content placement and tutorial highlights.

- [ ] **Step 1: Replace the separated-island expectations with a failing unified-panel test**

```python
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
```

- [ ] **Step 2: Run the city-model suite and verify the new test fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_city_model.py`

Expected: failure because `outer` does not exist and the old 24-pixel gaps still show the world.

- [ ] **Step 3: Implement one outer panel and contiguous content zones**

```python
PANEL_TOP = 14
HUD_W = 900
LEFT_W = 300
CENTER_W = 400
RIGHT_W = 200
PANEL_H = 150


def hud_panel_rects(width, height):
    outer = pygame.Rect((width - HUD_W) // 2, PANEL_TOP, HUD_W, PANEL_H)
    left = pygame.Rect(outer.left, outer.top, LEFT_W, PANEL_H)
    center = pygame.Rect(left.right, outer.top, CENTER_W, PANEL_H)
    right = pygame.Rect(center.right, outer.top, RIGHT_W, PANEL_H)
    return {"outer": outer, "left": left, "center": center, "right": right}


def hud_hit_test(layout, pos):
    return layout["outer"].collidepoint(pos)
```

In `HUD.draw`, blit `_glass_panel(outer.size)` once at `outer`, then draw one-pixel translucent dividers at `left.right` and `center.right`. In `main.py` and the capture harness, change plant obstacles from `*hud_panels.values()` to `hud_panels["outer"]`. Keep speed/audio coordinates relative to `left`.

- [ ] **Step 4: Run the city-model suite and verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_city_model.py`

Expected: all checks pass.

- [ ] **Step 5: Commit the unified HUD**

```bash
git add energy_grid_game/ui/hud.py energy_grid_game/main.py energy_grid_game/test_city_model.py tools/capture_moments.py
git commit -m "Unify the gameplay HUD"
```

---

### Task 2: Full plant cards, chevrons, and off-screen edge tabs

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py:1950-2010`
- Modify: `energy_grid_game/ui/plant_pins.py`
- Modify: `energy_grid_game/main.py:250-290, 320-415`
- Modify: `energy_grid_game/test_city_model.py:210-475`
- Modify: `tools/capture_moments.py:105-135, 250-290`

**Interfaces:**
- Produces: `IsoCity.plant_markers(rect) -> dict[str, dict]`; each marker contains `target`, `anchor`, and `visible`.
- Produces: `IsoCity.focus_plant(key: str, rect: pygame.Rect) -> bool`.
- Changes: `PlantPins.layout(sources, markers, obstacles, viewport) -> dict`; each item has `kind` equal to `card` or `tab`.
- Changes: `PlantPins.handle_mouse_down(...) -> tuple[str, str] | None`, returning `("dial", key)` or `("focus", key)`.

- [ ] **Step 1: Add failing tests for card fit, chevrons, edge tabs, and camera focus**

```python
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


def test_visible_card_draw_has_chevron_and_no_leader_line():
    pins = PlantPins(_font(16), _font(13), _font(16))
    viewport = pygame.Rect(0, 0, 800, 500)
    source = _pin_source("wind")
    markers = {"wind": {"target": (400, 350), "anchor": (400, 350),
                         "visible": True}}
    surface = pygame.Surface(viewport.size, pygame.SRCALPHA)
    layout = pins.draw(surface, [source], markers, (), viewport)
    card = layout["wind"]["rect"]
    assert surface.get_at(((card.centerx + 400) // 2,
                           (card.centery + 350) // 2)).a == 0
    assert surface.get_at((card.centerx, card.bottom + 5)).a > 0


def test_focus_plant_centers_camera_on_plant():
    city = _city(200_000)
    viewport = pygame.Rect(0, 0, 1000, 680)
    assert city.focus_plant("gas", viewport)
    site = next(site for site in city._plants if site.key == "gas")
    expected = (site.sx + city._origin[0], site.sy + city._origin[1])
    assert tuple(city.camera.center) == expected
```

Test helpers `_font` and `_pin_source` remain in the test file and return real Pygame fonts and a complete lightweight source object, not mocks of `PlantPins`.

- [ ] **Step 2: Run the city-model suite and verify the tests fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_city_model.py`

Expected: failures for the 148-pixel width, missing marker/tab APIs, current leader line, and missing camera-focus method.

- [ ] **Step 3: Implement camera-aware markers and camera focus**

Replace `plant_anchors` with `plant_markers`. Compute the unbounded `target` from the artwork's visual center, compute `visible` from the scaled artwork rectangle intersecting `rect.inflate(-72, -72)`, and clamp only `anchor` to the viewport margin. Do not drop off-screen plants.

```python
def focus_plant(self, key, rect):
    site = next((site for site in self._plants if site.key == key), None)
    if site is None or self.camera is None:
        return False
    self.camera.center[:] = [site.sx + self._origin[0],
                             site.sy + self._origin[1]]
    self.camera.clamp(rect, self._world_rect)
    return True
```

- [ ] **Step 4: Implement card and edge-tab layout**

Set `PIN_W = 168`, `PIN_H = 94`, `TAB_W = 116`, and `TAB_H = 28`. For visible markers, reuse the existing obstacle-aware candidates. For off-screen markers, project from `viewport.center` toward `target`, choose the first intersected edge, center the tab at that point, and slide it along that edge in `TAB_H + 6` steps until it avoids obstacles and prior tabs. Store the normalized target vector in `direction` and the chosen edge in `edge`.

Remove the loop that calls `pygame.draw.line`. Draw a five-pixel filled chevron under full cards and an inward-facing chevron on edge tabs. Apply `round(2 * math.sin(self._t * math.tau / 1.8))` only to the drawn card/tab and chevron, not to hit-test rectangles.

- [ ] **Step 5: Dispatch edge-tab clicks in the main loop**

```python
action = plant_pins.handle_mouse_down(
    event.pos, state.active_sources, markers, obstacles, city_rect)
if action:
    kind, key = action
    if kind == "focus":
        city.focus_plant(key, city_rect)
    audio.play("ui_click")
elif city_rect.collidepoint(event.pos) and not hud_hit_test(hud_panels, event.pos):
    city_dragging = True
```

Update mouse-motion, drawing, tutorial regions, and the capture harness to pass `plant_markers` consistently. Remove `strict_above_keys_for_zoom`; the visible/off-screen distinction supersedes the solar-only exception.

- [ ] **Step 6: Run the city-model suite and verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_city_model.py`

Expected: all checks pass.

- [ ] **Step 7: Commit plant controls and edge tabs**

```bash
git add energy_grid_game/ui/iso_city.py energy_grid_game/ui/plant_pins.py energy_grid_game/main.py energy_grid_game/test_city_model.py tools/capture_moments.py
git commit -m "Add directional plant cards and edge tabs"
```

---

### Task 3: Correct plant artwork geometry

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py:620-815, 900-1080`
- Modify: `energy_grid_game/test_city_model.py:340-390`

**Interfaces:**
- Produces: `centered_ellipse_rect(cx, cy, rx, ry) -> pygame.Rect`.
- Produces: `solar_lot_polygon(x, y) -> tuple[tuple[int, int], ...]`.
- Existing `_cooling_tower`, `_lot`, and `_draw_plant_static` consume those helpers.

- [ ] **Step 1: Add failing geometry and pixel-behavior tests**

```python
def test_cooling_tower_rim_rect_is_pixel_centered():
    for radius in (7.2, 9.8, 11.4):
        rect = centered_ellipse_rect(60, 40, radius, radius * 0.42)
        assert rect.centerx == 60
        assert rect.width % 2 == 1


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
```

- [ ] **Step 2: Run the city-model suite and verify the tests fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_city_model.py`

Expected: failures for missing helpers and the existing yellow gas line.

- [ ] **Step 3: Center the cooling-tower rim and live effects**

```python
def centered_ellipse_rect(cx, cy, rx, ry):
    half_w = max(1, math.ceil(rx))
    half_h = max(1, math.ceil(ry))
    return pygame.Rect(round(cx) - half_w, round(cy) - half_h,
                       half_w * 2 + 1, half_h * 2 + 1)
```

Derive the outer lip from this rectangle and use `inflate` for the inner lip and opening, preserving the same `centerx`. Keep the shell scanlines centered on `round(x)`. Align plume and beacon x coordinates to those same tower centers.

- [ ] **Step 4: Preserve the complete solar lot and remove the gas line**

Make `solar_lot_polygon(x, y)` return the same four points `_lot` uses for a 13-by-10 tile lot at `back = (x - 52, y - 34)`. Draw that polygon and its complete perimeter before the two internal gravel strips. Clip the strips to a temporary lot-sized alpha surface before compositing so neither replaces a perimeter corner. Delete the `(206, 170, 74)` gas fuel-line draw call.

- [ ] **Step 5: Run the city-model suite and verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_city_model.py`

Expected: all checks pass.

- [ ] **Step 6: Commit the geometry fixes**

```bash
git add energy_grid_game/ui/iso_city.py energy_grid_game/test_city_model.py
git commit -m "Correct power plant artwork geometry"
```

---

### Task 4: Connected vehicle routing and sparse traffic

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py:1220-1370, 1390-1420, 1745-1790, 2125-2160`
- Modify: `energy_grid_game/test_city_model.py:120-150, 575-700`

**Interfaces:**
- Produces: `parabolic_peak(hour: float, center: float, half_width: float) -> float`.
- Keeps: `traffic_level(sim_hour: float, served: float = 1.0) -> float`.
- Produces: `road_neighbors(tiles: dict) -> dict[tuple[int, int], tuple[tuple[int, int], ...]]`.
- Changes `_Vehicle` to own `tile`, `next_tile`, `previous_tile`, `progress`, `speed`, `kind`, and `color`.
- Produces: `_Vehicle.advance(dt, neighbors, rng) -> None`.

- [ ] **Step 1: Add failing traffic-curve and routing tests**

```python
def test_traffic_has_smooth_parabolic_rush_hour_peaks():
    assert traffic_level(9.0) > traffic_level(12.0) > traffic_level(3.0)
    assert traffic_level(17.0) > traffic_level(12.0)
    assert traffic_level(8.0) < traffic_level(9.0) > traffic_level(10.0)
    assert traffic_level(16.0) < traffic_level(17.0) > traffic_level(18.0)
    for center in (9.0, 17.0):
        assert abs(traffic_level(center - 0.1) -
                   traffic_level(center + 0.1)) < 0.04


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
```

- [ ] **Step 2: Run the city-model suite and verify the tests fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_city_model.py`

Expected: failures because traffic uses a 24-point lookup, vehicles own straight intervals, and 260 vehicles are generated.

- [ ] **Step 3: Implement the rush-hour curve**

```python
def parabolic_peak(hour, center, half_width):
    distance = abs((hour - center + 12.0) % 24.0 - 12.0)
    x = distance / half_width
    return max(0.0, 1.0 - x * x)


def traffic_level(sim_hour, served=1.0, traffic_min=TRAFFIC_MIN):
    h = sim_hour % 24.0
    daylight_base = max(0.0, math.sin(math.pi * (h - 5.0) / 17.0))
    level = (0.06 + 0.28 * daylight_base
             + 0.62 * parabolic_peak(h, 9.0, 1.5)
             + 0.70 * parabolic_peak(h, 17.0, 1.5))
    return max(traffic_min, min(1.0, level * (0.65 + 0.35 * served)))
```

- [ ] **Step 4: Build and traverse the road graph**

Create neighbors from the four orthogonal grid offsets for every tile whose kind is `road`. Generate `MAX_VEHICLES = 96` vehicles on graph edges. `_Vehicle.advance` interpolates along an edge, rolls excess progress into the next edge, excludes `previous_tile` from candidates when another exit exists, and uses the seeded city RNG for a deterministic choice.

In `_draw_vehicles`, interpolate `(col, row)` between `tile` and `next_tile`, derive orientation from their delta, apply a 0.10-tile perpendicular lane offset according to direction, and retain `_occluded(col, row)` before blitting. Set zoom densities to `{1: 0.24, 2: 0.48, 4: 0.72}`.

- [ ] **Step 5: Run the city-model suite and verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_city_model.py`

Expected: all checks pass.

- [ ] **Step 6: Commit traffic routing**

```bash
git add energy_grid_game/ui/iso_city.py energy_grid_game/test_city_model.py
git commit -m "Route sparse traffic through city streets"
```

---

### Task 5: Absolute 101%-to-200% overload visuals

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py:100-155, 2025-2080, 2190-2275`
- Modify: `energy_grid_game/test_city_model.py:510-570`
- Modify: `tools/capture_moments.py:220-300`

**Interfaces:**
- Produces: `voltage_overload_level(ratio: float) -> float` for 1.01 through 1.50.
- Produces: `fire_overload_level(ratio: float) -> float` for 1.50 through 2.00.
- Changes `_ignite_rate`, `_max_fires`, and `_fire_reach` to consume absolute fire severity only.

- [ ] **Step 1: Add failing tests for absolute visual thresholds**

```python
def test_absolute_overload_visual_thresholds():
    assert voltage_overload_level(1.0) == 0.0
    assert voltage_overload_level(1.01) == 0.0
    assert 0.0 < voltage_overload_level(1.20) < 1.0
    assert voltage_overload_level(1.50) == 1.0
    assert fire_overload_level(1.49) == 0.0
    assert fire_overload_level(1.50) == 0.0
    assert 0.0 < fire_overload_level(1.75) < 1.0
    assert fire_overload_level(2.00) == 1.0
    assert fire_overload_level(2.50) == 1.0


def test_fire_escalation_is_monotonic_from_150_to_200_percent():
    severities = [fire_overload_level(r) for r in (1.50, 1.65, 1.80, 2.00)]
    assert severities == sorted(severities)
    for fn in (_ignite_rate, _max_fires, _fire_reach):
        values = [fn(level) for level in severities]
        assert values == sorted(values), fn.__name__
    assert _max_fires(severities[0]) == 0
    assert _fire_reach(severities[-1]) == 1.0
```

- [ ] **Step 2: Run the city-model suite and verify the tests fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_city_model.py`

Expected: failure because current severity depends on difficulty meltdown thresholds and current fire helpers require `crisis`.

- [ ] **Step 3: Implement separate voltage and fire severities**

```python
def _ramp(value, start, end):
    return max(0.0, min(1.0, (value - start) / (end - start)))


def voltage_overload_level(ratio):
    return _ramp(ratio, 1.01, 1.50)


def fire_overload_level(ratio):
    return _ramp(ratio, 1.50, 2.00)


def _ignite_rate(fire):
    return fire * 8.0


def _max_fires(fire):
    return int(round(48 * fire))


def _fire_reach(fire):
    return fire
```

In `IsoCity.draw`, calculate `ratio = total_actual_mw / demand_mw` with a 1.0 fallback for zero demand. Pass voltage severity to the tint/arcing path and fire severity to `_update_fires`. Do not use `state.difficulty.meltdown` or `danger_timer` for visual severity. Keep existing loss mechanics untouched in `GameState`.

- [ ] **Step 4: Scale city effects without increasing full-screen pulse frequency**

At voltage severity below 0.4, draw only the warm tint. Above 0.4, allow occasional local arcs with a rate proportional to voltage severity. Fires and smoke are drawn only when fire severity is positive. Keep the existing `sin(self.t * 1.6)` whole-screen envelope unchanged.

- [ ] **Step 5: Add deterministic capture states**

Extend the capture harness with `23_overload_101.png`, `24_overload_150.png`, and `25_overload_200.png`. Set plant output and demand so the actual supply/demand ratio is respectively 1.01, 1.50, and 2.00, then settle enough frames for local effects to appear at the latter two levels.

- [ ] **Step 6: Run the city-model suite and verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_city_model.py`

Expected: all checks pass.

- [ ] **Step 7: Commit overload scaling**

```bash
git add energy_grid_game/ui/iso_city.py energy_grid_game/test_city_model.py tools/capture_moments.py
git commit -m "Scale city overload effects from live supply"
```

---

### Task 6: Visual captures and complete regression verification

**Files:**
- Modify: `tools/capture_moments.py`
- Update: `captures/v11/09_day_complete.png` only if the intentional unified HUD changes that tracked baseline.

**Interfaces:**
- The capture harness remains runnable as `python tools/capture_moments.py <out_dir>` and writes deterministic review PNGs.

- [ ] **Step 1: Add capture states for edge tabs and rush-hour traffic**

After the existing zoom captures, pan at 4x until at least three plant markers are off-screen and save `26_offscreen_plant_tabs.png`. Set `sim_hour` to 9.0 and 17.0, settle 90 frames at 2x, and save `27_morning_rush.png` and `28_evening_rush.png`. Reset camera and state between captures so each state is independently reproducible.

- [ ] **Step 2: Run all automated verification commands**

Run each command separately:

```bash
PYTHONPYCACHEPREFIX=/tmp/grid_keeper_pycache .venv/bin/python -m py_compile energy_grid_game/main.py energy_grid_game/ui/iso_city.py energy_grid_game/ui/plant_pins.py energy_grid_game/ui/hud.py
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_city_model.py
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_capacities.py
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python energy_grid_game/test_instructional.py
git diff --check
```

Expected: every command exits zero and all three suites report all checks passed.

- [ ] **Step 3: Generate fresh review captures**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python tools/capture_moments.py /tmp/grid-keeper-ui-traffic-polish`

Expected: the harness reports every capture written without a traceback.

- [ ] **Step 4: Inspect the required visual states**

Open and inspect:

- `06_game.png`: unified HUD, wide MW-safe cards, downward chevrons, no leaders;
- `13_zoom_4x_day.png`: complete solar lot and centered nuclear rims;
- `21_delivery_chain_close.png`: gas pavement without the yellow line;
- `23_overload_101.png`, `24_overload_150.png`, `25_overload_200.png`: monotonic escalation;
- `26_offscreen_plant_tabs.png`: non-overlapping directional tabs;
- `27_morning_rush.png`, `28_evening_rush.png`: sparse routed rush traffic.

Expected: each screenshot matches the approved design and no card, tab, plant, vehicle, or HUD element is clipped.

- [ ] **Step 5: Commit capture-harness updates and any intentional baseline**

```bash
git add tools/capture_moments.py captures/v11/09_day_complete.png
git commit -m "Add UI and traffic visual regression captures"
```

If the tracked baseline did not change, omit it from `git add` and commit only the harness.

---

## Final Review Checklist

- [ ] One continuous HUD panel replaces the three islands.
- [ ] Long MW values remain inside full plant cards.
- [ ] Full cards bob subtly and use downward chevrons without leader lines.
- [ ] Off-screen plants use compact directional edge tabs and tab clicks focus the plant.
- [ ] Cooling-tower lips, openings, shells, plumes, and beacons share a centerline.
- [ ] The solar lot has a complete four-corner footprint.
- [ ] The gas plant has no yellow pavement line.
- [ ] Vehicles follow connected roads, turn at junctions, avoid needless U-turns, use lane offsets, and remain sparse.
- [ ] Traffic has smooth visible peaks at 8–10 AM and 4–6 PM.
- [ ] Overload visuals are calm at 101%, serious at 150%, and maximal at 200%.
- [ ] City-model, capacity, instructional, compile, capture, and diff checks all pass.
