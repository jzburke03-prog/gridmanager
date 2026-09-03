# Command UI Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan is local-only: do not run `git add`, `git commit`, `git reset`, create branches, or otherwise modify git state.

**Goal:** Refresh Grid Manager's HUD, demand monitor, menu, and outcome screens so the game clearly teaches supply-demand balance, spending, and homes powered while preserving the voxel-pixel aesthetic.

**Architecture:** Keep changes localized to the existing Pygame UI modules. Add small pure formatting/severity helpers in `ui/hud.py`, restyle existing draw paths, and remove the old bottom-right homes draw call from both live rendering and capture rendering.

**Tech Stack:** Python 3, Pygame 2.6.1, existing `ui.assets` pixel asset loader, existing visual capture harness.

## Global Constraints

- Work locally only. Do not use git for implementation, verification, staging, commits, resets, branches, or PR work.
- Preserve gameplay behavior, simulation math, scoring, chart data, and existing input semantics.
- Keep the current voxel-pixel art direction: square bevels, dark console materials, monospace typography, source colors, green/amber/red status language.
- No new external UI framework or asset dependency.
- Design against the existing minimum window size: 1000 x 680.
- Remove the bottom-right homes-without-power box from normal play and visual captures.

---

### Task 1: HUD Helper Functions And Tests

**Files:**
- Modify: `energy_grid_game/ui/hud.py`
- Modify: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Produces: `_homes_out_status(homes_out: float, homes_total: float) -> tuple[str, tuple[int, int, int]]`
- Produces: `_money_status(price: float) -> tuple[int, int, int]`
- Consumes: existing HUD constants `DIM`, `_format_money()`, `_price_color()`

- [ ] **Step 1: Write focused helper tests**

Add tests to `energy_grid_game/test_city_model.py`:

```python
def test_homes_out_status_uses_green_zero_amber_warning_red_majority():
    from ui.hud import _homes_out_status

    assert _homes_out_status(0, 1000)[0] == "0"
    assert _homes_out_status(250, 1000)[0] == "0"

    amber_value, amber_color = _homes_out_status(600, 2000)
    assert amber_value == "600"
    assert amber_color == (240, 170, 80)

    red_value, red_color = _homes_out_status(1200, 2000)
    assert red_value == "1,200"
    assert red_color == (230, 90, 90)
```

- [ ] **Step 2: Run failing helper test**

Run: `.venv39\Scripts\python.exe -m pytest energy_grid_game/test_city_model.py::test_homes_out_status_uses_green_zero_amber_warning_red_majority -q`

Expected: FAIL because `_homes_out_status` does not exist yet.

- [ ] **Step 3: Implement helpers**

Add near `FAILURE_EXPLANATIONS` in `ui/hud.py`:

```python
OK = (100, 220, 140)
WARN = (240, 170, 80)
BAD = (230, 90, 90)


def _homes_out_status(homes_out: float, homes_total: float):
    if homes_out <= 500:
        return "0", OK
    if homes_total > 0 and homes_out > homes_total * 0.5:
        return f"{homes_out:,.0f}", BAD
    return f"{homes_out:,.0f}", WARN


def _money_status(price: float):
    return _price_color(price)
```

If `OK`, `WARN`, or `BAD` duplicate existing colors, use these constants in the HUD drawing code rather than introducing more color constants.

- [ ] **Step 4: Run helper test**

Run: `.venv39\Scripts\python.exe -m pytest energy_grid_game/test_city_model.py::test_homes_out_status_uses_green_zero_amber_warning_red_majority -q`

Expected: PASS.

### Task 2: Promote Balance, Homes, And Money In The Top HUD

**Files:**
- Modify: `energy_grid_game/ui/hud.py`
- Modify: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: `_homes_out_status(homes_out, homes_total)`
- Produces: `HUD._draw_metric_plate(surface, rect, label, value, color, icon=None, sub=None) -> None`
- Produces: top HUD rendering with balance center, money/homes/score right-side modules

- [ ] **Step 1: Write HUD smoke test**

Add this test to `energy_grid_game/test_city_model.py`:

