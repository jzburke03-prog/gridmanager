"""3D terrain renderer checks. Run: python test_terrain3d.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from ui.terrain3d import (BUILDING_MATERIALS, CAM_ROT, MATERIALS,
                           ROAD_MATERIALS, ROAD_ROLE_TO_SHAPE_YAW,
                           TILE_SPACING, build_instances)
from ui.iso_city import iso_xy

import os as _os
_os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

from ui.gl_context import create_context
from ui.terrain3d import (create_framebuffer, create_program, draw,
                           load_meshes, read_rgba, to_surface,
                           upload_instances)


def test_build_instances_buckets_by_material_and_skips_unrecognized_kinds():
    tiles = {
        (0, 0): ("grass", None),
        (1, 0): ("farm", None),
        (2, 0): ("tree", None),
        (3, 0): ("water", None),
        (4, 0): ("mountain", 7),
        (5, 0): ("nonsense_kind", None),  # not a terrain/road/building kind, skip
        (6, 0): ("road", "not_a_real_role"),  # unrecognized role, skip
    }
    instances = build_instances(tiles)
    assert set(instances) == {"grass", "farm", "tree", "water", "mountain"}
    for material in MATERIALS:
        assert instances[material].shape == (1, 4)
        assert instances[material].dtype == np.float32


def test_build_instances_offset_matches_col_row():
    tiles = {(3, 5): ("grass", None)}
    instances = build_instances(tiles)
    expected = np.array([-5.0 * TILE_SPACING, 0.0, 3.0 * TILE_SPACING, 0.0], dtype="f4")
    assert np.array_equal(instances["grass"][0], expected)


def test_build_instances_groups_multiple_tiles_of_the_same_material():
    tiles = {(0, 0): ("grass", None), (1, 1): ("grass", None), (2, 2): ("grass", None)}
    instances = build_instances(tiles)
    assert instances["grass"].shape == (3, 4)


def test_build_instances_omits_materials_with_no_tiles():
    instances = build_instances({(0, 0): ("water", None)})
    assert set(instances) == {"water"}


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
        offset = build_instances(tiles)["grass"][0]
        cam = CAM_ROT @ offset[:3]
        sx = cam[0]
        screen_y = -cam[1]
        iso_x, iso_y = iso_xy(col, row)
        assert np.sign(sx) == np.sign(iso_x), (col, row, sx, iso_x)
        assert np.sign(screen_y) == np.sign(iso_y), (col, row, screen_y, iso_y)


def test_build_instances_buckets_road_tiles_by_shape_with_correct_yaw():
    tiles = {
        (0, 0): ("road", "straight_ne"),
        (1, 0): ("road", "straight_nw"),
        (2, 0): ("road", "cross"),
    }
    instances = build_instances(tiles)
    assert instances["straight"].shape == (2, 4)
    yaws = sorted(instances["straight"][:, 3].tolist())
    assert yaws == [0.0, 90.0]
    assert instances["cross"].shape == (1, 4)
    assert instances["cross"][0, 3] == 0.0


def test_road_role_to_shape_yaw_covers_all_seven_roles():
    assert set(ROAD_ROLE_TO_SHAPE_YAW) == {
        "straight_ne", "straight_nw", "corner_ne", "corner_nw",
        "tee_ne", "tee_nw", "cross"}
    for shape, yaw in ROAD_ROLE_TO_SHAPE_YAW.values():
        assert shape in ROAD_MATERIALS
        assert yaw in (0.0, 90.0)


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


class _FakeCamera:
    def __init__(self, center=(0.0, 0.0), zoom=1.0):
        self.center = list(center)
        self.zoom = zoom


def test_load_meshes_covers_terrain_road_and_building_materials():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        assert set(meshes) == set(MATERIALS) | set(ROAD_MATERIALS) | set(BUILDING_MATERIALS)
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


def test_to_surface_returns_a_surface_of_the_requested_size():
    rgba = bytes([255, 0, 0, 255] * (8 * 8))
    surf = to_surface(rgba, (8, 8))
    assert isinstance(surf, pygame.Surface)
    assert surf.get_size() == (8, 8)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall terrain3d checks passed")
