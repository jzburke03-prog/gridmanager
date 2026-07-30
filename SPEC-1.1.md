# Grid Keeper 1.1 — Visualization & Instructional Mode

Status: draft spec. Supersedes the water-tank visualization from 1.0.

Three independent workstreams:

1. **Seamless isometric regional stage** replaces the water cube (§1)
2. **Standard grid capacity rebalance** to a 1750 MW fleet (§2)
3. **Instructional Mode** — a four-day guided onboarding grid (§3)

§2 is a half-day change. §1 and §3 are each substantial and can ship separately;
§3 depends on §1 only for the callout-box art placement, not functionally.

**1.1 is groundwork for 1.2.** Each power plant now has its own visible
transmission route to a neighbourhood substation. Congestion is still deferred,
but the per-route `Flow` objects preserve the independent channels that model
will attach to later (§1.6).

---

## 1. Visualization: seamless isometric regional grid

### 1.1 Rationale

The expanding/contracting water cube models supply-vs-demand as a single scalar
level in a vessel. That reads cleanly but implies electricity is *stored*, which
is exactly the misconception the game exists to correct — and it leaves no
surface to express congestion, locality, or time-of-day load at all.

Replacement: an isometric city and its surrounding power region, occupying every
pixel behind three centered translucent HUD islands. The city stops being
decorative backdrop and becomes the primary instrument. At 1x the camera reveals
more countryside; it never shrinks a finite city rectangle over a separate
background.

### 1.2 What is removed

| Item | Location |
|---|---|
| `DemandBox` (isometric tank renderer) | `ui/demand_box.py` — delete, 354 lines |
| `CityGrid` (satellite renderer) | `ui/city_grid.py` — replaced by `ui/iso_city.py` |
| `box_scale`, `box_height_px`, `box_footprint_px` | `game_state.py:214-216`, `:396-401` |
| `MAX_BOX_*`, `MIN_BOX_*`, `BOX_LERP_SPEED` | `game_state.py:25-29` |
| `ISO_HALF_WIDTH_RATIO`, `BOX_*_MARGIN`, box scale-to-fit math | `main.py:41-44`, `:264-282` |
| `_supply_mix_tint` (water tint by fuel mix) | `main.py:47` |
| `agitation` (water-surface turbulence) | `main.py:346` |
| `TOTAL_GRID_CAPACITY_MW = 1725` | `game_state.py:31` — already dead, no readers |

**Retained and unchanged:** `fill_pct` / `fill_pct_display` and
`physics/water_sim.track_fill`. The water *model* stays; only the water *vessel*
goes. `fill_pct` drives scoring (`score_delta`), the blackout/meltdown thresholds,
screen shake, and the homes-without-power readout, and it remains the substrate
the transmission-physics work in §1.6 will build on. Do not rename the module and
do not "clean up" the hydraulic vocabulary — it is load-bearing for what comes next.

**Required content edit:** `ui/tutorial_data.py:63-72`, the `"tank"` step, is written
entirely in water metaphor ("That tank is the same balance, in water"). It must be
rewritten against the city view, and its `highlight` key changes `"tank"` → `"city"`.
The `regions` dict in `main.py:289` loses `"tank"` and `"city"` becomes the full
city rect rather than the corner readout anchor.

### 1.3 Layout

The city occupies the full frame behind the HUD. `compute_layout`
([main.py:62](energy_grid_game/main.py:62)) keeps returning `chart_rect` and a
readout anchor, both now insets floating over the city rather than beside the tank.
Clock/operations, grid status, and score/economics are grouped into three rounded
semi-translucent islands centered as one row with equal 24px gaps. There is no
opaque full-width top band.

The deterministic world is sized from minimum 1x camera coverage plus overscan,
not from the default 2x view. Legal camera centers can therefore never expose a
world edge. One semantic layout feeds additive art detail:

- **1x regional:** terrain parcels, district masses, major roads, plant
  silhouettes, substations and transmission corridors;
- **2x gameplay:** building facades, lane paint, recognizable vehicles,
  switchyards, transformers and distribution branches;
- **4x inspection:** roof equipment, crossings, vehicle details, panel supports,
  equipment frames, insulators and fine service connections.

Zoom changes select cached detail layers and never regenerate the layout.

