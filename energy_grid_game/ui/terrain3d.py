"""Real-time 3D terrain rendering: instanced voxel meshes for countryside
tiles (grass/farm/tree/water/mountain), composited under the existing 2D
sprite city. See docs/superpowers/specs/2026-08-05-realtime-3d-terrain-
phase1-design.md.

This module is imported by main.py only; it does not import ui.iso_city, to
avoid a circular import (same discipline as ui.voxel_terrain).

Per-frame cost note: draw() renders to an offscreen FBO, and the
read_rgba() + to_surface() pair that follows each draw() performs a
synchronous GPU->CPU framebuffer readback (fbo.read()) every frame, measured
at roughly 2-3ms on typical hardware. This blocks the CPU until the GPU
finishes rendering that frame's terrain -- there is no batching, double
buffering, or async (PBO-backed) readback in Phase 1. This is a known,
accepted tradeoff for now; a future phase could hide the stall by reading
back a frame late (double-buffered FBOs) or avoiding the CPU round-trip
entirely by compositing on the GPU instead of blitting into a pygame
Surface.
"""
import os
import json
from pathlib import Path

import numpy as np

from ui import time_of_day
from ui import voxel_terrain
from ui import voxel_city as vc


def is_enabled():
    """Whether the default 3D terrain pipeline is active. Shared by main.py
    (decides whether to create a GL context at all) and ui.iso_city (decides
    whether to skip drawing 2D tiles that now have a 3D equivalent)."""
    value = os.environ.get("GRIDMANAGER_TERRAIN3D")
    if value is None:
        return True
    return value.strip().lower() not in ("0", "false", "no", "off")


def covers_tile_kind(kind):
    return kind in (
        "grass", "farm", "tree", "water", "mountain", "road",
        "vroad",
    )


def lighting_for_state(state):
    """Derive conservative 3D lighting controls from sim time and weather."""
    day = time_of_day.daylight(getattr(state, "sim_hour", 12.0))
    date = getattr(state, "date", None)
    season = (
        voxel_terrain.season_of(date.month)
        if date is not None and getattr(date, "month", None) is not None
        else "summer"
    )
    event = getattr(state, "active_event", None)
    event_kind = getattr(event, "kind", None)

    ambient = 0.34 + 0.30 * day
    night_tint = np.array((0.58, 0.66, 0.84), dtype="f4")
    daylight_tint = np.array((1.0, 1.0, 1.0), dtype="f4")
    tint = night_tint + (daylight_tint - night_tint) * day
    if season == "winter":
        tint *= np.array((0.95, 0.98, 1.0), dtype="f4")

    snow_mix = 0.10 if season == "winter" else 0.0
    wet_mix = 0.0
    ice_mix = 0.0
    if event_kind == "RAIN":
        wet_mix = 0.32
    if event_kind == "SNOW":
        snow_mix = max(snow_mix, 0.34)
        wet_mix = 0.10
    elif event_kind == "ICE_STORM":
        snow_mix = max(snow_mix, 0.24)
        wet_mix = 0.22
        ice_mix = 0.30

    return {
        "ambient": float(max(0.0, min(1.0, ambient))),
        "light_tint": tuple(float(max(0.0, min(1.0, c))) for c in tint),
        "snow_mix": float(max(0.0, min(1.0, snow_mix))),
        "wet_mix": float(max(0.0, min(1.0, wet_mix))),
        "ice_mix": float(max(0.0, min(1.0, ice_mix))),
    }


TW, TH = 16, 8  # MUST match ui.iso_city.TW/TH

MATERIALS = ("grass", "farm", "tree", "water", "mountain")
ROAD_MATERIALS = ("straight", "corner", "tee", "cross")
BUILDING_MATERIALS = ("house", "shop", "block", "midrise", "tower")
WEATHER_TERRAIN = 0
WEATHER_ROAD = 1
WEATHER_BUILDING = 2
WEATHER_BILLBOARD = 3
WEATHER_METAL = 4
DOWNTOWN_BUILDING_MATERIALS = (
    "downtown_house_a", "downtown_house_b",
    "downtown_market_a", "downtown_school_a",
    "downtown_mall_a", "downtown_department_a",
    "downtown_apartment_a", "downtown_apartment_b",
    "downtown_office_a", "downtown_office_b", "downtown_office_c",
)
DOWNTOWN_BUILDING_MATERIAL_FOR_SLUG = {
    "house": ("downtown_house_a", "downtown_house_b"),
    "market": ("downtown_market_a",),
    "school": ("downtown_school_a",),
    "mall": ("downtown_mall_a",),
    "department_store": ("downtown_department_a",),
    "apartment": ("downtown_apartment_a", "downtown_apartment_b"),
    "building_2": ("downtown_office_a", "downtown_department_a"),
    "building_3": ("downtown_office_b", "downtown_mall_a"),
    "building_4": ("downtown_office_c", "downtown_apartment_b"),
    "building_5": ("downtown_office_a", "downtown_office_b"),
}

# Derived by rotating each baked mesh's default (yaw=0) open "arms" -- read
# from its .npz `pos` bounding box -- against the neighbor directions
# ui.road_network.assign_roles's docstring assigns to each role, using this
# module's own position formula (x = -row*TILE_SPACING, z = col*TILE_SPACING,
# so up/row-1 -> +X, down/row+1 -> -X, left/col-1 -> -Z, right/col+1 -> +Z)
# and the shader's yaw rotation. The shader builds `mat3(c,0,-s, 0,1,0, s,0,c)`
# from GLSL's *column-major* constructor argument order, which works out to
# the matrix [[c,0,s],[0,1,0],[-s,0,c]] -- i.e. new_x = x*cos(yaw) + z*sin(yaw),
# new_z = -x*sin(yaw) + z*cos(yaw). (An earlier fix pass used the transposed
# form new_x = x*cos - z*sin, new_z = x*sin + z*cos, which is rotation by
# -yaw instead of +yaw; that only happened to be invisible for the other
# roles and silently miscomputed tee_nw. A later independent re-derivation
# caught the transpose and confirmed the values below numerically against
# the baked tee.npz mesh.)
#   straight.npz default arms: +X, -X (the through-axis is X at yaw=0).
#     straight_ne wants up+down (+-X) -> yaw 0. straight_nw wants
#     left+right (+-Z) -> yaw 90 rotates the X arms onto Z.
#   corner.npz default arms: +X, +Z.
#     corner_ne wants up+right (+X,+Z) -> yaw 0 (exact match already).
#     corner_nw wants down+left (-X,-Z) -> yaw 180 (negates both arms).
#   tee.npz default arms: +X, -X, +Z (missing -Z).
#     tee_ne wants up+down+left (+X,-X,-Z) -> yaw 180 turns the missing arm
#     from -Z to +Z... i.e. rotating the {+X,-X,+Z} set by 180 gives
#     {-X,+X,-Z}, which matches. tee_nw wants left+right+down (-Z,+Z,-X) --
#     applying the correct (non-transposed) rotation, yaw 270 rotates
#     {+X,-X,+Z} to {+Z,-Z,-X}, which is an exact match. (yaw 90 gives
#     {-Z,+Z,+X} instead -- it has +X where -X is needed, so it's wrong.)
#   cross.npz is 4-way symmetric, so its yaw is irrelevant; 0 is as good as
#   any other value.
ROAD_ROLE_TO_SHAPE_YAW = {
    "straight_ne": ("straight", 0.0), "straight_nw": ("straight", 90.0),
    "corner_ne": ("corner", 0.0), "corner_nw": ("corner", 180.0),
    "tee_ne": ("tee", 180.0), "tee_nw": ("tee", 270.0),
    "cross": ("cross", 0.0),
}