```python
def test_hud_draw_promotes_homes_without_power_number():
    import pygame
    from ui.hud import HUD, hud_panel_rects, _homes_out_status
    import scenarios
    from game_state import GameState

    pygame.init()
    pygame.display.set_mode((1000, 680))
    font = pygame.font.Font(None, 18)
    hud = HUD(font, font, pygame.font.Font(None, 28), pygame.font.Font(None, 44))
    state = GameState(scenarios.make_standard())
    state.homes_without_power = 1234
    state.homes_total = 2000

    surface = pygame.Surface((1000, 680), pygame.SRCALPHA)
    hud.draw(surface, state, hud_panel_rects(1000, 680))

    value, color = _homes_out_status(state.homes_without_power, state.homes_total)
    assert value == "1,234"
    assert color == (230, 90, 90)
    assert surface.get_bounding_rect().width > 0
```

- [ ] **Step 2: Run HUD smoke test**

Run: `.venv39\Scripts\python.exe -m pytest energy_grid_game/test_city_model.py::test_hud_draw_promotes_homes_without_power_number -q`

Expected: PASS once imports are correct; this verifies the draw path remains nonblank while using the promoted homes helper.

- [ ] **Step 3: Add metric drawing helper**

In `HUD`, add:

```python
def _draw_metric_plate(self, surface, rect, label, value, color, icon=None, sub=None):
    plate = pygame.Surface(rect.size, pygame.SRCALPHA)
    plate.fill((8, 12, 20, 120))
    pygame.draw.rect(plate, (70, 82, 112, 135), plate.get_rect(), width=1)
    pygame.draw.line(plate, (120, 136, 166, 100), (0, 0), (rect.width - 1, 0))
    pygame.draw.line(plate, (4, 7, 12, 160), (0, rect.height - 1), (rect.width - 1, rect.height - 1))
    surface.blit(plate, rect.topleft)
    x = rect.left + 8
    if icon is not None:
        surface.blit(icon, (x, rect.top + 8))
        x += icon.get_width() + 6
    label_txt = self.font_small.render(label, True, DIM)
    value_txt = self.font_big.render(value, True, color)
    surface.blit(label_txt, (x, rect.top + 7))
    surface.blit(value_txt, (x, rect.top + 7 + label_txt.get_height()))
    if sub:
        sub_txt = self.font_small.render(sub, True, DIM)
        surface.blit(sub_txt, (x, rect.bottom - sub_txt.get_height() - 5))
```

- [ ] **Step 4: Reorganize `HUD.draw()` right zone**

Inside `HUD.draw()`, keep existing clock/date/season/speed/event behavior and the large central balance readout. Replace the current score-first right column with three compact plates:

```python
homes_value, homes_color = _homes_out_status(state.homes_without_power, state.homes_total)
homes_icon = assets.resource_icon("population", 14)
self._draw_metric_plate(surface, homes_rect, "HOMES OUT", homes_value, homes_color, homes_icon)

if state.show_economics:
    self._draw_metric_plate(surface, spent_rect, "TOTAL SPENT",
                            _format_money(state.total_cost), (240, 200, 90),
                            assets.resource_icon("money", 14),
                            f"${state.grid_price:0.0f}/MWh  {_format_money(state.cost_per_hour)}/hr")

self._draw_metric_plate(surface, score_rect, "SCORE", f"{int(state.score):,}", TEXT,
                        sub=f"BEST {int(state.high_score):,}")
```

Use concrete `pygame.Rect` values derived from `right.right`, `right.top`, and available height. At 1000 px width, plates must not overlap the center balance block.

- [ ] **Step 5: Clarify center supply/demand labels**

Change the small labels around the central supply/demand values to `SUPPLY NOW` and `DEMAND TARGET`. Keep the existing supply green and demand orange colors.

- [ ] **Step 6: Run HUD tests**

Run: `.venv39\Scripts\python.exe -m pytest energy_grid_game/test_city_model.py::test_homes_out_status_uses_green_zero_amber_warning_red_majority energy_grid_game/test_city_model.py::test_hud_draw_promotes_homes_without_power_number -q`

Expected: PASS.

### Task 3: Remove The Bottom-Right Homes Box From Live And Capture Rendering

**Files:**
- Modify: `energy_grid_game/main.py`
- Modify: `tools/capture_moments.py`
- Modify: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: existing `compute_layout(screen_w, screen_h)` return tuple
- Produces: no call to `city.draw_homes_label()` in main render or capture render

- [ ] **Step 1: Write source-level regression test**