Geometry: **a road network, not a grid of blocks.** A rectilinear array of equal
cells was tried first and reads as a spreadsheet from above, which is precisely
what a real city does not look like. What a city actually shows from orbit at
night is a glowing network — light lives on the roads:

- a dense bright **core** downtown,
- ~5 **highways**: long smooth sweeps, each displaced perpendicular to its own
  heading so they do *not* all converge on downtown — every highway through the
  exact centre reads as a drawn asterisk,
- an inner **ring** loop plus an outer partial **bypass** (two complete
  concentric ellipses read as an orbital diagram),
- ~9 **arterials**, radial and gently curving,
- ~190 **neighbourhoods**: small street grids, each at its own local
  orientation, clipped to a jittered ellipse.

Curvature on every road is a smooth per-road bias, **never a per-step random
walk** — a random walk is what produced the jittery scratches this replaced.

The neighbourhoods are the load-bearing idea. Coherent street direction *within*
a neighbourhood and different directions *between* them is what makes the frame
read as a built environment rather than as noise. Their silhouettes must be
elliptical and jittered: rectangular grids leave hard rotated-rectangle edges,
and a field of those reads as scattered tiles.

**At night the neighbourhoods are not drawn as lit street grids.** At this scale
a real night image shows only major roads as distinct lines; everything between
is soft mottled glow speckled with individual lights. Drawing the grids literally
produced an orange chain-link mesh. Each neighbourhood is instead a pre-rendered
sprite — a soft elliptical haze plus fixed speckle — blitted with one alpha.

Radial, so the whole thing is an ellipse filling a wide viewport with clipping at
top and bottom — the same read as a wide crop of a real satellite night image.
Layout is generated once from a fixed-seed RNG (seed 2024) in normalised
coordinates, so a resize is a rescale and the city never rearranges itself.

**The city is not perpetually night.** A full daylit layer sits under the
lighting, so solar noon reads as a daytime aerial photograph and the night-lights
view is only what the small hours look like:

- **tree canopy** generated as multi-octave value noise, not drawn blobs — blobs
  at any size read as camouflage, noise reads as canopy. Metro areas from the
  air are mostly trees, not buildings, so green stays dominant.
- **neighbourhood streets** in asphalt grey, crowded with 1–2 px roofs. That
  fine bright speckle at lot scale is what separates built ground from open
  ground; large grey patches just swallow the road network.
- **highways and arterials** in light concrete grey, drawn over everything.
- **downtown** as a tight mass of bright roofs — a compact cluster, not a
  diffuse glow.

**Layers and cost.** Three caches, all built once per size (~120 ms at startup,
again only on resize):

| Layer | Rebuilt | Purpose |
|---|---|---|
| `_night_base` | on resize | ground + dark road surface |
| `_day_base` | on resize | the whole daylit city above |
| hood sprites | on resize | one amber + one red variant each |

Per frame the two bases are **cross-faded by sun angle** — no rebuild, so the
day/night transition is continuous rather than stepped, and the periodic hitch
of a daylight-keyed cache is gone entirely. Worst case (full night, everything
lit) measures ~3.5 ms against a 16.7 ms budget.

### 1.4 Illumination model

Two independent inputs, multiplied. This is the core of the change and the part
that must be got right.

```
awake   = AWAKE_MIN + (1 - AWAKE_MIN) * demand_level     # how much of the city wants power
served  = clamp(fill_pct, 0, 1)                          # what fraction of that it gets
lit_frac = awake * served
```

- `demand_level` is the 0..1 position on the day's demand curve
  (`DemandProfile.level_at`), already on the state object.
- `AWAKE_MIN ≈ 0.15`. At the 04:00 trough with perfect supply, ~15% of the network
  is lit: downtown plus the main arterials, everything else dark. This is what
  makes 4 AM read as 4 AM rather than as a failure.
- A road segment is lit when its stable `priority` (0..1) is below `lit_frac`.
  Priority is **rank-normalised** — the raw core-distance score is heavily
  clustered, and comparing it to `lit_frac` directly lit ~1% of the city when it
  claimed 15%. Ranking preserves the lighting order exactly while making
  `lit_frac` mean the fraction it says. Wider roads score better, so a brownout
  strips side streets before trunk arterials. Segments are stored pre-sorted, so
  the lit set is always a prefix.

