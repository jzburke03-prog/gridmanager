# Grid Keeper — Combined Changelog

This branch (`codex/ui-traffic-polish`) has had two development threads
running in parallel: a series of Claude Code / superpowers-driven sessions
(power-flow visualization, congestion mechanics, dialogue, and pricing) and a
separate Codex-driven visual rebuild of the city presentation. This file
merges both into one chronological history, newest first. `CHANGELOG.md`
remains the original, standalone record of the Urban Grid Visual Rebuild
entry below — this file does not replace it, it adds the rest of the story
around it.

---

## 2026-08-01 — Urban Grid Visual Rebuild

*(Codex thread — summarized here from `CHANGELOG.md`, not authored in this
session; see that file for the full original entry.)*

Rebuilt the isometric city presentation from a rural town-in-greenery scene
into a dense modern-retro urban grid: sliced open-source sprite sheets into
semantic iso asset families (roads, municipal buildings, civic details, plant
assets, block palettes), added a deterministic urban layout model (districts,
civic anchors, utility campuses, buildable blocks, parks, road metadata), and
routed transmission conductors along road corridors instead of open ground.
Power plants moved to technology-specific city-edge campuses. Overload/
underload warnings changed from a full-screen gradient wash to an edge
vignette. Added renderer budgets to cap urban blocks/tiles and avoid zoom-in
lag.

**Known issue carried from that entry:** `test_city_model.py` fails at
`test_city_size_tracks_population` — the rebuilt visual direction
intentionally keeps the city visually full instead of scaling footprint by
population, which conflicts with that test's assumption. Not yet reconciled.

---

## 2026-08-01 — Power-Flow Accuracy

*(This session.)* Fixed a real bug where the animated "electron" particles
representing power flow did not actually follow the drawn transmission
wires — they were built from a different, silently mismatched path. Also
replaced "electron speed varies by voltage" (researched and confirmed not a
real, visually distinguishable physical signal — AC drift velocity is ~0 and
signal propagation is near light-speed on every line regardless of voltage
class) with speed derived from each plant's real ramp-up responsiveness.

### Added
- `ramp_speed_px_s()` — log-scaled mapping from a plant's real
  `ramp_up_latency` (already declared per source in `sources/*.py`) to a
  fixed electron travel speed. Peaker/gas read as brisk, coal/nuclear as a
  crawl, matching the game's own tutorial dialogue.
- `LinePulse` — a traveling brightness wave for distribution and service
  lines (substation → neighbourhood transformer → house), replacing
  discrete particles downstream of the substation. Design consulted with a
  `technical-art:shader-architect` pass (traveling band, not a uniform
  blink, so it reads as "current flowing" rather than "line blinking").
  Only pulses on branches that are actually energised.
