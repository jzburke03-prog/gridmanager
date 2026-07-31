# Autonomous Structure Growth and Sprite Catalog Design

**Date:** 2026-07-30

**Status:** Approved for written-spec review

## Objective

Replace procedural building shapes with an autonomous, road-accessible
structure lifecycle and a catalog of original isometric pixel-art sprites.
Buildings should have the clarity and variety of classic transport-city games
while remaining consistent with this game's coarser 8-bit style and fixed grid.

The player never places, selects, zones, demolishes, or upgrades structures.
The player affects population growth indirectly through low energy prices and
high grid reliability. The city chooses where and what to build.

## Simulation Meaning and Visual Style

Every building is residential for simulation purposes. Every occupied structure
contributes only residential population capacity.

The art catalog may nevertheless use residential-, commercial-, mixed-use-,
industrial-, and civic-looking architecture. These are cosmetic style tags for
visual variety, not jobs, zoning, production chains, or separate economies.

Production art must be original. The OpenTTD references establish readability,
density, and urban texture, not sprites to reproduce. The art direction is:

- crisp, deliberately pixelated 8-bit forms;
- nearest-neighbor scaling only;
- consistent 2:1 isometric projection and light direction;
- strong silhouettes with readable roofs, walls, windows, doors, cornices,
  setbacks, yards, parking, trees, plazas, and roof equipment;
- denser, taller forms near valuable areas and lower, more open forms at the
  fringe;
- enough palette and material variation to avoid a repeated-building field.

## Allowed Footprints

Only four footprint orientations are valid:

- 1 by 1;
- 1 by 2;
- 2 by 1;
- 2 by 2.

A footprint is a connected rectangle in logical grid space. No L-shapes,
diagonal footprints, or structures larger than 2 by 2 are allowed.

A 1 by 2 and a 2 by 1 structure have identical area and projected proportions;
one is the grid rotation of the other. Their projected ground rhombi are both
24 by 12 native pixels, slanted in opposite grid directions. Neither may appear
thicker, deeper, or larger than the other.

At the native 16 by 8 cell projection, the exact ground masks are:

| Footprint | Projected ground bounds |
| --- | --- |
| 1 by 1 | 16 by 8 pixels |
| 1 by 2 | 24 by 12 pixels |
| 2 by 1 | 24 by 12 pixels |
| 2 by 2 | 32 by 16 pixels |

Artwork may rise above these bounds but cannot claim ground outside them.

## Road Access and Parcel Rules

Every structure footprint must share at least one external cardinal edge with a
road tile. Diagonal contact does not count.

A multi-cell structure needs road access at the footprint level: at least one
of its cells must share an external cardinal edge with a road. Every component
cell does not need its own road edge. This permits coherent 1 by 2, 2 by 1, and
2 by 2 buildings while preventing isolated structures in the center of a large
block.

One logical cell is a parcel. A sprite's footprint may visually contain a
building, setback, yard, parking, trees, or plaza, but the entire footprint is
reserved for that one structure. Multi-cell buildings render as one coherent
sprite, never as stitched 1 by 1 buildings.

The full footprint becomes occupied and unavailable as soon as construction
starts.

## Construction Stages

Every new structure passes through four discrete stages:

1. **Prepared site** — plain brown cleared ground.
2. **Foundation** — a visible footprint foundation.
3. **Scaffolding** — the foundation plus active scaffolding.
4. **Finished building** — the selected building's unique completed artwork.

Stages 1, 2, and 3 are shared by every building with the same footprint and
orientation. The initial catalog therefore needs exactly **12 shared
construction sprites**: three stages for each of the four allowed footprint
orientations.

Construction time follows simulation time and stops while the game is paused.
The prepared-site stage is short, the foundation stage is longer, and the
scaffolding stage consumes the largest portion of the schedule. Larger and
taller structures take longer overall. Stage changes are discrete rather than
animated blends.

An unfinished structure houses no residents and consumes no occupied-building
power. Its intended completed capacity counts as pipeline capacity so the city
does not overbuild roads or structures while construction is already underway.
Completion enables occupancy.

The selected catalog ID, footprint, construction stage, and time remaining must
survive save/load.

## Finished and Abandoned Art

Every catalog design has two unique state sprites:

- a finished sprite;
- a matching abandoned sprite.

The abandoned sprite preserves the finished building's footprint, canvas,
anchor, orientation, and principal silhouette. It depicts state through
restrained changes such as dark or broken windows, boards, weeds, soot, roof
damage, or neglected grounds. It must still be immediately recognizable as the
same building.

