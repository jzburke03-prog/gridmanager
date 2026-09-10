"""3D terrain renderer checks. Run: python test_terrain3d.py"""
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from ui.terrain3d import (BUILDING_MATERIALS, CAM_ROT, MATERIALS, MESH_DIR,
                           PX_PER_UNIT, ROAD_MATERIALS,
                           ROAD_ROLE_TO_SHAPE_YAW, TILE_SPACING,
                           TRANSMISSION_CONDUCTOR_HEIGHT_WORLD,
                           _VERTICAL_FORESHORTENING,
                           build_tower_billboards,
                           build_transmission_geometry, build_instances,
                           conductor_strip_mesh, load_transmission,
                           release_transmission, screen_px_to_world,
                           tower_billboard_surface)
from ui.iso_city import IsoCity, iso_xy
from ui.urban_blocks import UrbanRoad

import os as _os
_os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
pygame.display.set_mode((1, 1))     # sprite baking (IsoCity._layout) needs a video surface

from ui.gl_context import create_context
from ui.terrain3d import (create_framebuffer, create_program, draw,
                           load_meshes, read_rgba, to_surface,
                           upload_instances)
from ui.terrain3d import billboard_quad, camera_basis, create_dynamic_texture
from ui.terrain3d import build_plant_billboards
from ui.terrain3d import load_billboards


def test_is_enabled_defaults_on_and_accepts_explicit_opt_out_values():
    """Catch treating GRIDMANAGER_TERRAIN3D as opt-in instead of opt-out."""
    from ui import terrain3d

    key = "GRIDMANAGER_TERRAIN3D"
    sentinel = object()
    original = os.environ.get(key, sentinel)
    try:
        os.environ.pop(key, None)
        assert terrain3d.is_enabled() is True

        for value in ("0", "false", "no", "off"):
            os.environ[key] = value
            assert terrain3d.is_enabled() is False, value

        for value in ("1", "true", "yes", "on"):
            os.environ[key] = value
            assert terrain3d.is_enabled() is True, value
    finally:
        if original is sentinel:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original


def test_covers_tile_kind_keeps_dense_downtown_sprite_overlay_visible():
    from ui import terrain3d
    assert terrain3d.covers_tile_kind("grass")
    assert terrain3d.covers_tile_kind("road")
    assert terrain3d.covers_tile_kind("vroad")
    assert not terrain3d.covers_tile_kind("voxel_bldg")
    assert not terrain3d.covers_tile_kind("pad")
    assert not terrain3d.covers_tile_kind("campus")


def test_kit_manifest_covers_every_source_gltf_and_artifact():
    from ui import terrain3d

    repo_root = Path(__file__).resolve().parents[1]
    source_root = repo_root / terrain3d.KIT_SOURCE_ROOT
    expected_sources = {
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*.gltf")
    }
    manifest = terrain3d.load_kit_manifest()
    manifest_sources = {entry["source"] for entry in manifest.values()}

    assert len(expected_sources) >= 373
    assert manifest_sources == expected_sources
    for key, entry in manifest.items():
        assert key == entry["key"]
        assert terrain3d.kit_artifact_path(entry).exists(), key


def test_kit_semantic_sources_exist_for_active_and_deferred_families():
    from ui import terrain3d

    manifest = terrain3d.load_kit_manifest()
    semantics = terrain3d.available_kit_semantics()

    required = {
        "terrain.grass.base", "terrain.farm.base", "terrain.water.base",
        "terrain.mountain.base", "terrain.desert.base", "terrain.city.base",
        "road.straight", "road.corner", "road.tee", "road.cross",
        "track.straight", "track.curve", "track.switch",
        "prop.tree", "prop.bush", "prop.stone", "prop.cactus",
        "prop.wood", "prop.bones", "city.building",
        "edge.forest_water.side", "edge.dirt_water.side",
        "edge.desert_water.side", "edge.city_water.side",
    }

    assert required <= set(semantics)
    for semantic, key in semantics.items():
        assert key in manifest, semantic
        assert terrain3d.kit_artifact_path(manifest[key]).exists(), semantic


def test_active_kit_sources_are_rich_enough_for_finished_visuals():
    from ui import terrain3d

    active_sources = set(terrain3d.KIT_ACTIVE_MESH_SOURCES.values())

    assert len(active_sources) >= 24
    assert any(key.startswith("forestwater/") for key in active_sources)
    assert any(key.startswith("dirtwater/") for key in active_sources)
    assert any(key.startswith("roads/road-straight-") for key in active_sources)
    assert any(key.startswith("mountains/") for key in active_sources)


def test_lighting_for_state_derives_day_night_winter_and_storm_snow():
    from ui import terrain3d

    noon = SimpleNamespace(sim_hour=12.0, date=date(2026, 7, 15), active_event=None)
    night = SimpleNamespace(sim_hour=2.0, date=date(2026, 7, 15), active_event=None)
    winter = SimpleNamespace(sim_hour=12.0, date=date(2026, 1, 15), active_event=None)
    snow = SimpleNamespace(
        sim_hour=12.0,
        date=date(2026, 1, 15),
        active_event=SimpleNamespace(kind="SNOW"),
    )
    ice = SimpleNamespace(
        sim_hour=12.0,
        date=date(2026, 1, 15),
        active_event=SimpleNamespace(kind="ICE_STORM"),
    )

    noon_lighting = terrain3d.lighting_for_state(noon)
    night_lighting = terrain3d.lighting_for_state(night)
    winter_lighting = terrain3d.lighting_for_state(winter)
    snow_lighting = terrain3d.lighting_for_state(snow)
    ice_lighting = terrain3d.lighting_for_state(ice)

    assert noon_lighting["ambient"] > night_lighting["ambient"]
    assert night_lighting["light_tint"][0] < noon_lighting["light_tint"][0]
    assert night_lighting["light_tint"][1] < noon_lighting["light_tint"][1]
    assert night_lighting["light_tint"][2] <= noon_lighting["light_tint"][2]
    assert winter_lighting["snow_mix"] > 0.0
    assert snow_lighting["snow_mix"] > winter_lighting["snow_mix"]
    assert ice_lighting["snow_mix"] > winter_lighting["snow_mix"]


def test_lighting_for_state_defaults_without_complete_state():
    from ui import terrain3d

    lighting = terrain3d.lighting_for_state(SimpleNamespace())

    assert set(lighting) == {"ambient", "light_tint", "snow_mix", "wet_mix", "ice_mix"}
    assert 0.0 <= lighting["ambient"] <= 1.0
    assert len(lighting["light_tint"]) == 3
    for channel in lighting["light_tint"]:
        assert 0.0 <= channel <= 1.0
    for key in ("snow_mix", "wet_mix", "ice_mix"):
        assert 0.0 <= lighting[key] <= 1.0