def downtown_vroad_shape_yaw(col, row):
    if col % vc.BLOCK == 0 and row % vc.BLOCK == 0:
        return "cross", 0.0
    if col % vc.BLOCK == 0:
        return "straight", 0.0
    if row % vc.BLOCK == 0:
        return "straight", 90.0
    return "cross", 0.0

# Baked ground meshes (energy_grid_game/assets/terrain3d/*.npz) each span
# -1.6..+1.6 on X and Z -- a 3.2-unit footprint -- so instances must be
# spaced 3.2 world units apart per tile to avoid overlapping their
# neighbors. tree.npz is a smaller decoration-prop mesh with no separate
# ground plane (a deliberate Phase 1 simplification) and is placed on the
# same grid spacing as everything else.
TILE_SPACING = 3.2

MESH_DIR = Path(__file__).resolve().parents[1] / "assets" / "terrain3d"
KIT_SOURCE_ROOT = Path("newassets") / "terrain" / "gltf"
KIT_ARTIFACT_ROOT = MESH_DIR / "kit"
KIT_MANIFEST = MESH_DIR / "kit_manifest.json"

KIT_SEMANTIC_SOURCES = {
    "terrain.grass.base": "forest/forest-1",
    "terrain.grass.alt": "forest/forest-2",
    "terrain.farm.base": "dirt/dirt-1",
    "terrain.farm.alt": "dirt/dirt-2",
    "terrain.water.base": "water/water-1",
    "terrain.water.alt": "water/water-2",
    "terrain.mountain.base": "mountains/mountain-1",
    "terrain.mountain.cave": "mountains/mountain-cave",
    "terrain.desert.base": "desert/desert-1",
    "terrain.city.base": "city/city-1",
    "road.straight": "roads/road-straight-1",
    "road.corner": "roads/road-edgy-curve-1",
    "road.tee": "roads/road-edgy-3-way-crossing-1",
    "road.cross": "roads/road-edgy-4-way-crossing-1",
    "track.straight": "tracks/track-straight",
    "track.curve": "tracks/track-curve",
    "track.switch": "tracks/track-switch-1",
    "track.road_intersection": "tracks/track-road-intersection-1",
    "prop.tree": "trees/tree-1",
    "prop.bush": "bushes/bush-1",
    "prop.stone": "stones/stone-1",
    "prop.cactus": "cactus/cactus-1",
    "prop.wood": "wood/wood-1",
    "prop.bones": "bones/bones-1",
    "city.building": "buildings/city-building",
    "edge.forest_water.side": "forestwater/forest-water-side-1",
    "edge.dirt_water.side": "dirtwater/dirt-water-side-1",
    "edge.desert_water.side": "desertwater/desert-water-side-1",
    "edge.city_water.side": "citywater/city-water-side-1",
}

TERRAIN_VARIANT_SOURCES = {
    "grass": (
        ("grass", KIT_SEMANTIC_SOURCES["terrain.grass.base"]),
        ("grass_2", "forest/forest-2"),
        ("grass_3", "forest/forest-3"),
        ("grass_4", "forest/forest-4"),
        ("grass_water_side", KIT_SEMANTIC_SOURCES["edge.forest_water.side"]),
    ),
    "farm": (
        ("farm", KIT_SEMANTIC_SOURCES["terrain.farm.base"]),
        ("farm_2", "dirt/dirt-2"),
        ("farm_3", "dirt/dirt-3"),
        ("farm_4", "dirt/dirt-4"),
        ("farm_water_side", KIT_SEMANTIC_SOURCES["edge.dirt_water.side"]),
    ),
    "water": (
        ("water", KIT_SEMANTIC_SOURCES["terrain.water.base"]),
        ("water_2", "water/water-2"),
        ("water_3", "water/water-3"),
        ("water_4", "water/water-4"),
    ),
    "mountain": (
        ("mountain", KIT_SEMANTIC_SOURCES["terrain.mountain.base"]),
        ("mountain_side_1", "mountains/mountain-side-1"),
        ("mountain_side_2", "mountains/mountain-side-2"),
        ("mountain_edge_1", "mountains/mountain-edge-inner-1"),
        ("mountain_cave", KIT_SEMANTIC_SOURCES["terrain.mountain.cave"]),
    ),
    "tree": (
        ("tree", KIT_SEMANTIC_SOURCES["prop.tree"]),
        ("tree_2", "trees/tree-2"),
        ("tree_3", "trees/tree-3"),
        ("tree_4", "trees/tree-4"),
    ),
}

ROAD_VARIANT_SOURCES = {
    "straight": (
        ("straight", KIT_SEMANTIC_SOURCES["road.straight"]),
        ("straight_2", "roads/road-straight-2"),
        ("straight_3", "roads/road-straight-3"),
        ("straight_4", "roads/road-straight-4"),
    ),
    "corner": (
        ("corner", KIT_SEMANTIC_SOURCES["road.corner"]),
        ("corner_2", "roads/road-edgy-curve-2"),
        ("corner_3", "roads/road-edgy-curve-3"),
        ("corner_4", "roads/road-edgy-curve-4"),
    ),
    "tee": (
        ("tee", KIT_SEMANTIC_SOURCES["road.tee"]),
        ("tee_2", "roads/road-edgy-3-way-crossing-2"),
        ("tee_3", "roads/road-rounded-3-way-crossing-1"),
        ("tee_4", "roads/road-rounded-3-way-crossing-2"),
    ),
    "cross": (
        ("cross", KIT_SEMANTIC_SOURCES["road.cross"]),
        ("cross_2", "roads/road-edgy-4-way-crossing-2"),
        ("cross_3", "roads/road-rounded-4-way-crossing-1"),
        ("cross_4", "roads/road-rounded-4-way-crossing-2"),
    ),
}

