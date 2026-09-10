"""Loader for the sliced voxel sprite library (assets/voxel/).

Static sprites only (animation deferred). Sprites are cached and convert_alpha'd
on first use, so a pygame display must exist before calling `sprite`.
"""
import json
from pathlib import Path

import pygame

_DIR = Path(__file__).resolve().parents[1] / "assets" / "voxel"
_manifest = None
_cache = {}

# game plant key -> generation slug (wind keeps its procedural turbine: no asset)
GEN_FOR_PLANT = {
    "nuclear": "nuclear", "hydro": "tidal", "solar": "solar",
    "coal": "thermal", "gas": "cogeneration", "peaker": "geothermal",
    "wind": None,
}

# town building slugs, roughly tallest -> smallest (used by the density gradient)
TOWN_SLUGS = ("apartment", "department_store", "mall", "school", "house", "market")


def _man():
    global _manifest
    if _manifest is None:
        _manifest = json.loads((_DIR / "manifest.json").read_text(encoding="utf-8"))
    return _manifest


def has(slug):
    return slug in _man()


def sprite(slug, rot=0):
    """Return the cached Surface for a slug at a rotation (0..3)."""
    key = (slug, rot)
    if key in _cache:
        return _cache[key]
    rots = _man()[slug]["rotations"]
    entry = rots[rot % len(rots)]
    surf = pygame.image.load(str(_DIR / entry["file"])).convert_alpha()
    _cache[key] = surf
    return surf
