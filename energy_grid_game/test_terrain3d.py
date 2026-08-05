"""3D terrain renderer checks. Run: python test_terrain3d.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from ui.terrain3d import MATERIALS, build_instances


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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall terrain3d checks passed")