Consequence worth stating plainly: a 50% supply deficit at 04:00 darkens far fewer
blocks than the same deficit at the 18:00 peak. That is correct — it matches the
existing `homes_without_power` metric, which is also demand-scaled — and it means
the player learns that *when* you are short matters as much as *how* short.

**Traffic runs off the clock, not the grid** — cars do not need electricity, so
a blackout must not empty the roads. `traffic_level(sim_hour, served)` follows a
diurnal curve with twin rush-hour peaks (08:00–10:00, 16:00–18:00), a high
midday plateau, a steep fall after 23:00 and a deep 01:00–05:00 trough. A shed
grid damps it — dark signals, closed businesses — but never below `TRAFFIC_MIN`.

Up to 2400 vehicles, each drawn as a short motion streak; a static dot at this
scale reads as noise. They traverse whole **routes** end to end, never single
segments — segment-bound vehicles shuttled along a few disconnected stretches
and left the roads beside them visibly empty. The list is pre-shuffled across
routes so thinning it for a low traffic level thins the network evenly.

In daylight traffic *brightens* rather than fades, and shifts from amber to
white: sun glinting off metal and glass is the most visible thing on a road from
the air, and it is what keeps the city readable when the streetlights cannot be.

**Time of day** comes from `ui/time_of_day`, which is the single source of truth
so the sky and the city cannot disagree. Two channels:

- `daylight(hour)` — **sun elevation**, not colour brightness. Dawn and dusk are
  warm, high-luminance skies while the sun is still on the horizon, so deriving
  daylight from the keyframe colours reads 05:00 as nearly midday. It lerps the
  ground from night-black to a green-grey terrain and the road surface from dark
  to visible, and damps streetlight strength (never to zero — the lights *are*
  the supply readout and must stay legible at noon).
- `get_time_of_day_colors(hour)` — a gentle colour cast at
  `DAYLIGHT_MAX_ALPHA ≈ 46`, **normal alpha, never additive**. Additive blending
  a bright sky colour over the whole city blows the frame to flat pastel at noon
  and floods it salmon at dusk, destroying the read the view exists to convey.

There is no separate sky backdrop. `ui/atmosphere.py` derives a deterministic
world tint and material response from the same clock: cloud shadows cross the
terrain, rain darkens the scene and adds clipped streaks, snow/ice tint surfaces
as well as adding precipitation, wind moves world effects, and heat adds a
restrained shimmer. Dynamic particles are clipped to the stage; the HUD is never
weather-tinted.

### 1.5 Overload

Do **not** hardcode 150%. `difficulty.meltdown` ranges from 1.15 (Expert) to 2.10
(Easy) across the four tiers ([scenarios.py:64](energy_grid_game/scenarios.py:64)),
so a fixed threshold would show catastrophe on a grid that is fine, or nothing at
all right up to the moment the run ends. Normalize instead:

```
over = clamp((fill_pct - 1.0) / (difficulty.meltdown - 1.0), 0, 1)
```

Severity is front-loaded (`sev = over ** 0.85`) so that being barely over is
almost invisible while 150% already looks dire. Five overlapping stages, so
nothing pops on:

| Stage | Starts at `sev` | Effect |
|---|---|---|
| Arcing | 0.10 | Slow pulses at substation nodes; road light warms |
| Fires | 0.25 | Flames along the network, denser as it worsens |
| Smoke | 0.35 | Plumes drifting up and thickening into a pall |
| Burnt-out districts | 0.60 | Neighbourhoods going dark under black scars |
| Firestorm haze | 0.50 | Red wash over the whole frame, embers on the updraught |

Calibration matters as much as the effects. An earlier cut saturated every stage
by ~140%, so 140/150/175% were indistinguishable brown mush and the city
disappeared under its own smoke. The ranges are stretched so the **meltdown line
is the maximum**, and every effect is thinned enough that the burning city still
reads as a city.

Fires burn *along the road network* rather than on arbitrary patches of ground —
it is the infrastructure being overloaded, and it keeps the network legible
instead of painting the frame orange.

However catastrophic this gets it stays inside the accessibility rule above:
all easing is smooth and under ~1.2 Hz, and none of it becomes large-area strobe.

