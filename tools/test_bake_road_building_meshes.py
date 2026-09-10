"""Road/building mesh bake checks. Run: python test_bake_road_building_meshes.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from bake_road_building_meshes import ROAD_SOURCES, BUILDING_SOURCES, bake_road, bake_building


def test_road_sources_cover_the_four_shapes():
    assert set(ROAD_SOURCES) == {"straight", "corner", "tee", "cross"}
    for rel_path in ROAD_SOURCES.values():
        assert rel_path.endswith(".gltf")


def test_building_sources_cover_the_five_archetypes():
    assert set(BUILDING_SOURCES) == {"house", "shop", "block", "midrise", "tower"}
    for rel_path in BUILDING_SOURCES.values():
        assert rel_path.endswith(".obj")


def test_bake_road_writes_a_loadable_npz():
    import tempfile
    from pathlib import Path
    out_dir = Path(tempfile.mkdtemp())
    out_path = bake_road("straight", out_dir)
    assert out_path.exists()
    data = np.load(out_path)
    assert data["pos"].shape[1] == 3
    assert data["idx"].shape[1] == 3
    assert data["tex"].ndim == 3 and data["tex"].shape[2] == 4


def test_bake_building_writes_a_loadable_npz():
    import tempfile
    from pathlib import Path
    out_dir = Path(tempfile.mkdtemp())
    out_path = bake_building("house", out_dir)
    assert out_path.exists()
    data = np.load(out_path)
    assert data["pos"].shape[1] == 3
    assert data["idx"].shape[1] == 3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall bake_road_building_meshes checks passed")
