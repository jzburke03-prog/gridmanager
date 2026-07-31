# Autonomous Grid and Road Growth Design

**Date:** 2026-07-30

**Status:** Approved for written-spec review

## Objective

Replace the current illustrative road sprawl with a deterministic city-growth
system on a fixed logical grid. Roads must form plausible, connected blocks and
expand only when the population needs more road-served building capacity.

This follows the OpenTTD model of indirect city influence: the player never
places, removes, or upgrades roads or structures. The player manages the energy
system. Low energy prices and high grid reliability support population growth;
the autonomous city decides how to accommodate that growth.

## World Grid

- The world is a fixed **144 by 144 logical-cell grid**.
- One logical cell projects to a **16 by 8 pixel** isometric diamond at the
  native 1x art scale.
- The existing camera zooms remain:
  - 1x: 16 by 8 displayed pixels per cell;
  - 2x: 32 by 16 displayed pixels per cell and the normal gameplay view;
  - 4x: 64 by 32 displayed pixels per cell.
- Every world object occupies one or more logical cells even when its artwork
  rises above or visually overlaps its footprint.
- Grid coordinates and simulation state are independent of Pygame and screen
  resolution.

## Player Influence and Growth Pressure

Road growth has one trigger: **unmet population pressure**.

Energy price and reliability affect population change. Population change then
creates or reduces pressure on city capacity. Roads do not react directly to a
button, cursor, power plant, or arbitrary timer.

When population pressure rises, the city must try these responses in order:

1. occupy available capacity in existing road-accessible buildings;
2. reoccupy eligible demographically abandoned buildings;
3. complete already committed construction;
4. construct or redevelop buildings on existing road frontage;
5. request a road project only when the preceding capacity is insufficient.

Completed capacity and pipeline capacity both count against pressure. This
prevents the city from ordering redundant streets while enough housing is
already under construction.

Falling population pressure does not cause automatic road demolition. It may
cause vacancy or abandonment under the separate structure lifecycle rules.

## Road-Network Invariants

- A road tile connects only north, east, south, and west in grid space.
- Diagonal road connections and diagonal-only access never count.
- Every new road must connect to the existing origin network.
- Isolated road islands are prohibited.
- A road cannot overwrite a structure, reserved building footprint, plant,
  impassable terrain, or another incompatible reserved cell.
- A road may join an existing road, subject to the intersection rules.
- The map boundary is not a road and cannot complete a perimeter.
- Road visuals derive from the cardinal-neighbor connection mask. The renderer
  selects the corresponding end, straight, corner, T, or four-way sprite.
- Local roads and arterials occupy the same one-cell grid. Their hierarchy is
  metadata and visual treatment, not a second geometry system.

## Road Projects

The growth system proposes complete **road projects**, not unrelated individual
tiles. A project contains:

- a project type and priority class;
- a cardinally connected ordered path;
- its connection point or points on the existing network;
- every cell that must remain reserved while it is built;
- the new or changed perimeters it would create;
- its score components and deterministic tie-break value;
- construction progress and temporary endpoints.

The complete path is validated before construction begins. Its cells are then
reserved and built sequentially on simulation ticks. No partial project may be
started if its completed geometry would be invalid.

The growing end of an active project is a **temporary dead end** and is exempt
from the permanent-dead-end limit. If construction is interrupted by changed
world state, the system must either retain the reservation and resume later or
cancel the unbuilt portion without leaving an invalid completed layout.

## Candidate Project Types and Priority

Candidates are considered in this strict priority order:

1. **Loop completion** — connects existing branches and removes a dead end.
2. **Oversized-block subdivision** — adds an internal street that creates
   smaller valid blocks and usable frontage.
3. **Infill street** — opens usable frontage inside or between existing
   developed areas.
4. **Outward local-road expansion** — extends the city edge toward pressure.
5. **New arterial corridor** — opens a new broad growth direction.

Priority is lexicographic: the generator selects the highest-scoring useful
candidate in the first priority class that contains a valid project. A
high-scoring arterial cannot displace an available useful loop completion.

The generator should normally propose straight runs of three to seven cells,
then deliberate turns or branches. It must reject one-cell lateral jogs.
T-intersections are ordinary; four-way intersections are less frequent.
Adjacent intersections are disfavored and may be rejected when they produce an
unreadable or wasteful pattern.

## Project Scoring

Each accepted criterion is normalized to a value from 0 to 1, then multiplied
by its weight:

| Criterion | Weight | Meaning |
| --- | ---: | --- |
| Pressure relief | 30 | How much unmet population pressure the resulting frontage can accommodate |
| Usable frontage | 25 | Number and quality of newly road-accessible buildable cells |
| Connectivity | 15 | Loop closure, alternate routes, and removal of unresolved endpoints |
| Block quality | 15 | How closely resulting blocks match the preferred size range |
| Road efficiency | 10 | Useful frontage and connectivity gained per road cell |
| Directional fit | 5 | Alignment with the spatial concentration of population pressure |

The raw weighted score is out of 100. Penalties are then subtracted for:

