# Road Growth and Population Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use the `engineering:gameplay-coder` agent type as the implementer for every task (matching this project's established pattern) — its remit is exactly this class of work. Tasks 1-4 involve genuine algorithmic complexity (deterministic constraint validation, tick-based procedural growth) confirmed via `procedural:constraint-designer` and `procedural:pcg-architect` consults during planning — use a standard-tier model, not the cheapest, for those four.

**Goal:** Replace the city's one-shot, non-growing road/building stamp with a
persistent, incrementally-growing road network driven by population pressure,
fixing `test_city_size_tracks_population` for real and giving population a
genuine per-day value instead of a fixed constant.

**Architecture:** A new `RoadNetwork` object (new file `ui/road_network.py`)
owns a persistent set of road cells that only ever grows, via a single
`grow_tick()` function reused by both an offscreen bootstrap (population
target → deterministic starting city) and live incremental growth (population
changes once per in-game day). `ui/iso_city.py`'s `_layout()` is rewired to
own this persistent network instead of calling `build_urban_layout()` fresh
every bake; its giant rasterization loop in `_bake()` is untouched — it's
agnostic to where `self._tiles` came from. `game_state.py` gains a real
`population` field updated once per day from the same reliability fraction
the day-complete panel's star rating already computes.

**Tech Stack:** Python 3.9 (`.venv39`), pygame 2.6. Tests are plain-assert
self-runner modules (no pytest), run via
`./.venv39/Scripts/python.exe energy_grid_game/<test>.py` from
`D:/Github/gridmanager`. No git operations — the user handles version control.

## Global Constraints

- Cardinal-only (N/E/S/W) road connectivity — no diagonal moves, anywhere
  (path steps, network-touch checks, flood-fill adjacency all use the same
  4-connected model — confirmed by the constraint-designer consult as the
  one consistency rule that matters most here).
- Every new road project must connect to the existing network; no isolated
  islands. No cell overlaps `occupied`. No candidate creates a 1×1 enclosed
  perimeter or an oversized/degenerate enclosed block (bbox side > 6 cells,
  or interior cell count > ~30-36 — coarse sanity, not exact scoring).
- Only two project types: **infill** (use a buildable gap inside the built
  area) and **extend** (grow the frontier 3-5 cells outward). No loop
  completion, subdivision, or arterial project types.
- No exact dead-end-percentage bookkeeping. No save-data persistence for
  road projects (the game doesn't persist city layout across sessions today
  for any system).
- World grid is sized once from the existing `required_world_size`-derived
  bound, fixed at network-creation time — not literally "144×144", not
  re-derived every bake.
- Population changes **once per in-game day**, at `start_next_day()`, not
  continuously — capped at **±3% of current population per day** (first-pass
  tuning constant).
- Determinism: same population target → same bootstrapped network, every
  time. RNG for each growth tick is derived from `hash((master_seed,
  tick_index))`, `tick_index` a field on `RoadNetwork` incremented on every
  attempt (success or failure) — never a single mutated `random.Random`
  carried across ticks (confirmed by the pcg-architect consult as the
  detail that avoids call-order-dependent determinism).
- `RoadNetwork` maintains `frontier_bounds` and `capacity` as running state,
  updated O(1) at commit time — never recomputed by scanning all cells.
- Bootstrap is bounded by two independent counters: `max_ticks` (500) and
  `max_consecutive_failures` (20). Never silently returns a network under
  target capacity — raises a distinct, debuggable exception instead.

---

## Task 1: `RoadNetwork` core data model + occupancy

**Files:**
- Create: `energy_grid_game/ui/road_network.py`
- Test: `energy_grid_game/test_road_network.py` (create)

**Interfaces:**
- Consumes: `ui.urban_blocks.UrbanRoad` (existing dataclass: `col, row, role,
  avenue` — reused as-is so the renderer's existing `hasattr(extra, "role")`
  / `.avenue` duck-typing in `iso_city.py._bake` keeps working unchanged).
- Produces: `RoadNetwork` class with fields `roads: dict[(int,int),
  UrbanRoad]`, `occupied: set[(int,int)]`, `road_cells: set[(int,int)]`,
  `frontier_bounds: tuple[int,int,int,int]` (min_col, max_col, min_row,
  max_row), `capacity: float`, `tick_index: int`, `master_seed: int`.
  `RoadNetwork.__init__(self, master_seed: int)`.
  `RoadNetwork.commit_project(self, cells: list[(int,int)], role_for: Callable,
  avenue: bool, capacity_delta: float) -> None`.

- [ ] **Step 1: Write the failing test**

```python
"""RoadNetwork core data model checks. Run: python test_road_network.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from ui.road_network import RoadNetwork


def test_new_network_starts_empty():
    net = RoadNetwork(master_seed=1)
    assert net.roads == {}
    assert net.occupied == set()
    assert net.road_cells == set()
    assert net.capacity == 0.0
    assert net.tick_index == 0


def test_commit_project_updates_roads_occupied_and_capacity():
    net = RoadNetwork(master_seed=1)
    cells = [(0, 0), (1, 0), (2, 0)]
    net.commit_project(cells, role_for=lambda c, r: "straight_ne",
                       avenue=False, capacity_delta=150.0)
    assert set(net.roads) == set(cells)
    assert net.road_cells == set(cells)
    assert net.occupied >= set(cells)
    assert net.capacity == 150.0
    for cell in cells:
        assert net.roads[cell].role == "straight_ne"
        assert net.roads[cell].avenue is False


def test_commit_project_updates_frontier_bounds_incrementally():
    net = RoadNetwork(master_seed=1)
    net.commit_project([(0, 0)], role_for=lambda c, r: "cross",
                       avenue=False, capacity_delta=0.0)
    assert net.frontier_bounds == (0, 0, 0, 0)
    net.commit_project([(5, -2), (5, -1)], role_for=lambda c, r: "cross",
                       avenue=False, capacity_delta=0.0)
    assert net.frontier_bounds == (0, 5, -2, 0)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall road_network checks passed")
```

