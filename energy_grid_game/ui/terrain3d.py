"""Real-time 3D terrain rendering: instanced voxel meshes for countryside
tiles (grass/farm/tree/water/mountain), composited under the existing 2D
sprite city. See docs/superpowers/specs/2026-08-05-realtime-3d-terrain-
phase1-design.md.

This module is imported by main.py only; it does not import ui.iso_city, to
avoid a circular import (same discipline as ui.voxel_terrain).
"""
from pathlib import Path

import numpy as np

TW, TH = 16, 8  # MUST match ui.iso_city.TW/TH

MATERIALS = ("grass", "farm", "tree", "water", "mountain")

MESH_DIR = Path(__file__).resolve().parents[1] / "assets" / "terrain3d"


def build_instances(tiles):
    """Pure tile-dict -> per-material instance offsets. No GL calls.

    `tiles` is shaped like IsoCity.tiles: {(col, row): (kind, extra)}. Tiles
    whose kind isn't one of MATERIALS (roads, buildings, parks, etc. -- still
    2D-sprite-rendered in Phase 1) are skipped. Each terrain tile becomes one
    (col, 0, row) world-space offset; y=0 for all materials in Phase 1
    (mountain height/elevation is a Phase 4 polish item, not consumed here
    yet even though the tile payload carries it)."""
    buckets = {material: [] for material in MATERIALS}
    for (col, row), (kind, _extra) in tiles.items():
        if kind in buckets:
            buckets[kind].append((float(col), 0.0, float(row)))
    return {
        material: np.array(offsets, dtype="f4").reshape(-1, 3)
        for material, offsets in buckets.items()
        if offsets
    }