DECORATION_VARIANT_SOURCES = {
    "grass": (
        ("bush_1", "bushes/bush-1"),
        ("bush_2", "bushes/bush-2"),
        ("bush_3", "bushes/bush-3"),
        ("stone_1", "stones/stone-1"),
        ("stone_2", "stones/stone-2"),
    ),
    "farm": (
        ("wood_1", "wood/wood-1"),
        ("wood_2", "wood/wood-2"),
        ("stone_3", "stones/stone-3"),
        ("bones_1", "bones/bones-1"),
        ("cactus_1", "cactus/cactus-1"),
    ),
    "tree": (
        ("bush_1", "bushes/bush-1"),
        ("bush_2", "bushes/bush-2"),
        ("stone_4", "stones/stone-4"),
    ),
    "mountain": (
        ("stone_4", "stones/stone-4"),
        ("stone_5", "stones/stone-5"),
        ("stone_6", "stones/stone-6"),
        ("bones_2", "bones/bones-2"),
    ),
}

KIT_ACTIVE_MESH_SOURCES = {
    name: source
    for variants in (
        tuple(TERRAIN_VARIANT_SOURCES.values())
        + tuple(ROAD_VARIANT_SOURCES.values())
        + tuple(DECORATION_VARIANT_SOURCES.values())
    )
    for name, source in variants
}

TERRAIN_RUNTIME_MESHES = tuple(
    name for variants in TERRAIN_VARIANT_SOURCES.values() for name, _source in variants
)
ROAD_RUNTIME_MESHES = tuple(
    name for variants in ROAD_VARIANT_SOURCES.values() for name, _source in variants
)
DECORATION_RUNTIME_MESHES = tuple(dict(
    (name, source)
    for variants in DECORATION_VARIANT_SOURCES.values()
    for name, source in variants
))
BUILDING_RUNTIME_MESHES = BUILDING_MATERIALS + DOWNTOWN_BUILDING_MATERIALS
RUNTIME_MESH_NAMES = (
    TERRAIN_RUNTIME_MESHES + ROAD_RUNTIME_MESHES
    + DECORATION_RUNTIME_MESHES + BUILDING_RUNTIME_MESHES
)

DOWNTOWN_BUILDING_SPECS = {
    "downtown_house_a": ("house", 0.92, 0.84, (0.92, 1.00, 0.92)),
    "downtown_house_b": ("shop", 0.86, 0.78, (1.02, 0.93, 0.86)),
    "downtown_market_a": ("shop", 1.02, 0.92, (1.05, 0.98, 0.82)),
    "downtown_school_a": ("block", 1.08, 1.00, (0.84, 0.92, 1.06)),
    "downtown_mall_a": ("midrise", 1.18, 1.12, (1.03, 0.93, 0.98)),
    "downtown_department_a": ("midrise", 1.46, 1.06, (0.94, 0.98, 1.06)),
    "downtown_apartment_a": ("midrise", 1.82, 1.00, (0.90, 0.96, 1.08)),
    "downtown_apartment_b": ("midrise", 2.22, 0.94, (1.00, 0.94, 0.88)),
    "downtown_office_a": ("midrise", 1.62, 0.96, (0.82, 0.90, 1.08)),
    "downtown_office_b": ("midrise", 2.10, 0.90, (0.88, 1.00, 1.00)),
    "downtown_office_c": ("midrise", 2.62, 0.84, (1.04, 0.96, 0.90)),
}

_KIT_MANIFEST_CACHE = None


def load_kit_manifest(manifest_path=KIT_MANIFEST):
    global _KIT_MANIFEST_CACHE
    manifest_path = Path(manifest_path)
    if _KIT_MANIFEST_CACHE is not None and manifest_path == KIT_MANIFEST:
        return _KIT_MANIFEST_CACHE
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_root = raw.get("artifact_root", KIT_ARTIFACT_ROOT.as_posix())
    if not Path(artifact_root).is_absolute():
        artifact_root = Path(__file__).resolve().parents[2] / artifact_root
    artifact_root = str(Path(artifact_root))
    assets = {entry["key"]: dict(entry) for entry in raw["assets"]}
    for key, entry in assets.items():
        entry["key"] = key
        entry["_artifact_root"] = artifact_root
    if manifest_path == KIT_MANIFEST:
        _KIT_MANIFEST_CACHE = assets
    return assets


def kit_artifact_path(entry, artifact_root=KIT_ARTIFACT_ROOT):
    root = Path(entry.get("_artifact_root", artifact_root))
    return root / entry["artifact"]


def available_kit_semantics(manifest_path=KIT_MANIFEST):
    manifest = load_kit_manifest(manifest_path)
    return {
        semantic: key
        for semantic, key in KIT_SEMANTIC_SOURCES.items()
        if key in manifest and kit_artifact_path(manifest[key]).exists()
    }


def _load_kit_npz(source_key, manifest=None):
    manifest = manifest or load_kit_manifest()
    return np.load(kit_artifact_path(manifest[source_key])), source_key


def _mesh_arrays(data, y_scale=1.0, xz_scale=1.0, tint=(1.0, 1.0, 1.0)):
    pos = np.array(data["pos"], dtype="f4", copy=True)
    pos[:, 0] *= float(xz_scale)
    pos[:, 1] *= float(y_scale)
    pos[:, 2] *= float(xz_scale)
    tex = np.array(data["tex"], dtype="f4", copy=True)
    tex[:, :, :3] *= np.array(tint, dtype="f4")
    tex = np.clip(tex, 0, 255).astype("u1")
    return pos, data["nrm"], data["uv"], data["idx"], tex


def _legacy_runtime_mesh_spec(mesh_dir, name):
    for kind, variants in TERRAIN_VARIANT_SOURCES.items():
        if any(name == variant_name for variant_name, _source in variants):
            scale = (3.1, 2.5) if kind == "tree" else None
            return mesh_dir / f"{kind}.npz", WEATHER_TERRAIN, scale, None
    for shape, variants in ROAD_VARIANT_SOURCES.items():
        if any(name == variant_name for variant_name, _source in variants):
            return mesh_dir / "roads" / f"{shape}.npz", WEATHER_ROAD, None, None
    if name in DECORATION_RUNTIME_MESHES:
        base = "tree" if name.startswith(("bush_", "cactus_")) else "mountain"
        return mesh_dir / f"{base}.npz", WEATHER_TERRAIN, (3.2, 2.8), None
    if name in BUILDING_MATERIALS:
        return mesh_dir / "buildings" / f"{name}.npz", WEATHER_BUILDING, None, None
    if name in DOWNTOWN_BUILDING_SPECS:
        base, y_scale, xz_scale, tint = DOWNTOWN_BUILDING_SPECS[name]
        return (
            mesh_dir / "buildings" / f"{base}.npz",
            WEATHER_BUILDING,
            (y_scale, xz_scale),
            tint,
        )
    raise KeyError(f"no legacy mesh mapping for runtime mesh {name!r}")


def _tile_hash(col, row, salt=0):
    n = (int(col) * 374761393 + int(row) * 668265263 + int(salt) * 1442695041) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return n & 0xFFFFFFFF