`over = 1.0` is the meltdown line — the point where sustained occupancy ends the
run — so the visual peak and the failure condition coincide on every difficulty.
On Moderate (`meltdown` 1.75) the fires phase begins near 141% supply, which is
close to the 150% you specified; on Expert it begins near 113%, which is where it
belongs given the run ends at 115%.

Undersupply keeps the per-element out-of-phase brownout wobble from 1.0: roads
near the edge of what supply can reach sag before they drop, so a brownout reads
as the network fraying rather than snapping.

**Accessibility — do not simplify this away.** All severity animation stays slow,
smooth, low-contrast easing, capped well under 3 Hz. No hard on/off flashing on
large screen areas; large-area strobe is a photosensitive-seizure trigger. This
constraint is documented in the current `iso_city.py` module docstring and must
survive the rewrite.

### 1.6 Transmission corridors replace water pipes

The hydraulic pipe overlay is removed. Each plant now routes a visible chain from
its decorative switchyard through high-voltage corridors and a regional
substation, then through street-aligned distribution feeders and neighbourhood
transformers to homes and businesses. Lattice pylons and sagging conductors are
baked into the city, while blue pulses show the source's live `actual_pct` and
downstream served state. Offline plants keep their physical circuit but emit no
pulses; undersupply de-energises the same feeder clusters whose buildings go dark.

Switchyards contain transformers, breakers, busbars, insulators and gantries but
are deliberately aesthetic-only in 1.1: no controls, capacity, economics, failures
or click targets.

Each route owns an independent `Flow` object. That keeps the per-source channels
needed by the later carrying-capacity and congestion model without retaining the
misleading visual claim that electricity is water discharged from a control
panel. A plant at zero output leaves a dark but visible circuit.

---

## 2. Standard grid capacities

### 2.1 The table

| Source | MW | Class default today | Change |
|---|---|---|---|
| Natural Gas CC | 750 | 750 | — |
| Gas Peaker | 50 | 50 | — |
| Coal | 250 | 250 | — |
| Wind | 225 | 200 | +25 |
| Solar | 175 | 175 | — |
| Nuclear | 150 | 150 | — |
| Hydro | 150 | 150 | — |
| **Total** | **1750** | | |

Wind is the only capacity that actually moves from the class defaults. Everything
else is already at its 1.1 value in `sources/*.py` — but see §2.3, because
`STANDARD_CAPACITIES` declares a completely different set of numbers and is what
Standard runs actually load.

### 2.2 The playability constraint clears

`_ensure_playable` ([scenarios.py:102](energy_grid_game/scenarios.py:102)) enforces
a design invariant — renewables must never be *required* to meet peak — by
demanding `firm ≥ peak × 1.15`, where firm = nuclear + coal + gas + peaker + hydro.
Any shortfall is silently added to gas.

At the 1.1 capacities it is satisfied, worst month included:

```
firm actual   = 150 + 250 + 750 + 50 + 150 = 1350 MW
July peak     = 1000 × 1.16 (peak _SEASON) = 1160 MW
firm required = 1160 × 1.15                = 1334 MW   ✓ 1350 ≥ 1334
```

It clears by 16 MW. That is enough, but it is not much — raising `_SEASON`'s July
multiplier above ~1.17, raising the 1.15 headroom, or shaving firm capacity again
would push it under, at which point `_ensure_playable` starts silently adding MW
to gas and the published table quietly stops being true. Worth a comment at the
constant so the next person changing either number knows they are close to the line.

Two consequences, both good:

- **The seasonal demand multiplier stays.** The earlier draft proposed pinning
  Standard's peak flat at 1000 MW to make the numbers fit; that is no longer
  necessary. `_SEASON` ([scenarios.py:92](energy_grid_game/scenarios.py:92)) keeps
  shaping both demand and solar, and winter heating / summer AC load survive.
- **The published table is the loaded table.** `_ensure_playable` never fires, so
  it never silently rewrites gas. Today it *does* fire — Standard declares Gas CC
  at 560 MW and the game loads something larger — which means the currently
  documented capacities are already fiction. This change ends that.

