"""3D terrain renderer checks. Run: python test_terrain3d.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from ui.terrain3d import MATERIALS, build_instances

import os as _os
_os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

from ui.gl_context import create_context
from ui.terrain3d import (create_framebuffer, create_program, draw,
                           load_meshes, read_rgba, to_surface,
                           upload_instances)


def test_build_instances_buckets_by_material_and_skips_non_terrain_kinds():
    tiles = {
        (0, 0): ("grass", None),
        (1, 0): ("farm", None),
        (2, 0): ("tree", None),
        (3, 0): ("water", None),
        (4, 0): ("mountain", 7),
        (5, 0): ("road", "straight_ne"),      # 2D-sprite-rendered, skip
        (6, 0): ("urban_block", "shop"),      # 2D-sprite-rendered, skip
    }
    instances = build_instances(tiles)
    assert set(instances) == {"grass", "farm", "tree", "water", "mountain"}
    for material in MATERIALS:
        assert instances[material].shape == (1, 3)
        assert instances[material].dtype == np.float32


def test_build_instances_offset_matches_col_row():
    tiles = {(3, 5): ("grass", None)}
    instances = build_instances(tiles)
    assert np.array_equal(instances["grass"][0], np.array([3.0, 0.0, 5.0], dtype="f4"))


def test_build_instances_groups_multiple_tiles_of_the_same_material():
    tiles = {(0, 0): ("grass", None), (1, 1): ("grass", None), (2, 2): ("grass", None)}
    instances = build_instances(tiles)
    assert instances["grass"].shape == (3, 3)


def test_build_instances_omits_materials_with_no_tiles():
    instances = build_instances({(0, 0): ("water", None)})
    assert set(instances) == {"water"}


class _FakeCamera:
    def __init__(self, center=(0.0, 0.0), zoom=1.0):
        self.center = list(center)
        self.zoom = zoom


def test_load_meshes_covers_all_materials():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        assert set(meshes) == set(MATERIALS)
    finally:
        ctx.release()


def test_draw_produces_a_readable_framebuffer_with_visible_content():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        upload_instances(ctx, meshes, {"grass": np.array([[0.0, 0.0, 0.0]], dtype="f4")})
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
