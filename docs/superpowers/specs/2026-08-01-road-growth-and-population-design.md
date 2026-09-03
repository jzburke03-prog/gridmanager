# Road Growth and Population (sub-project A of 2)

## Context

The user supplied two externally-authored, already-approved specs to meld into
this project: `2026-07-30-grid-road-growth-design.md` (deterministic
population-pressure-driven road network growth on a discrete grid) and
`2026-07-30-structure-growth-and-sprite-catalog-design.md` (building
lifecycle: construction stages, land value, abandonment/redevelopment, a
sprite catalog). Both were written independently of this codebase and assume
a "fixed 144×144 logical grid" and a population that already responds to
price/reliability — neither of which exists here yet.

This codebase currently has a separate, already-implemented "Urban Grid
Visual Rebuild" (Codex thread, `2026-08-01-urban-grid-visual-rebuild-design.md`):
`ui/urban_blocks.py`'s `build_urban_layout()` produces a **one-shot,
seed-deterministic stamp** — a checkerboard road grid at fixed spacing plus
per-tile district/archetype assignment — regenerated wholesale from scratch
every time population, fleet, or viewport changes. There is no persistent
grid, no incremental growth, and `IsoCity._extent` (the value the failing
test checks) is a **hard-coded constant (`= 0.72`)**, never derived from
anything. This is the literal root cause of `test_city_size_tracks_population`
failing: nothing in the current code makes the city's visual extent respond
to population at all.