def test_lighting_for_state_derives_rain_wetness_and_ice():
    from ui import terrain3d

    rain = SimpleNamespace(
        sim_hour=12.0,
        date=date(2026, 7, 15),
        active_event=SimpleNamespace(kind="RAIN"),
    )
    snow = SimpleNamespace(
        sim_hour=12.0,
        date=date(2026, 1, 15),
        active_event=SimpleNamespace(kind="SNOW"),
    )
    ice = SimpleNamespace(
        sim_hour=12.0,
        date=date(2026, 1, 15),
        active_event=SimpleNamespace(kind="ICE_STORM"),
    )

    rain_lighting = terrain3d.lighting_for_state(rain)
    snow_lighting = terrain3d.lighting_for_state(snow)
    ice_lighting = terrain3d.lighting_for_state(ice)

    assert 0.25 <= rain_lighting["wet_mix"] <= 0.40
    assert 0.05 <= snow_lighting["wet_mix"] <= 0.16
    assert 0.16 <= ice_lighting["wet_mix"] <= 0.30
    assert 0.24 <= ice_lighting["ice_mix"] <= 0.36
    assert rain_lighting["ice_mix"] == 0.0
    assert snow_lighting["ice_mix"] == 0.0


def test_build_instances_buckets_by_material_and_skips_unrecognized_kinds():
    from ui import terrain3d

    tiles = {
        (0, 0): ("grass", None),
        (1, 0): ("farm", None),
        (2, 0): ("tree", None),
        (3, 0): ("water", None),
        (4, 0): ("mountain", 7),
        (5, 0): ("nonsense_kind", None),  # not a terrain/road/building kind, skip
    }
    instances = build_instances(tiles)
    assert len(instances) == 5
    assert all(name in terrain3d.TERRAIN_RUNTIME_MESHES for name in instances)
    for offsets in instances.values():
        assert offsets.shape == (1, 4)
        assert offsets.dtype == np.float32


def test_build_instances_raises_on_unrecognized_road_role():
    tiles = {(0, 0): ("road", UrbanRoad(col=0, row=0, role="not_a_real_role", avenue=False))}
    try:
        build_instances(tiles)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_build_instances_raises_on_unrecognized_building_archetype():
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ui.iso_city import _building_tile
    tile = _building_tile(0, 0, "Downtown", "not_a_real_archetype")
    tiles = {(0, 0): ("urban_block", tile)}
    try:
        build_instances(tiles)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_build_instances_offset_matches_col_row():
    from ui import terrain3d

    tiles = {(3, 5): ("grass", None)}
    instances = build_instances(tiles)
    mesh_name = terrain3d.terrain_mesh_name("grass", 3, 5, tiles)
    expected = np.array([
        -5.0 * TILE_SPACING,
        terrain3d.terrain_height_world("grass", None, 3, 5),
        3.0 * TILE_SPACING,
        0.0,
    ], dtype="f4")
    assert np.array_equal(instances[mesh_name][0], expected)


def test_build_instances_groups_multiple_tiles_of_the_same_material():
    tiles = {(0, 0): ("grass", None), (1, 1): ("grass", None), (2, 2): ("grass", None)}
    instances = build_instances(tiles)
    assert sum(len(v) for name, v in instances.items() if name.startswith("grass")) == 3


def test_build_instances_omits_materials_with_no_tiles():
    instances = build_instances({(0, 0): ("water", None)})
    assert len(instances) == 1
    assert next(iter(instances)).startswith("water")


def test_build_instances_matches_iso_xy_sign_convention():
    """The bug this test exists to catch: negating only `row` (the old
    formula) gets screen_x right but mirrors screen_y. Project a handful of
    build_instances() offsets through the actual camera math (CAM_ROT) that
    terrain3d.py uses at draw time, derive (sx, screen_y) the same way
    _VERTEX_SHADER does (sx = cam.x * scale, screen_y = -cam.y * scale --
    scale is a positive constant so only the signs matter here), and check
    those signs against ui.iso_city.iso_xy(col, row)'s (x, y) signs for
    several distinct tiles. (0, 0) is skipped since both axes are zero
    there and (1, 1) is skipped since its projected screen_x lands exactly
    on zero -- neither has a sign to compare."""
    for col, row in [(1, 0), (0, 1), (2, 1)]:
        tiles = {(col, row): ("grass", None)}
        offset = next(iter(build_instances(tiles).values()))[0].copy()
        offset[1] = 0.0
        cam = CAM_ROT @ offset[:3]
        sx = cam[0]
        screen_y = -cam[1]
        iso_x, iso_y = iso_xy(col, row)
        assert np.sign(sx) == np.sign(iso_x), (col, row, sx, iso_x)
        assert np.sign(screen_y) == np.sign(iso_y), (col, row, screen_y, iso_y)


def _project(offset):
    """Project a build_instances() (x, y, z, yaw) offset through the same
    camera math draw()/_VERTEX_SHADER apply at render time (yaw=0 here, so
    the yaw rotation matrix is the identity and can be skipped): cam =
    CAM_ROT @ world, sx = cam.x * PX_PER_UNIT, screen_y = -cam.y *
    PX_PER_UNIT (zoom is a runtime multiplier applied equally to both axes,
    so it's omitted here since only the ratio/proportionality matters)."""
    cam = CAM_ROT @ offset[:3]
    return cam[0] * PX_PER_UNIT, -cam[1] * PX_PER_UNIT


def test_build_instances_projection_matches_iso_xy_proportionally():
    """Stronger than the sign-convention test above: confirms the corrected
    CAM_ROT (_AX = 30 degrees) and PX_PER_UNIT together make the projected
    (sx, screen_y) genuinely PROPORTIONAL to ui.iso_city.iso_xy(col, row) --
    not just sign-matched -- across several distinct (col, row) pairs, with
    the same proportionality constant each time. This is what actually
    guarantees the 3D terrain tiles line up with the 2D city grid on
    screen."""
    pairs = [(1, 0), (0, 1), (2, 1), (3, 5), (7, 1), (2, 6)]
    ratios_x = []
    ratios_y = []
    for col, row in pairs:
        tiles = {(col, row): ("grass", None)}
        offset = next(iter(build_instances(tiles).values()))[0].copy()
        offset[1] = 0.0
        sx, screen_y = _project(offset)
        iso_x, iso_y = iso_xy(col, row)
        assert iso_x != 0
        ratios_x.append(sx / iso_x)
        if iso_y != 0:
            ratios_y.append(screen_y / iso_y)
    # All x-ratios agree with each other (proportionality)...
    for r in ratios_x:
        assert abs(r - ratios_x[0]) < 1e-4, (ratios_x, r)
    for r in ratios_y:
        assert abs(r - ratios_y[0]) < 1e-4, (ratios_y, r)
    # ...and the x- and y-ratios agree with EACH OTHER too, confirming the
    # 2:1 ratio itself (not just two independently-scaled axes).
    assert abs(ratios_x[0] - ratios_y[0]) < 1e-4, (ratios_x[0], ratios_y[0])
    # Sanity: the shared constant should be close to 1.0 (exact scale match
    # to iso_xy, not just proportional up to some arbitrary factor).
    assert abs(ratios_x[0] - 1.0) < 1e-3, ratios_x[0]


