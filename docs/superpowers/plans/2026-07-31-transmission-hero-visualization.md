# Transmission-Hero Visualization — Plan

> Increment on the isometric-city build. Local edits only (no git — user handles VC).
> Render-verified via `tools/capture_moments.py`. Keep all six test files green.

## Design

**Goal:** Flip the visual hierarchy so the **transmission grid is the primary
graphic** — the way a grid operator's SCADA wall reads — while the isometric
city stays clearly present but recedes to a backdrop. Direction is a *middle
ground* between transmission-dominant isometric and a schematic overlay: the
towers and lines stay physical iso objects, but they gain a bright, glowing,
one-line-diagram quality on top of a dimmed city.

**Locked decisions (from brainstorming):**
- Middle ground between transmission-dominant iso and SCADA schematic overlay.
- **Bolder, not denser:** keep one corridor per plant. Prevalence comes from
  scale, brightness, and fidelity — NOT from adding a meshed network.
- City still prevalent, but clearly secondary to the grid.

**The four moves:**
1. **City recedes.** Knock the composited city + terrain back (dim/desaturate a
   modest amount) so the bright transmission pops against it. The city must stay
   readable — this is "backdrop," not "black."
2. **Transmission becomes a bright glowing overlay.** Bake the towers /
   conductors / substations onto their own layer and composite them *on top of*
   the dimmed city at full brightness, with a soft additive glow behind the
   conductors. This glow is what supplies the "operator screen" read — bright
   traces standing off a dark field — without abandoning the iso towers.
3. **Taller, bolder, higher-fidelity towers & conductors.** Raise pylon height,
   draw members at 2 px with a lit edge + shadow, add a third crossarm, and make
   conductors a bold bright core with a glow and a smoother catenary. Per-source
   colour (already in) stays, but brighter.
4. **Bigger substations + schematic node markers.** Scale up the substation
   yards, and place a bright glowing bus/node marker at every connection point
   (substations, plant switchyards, neighbourhood transformers). Those nodes +
   the glowing lines are the one-line-diagram layer that ties it to the SCADA
   reference.

**Constraints:** accessibility rules in `iso_city.py` survive (all easing/glow
pulsing smooth, < ~3 Hz, no large-area strobe — the new conductor glow must be
static or gently eased, never flashing). Day, night, 1x/2x/4x zoom, weather, and
the congestion overload-glow must all still read. `test_city_model.py` (layout
invariants) stays green.

---

## Task 1 — City recedes to a backdrop

**File:** `ui/iso_city.py` (the `draw`/composite path where `_base_day`/
`_base_night` and building layers are blitted to the frame).

- Add a tuning knob near the palette constants:
  `CITY_BACKDROP_DIM = 0.78`  # multiply the city toward muted so the grid pops
- Apply it to the composited city BEFORE transmission is drawn: multiply the
  city/terrain layer by `CITY_BACKDROP_DIM` (a `BLEND_RGB_MULT` of
  `(dim,dim,dim)`), or draw a low-alpha dark scrim over the city layer only.
  Do NOT dim the transmission overlay or the HUD.
- **Locate the exact composite site first** (the `IsoCity.draw` body that blits
  the cached bases + detail layers). This is the one architectural unknown —
  read it before editing; if the city and transmission are baked into the same
  surface, Task 2 must split them first (it does anyway).

**Verify:** render `06`, `16_region_night`; city visibly recedes but every
district/road is still legible; HUD unaffected.

## Task 2 — Transmission as a bright glowing overlay

**File:** `ui/iso_city.py` (the transmission bake at ~L1908-1928 and the draw
composite).

- Bake pylons/conductors/substations onto a dedicated `self._transmission`
  SRCALPHA surface instead of folding them into `day`/`night`. Keep a night
  variant only for the tower *steel* (multiplied), but the **conductors and
  node markers stay bright at night** (that's the point — the grid glows over a
  dark city, exactly like the operator screen).
- Build a one-time **glow**: blur-substitute by blitting the conductor/node layer
  a few times at low alpha with small offsets (or scale-down/scale-up), then
  composite glow (additive) → crisp lines on top.
- Composite order in `draw`: dimmed city → transmission glow (additive) →
  transmission crisp → plants → HUD.

**Verify:** conductors read as bright traces over the dimmed city day AND night;
no per-frame cost spike (glow baked once per resize, not per frame).

## Task 3 — Taller, bolder, higher-fidelity towers & conductors

**File:** `ui/iso_city.py` — `_pylon`, `_span`, and the bake loop.

- `_pylon`: height ~15 → ~22; members 2 px with a lit NW edge + a darker SE edge
  (cheap "AA"/shading); a third (lowest) crossarm; insulator strings as 2-px
  drops. Keep the upper crossarm the conductor attach point.
- `_span`: bold bright conductor — 2-px core in the source colour's bright
  variant, plus the Task-2 glow behind it; bump catenary steps 4 → 8 for a
  smoother sag.
- Bake: attach the double-circuit conductors at the new crossarm height; space
  towers a touch closer (46 → ~40 px) so a corridor reads as a continuous line
  of towers, not isolated pins.

**Verify:** `21_delivery_chain_close`, `13_zoom_4x_day` — towers read as tall HV
lattice; conductors bold and bright; per-source colours intact.

## Task 4 — Bigger substations + schematic node markers

**File:** `ui/iso_city.py` — `_substation`, `_transformer`, `_switchyard`, and
the bake (add node markers at `self._sub_screen`, plant `switchyard_anchor`s,
and `transformer.point`s).

- Scale substation yards up ~1.3× with more transformer-bank rows and a clearer
  busbar gantry.
- New `_node(surf, x, y, color)` helper: a bright filled marker (small
  diamond/square) with a soft ring — a SCADA bus node. Draw one at every
  connection point, in the corridor's source colour at plants/substations and a
  neutral bright at transformers.

**Verify:** connection points read as bright nodes; the plant→substation→city
chain reads as an operator one-line, not just scenery.

## Task 5 — Validate everything

- All six tests green (`test_pricing`, `test_congestion`, `test_dialogue_schema`,
  `test_capacities`, `test_instructional`, `test_city_model`).
- Render + eyeball the full moment set: `06`, `11/12/13` zoom, `16` night,
  `17-20` weather, `21` chain, `23/24/25` overload (congestion hot-glow must
  still win over the new bright conductor glow), `27/28` rush.
- Accessibility spot-check: conductor/node glow is static or gently eased,
  no strobe; night is legible.

## Open
- The "Also…" from your last message is still unresolved — fold in when you say.
- Exact `CITY_BACKDROP_DIM`, glow strength, tower height, and node size are
  first guesses to converge by render.