Investigation found the two given specs assume a *harder* problem than needs
solving here: the sprite/asset layer is already close to what
`structure-growth-and-sprite-catalog-design.md` wants (`assets/iso/manifest.json`
already has individually-addressable PNGs per entry, footprint metadata on
some entries, and — critically — **road sprites already keyed by cardinal
connectivity role** (`straight_ne/nw`, `corner_ne/nw`, `tee_ne/nw`, `cross`) —
exactly what `grid-road-growth-design.md`'s "renderer selects the
corresponding sprite from the connection mask" wants, just not actually
wired up that way today (`urban_blocks.py._road_role` currently pattern-matches
`col % 4 == 0`, never looking at real neighbors).

**Scope decision (confirmed with the user):** replace the *generation model*
(swap `urban_blocks.py`'s one-shot stamp for a persistent, incrementally-grown
network) while reusing the existing art/manifest. Build a **pragmatic
subset** of the given spec's rigor: keep whatever's cheap and foundational
(cardinal-only connectivity, connect-to-network, no overlap, no 1×1
perimeter, real neighbor-mask sprite selection), drop whatever is
city-builder rigor beyond what an energy-management game's backdrop needs
(the 6-criterion weighted scoring formula, the full 5-type strict-priority
project catalog, exact dead-end-percentage bookkeeping, save-data
persistence for road projects).

This is **sub-project A of 2**. Sub-project B (Structure Growth — the fuller
building lifecycle: construction stages, land value, abandonment/
redevelopment, the full sprite catalog manifest schema) is deferred to its
own spec/plan cycle once this one is built and stable, per its explicit
dependency ("the structure system... queries the road system for cardinal
frontage").

## Goals

1. Fix `test_city_size_tracks_population`: city visual extent and building
   count must strictly increase with population, driven by a real mechanism
   — not a coincidence of re-baking.
2. Replace `urban_blocks.py`'s one-shot regeneration with a **persistent
   world grid** that only grows, never gets thrown away and rebuilt.
3. Road placement obeys the invariants that are cheap and load-bearing for
   *not looking broken*: cardinal-only, connects to the existing network, no
   overlap with occupied/reserved cells, no 1×1 enclosed perimeter, no
   degenerate/oversized blocks.
4. Road tiles render via their real measured cardinal-neighbor connectivity
   mask (the manifest already has the right sprites; today's code doesn't
   use them correctly).
5. Population becomes a real, changing per-day metric (previously always a
   fixed constant) driven by a day's reliability + price performance,
   reusing the exact fraction the existing day-complete star rating already
   computes.
6. Existing transmission routing (`road_path_tiles`, `nearest_road_tile`)
   keeps working, pointed at the new persistent network instead of a
   freshly-baked one.
7. Just enough building placement to make growth visible and satisfy the
   test's building-count requirement — **not** the full structure lifecycle
   (that's sub-project B).

## Non-goals (explicitly out of scope for this sub-project)

- The full weighted 6-criterion scoring formula and penalty system.
- The full 5-type strict-priority project catalog (loop completion,
  oversized-block subdivision, infill, outward expansion, new arterial). Two
  types only: **infill** and **extend**.
- Exact dead-end-percentage bookkeeping (10% cap with active/arterial
  exclusions). Frontier dead ends are left alone — normal for a growing edge.
- Save-data persistence for in-progress road projects. The game does not
  persist city layout across sessions today for *any* system; adding that
  is new scope beyond either given spec, not something this melds into.
- A literal fixed "144×144" grid size — sized generously once from the
  existing viewport-derived bound instead (`required_world_size`), fixed at
  world-creation time.
- A real economic model for "price/reliability → population." A small,
  honestly-scoped per-day drift using data the game already computes
  (below), not a new economic subsystem.
- Structure lifecycle: construction stages, land value, abandonment,
  redevelopment, the full catalog manifest schema (`id`/`density`/`capacity`/
  `weight`/paired finished+abandoned sprites). All of sub-project B.

## Design

### 1. Persistent world grid

New `RoadNetwork` object (module: `ui/road_network.py`, new file — keeps
`urban_blocks.py`'s current per-tile district/archetype logic separate from
the new growth engine, per "each file has one clear responsibility").
Constructed once per city (not re-derived every bake), sized from
`required_world_size`-equivalent bounds, using the same integer `(col, row)`
tile coordinates `urban_blocks.py` already uses — no coordinate-system
rewrite. Owns:

- `roads: dict[(col,row) -> RoadTile]` — the persistent, only-grows set.
- `occupied: set[(col,row)]` — cells claimed by roads, buildings, plants, or
  reserved space (queried by both road and building placement).
- Methods to add a validated project's cells to `roads`/`occupied`
  atomically (a project either fully succeeds or is fully rejected before
  any cell is touched — no partial/invalid intermediate state).

### 2. Road invariants (kept faithful — cheap, foundational)

Every candidate project is validated before acceptance:

- Cardinal-only (N/E/S/W) connectivity; no diagonal roads.
- Every new cell connects (directly or via the project's own path) to the
  existing network — no isolated islands.
- No cell overlaps `occupied`.
- No candidate creates a fully-enclosed 1×1 perimeter (flood-fill check:
  after adding the candidate, no enclosed non-road region of exactly one
  cell).
- No candidate creates a degenerate/oversized block: enclosed regions stay
  within a sane bound (reject if any side exceeds ~6 cells or if the
  interior is absurdly large/empty) — a coarse sanity check, not the
  original spec's exact 3×3–4×4 preference scoring.

If no valid candidate exists on a given growth tick, pressure carries over
unmet to the next tick (matches the original spec's fallback behavior) —
the system never forces an invalid road.

### 3. Road tile rendering — real connectivity mask

Replace `urban_blocks.py._road_role`'s `col % 4 == 0` pattern-match with a
real neighbor lookup: for each road tile, check which of its 4 cardinal
neighbors are also road tiles, and select the matching manifest sprite key
(`straight_ne/nw`, `corner_ne/nw`, `tee_ne/nw`, `cross`) — these keys already
exist in `assets/iso/manifest.json`'s `roads` family; this is a rendering
correctness fix that costs nothing new in assets.

### 4. Growth algorithm — two project types

On each growth tick (see §6 for cadence), check in order:

1. **Existing + pipeline capacity** already covers population — do nothing.
2. **Infill** — is there a gap inside the already-built-up area (a
   buildable, road-adjacent tile not yet built on) that could absorb the
   pressure? Use it; no new road needed.
3. **Extend** — grow outward from the network frontier, in a fixed 3–5 cell
   run, toward the direction of highest local population pressure (reusing
   `urban_blocks.py`'s existing district-angle logic to bias direction).
   Validated against §2 before acceptance.

If neither resolves the pressure, it carries over.

### 5. Minimal population-scaled building placement (not full lifecycle)

The failing test requires building **count** to strictly increase with
population too, not just road extent — so this sub-project includes a
lightweight placement step: whenever a road-adjacent buildable tile becomes
available (via infill or the new frontier from an extend project), place one
building using `urban_blocks.py`'s **existing** per-tile district → archetype
→ manifest-sprite selection (unchanged), just now triggered incrementally as
the persistent grid grows instead of once per wholesale regeneration. No
footprints beyond the current 1-cell-per-building model, no construction
stages, no land value, no abandonment — all of that is sub-project B.

### 6. Bootstrap — the mechanism that actually fixes the test

`test_city_size_tracks_population` calls `_city(p)` fresh for each `p` — it
is testing "given a population target and nothing else, produce a
deterministically-sized city," which is exactly the original spec's "Initial
City" bootstrap concept. Implementation: a bootstrap routine runs the same
growth-tick logic (§4) repeatedly, offscreen and accelerated, starting from
a minimal seed network — a short fixed-length road stub at the grid origin
(enough to satisfy "connects to the existing network" for the first
extend project; not itself a project) — until existing+pipeline capacity ≥
the target population. This routine serves **both** paths:

- Test/bake path (`_city(p)`, scenario start): run to completion immediately.
- Live play: the same tick logic runs incrementally, once per real
  population-change event (see §7), never re-running from scratch.

`IsoCity._extent` stops being the hard-coded `0.72` and becomes derived from
the actual measured extent of the grown network (e.g., the furthest built
tile's normalized distance from center) — this is what makes it correctly
increase monotonically with population, and what makes it plausibly stay
under the test's `< 0.95` ceiling since growth is bounded by the fixed grid
size from §1.

### 7. Population as a per-day metric

New `GameState.population` field (previously nonexistent — `state.population`
always fell back to a fixed `ILLUSTRATIVE_POPULATION` constant). Initialized
once at game start to that same baseline, so existing modes are unaffected
until a day completes.

Updated **once per day**, inside `start_next_day()`, not continuously:

- Snapshot `time_ideal`/`time_under`/`time_over` at the *start* of each day
  (new fields), since those counters are cumulative for the whole run, not
  per-day.
- At rollover, compute that day's reliability fraction using the exact
  calculation `DayCompletePanel` already uses for its star rating:
  `day_ideal / (day_ideal + day_under + day_over)` (day deltas, not
  cumulative).
- Combine with that day's price/cost performance (`total_cost` delta or
  average `grid_price` over the day) into a population delta, capped at
  **±3% of current population per day** (first-pass tuning constant,
  adjustable by playtest — the bound itself, not its exact value, is the
  requirement: no single day may swing population drastically).

This reuses a number the player already sees rather than inventing a second
reliability metric. No new UI is required — "population ±X" on the
day-complete panel is a natural future addition but not built here unless
requested separately.

### 8. Integration points — low risk

- `road_path_tiles`/`nearest_road_tile` (BFS pathfinding, already consuming
  integer `(col,row)` tiles for transmission routing) point at the new
  `RoadNetwork.roads` instead of a freshly-baked `UrbanLayout.roads` — a
  source-of-truth swap, not a rewrite.
- Plant campus placement (`_campuses` in `urban_blocks.py`) and civic/
  district assignment logic are unaffected — they still run once to seed
  fixed campus/civic anchor positions; the persistent grid grows around them.
- `IsoCity.prepare()`'s cache-key logic (currently re-bakes on population
  *bucket* change) changes to: bake once to construct the persistent
  `RoadNetwork` and bootstrap it to the initial population, then on
  population change, run incremental growth ticks against the *same*
  network rather than re-baking from scratch.

## Testing

- `test_city_size_tracks_population` passes using the real mechanism (§6),
  not a coincidence.
- New tests: cardinal-only connectivity, no isolated islands, no overlap
  with occupied cells, no 1×1 perimeter, no oversized/degenerate block, road
  sprite selection matches real measured neighbors, infill preferred over
  extend when capacity exists inside the built area, growth ticks are
  deterministic for a fixed seed, population per-day delta uses day-scoped
  (not cumulative) reliability figures.
- Existing congestion/pricing/dialogue/instructional/grid_flow tests stay
  green (untouched by this sub-project).

## What's next (not this sub-project)

Sub-project B (Structure Growth + Sprite Catalog) builds on this once
stable: real footprints (1×1/1×2/2×1/2×2), the four-stage construction
sequence, land value, abandonment/redevelopment, and the fuller catalog
manifest schema — querying this sub-project's `RoadNetwork` for cardinal
frontage exactly as its own spec describes.
