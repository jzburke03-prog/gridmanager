# Deliberate grid diagram — city + transmission redesign

## Context

The isometric-city renderer (`ui/iso_city.py`) produces a dense procedurally-generated
region — hundreds of buildings, a road network, and glowing transmission pulses —
that looks good but doesn't *teach*. The player can't easily trace "this plant's
power goes up to transmission voltage, travels the HV line, steps back down at a
substation, and fans out on distribution to homes." The previous session's
transmission-hero pass (brighter towers, glow, colour) made the grid the visual
focus but kept the SCADA-glow aesthetic — pretty, not diagrammatic. The user wants
the game's core teaching claim — "electricity has a physical delivery chain with a
voltage hierarchy" — to be the unmistakable subject of the scene, in clean flat
pixel art, not decoration.

Approved direction from brainstorming (mockups shown, both options built and
compared): **a blend** of a compact deliberate chain-diagram layout and a
regional-map/city feel — enough city to read as a place, laid out so the full
generation → switchyard → transmission → substation → distribution chain is
legible at a glance. Camera is a **fixed composed tableau** (no free pan/zoom
required to see the whole story) **with zoom-to-inspect** on any plant or
substation for switchyard/transformer detail. Electrons are small, appear mainly
at the generating plants, and fade out along the HV line rather than animating the
whole network.

## Goals

1. **Instructionally accurate, unmistakable chain.** Every stage of real electricity
   delivery is a distinct, correctly-shaped object: generation → switchyard
   (step-up) → HV transmission (tall lattice towers, few, long spans) → substation
   (step-down) → distribution (short poles, thin lines, many branches into the
   city). The height/scale difference between transmission and distribction
   *is* the voltage lesson — not a label, a fact you can see.
2. **Clean pixel isometric city**, not a dense procedural sprawl: a compact,
   legible street grid with a few distinct building types, calm flat palette.
3. **Electrons are subtle and mainly at the source**: small warm dots emitted at
   each plant's switchyard (rate ∝ output), a faint sparse trickle along the HV
   line to the substation, then nothing — distribution/the city shows "powered"
   through window-lighting, not electron traffic.
4. **Fixed, deliberate composition** — the whole chain readable in one frame,
   with click-to-zoom into any plant/substation for switchyard detail, then
   zoom back out.
5. Keep the game's existing mechanics and player-facing behaviour intact (see
   "What's preserved").

## Non-goals

- No change to simulation, scoring, pricing, or congestion math.
- No new gameplay systems (e.g. no player control over the substation/distribution
  layer — that stays scenery, same as the current switchyards).
- Not a full free-pan/zoom regional sandbox — the previous `iso_city` region
  generator (procedural roads, ~190 neighbourhoods, traffic) is retired, not
  evolved. This is an explicit, larger rebuild, not an incremental tune.

## Design

### Composition

One fixed tableau, sized to the game's world-stage rect (as today). A compact
city sits at the center on a modest landscape: a tidy street grid (a handful of
named blocks — a couple of residential rows, one mixed/commercial row, a small
civic block), grass fields, and a river along one edge (keeps hydro's siting
logic meaningful). The seven plants sit at **fixed, sensible positions** around
the city's periphery, chosen for real-world plausibility, not random layout:

- **Hydro** — on the river.
- **Wind** — open field, away from the city (wind farms are sited for open land).
- **Solar** — a field lot, unobstructed.
- **Nuclear, Coal, Gas (CC)** — set back as heavy industry, each with its own
  switchyard, spaced so their HV lines don't cross.
- **Gas Peaker** — closer in, near a substation (peakers are sited near load).

Two (or three, if geography calls for it) **substations** sit at the city's edge,
each fed by the nearest 2–3 plants' HV lines and fanning distribution feeders
into the adjacent city blocks. Every plant, tower, and substation position is
fixed (not randomly generated) — this is a composed diagram, not a procedural
world — but still built parametrically in code (not hand-placed pixel-by-pixel)
so it can adapt to different viewport sizes/aspect ratios the way the current
renderer does.

### The delivery chain (instructional core)

Reuse and sharpen the existing primitives rather than reinventing them:

- **Switchyard** (`_switchyard`, `SWITCHYARD_TAKEOFF`) at each plant: transformer
  bank + takeoff gantry, unchanged in concept, kept small and functional-looking
  (no glow).
- **Transmission towers** (`_pylon`): the tall lattice towers built in the
  previous pass (three crossarms, splayed legs) — kept, because they're
  correctly proportioned for "this is the tallest structure in the scene."
  Reduce line COUNT to one clean corridor per plant → nearest substation (already
  the model), spaced so towers read as a deliberate row, not a maze.
- **Substation** (`_substation`): step-down yard — busbar gantry + clustered
  transformer banks — kept from the previous pass, sized clearly larger than a
  distribution pole so the step-down is visually obvious.
- **Distribution** (new, replacing the neighbourhood-transformer/feeder mesh):
  short wooden/concrete poles (a new small primitive, ~1/3 the height of a
  transmission tower, single crossarm, single thin conductor) strung along
  streets from each substation into its assigned blocks. Visually and
  structurally distinct from transmission — the height difference is the point.

No SCADA-style bright glow layer, no bus-node halos. Conductors are a flat,
readable grey/steel line; the plant's own colour is reserved for the electron
dots and the (unchanged) HUD/dial UI, not painted onto the wires.

### Electrons