Add to `energy_grid_game/test_city_model.py`:

```python
def test_main_and_capture_no_longer_draw_bottom_homes_label():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    main_src = (root / "main.py").read_text(encoding="utf-8")
    capture_src = (root.parent / "tools" / "capture_moments.py").read_text(encoding="utf-8")

    assert ".draw_homes_label(" not in main_src
    assert ".draw_homes_label(" not in capture_src
```

- [ ] **Step 2: Run failing removal test**

Run: `.venv39\Scripts\python.exe -m pytest energy_grid_game/test_city_model.py::test_main_and_capture_no_longer_draw_bottom_homes_label -q`

Expected: FAIL because both render paths still call `draw_homes_label`.

- [ ] **Step 3: Remove live draw call**

In `energy_grid_game/main.py`, remove:

```python
city.draw_homes_label(frame, readout_rect, state.homes_without_power, state.homes_total)
```

Keep `readout_rect` only where it still acts as an obstacle or layout return value. Do not change city simulation or HUD draw order.

- [ ] **Step 4: Remove capture draw call**

In `tools/capture_moments.py`, remove:

```python
w["city"].draw_homes_label(frame, w["readout_rect"], st.homes_without_power,
                           st.homes_total)
```

Keep `readout_rect` in `_build()` for this task so plant-pin obstacle layout remains unchanged.

- [ ] **Step 5: Run removal test**

Run: `.venv39\Scripts\python.exe -m pytest energy_grid_game/test_city_model.py::test_main_and_capture_no_longer_draw_bottom_homes_label -q`

Expected: PASS.

### Task 4: Restyle DemandChart As A Pixel Utility Monitor

**Files:**
- Modify: `energy_grid_game/ui/demand_chart.py`
- Modify: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Produces: `DemandChart._monitor_rects() -> tuple[pygame.Rect, pygame.Rect]`
- Keeps: `DemandChart.draw(surface, current_hour, sources, history, demand_mw_now, min_mw, peak_mw)`

- [ ] **Step 1: Write demand chart smoke test**

Add to `energy_grid_game/test_city_model.py`:

```python
def test_demand_chart_draws_pixel_monitor_frame_with_empty_history():
    import pygame
    from ui.demand_chart import DemandChart

    pygame.init()
    pygame.display.set_mode((1000, 680))
    surface = pygame.Surface((300, 170), pygame.SRCALPHA)
    chart = DemandChart(pygame.Rect(0, 0, 300, 170), pygame.font.Font(None, 14))

    chart.draw(surface, 12.0, [], [], 900.0, 500.0, 1200.0)

    assert surface.get_at((1, 1)).a > 0
    assert surface.get_at((150, 20)).a > 0
```

- [ ] **Step 2: Run chart smoke test**

Run: `.venv39\Scripts\python.exe -m pytest energy_grid_game/test_city_model.py::test_demand_chart_draws_pixel_monitor_frame_with_empty_history -q`

Expected: PASS after the chart can draw without source history.

- [ ] **Step 3: Replace rounded background with monitor frame**

In `DemandChart._draw_dynamic_bg()`, draw:

```python
outer = self.rect
pygame.draw.rect(surface, (7, 10, 18), outer)
pygame.draw.rect(surface, (72, 84, 116), outer, width=2)
pygame.draw.line(surface, (130, 146, 178), outer.topleft, (outer.right - 1, outer.top))
pygame.draw.line(surface, (3, 6, 11), (outer.left, outer.bottom - 1), (outer.right - 1, outer.bottom - 1))
header = pygame.Rect(outer.left + 2, outer.top + 2, outer.width - 4, 22)
pygame.draw.rect(surface, (18, 28, 44), header)
screen = outer.inflate(-10, -34)
screen.top = header.bottom + 5
```

Blit the existing darkened time-of-day gradient into `screen`, not the whole `rect`. Store `self._plot_rect = screen` for plotting.

- [ ] **Step 4: Plot against the inner screen**

Change `_x()` and `_y()` to use `self._plot_rect` when present:

```python
plot = getattr(self, "_plot_rect", self.rect)
```

Use `plot.left`, `plot.right`, `plot.top`, and `plot.bottom` in calculations.

- [ ] **Step 5: Add grid ticks**