def _neighbor_has_kind(tiles, col, row, wanted):
    for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        if tiles.get((col + dc, row + dr), (None,))[0] == wanted:
            return True
    return False


def _variant_name(variants, col, row, salt=0):
    return variants[_tile_hash(col, row, salt) % len(variants)][0]


def terrain_mesh_name(kind, col, row, tiles):
    if kind == "grass" and _neighbor_has_kind(tiles, col, row, "water"):
        return "grass_water_side"
    if kind == "farm" and _neighbor_has_kind(tiles, col, row, "water"):
        return "farm_water_side"
    return _variant_name(TERRAIN_VARIANT_SOURCES[kind], col, row, 11)


def road_mesh_name(shape, col, row):
    return _variant_name(ROAD_VARIANT_SOURCES[shape], col, row, 23)


def downtown_building_mesh_name(slug, col, row):
    variants = DOWNTOWN_BUILDING_MATERIAL_FOR_SLUG.get(slug)
    if variants is None:
        raise ValueError(f"unrecognized downtown building slug: {slug!r}")
    return variants[_tile_hash(col, row, 37) % len(variants)]


def terrain_height_world(kind, extra, col, row):
    if kind == "water":
        return -0.06
    if kind == "mountain":
        elev_px = float(extra or 0.0)
        return 0.18 + min(1.7, elev_px * 0.045)
    if kind in ("grass", "farm", "tree"):
        coarse = ((_tile_hash(col // 3, row // 3, 41) & 0xFF) / 255.0)
        fine = ((_tile_hash(col, row, 43) & 0xFF) / 255.0)
        return 0.03 + 0.12 * coarse + 0.04 * fine
    return 0.0


def decoration_instance(kind, col, row, base_y):
    variants = DECORATION_VARIANT_SOURCES.get(kind)
    if not variants:
        return None
    chance = {
        "grass": 6,
        "farm": 7,
        "tree": 12,
        "mountain": 3,
    }[kind]
    roll = _tile_hash(col, row, 53) % 100
    if roll >= chance:
        return None
    name = _variant_name(variants, col, row, 59)
    yaw = float((_tile_hash(col, row, 61) % 4) * 90)
    jitter_x = (((_tile_hash(col, row, 67) & 0xFF) / 255.0) - 0.5) * 0.70
    jitter_z = (((_tile_hash(col, row, 71) & 0xFF) / 255.0) - 0.5) * 0.70
    return name, float(base_y) + 0.34, jitter_x, jitter_z, yaw


def build_instances(tiles):
    """Pure tile-dict -> per-material instance offsets. No GL calls.

    `tiles` is shaped like IsoCity.tiles: {(col, row): (kind, extra)}.
    Returns {material: (N,4) float32 array of [x, y, z, yaw_degrees]} --
    every material uses this 4-column format (Phase 2 generalization),
    even terrain materials that never rotate (yaw always 0.0 for them).
    col and row are swapped (col feeds world Z, row feeds world -X) so the
    projected result matches ui.iso_city.iso_xy's (col - row, col + row)
    diamond axes -- see test_build_instances_matches_iso_xy_sign_convention.
    Combined with CAM_ROT/PX_PER_UNIT below (tuned to the same 2:1 ratio and
    absolute scale as iso_xy), the projected screen position is not just
    sign-matched but proportional to iso_xy(col, row) -- see
    test_build_instances_projection_matches_iso_xy_proportionally.

    Phase 2 also buckets `road` tiles (payload is a
    ui.road_network.RoadNetwork/ui.urban_blocks.UrbanRoad instance whose
    `.role` attribute is a role string like "straight_ne", mapped to a
    shape+yaw via ROAD_ROLE_TO_SHAPE_YAW) and `urban_block` tiles (payload is
    a ui.urban_blocks.UrbanBlock whose .buildings[0] is the archetype name,
    e.g. "house") into the ROAD_MATERIALS/BUILDING_MATERIALS buckets
    alongside the terrain ones.

    An unrecognized road role or building archetype raises ValueError rather
    than silently dropping the tile -- a previous silent-skip here is exactly
    what let every real road tile go undrawn undetected (the payload's
    `.role` wasn't even being read). Fully unrecognized top-level `kind`
    values (e.g. "park", "campus", "pad") are still silently skipped, since
    that's established Phase 1 behavior for tile kinds this module simply
    doesn't render.
    """
    buckets = {m: [] for m in RUNTIME_MESH_NAMES}
    for (col, row), (kind, extra) in tiles.items():
        x = -float(row) * TILE_SPACING
        z = float(col) * TILE_SPACING
        if kind in MATERIALS:
            mesh_name = terrain_mesh_name(kind, col, row, tiles)
            y = terrain_height_world(kind, extra, col, row)
            buckets[mesh_name].append((x, y, z, 0.0))
            prop = decoration_instance(kind, col, row, y)
            if prop is not None:
                prop_name, prop_y, jitter_x, jitter_z, prop_yaw = prop
                buckets[prop_name].append((x + jitter_x, prop_y, z + jitter_z, prop_yaw))
        elif kind == "road":
            role = getattr(extra, "role", None)
            if role not in ROAD_ROLE_TO_SHAPE_YAW:
                raise ValueError(f"unrecognized road role: {role!r}")
            shape, yaw = ROAD_ROLE_TO_SHAPE_YAW[role]
            buckets[road_mesh_name(shape, col, row)].append((x, 0.0, z, yaw))
        elif kind == "vroad":
            shape, yaw = downtown_vroad_shape_yaw(col, row)
            buckets[road_mesh_name(shape, col, row)].append((x, 0.0, z, yaw))
        elif kind == "urban_block":
            archetype = extra.buildings[0]
            if archetype not in BUILDING_MATERIALS:
                raise ValueError(f"unrecognized building archetype: {archetype!r}")
            buckets[archetype].append((x, 0.0, z, 0.0))
        elif kind == "voxel_bldg":
            archetype = downtown_building_mesh_name(extra, col, row)
            buckets[archetype].append((x, 0.0, z, 0.0))
    return {
        m: np.array(offsets, dtype="f4").reshape(-1, 4)
        for m, offsets in buckets.items()
        if offsets
    }


import moderngl
import pygame

LIGHT = np.array([-0.35, 0.8, 0.5])
LIGHT = LIGHT / np.linalg.norm(LIGHT)

# Camera tuned to exactly match ui.iso_city.iso_xy's 2:1 diamond projection
# ((col-row)*(TW//2), (col+row)*(TH//2)), NOT the true cube-diagonal
# isometric angle used by tools/bake_gltf_terrain.py's offline sprite bake
# (that tool bakes separate, already-shipped 2D sprite assets and is
# intentionally left alone -- see that file's own camera setup).
#
# Derivation: CAM_ROT = RX(_AX) @ RY(45deg) applied to a world offset
# (X, 0, Z) gives (after expanding the matrix product):
#   cam.x = (X+Z) * sqrt(2)/2
#   cam.y = -(Z-X) * sqrt(2)/2 * sin(_AX)
# build_instances() sets X = -row*TILE_SPACING, Z = col*TILE_SPACING, so
# X+Z = TILE_SPACING*(col-row) and Z-X = TILE_SPACING*(col+row). The vertex
# shader computes sx = cam.x*px_per_unit*zoom and
# screen_y = -cam.y*px_per_unit*zoom, giving:
#   sx        = TILE_SPACING * sqrt(2)/2 * px_per_unit * (col-row)
#   screen_y  = TILE_SPACING * sqrt(2)/2 * px_per_unit * sin(_AX) * (col+row)
# For this to be proportional to iso_xy's ((col-row)*8, (col+row)*4) -- a
# 2:1 ratio between the (col-row) and (col+row) coefficients -- we need
# sin(_AX) = 1/2, i.e. _AX = 30 degrees (not the ~35.264 degree true
# isometric angle). Matching the sx coefficient to iso_xy's absolute scale
# (TW//2 = 8) then pins px_per_unit = TW / (sqrt(2) * TILE_SPACING) (see
# PX_PER_UNIT below), which also makes the screen_y coefficient equal
# TH//2 = 4 exactly. This camera therefore DOES now produce iso_xy's exact
# 2:1 screen ratio and scale; the col/row swap-and-negate in
# build_instances() above additionally aligns the two axes' orientation.
_AY = np.deg2rad(45.0)
_AX = np.deg2rad(30.0)
_RY = np.array([[np.cos(_AY), 0, np.sin(_AY)],
                [0, 1, 0],
                [-np.sin(_AY), 0, np.cos(_AY)]])
_RX = np.array([[1, 0, 0],
                [0, np.cos(_AX), -np.sin(_AX)],
                [0, np.sin(_AX), np.cos(_AX)]])
CAM_ROT = _RX @ _RY

# px_per_unit that makes the camera's projected scale match iso_xy's
# TW//2 = 8 px per (col-row) unit exactly (see derivation above).
PX_PER_UNIT = TW / (2 ** 0.5 * TILE_SPACING)


def camera_basis():
    """World-space basis for a camera-facing billboard, derived once from
    the fixed CAM_ROT. right_world/up_world span the billboard's plane;
    facing_normal points back toward the camera, which lands in the shared
    banded-lighting shader's middle band (~70% brightness) rather than full
    brightness -- billboarded plants will read visibly darker than their 2D
    counterparts until Phase 3b addresses this (e.g. an unlit/full-bright
    shader path for billboards).

    up_world is pinned to world-vertical (0, 1, 0) -- billboards stand
    upright, matching the existing 2D sprites' "flat cutout standing on the
    ground" convention -- rather than the camera's true local "up" axis.
    CAM_ROT tilts the camera down by 30 degrees (see the CAM_ROT derivation
    comment above), so the camera's raw local up/forward directions are NOT
    orthogonal to world-vertical: transforming camera-space (0,0,-1)
    straight into world space via CAM_ROT.T (valid since CAM_ROT is
    orthonormal, so its inverse is its transpose) gives a vector with
    dot(up_world, that) == -sin(30deg) == -0.5, nowhere near the 0 an
    orthonormal basis requires. So this uses the standard cylindrical/
    vertical-billboard construction instead: derive right_world as the
    horizontal axis perpendicular to both world-up and the camera's raw
    view direction (a cross product with world-up is always perpendicular
    to world-up by construction), then re-derive facing_normal as
    cross(right_world, up_world) so all three vectors end up mutually
    orthogonal by construction rather than merely close.  The resulting
    facing_normal is the raw camera direction's horizontal projection --
    it points toward the camera's side of the scene with no vertical
    component, which is the correct "faces the camera" direction for a
    billboard whose up edge must stay world-vertical."""
    inv = CAM_ROT.T
    up_world = np.array([0.0, 1.0, 0.0])
    raw_facing = inv @ np.array([0.0, 0.0, -1.0])
    right_world = np.cross(raw_facing, up_world)
    right_world = right_world / np.linalg.norm(right_world)
    # cross(right_world, up_world) (not up x right) so facing_normal points
    # back toward the camera rather than into the scene -- verified
    # numerically: with CAM_ROT's fixed _AY=45/_AX=30, this yields
    # (-0.7071, 0, 0.7071), matching the horizontal projection of
    # CAM_ROT.T @ (0,0,1) (the true toward-camera direction).
    facing_normal = np.cross(right_world, up_world)
    facing_normal = facing_normal / np.linalg.norm(facing_normal)
    return right_world, up_world, facing_normal


def billboard_quad(width_world, height_world, basis=None):
    """A single camera-facing quad: bottom edge at local y=0 (ground), top
    edge at y=height_world, centered on x=0. `basis` overrides
    camera_basis() for testing; production callers use the default.

    NOTE for whoever adds sprite-pixel-height -> world-unit conversion
    (e.g. a future build_plant_billboards()): unlike right_world, up_world
    is pinned to world-vertical rather than being perpendicular to the
    camera's view direction, so vertical extents get foreshortened by
    cos(_AX) = cos(30deg) ~= 0.866 on screen under this camera's pitch. A
    caller that wants a specific on-screen pixel height should divide the
    world-unit height by that factor before passing it in here."""
    right_world, up_world, facing_normal = (
        basis if basis is not None else camera_basis()
    )
    half_w = width_world / 2.0
    bottom_left = -half_w * right_world
    bottom_right = half_w * right_world
    top_left = bottom_left + height_world * up_world
    top_right = bottom_right + height_world * up_world
    pos = np.array([bottom_left, bottom_right, top_right, top_left], dtype="f4")
    nrm = np.tile(facing_normal.astype("f4"), (4, 1))
    uv = np.array([[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]], dtype="f4")
    idx = np.array([[0, 1, 2], [0, 2, 3]], dtype="i4")
    return pos, nrm, uv, idx


# Correction factor for build_plant_billboards()'s height conversion -- see
# billboard_quad()'s docstring note above: up_world is pinned to
# world-vertical rather than being perpendicular to the camera's view
# direction, so a billboard's vertical extent renders on-screen at only
# cos(30deg) of what its horizontal extent would at the same world-unit
# size. Dividing the height conversion by this factor (in addition to
# PX_PER_UNIT) cancels that foreshortening so the billboard's on-screen
# aspect ratio matches the source sprite's pixel aspect ratio, same as its
# width does.
_VERTICAL_FORESHORTENING = np.cos(_AX)
TRANSMISSION_CONDUCTOR_SCREEN_LIFT_PX = 16.0
TRANSMISSION_CONDUCTOR_HEIGHT_WORLD = (
    TRANSMISSION_CONDUCTOR_SCREEN_LIFT_PX / (PX_PER_UNIT * _VERTICAL_FORESHORTENING)
)


_TOWER_SURFACE = None


def tower_billboard_surface():
    global _TOWER_SURFACE
    if _TOWER_SURFACE is None:
        surf = pygame.Surface((24, 42), pygame.SRCALPHA)
        steel = (126, 132, 142, 255)
        dark = (54, 60, 68, 255)
        x, y, h = 12, 38, 34
        pygame.draw.line(surf, dark, (x - 5, y), (x, y - h), 1)
        pygame.draw.line(surf, dark, (x + 5, y), (x, y - h), 1)
        pygame.draw.line(surf, steel, (x - 3, y), (x, y - h + 1), 1)
        for yy in (y - 7, y - 16, y - 25):
            pygame.draw.line(surf, steel, (x - 8, yy), (x + 8, yy), 1)
            pygame.draw.line(surf, (164, 168, 176, 255), (x - 8, yy), (x - 8, yy + 3), 1)
            pygame.draw.line(surf, (164, 168, 176, 255), (x + 8, yy), (x + 8, yy + 3), 1)
        pygame.draw.line(surf, steel, (x, y - h), (x, y - h - 3), 1)
        _TOWER_SURFACE = surf
    return _TOWER_SURFACE


def build_tower_billboards(towers):
    surface = tower_billboard_surface()
    w, h = surface.get_size()
    return [{
        "key": tower["key"],
        "offset": tower["offset"],
        "width_world": w / PX_PER_UNIT,
        "height_world": h / (PX_PER_UNIT * _VERTICAL_FORESHORTENING),
        "surface": surface,
    } for tower in towers]


def build_plant_billboards(plants):
    """Pure PlantSite-list -> billboard placement data. No GL calls. Uses
    the same (-row*TILE_SPACING, 0, col*TILE_SPACING) world convention as
    build_instances(), NOT the clamped 2D sx/sy IsoCity uses for its own
    on-screen anchor (see Phase 3a design doc's scope note).

    height_world divides by PX_PER_UNIT * _VERTICAL_FORESHORTENING (not
    just PX_PER_UNIT, unlike width_world) to counteract the camera's
    vertical foreshortening described above."""
    billboards = []
    for site in plants:
        w, h = site.sprite.get_size()
        billboards.append({
            "key": site.key,
            "offset": (-float(site.row) * TILE_SPACING, 0.0, float(site.col) * TILE_SPACING),
            "width_world": w / PX_PER_UNIT,
            "height_world": h / (PX_PER_UNIT * _VERTICAL_FORESHORTENING),
            "surface": site.sprite,
        })
    return billboards


def screen_px_to_world(screen_point, origin, y_world=0.0):
    """Convert an IsoCity screen-space point back into terrain3d world X/Y/Z.

    This is the inverse of iso_xy plus build_instances' world convention:
    sx = (col - row) * TW/2 + origin_x
    sy = (col + row) * TH/2 + origin_y
    x = -row * TILE_SPACING
    z = col * TILE_SPACING
    """
    sx = (float(screen_point[0]) - float(origin[0])) / (TW / 2.0)
    sy = (float(screen_point[1]) - float(origin[1])) / (TH / 2.0)
    col = (sx + sy) / 2.0
    row = (sy - sx) / 2.0
    return (-row * TILE_SPACING, float(y_world), col * TILE_SPACING)


def build_transmission_geometry(snapshot, origin):
    towers = []
    conductors = []
    for route in snapshot:
        key = route["key"]
        sub_index = route["substation_index"]
        for point in route["tower_points"]:
            towers.append({
                "key": key,
                "substation_index": sub_index,
                "offset": screen_px_to_world(point, origin),
            })
        for arm, points in route["conductor_paths"].items():
            world_points = tuple(
                screen_px_to_world(
                    (point[0], point[1] + TRANSMISSION_CONDUCTOR_SCREEN_LIFT_PX),
                    origin,
                    y_world=TRANSMISSION_CONDUCTOR_HEIGHT_WORLD,
                )
                for point in points
            )
            if len(world_points) >= 2:
                conductors.append({
                    "key": key,
                    "substation_index": sub_index,
                    "arm": arm,
                    "points": world_points,
                })
    return {"towers": towers, "conductors": conductors}


def conductor_strip_mesh(conductors, width_world=0.16):
    verts = []
    normals = []
    uvs = []
    indices = []
    normal = np.array([0.0, 1.0, 0.0], dtype="f4")
    half = width_world / 2.0
    for conductor in conductors:
        pts = conductor["points"]
        for a, b in zip(pts, pts[1:]):
            a = np.array(a, dtype="f4")
            b = np.array(b, dtype="f4")
            direction = b - a
            length = np.linalg.norm(direction[[0, 2]])
            if length <= 1e-6:
                continue
            side = np.array([-direction[2], 0.0, direction[0]], dtype="f4")
            side = side / max(np.linalg.norm(side), 1e-6) * half
            base = len(verts)
            verts.extend([a - side, a + side, b + side, b - side])
            normals.extend([normal, normal, normal, normal])
            uvs.extend([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
            indices.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])
    if not verts:
        verts = [np.zeros(3, dtype="f4")] * 4
        normals = [normal] * 4
        uvs = [(0.0, 0.0)] * 4
        indices = [(0, 1, 2), (0, 2, 3)]
    tex = np.array([[[116, 122, 132, 255]]], dtype="u1")
    return (np.array(verts, dtype="f4"),
            np.array(normals, dtype="f4"),
            np.array(uvs, dtype="f4"),
            np.array(indices, dtype="i4"),
            tex)


def _has_conductor_segments(conductors):
    for conductor in conductors:
        pts = conductor["points"]
        for a, b in zip(pts, pts[1:]):
            direction = np.array(b, dtype="f4") - np.array(a, dtype="f4")
            if np.linalg.norm(direction[[0, 2]]) > 1e-6:
                return True
    return False


def _surface_to_rgba_array(surface):
    """Shared pygame-Surface -> (h, w, 4) uint8 RGBA array conversion, used
    by both create_dynamic_texture() (which wraps it in a moderngl.Texture)
    and load_billboards() (which needs the raw array for GLMesh.__init__)."""
    w, h = surface.get_size()
    data = pygame.image.tostring(surface.convert_alpha(), "RGBA", False)
    return np.frombuffer(data, dtype="u1").reshape(h, w, 4)


def create_dynamic_texture(ctx, surface):
    """Runtime GL texture from a pygame Surface (plant sprites are drawn
    procedurally at bake time, not baked offline like terrain/road/building
    meshes -- there is no .npz for these)."""
    array = _surface_to_rgba_array(surface)
    h, w = array.shape[0], array.shape[1]
    tex = ctx.texture((w, h), 4, array.tobytes())
    tex.filter = moderngl.NEAREST, moderngl.NEAREST
    return tex

_VERTEX_SHADER = """
#version 330
uniform mat3 cam_rot;
uniform float px_per_unit;
uniform float zoom;
uniform vec2 img_size;
uniform vec2 origin;
in vec3 in_pos;
in vec3 in_normal;
in vec2 in_uv;
in vec3 in_offset;
in float in_yaw;
out vec2 v_uv;
out vec3 v_normal;
void main() {
    float rad = radians(in_yaw);
    float c = cos(rad);
    float s = sin(rad);
    mat3 yaw_rot = mat3(c, 0.0, -s,
                         0.0, 1.0, 0.0,
                         s, 0.0, c);
    vec3 local = yaw_rot * in_pos;
    vec3 normal = yaw_rot * in_normal;
    vec3 world = local + in_offset;
    vec3 cam = cam_rot * world;
    float sx = cam.x * px_per_unit * zoom;
    float sy = -cam.y * px_per_unit * zoom;
    float depth = -cam.y + 0.35 * cam.z;
    vec2 screen_px = vec2(sx, sy) - origin;
    float ndc_x = screen_px.x / img_size.x * 2.0 - 1.0;
    // Inverted (vs. the "1.0 - ..." convention) on purpose: FBO reads are
    // bottom-up, so flipping the sign here bakes that correction into the
    // projection instead of paying for a per-frame CPU
    // pygame.transform.flip() in to_surface() below.
    float ndc_y = screen_px.y / img_size.y * 2.0 - 1.0;
    gl_Position = vec4(ndc_x, ndc_y, -depth * 0.01, 1.0);
    v_uv = in_uv;
    v_normal = normal;
}
"""

# Lighting is quantized into 3 discrete bands (not a smooth Lambert term) --
# this is what gives the flat/voxel look the design calls for, deliberately
# different from tools/bake_gltf_terrain.py's smooth-shaded sprite bake.
_FRAGMENT_SHADER = """
#version 330
uniform sampler2D tex;
uniform vec3 light_dir;
uniform float ambient;
uniform vec3 light_tint;
uniform float snow_mix;
uniform float wet_mix;
uniform float ice_mix;
uniform bool unlit;
uniform int weather_role;
in vec2 v_uv;
in vec3 v_normal;
out vec4 f_color;
void main() {
    vec4 texel = texture(tex, v_uv);
    if (texel.a < 0.01) discard;
    float bright = 1.0;
    if (!unlit) {
        vec3 n = normalize(v_normal);
        float lambert = max(dot(n, light_dir), 0.0);
        float banded = floor(lambert * 3.0) / 3.0;
        bright = ambient + (1.0 - ambient) * banded;
    }
    float role_snow_mix = snow_mix;
    if (weather_role == 1) {
        role_snow_mix *= 0.45;
    } else if (weather_role == 3) {
        role_snow_mix *= 0.35;
    } else if (weather_role == 4) {
        role_snow_mix *= 0.60;
    }
    vec3 snow = vec3(0.88, 0.93, 0.98);
    vec3 rgb = mix(texel.rgb, snow, clamp(role_snow_mix, 0.0, 1.0));
    if (weather_role == 1 || weather_role == 4) {
        float gray = dot(rgb, vec3(0.299, 0.587, 0.114));
        vec3 wet_rgb = mix(rgb, vec3(gray), 0.55) * 0.72;
        rgb = mix(rgb, wet_rgb, clamp(wet_mix, 0.0, 1.0));
    }
    if (weather_role == 1 || weather_role == 2 || weather_role == 4) {
        vec3 ice_rgb = vec3(0.76, 0.86, 0.96);
        rgb = mix(rgb, ice_rgb, clamp(ice_mix, 0.0, 1.0) * 0.35);
    }
    f_color = vec4(clamp(rgb * bright * light_tint, 0.0, 1.0), texel.a);
}
"""


def create_program(ctx):
    return ctx.program(vertex_shader=_VERTEX_SHADER, fragment_shader=_FRAGMENT_SHADER)


class GLMesh:
    def __init__(self, ctx, prog, pos, nrm, uv, idx, tex, unlit=False,
                 weather_role=WEATHER_TERRAIN, source_key=None):
        self.prog = prog
        self.unlit = bool(unlit)
        self.weather_role = int(weather_role)
        self.source_key = source_key
        verts = np.hstack([pos, nrm, uv]).astype("f4")
        self.vbo = ctx.buffer(verts.tobytes())
        self.ibo = ctx.buffer(idx.astype("i4").tobytes())
        self.instance_vbo = ctx.buffer(reserve=16)  # 1 instance (x,y,z,yaw) placeholder
        self.vao = ctx.vertex_array(
            prog,
            [(self.vbo, "3f 3f 2f", "in_pos", "in_normal", "in_uv"),
             (self.instance_vbo, "3f 1f/i", "in_offset", "in_yaw")],
            self.ibo,
        )
        tex_h, tex_w = tex.shape[0], tex.shape[1]
        self.texture = ctx.texture((tex_w, tex_h), 4, tex.astype("u1").tobytes())
        self.texture.filter = moderngl.NEAREST, moderngl.NEAREST
        self.instance_count = 0

    def set_instances(self, offsets):
        data = offsets.astype("f4").tobytes()
        self.instance_vbo.orphan(max(len(data), 16))
        if len(data):
            self.instance_vbo.write(data)
        self.instance_count = len(offsets)

    def render(self):
        if self.instance_count:
            self.prog["unlit"].value = self.unlit
            self.prog["weather_role"].value = self.weather_role
            self.texture.use(0)
            self.vao.render(instances=self.instance_count)

    def release(self):
        """Release this mesh's GL resources (buffers, VAO, texture). Needed
        by callers (e.g. main.py's per-layout-change billboard rebuild) that
        replace a list of GLMesh instances with a new one -- without this,
        every rebuild leaks a VBO/IBO/instance VBO/VAO/texture set per mesh,
        matching the same "release old before creating new" discipline
        main.py already applies to its terrain3d FBO's attachments."""
        self.vbo.release()
        self.ibo.release()
        self.instance_vbo.release()
        self.vao.release()
        self.texture.release()


def load_meshes(ctx, prog, mesh_dir=MESH_DIR):
    mesh_dir = Path(mesh_dir)
    meshes = {}
    kit_manifest = load_kit_manifest() if mesh_dir == MESH_DIR else None

    if kit_manifest is not None:
        for name, source_key in KIT_ACTIVE_MESH_SOURCES.items():
            data, _source_key = _load_kit_npz(source_key, kit_manifest)
            weather_role = WEATHER_ROAD if name in ROAD_RUNTIME_MESHES else WEATHER_TERRAIN
            if name in DECORATION_RUNTIME_MESHES:
                arrays = _mesh_arrays(data, y_scale=3.2, xz_scale=2.8)
            elif name.startswith("tree"):
                arrays = _mesh_arrays(data, y_scale=3.1, xz_scale=2.5)
            else:
                arrays = (data["pos"], data["nrm"], data["uv"], data["idx"], data["tex"])
            meshes[name] = GLMesh(ctx, prog, *arrays,
                                  weather_role=weather_role,
                                  source_key=_source_key)
        for archetype in BUILDING_MATERIALS:
            data = np.load(mesh_dir / "buildings" / f"{archetype}.npz")
            meshes[archetype] = GLMesh(ctx, prog, data["pos"], data["nrm"],
                                       data["uv"], data["idx"], data["tex"],
                                       weather_role=WEATHER_BUILDING)
        for name, (base, y_scale, xz_scale, tint) in DOWNTOWN_BUILDING_SPECS.items():
            data = np.load(mesh_dir / "buildings" / f"{base}.npz")
            meshes[name] = GLMesh(ctx, prog, *_mesh_arrays(data, y_scale, xz_scale, tint),
                                  weather_role=WEATHER_BUILDING,
                                  source_key=f"legacy-building/{base}")
        return meshes

    for name in RUNTIME_MESH_NAMES:
        mesh_path, weather_role, scale, tint = _legacy_runtime_mesh_spec(mesh_dir, name)
        data = np.load(mesh_path)
        if scale is None and tint is None:
            arrays = (data["pos"], data["nrm"], data["uv"], data["idx"], data["tex"])
        else:
            y_scale, xz_scale = scale or (1.0, 1.0)
            arrays = _mesh_arrays(data, y_scale, xz_scale, tint or (1.0, 1.0, 1.0))
        meshes[name] = GLMesh(ctx, prog, *arrays,
                              weather_role=weather_role,
                              source_key=f"legacy/{mesh_path.as_posix()}")
    return meshes


def load_billboards(ctx, prog, billboards):
    """One GLMesh per plant billboard, each with its own single-quad
    geometry (sized/facing per its `width_world`/`height_world` via
    billboard_quad()) and its own runtime texture (from its `surface`), each
    carrying exactly one instance at the plant's world offset with yaw=0.0
    (billboards are camera-facing by construction, not by per-instance
    rotation)."""
    meshes = []
    for b in billboards:
        pos, nrm, uv, idx = billboard_quad(b["width_world"], b["height_world"])
        tex_data = _surface_to_rgba_array(b["surface"])
        mesh = GLMesh(ctx, prog, pos, nrm, uv, idx, tex_data, unlit=True,
                      weather_role=WEATHER_BILLBOARD)
        mesh.set_instances(np.array([[*b["offset"], 0.0]], dtype="f4"))
        meshes.append(mesh)
    return meshes


def load_transmission(ctx, prog, geometry):
    tower_meshes = load_billboards(ctx, prog, build_tower_billboards(geometry["towers"]))
    pos, nrm, uv, idx, tex = conductor_strip_mesh(geometry["conductors"])
    conductor_mesh = GLMesh(ctx, prog, pos, nrm, uv, idx, tex,
                            weather_role=WEATHER_METAL)
    instances = (np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4")
                 if _has_conductor_segments(geometry["conductors"])
                 else np.zeros((0, 4), dtype="f4"))
    conductor_mesh.set_instances(instances)
    return {"towers": tower_meshes, "conductors": conductor_mesh}


def release_transmission(transmission_meshes):
    if not transmission_meshes:
        return
    for mesh in transmission_meshes.get("towers", []):
        mesh.release()
    conductor = transmission_meshes.get("conductors")
    if conductor is not None:
        conductor.release()


def upload_instances(ctx, meshes, instances):
    empty = np.zeros((0, 4), dtype="f4")
    for material, mesh in meshes.items():
        mesh.set_instances(instances.get(material, empty))


def create_framebuffer(ctx, size):
    size = (max(1, size[0]), max(1, size[1]))
    return ctx.framebuffer(
        color_attachments=[ctx.texture(size, 4)],
        depth_attachment=ctx.depth_renderbuffer(size),
    )


def draw(ctx, prog, meshes, fbo, camera, px_per_unit=PX_PER_UNIT, ambient=0.55,
         light_tint=(1.0, 1.0, 1.0), snow_mix=0.0, wet_mix=0.0, ice_mix=0.0,
         billboard_meshes=None, transmission_meshes=None, world_origin=(0.0, 0.0),
         viewport_center=None):
    """Draws the material meshes, then any billboard_meshes (e.g. from
    load_billboards()) in the SAME pass -- same fbo, same depth state, no
    ctx.clear() between the two groups -- so billboards are properly
    depth-tested against the terrain/road/building geometry rather than
    composited on top of it. `billboard_meshes` defaults to None so existing
    callers that don't pass it behave exactly as before."""
    fbo.use()
    ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
    ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
    ctx.clear(0.10, 0.11, 0.13, 1.0)
    prog["cam_rot"].write(CAM_ROT.T.astype("f4").tobytes())
    prog["px_per_unit"].value = float(px_per_unit)
    prog["zoom"].value = float(camera.zoom)
    prog["img_size"].value = (float(fbo.size[0]), float(fbo.size[1]))
    if viewport_center is None:
        viewport_center = (fbo.size[0] / 2.0, fbo.size[1] / 2.0)
    origin = (
        float(camera.center[0]) * float(camera.zoom)
        - float(viewport_center[0])
        - float(world_origin[0]) * float(camera.zoom),
        float(camera.center[1]) * float(camera.zoom)
        - float(viewport_center[1])
        - float(world_origin[1]) * float(camera.zoom),
    )
    prog["origin"].value = origin
    prog["tex"].value = 0
    prog["light_dir"].value = tuple(LIGHT.astype("f4"))
    prog["ambient"].value = float(ambient)
    prog["light_tint"].value = tuple(float(c) for c in light_tint)
    prog["snow_mix"].value = float(snow_mix)
    prog["wet_mix"].value = float(wet_mix)
    prog["ice_mix"].value = float(ice_mix)
    for mesh in meshes.values():
        mesh.render()
    if transmission_meshes:
        conductor = transmission_meshes.get("conductors")
        if conductor is not None:
            conductor.render()
        for mesh in transmission_meshes.get("towers", []):
            mesh.render()
    for mesh in (billboard_meshes or []):
        mesh.render()


def read_rgba(fbo):
    return fbo.read(components=4), fbo.size


def to_surface(rgba_bytes, size):
    """Pure pygame conversion, no GL involved. FBO reads are bottom-up, but
    unlike tools/bake_gltf_terrain.py (which flips via PIL's
    FLIP_TOP_BOTTOM after the fact), the vertical flip here is baked into
    _VERTEX_SHADER's ndc_y sign convention, so no per-frame CPU
    pygame.transform.flip() is needed."""
    return pygame.image.frombuffer(rgba_bytes, size, "RGBA")