One abandoned sprite may represent either demographic abandonment or physical
damage, but the simulation stores the abandonment cause separately because
their recovery rules differ.

## Sprite File Contract

Structure art ships as individual transparent RGBA PNG files plus one catalog
manifest. A runtime-generated building assembler and a mandatory texture atlas
are intentionally excluded.

Artists work on the native 1x pixel grid. A 4x nearest-neighbor export may be
stored to match the existing asset-pack convention, but every export pixel must
represent an exact 4 by 4 block from the native artwork. Smooth scaling,
anti-aliased edges, subpixel offsets, and semi-transparent fringe pixels are
prohibited.

Each footprint template defines:

- the exact projected ground mask;
- the ground-contact anchor at the southernmost footprint vertex;
- maximum horizontal overhang;
- maximum height by density tier;
- road-facing orientation;
- palette and light direction.

Canvas dimensions may vary between catalog designs to accommodate height.
Within one design, finished and abandoned files must have identical canvas
dimensions and anchor coordinates. Construction sprites use their footprint
template's anchor. At render time, all states place that anchor on the same
world-space footprint vertex, preventing jumps between construction, completion,
and abandonment.

Recommended paths are:

```text
assets/city/construction/<footprint>_<stage>.png
assets/city/buildings/<building_id>_finished.png
assets/city/buildings/<building_id>_abandoned.png
assets/city/buildings.json
```

Footprint tokens are `1x1`, `1x2`, `2x1`, and `2x2`; construction stages are
`site`, `foundation`, and `scaffold`.

## Catalog Manifest

Each building entry contains:

```json
{
  "id": "brick_row_01",
  "footprint": "1x2",
  "density": "medium",
  "capacity": 300,
  "style": "mixed_use_look",
  "weight": 1.0,
  "anchor": [48, 92],
  "finished": "city/buildings/brick_row_01_finished.png",
  "abandoned": "city/buildings/brick_row_01_abandoned.png"
}
```

`id` is stable and stored in saves. `style` is cosmetic. `weight` controls
selection frequency after eligibility and repetition penalties. The manifest
is the authoritative mapping; filenames are not parsed to infer behavior.

At minimum, asset validation must reject:

- a missing file or non-RGBA PNG;
- a duplicate or unstable ID;
- an invalid footprint, density, capacity, weight, or anchor;
- mismatched finished/abandoned canvas dimensions;
- visible ground pixels outside the footprint mask;
- a non-4x-aligned export when the asset is stored at 4x;
- anti-aliased or semi-transparent edge pixels;
- a missing finished/abandoned partner.

## Initial Inventory

The first production inventory should contain:

- 20 to 24 designs for 1 by 1;
- 8 to 10 designs for 1 by 2;
- 8 to 10 designs for 2 by 1;
- 8 to 10 designs for 2 by 2.

This is roughly 50 designs, 100 unique finished/abandoned PNGs, and 12 shared
construction PNGs. Additional buildings can be added through the manifest
without changing simulation code.

AI-generated images may be used as exploratory composition references.
Production assets require human pixel cleanup and must pass the same footprint,
anchor, palette, alpha, and paired-state validation as hand-drawn assets.

## Density and Capacity

Capacity is based on density tier and occupied footprint cells:

| Density | Minimum land value | Residents per occupied cell |
| --- | ---: | ---: |
| Low-rise | 0 | 45 |
| Medium | 35 | 150 |
| High | 60 | 600 |
| Tower | 80 | 1,300 |

For example, a 2 by 2 tower has capacity for 5,200 residents.

Meeting a land-value threshold makes a tier eligible; it does not force the
highest tier. Population pressure biases selection toward more capacity.
Neighborhood height and recent design repetition bias selection toward visual
variety. Selection is a deterministic weighted choice using the world seed and
stable growth-event identity.

The aggregate game demand curve remains authoritative. Building capacity
distributes the visible population spatially; it does not replace the game's
top-level demand calculation.

## Land Value

Land value is a smoothed score from 0 to 100. Its target value is:

| Input | Weight |
| --- | ---: |
| Centrality | 20% |
| Road access and connectivity | 15% |
| Nearby occupied structures | 15% |
| Parks, water, and open space | 10% |
| Recent local power reliability | 25% |
| Neighborhood condition, abandonment, and damage | 15% |

Positive inputs increase the target; poor reliability, abandonment, and damage
reduce their associated components. The total is clamped to 0–100. Actual land
value moves only partway toward the target on each growth tick so brief events
do not instantly transform a district.

The reliability input is local and recent rather than a lifetime city average.
Neighborhood-condition penalties are capped so one abandoned building cannot
permanently collapse a whole district.

