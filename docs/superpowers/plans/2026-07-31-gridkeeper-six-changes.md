# Grid Keeper Six-Change Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the nuclear price, relabel the SKIP button, color transmission by
source, add a light congestion mechanic (with real MW loss), redesign the
isometric city toward a cleaner reference look, and rewrite the dialogue in
natural English.

**Architecture:** Six mostly-independent workstreams against the isometric-city
build. The simulation (`game_state.py`) stays the single source of truth; UI
(`hud.py`, `iso_city.py`, `grid_flow.py`) only reads. Congestion reuses the
per-route `Flow` groundwork SPEC-1.1 §1.6 left in place.

**Tech Stack:** Python 3, pygame 2.6. Tests are plain-`assert` functions with a
`__main__` self-runner (no pytest). Run with the project venv:
`.\.venv39\Scripts\python.exe energy_grid_game\<test_file>.py`.

## Global Constraints

- **NO git operations in this repo** (standing rule). Every "Checkpoint" step means
  *run the verification and confirm green* — do **not** `git add`/`commit`.
- Keep existing tests green: `energy_grid_game/test_capacities.py`,
  `test_city_model.py`, `test_instructional.py`.
- Accessibility (from `iso_city.py` docstring): all severity easing stays smooth,
  under ~3 Hz; no large-area strobe. Must survive the city redesign.
- Dialogue edits change **human-readable strings only** — never the step schema
  keys (`id`, `portrait`, `speaker`, `highlight`, `wait_for`, `action_hint`,
  `learn_more`) or `CONDITIONS`. Keep each rendered line within
  `DialogueBox.MAX_LINES = 3` after wrap.
- Congestion playability guardrail: `LINE_HEADROOM * firm_capacity(1350 MW) ≥ peak`.
  At `LINE_HEADROOM = 0.90` → 1215 MW ≥ July peak 1160 MW. Do not lower it past
  `peak / 1350 ≈ 0.86`.
- Verify visuals with `.\.venv39\Scripts\python.exe tools\capture_moments.py <dir>`
  and eyeball against `captures/` and the reference image.

---

## Task 1: Correct the nuclear marginal price

**Files:**
- Modify: `energy_grid_game/pricing.py:26` (constant) and the docstring nuclear line
- Test: `energy_grid_game/test_pricing.py` (create)

**Interfaces:**
- Produces: `NUCLEAR_PRICE_PER_MWH = 11.0` (module constant, unchanged name/type)

- [ ] **Step 1: Write the failing test** — create `energy_grid_game/test_pricing.py`

```python
"""Marginal-cost sanity checks (pricing.py). Run: python test_pricing.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pricing


def test_nuclear_is_marginal_not_all_in():
    # Nuclear marginal cost = fuel (~$7) + variable O&M (~$2.5) ~= $9-12/MWh,
    # NOT its ~$33 all-in generating cost. It must be the cheapest firm source.
    assert 8.0 <= pricing.NUCLEAR_PRICE_PER_MWH <= 13.0


def test_merit_order_firm_sources():
    # Cheapest dispatch first: nuclear < coal < gas baseline < peaker baseline.
    assert pricing.NUCLEAR_PRICE_PER_MWH < pricing.COAL_PRICE_PER_MWH
    assert pricing.NUCLEAR_PRICE_PER_MWH < pricing.GAS_BASE_PRICE_PER_MWH
    assert pricing.GAS_BASE_PRICE_PER_MWH < pricing.PEAKER_BASE_PRICE_PER_MWH


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall pricing checks passed")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.\.venv39\Scripts\python.exe energy_grid_game\test_pricing.py`
Expected: FAIL — `test_nuclear_is_marginal_not_all_in` (28.0 not in 8..13).

- [ ] **Step 3: Change the constant** — `energy_grid_game/pricing.py:26`

```python
NUCLEAR_PRICE_PER_MWH = 11.0
```

- [ ] **Step 4: Fix the docstring nuclear line** (`pricing.py`, in the reference block)

Replace the `Nuclear:` line with:

```
  Nuclear: fuel ~$0.75/MMBtu at ~10,400 Btu/kWh gives ~$7/MWh fuel + ~$2.5/MWh
           variable O&M -> ~$11/MWh MARGINAL/dispatch cost (what merit order
           uses). Its ~$33/MWh all-in generating cost is a different figure —
           it includes fixed O&M and capital, which dispatch order ignores.
```

