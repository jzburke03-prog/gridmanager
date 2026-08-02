# Grid Keeper — six-change design (2026-07-31)

## Context

Six independent requests against the real build at `D:\Github\gridmanager`
(isometric-city build, post SPEC-1.1). Each is scoped below with the files it
touches and how to verify it. They can land in any order; only the congestion
and color items share code (`ui/grid_flow.py`, `ui/iso_city.py`).

Decisions taken during brainstorming:
- SKIP DAY → **relabel to "SKIP DIALOGUE"**, keep current behaviour, fix any click bug.
- Congestion → **light mechanic with a real delivered-MW loss, plus score/cost
  penalty and a HUD readout** (see §4; playability preserved via a headroom guardrail).
- City visuals → **strong redesign toward the reference image**.
- Dialogue → keep the "Gattie" veteran-dispatcher character, fix the English.

Note: this repo has a standing "no git operations" rule. Write files locally;
do **not** commit. (Overrides the brainstorming skill's "commit the design doc" step.)

---

## 1. Nuclear price accuracy

**Problem.** [pricing.py:26](energy_grid_game/pricing.py:26) sets
`NUCLEAR_PRICE_PER_MWH = 28.0`. That is nuclear's *all-in* generating cost
(NEI 2024 ≈ $33.74/MWh), but `pricing.py` is explicitly a *marginal/dispatch*
model feeding the merit-order grid price. Nuclear's marginal cost is
fuel (~$7/MWh) + variable O&M (~$2–2.5/MWh) ≈ **$9–11/MWh**. At $28 nuclear
falsely ties gas-CC baseline ($28), so the merit order is wrong and Instructional
Day 3's "baseload is cheap" lesson doesn't hold.

**Change.** `NUCLEAR_PRICE_PER_MWH = 11.0`. Rewrite the nuclear line in the module
docstring to state this is marginal/dispatch cost and note all-in ≈ $33 is a
different figure for a different purpose. Leave coal ($38) and hydro ($8) — a
touch high but defensible; call them out in the design review if we want them moved.
Sources: NEI Costs in Context; CRS R44715.

**Files:** `energy_grid_game/pricing.py` (constant + docstring only). `nuclear.py`
reads the constant, no change.

**Verify:** launch a Standard run, open the Nuclear pin — reads `$11/MWh`; nuclear
now sits below coal/gas in the pin prices and in the day-complete "spent by source".

---

## 2. Color-code electricity to its source

**Problem.** [grid_flow.py:25](energy_grid_game/ui/grid_flow.py:25) hardcodes one
blue `PULSE` for every flow; a past decision removed per-source color. Request
reverses that: the line should read as its fuel type.

**Change.** `Flow.update_and_draw` already takes `color=`. In `ui/iso_city.py`
where the **plant→substation transmission routes** are drawn (the `_routes` /
`_flows` draw path around [iso_city.py:1946](energy_grid_game/ui/iso_city.py:1946)),
pass that plant's `source.color` instead of the default. Keep the downstream
**distribution/service** flows cool-white/blue — that power is a blend of all
sources and coloring it by one would misinform. Update the `grid_flow.py` docstring
note that claimed per-source color was dropped.

**Files:** `energy_grid_game/ui/iso_city.py` (flow draw call), `ui/grid_flow.py`
(docstring only).

**Verify:** render `06_game` and `21_delivery_chain_close`; each plant's corridor
pulses in its own color (nuclear cyan, gas orange, solar amber, etc.); distribution
into blocks stays neutral.

---

## 3. "SKIP DIALOGUE" button

**Problem.** The instructional TutorialManager is built with
`skip_label="SKIP DAY"` ([main.py:121](energy_grid_game/main.py:121)), but its
handler calls `tutorial.skip()`, which only dismisses the guided dialogue — it
does not skip the day. Label lies → reads as "doesn't work."

**Change.**
1. Rename the label to **`"SKIP DIALOGUE"`** at [main.py:121](energy_grid_game/main.py:121).
2. Reproduce the click live to confirm the hit test registers. Suspect area:
   `skip_rect` is positioned at `self.rect.top - 26`
   ([dialogue.py:225](energy_grid_game/ui/dialogue.py:225)) — if the dialogue box
   is ever placed at the top of the screen, the button lands off-screen /
   unclickable. If reproduced, clamp `skip_rect` (and the mirrored `learn_rect`)
   to stay on-screen, or move it just *inside* the box's top edge.

**Files:** `energy_grid_game/main.py` (label), possibly
`energy_grid_game/ui/dialogue.py` (clamp) and/or `ui/tutorial.py`.

**Verify:** launch Instructional Day 1; button reads "SKIP DIALOGUE"; clicking it
dismisses Gattie's dialogue and returns to play every time, at any box position
(test after a resize that forces a top placement).

---

## 4. Light congestion mechanic (score/cost penalty + readout)

**Problem/context.** No congestion model exists; SPEC-1.1 §1.6/§5 deferred it to
1.2 but left per-route `Flow` objects as the intended hook. User wants a *light*
version now, with a visible penalty.

**Design — real MW loss, plus score/cost + readout.** Each **dispatchable** source
(nuclear, coal, gas, peaker, hydro — the plants the player throttles) gets a
transmission `line_capacity_mw = max_output_mw * LINE_HEADROOM`
(`LINE_HEADROOM ≈ 0.9`, a tuning constant). Solar and wind are excluded: their
output is weather-driven ("open them and take what's there"), so a full-output
sunny/windy day must not read as the player's congestion. When a dispatchable
source's `current_output_mw > line_capacity_mw`, the excess is `overload_mw`, and:
- **MW loss (the tangible penalty):** a fraction of the overload is dissipated and
  never reaches the city — `loss_mw = LOSS_FRACTION * overload_mw`
  (`LOSS_FRACTION ≈ 0.6`, tuning constant). Sum to `congestion_loss_mw`. The
  supply the grid actually delivers becomes
  `effective_supply_mw = total_actual_mw - congestion_loss_mw`, and **this** is
  what feeds `fill_pct` (`track_fill`), the HUD SUPPLY readout, and
  `homes_powered`. So overloading a line visibly drops the balance number and can
  push you toward blackout — you feel it, not just pay for it.
- **Score:** a per-second bleed proportional to total `overload_mw`, added through
  the existing per-second scoring in `game_state.update` alongside `score_delta`.
- **Cost:** a congestion surcharge on `cost_per_hour`/`total_cost` (you burn fuel
  for MW the wire throws away as heat).
- **Readout:** a HUD "CONGESTION" badge shown only while overloaded, in the
  grid-status island ([hud.py](energy_grid_game/ui/hud.py)); gated by
  `show_economics` so it stays hidden on Instructional Day 1.
- **Visual:** the overloaded plant's corridor pulses shift from its source color
  toward hot amber/red with a thicker glow (ties into §2 — `grid_flow` gets an
  `overload` 0..1 that lerps color and radius).

**Playability guardrail (must hold).** Because delivered MW now drops under
congestion, `LINE_HEADROOM` must keep the *no-congestion* firm fleet able to cover
peak, or the grid stops being winnable:

```
firm_deliverable = LINE_HEADROOM * (nuclear+coal+gas+peaker+hydro max)
                 = 0.90 * 1350 = 1215 MW   ≥   July peak 1160 MW   ✓ (clears by 55)
```

This mirrors `_ensure_playable`'s existing firm ≥ peak invariant. Put a comment at
`LINE_HEADROOM` stating the constraint (`headroom * firm_capacity ≥ peak`), since
lowering headroom or shaving firm capacity could push it under and make peak demand
impossible to meet without incurring loss. The player can always meet peak by
spreading load and running each plant under its line rating; loss only bites when
you slam one corridor.

**Interface.** Add to `GameState`: `line_capacity_mw(source)` helper; computed
`congestion_overload_mw`, `congestion_loss_mw`, and per-source overload fraction,
updated each `update()`; `effective_supply_mw` used by fill/HUD/homes. `iso_city`/
`grid_flow` read the per-source fraction for color; `hud` reads the total for the
readout; scoring/cost read the total. Sim is the single source of truth; UI reads.

**Files:** `energy_grid_game/game_state.py` (capacity + overload/loss calc, route
`fill_pct`/supply/homes through `effective_supply_mw`, score/cost penalty),
`ui/grid_flow.py` (overload color/size), `ui/iso_city.py` (pass overload per route),
`ui/hud.py` (readout). New tuning constants near the top of `game_state.py`.

**Verify:** run one plant (e.g. Gas CC) to 100% while demand needs less → its
corridor goes red, SUPPLY and the balance % drop below what the dial shows, score
bleeds, `$/hr` rises, "CONGESTION" appears; spreading the same MW across two plants
clears all of it. Confirm Instructional Day 1 never shows congestion. Confirm a
Standard July run is still winnable at peak by distributing load
(1215 firm-deliverable ≥ 1160 peak).

---

## 5. City visuals — strong redesign toward the reference

**Goal.** The current isometric city reads as a dense, noisy tangle (heavy tree
canopy competing with the city, faint thread-like transmission lines). Target the
reference image: **clean, orderly, deliberately isometric** — distinct districts,
clear wide roads, bigger/cleaner blocks, restrained tree detail, and transmission
infrastructure (corridors, **substations, transformers, pylons**) that reads as
intentional infrastructure rather than faint threads.

**Approach (iterative, render-verified).** All in `ui/iso_city.py`:
- **Declutter:** reduce tree-canopy density and dial the palette calmer so green
  stops competing (canopy/field constants near
  [iso_city.py:319-348](energy_grid_game/ui/iso_city.py:319)); fewer, larger,
  cleaner building masses; wider road spacing (`ROAD_SPACING`, `ARTERIAL_SPACING`
  near [iso_city.py:249](energy_grid_game/ui/iso_city.py:250)).
- **Deliberate lines + transformers:** make the plant→substation corridors and the
  substation/transformer nodes visually prominent and clean (straight cross-country
  runs already exist via `_route_transmission`
  [iso_city.py:1730](energy_grid_game/ui/iso_city.py:1730)); strengthen pylon/node
  art and spacing so the network is legible. Pairs with §2 (color) and §4 (overload).
- **District order:** push the block/neighbourhood layout toward the reference's
  orderly grid-of-districts feel while keeping the fixed-seed determinism and the
  accessibility rules in the module docstring (all severity easing < 3 Hz, no
  large-area strobe — must survive).

**This is a look-and-feel target, converged with the capture harness**
(`tools/capture_moments.py` → compare `06/11/12/13/21` before/after). Acceptance is
qualitative: side-by-side, it reads clean, deliberate, and isometric like the
reference, not a tight mess. Exact constant values emerge during implementation.

**Files:** `energy_grid_game/ui/iso_city.py` (primary). Keep existing tests
(`test_city_model.py`) green.

**Verify:** re-run `tools/capture_moments.py`; review `06_game`, `11/12/13` (zoom
1x/2x/4x), `21_delivery_chain_close`, `16_region_night` against the reference and
the before shots.

---

## 6. Dialogue — natural, grammatical English (keep Gattie)

**Problem.** The tutorial and instructional scripts are written in clipped
fragments ("0400 hours. Whole city's asleep. The grid never gets to be.") that
read as stylized shorthand rather than natural speech.

**Change.** Rewrite every `lines` / `success` / `correction` string in
[tutorial_data.py](energy_grid_game/ui/tutorial_data.py) and
[instructional_data.py](energy_grid_game/ui/instructional_data.py) (plus
`DAY_NOTES`) into natural, grammatical English that keeps Gattie's grizzled
30-year-dispatcher voice. Use the `write` skill for tone. **No logic changes:**
`id`, `portrait`, `speaker`, `highlight`, `wait_for`, `action_hint`, `learn_more`,
and `CONDITIONS` all stay exactly as they are — only human-readable strings change.
Keep lines within the box's 3-line wrap budget (`DialogueBox.MAX_LINES`).

**Files:** `energy_grid_game/ui/tutorial_data.py`,
`energy_grid_game/ui/instructional_data.py`.

**Verify:** play the Standard tutorial and Instructional Days 1–4; every line reads
as natural speech, still in character, and still fits the box without clipping.

---

## Global verification

- `.venv39\Scripts\python.exe tools\capture_moments.py <dir>` after each visual
  change; eyeball against `captures/` baselines and the reference image.
- Existing tests: `test_capacities.py`, `test_city_model.py`,
  `test_instructional.py` must stay green.
- Full manual pass: Standard tutorial, Instructional Days 1–4, one Scenario.