## Autonomous Selection and Growth

On a structure-growth tick, the city:

1. calculates completed capacity, pipeline capacity, vacancy, and spatial
   population pressure;
2. reoccupies eligible demographic abandonment where pressure and value support
   it;
3. identifies vacant road-accessible footprints and redevelopment candidates;
4. filters catalog entries by footprint and eligible density;
5. penalizes designs repeated nearby;
6. makes a deterministic weighted selection;
7. reserves the footprint and begins the matching shared construction sequence;
8. requests road frontage only if existing and pipeline capacity cannot satisfy
   pressure.

Road frontage is a hard eligibility rule. A desirable but inaccessible parcel
cannot build and cannot cause the structure system to place a road itself.

## Lifecycle, Abandonment, and Redevelopment

The supported lifecycle paths are:

```text
vacant -> construction -> occupied -> redevelopment construction -> higher capacity
occupied -> demographic abandonment -> reoccupation or redevelopment
occupied -> fire/overload damage -> damaged abandonment -> redevelopment only
```

An abandoned structure:

- remains on and reserves its full footprint;
- houses no residents;
- consumes minimal or no building power;
- applies a capped local land-value penalty;
- remains eligible for the appropriate recovery path;
- stores its abandonment cause even if both causes share one sprite.

Recovery is split:

- **Demographic abandonment** may return directly to the finished occupied state
  when population pressure and land value recover.
- **Fire or grid-overload damage** cannot reoccupy directly. Recovery clears the
  old structure to the prepared-site stage and completes a new redevelopment
  construction sequence.

Existing occupied or abandoned buildings may redevelop when land value supports
a higher density. Initial redevelopment preserves the existing footprint;
automatic parcel merging and splitting are excluded. Redevelopment also
requires a meaningful capacity increase and a cooldown since the building's
last completion or state change.

## System Boundaries

The shared world model is pure simulation data and does not depend on Pygame.

The structure system owns:

- footprints and parcel reservations;
- catalog selection and stable building IDs;
- construction stages and pipeline capacity;
- occupancy, abandonment cause, and recovery;
- land value and redevelopment;
- publication of completed residential capacity.

It queries the road system for cardinal frontage and can submit a request for
more road-served capacity. It cannot place or alter roads. The road system sees
only structure occupancy and reservations, not style, density, or land value.

The renderer reads state and selects the shared construction, finished, or
abandoned sprite. It does not decide lifecycle transitions.

## Initial City

New scenarios display an established city generated before interactive play.
The bootstrap process uses the same road access, catalog selection,
construction-completion, capacity, and land-value rules in deterministic
accelerated simulation until the scenario's starting population is represented.

No construction controls are exposed to the player during or after bootstrap.
After play begins, low prices and high reliability encourage population growth;
poor service encourages outmigration and demographic abandonment; fire or grid
overload may create damaged abandonment.

## Save Data

Each structure record must preserve:

- stable catalog building ID;
- footprint cells and orientation;
- anchor-compatible render state;
- lifecycle state;
- construction stage and remaining time;
- completed or intended capacity;
- occupied population;
- land value and smoothing state;
- abandonment cause;
- redevelopment cooldown.

Save/load must reproduce catalog choices and active construction exactly rather
than rerolling them.

## Verification

Automated simulation and asset checks must demonstrate:

- only the four allowed rectangular footprints are accepted;
- every structure has footprint-level cardinal road access;
- 1 by 2 and 2 by 1 ground masks have identical 24 by 12 projected bounds;
- no footprint overlaps a road, structure, reservation, plant, or impassable
  cell;
- construction progresses through the four stages and pauses with simulation
  time;
- unfinished capacity counts as pipeline but not occupied population;
- land value stays within 0–100 and changes gradually;
- redevelopment preserves footprint and meaningfully increases capacity;
- demographic abandonment can reoccupy;
- damaged abandonment requires reconstruction;
- finished and abandoned sprites remain registered to one anchor;
- nearby repetition penalties vary appearance without breaking determinism;
- identical seeds reproduce the same catalog selections and different seeds can
  vary equivalent selections.

Visual review must inspect every footprint and state at 1x, 2x, and 4x, with
special attention to road contact, anchor stability, silhouette readability,
nearest-neighbor scaling, and equal 1 by 2 versus 2 by 1 ground thickness.

## Deferred Scope

This design does not add zoning, employment, commercial or industrial
simulation, building interaction controls, manual demolition, parcel merging,
animated construction frames, runtime procedural building assembly, or a
required texture atlas.