- [ ] **Step 5: Run the test — passes**

Run: `.\.venv39\Scripts\python.exe energy_grid_game\test_pricing.py`
Expected: PASS (both tests).

- [ ] **Step 6: Checkpoint** — launch a Standard run, open the Nuclear pin, confirm
  it reads `$11/MWh` and sits below coal/gas in the pin prices.

---

## Task 2: Relabel "SKIP DAY" → "SKIP DIALOGUE" and fix the hit target

**Files:**
- Modify: `energy_grid_game/main.py:121` (label)
- Modify: `energy_grid_game/ui/dialogue.py:224-246` (clamp skip/learn rects on-screen)

**Interfaces:**
- Consumes: `DialogueBox.skip_rect`, `.learn_rect` (existing pygame.Rects)

- [ ] **Step 1: Rename the label** — `main.py:121`

```python
                                   skip_label="SKIP DIALOGUE")
```

- [ ] **Step 2: Clamp the skip/learn buttons on-screen** — `ui/dialogue.py`

The buttons are placed at `self.rect.top - 26`. When the box lands at the top of
the screen (after a resize, per `get_dialogue_rect`), that y is negative and the
button is unclickable. In `draw`, replace the skip-rect placement (currently
`self.skip_rect.topright = (self.rect.right, self.rect.top - 26)`) with a clamp:

```python
        if skip_label:
            self.skip_rect = pygame.Rect(0, 0, 118, 22)
            top = max(2, self.rect.top - 26)  # never off the top of the screen
            self.skip_rect.topright = (self.rect.right, top)
            pygame.draw.rect(surface, (18, 22, 34), self.skip_rect, border_radius=4)
            pygame.draw.rect(surface, (120, 132, 160), self.skip_rect, width=1, border_radius=4)
            txt = self.font_small.render(skip_label, True, (218, 226, 240))
            surface.blit(txt, (self.skip_rect.centerx - txt.get_width() // 2,
                               self.skip_rect.centery - txt.get_height() // 2))
        else:
            self.skip_rect = pygame.Rect(0, 0, 0, 0)
```

Apply the identical `top = max(2, self.rect.top - 26)` clamp to the `learn_rect`
placement in the block just below it.

- [ ] **Step 3: Checkpoint** — launch Instructional Day 1: the button reads
  "SKIP DIALOGUE"; clicking it dismisses Gattie's dialogue and returns to play.
  Maximize/restore the window to force a top box placement and confirm it is still
  clickable. (Manual — this is layout/interaction, not unit-testable.)

---

## Task 3: Color transmission flows by source

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py:2199-2202` (transmission flow draw)

**Interfaces:**
- Consumes: `Flow.update_and_draw(surf, output, dt, color=..., overload=...)` — the
  `overload=` parameter is added in Task 5; for now pass `color=` only.
- Consumes: `EnergySource.color` (RGB tuple, already on every source)

- [ ] **Step 1: Pass each plant's color on its corridor** — `iso_city.py`, in the
  transmission loop (the `for (key, i), flow in self._flows.items():` block):

```python
        for (key, i), flow in self._flows.items():
            src = by_key.get(key)
            out = 0.0 if src is None or src.max_output_mw <= 0 else src.actual_pct
            color = src.color if src is not None else (120, 200, 255)
            flow.update_and_draw(layer, out, dt, color=color)
            got, cap = load.get(i, (0.0, 0.0))
            mw = src.max_output_mw if src else 0.0
            load[i] = (got + out * mw, cap + mw)