- `NON_RAMP_SPEED_PX_S` — a fixed neutral speed for solar/wind, excluded
  from the ramp-speed mapping (their `ramp_up_latency` represents throttle
  response, not a real generation-ramp characteristic — same exclusion
  precedent as the congestion mechanic's `CONGESTION_EXCLUDED_KEYS`).
- New tests: `test_grid_flow.py` (Flow speed model, LinePulse behavior,
  rate-monotonicity), plus new/updated tests in `test_city_model.py`
  (conductor-geometry accuracy, ramp-speed threading).

### Fixed
- Electron particles now built from the exact elevated/offset conductor
  point geometry the double-circuit wire is actually drawn with (both
  conductors), so they visibly ride the real wire and arrive exactly at the
  substation.
- Distribution/service `LinePulse` waves now correctly gate on camera zoom
  (previously animated even when their wire wasn't composited at the
  current zoom level — a real bug found in the final whole-branch review).
- A test that verified the ramp-speed clamp had gone vacuous after a tuning
  change; corrected to pin against the actual speed constants.
- Solar/wind had silently collapsed onto the peaker's exact speed after a
  tuning pass narrowed the ramp-latency floor; excluded them from the
  ramp-speed mapping entirely instead.

### Process notes
- Went through two implementer fix rounds on the `LinePulse` drawing code
  (a simpler-but-slower per-pixel approach was twice substituted for the
  specified per-segment one; caught by diff-vs-brief comparison both times).
- A final whole-branch review (dispatched separately from the four
  per-task reviews) caught three real cross-task integration bugs that no
  single task's review could see in isolation — all confirmed independently
  and fixed in one consolidated pass.
- All 7 test files (`test_pricing`, `test_congestion`, `test_dialogue_schema`,
  `test_capacities`, `test_instructional`, `test_city_model`,
  `test_grid_flow`) passing at the end of this work.

---

## 2026-08-01 — Deliberate Grid Diagram

*(This session.)* Reworked the transmission visuals toward instructional
accuracy and away from decorative styling, per direct feedback that the
prior pass read as a glowing "SCADA hero" effect rather than an accurate
delivery chain.

### Changed
- Removed the additive glow layer, bright unnatural conductor color, and
  haloed junction markers from the previous pass; reverted to flat
  steel-grey conductors and plain markers. Congestion's hot-color cue
  (a real fault signal) was kept as the one deliberate exception.
- Added real distribution-pole art (`_pole`), visually distinct from
  transmission towers (~1/3 height, single crossarm), placed along every
  distribution/service route — previously those were bare unadorned lines.
- Electrons confined to travel only the first 40% of each transmission
  corridor near the plant (later superseded by Power-Flow Accuracy's
  full-path fix above, once "arrive at the substation" became the
  requirement).
- Declutter pass: reduced `MAX_EXTENT` (city occupies less of the frame),
  trimmed the house palette from 5 sets to 3 for a more cohesive look.

---

## 2026-07-31 — Transmission-Hero Visualization

*(This session.)* Made the transmission grid the primary visual subject —
closer to a grid operator's SCADA wall — with the city receded to a
backdrop.

### Added
- Transmission composited as a bright glowing overlay over a dimmed city
  (dark scrim + additive glow layer).
- Taller, bolder HV lattice towers (3 crossarms, lit edges) and bold
  double-circuit conductors with a glow.
- Larger substation yards with clustered transformer banks and a busbar
  gantry; bright bus/node markers at every connection point.
- Plant control dials now float directly on the plant they control (no
  card background), colored by fuel type.
- Boxless top HUD: SUPPLY tagged "NOW", DEMAND tagged "TARGET" — explicit
  goal framing instead of a windowed panel.
- Demand-curve background now tracks time of day (dark blue at night, warm
  at dawn/dusk, brighter at midday).

*(Superseded 2026-08-01 by Deliberate Grid Diagram above, which reverted
the glow/scrim styling in favor of flat, accurate infrastructure — the
floating dials, goal-framed HUD, and time-of-day demand curve from this
pass were kept.)*

---

## 2026-07-31 — Grid Keeper: Six Changes

*(This session.)* A batch of fixes and additions spanning pricing accuracy,
a mislabeled control, visual clarity, and a new gameplay mechanic.

### Fixed
- **Nuclear pricing:** `NUCLEAR_PRICE_PER_MWH` corrected from $28/MWh (which
  was actually nuclear's *all-in* generating cost) to $11/MWh, the real
  *marginal* dispatch cost (fuel ~$7 + variable O&M ~$2.5/MWh) — the number
  the game's merit-order pricing model is supposed to use. Nuclear now
  correctly prices as the cheapest firm source.
- **"Skip Day" button:** was actually labeled "SKIP DAY" but only dismissed
  the guided tutorial dialogue — never skipped a day. Relabeled to
  "SKIP DIALOGUE" and clamped its on-screen position so it can't render
  off-screen after a resize.

### Added
- **Transmission congestion mechanic:** each dispatchable source (excluding
  weather-driven solar/wind) gets a line capacity at 90% of nameplate;
  exceeding it dissipates real delivered MW (not just a cosmetic penalty),
  bleeds score, adds a cost surcharge, and shows a HUD "CONGESTION" badge
  plus a hot-color glow on the overloaded corridor. Tuned with a guardrail
  so peak demand stays meetable by spreading load across plants.
- Per-source colored transmission flows (each plant's corridor pulses in
  its own fuel color instead of one uniform blue).

### Changed
- City visuals decluttered and transmission made visually prominent
  (taller pylons, clustered substations) as a first pass, later continued
  in the Transmission-Hero and Deliberate Grid Diagram work above.
- Tutorial and instructional-mode dialogue rewritten into natural,
  grammatical English while keeping the "Gattie" veteran-dispatcher voice
  (previously written in clipped fragments).

### Verification
All six test files passing at the end of this batch:
`test_pricing`, `test_congestion`, `test_dialogue_schema`,
`test_capacities`, `test_instructional`, `test_city_model`.