- [ ] **Step 2: Run it — must FAIL**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_road_network.py`
Expected: `ModuleNotFoundError: No module named 'ui.road_network'`.

- [ ] **Step 3: Write `ui/road_network.py`**

```python
"""Persistent, incrementally-growing road network.

Replaces the one-shot regeneration in `urban_blocks.build_urban_layout` for
the ROAD layer specifically: once created, a `RoadNetwork`'s cells only ever
get added, never thrown away and rebuilt. This is what makes population-
driven growth possible at all -- a wholesale regenerate-from-scratch model
has nothing to grow.

Cardinal-only (N/E/S/W) connectivity throughout: path steps, network-touch
checks, and flood-fill adjacency all use the same 4-connected model. Mixing
adjacency models here is exactly the kind of inconsistency that produces
topologically-wrong-looking roads.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ui.urban_blocks import UrbanRoad

CARDINAL_OFFSETS = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class RoadNetwork:
    """Persistent road grid. `commit_project` is the only way cells are ever
    added -- always atomic, always pre-validated by the caller (see
    ui/road_growth.py's `_validate_candidate`)."""

    master_seed: int
    roads: dict = field(default_factory=dict)          # (col,row) -> UrbanRoad
    occupied: set = field(default_factory=set)          # roads + buildings + plants + reserved
    road_cells: set = field(default_factory=set)        # roads only, dedicated set (hot path for flood-fill)
    frontier_bounds: tuple | None = None                # (min_col, max_col, min_row, max_row)
    capacity: float = 0.0
    tick_index: int = 0

    def commit_project(self, cells, role_for, avenue: bool, capacity_delta: float) -> None:
        """Add a validated project's cells to the network atomically.
        `role_for(col, row)` returns that cell's connectivity-mask role
        string (see ui/road_growth.py's `assign_roles`), computed by the
        caller AFTER all cells are notionally placed, so roles reflect the
        final connectivity, not a partial in-progress state."""
        for (col, row) in cells:
            self.roads[(col, row)] = UrbanRoad(col=col, row=row,
                                               role=role_for(col, row), avenue=avenue)
            self.occupied.add((col, row))
            self.road_cells.add((col, row))
            if self.frontier_bounds is None:
                self.frontier_bounds = (col, col, row, row)
            else:
                min_c, max_c, min_r, max_r = self.frontier_bounds
                self.frontier_bounds = (min(min_c, col), max(max_c, col),
                                        min(min_r, row), max(max_r, row))
        self.capacity += capacity_delta
```

- [ ] **Step 4: Run the test — must PASS**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_road_network.py`
Expected: all 3 tests print `ok`, then "all road_network checks passed".

- [ ] **Step 5: Checkpoint** — confirm `UrbanRoad` import matches
  `urban_blocks.py`'s actual dataclass fields (`col, row, role, avenue`) by
  re-reading that file's `UrbanRoad` definition before moving to Task 2.

---

## Task 2: Candidate validation (constraint system)

**Files:**
- Modify: `energy_grid_game/ui/road_network.py`
- Modify: `energy_grid_game/test_road_network.py`

**Interfaces:**
- Consumes: `RoadNetwork.occupied`, `RoadNetwork.road_cells` (from Task 1).
- Produces: `validate_candidate(network: RoadNetwork, cells: list[(int,int)]) -> tuple[bool, str]`
  — `(True, "")` if valid, `(False, reason)` if rejected, `reason` one of
  `"diagonal"`, `"occupied"`, `"disconnected"`, `"enclosed_1x1"`, `"oversized_block"`.

This task implements the exact algorithm from the `procedural:constraint-designer`
consult: bounded-window flood-fill (margin 8, boundary-touch = open), checks
ordered cheapest-first, single dict+set data model.

- [ ] **Step 1: Write the failing tests** — append to `test_road_network.py`:

```python
from ui.road_network import validate_candidate


def _seed_network():
    net = RoadNetwork(master_seed=1)
    net.commit_project([(0, 0), (1, 0), (2, 0)], role_for=lambda c, r: "straight_ne",
                       avenue=False, capacity_delta=0.0)
    return net


def test_rejects_diagonal_step():
    net = _seed_network()
    ok, reason = validate_candidate(net, [(2, 0), (3, 1)])
    assert not ok and reason == "diagonal"


def test_rejects_disconnected_from_network():
    net = _seed_network()
    ok, reason = validate_candidate(net, [(10, 10), (11, 10)])
    assert not ok and reason == "disconnected"


def test_rejects_occupied_cell():
    net = _seed_network()
    net.occupied.add((3, 0))
    ok, reason = validate_candidate(net, [(2, 0), (3, 0)])
    assert not ok and reason == "occupied"


def test_accepts_valid_extension():
    net = _seed_network()
    ok, reason = validate_candidate(net, [(3, 0), (4, 0), (5, 0)])
    assert ok and reason == ""


def test_rejects_1x1_enclosure():
    net = RoadNetwork(master_seed=1)
    # a ring around a single empty cell: (1,0),(1,2),(0,1),(2,1) already
    # placed, candidate closes the last side by completing the loop through
    # (2,0) -> the interior (1,1) becomes a fully enclosed 1x1 pocket.
    net.commit_project([(1, 0), (0, 1), (1, 2)], role_for=lambda c, r: "straight_ne",
                       avenue=False, capacity_delta=0.0)
    ok, reason = validate_candidate(net, [(2, 1), (2, 0)])
    assert not ok and reason == "enclosed_1x1"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall road_network checks passed")
```

- [ ] **Step 2: Run it — must FAIL**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_road_network.py`
Expected: `ImportError: cannot import name 'validate_candidate'`.

- [ ] **Step 3: Add `validate_candidate` to `ui/road_network.py`**

Add after `RoadNetwork`:

```python
FLOOD_WINDOW_MARGIN = 8         # cells beyond the candidate's bbox, each side
MAX_ENCLOSED_SIDE = 6            # reject if an enclosed region's bbox exceeds this
MAX_ENCLOSED_CELLS = 34          # reject if an enclosed region has more cells than this
FLOOD_FILL_CAP = 60              # safety valve: treat as oversized if fill runs this long


def _is_diagonal_free(cells) -> bool:
    for (c0, r0), (c1, r1) in zip(cells, cells[1:]):
        if (c1 - c0, r1 - r0) not in CARDINAL_OFFSETS:
            return False
    return True


def _touches_network(network: RoadNetwork, cells) -> bool:
    if not network.road_cells:
        return True   # first-ever project has nothing to connect to yet
    cell_set = set(cells)
    for (col, row) in cells:
        for dc, dr in CARDINAL_OFFSETS:
            neighbor = (col + dc, row + dr)
            if neighbor in network.road_cells and neighbor not in cell_set:
                return True
    # also valid if the path is internally connected AND its own first/last
    # cell directly abuts the network (covers a path that only touches at
    # one end)
    return False


def _find_enclosed_region(network: RoadNetwork, hypothetical_roads: set, start: tuple) -> set | None:
    """Flood-fill from `start` (a non-road cell adjacent to the new project)
    within a bounded window. Returns the enclosed region's cells if it never
    touches the window boundary (truly enclosed), or None if it escapes
    (open) or exceeds the size cap (treated as oversized -> caller rejects)."""
    min_c, max_c, min_r, max_r = network.frontier_bounds or (start[0], start[0], start[1], start[1])
    min_c = min(min_c, start[0]) - FLOOD_WINDOW_MARGIN
    max_c = max(max_c, start[0]) + FLOOD_WINDOW_MARGIN
    min_r = min(min_r, start[1]) - FLOOD_WINDOW_MARGIN
    max_r = max(max_r, start[1]) + FLOOD_WINDOW_MARGIN

    seen = {start}
    queue = [start]
    while queue:
        if len(seen) > FLOOD_FILL_CAP:
            return set()   # oversized: caller treats an over-cap result as a reject
        col, row = queue.pop()
        for dc, dr in CARDINAL_OFFSETS:
            nc, nr = col + dc, row + dr
            if (nc, nr) in seen:
                continue
            if nc <= min_c or nc >= max_c or nr <= min_r or nr >= max_r:
                return None   # escaped the window -> open, not enclosed
            if (nc, nr) in hypothetical_roads or (nc, nr) in network.occupied:
                continue      # walls don't get filled
            seen.add((nc, nr))
            queue.append((nc, nr))
    return seen


def validate_candidate(network: RoadNetwork, cells: list) -> tuple:
    """Validate a candidate project BEFORE it is committed. Checks ordered
    cheapest-first (per the constraint-designer consult): topology checks
    are O(path length); the enclosure check is the only O(window^2) one, so
    it runs last."""
    if not _is_diagonal_free(cells):
        return False, "diagonal"
    for cell in cells:
        if cell in network.occupied:
            return False, "occupied"
    if not _touches_network(network, cells):
        return False, "disconnected"

    hypothetical_roads = network.road_cells | set(cells)
    checked_starts = set()
    for (col, row) in cells:
        for dc, dr in CARDINAL_OFFSETS:
            start = (col + dc, row + dr)
            if start in hypothetical_roads or start in network.occupied or start in checked_starts:
                continue
            checked_starts.add(start)
            region = _find_enclosed_region(network, hypothetical_roads, start)
            if region is None:
                continue   # escaped -> open, fine
            if len(region) == 1:
                return False, "enclosed_1x1"
            cols = [c for c, _r in region]
            rows = [r for _c, r in region]
            side = max(max(cols) - min(cols) + 1, max(rows) - min(rows) + 1)
            if side > MAX_ENCLOSED_SIDE or len(region) > MAX_ENCLOSED_CELLS:
                return False, "oversized_block"
    return True, ""
```

- [ ] **Step 4: Run the tests — must PASS**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_road_network.py`
Expected: all 8 tests (3 from Task 1 + 5 new) print `ok`, then "all
road_network checks passed".

- [ ] **Step 5: Checkpoint** — trace `test_rejects_1x1_enclosure` by hand
  against the implementation before moving on: confirm the flood-fill from
  the interior cell `(1,1)` finds only itself, never escapes the 8-cell
  margin window, and returns a region of size 1.

---

## Task 3: Candidate generation (infill + extend) + `grow_tick`

**Files:**
- Modify: `energy_grid_game/ui/road_network.py`
- Modify: `energy_grid_game/test_road_network.py`

**Interfaces:**
- Consumes: `RoadNetwork`, `validate_candidate` (Tasks 1-2).
- Produces: `TickResult` (simple string-constant enum:
  `GREW = "grew"`, `NO_CAPACITY_NEEDED = "no_capacity_needed"`,
  `NO_VALID_CANDIDATE = "no_valid_candidate"`).
  `grow_tick(network: RoadNetwork, target_capacity: float, pressure_direction: tuple[float,float] = (1.0, 0.0)) -> str`
  (returns one of the `TickResult` values).

- [ ] **Step 1: Write the failing tests** — append to `test_road_network.py`:

```python
from ui.road_network import grow_tick, TickResult


def test_grow_tick_does_nothing_when_capacity_already_covers_target():
    net = _seed_network()
    net.capacity = 500.0
    result = grow_tick(net, target_capacity=200.0)
    assert result == TickResult.NO_CAPACITY_NEEDED
    assert net.tick_index == 1   # tick_index still advances -- it's an attempt counter


def test_grow_tick_extends_frontier_when_capacity_insufficient():
    net = _seed_network()
    net.capacity = 0.0
    before = len(net.roads)
    result = grow_tick(net, target_capacity=200.0)
    assert result == TickResult.GREW
    assert len(net.roads) > before
    assert net.capacity > 0.0


def test_grow_tick_is_deterministic_for_a_fixed_seed():
    net_a = _seed_network()
    net_b = _seed_network()
    grow_tick(net_a, target_capacity=200.0)
    grow_tick(net_b, target_capacity=200.0)
    assert net_a.roads.keys() == net_b.roads.keys()
    assert net_a.tick_index == net_b.tick_index


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall road_network checks passed")
```

- [ ] **Step 2: Run it — must FAIL**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_road_network.py`
Expected: `ImportError: cannot import name 'grow_tick'`.

- [ ] **Step 3: Add `TickResult` and `grow_tick` to `ui/road_network.py`**

Add `import random` and `import math` to the top of the file (alongside
the existing `from __future__ import annotations`), then add:

```python
CAPACITY_PER_ROAD_CELL = 60.0    # illustrative capacity a road cell's frontage unlocks
EXTEND_RUN_MIN, EXTEND_RUN_MAX = 3, 5
MAX_CANDIDATE_RETRIES = 5


class TickResult:
    GREW = "grew"
    NO_CAPACITY_NEEDED = "no_capacity_needed"
    NO_VALID_CANDIDATE = "no_valid_candidate"


def _tick_rng(network: RoadNetwork) -> "random.Random":
    return random.Random(hash((network.master_seed, network.tick_index)))


def assign_roles(network: RoadNetwork, hypothetical_roads: set):
    """Connectivity-mask role for every cell in `hypothetical_roads`, from
    its ACTUAL cardinal neighbors within that same set -- matches the
    manifest's road sprite keys exactly (see ui/road_growth.py Task 5)."""
    def role_for(col, row):
        n = (col, row + 1) in hypothetical_roads or (col, row - 1) in hypothetical_roads
        e = (col + 1, row) in hypothetical_roads or (col - 1, row) in hypothetical_roads
        # `n`/`e` here mean "has a neighbor along the row axis / col axis" --
        # translate the 4 cardinal neighbor booleans into the manifest's role keys.
        up = (col, row - 1) in hypothetical_roads
        down = (col, row + 1) in hypothetical_roads
        left = (col - 1, row) in hypothetical_roads
        right = (col + 1, row) in hypothetical_roads
        count = sum((up, down, left, right))
        if count >= 4:
            return "cross"
        if count == 3:
            return "tee_ne" if not left else "tee_nw"
        if count == 2 and ((up and down) or (left and right)):
            return "straight_ne" if (left and right) else "straight_nw"
        if count == 2:
            return "corner_ne" if (up or down) and right else "corner_nw"
        return "straight_ne"
    return role_for


def _infill_candidate(network: RoadNetwork, rng) -> list | None:
    """A short spur from an existing road cell into an adjacent open cell,
    inside the current frontier bounds -- no outward growth."""
    if not network.frontier_bounds:
        return None
    candidates = sorted(network.road_cells)
    rng.shuffle(candidates)
    for (col, row) in candidates[:20]:
        for dc, dr in CARDINAL_OFFSETS:
            spur = (col + dc, row + dr)
            if spur not in network.occupied:
                return [spur]
    return None


def _extend_candidate(network: RoadNetwork, rng, direction: tuple) -> list | None:
    """Grow the frontier outward, in a straight run of EXTEND_RUN_MIN..MAX
    cells, biased toward `direction`."""
    if not network.road_cells:
        return [(0, 0)]
    anchor = max(network.road_cells,
                key=lambda cell: cell[0] * direction[0] + cell[1] * direction[1])
    step = (1, 0) if abs(direction[0]) >= abs(direction[1]) else (0, 1)
    if direction[0] < 0 and step == (1, 0):
        step = (-1, 0)
    if direction[1] < 0 and step == (0, 1):
        step = (0, -1)
    run_len = rng.randint(EXTEND_RUN_MIN, EXTEND_RUN_MAX)
    cells = [(anchor[0] + step[0] * i, anchor[1] + step[1] * i) for i in range(1, run_len + 1)]
    return cells


def grow_tick(network: RoadNetwork, target_capacity: float,
             pressure_direction: tuple = (1.0, 0.0)) -> str:
    """One growth attempt. Always advances `network.tick_index`, whether or
    not it succeeds -- tick_index is an attempt counter, which is what makes
    the per-tick RNG derivation deterministic and replay-safe."""
    if network.capacity >= target_capacity:
        network.tick_index += 1
        return TickResult.NO_CAPACITY_NEEDED

    rng = _tick_rng(network)
    for _attempt in range(MAX_CANDIDATE_RETRIES):
        candidate = _infill_candidate(network, rng)
        if candidate is None:
            candidate = _extend_candidate(network, rng, pressure_direction)
        ok, _reason = validate_candidate(network, candidate)
        if ok:
            hypothetical = network.road_cells | set(candidate)
            role_for = assign_roles(network, hypothetical)
            network.commit_project(candidate, role_for=role_for, avenue=False,
                                   capacity_delta=CAPACITY_PER_ROAD_CELL * len(candidate))
            # re-derive neighbor roles for cells adjacent to the new project too,
            # since their connectivity may have changed
            network.tick_index += 1
            return TickResult.GREW

    network.tick_index += 1
    return TickResult.NO_VALID_CANDIDATE
```

- [ ] **Step 4: Run the tests — must PASS**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_road_network.py`
Expected: all 11 tests pass.

- [ ] **Step 5: Checkpoint** — self-review `assign_roles`'s branch for
  `tee_ne` vs `tee_nw` and `corner_ne` vs `corner_nw`: confirm against the
  manifest's actual `roads` family key list
  (`straight_ne/nw, corner_ne/nw, tee_ne/nw, cross, avenue_ne`) by reading
  `assets/iso/manifest.json`'s `roads` section, and adjust the boolean
  logic if the `_ne`/`_nw` suffix convention doesn't match what's there —
  this mapping is finished properly in Task 5, this step is a sanity check
  only.

---

## Task 4: Bootstrap runner

**Files:**
- Modify: `energy_grid_game/ui/road_network.py`
- Modify: `energy_grid_game/test_road_network.py`

**Interfaces:**
- Consumes: `RoadNetwork`, `grow_tick`, `TickResult` (Task 3).
- Produces: `bootstrap_network(target_capacity: float, master_seed: int) -> RoadNetwork`,
  `BootstrapStalled(Exception)`, `BootstrapExhausted(Exception)` (both carry
  `.network`, `.tick_count`, `.last_failures: list[str]` attributes).

- [ ] **Step 1: Write the failing tests** — append to `test_road_network.py`:

```python
from ui.road_network import bootstrap_network, BootstrapExhausted


def test_bootstrap_reaches_target_capacity():
    net = bootstrap_network(target_capacity=600.0, master_seed=7)
    assert net.capacity >= 600.0


def test_bootstrap_grows_more_for_a_larger_target():
    small = bootstrap_network(target_capacity=300.0, master_seed=7)
    large = bootstrap_network(target_capacity=3000.0, master_seed=7)
    assert len(large.roads) > len(small.roads)
    assert large.capacity > small.capacity


def test_bootstrap_is_deterministic_for_the_same_target_and_seed():
    net_a = bootstrap_network(target_capacity=1200.0, master_seed=42)
    net_b = bootstrap_network(target_capacity=1200.0, master_seed=42)
    assert net_a.roads.keys() == net_b.roads.keys()
    assert net_a.capacity == net_b.capacity


def test_bootstrap_raises_when_target_is_unreachable():
    # A target far beyond what max_ticks can plausibly reach must raise
    # BootstrapExhausted, never silently return an under-capacity network.
    try:
        bootstrap_network(target_capacity=10_000_000.0, master_seed=1)
        assert False, "expected BootstrapExhausted"
    except BootstrapExhausted as exc:
        assert exc.tick_count > 0
        assert exc.network.capacity < 10_000_000.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall road_network checks passed")
```

- [ ] **Step 2: Run it — must FAIL**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_road_network.py`
Expected: `ImportError: cannot import name 'bootstrap_network'`.

- [ ] **Step 3: Add bootstrap to `ui/road_network.py`**

```python
MAX_BOOTSTRAP_TICKS = 500
MAX_CONSECUTIVE_FAILURES = 20


class BootstrapStalled(Exception):
    def __init__(self, network, tick_count, last_failures):
        super().__init__(
            f"road growth stalled after {len(last_failures)} consecutive "
            f"failed ticks (tick {tick_count}, capacity {network.capacity:.0f})")
        self.network = network
        self.tick_count = tick_count
        self.last_failures = last_failures


class BootstrapExhausted(Exception):
    def __init__(self, network, tick_count, last_failures):
        super().__init__(
            f"road growth hit the {MAX_BOOTSTRAP_TICKS}-tick bootstrap cap "
            f"(capacity {network.capacity:.0f})")
        self.network = network
        self.tick_count = tick_count
        self.last_failures = last_failures


def bootstrap_network(target_capacity: float, master_seed: int) -> RoadNetwork:
    """Deterministically grow a fresh network, offscreen/instantly, from a
    minimal seed stub until capacity >= target_capacity. Bounded by two
    independent counters (ticks, consecutive failures) so it can never hang;
    raises rather than silently returning an under-capacity network."""
    network = RoadNetwork(master_seed=master_seed)
    seed_cells = [(0, 0), (1, 0), (2, 0)]
    network.commit_project(seed_cells, role_for=lambda c, r: "straight_ne",
                           avenue=True, capacity_delta=0.0)

    consecutive_failures = 0
    recent_failures = []
    for tick_count in range(1, MAX_BOOTSTRAP_TICKS + 1):
        result = grow_tick(network, target_capacity)
        if result == TickResult.NO_CAPACITY_NEEDED:
            return network
        if result == TickResult.GREW:
            consecutive_failures = 0
            continue
        consecutive_failures += 1
        recent_failures.append(result)
        recent_failures = recent_failures[-MAX_CONSECUTIVE_FAILURES:]
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            raise BootstrapStalled(network, tick_count, recent_failures)

    raise BootstrapExhausted(network, MAX_BOOTSTRAP_TICKS, recent_failures)
```

- [ ] **Step 4: Run the tests — must PASS**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_road_network.py`
Expected: all 15 tests pass. (`test_bootstrap_raises_when_target_is_unreachable`
may take a few seconds — it runs the full 500-tick bootstrap loop before
raising `BootstrapExhausted`; that's expected, not a bug.)

- [ ] **Step 5: Checkpoint** — confirm `test_bootstrap_raises_when_target_is_unreachable`
  actually exercises `BootstrapExhausted` (ticks exhausted) rather than
  `BootstrapStalled` (20 consecutive failures) by checking which one fires
  for a 10-million target with `CAPACITY_PER_ROAD_CELL = 60.0` — at ~5
  cells/tick that's roughly 33,000 ticks needed, far past the 500-tick cap,
  so `BootstrapExhausted` is the expected outcome; if the test file raises
  `BootstrapStalled` instead, that's still a valid "never silently
  under-deliver" outcome — loosen the except clause to catch either if so,
  rather than treating it as a bug.

---

## Task 5: Road tile rendering — real connectivity mask

**Files:**
- Modify: `energy_grid_game/ui/road_network.py` (refine `assign_roles`)
- Test: `energy_grid_game/test_road_network.py`

**Interfaces:**
- Consumes: `assets/iso/manifest.json`'s `roads` family keys (read them
  directly, don't guess).
- Produces: `assign_roles` (Task 3) corrected to match the manifest exactly.

- [ ] **Step 1: Read the manifest's actual road role keys**

Run: `./.venv39/Scripts/python.exe -c "import json; m = json.load(open('assets/iso/manifest.json')); print(list(m['roads'].keys()))"`
from `D:/Github/gridmanager`. Use the exact printed key list for this task
— do not assume the plan's Task 3 sanity-check guess was correct.

- [ ] **Step 2: Write the failing tests** — append to `test_road_network.py`:

```python
from ui.road_network import assign_roles


def test_role_assignment_matches_measured_neighbors_straight():
    net = RoadNetwork(master_seed=1)
    cells = {(0, 0), (1, 0), (2, 0)}   # a horizontal (east-west) run
    role_for = assign_roles(net, cells)
    assert role_for(1, 0) in ("straight_ne", "straight_nw")  # whichever key
                                                              # the manifest uses
                                                              # for an E-W run


def test_role_assignment_matches_measured_neighbors_corner():
    net = RoadNetwork(master_seed=1)
    cells = {(0, 0), (1, 0), (1, 1)}   # an L-bend
    role_for = assign_roles(net, cells)
    assert role_for(1, 0).startswith("corner_")


def test_role_assignment_matches_measured_neighbors_tee():
    net = RoadNetwork(master_seed=1)
    cells = {(0, 0), (1, 0), (2, 0), (1, 1)}   # a T off a straight run
    role_for = assign_roles(net, cells)
    assert role_for(1, 0).startswith("tee_")


def test_role_assignment_matches_measured_neighbors_cross():
    net = RoadNetwork(master_seed=1)
    cells = {(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)}   # 4-way at (1,1)
    role_for = assign_roles(net, cells)
    assert role_for(1, 1) == "cross"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall road_network checks passed")
```

- [ ] **Step 3: Run it — check current pass/fail state**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_road_network.py`
The `cross` test should already pass (Task 3's `assign_roles` handles
`count >= 4` correctly). The straight/corner/tee tests may fail if Task 3's
`_ne`/`_nw` axis-vs-key mapping guessed wrong — fix `assign_roles` in Step 4
based on what actually failed and what Step 1's real manifest keys are.

- [ ] **Step 4: Fix `assign_roles` in `ui/road_network.py` to match reality**

Using the exact key list from Step 1, rewrite the body of `role_for` inside
`assign_roles` so each of the 4 boolean neighbor flags (`up, down, left,
right`) maps to the correct manifest key for straight (2 opposite
neighbors), corner (2 adjacent neighbors), tee (3 neighbors), and cross (4
neighbors) — using the manifest's own `_ne`/`_nw` (or whatever the real
suffix convention is) to distinguish orientation within each category. Keep
the function's signature and the `role_for(col, row) -> str` contract
unchanged — only the body's key strings and orientation logic change.

- [ ] **Step 5: Run the tests — must PASS**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_road_network.py`
Expected: all 19 tests pass.

---

## Task 6: `iso_city.py` integration

**Files:**
- Modify: `energy_grid_game/ui/iso_city.py`
  - `__init__` (add `_road_network` field)
  - `_layout` (~L1620-1696): replace `build_urban_layout` call + tile/building/
    priority/extent derivation with `RoadNetwork`-driven equivalents
  - `prepare` (~L2285-2294): bootstrap-once, grow-incrementally-on-change
- Test: `energy_grid_game/test_city_model.py`

**Interfaces:**
- Consumes: `RoadNetwork`, `bootstrap_network`, `grow_tick`, `TickResult`
  (Tasks 1-4), all reviewer-approved and independently working in isolation.
- Produces: `IsoCity._road_network: RoadNetwork | None`, `IsoCity._extent`
  now derived (not a constant), `IsoCity._layout`/`.prepare` signatures
  UNCHANGED (existing callers, including the `_city(p)` test helper in
  `test_city_model.py`, keep working with no call-site changes).

**Important:** `_bake`'s giant rasterization loop (the `for (col, row) in
sorted(self._tiles, ...)` loop and everything after it — transmission,
plants, electron Flows, distribution pulses) is **not touched by this
task**. It is agnostic to where `self._tiles`/`self._buildings`/
`self._priority` came from; only `_layout`'s internals and `prepare`'s
rebake trigger change.

- [ ] **Step 1: Add the persistent network field to `__init__`**

Find (near the other per-instance fields, close to
`self._urban_layout = None` if present, otherwise near `self._key = None`):

```python
        self._key = None          # (rect size, population bucket, fleet)
```

Add directly after it:

```python
        self._road_network = None   # persistent RoadNetwork; created once, only grows
```

- [ ] **Step 2: Import the new module**

Add near the top of `ui/iso_city.py`, alongside the existing
`from ui.urban_blocks import build_urban_layout, nearest_road_tile, road_path_tiles`
line:

```python
from ui.road_network import bootstrap_network, grow_tick, TickResult
```

Keep the existing `urban_blocks` import — `nearest_road_tile`/
`road_path_tiles` are still used for transmission routing (Task 8 confirms
this), and district/campus/civic assignment logic in `urban_blocks.py`
still runs (Step 3).

- [ ] **Step 3: Rewrite `_layout`'s road/building/extent derivation**

Find the current body from `urban = build_urban_layout(rect, tuple(fleet))`
through `self._extent = 0.72` (the block that populates `self._tiles`,
`buildings`, `self._priority`, `self._sub_sites`, and the hard-coded
extent). Replace **only that block** — the surrounding `_place_plants`/
`_make_roads` calls and the `_choose_city_centers` call stay exactly where
they are, unchanged:

```python
        # Population -> capacity target for the persistent road network.
        # CAPACITY_PER_ROAD_CELL in road_network.py is illustrative, not tied
        # to a real units system -- population is the target directly (1
        # population unit ~= 1 capacity unit), which keeps this simple and
        # matches what test_city_size_tracks_population actually checks
        # (does extent/building-count scale with population, not exact numbers).
        if self._road_network is None:
            self._road_network = bootstrap_network(target_capacity=float(population),
                                                    master_seed=20260730)
        elif self._road_network.capacity < population:
            # Live incremental growth: run ticks against the SAME persistent
            # network, never a fresh one, until this bucket's target is met
            # or ticks are exhausted for this bake.
            for _ in range(50):
                if self._road_network.capacity >= population:
                    break
                result = grow_tick(self._road_network, target_capacity=float(population))
                if result == TickResult.NO_CAPACITY_NEEDED:
                    break

        network = self._road_network
        min_c, max_c, min_r, max_r = network.frontier_bounds or (0, 0, 0, 0)
        # Extent: normalized 0..1 distance from origin to the network's
        # furthest built cell, against the same u_max/v_max bound used
        # elsewhere in this method -- this is what makes _extent actually
        # respond to population instead of being a hard-coded constant.
        far_u = max(abs(min_c - min_r), abs(max_c - max_r)) / max(1.0, u_max)
        far_v = max(abs(min_c + min_r), abs(max_c + max_r)) / max(1.0, v_max)
        self._extent = min(0.94, max(0.30, math.hypot(far_u, far_v)))

        urban = build_urban_layout(rect, tuple(fleet))   # districts, campuses, civic
                                                           # anchors, green tiles -- still
                                                           # a one-shot deterministic stamp,
                                                           # UNCHANGED; only ROADS/BUILDINGS
                                                           # now come from the persistent network
        self._urban_layout = urban

        def river_v(u):
            return 0.34 * v_max + 0.10 * v_max * math.sin(
                u / max(1.0, u_max * 0.42))

        tiles = {}
        buildings = []
        for pos, road in network.roads.items():
            tiles[pos] = ("road", road)
        # Buildings: one per road-adjacent buildable cell the network has
        # opened up so far -- minimal placement (Task 7), not the full
        # structure lifecycle (deferred to sub-project B). Reuses the
        # existing district/archetype selection from urban_blocks.py.
        buildable = _road_adjacent_buildable_cells(network, urban)
        for (col, row) in buildable:
            e = math.hypot((col - row) / u_max, (col + row) / v_max)
            angle = math.atan2((col + row) / v_max, (col - row) / u_max)
            district = _district(e, angle)
            archetype_name = _pick_archetype(district, col, row)
            tiles[(col, row)] = ("urban_block", _building_tile(col, row, district, archetype_name))
            buildings.append((col, row, archetype_name, e))
        for pos in urban.green_tiles:
            if pos not in tiles:
                tiles[pos] = ("park", None)
        for campus in urban.campuses.values():
            cc, rr = round(campus.col), round(campus.row)
            for dc in range(-campus.radius, campus.radius + 1):
                for dr in range(-campus.radius, campus.radius + 1):
                    if abs(dc) + abs(dr) <= campus.radius + 1:
                        tiles[(cc + dc, rr + dr)] = ("campus", campus.key)
```

Add these module-level helpers near the top of `ui/iso_city.py` (alongside
other free functions like `_district`, which already exists — confirm it's
imported/defined and reuse it rather than duplicating). `_building_tile`
reuses the existing `UrbanBlock` dataclass from `urban_blocks.py` rather
than inventing a parallel type, which guarantees compatibility with
`_bake`'s existing `draw_urban_block(day, sx, sy, extra, ...)` call — that
call already expects an `UrbanBlock`-shaped object, so before finalizing
this step, read that function's signature in `ui/urban_blocks.py` and
confirm the field names below (`district`, `archetype`, `variant`,
`greenery`, `buildings`) match what it actually reads:

```python
def _road_adjacent_buildable_cells(network, urban):
    """Cells with cardinal road frontage that aren't already occupied --
    the minimal 'has road access' rule from the structure-growth spec,
    without its full lifecycle."""
    result = []
    for (rc, rr) in sorted(network.road_cells):
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cell = (rc + dc, rr + dr)
            if cell in network.occupied or cell in urban.green_tiles:
                continue
            if cell not in result:
                result.append(cell)
                network.occupied.add(cell)
    return result


_ARCHETYPE_PALETTE = {
    "core": ("tower", "midrise", "shop"),
    "mixed": ("midrise", "block", "shop", "house"),
    "civic": ("shop", "midrise"),
    "industrial": ("block", "shop"),
    "utility": ("block", "shop"),
}


def _pick_archetype(district, col, row):
    palette = _ARCHETYPE_PALETTE.get(district, _ARCHETYPE_PALETTE["mixed"])
    index = abs(hash((district, col, row))) % len(palette)
    return palette[index]


def _building_tile(col, row, district, archetype_name):
    from ui.urban_blocks import UrbanBlock
    return UrbanBlock(col=col, row=row, district=district, archetype="urban",
                      variant=abs(hash((col, row))) % 10_000, greenery=0.08,
                      buildings=(archetype_name,))
```

- [ ] **Step 4: Restructure `prepare`'s rebake trigger**

Replace:

```python
    def prepare(self, rect, state):
        """Ensure camera, world layers, and plant markers exist for this frame."""
        population = state_population(state)
        fleet = tuple(sorted(s.key for s in state.sources if s.max_output_mw > 0))
        world_size = required_world_size(rect)
        key = (world_size, round(population / 5000.0), fleet)
        if key != self._key:
            self._key = key
            ramp_by_key = {s.key: s.ramp_up_latency for s in state.sources}
            self._bake(rect, population, fleet, ramp_by_key)
```

with:

```python
    def prepare(self, rect, state):
        """Ensure camera, world layers, and plant markers exist for this frame.

        The persistent RoadNetwork survives across bakes (created once, only
        grows); a bake is still needed whenever population/fleet/viewport
        changes, since the RASTER layers (day/night surfaces) are baked
        images, not something updated incrementally -- only the underlying
        road/building DATA is incremental. `_layout` (called from `_bake`)
        is what actually decides whether to bootstrap fresh or grow the
        existing network.
        """
        population = state_population(state)
        fleet = tuple(sorted(s.key for s in state.sources if s.max_output_mw > 0))
        world_size = required_world_size(rect)
        key = (world_size, round(population / 5000.0), fleet)
        if key != self._key:
            self._key = key
            ramp_by_key = {s.key: s.ramp_up_latency for s in state.sources}
            self._bake(rect, population, fleet, ramp_by_key)
```

(This step's diff is intentionally a no-op on `prepare` itself — the
docstring documents the new contract, but the actual bootstrap-vs-grow
decision already lives in `_layout`'s Step 3 rewrite, keyed off
`self._road_network is None`. Confirm this reasoning holds: `prepare`
still re-triggers `_bake` on the same population-bucket-change cadence as
before, `_bake` still calls `_layout` every time it runs, and `_layout`'s
new logic is what makes that call either bootstrap-once or grow-the-
existing-network — so no change to `prepare`'s body is actually needed
beyond the comment. If a step reviewer disagrees and believes `prepare`
needs an actual code change, escalate rather than guessing.)

- [ ] **Step 5: Checkpoint — import check**

Run (from `D:/Github/gridmanager`):
`./.venv39/Scripts/python.exe -c "import sys; sys.path.insert(0,'energy_grid_game'); import ui.iso_city; print('import ok')"`
Expected: `import ok`, no traceback.

- [ ] **Step 6: Run `test_city_model.py` and fix `test_city_size_tracks_population`
  if still failing**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_city_model.py`
Expected: `test_city_size_tracks_population` now passes (extent and building
count both strictly increase with population, using the real bootstrap
mechanism). If other pre-existing tests in this file fail because they
assumed the old `build_urban_layout`-only road/building model (e.g. tests
asserting specific road counts or districts that no longer match), read
each failure and update ONLY the assertions that were coupled to the old
one-shot generation's specifics — do not weaken `test_city_size_tracks_population`
itself. Report any test whose fix isn't obvious as NEEDS_CONTEXT rather than
guessing at what the new correct value should be.

---

## Task 7: Population as a per-day metric

**Files:**
- Modify: `energy_grid_game/game_state.py`
- Test: `energy_grid_game/test_population.py` (create)

**Interfaces:**
- Consumes: `GameState.time_ideal`/`time_under`/`time_over` (existing,
  cumulative-for-the-whole-run fields), `GameState.start_next_day` (existing
  method).
- Produces: `GameState.population: float` (new field), day-start snapshot
  fields `_day_start_time_ideal`/`_day_start_time_under`/`_day_start_time_over`
  (new, private).

- [ ] **Step 1: Write the failing tests** — create
  `energy_grid_game/test_population.py`:

```python
"""Per-day population mechanics (game_state.py). Run: python test_population.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import scenarios
from game_state import GameState


def _standard():
    return GameState(scenarios.make_standard())


def test_population_field_exists_with_a_sane_default():
    st = _standard()
    assert st.population > 0


def test_population_does_not_change_mid_day():
    st = _standard()
    before = st.population
    for _ in range(120):
        st.update(1 / 60.0)
    assert st.population == before   # only start_next_day() may change it


def test_well_managed_day_increases_population():
    st = _standard()
    before = st.population
    # simulate a day's cumulative stats as if entirely in the ideal band
    st.time_ideal = 24.0
    st.time_under = 0.0
    st.time_over = 0.0
    st.start_next_day()
    assert st.population > before


def test_poorly_managed_day_does_not_increase_population():
    st = _standard()
    before = st.population
    st.time_ideal = 0.0
    st.time_under = 24.0
    st.time_over = 0.0
    st.start_next_day()
    assert st.population <= before


def test_population_delta_is_capped_per_day():
    st = _standard()
    before = st.population
    st.time_ideal = 1_000_000.0   # absurdly good, to try to blow past the cap
    st.time_under = 0.0
    st.time_over = 0.0
    st.start_next_day()
    assert st.population <= before * 1.03 + 1e-6   # +/-3%/day cap


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall population checks passed")
```

- [ ] **Step 2: Run it — must FAIL**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_population.py`
Expected: `AttributeError: 'GameState' object has no attribute 'population'`.

- [ ] **Step 3: Add the `population` field and day-start snapshots to
  `GameState.__init__`**

Find the `__init__` section that sets `self.time_ideal = 0.0` /
`self.time_under = 0.0` / `self.time_over = 0.0` (the cumulative-per-run
counters). Add directly after that block:

```python
        # Population: a real, changing per-day metric (previously always a
        # fixed illustrative constant read by ui/iso_city.state_population).
        # Updated once per day, in start_next_day(), from that day's
        # reliability fraction -- the SAME calculation the day-complete
        # panel's star rating already uses -- plus that day's price
        # performance. Never updated mid-day.
        self.population = 12_000.0   # matches ui.iso_city.ILLUSTRATIVE_POPULATION
        self._day_start_time_ideal = 0.0
        self._day_start_time_under = 0.0
        self._day_start_time_over = 0.0
```

- [ ] **Step 4: Add the population-delta calculation to `start_next_day`**

Find `start_next_day`'s current body. Add the delta calculation as the
FIRST thing the method does (before `self.day += 1` and the other
resets, since it needs the OUTGOING day's final cumulative values):

```python
    def start_next_day(self):
        """Initialise the next day. Called exactly once per confirmed rollover by
        the day panel's ADVANCING_DAY phase."""
        # Population changes once per day, from the day that's ending -- reusing
        # the exact reliability fraction the day-complete panel's star rating
        # already computes, but as a DAY-SCOPED delta (time_ideal/_under/_over
        # are cumulative for the whole run, not per-day, so this diffs against
        # a snapshot taken at the start of the day being closed out).
        day_ideal = self.time_ideal - self._day_start_time_ideal
        day_under = self.time_under - self._day_start_time_under
        day_over = self.time_over - self._day_start_time_over
        day_total = day_ideal + day_under + day_over
        if day_total > 1e-6:
            reliability_frac = day_ideal / day_total
            # price performance: cheap grid price this day nudges population up
            price_frac = 1.0 - min(1.0, self.grid_price / 200.0) if self.grid_price > 0 else 0.5
            performance = 0.7 * reliability_frac + 0.3 * price_frac   # 0..1
            delta_frac = (performance - 0.5) * 2.0 * POPULATION_MAX_DAILY_DELTA
            self.population = max(1.0, self.population * (1.0 + delta_frac))
        self._day_start_time_ideal = self.time_ideal
        self._day_start_time_under = self.time_under
        self._day_start_time_over = self.time_over

        retiring = {s.key for s in self.active_sources}
        self.day += 1
```

(The rest of `start_next_day`'s existing body — everything from
`still_active = self.config.sources_for_day(self.day)` onward — stays
exactly where it is, unchanged, after this new block.)

Add the tuning constant near the top of `game_state.py`, alongside other
module-level constants:

```python
POPULATION_MAX_DAILY_DELTA = 0.03   # +/-3% of current population per day (first-pass tuning)
```

- [ ] **Step 5: Wire `population` into the city renderer**

In `ui/iso_city.py`'s `state_population` function, change:

```python
def state_population(state):
    population = getattr(state, "population", None)
    return population if population is not None else ILLUSTRATIVE_POPULATION
```

to (this now reads the REAL field Step 3 added; the `getattr` fallback
stays for safety against any other code path that constructs a bare state
object without going through `GameState.__init__`, e.g. some test helpers):

```python
def state_population(state):
    population = getattr(state, "population", None)
    return population if population is not None else ILLUSTRATIVE_POPULATION
```

(No change needed here — `state.population` already resolves correctly
once Step 3 sets it on every real `GameState`. This step is a
verification-only checkpoint, not a code change: confirm by reading the
function that it already does the right thing.)

- [ ] **Step 6: Run the tests — must PASS**

Run: `./.venv39/Scripts/python.exe energy_grid_game/test_population.py`
Expected: all 5 tests pass.

---

## Task 8: Final integration verification

**Files:** none changed; this task only runs, inspects, and reports.

- [ ] **Step 1: Full test suite**

Run every test file from `D:/Github/gridmanager`:
```
./.venv39/Scripts/python.exe energy_grid_game/test_pricing.py
./.venv39/Scripts/python.exe energy_grid_game/test_congestion.py
./.venv39/Scripts/python.exe energy_grid_game/test_dialogue_schema.py
./.venv39/Scripts/python.exe energy_grid_game/test_capacities.py
./.venv39/Scripts/python.exe energy_grid_game/test_instructional.py
./.venv39/Scripts/python.exe energy_grid_game/test_city_model.py
./.venv39/Scripts/python.exe energy_grid_game/test_grid_flow.py
./.venv39/Scripts/python.exe energy_grid_game/test_road_network.py
./.venv39/Scripts/python.exe energy_grid_game/test_population.py
```
Expected: all nine print their "all ... checks passed" line, with
`test_city_model.py` specifically including a passing
`test_city_size_tracks_population`.

- [ ] **Step 2: Confirm transmission routing still works**

Run: `./.venv39/Scripts/python.exe tools/capture_moments.py <dir>` (any
writable dir) from `D:/Github/gridmanager`. Expected: "captured NN
moments", no traceback. Open `21_delivery_chain_close.png` — transmission
corridors must still visibly route from plants toward substations along
road-adjacent corridors (confirming `road_path_tiles`/`nearest_road_tile`
correctly point at the new `RoadNetwork.road_cells` instead of a stale/
empty source).

- [ ] **Step 3: Render at a low and a high population, compare**

Write a small one-off script (not a permanent file — scratch, delete after)
that constructs two `GameState`s via `scenarios.make_standard()`, manually
sets `state.population` to a low value (e.g. `4_000`) and a high value
(e.g. `300_000`) respectively, renders each through the same
`tools/capture_moments.py`-style harness, and confirms by eye: the
high-population render shows a visibly larger built-up area (more road
cells, more buildings) than the low-population one. This is the direct
visual confirmation that the mechanism `test_city_size_tracks_population`
checks numerically actually looks right, not just passes an assertion.

- [ ] **Step 4: Report**

Summarize: all 9 test files' pass/fail status, the transmission-routing
visual check, and the low-vs-high population visual comparison. Flag
anything that passed tests but looked visually wrong (a real risk given
Task 6's building-placement heuristic is intentionally minimal) as a
concern for follow-up, not something to silently patch outside this plan's
scope.

---

## Self-review notes

- Spec coverage: §1 (persistent grid) → Task 1. §2 (invariants) → Task 2.
  §3 (rendering mask) → Task 5. §4 (infill/extend) → Task 3. §5 (minimal
  building placement) → Task 6 Step 3. §6 (bootstrap, `_extent` derived) →
  Task 4 + Task 6 Step 3. §7 (population per-day) → Task 7. §8 (integration
  points, low risk) → Task 6 Step 3 (urban_blocks still owns districts/
  campuses) + Task 8 Step 2 (transmission routing verified). All covered.
- No pytest: all tests are self-running assert modules matching the
  repo's existing convention, new files follow the per-topic naming
  convention (`test_road_network.py`, `test_population.py`).
- No git: every "Commit" step is a verification/checkpoint step instead,
  per the repo's standing no-git rule.
- Type consistency: `RoadNetwork`, `TickResult`, `grow_tick`,
  `bootstrap_network`, `validate_candidate`, `assign_roles` are defined
  once in Tasks 1-5 and consumed with identical signatures in Task 6.
  `UrbanRoad` and `UrbanBlock` (both reused via `_building_tile`, not
  redefined) come from `ui/urban_blocks.py`, unchanged.
- Task 6 is the highest-risk task in this plan — it's the only one editing
  a large, already-dense existing file rather than building fresh in a new
  one. Its brief explicitly tells the implementer which surrounding code
  must NOT change (`_bake`'s rasterization loop) and to escalate rather
  than guess if the `draw_urban_block` signature check in Step 3 doesn't
  match what's assumed.