Reserve margin at the July peak is 1350 ÷ 1160 ≈ 116% on firm capacity alone, with
wind, solar and hydro on top. Appropriate for the grid that Instructional Mode
graduates into.

### 2.3 Also fix the drift

`STANDARD_CAPACITIES` ([scenarios.py:85](energy_grid_game/scenarios.py:85)) and the
per-class defaults in `sources/*.py` are two separate declarations of the same
fleet, and they currently disagree — Standard declares nuclear 110 / coal 175 /
gas 560 / peaker 45 / solar 130 / wind 150 / hydro 100, none of which match the
class defaults. Update both to §2.1. On the class side only `wind.py` moves
(200→225); the rest are already correct. The class defaults are overridden by
`_apply_config` on every real run, so the disagreement is harmless today, but it
is a trap for whoever next reads one and trusts it.

---

## 3. Instructional Mode

Standard's grid and demand curve, revealed over four days. The existing one-shot
tutorial (`ui/tutorial.py` + `ui/tutorial_data.py`) stays as-is for Standard; this
mode reuses the same machinery with a day-keyed script.

### 3.1 Menu

A third card on the MODE screen, positioned left of FREE PLAY and SCENARIOS
(`ui/menu.py:255`, `_draw_mode` — currently a two-column layout centered on the
midline; becomes three). It takes no configuration screen: no region, no date,
no difficulty picker. Clicking it launches immediately, synthetic, no EIA fetch.

Plumbing: extend `TITLE, MODE, FREEPLAY, SCENARIOS, FETCHING = range(5)` to include
`INSTRUCTIONAL`, add it to `_SCREEN_NAMES`, add a `("start_instructional",)` action
in `_do`, and a `scenarios.make_instructional()` builder returning a
`RunConfig(mode="instructional", difficulty=DIFFICULTIES["easy"], ...)`.

`main.py:166` gates the tutorial on `state.config.mode == "standard"` — it must
accept `"instructional"` too.

### 3.2 Day schedule

| Day | Sources available | Teaches | HUD |
|---|---|---|---|
| 1 | `generic` only | Demand curve; supply must match it, continuously | No price, no cost |
| 2 | `gas`, `peaker` | Dynamic pricing — gas costs more as demand climbs | Price meter appears |
| 3 | + `coal`, `nuclear` | Baseload; ramp latency; nuclear cannot be dropped fast | Full |
| 4 | + `solar`, `wind`, `hydro` | Intermittency; weather; the full seven-valve grid | Full |

There is no Day 5. Confirming Day 4's summary ends the mode and returns to the
menu — see §3.9.

**Day 2 includes the peaker. Confirmed.** The peaker *is* the dynamic-pricing
lesson: gas gets expensive at peak precisely because inefficient simple-cycle
turbines get dispatched for the last slice of load, which is what `pricing.py`
models directly (`GAS_PEAK_PRICE_PER_MWH` 145 vs `PEAKER_PEAK_PRICE_PER_MWH` 240).
Splitting them would teach the price curve without its cause.

The Day 2 script should let the player *cause* the price spike rather than be told
about it — push demand into the evening peak with CC alone, watch it fall short,
open the peaker, watch the grid price jump. The HUD's marginal-price readout
already shows exactly this: `grid_price` is the cost of the most expensive source
currently dispatched ([game_state.py:461](energy_grid_game/game_state.py:461)), so
opening the peaker moves the number immediately and visibly.

### 3.3 The Day 1 valve

New `sources/generic.py`, `GenericSource(EnergySource)`:

- name `"Electricity"`, key `"generic"`
- `max_output_mw` = 1200 (peak demand plus headroom, so matching is always possible)
- ramp latency ≈ 0 both directions — the valve responds immediately
- `min_stable_output = 0`, `can_shut_down = True`, availability constant 1.0
- price 0, and never displayed

It teaches one thing — supply must track demand — with no ramp behavior, no
failure mode, and no economics to distract from it.

**Rollover hazard:** when Day 2 begins, the generic source leaves the active set.
If its output is not zeroed it keeps generating and supply silently doubles. Any
source leaving the active set on a day boundary must have `requested_pct` and
`actual_pct` forced to 0 in `start_next_day`. This is easy to miss and would
present as an unexplained oversupply on Day 2.

### 3.4 Source gating