def _road_tile(col, row, role):
    # Build a real UrbanRoad the same way RoadNetwork.commit_project does,
    # so this test breaks (loudly) if road tile payloads stop being
    # UrbanRoad instances (see Finding 1: build_instances used to read the
    # raw payload as if it were a bare role string, which meant every real
    # road tile silently never matched ROAD_ROLE_TO_SHAPE_YAW).
    return UrbanRoad(col=col, row=row, role=role, avenue=False)


def test_build_instances_buckets_road_tiles_by_shape_with_correct_yaw():
    tiles = {
        (0, 0): ("road", _road_tile(0, 0, "straight_ne")),
        (1, 0): ("road", _road_tile(1, 0, "straight_nw")),
        (2, 0): ("road", _road_tile(2, 0, "cross")),
        (3, 0): ("road", _road_tile(3, 0, "corner_nw")),
        (4, 0): ("road", _road_tile(4, 0, "tee_ne")),
    }
    instances = build_instances(tiles)

    def offsets_for(prefix):
        rows = [v for name, v in instances.items() if name == prefix or name.startswith(prefix + "_")]
        return np.vstack(rows)

    straight = offsets_for("straight")
    assert straight.shape == (2, 4)
    yaws = sorted(straight[:, 3].tolist())
    assert yaws == [0.0, 90.0]
    cross = offsets_for("cross")
    assert cross.shape == (1, 4)
    assert cross[0, 3] == 0.0
    corner = offsets_for("corner")
    assert corner.shape == (1, 4)
    assert corner[0, 3] == 180.0
    tee = offsets_for("tee")
    assert tee.shape == (1, 4)
    assert tee[0, 3] == 180.0


def test_road_role_to_shape_yaw_covers_all_seven_roles():
    assert set(ROAD_ROLE_TO_SHAPE_YAW) == {
        "straight_ne", "straight_nw", "corner_ne", "corner_nw",
        "tee_ne", "tee_nw", "cross"}
    for shape, yaw in ROAD_ROLE_TO_SHAPE_YAW.values():
        assert shape in ROAD_MATERIALS
        assert yaw in (0.0, 90.0, 180.0, 270.0)


def test_build_instances_buckets_urban_block_tiles_by_archetype():
    # Build a real urban_block tile the same way IsoCity does, so this test
    # breaks (loudly) if _building_tile's payload shape ever changes.
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ui.iso_city import _building_tile
    tile = _building_tile(0, 0, "Downtown", "house")
    tiles = {(0, 0): ("urban_block", tile)}
    instances = build_instances(tiles)
    assert "house" in instances
    assert instances["house"].shape == (1, 4)


def test_build_instances_maps_dense_downtown_voxel_buildings():
    tiles = {
        (0, 0): ("voxel_bldg", "apartment"),
        (1, 0): ("voxel_bldg", "market"),
        (2, 0): ("voxel_bldg", "school"),
    }
    instances = build_instances(tiles)
    assert sum(len(v) for k, v in instances.items() if k.startswith("downtown_apartment")) == 1
    assert sum(len(v) for k, v in instances.items() if k.startswith("downtown_market")) == 1
    assert sum(len(v) for k, v in instances.items() if k.startswith("downtown_school")) == 1


def test_build_instances_maps_dense_downtown_vroads_by_grid_role():
    tiles = {
        (0, 0): ("vroad", None),
        (4, 1): ("vroad", None),
        (1, 4): ("vroad", None),
    }
    instances = build_instances(tiles)
    cross = np.vstack([v for k, v in instances.items() if k == "cross" or k.startswith("cross_")])
    straight = np.vstack([v for k, v in instances.items() if k == "straight" or k.startswith("straight_")])
    assert cross.shape == (1, 4)
    assert straight.shape == (2, 4)
    assert set(straight[:, 3]) == {0.0, 90.0}


def test_build_instances_produces_road_and_building_instances_from_a_real_city_layout():
    rect = pygame.Rect(0, 0, 1400, 410)
    city = IsoCity(None)
    city._layout(rect, 2_000_000, ("gas",))
    instances = build_instances(city.tiles)
    road_instance_count = sum(
        len(v) for k, v in instances.items()
        if any(k == r or k.startswith(r + "_") for r in ROAD_MATERIALS)
    )
    building_instance_count = sum(
        len(v) for k, v in instances.items()
        if k in BUILDING_MATERIALS or k.startswith("downtown_")
    )
    assert road_instance_count > 0
    assert building_instance_count > 20


def test_real_city_layout_produces_finished_visual_mesh_variety_and_elevation():
    rect = pygame.Rect(0, 0, 1400, 900)
    city = IsoCity(None)
    city._layout(rect, 2_000_000, ("gas", "solar", "wind", "hydro"))
    instances = build_instances(city.tiles)

    non_empty = {name: offsets for name, offsets in instances.items() if len(offsets)}
    building_buckets = [
        name for name in non_empty
        if name in BUILDING_MATERIALS or name.startswith("downtown_")
    ]
    y_values = np.concatenate([offsets[:, 1] for offsets in non_empty.values()])

    assert len(non_empty) >= 24
    assert len(building_buckets) >= 8
    assert y_values.max() > 0.20
    assert np.unique(np.round(y_values, 2)).size >= 5


def test_real_city_layout_places_sparse_terrain_decoration_props():
    rect = pygame.Rect(0, 0, 1400, 900)
    city = IsoCity(None)
    city._layout(rect, 2_000_000, ("gas", "solar", "wind", "hydro"))
    instances = build_instances(city.tiles)

    prop_prefixes = ("bush_", "stone_", "wood_", "bones_", "cactus_")
    prop_buckets = [name for name in instances if name.startswith(prop_prefixes)]
    prop_count = sum(len(instances[name]) for name in prop_buckets)

    assert len(prop_buckets) >= 8
    assert prop_count >= 120