```

Leave the `_distribution_flows` and `_service_flows` loops UNCHANGED — that power is
a blend of all sources and must stay neutral blue.

- [ ] **Step 2: Update the grid_flow docstring** — `ui/grid_flow.py`, the bullet that
  claims "One colour for everything": note that per-source colour is now used on the
  plant→substation corridors (distribution stays neutral because it is mixed).

- [ ] **Step 3: Checkpoint** — render and eyeball:

Run: `.\.venv39\Scripts\python.exe tools\capture_moments.py $env:TEMP\gk_task3`
Expected: in `06_game.png` and `21_delivery_chain_close.png`, each plant's corridor
pulses in its own colour (nuclear cyan, gas orange, solar amber, wind pale-blue…);
the flows feeding into the blocks stay neutral blue.

---

## Task 4: Congestion — model, MW loss, score/cost (game_state)

**Files:**
- Modify: `energy_grid_game/game_state.py` — constants (~L32-41), `__init__` (~L255),
  properties (~L412, L427), `update` (~L509-557), `_update_pricing` (~L571-611)
- Test: `energy_grid_game/test_congestion.py` (create)

**Interfaces:**
- Produces: `GameState.line_capacity_mw(source) -> float`
- Produces: `GameState.effective_supply_mw -> float` (property)
- Produces: `GameState.congestion_overload_mw: float`, `.congestion_loss_mw: float`,
  `.line_overload_frac: dict[str, float]` (0..1 per source key), refreshed each `update`

- [ ] **Step 1: Write the failing test** — `energy_grid_game/test_congestion.py`

```python
"""Congestion mechanic checks (game_state). Run: python test_congestion.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import scenarios
from game_state import GameState, LINE_HEADROOM, CONGESTION_LOSS_FRACTION


def _standard():
    return GameState(scenarios.make_standard())


def test_no_congestion_below_line_rating():
    st = _standard()
    gas = next(s for s in st.sources if s.key == "gas")
    gas.actual_pct = LINE_HEADROOM - 0.05          # under the line rating
    st._update_congestion(0.0)
    assert st.congestion_overload_mw == 0.0
    assert st.effective_supply_mw == st.total_actual_mw


def test_overload_loses_mw_and_flags_source():
    st = _standard()
    for s in st.sources:
        s.actual_pct = 0.0
    gas = next(s for s in st.sources if s.key == "gas")
    gas.actual_pct = 1.0                            # slammed to 100%
    st._update_congestion(0.0)
    cap = st.line_capacity_mw(gas)
    overload = gas.current_output_mw - cap
    assert st.congestion_overload_mw > 0.0
    assert abs(st.congestion_loss_mw - CONGESTION_LOSS_FRACTION * overload) < 1e-6
    assert st.effective_supply_mw < st.total_actual_mw
    assert st.line_overload_frac["gas"] > 0.9       # ~fully overloaded at 100%


def test_peak_is_meetable_without_congestion():
    # Firm fleet at the line rating must still cover the worst-month peak.
    st = _standard()
    firm = sum(st.line_capacity_mw(s) for s in st.sources
               if s.key in ("nuclear", "coal", "gas", "peaker", "hydro"))
    assert firm >= st.demand_peak_mw, f"{firm} < {st.demand_peak_mw}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall congestion checks passed")
```

- [ ] **Step 2: Run it — fails**

Run: `.\.venv39\Scripts\python.exe energy_grid_game\test_congestion.py`
Expected: FAIL — `ImportError: cannot import name 'LINE_HEADROOM'`.

- [ ] **Step 3: Add tuning constants** — `game_state.py`, near `FILL_TRACK_SPEED`:

```python
# --- transmission congestion (light 1.2-preview mechanic) -------------------
# A plant's corridor carries LINE_HEADROOM of its nameplate before it overloads.
# GUARDRAIL: LINE_HEADROOM * firm_capacity(1350 MW) must stay >= peak (1160 MW),
# or peak demand becomes unmeetable without loss. 0.90 * 1350 = 1215 >= 1160.
LINE_HEADROOM = 0.90
CONGESTION_LOSS_FRACTION = 0.60      # fraction of overloaded MW dissipated as heat
CONGESTION_SCORE_BLEED_PER_MW = 0.05 # score/sec bled per MW of total overload
```

- [ ] **Step 4: Initialise state** — `game_state.py` `__init__`, near `self.cost_per_hour`:

```python
        self.congestion_overload_mw = 0.0
        self.congestion_loss_mw = 0.0
        self.line_overload_frac = {}   # source key -> 0..1 overload for the UI
```

- [ ] **Step 5: Add the capacity helper, effective-supply property, and calc** —
  `game_state.py` (place the helper/property near `total_actual_mw`):

```python
    def line_capacity_mw(self, source) -> float:
        return source.max_output_mw * LINE_HEADROOM

    @property
    def effective_supply_mw(self) -> float:
        """Supply that actually reaches the city — nameplate output minus what
        overloaded corridors dissipate."""
        return max(0.0, self.total_actual_mw - self.congestion_loss_mw)

    def _update_congestion(self, dt: float):
        """Per-corridor overload -> total loss, per-source fraction, and $ cost.
        Called from update() AFTER pricing so grid_price is fresh."""
        overload_total = 0.0
        frac = {}
        for s in self.sources:
            cap = self.line_capacity_mw(s)
            over = max(0.0, s.current_output_mw - cap)
            overload_total += over
            headroom_span = max(1.0, s.max_output_mw * (1.0 - LINE_HEADROOM))
            frac[s.key] = min(1.0, over / headroom_span)
        self.congestion_overload_mw = overload_total
        self.congestion_loss_mw = CONGESTION_LOSS_FRACTION * overload_total
        self.line_overload_frac = frac
        # you burn fuel for MW the wire throws away: price the loss at the margin
        if self.congestion_loss_mw > 0.0 and dt > 0.0:
            sim_hours = dt / self.seconds_per_sim_hour()
            surcharge_rate = self.congestion_loss_mw * self.grid_price
            self.cost_per_hour += surcharge_rate
            self.total_cost += surcharge_rate * sim_hours
```

- [ ] **Step 6: Route delivered supply through congestion** — `game_state.py`:

In `homes_powered`, change `self.total_actual_mw` → `self.effective_supply_mw`:

```python
    def homes_powered(self) -> float:
        return min(self.effective_supply_mw, self.demand_mw) * HOUSEHOLDS_PER_MW
```

In `update`, right after `self._update_pricing(dt)`, add:

```python
        self._update_congestion(dt)
```

Then change the `track_fill` call to use effective supply:

```python
        self.fill_pct = track_fill(self.fill_pct, self.effective_supply_mw, self.demand_mw,
                                    dt, FILL_TRACK_SPEED, MAX_FILL_PCT)
```

- [ ] **Step 7: Bleed score while overloaded** — `game_state.py` `update`, right after
  `self.score += delta` (the `score_delta` block):

```python
        if self.congestion_overload_mw > 0.0:
            bleed = CONGESTION_SCORE_BLEED_PER_MW * self.congestion_overload_mw * dt
            self.score -= bleed
            self.points["source"] -= bleed   # folded into the source-penalty bucket
```

- [ ] **Step 8: Run the test — passes**

Run: `.\.venv39\Scripts\python.exe energy_grid_game\test_congestion.py`
Expected: PASS (all three).

- [ ] **Step 9: Keep old tests green**

Run: `.\.venv39\Scripts\python.exe energy_grid_game\test_capacities.py`
and `... test_instructional.py`
Expected: both PASS (effective_supply change must not break Instructional Day 1 —
generic source max 1200 sits under its own line rating at normal output).

- [ ] **Step 10: Checkpoint** — done when Task 4 tests + existing tests are green.

---

## Task 5: Congestion — HUD readout + flow overload visual

**Files:**
- Modify: `energy_grid_game/ui/grid_flow.py` (`update_and_draw` gains `overload=`)
- Modify: `energy_grid_game/ui/iso_city.py:2199-2202` (pass `overload=`)
- Modify: `energy_grid_game/ui/hud.py:~250` (congestion badge, economics-gated)

**Interfaces:**
- Consumes: `state.line_overload_frac`, `state.congestion_overload_mw`,
  `state.show_economics`

- [ ] **Step 1: Add an `overload` channel to Flow** — `ui/grid_flow.py`

Add a hot colour constant near `PULSE`:

```python
OVERLOAD_HOT = (255, 120, 60)   # colour an overloaded corridor lerps toward
```

Change the signature and colour/size handling in `update_and_draw`:

```python
    def update_and_draw(self, surf, output, dt, color=PULSE, overload=0.0):
        """`output` is 0..1 (ramped throttle). `overload` is 0..1 — how far past
        the line's carrying capacity this corridor is; it warms the pulse toward
        OVERLOAD_HOT and fattens it, so a congested line reads hot and heavy."""
        if self.total <= 0:
            return
        ov = max(0.0, min(1.0, overload))
        color = tuple(int(color[j] + (OVERLOAD_HOT[j] - color[j]) * ov) for j in range(3))
```

(Keep the rest of the method as-is, but where `radius` is computed, add the
overload bump:)

```python
        radius = 1.5 + output * 1.8 + ov * 2.0
```

- [ ] **Step 2: Pass overload from the city** — `ui/iso_city.py`, the transmission
  loop from Task 3:

```python
            frac = state.line_overload_frac.get(key, 0.0)
            flow.update_and_draw(layer, out, dt, color=color, overload=frac)
```

- [ ] **Step 3: Draw the CONGESTION badge** — `ui/hud.py`, inside the
  `if state.show_economics:` block near the GRID PRICE line (~L250):

```python
            if state.congestion_overload_mw > 1.0:
                warn = self.font_small.render(
                    f"CONGESTION  -{state.congestion_loss_mw:,.0f} MW", True, (255, 140, 90))
                surface.blit(warn, (w // 2 - warn.get_width() // 2, y))
                y += warn.get_height() + 2
```

(Use whatever running `y` cursor and width `w` the surrounding block already uses;
place it directly below the price line so it only appears while overloaded.)

- [ ] **Step 4: Checkpoint** — render an overloaded frame and eyeball:

Run: `.\.venv39\Scripts\python.exe tools\capture_moments.py $env:TEMP\gk_task5`
In-game manual: run Gas CC to 100% while demand needs less → its corridor turns
hot, SUPPLY/balance drops below the dial total, "CONGESTION -NN MW" shows, `$/hr`
rises; spread the load and it all clears. Confirm the badge is absent on
Instructional Day 1 (`show_economics` false).

---

## Task 6: City redesign toward the reference (iterative, render-verified)

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py` (layout/density/road/palette knobs and
  transmission-node art)
- Keep green: `energy_grid_game/test_city_model.py`

**Interfaces:** none new — this is look-and-feel tuning of the existing renderer.

This task has no unit test (it is a visual target). Its cycle is **change one knob
group → render → compare to the reference → adjust**. Work in this order and render
after each step; stop when the frame reads clean, orderly and deliberately
isometric like the reference, not a tight mess.

- [ ] **Step 1: Baseline** — capture the current look for before/after comparison:

Run: `.\.venv39\Scripts\python.exe tools\capture_moments.py $env:TEMP\gk_city_before`

- [ ] **Step 2: Declutter the terrain** — reduce tree-canopy dominance and calm the
  palette (constants near `FIELD_SIZE`/`WOOD_SIZE` ~L319 and the `ROAD_*`/terrain
  colours ~L348). Lower woodland coverage and desaturate greens so the city stops
  competing with the countryside. Render and compare.

- [ ] **Step 3: Widen and regularise the road/block grid** — increase `ROAD_SPACING`
  and/or `ARTERIAL_SPACING` (~L250) so blocks are bigger and cleaner, and districts
  read as deliberate rather than a dense mesh. Render and compare. Keep
  `test_city_model.py` green after each change.

- [ ] **Step 4: Make transmission infrastructure deliberate** — strengthen the
  substation/transformer/pylon art and the corridor routing (`_route_transmission`
  ~L1730, `_substation_sites` ~L1709, and the node/pylon draw code) so the lines
  read as intentional infrastructure with clear nodes, matching the reference's
  clean isometric feel. This pairs with the Task 3 colours and Task 5 overload.
  Render and compare.

- [ ] **Step 5: Accessibility re-check** — confirm the overload/brownout easing is
  still smooth and under ~3 Hz with no large-area strobe (the docstring rule). Spot
  check `24_overload_150.png`, `25_overload_200.png`, `16_region_night.png`.

- [ ] **Step 6: Keep model tests green**

Run: `.\.venv39\Scripts\python.exe energy_grid_game\test_city_model.py`
Expected: PASS.

- [ ] **Step 7: Checkpoint** — side-by-side `gk_city_before` vs a fresh capture and
  the reference image; the city should read noticeably cleaner, less noisy, and more
  deliberately isometric. Iterate Steps 2–4 until it does.

---

## Task 7: Rewrite the dialogue in natural English (keep Gattie)

**Files:**
- Modify: `energy_grid_game/ui/tutorial_data.py` (STEPS strings)
- Modify: `energy_grid_game/ui/instructional_data.py` (DAYS strings + DAY_NOTES)
- Test: `energy_grid_game/test_dialogue_schema.py` (create)

**Interfaces:** none — only string content changes.

- [ ] **Step 1: Write the schema-invariance test** — `test_dialogue_schema.py`:

```python
"""Dialogue rewrite must not change structure. Run: python test_dialogue_schema.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from ui import tutorial_data, instructional_data