Keep `state.sources` complete for all seven-plus sources at all times — day-to-day
history, pricing, and totals all iterate it, and a locked source sits at 0 MW and
contributes nothing. Add:

```python
@property
def active_sources(self):
    """Sources the player can see and touch today."""
```

…and use it only at the render/input boundary: plant-pin drawing, hit-testing,
and transmission-flow lookup. Nothing in the simulation changes.

### 3.5 Failure suppression

A player cannot be allowed to lose on their first day. `_trigger_game_over`
([game_state.py:340](energy_grid_game/game_state.py:340)) is the single choke point
for blackout, meltdown, and nuclear SCRAM, so one guard covers all three:

```python
if self.config.mode == "instructional" and self.day < 4:
    return
```

Days 1–3 cannot end the run. This also makes the Day 3 nuclear lesson *teachable* —
the player can be told not to drop nuclear hard, try it anyway, watch the SCRAM,
and read about it in the end-of-day summary instead of losing the session to it.
Day 4 onward, with all sources unlocked, failure is live on Easy thresholds.

### 3.6 HUD and summary gating

Add `GameState.show_economics` → `config.mode != "instructional" or day >= 2`.
`HUD.draw` already receives the whole state object, so it reads the property
directly rather than taking a new parameter. It gates the grid-price line
(`ui/hud.py:214-221`) and the total-spent readout (`ui/hud.py:159`).
`DayCompletePanel` gates its cost rows on the same property.

Per-day end-of-day narrative: an optional `day_note` string supplied by the
instructional script, rendered in the existing day-complete panel. Day 1's speaks
to balance only; Day 2's introduces spend.

### 3.7 Callout boxes

`TutorialManager` currently imports `STEPS` at module scope and indexes it
directly. One change makes it reusable:

```python
def __init__(self, font, font_small, font_body, steps=STEPS):
```

Then `ui/instructional_data.py` holds `DAYS = {1: [...], 2: [...], 3: [...], 4: [...]}`
using the identical step schema (`id`, `portrait`, `speaker`, `lines`, `highlight`,
`wait_for`, `action_hint`, `success`, `correction`) and the same `CONDITIONS`
gating mechanism. No new dialogue system.

**Learn-more hook.** Steps gain an optional `"learn_more": "<source_key>"`. When
present the box renders an extra button. The content interface is:

```python
CONTENT = {
    "solar": {"title": str, "body": [str], "link": str | None},
    ...
}
```

Delivery is deliberately unresolved — external URL, bundled PDF, or an in-game
panel — and the hook is a stub until you decide.

**The two-pagers do not exist yet, and Instructional Mode must not wait on them.**
`CONTENT` therefore ships empty, and a step whose `learn_more` key has no entry
renders no button at all — not a greyed-out one, not a "coming soon". Days 1–4 are
complete and shippable with an empty `CONTENT`; each two-pager becomes live the
moment its entry is added, with no code change. This is the only reason the
indirection exists — do not replace it with a direct link per step.

**Day 4 availability graphs.** The wind and solar peak-time curves you want are
already computable: `source.availability_fn(hour)` sampled across 24 hours is
exactly that curve, and `DemandChart` ([ui/demand_chart.py](energy_grid_game/ui/demand_chart.py))
already draws a 24-hour polyline. Reuse its plotting routine against an arbitrary
sample list. Do not add a charting dependency.

### 3.8 Completion

Day 4 is terminal. Confirming its end-of-day summary returns the player to the
menu instead of starting Day 5.

`DayCompletePanel` currently always advances (`ADVANCING_DAY` → `start_next_day`).
It needs a terminal variant: on the final instructional day the confirm button
reads **RETURN TO MENU** rather than CONTINUE, and instead of rolling the day it
sets a flag `main.py` reads to run the same transition Esc already performs —
`scene = "menu"`, `menu.open_menu()`, `audio.unduck_music()` ([main.py:192](energy_grid_game/main.py:192)).

`menu.open_menu()` reopens on `_launch_state`. Instructional launches from the MODE
screen and has no configuration screen of its own, so `_launch_state` must be set
to `MODE` for this mode — otherwise the player lands on a screen that doesn't exist.