def _mesh_open_arms(mesh_name, threshold=1.5):
    """For a baked road mesh's `pos` array, return the set of unit (x, z)
    directions whose extreme value reaches close to the tile edge -- i.e.
    the mesh's open "connection arms" at yaw=0. A simple, GL-free geometry
    check standing in for a full render: it only inspects the bounding box
    of baked vertex positions, not actual rendered pixels."""
    from ui import terrain3d

    manifest = terrain3d.load_kit_manifest()
    source_key = terrain3d.KIT_ACTIVE_MESH_SOURCES[mesh_name]
    data = np.load(terrain3d.kit_artifact_path(manifest[source_key]))
    pos = data["pos"]
    arms = set()
    for axis, positive in (("x", True), ("x", False), ("z", True), ("z", False)):
        col = pos[:, 0] if axis == "x" else pos[:, 2]
        extreme = col.max() if positive else col.min()
        if abs(extreme) >= threshold:
            vec = (1, 0) if axis == "x" else (0, 1)
            if not positive:
                vec = (-vec[0], -vec[1])
            arms.add(vec)
    return arms


def _rotate(vec, yaw_deg):
    """Same 2D rotation the vertex shader applies to (x, z). The shader
    builds `mat3(c,0,-s, 0,1,0, s,0,c)` via GLSL's column-major constructor,
    which is the matrix [[c,0,s],[0,1,0],[-s,0,c]]: new_x = x*cos(yaw) +
    z*sin(yaw), new_z = -x*sin(yaw) + z*cos(yaw)."""
    theta = np.deg2rad(yaw_deg)
    c, s = np.cos(theta), np.sin(theta)
    x, z = vec
    return (round(x * c + z * s), round(-x * s + z * c))


# Each role's required neighbor directions in (x, z) unit vectors, per
# ui.road_network.assign_roles's docstring and this module's position
# formula (up/row-1 -> +X, down/row+1 -> -X, left/col-1 -> -Z,
# right/col+1 -> +Z).
_ROLE_REQUIRED_ARMS = {
    "straight_ne": {(1, 0), (-1, 0)},           # up + down
    "straight_nw": {(0, 1), (0, -1)},           # left + right
    "corner_ne": {(1, 0), (0, 1)},              # up + right
    "corner_nw": {(-1, 0), (0, -1)},            # down + left
    "tee_ne": {(1, 0), (-1, 0), (0, -1)},       # up + down + left
    "tee_nw": {(0, 1), (0, -1), (-1, 0)},       # left + right + down
}


def test_road_mesh_geometry_arms_match_yaw_rotated_role_connectivity():
    """Pure numpy/geometry check tying each baked road mesh's actual open
    arms (from its .npz bounding box) to the neighbor connectivity its role
    name requires, once rotated by ROAD_ROLE_TO_SHAPE_YAW's yaw -- no GL
    context needed. `cross` is 4-way symmetric so it is not checked here
    (any yaw is equally valid for it)."""
    from ui import terrain3d

    for role, required in _ROLE_REQUIRED_ARMS.items():
        shape, yaw = ROAD_ROLE_TO_SHAPE_YAW[role]
        for mesh_name, _source in terrain3d.ROAD_VARIANT_SOURCES[shape]:
            base_arms = _mesh_open_arms(mesh_name)
            rotated_arms = {_rotate(arm, yaw) for arm in base_arms}
            assert rotated_arms == required, (
                role, mesh_name, yaw, required, rotated_arms)


class _FakeCamera:
    def __init__(self, center=(0.0, 0.0), zoom=1.0):
        self.center = list(center)
        self.zoom = zoom


def _flat_test_quad(rgb):
    pos = np.array([
        [-1.0, 0.0, -1.0],
        [1.0, 0.0, -1.0],
        [1.0, 0.0, 1.0],
        [-1.0, 0.0, 1.0],
    ], dtype="f4")
    nrm = np.tile(np.array([0.0, -1.0, 0.0], dtype="f4"), (4, 1))
    uv = np.array([[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]], dtype="f4")
    idx = np.array([[0, 1, 2], [0, 2, 3]], dtype="i4")
    tex = np.array([[[rgb[0], rgb[1], rgb[2], 255]]], dtype="u1")
    return pos, nrm, uv, idx, tex


def test_load_meshes_covers_terrain_road_and_building_materials():
    from ui import terrain3d

    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        assert set(terrain3d.RUNTIME_MESH_NAMES) <= set(meshes)
        assert set(MATERIALS) <= set(meshes)
        assert set(ROAD_MATERIALS) <= set(meshes)
        assert set(BUILDING_MATERIALS) <= set(meshes)
        for mesh in meshes.values():
            mesh.release()
    finally:
        ctx.release()


def test_load_meshes_uses_kit_manifest_for_active_terrain_and_roads():
    from ui import terrain3d

    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        active = terrain3d.KIT_ACTIVE_MESH_SOURCES
        for material in MATERIALS:
            assert meshes[material].source_key == active[material]
        for shape in ROAD_MATERIALS:
            assert meshes[shape].source_key == active[shape]
        for mesh in meshes.values():
            mesh.release()
    finally:
        ctx.release()


def test_load_meshes_accepts_string_mesh_dir_paths():
    from ui import terrain3d

    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog, mesh_dir=str(MESH_DIR))
        assert set(terrain3d.RUNTIME_MESH_NAMES) <= set(meshes)
        for mesh in meshes.values():
            mesh.release()
    finally:
        ctx.release()


def test_load_meshes_custom_mesh_dir_keeps_variant_buckets_renderable():
    from ui import terrain3d

    ctx = create_context()
    try:
        prog = create_program(ctx)
        custom_mesh_dir = Path("energy_grid_game") / "assets" / "terrain3d"
        assert custom_mesh_dir != MESH_DIR
        meshes = load_meshes(ctx, prog, mesh_dir=custom_mesh_dir)
        try:
            instances = {
                "grass_2": np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4"),
                "straight_4": np.array([[3.2, 0.0, 0.0, 0.0]], dtype="f4"),
                "downtown_office_c": np.array([[6.4, 0.0, 0.0, 0.0]], dtype="f4"),
                "bush_1": np.array([[9.6, 0.0, 0.0, 0.0]], dtype="f4"),
            }
            upload_instances(ctx, meshes, instances)
            for name in instances:
                assert meshes[name].instance_count == 1
        finally:
            for mesh in meshes.values():
                mesh.release()
    finally:
        ctx.release()