EXPECTED_STANDARD_IDS = ["intro", "readout", "city", "raise_supply",
                         "balance", "speed", "outro"]


def test_standard_step_ids_unchanged():
    assert [s["id"] for s in tutorial_data.STEPS] == EXPECTED_STANDARD_IDS


def test_conditions_keys_unchanged():
    assert set(tutorial_data.CONDITIONS) == {"supply_raised", "balanced"}
    assert set(instructional_data.CONDITIONS) == {
        "generic_raised", "balanced", "peaker_running",
        "baseload_running", "renewable_opened"}


def test_every_step_has_at_least_one_line():
    for step in tutorial_data.STEPS:
        assert step["lines"] and all(isinstance(x, str) for x in step["lines"])
    for day in instructional_data.DAYS.values():
        for step in day:
            assert step["lines"] and all(isinstance(x, str) for x in step["lines"])


def test_instructional_days_are_1_to_4():
    assert sorted(instructional_data.DAYS) == [1, 2, 3, 4]
    assert sorted(instructional_data.DAY_NOTES) == [1, 2, 3, 4]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall dialogue-schema checks passed")
```

- [ ] **Step 2: Run it — passes now (guards the rewrite)**

Run: `.\.venv39\Scripts\python.exe energy_grid_game\test_dialogue_schema.py`
Expected: PASS. (This is a guardrail, not a red-first test — it must stay green
through the rewrite.)

- [ ] **Step 3: Rewrite the strings** — use the `write` skill for tone. Convert the
  clipped fragments to natural, grammatical lines in Gattie's grizzled-veteran voice.
  Edit only the `lines` / `success["text"]` / `correction["text"]` values in
  `tutorial_data.STEPS` and `instructional_data.DAYS`, plus `DAY_NOTES`. Examples of
  the transformation:

  - `"0400 hours. Whole city's asleep. The grid never gets to be."`
    → `"It's four in the morning. The whole city's asleep — the grid never gets to be."`
  - `"Name's Gattie. Thirty years on this desk. Couple minutes, it's yours."`
    → `"Name's Gattie. Thirty years on this desk. Give me a couple of minutes and it's yours."`
  - `"Reach for gas first. It ramps in seconds. Nuclear and coal take their time."`
    → (already natural — leave or lightly smooth)

  Keep each line short enough to fit the 3-line box after wrap (roughly ≤ 120 chars
  per line at the box's width). Do not add or remove steps.

- [ ] **Step 4: Re-run the guardrail**

Run: `.\.venv39\Scripts\python.exe energy_grid_game\test_dialogue_schema.py`
Expected: PASS (structure intact).

- [ ] **Step 5: Checkpoint** — play the Standard tutorial and Instructional Days 1–4;
  every line reads as natural speech, stays in character, and fits the box without
  clipping.

---

## Final verification (all tasks)

- [ ] Run every test:
  `.\.venv39\Scripts\python.exe energy_grid_game\test_pricing.py`,
  `test_congestion.py`, `test_dialogue_schema.py`, `test_capacities.py`,
  `test_city_model.py`, `test_instructional.py` — all PASS.
- [ ] `.\.venv39\Scripts\python.exe tools\capture_moments.py $env:TEMP\gk_final` and
  review `06`, `11/12/13`, `21`, `24/25`, `16` against the reference and baselines.
- [ ] Manual pass: Standard tutorial, Instructional Days 1–4, one Scenario — no
  crashes; congestion, colours, SKIP DIALOGUE, and dialogue all behave as specified.

## Self-review notes

- Spec coverage: §1 nuclear→T1; §2 color→T3; §3 skip→T2; §4 congestion→T4+T5;
  §5 city→T6; §6 dialogue→T7. All covered.
- No pytest: all tests are self-running assert modules matching the repo's style.
- No git: every "Commit" was replaced with a "Checkpoint" per the repo rule.
- Type consistency: `line_overload_frac` (dict key→0..1), `effective_supply_mw`
  (property), `overload=` (0..1) are defined in T4 and consumed identically in T5.