**Persisting the marker.** Reuse `highscore.json` and its existing
`load_high_score` / `save_high_score` pair ([game_state.py:147](energy_grid_game/game_state.py:147)) —
do not add a second settings file for one boolean. `save_high_score` currently
writes `{"high_score": score}`, clobbering the whole file, so it becomes a
read-modify-write over the full dict with an `instructional_complete: true` key
added. Both functions keep swallowing `OSError`; a failed save must never crash
the loop, and a lost completion marker is a cosmetic loss.

**What the marker does:**

- The MODE screen's Instructional card renders a completed state — a check glyph
  or a COMPLETE tag. It does **not** lock or hide the mode; it stays replayable,
  and replaying it just re-runs Days 1–4 from scratch.
- It suppresses the Standard-grid tutorial. `main.py` already latches
  `tutorial_completed` for the session ([main.py:121](energy_grid_game/main.py:121));
  seed that latch from the persisted marker at startup. Someone who has finished
  four guided days should not be walked through the tank step again.

### 3.9 Events

Instructional runs with `events_enabled = False` for Days 1–3 — an unexplained heat
wave on Day 1 is noise, not teaching — and `True` from Day 4, where storms are the
lesson (rain boosts hydro, gusts spike wind, cloud cover kills solar; all three
already exist in `_make_event`). `events_enabled` is currently a per-run field on
`RunConfig`, so this needs to become day-aware for this mode.

---

## 4. Open questions

1. **Two-pager delivery — deferred, not blocking.** The two-pagers are unwritten.
   `CONTENT` ships empty and the buttons simply don't render (§3.7), so all of
   Instructional Mode can be built and shipped now. Decide later whether they open
   as a web link, a bundled PDF, or an in-game panel; the first two are a few lines
   each, the third is real authoring work.
None blocking. Everything raised during drafting is now settled:

| Decision | Where |
|---|---|
| Capacity table, 1750 MW total | §2.1 |
| Wind kept in Standard; seasonal shaping retained | §2.2 |
| Water mains kept as independent per-source channels | §1.6 |
| Overload keyed to `difficulty.meltdown`, not a fixed 150% | §1.5 |
| Generic single valve for Day 1 | §3.3 |
| Peaker unlocks on Day 2 with gas | §3.2 |
| Days 1–3 cannot end the run | §3.5 |
| Two-pagers deferred; empty `CONTENT`, no button rendered | §3.7 |
| Day 4 terminal → menu, completion marker in `highscore.json` | §3.8 |

Still deliberately out of scope for 1.1: the transmission/congestion model itself
(1.2). The present switchyards and per-route `Flow` objects are visual groundwork,
not a load-flow simulation.

## 5. Files touched

| File | Change |
|---|---|
| `ui/demand_box.py` | delete |
| `ui/iso_city.py` | isometric renderer, camera, plants, and transmission routes |
| `ui/atmosphere.py` | world-integrated time/weather sampling and clipped effects |
| `ui/sky.py` | delete; no separate sky/background layer |
| `ui/plant_pins.py` | map-native plant controls |
| `ui/pipes.py`, `ui/spigot_panel.py` | delete; replaced by transmission and plant pins |
| `physics/water_sim.py` | **untouched** — substrate for the transmission model |
| `ui/tutorial.py` | `steps=` parameter |
| `ui/tutorial_data.py` | rewrite the `tank` step |
| `ui/instructional_data.py` | new — four-day script |
| `ui/callouts.py` | new — learn-more content + stub opener |
| `ui/menu.py` | third mode card, `INSTRUCTIONAL` screen |
| `ui/hud.py` | gate price/spend on `show_economics` |
| `ui/day_panel.py` | gate cost rows; render `day_note`; terminal RETURN TO MENU variant |
| `sources/generic.py` | new — the Day 1 valve |
| `sources/*.py` | align default capacities to §2.1 |
| `scenarios.py` | `make_instructional`, `STANDARD_CAPACITIES` per §2.1 |
| `game_state.py` | drop box geometry; `active_sources`, `show_economics`, day-unlock rollover, failure guard; completion flag in the highscore read/write |
| `main.py` | drop box layout/tint/agitation; city draw; `regions` update; tutorial gate accepts `instructional`; seed `tutorial_completed` from the marker; day-panel return-to-menu |