After drawing the inner gradient, draw low-alpha vertical tick lines for `LABEL_OFFSETS` and two horizontal gridlines. Use muted blue-grey so the source stack and demand line remain dominant.

- [ ] **Step 6: Run chart smoke test**

Run: `.venv39\Scripts\python.exe -m pytest energy_grid_game/test_city_model.py::test_demand_chart_draws_pixel_monitor_frame_with_empty_history -q`

Expected: PASS.

### Task 5: Elevate Menu, Game Over, And Day Complete Screens

**Files:**
- Modify: `energy_grid_game/ui/menu.py`
- Modify: `energy_grid_game/ui/hud.py`
- Modify: `energy_grid_game/ui/day_panel.py`

**Interfaces:**
- Keeps: `MenuSystem` states and click targets
- Keeps: `HUD.draw_game_over(surface, state)`
- Keeps: `DayCompletePanel.draw(surface)`

- [ ] **Step 1: Update title controls**

In `MenuSystem._draw_title()`, reposition PLAY and events controls lower in the ground-band/control-console area, with a stronger pixel bevel/glow. Keep the click targets and actions unchanged:

```python
self._btn(surface, pygame.Rect(cx - 130, h // 2 + 8, 260, 60), "PLAY",
          ("goto", MODE), accent=ACCENT, big=True)
```

Change the events toggle to a hardware status chip with a small square indicator and text `GRID EVENTS ON/OFF`. Preserve `("toggle_events",)`.

- [ ] **Step 2: Strengthen mode cards**

In `MenuSystem._card()`, add a thin header strip, corner ticks, and slightly stronger hover glow while keeping square corners. Do not change card text, state transitions, or hit testing.

- [ ] **Step 3: Restyle game-over overlay**

In `HUD.draw_game_over()`, keep the portrait and keyboard semantics. Add a centered alert panel behind the title/explanation/score block with square bevel, a red/amber top alert strip, and clearer grouping:

```python
panel = pygame.Rect(0, 0, min(680, w - 160), 280)
panel.center = (w // 2 + 80, h // 2)
```

Clamp the portrait so it does not overlap the panel at 1000 x 680.

- [ ] **Step 4: Restyle day-complete panel shell**

In `DayCompletePanel.draw()`, replace rounded panel drawing with a square-corner command-panel surface: dark base, bevel lines, steel border, and a header strip. Keep chart/stat layout and button click target behavior unchanged.

- [ ] **Step 5: Preserve text fit**

Run the game-over and day-complete drawing manually through `tools/capture_moments.py` in Task 6; if any text overlaps, shrink only panel-local spacing or font choice. Do not change global font sizes.

### Task 6: Verification And Visual Captures

**Files:**
- Modify: no required files unless verification reveals a layout issue

**Interfaces:**
- Consumes: `tools/capture_moments.py`
- Produces: refreshed PNG captures under a local output directory

- [ ] **Step 1: Run focused tests**

Run:

```powershell
.venv39\Scripts\python.exe -m pytest `
  energy_grid_game/test_city_model.py::test_homes_out_status_uses_green_zero_amber_warning_red_majority `
  energy_grid_game/test_city_model.py::test_hud_draw_promotes_homes_without_power_number `
  energy_grid_game/test_city_model.py::test_main_and_capture_no_longer_draw_bottom_homes_label `
  energy_grid_game/test_city_model.py::test_demand_chart_draws_pixel_monitor_frame_with_empty_history `
  energy_grid_game/test_instructional.py::test_four_day_progression_through_the_real_day_panel -q
```

Expected: PASS.

- [ ] **Step 2: Run visual captures**

Run: `.venv39\Scripts\python.exe tools\capture_moments.py captures_ui_refresh`

Expected: command exits 0 and reports captured moments.

- [ ] **Step 3: Inspect key captures**

Open these files and visually inspect for readability, no overlap, and matching pixel-console aesthetic:

- `captures_ui_refresh/01_title.png`
- `captures_ui_refresh/02_mode.png`
- `captures_ui_refresh/06_game.png`
- `captures_ui_refresh/09_day_complete.png`
- `captures_ui_refresh/10_game_over.png`

- [ ] **Step 4: Fix any visual overlap**

If overlap appears, adjust only the relevant local layout constants in `hud.py`,
`demand_chart.py`, `day_panel.py`, or `menu.py`, then rerun Step 1 and Step 2.
