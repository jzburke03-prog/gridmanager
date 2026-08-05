"""Terrain mesh bake checks. Run: python test_bake_terrain_meshes.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from bake_terrain_meshes import MATERIAL_SOURCES, bake_material


def test_material_sources_cover_the_five_phase1_materials():
    assert set(MATERIAL_SOURCES) == {"grass", "farm", "tree", "water", "mountain"}
    for rel_path in MATERIAL_SOURCES.values():
        assert rel_path.endswith(".gltf")


def test_bake_material_writes_a_loadable_npz(tmp_path=None):
    import tempfile
    from pathlib import Path
    out_dir = Path(tempfile.mkdtemp())
    out_path = bake_material("grass", out_dir)
    assert out_path.exists()
    data = np.load(out_path)
    assert data["pos"].ndim == 2 and data["pos"].shape[1] == 3
    assert data["nrm"].shape == data["pos"].shape
    assert data["uv"].shape[1] == 2
    assert data["idx"].shape[1] == 3
    assert data["tex"].ndim == 3 and data["tex"].shape[2] == 4


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall bake_terrain_meshes checks passed")
