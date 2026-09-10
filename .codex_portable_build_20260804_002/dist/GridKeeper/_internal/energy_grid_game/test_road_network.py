"""RoadNetwork core data model checks. Run: python test_road_network.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from ui.road_network import RoadNetwork, validate_candidate
from ui.road_network import grow_tick, TickResult
from ui.road_network import bootstrap_network, BootstrapExhausted
from ui.road_network import assign_roles


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