Small warm particles (3 max concurrent per plant, current radius/behaviour
class reused from `grid_flow.Flow` but retuned): spawn at the plant's switchyard
takeoff point, rate scaling with `actual_pct`; travel a short distance along the
first tower span; fade to nothing well before reaching the substation (a fixed
fraction of the corridor length, not the whole run). No animated flow on
distribution feeders at all — a distribution line's "on" state is shown by
whether its fed blocks' windows are lit (existing illumination-ring model),
not by moving particles.

### Zoom-to-inspect

The composition is legible at the default camera. Clicking a plant or substation
(reusing `plant_markers`/`focus_plant` machinery already in `IsoCity`) zooms the
camera in on that structure, revealing switchyard/substation nameplate detail
(transformer banks, gantry) at higher fidelity — the existing 1x/2x/4x
`detail_levels_for_zoom` tiering is reused for this, not rebuilt.

### Clean pixel style

Flat colours, a restrained palette (the existing `GRASS`/`FIELDS`/roof-set
constants are a reasonable starting point but should be tightened — fewer hue
variants, more consistent value steps), crisp 1px outlines, no additive glow, no
per-pixel noise canopy at this smaller scale (trees become a few placed clusters,
not a generated forest). Day/night and weather (`atmosphere.py`, `time_of_day.py`)
are unchanged — the new scene still cross-fades and takes rain/snow/wind.

### What's preserved (do not change)

- **Simulation**: `game_state.py` congestion, pricing, scoring — no changes.
- **Plant dials**: `ui/plant_pins.py` floating dial-on-plant behaviour from the
  last session stays; pins still anchor to `plant_markers()`.
- **City illumination model**: served/activity two-input lighting
  (`served_fraction`, `activity_level`, ring-based shedding) — reused as-is
  against the new (smaller, fixed) building set.
- **Congestion visual**: an overloaded plant's own transmission corridor still
  heats/glows hot per `line_overload_frac` — this is the one place a stronger
  colour cue is earned (it signals a real fault state), so it is not covered by
  "no glow."
- **HUD**: goal-framed NOW/TARGET readout, boxless top scrim, time-of-day demand
  curve — all from the prior session, untouched.
- **Public interface** `main.py` depends on: `IsoCity.draw`, `.prepare`,
  `.plant_markers`, `.draw_homes_label`, `.pan_by`, `.zoom_at`, `.focus_plant`,
  `.camera` — signatures unchanged so `main.py` needs no changes beyond what a
  smaller world naturally implies (camera bounds).

## Scope / approach

**Revised after reading the current implementation** (this replaces the
brainstorming-time assumption that the whole procedural generator needed
replacing): `_layout`/`_place_plants` already place the city, plants, and
substations **deterministically from a fixed seed and fixed bearings**
(`_PLANT_ANGLES`, `_SUB_ANGLES`) — every game already renders the same
composition for a given viewport size and fleet. That satisfies "fixed
composed tableau" as-is. The actual gaps between today's scene and the spec's
goals are narrower and more mechanical:

1. **Glow/SCADA styling must come out.** The previous session's transmission-hero
   pass added an additive glow layer, a bright unnatural cyan conductor colour,
   and haloed "bus node" markers — exactly the decorative treatment this spec
   rejects in favour of flat, accurate infrastructure. Revert to flat steel-grey
   conductors, plain small junction markers, no additive glow, no backdrop
   scrim tied to glow (a light, non-glow legibility scrim may stay if it reads
   as "deliberate," but nothing additive/bright).
2. **Distribution has no real pole art.** Today a "distribution line" is a bare
   1px grey line from substation to a `_transformer` icon to buildings — there
   is no pole structure, so it doesn't visually contrast with a transmission
   tower. Add a real `_pole` primitive (short, single crossarm, single thin
   conductor, ~1/3 tower height) and place poles along each distribution/
   service route, the same way `_pylon` towers already stride a transmission
   corridor.
3. **Electrons animate the whole network, including distribution.** `Flow`
   objects currently drive particles on `_distribution_flows` and
   `_service_flows` too. Per spec, distribution must show NO particle
   animation (state shown by window-lighting only) and transmission particles
   must fade out well before the substation, not travel the full corridor.
4. **The city reads dense/busy, not clean and compact.** Tighten the palette
   (fewer, more consistent hue steps) and reduce building/tree density so the
   town reads as a compact, legible place rather than a procedural sprawl —
   tuning existing knobs (`ILLUSTRATIVE_POPULATION`, `MAX_EXTENT`, `CAPACITY`,
   canopy/woodland density), not new generation logic.
5. **Substation vs. pole size must read as the voltage step-down.** Already
   true in scale (substation yard >> a single pole) once poles exist; confirm
   during the render pass.

The drawing primitives being reused are unchanged: `_pylon`, `_span`,
`_substation`, `_switchyard`, `_transformer`, `_shed`, `_tank`, `_sphere`,
house/building box drawers, the lighting-ring system, the overload/fire system,
the camera, and the deterministic `_layout`/`_place_plants`/
`_route_transmission`/`_build_distribution` placement logic itself. Nothing
about world sizing, population scaling, or camera/zoom changes.

`test_city_model.py` mostly still applies (it tests the illumination model,
camera, zoom tiers, vehicle sprites — all unchanged). It needs updates only
where it asserts on things this plan changes: any coupling to the glow/scrim
constants being removed, and any assumption that distribution flows animate.

## Open questions (resolved for this spec)

- **Exact building/block count**: left to implementation to converge visually
  (target: legible, not sparse — a "town," not a village) via the capture
  harness, not fixed here.
- **Number of substations**: 2 as the default target (city has two edges facing
  its plant clusters); implementation may use 3 if plant geometry makes lines
  cross otherwise. Not a hard constant.
- **Distribution pole art**: new primitive, described functionally above; exact
  pixel dimensions converge during implementation.
