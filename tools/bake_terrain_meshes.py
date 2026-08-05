#!/usr/bin/env python3
"""Bake curated glTF terrain meshes from newassets/terrain/gltf/ into compact
.npz files the runtime 3D renderer (ui/terrain3d.py) loads directly, so the
running game never parses raw glTF/JSON -- same bake-time-only principle as
tools/bake_gltf_terrain.py's PNG sprite bake, just a different output format
(raw geometry + texture arrays instead of a pre-rendered image).

One base mesh per Phase 1 material -- no edge/corner connector variants and
no decoration compositing yet (e.g. "tree" tiles render as a standalone tree
mesh with no separate ground plane underneath). See the Phase 1 design doc's
Non-goals section.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bake_gltf_terrain import load_gltf  # noqa: E402  (path setup above)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "newassets" / "terrain" / "gltf"
OUT = ROOT / "energy_grid_game" / "assets" / "terrain3d"

MATERIAL_SOURCES = {
    "grass": "Forest/forest-1.gltf",
    "farm": "Dirt/dirt-1.gltf",
    "tree": "Trees/tree-1.gltf",
    "water": "Water/water-1.gltf",
    "mountain": "Mountains/mountain-1.gltf",
}


def bake_material(material, out_dir=OUT):
    rel_path = MATERIAL_SOURCES[material]
    pos, nrm, uv, idx, tex = load_gltf(SRC / rel_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{material}.npz"
    np.savez(out_path,
              pos=pos.astype("f4"), nrm=nrm.astype("f4"),
              uv=uv.astype("f4"), idx=idx.astype("i4"),
              tex=tex.astype("u1"))
    return out_path


def main():
    for material in MATERIAL_SOURCES:
        out_path = bake_material(material)
        print(f"baked {material} -> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