- unnecessary or adjacent intersections;
- one-cell zigzags;
- excess land consumption;
- avoidable duplication of a nearby parallel road;
- creating a prospective permanent dead end.

The numeric penalty constants are tuning data, but their relative order is
fixed: invalid geometry is rejected, not merely penalized; a new permanent dead
end receives the strongest remaining penalty.

Candidate generation and tie-breaking are deterministic for a saved world seed.
The same world state and seed must select the same project.

## Perimeters and Block Quality

A perimeter is an area of non-road cells fully enclosed by connected road tiles.
Its size is measured in enclosed interior grid cells.

- A 1 by 1 enclosed perimeter is prohibited.
- A 1 by 2 or 2 by 1 perimeter is valid but uncommon.
- Preferred ordinary block interiors are 3 by 3, 3 by 4, 4 by 3, and 4 by 4.
- An ordinary block may be at most six cells on either side.
- An ordinary block may contain at most four cells with no cardinal road edge,
  and those cells must form one compact group.
- Large campuses, plants, and other explicitly reserved regional features use
  separate layout rules and are not ordinary city blocks.

The four-core-cell rule permits modest depth without producing a large center
that can never participate in a road-accessible building footprint. It also
rejects a 6 by 6 ordinary block, whose 4 by 4 core would be excessive.

If one road project closes or divides several areas, every resulting area must
pass perimeter validation. A project cannot hide one invalid block behind a
larger valid result.

## Dead Ends

Temporary open branches are expected during active construction and may later
become loops or intersections. Permanent dead ends are allowed sparingly.

After a project completes, a local-road terminal is permanent when it is not
part of any active or reserved continuation. Each completed local-road project
records whether it left one or more such terminals. A candidate is rejected if
its completion would make projects with that outcome exceed **10 percent of all
completed local-road projects**. Active projects and arterial corridors are
excluded from both counts. The percentage is an initial tuning constant, but
the distinction between temporary and permanent endpoints is required.

Loop-completion candidates should preferentially consume old permanent
terminals when population pressure makes further road work necessary.

## Candidate Rejection

A proposed project is rejected before reservation when any of these is true:

- its path is diagonal, internally disconnected, or disconnected from the
  origin road network;
- any cell collides with occupied, reserved, or impassable space;
- it leaves the 144 by 144 grid;
- it creates a prohibited 1 by 1 perimeter;
- any resulting ordinary block violates side-length or core-cell limits;
- it creates an invalid intersection or one-cell jog;
- it disconnects any part of the existing network;
- it would exceed the permanent-dead-end limit;
- it does not create useful capacity, connectivity, or valid subdivision for
  the pressure that requested it.

If no project passes, population pressure remains unmet and is reconsidered on
a later growth tick. The system never forces an invalid road to make progress.

## Ownership Boundaries

The road system owns:

- grid road occupancy and reservations;
- the connected road graph and road hierarchy;
- road-project generation, validation, scoring, and construction;
- perimeter detection;
- publication of road frontage created or removed.

The structure system owns buildings, parcels, capacity, construction,
abandonment, redevelopment, and land value. It may request more frontage and
query road adjacency, but it cannot create roads. The road system sees occupied
and reserved cells, but it does not inspect building style, land value, or
lifecycle state.

Growth runs on discrete simulation ticks rather than render frames.

## Initial City

A new scenario presents an already established city. Before interactive play,
the game deterministically bootstraps the city from its origin using the same
road and structure rules in accelerated, offscreen simulation until the
scenario's starting population and capacity targets are met.

This is an initialization mechanism, not a player mode. The player never starts
placing roads or buildings and never chooses whether to watch origin growth.
Once play begins, all further city growth remains autonomous and responds only
to the simulated population pressure produced by energy price and reliability.

## Save Data

Save data must persist:

- world seed and 144 by 144 grid occupancy;
- road tiles, hierarchy, and origin-network membership;
- active project type, full path, reservations, score, and construction index;
- temporary and permanent endpoint state;
- detected block/perimeter identifiers or enough state to reproduce them
  deterministically;
- outstanding population-pressure road requests.

Loading a save must not reroll candidate selection or abandon an in-progress
project.

## Verification

Automated tests must demonstrate:

- every road is cardinal and belongs to the origin network;
- collisions and out-of-grid projects are rejected;
- 1 by 1 perimeters cannot be completed;
- ordinary blocks contain no more than four compact core cells;
- the five project classes obey their strict priority order;
- permanent dead ends stay within the configured cap while active endpoints
  remain exempt;
- identical seeds and state produce identical projects;
- different seeds can vary among otherwise equivalent candidates;
- a road request is made only after existing and pipeline capacity are
  insufficient;
- failure to find a valid project preserves pressure without corrupting the
  network.

Visual checks must cover sparse, medium, and dense cities at 1x, 2x, and 4x
zoom, including corners, T-junctions, four-way junctions, temporary endpoints,
and loop completion.

## Deferred Scope

This design does not add player road tools, zoning, road demolition, bridges,
tunnels, multiple road widths, traffic-capacity simulation, or runtime
procedural road artwork. Those features require separate designs if the game
eventually needs them.