def test_draw_produces_a_readable_framebuffer_with_visible_content():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        upload_instances(ctx, meshes, {"grass": np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4")})
        fbo = create_framebuffer(ctx, (64, 64))
        draw(ctx, prog, meshes, fbo, _FakeCamera(center=(0.0, 0.0), zoom=1.0))
        rgba, size = read_rgba(fbo)
        assert size == (64, 64)
        pixels = np.frombuffer(rgba, dtype="u1").reshape(64, 64, 4)
        # A single grass instance at the origin, camera centered on it, must
        # paint at least some non-background pixels near the middle.
        assert pixels[:, :, 3].max() > 0
    finally:
        ctx.release()


def test_mixed_lit_and_unlit_meshes_do_not_leak_unlit_state():
    from ui import terrain3d

    ctx = create_context()
    try:
        prog = create_program(ctx)
        red_mesh = terrain3d.GLMesh(
            ctx, prog, *_flat_test_quad((255, 0, 0)),
            unlit=True,
            weather_role=terrain3d.WEATHER_BILLBOARD,
        )
        blue_mesh = terrain3d.GLMesh(
            ctx, prog, *_flat_test_quad((0, 0, 255)),
            unlit=False,
            weather_role=terrain3d.WEATHER_BILLBOARD,
        )
        red_mesh.set_instances(np.array([[-2.0, 0.0, 0.0, 0.0]], dtype="f4"))
        blue_mesh.set_instances(np.array([[2.0, 0.0, 0.0, 0.0]], dtype="f4"))
        fbo = create_framebuffer(ctx, (96, 64))
        draw(ctx, prog, {"red": red_mesh, "blue": blue_mesh}, fbo,
             _FakeCamera(center=(0.0, 0.0), zoom=6.0), ambient=0.0)
        rgba, size = read_rgba(fbo)
        pixels = np.frombuffer(rgba, dtype="u1").reshape(size[1], size[0], 4)

        assert pixels[:, :, 0].max() >= 250
        assert pixels[:, :, 2].max() <= 40
        red_mesh.release()
        blue_mesh.release()
        fbo.release()
    finally:
        ctx.release()


def test_road_weather_role_darkens_and_desaturates_under_wet_weather():
    from ui import terrain3d

    ctx = create_context()
    try:
        prog = create_program(ctx)
        road_mesh = terrain3d.GLMesh(
            ctx, prog, *_flat_test_quad((60, 170, 220)),
            unlit=True,
            weather_role=terrain3d.WEATHER_ROAD,
        )
        road_mesh.set_instances(np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4"))
        camera = _FakeCamera(center=(0.0, 0.0), zoom=8.0)

        dry_fbo = create_framebuffer(ctx, (64, 64))
        draw(ctx, prog, {"road": road_mesh}, dry_fbo, camera, wet_mix=0.0)
        dry_rgba, size = read_rgba(dry_fbo)

        wet_fbo = create_framebuffer(ctx, (64, 64))
        draw(ctx, prog, {"road": road_mesh}, wet_fbo, camera, wet_mix=1.0)
        wet_rgba, _ = read_rgba(wet_fbo)

        dry = np.frombuffer(dry_rgba, dtype="u1").reshape(size[1], size[0], 4)
        wet = np.frombuffer(wet_rgba, dtype="u1").reshape(size[1], size[0], 4)
        dry_mask = dry[:, :, 3] > 0
        wet_mask = wet[:, :, 3] > 0
        dry_rgb = dry[:, :, :3][dry_mask]
        wet_rgb = wet[:, :, :3][wet_mask]

        assert wet_rgb.max() < dry_rgb.max()
        assert (wet_rgb.max(axis=1) - wet_rgb.min(axis=1)).mean() < (
            dry_rgb.max(axis=1) - dry_rgb.min(axis=1)
        ).mean()
        road_mesh.release()
        dry_fbo.release()
        wet_fbo.release()
    finally:
        ctx.release()


def test_draw_real_city_layout_lands_near_viewport_center():
    from types import SimpleNamespace

    viewport = pygame.Rect(0, 0, 1000, 680)
    gas = SimpleNamespace(
        key="gas", max_output_mw=750.0, ramp_up_latency=3, ramp_down_latency=3)
    state = SimpleNamespace(population=2_000_000, sources=[gas])
    city = IsoCity(None)
    city.prepare(viewport, state)
    city.camera.center = [city._origin[0], city._origin[1]]
    city.camera.zoom = 1

    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        upload_instances(ctx, meshes, build_instances(city.tiles))
        tx = load_transmission(
            ctx, prog, build_transmission_geometry(city.transmission3d, city._origin))
        fbo = create_framebuffer(ctx, viewport.size)
        draw(ctx, prog, meshes, fbo, city.camera, transmission_meshes=tx,
             world_origin=city._origin)
        rgba, size = read_rgba(fbo)
        pixels = np.frombuffer(rgba, dtype="u1").reshape(size[1], size[0], 4)
        background = np.array([25, 28, 33], dtype="u1")
        changed = np.abs(pixels[:, :, :3].astype("i2") - background.astype("i2")).sum(axis=2) > 20
        ys, xs = np.where(changed)
        assert xs.size > 0
        assert abs(float(xs.mean()) - viewport.centerx) < viewport.width * 0.20
        assert abs(float(ys.mean()) - viewport.centery) < viewport.height * 0.20
        release_transmission(tx)
        fbo.release()
    finally:
        ctx.release()


def test_to_surface_returns_a_surface_of_the_requested_size():
    rgba = bytes([255, 0, 0, 255] * (8 * 8))
    surf = to_surface(rgba, (8, 8))
    assert isinstance(surf, pygame.Surface)
    assert surf.get_size() == (8, 8)


def test_load_meshes_assigns_weather_roles_by_mesh_family():
    from ui import terrain3d

    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        for material in MATERIALS:
            assert meshes[material].weather_role == terrain3d.WEATHER_TERRAIN
        for shape in ROAD_MATERIALS:
            assert meshes[shape].weather_role == terrain3d.WEATHER_ROAD
        for archetype in BUILDING_MATERIALS:
            assert meshes[archetype].weather_role == terrain3d.WEATHER_BUILDING
        for mesh in meshes.values():
            mesh.release()
    finally:
        ctx.release()


def test_instance_yaw_actually_rotates_the_rendered_mesh():
    """The `straight` road mesh is longer along one axis than the other (a
    road segment, not a symmetric tile) -- render it once at yaw=0 and once
    at yaw=90 into separate framebuffers and confirm the rendered alpha
    footprints differ, proving the shader's per-instance rotation actually
    executes rather than being a no-op."""
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        camera = _FakeCamera(center=(0.0, 0.0), zoom=1.0)

        upload_instances(ctx, meshes, {"straight": np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4")})
        fbo_a = create_framebuffer(ctx, (128, 128))
        draw(ctx, prog, meshes, fbo_a, camera)
        rgba_a, _ = read_rgba(fbo_a)

        upload_instances(ctx, meshes, {"straight": np.array([[0.0, 0.0, 0.0, 90.0]], dtype="f4")})
        fbo_b = create_framebuffer(ctx, (128, 128))
        draw(ctx, prog, meshes, fbo_b, camera)
        rgba_b, _ = read_rgba(fbo_b)

        assert rgba_a != rgba_b
    finally:
        ctx.release()


def test_camera_basis_vectors_are_orthonormal():
    right, up, facing = camera_basis()
    for v in (right, up, facing):
        assert abs(np.linalg.norm(v) - 1.0) < 1e-6
    assert abs(np.dot(right, up)) < 1e-6
    assert abs(np.dot(right, facing)) < 1e-6
    assert abs(np.dot(up, facing)) < 1e-6
    # up should be world-vertical: billboards stand upright, matching the
    # existing 2D sprites' "flat cutout standing on the ground" convention.
    assert np.allclose(up, np.array([0.0, 1.0, 0.0]), atol=1e-6)
    # facing must point back TOWARD the camera, not into the scene: for the
    # fixed CAM_ROT (_AY=45deg, _AX=30deg) that horizontal direction is
    # (-0.7071, 0, 0.7071), the negation of the away-from-camera direction a
    # sign flip would produce. Orthonormality alone can't catch a sign bug.
    assert np.allclose(facing, np.array([-0.70710678, 0.0, 0.70710678]), atol=1e-6)


def test_billboard_quad_has_four_verts_and_two_triangles():
    pos, nrm, uv, idx = billboard_quad(2.0, 3.0)
    assert pos.shape == (4, 3)
    assert nrm.shape == (4, 3)
    assert uv.shape == (4, 2)
    assert idx.shape == (2, 3)
    # bottom edge at y=0, top edge at y=height, centered on x=0 in the
    # camera-facing basis (before the per-instance world offset is added)
    assert np.isclose(pos[:, 1].min(), 0.0)
    assert np.isclose(pos[:, 1].max(), 3.0)


def test_create_dynamic_texture_matches_surface_size():
    ctx = create_context()
    try:
        surf = pygame.Surface((17, 23), pygame.SRCALPHA)
        surf.fill((255, 0, 0, 255))
        tex = create_dynamic_texture(ctx, surf)
        assert tex.size == (17, 23)
    finally:
        ctx.release()


class _FakePlantSite:
    def __init__(self, key, col, row, w, h):
        self.key = key
        self.col, self.row = col, row
        self.sprite = pygame.Surface((w, h), pygame.SRCALPHA)


def test_build_plant_billboards_converts_col_row_and_sprite_size():
    plants = [_FakePlantSite("gas", 3, -5, 32, 64)]
    billboards = build_plant_billboards(plants)
    assert len(billboards) == 1
    b = billboards[0]
    assert b["key"] == "gas"
    assert np.allclose(b["offset"], (5.0 * TILE_SPACING, 0.0, 3.0 * TILE_SPACING))
    assert np.isclose(b["width_world"], 32 / PX_PER_UNIT)
    # height is corrected for camera vertical foreshortening (see
    # billboard_quad's docstring note): dividing by PX_PER_UNIT alone would
    # render the billboard ~13% too short relative to its width, since
    # up_world isn't perpendicular to the camera view direction the way
    # right_world is. Dividing by PX_PER_UNIT * _VERTICAL_FORESHORTENING
    # instead makes the on-screen height match the sprite's pixel aspect
    # ratio.
    assert np.isclose(
        b["height_world"], 64 / (PX_PER_UNIT * _VERTICAL_FORESHORTENING)
    )
    assert b["surface"] is plants[0].sprite


def test_build_plant_billboards_handles_multiple_plants():
    plants = [_FakePlantSite("gas", 0, 0, 10, 10), _FakePlantSite("solar", 5, 5, 20, 20)]
    assert len(build_plant_billboards(plants)) == 2


def test_screen_px_to_world_round_trips_iso_projected_tile_center():
    from ui.iso_city import iso_xy
    col, row = 7, -3
    origin = (700.0, 392.0)
    sx, sy = iso_xy(col, row)
    world = screen_px_to_world((sx + origin[0], sy + origin[1]), origin)
    expected = (-float(row) * TILE_SPACING, 0.0, float(col) * TILE_SPACING)
    assert np.allclose(world, expected, atol=1e-5)


def test_build_transmission_geometry_creates_towers_and_conductors():
    origin = (700.0, 392.0)
    snapshot = ({
        "key": "gas",
        "substation_index": 0,
        "tower_points": ((700.0, 392.0), (716.0, 400.0)),
        "conductor_paths": {
            -6: ((694.0, 376.0), (710.0, 384.0)),
            6: ((706.0, 376.0), (722.0, 384.0)),
        },
    },)
    geom = build_transmission_geometry(snapshot, origin=origin)
    assert len(geom["towers"]) == 2
    assert len(geom["conductors"]) == 2
    assert geom["towers"][0]["key"] == "gas"
    assert geom["conductors"][0]["key"] == "gas"
    first_source = snapshot[0]["conductor_paths"][-6][0]
    first_world = np.array([*geom["conductors"][0]["points"][0], 0.0], dtype="f4")
    sx, sy = _project(first_world)
    assert np.allclose((sx + origin[0], sy + origin[1]), first_source, atol=1e-4)
    assert geom["conductors"][0]["points"][0][1] == TRANSMISSION_CONDUCTOR_HEIGHT_WORLD


def test_build_transmission_geometry_from_a_real_city_layout():
    from types import SimpleNamespace

    viewport = pygame.Rect(0, 0, 1400, 700)
    gas = SimpleNamespace(
        key="gas", max_output_mw=750.0, ramp_up_latency=3, ramp_down_latency=3)
    solar = SimpleNamespace(
        key="solar", max_output_mw=100.0, ramp_up_latency=1, ramp_down_latency=1)
    state = SimpleNamespace(population=200_000, sources=[gas, solar])
    city = IsoCity(None)
    city.prepare(viewport, state)

    geom = build_transmission_geometry(city.transmission3d, city._origin)
    assert len(geom["towers"]) >= len(city.transmission3d)
    assert len(geom["conductors"]) == len(city.transmission3d) * 2
    route_tower_points = sum(len(route["tower_points"]) for route in city.transmission3d)
    assert len(geom["towers"]) == route_tower_points
    by_route = {
        (conductor["key"], conductor["substation_index"], conductor["arm"]): conductor
        for conductor in geom["conductors"]
    }
    for route in city.transmission3d:
        for arm, source_points in route["conductor_paths"].items():
            conductor = by_route[(route["key"], route["substation_index"], arm)]
            assert len(conductor["points"]) == len(source_points)
            for source, world in (
                (source_points[0], conductor["points"][0]),
                (source_points[-1], conductor["points"][-1]),
            ):
                sx, sy = _project(np.array([*world, 0.0], dtype="f4"))
                projected = (sx + city._origin[0], sy + city._origin[1])
                assert np.allclose(projected, source, atol=1.0)


def test_tower_billboards_use_shared_surface_and_offsets():
    towers = [{"key": "gas", "substation_index": 0, "offset": (1.0, 0.0, 2.0)}]
    billboards = build_tower_billboards(towers)
    assert len(billboards) == 1
    assert billboards[0]["offset"] == (1.0, 0.0, 2.0)
    assert billboards[0]["surface"].get_width() > 0
    assert billboards[0]["surface"].get_height() > 0


def test_load_transmission_creates_releasable_resources():
    from ui import terrain3d

    ctx = create_context()
    try:
        prog = create_program(ctx)
        geometry = {
            "towers": [{"key": "gas", "substation_index": 0, "offset": (0.0, 0.0, 0.0)}],
            "conductors": [{
                "key": "gas", "substation_index": 0, "arm": -6,
                "points": ((0.0, 0.0, 0.0), (3.2, 0.0, 0.0)),
            }],
        }
        tx = load_transmission(ctx, prog, geometry)
        assert tx["towers"]
        assert tx["towers"][0].weather_role == terrain3d.WEATHER_BILLBOARD
        assert tx["conductors"] is not None
        assert tx["conductors"].weather_role == terrain3d.WEATHER_METAL
        release_transmission(tx)
    finally:
        ctx.release()


def test_load_transmission_does_not_draw_empty_conductors():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        tx = load_transmission(ctx, prog, {"towers": [], "conductors": []})
        assert tx["conductors"] is not None
        assert tx["conductors"].instance_count == 0
        release_transmission(tx)
    finally:
        ctx.release()


def test_load_billboards_marks_meshes_unlit():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        surf = pygame.Surface((8, 8), pygame.SRCALPHA)
        surf.fill((255, 0, 0, 255))
        meshes = load_billboards(ctx, prog, [{
            "key": "test",
            "offset": (0.0, 0.0, 0.0),
            "width_world": 8 / PX_PER_UNIT,
            "height_world": 8 / (PX_PER_UNIT * _VERTICAL_FORESHORTENING),
            "surface": surf,
        }])
        assert meshes[0].unlit is True
        for mesh in meshes:
            mesh.release()
    finally:
        ctx.release()


def test_billboard_renders_full_brightness_when_ambient_is_zero():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        surf = pygame.Surface((16, 16), pygame.SRCALPHA)
        surf.fill((255, 0, 0, 255))
        billboards = [{
            "key": "test",
            "offset": (0.0, 0.0, 0.0),
            "width_world": 16 / PX_PER_UNIT,
            "height_world": 16 / (PX_PER_UNIT * _VERTICAL_FORESHORTENING),
            "surface": surf,
        }]
        meshes = load_billboards(ctx, prog, billboards)
        fbo = create_framebuffer(ctx, (64, 64))
        draw(ctx, prog, {}, fbo, _FakeCamera(center=(0.0, 0.0), zoom=1.0),
             billboard_meshes=meshes, ambient=0.0)
        rgba, size = read_rgba(fbo)
        pixels = np.frombuffer(rgba, dtype="u1").reshape(size[1], size[0], 4)
        assert pixels[:, :, 0].max() >= 250
        for mesh in meshes:
            mesh.release()
        fbo.release()
    finally:
        ctx.release()


def test_unlit_billboard_still_receives_global_light_tint():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        surf = pygame.Surface((16, 16), pygame.SRCALPHA)
        surf.fill((255, 0, 0, 255))
        billboards = [{
            "key": "test",
            "offset": (0.0, 0.0, 0.0),
            "width_world": 16 / PX_PER_UNIT,
            "height_world": 16 / (PX_PER_UNIT * _VERTICAL_FORESHORTENING),
            "surface": surf,
        }]
        meshes = load_billboards(ctx, prog, billboards)
        fbo = create_framebuffer(ctx, (64, 64))
        draw(ctx, prog, {}, fbo, _FakeCamera(center=(0.0, 0.0), zoom=1.0),
             billboard_meshes=meshes, ambient=0.0, light_tint=(0.5, 1.0, 1.0))
        rgba, size = read_rgba(fbo)
        pixels = np.frombuffer(rgba, dtype="u1").reshape(size[1], size[0], 4)
        assert 110 <= int(pixels[:, :, 0].max()) <= 145
        for mesh in meshes:
            mesh.release()
        fbo.release()
    finally:
        ctx.release()


def test_draw_renders_transmission_conductor_pixels():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        upload_instances(ctx, meshes, {})
        geometry = {
            "towers": [],
            "conductors": [{
                "key": "gas", "substation_index": 0, "arm": -6,
                "points": ((-1.6, 0.0, 0.0), (1.6, 0.0, 0.0)),
            }],
        }
        tx = load_transmission(ctx, prog, geometry)
        fbo = create_framebuffer(ctx, (128, 128))
        draw(ctx, prog, meshes, fbo, _FakeCamera(center=(0.0, 0.0), zoom=4.0),
             transmission_meshes=tx)
        rgba, size = read_rgba(fbo)
        pixels = np.frombuffer(rgba, dtype="u1").reshape(size[1], size[0], 4)
        background = np.array([25, 28, 33], dtype="u1")
        assert np.any(np.abs(pixels[:, :, :3].astype("i2") - background.astype("i2")).sum(axis=2) > 20)
        release_transmission(tx)
    finally:
        ctx.release()


def test_draw_renders_transmission_conductors_above_terrain():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        upload_instances(ctx, meshes, {"grass": np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4")})
        camera = _FakeCamera(center=(0.0, 0.0), zoom=4.0)
        base_fbo = create_framebuffer(ctx, (128, 128))
        draw(ctx, prog, meshes, base_fbo, camera)
        base_rgba, size = read_rgba(base_fbo)

        geometry = {
            "towers": [],
            "conductors": [{
                "key": "gas", "substation_index": 0, "arm": -6,
                "points": ((-1.6, TRANSMISSION_CONDUCTOR_HEIGHT_WORLD, 0.0),
                           (1.6, TRANSMISSION_CONDUCTOR_HEIGHT_WORLD, 0.0)),
            }],
        }
        tx = load_transmission(ctx, prog, geometry)
        tx_fbo = create_framebuffer(ctx, (128, 128))
        draw(ctx, prog, meshes, tx_fbo, camera, transmission_meshes=tx)
        tx_rgba, _ = read_rgba(tx_fbo)

        base = np.frombuffer(base_rgba, dtype="u1").reshape(size[1], size[0], 4)
        with_tx = np.frombuffer(tx_rgba, dtype="u1").reshape(size[1], size[0], 4)
        diff = np.abs(with_tx[:, :, :3].astype("i2") - base[:, :, :3].astype("i2"))
        assert np.any(diff.sum(axis=2) > 20)
        release_transmission(tx)
        base_fbo.release()
        tx_fbo.release()
    finally:
        ctx.release()


def test_conductor_strip_mesh_builds_quads_for_each_segment():
    conductors = [{
        "key": "gas",
        "substation_index": 0,
        "arm": -6,
        "points": ((0.0, 0.0, 0.0), (3.2, 0.0, 0.0), (6.4, 0.0, 0.0)),
    }]
    pos, nrm, uv, idx, tex = conductor_strip_mesh(conductors)
    assert pos.shape == (8, 3)      # two segments, four verts each
    assert idx.shape == (4, 3)      # two triangles per segment
    assert tex.shape == (1, 1, 4)


def test_build_plant_billboards_from_a_real_city_layout():
    """Integration check mirroring
    test_build_instances_produces_road_instances_from_a_real_city_layout:
    a real IsoCity layout's PlantSite objects (with PlantSite.sprite set by
    _layout(), per Finding 2) must actually produce usable billboard data."""
    from types import SimpleNamespace

    viewport = pygame.Rect(0, 0, 1400, 700)
    gas = SimpleNamespace(
        key="gas", max_output_mw=750.0, ramp_up_latency=3, ramp_down_latency=3)
    solar = SimpleNamespace(
        key="solar", max_output_mw=100.0, ramp_up_latency=1, ramp_down_latency=1)
    state = SimpleNamespace(population=200_000, sources=[gas, solar])
    city = IsoCity(None)
    city.prepare(viewport, state)
    billboards = build_plant_billboards(city.plants)
    assert len(billboards) >= 1
    for b in billboards:
        assert b["surface"] is not None
        assert b["width_world"] > 0
        assert b["height_world"] > 0


def _count_red_pixels(ctx, prog, tower_offset_xyz, camera):
    """Render a 'tower' building instance at `tower_offset_xyz` together
    with a solid-red billboard fixed at the world origin, and return how
    many rendered pixels read back as "red" (the billboard's shaded fill).

    Under this file's banded lighting (LIGHT vs. the billboard's fixed
    facing_normal from camera_basis()), a pure (255,0,0,255) fill renders at
    R ~= 178.5 (lambert ~= 0.597, banded to the 1/3 band, bright = 0.55 +
    0.45*(1/3) = 0.70, 255*0.70 = 178.5) -- NOT the R > 200 an earlier
    version of this test checked for, which could never fire since nothing
    in this scene renders above that value. R > 150 sits safely below the
    actual rendered value with margin, while staying well above the (25,
    28, 33) background clear color and other meshes' shading."""
    meshes = load_meshes(ctx, prog)
    upload_instances(
        ctx, meshes,
        {"tower": np.array([[*tower_offset_xyz, 0.0]], dtype="f4")},
    )
    red_surface = pygame.Surface((32, 64), pygame.SRCALPHA)
    red_surface.fill((255, 0, 0, 255))
    billboards = [{"key": "test", "offset": (0.0, 0.0, 0.0),
                   "width_world": 2.0, "height_world": 2.0, "surface": red_surface}]
    billboard_meshes = load_billboards(ctx, prog, billboards)
    fbo = create_framebuffer(ctx, (128, 128))
    draw(ctx, prog, meshes, fbo, camera, billboard_meshes=billboard_meshes)
    rgba, size = read_rgba(fbo)
    pixels = np.frombuffer(rgba, dtype="u1").reshape(size[1], size[0], 4)
    is_red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 60) & (pixels[:, :, 2] < 60)
    for mesh in meshes.values():
        mesh.release()
    for mesh in billboard_meshes:
        mesh.release()
    fbo.color_attachments[0].release()
    fbo.depth_attachment.release()
    fbo.release()
    return int(is_red.sum())


def test_billboard_is_occluded_by_a_nearer_building_instance():
    """Synthetic proof of the core Phase 3a claim: a billboard is hidden by
    a building instance that is nearer to the camera, because both share
    the same depth buffer.

    The billboard stays fixed at the world origin. The tower instance is
    slid along CAM_ROT[2] -- the camera's own view-direction axis in world
    space (row index 2 of CAM_ROT, i.e. the direction cam_rot @ world maps
    onto cam.z) -- by a scalar `t`. Moving an object along this axis keeps
    its projected screen position (sx, sy) pixel-identical (since only
    cam.z, which feeds `depth`, changes -- sx/sy come from cam.x/cam.y) while
    changing how near/far it is from the camera. This is deliberately NOT
    the tower-at-origin/billboard-offset-(0,0,5) setup an earlier version of
    this test used: numeric analysis showed those two objects never share a
    screen pixel at all under this camera (disjoint sx ranges), so that
    setup could not have exercised depth testing regardless of any
    threshold fix. Camera center is offset to (-64,-64) (fbo is 128x128) so
    the world origin -- where both objects sit at t=0 -- projects to the
    center of the frame rather than to a screen corner, where an earlier
    version of this test's camera setup left it invisible/clipped.

    t < 0 moves the tower AWAY from the camera along that axis (behind the
    billboard); t > 0 moves it TOWARD the camera (in front of, i.e. nearer
    than, the billboard). Two assertions:
      1. Positive control: with the tower behind the billboard (t=-6), the
         billboard's red pixels are fully visible (proving this setup CAN
         detect the billboard at all when nothing occludes it -- a test
         that can't pass this can't meaningfully test occlusion either).
      2. The actual claim: with the tower in front of the billboard (t=+6),
         the red pixel count drops substantially, since the tower's nearer
         fragments win the depth test over the same screen pixels.
    Empirically (see this test's development notes) t=-6 renders 48 red
    pixels (full billboard silhouette) and t=+6 renders 16 (only the
    fringe peeking around the tower's narrower footprint) -- a large,
    unambiguous drop, not a borderline threshold."""
    ctx = create_context()
    try:
        prog = create_program(ctx)
        camera = _FakeCamera(center=(0.0, 0.0), zoom=1.0)
        axis = CAM_ROT[2]

        behind_count = _count_red_pixels(ctx, prog, tuple(-6.0 * axis), camera)
        assert behind_count >= 30, (
            "positive control failed: billboard should be fully visible "
            f"with nothing in front of it, got {behind_count} red pixels"
        )

        front_count = _count_red_pixels(ctx, prog, tuple(6.0 * axis), camera)
        assert front_count < behind_count / 2, (
            "tower in front of the billboard should occlude most of it: "
            f"behind={behind_count} front={front_count}"
        )
    finally:
        ctx.release()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall terrain3d checks passed")
