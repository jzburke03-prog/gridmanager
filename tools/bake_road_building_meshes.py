#!/usr/bin/env python3
"""Bake the 4 road-shape meshes and 5 building-archetype meshes Phase 2 needs
into .npz files, the same way tools/bake_terrain_meshes.py baked Phase 1's
terrain materials. Road shapes: one mesh per SHAPE (straight/corner/tee/
cross), not one per road_network.py role string -- roles like straight_ne
vs straight_nw are the same shape at a different yaw, applied per-instance
at render time by ui/terrain3d.py, not baked as separate meshes. See
docs/superpowers/specs/2026-08-05-realtime-3d-terrain-phase2-design.md.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bake_gltf_terrain import load_gltf, load_obj  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GLTF_SRC = ROOT / "newassets" / "terrain" / "gltf"
OBJ_SRC = ROOT / "newassets" / "City Voxel Pack" / "OBJ"
OUT = ROOT / "energy_grid_game" / "assets" / "terrain3d"

ROAD_SOURCES = {
    "straight": "Roads/road-straight-1.gltf",
    "corner": "Roads/road-edgy-curve-1.gltf",
    "tee": "Roads/road-edgy-3-way-crossing-1.gltf",
    "cross": "Roads/road-edgy-4-way-crossing-1.gltf",
}

BUILDING_SOURCES = {
    "house": "Building01.obj",
    "shop": "Building02.obj",
    "block": "Building03.obj",
    "midrise": "Building04.obj",
    "tower": "Building05.obj",
}


def _save(out_path, pos, nrm, uv, idx, tex):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out_path,
             pos=pos.astype("f4"), nrm=nrm.astype("f4"),
             uv=uv.astype("f4"), idx=idx.astype("i4"),
             tex=tex.astype("u1"))
    return out_path


def bake_road(shape, out_dir=OUT / "roads"):
    pos, nrm, uv, idx, tex = load_gltf(GLTF_SRC / ROAD_SOURCES[shape])
    return _save(out_dir / f"{shape}.npz", pos, nrm, uv, idx, tex)


def bake_building(archetype, out_dir=OUT / "buildings"):
    pos, nrm, uv, idx, tex = load_obj(OBJ_SRC / BUILDING_SOURCES[archetype])
    return _save(out_dir / f"{archetype}.npz", pos, nrm, uv, idx, tex)


def main():
    for shape in ROAD_SOURCES:
        out_path = bake_road(shape)
        print(f"baked road/{shape} -> {out_path.relative_to(ROOT)}")
    for archetype in BUILDING_SOURCES:
        out_path = bake_building(archetype)
        print(f"baked building/{archetype} -> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
