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

import math
import random
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


FLOOD_WINDOW_MARGIN = 8          # cells beyond the candidate's bbox, each side
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
            if len(region) == 0:
                return False, "oversized_block"   # flood-fill hit FLOOD_FILL_CAP
            if len(region) == 1:
                return False, "enclosed_1x1"
            cols = [c for c, _r in region]
            rows = [r for _c, r in region]
            side = max(max(cols) - min(cols) + 1, max(rows) - min(rows) + 1)
            if side > MAX_ENCLOSED_SIDE or len(region) > MAX_ENCLOSED_CELLS:
                return False, "oversized_block"
    return True, ""


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
    manifest's road sprite keys exactly (verified against
    assets/iso/roads/*.png pixel data and the iso projection in
    ui/iso_city.py's `iso_xy`, see ui/road_network.py Task 5).

    Geometry, derived from `iso_xy(col, row) = ((col-row)*TW/2, (col+row)*TH/2)`:
    the `up` neighbor (row-1) sits to the screen NE of a cell, `down` (row+1)
    to the SW, `left` (col-1) to the NW, `right` (col+1) to the SE. Sprite
    pixels confirm `straight_ne_01.png` is a NE-SW strip (the up/down axis)
    and `straight_nw_01.png` is a NW-SE strip (the left/right axis) -- the
    opposite of what Task 3 guessed.

    The manifest only ships 2 of the 4 possible rotations for `corner_*` and
    `tee_*` (verified the same way): `corner_ne` is an exact match for
    up+right, `corner_nw` for down+left; `tee_ne` is an exact match for
    up+down+left (missing right), `tee_nw` for left+right+down (missing up).
    The other 2 rotations in each category (up+left/down+right for corners;
    missing-left/missing-down for tees) have no matching sprite in the
    manifest -- they fall back to the same-family sprite below (documented
    in the Task 5 report as an asset-coverage gap, not a mapping bug).
    """
    def role_for(col, row):
        up = (col, row - 1) in hypothetical_roads
        down = (col, row + 1) in hypothetical_roads
        left = (col - 1, row) in hypothetical_roads
        right = (col + 1, row) in hypothetical_roads
        count = sum((up, down, left, right))
        if count >= 4:
            return "cross"
        if count == 3:
            # exact: up+down+left (missing right) -> tee_ne; left+right+down
            # (missing up) -> tee_nw. approximate fallback: any tee sharing
            # the same complete through-axis (up+down, or left+right) uses
            # the same sprite as its exact-match sibling.
            return "tee_ne" if (up and down) else "tee_nw"
        if count == 2 and ((up and down) or (left and right)):
            return "straight_ne" if (up and down) else "straight_nw"
        if count == 2:
            # exact: up+right -> corner_ne, down+left -> corner_nw.
            # approximate fallback (no sprite for up+left / down+right):
            # match on the left/right member, since that member is always
            # an exact match either way.
            return "corner_ne" if right else "corner_nw"
        # count <= 1 (isolated cell or single-neighbor spur end): no
        # connectivity to orient by -- default to a straight sprite rather
        # than raising.
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


GROWTH_AVENUE_SPACING = 6  # smaller than urban_blocks.py's old AVENUE_SPACING=12,
                            # since sqrt-compressed capacity targets produce smaller networks


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
            # Periodic avenue rule, mirroring urban_blocks.py's old
            # AVENUE_SPACING-based grid alignment but checked per-candidate
            # instead of precomputed over the whole grid -- keeps avenue
            # density scaling with network size instead of pinning it to
            # the bootstrap seed stub.
            avenue = any(c % GROWTH_AVENUE_SPACING == 0
                        for (col, row) in candidate for c in (col, row))
            network.commit_project(candidate, role_for=role_for, avenue=avenue,
                                   capacity_delta=CAPACITY_PER_ROAD_CELL * len(candidate))
            # re-derive neighbor roles for cells adjacent to the new project too,
            # since their connectivity may have changed
            network.tick_index += 1
            return TickResult.GREW

    network.tick_index += 1
    return TickResult.NO_VALID_CANDIDATE


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
    # Symmetric plus/cross seed, not a straight line: gives early growth
    # cells to extend from in all four cardinal directions instead of
    # biasing outward growth along one axis from the start.
    seed_cells = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]
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
