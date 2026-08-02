"""Deterministic city-block layout model for the isometric renderer."""
from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass

import pygame

ROAD_SPACING = 4
AVENUE_SPACING = 12
MAX_URBAN_BLOCKS = 220
MAX_GREEN_TILES = 40
MAX_ROAD_TILES = 3200


@dataclass(frozen=True)
class UrbanBlock:
    col: int
    row: int
    district: str
    archetype: str
    variant: int
    greenery: float
    buildings: tuple[str, ...]


@dataclass(frozen=True)
class UrbanRoad:
    col: int
    row: int
    role: str
    avenue: bool


@dataclass(frozen=True)
class UrbanCampus:
    key: str
    col: float
    row: float
    district: str
    radius: int


@dataclass(frozen=True)
class UrbanLayout:
    blocks: list[UrbanBlock]
    roads: dict[tuple[int, int], UrbanRoad]
    campuses: dict[str, UrbanCampus]
    civic: dict[tuple[int, int], str]
    green_tiles: set[tuple[int, int]]
    buildable_tiles: set[tuple[int, int]]


def _district(e: float, angle: float) -> str:
    if e < 0.22:
        return "core"
    if e < 0.43:
        return "mixed"
    if 1.85 < angle < 2.75:
        return "civic"
    if e > 0.62:
        return "utility"
    if angle < -0.25 or angle > 2.85:
        return "industrial"
    return "mixed"


def _road_role(col: int, row: int) -> str:
    on_col = col % ROAD_SPACING == 0
    on_row = row % ROAD_SPACING == 0
    if on_col and on_row:
        return "cross"
    if on_col:
        return "straight_nw"
    if on_row:
        return "straight_ne"
    return ""


def nearest_road_tile(layout: UrbanLayout, col: float, row: float) -> tuple[int, int]:
    """Return the road tile closest to a fractional city tile coordinate."""
    if not layout.roads:
        return round(col), round(row)
    return min(
        layout.roads,
        key=lambda tile: (
            (tile[0] - col) * (tile[0] - col) + (tile[1] - row) * (tile[1] - row),
            tile[0],
            tile[1],
        ),
    )


def road_path_tiles(layout: UrbanLayout, start: tuple[int, int],
                    end: tuple[int, int]) -> list[tuple[int, int]]:
    """Return a contiguous road-tile path between two road-adjacent anchors."""
    if not layout.roads:
        return [start, end] if start != end else [start]
    if start not in layout.roads:
        start = nearest_road_tile(layout, *start)
    if end not in layout.roads:
        end = nearest_road_tile(layout, *end)
    if start == end:
        return [start]

    roads = set(layout.roads)
    offsets = ((1, 0), (-1, 0), (0, 1), (0, -1))
    queue = deque([start])
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    while queue:
        tile = queue.popleft()
        if tile == end:
            break
        for dc, dr in offsets:
            neighbor = (tile[0] + dc, tile[1] + dr)
            if neighbor in roads and neighbor not in previous:
                previous[neighbor] = tile
                queue.append(neighbor)

    if end not in previous:
        return [start, end]
    path = [end]
    while previous[path[-1]] is not None:
        path.append(previous[path[-1]])
    path.reverse()
    return path


def _campuses(fleet: tuple[str, ...], u_max: float, v_max: float) -> dict[str, UrbanCampus]:
    angles = {
        "nuclear": math.radians(205),
        "coal": math.radians(155),
        "hydro": math.radians(188),
        "wind": math.radians(112),
        "solar": math.radians(64),
        "peaker": math.radians(24),
        "gas": math.radians(-28),
        "generic": math.radians(24),
    }
    campuses = {}
    for key in fleet:
        angle = angles.get(key, math.radians(24))
        ring = 0.76
        u = u_max * ring * math.cos(angle)
        v = v_max * ring * math.sin(angle)
        campuses[key] = UrbanCampus(
            key=key,
            col=(u + v) / 2.0,
            row=(v - u) / 2.0,
            district="utility",
            radius=3 if key in ("nuclear", "coal", "hydro") else 2,
        )
    return campuses


def _select_balanced_blocks(blocks: list[UrbanBlock], civic: dict[tuple[int, int], str], seed: int,
                            limit: int = MAX_URBAN_BLOCKS) -> list[UrbanBlock]:
    if len(blocks) <= limit:
        return blocks

    selector = random.Random(seed ^ 0xB10C)
    ranked = list(blocks)
    selector.shuffle(ranked)
    selected: list[UrbanBlock] = []
    selected_tiles: set[tuple[int, int]] = set()
    quadrant_counts = {(False, False): 0, (False, True): 0,
                       (True, False): 0, (True, True): 0}
    quadrant_limit = limit // len(quadrant_counts)

    blocks_by_tile = {(block.col, block.row): block for block in blocks}
    for tile in civic:
        block = blocks_by_tile[tile]
        selected.append(block)
        selected_tiles.add(tile)
        quadrant_counts[(block.col >= 0, block.row >= 0)] += 1

    for district in ("core", "mixed", "civic", "industrial", "utility"):
        block = next(
            block for block in ranked
            if block.district == district
            and (block.col, block.row) not in selected_tiles
        )
        selected.append(block)
        selected_tiles.add((block.col, block.row))
        quadrant_counts[(block.col >= 0, block.row >= 0)] += 1

    for block in ranked:
        if len(selected) >= limit:
            break
        tile = (block.col, block.row)
        quadrant = (block.col >= 0, block.row >= 0)
        if tile not in selected_tiles and quadrant_counts[quadrant] < quadrant_limit:
            selected.append(block)
            selected_tiles.add(tile)
            quadrant_counts[quadrant] += 1

    return selected


def _campus_road_tiles(campuses: dict[str, UrbanCampus]) -> set[tuple[int, int]]:
    tiles: set[tuple[int, int]] = set()
    for campus in campuses.values():
        cc, rr = round(campus.col), round(campus.row)
        radius = campus.radius + 1
        for dc in range(-radius, radius + 1):
            tiles.add((cc + dc, rr - radius))
            tiles.add((cc + dc, rr + radius))
        for dr in range(-radius, radius + 1):
            tiles.add((cc - radius, rr + dr))
            tiles.add((cc + radius, rr + dr))
    return tiles


def _trim_roads(
    roads: dict[tuple[int, int], UrbanRoad],
    blocks: list[UrbanBlock],
    green_tiles: set[tuple[int, int]],
    campuses: dict[str, UrbanCampus],
    limit: int = MAX_ROAD_TILES,
) -> dict[tuple[int, int], UrbanRoad]:
    if len(roads) <= limit:
        return roads

    anchors = {(block.col, block.row) for block in blocks} | set(green_tiles)
    keep: set[tuple[int, int]] = set()
    for col, row in anchors:
        for dc in range(-ROAD_SPACING + 1, ROAD_SPACING):
            for dr in range(-ROAD_SPACING + 1, ROAD_SPACING):
                if abs(dc) + abs(dr) <= ROAD_SPACING:
                    tile = (col + dc, row + dr)
                    if tile in roads:
                        keep.add(tile)

    keep |= _campus_road_tiles(campuses) & set(roads)
    if len(keep) <= limit:
        return {tile: roads[tile] for tile in sorted(keep)}

    def score(tile: tuple[int, int]) -> tuple[float, int, int]:
        col, row = tile
        avenue_bias = -8 if roads[tile].avenue else 0
        center_bias = abs(col - row) + abs(col + row)
        return (center_bias + avenue_bias, col, row)

    selected = set(sorted(keep, key=score)[:limit])
    return {tile: roads[tile] for tile in sorted(selected)}


def build_urban_layout(rect: pygame.Rect, fleet: tuple[str, ...], seed: int = 20260801) -> UrbanLayout:
    rng = random.Random(seed)
    u_max = max(24.0, rect.width * 0.92 / 16)
    v_max = max(18.0, rect.height * 0.64 / 8)
    u_lim = u_max * 0.96
    v_lim = v_max * 0.96
    m = int((u_lim + v_lim) / 2) + 2
    roads: dict[tuple[int, int], UrbanRoad] = {}
    blocks: list[UrbanBlock] = []
    civic: dict[tuple[int, int], str] = {}
    green_tiles: set[tuple[int, int]] = set()
    buildable_tiles: set[tuple[int, int]] = set()
    campuses = _campuses(tuple(fleet), u_max, v_max)

    civic_roles = ("hospital", "police_station", "fire_station", "school", "clinic", "graveyard")
    civic_index = 0

    for col in range(-m, m + 1):
        for row in range(-m, m + 1):
            u, v = col - row, col + row
            if abs(u) > u_lim or abs(v) > v_lim:
                continue
            role = _road_role(col, row)
            if role:
                roads[(col, row)] = UrbanRoad(
                    col=col,
                    row=row,
                    role=role,
                    avenue=(col % AVENUE_SPACING == 0 or row % AVENUE_SPACING == 0),
                )
                continue
            if col % ROAD_SPACING == 1 and row % ROAD_SPACING == 1:
                e = math.hypot(u / u_max, v / v_max)
                if e > 0.92:
                    continue
                angle = math.atan2(v / v_max, u / u_max)
                district = _district(e, angle)
                if district == "utility" and len(green_tiles) < MAX_GREEN_TILES and rng.random() < 0.16:
                    green_tiles.add((col, row))
                    continue
                count = 1 + (1 if district in ("core", "mixed") else 0) + (1 if rng.random() < 0.35 else 0)
                palette = {
                    "core": ("tower", "midrise", "shop"),
                    "mixed": ("midrise", "block", "shop", "house"),
                    "civic": ("shop", "midrise"),
                    "industrial": ("block", "shop"),
                    "utility": ("block", "shop"),
                }[district]
                buildings = tuple(palette[(rng.randrange(len(palette)) + i) % len(palette)] for i in range(count))
                archetype = "paved" if district in ("industrial", "utility") else "urban"
                if district == "civic" and civic_index < len(civic_roles):
                    civic[(col, row)] = civic_roles[civic_index]
                    civic_index += 1
                    archetype = "civic"
                blocks.append(UrbanBlock(col, row, district, archetype, rng.randrange(10_000), 0.08, buildings))

    blocks = _select_balanced_blocks(blocks, civic, seed, MAX_URBAN_BLOCKS)
    buildable_tiles = {(block.col, block.row) for block in blocks}
    civic = {tile: role for tile, role in civic.items() if tile in buildable_tiles}
    green_tiles = set(sorted(green_tiles)[:MAX_GREEN_TILES])

    for campus in campuses.values():
        cc, rr = round(campus.col), round(campus.row)
        for dc in range(-campus.radius - 1, campus.radius + 2):
            roads[(cc + dc, rr - campus.radius - 1)] = UrbanRoad(cc + dc, rr - campus.radius - 1, "straight_ne", True)
            roads[(cc + dc, rr + campus.radius + 1)] = UrbanRoad(cc + dc, rr + campus.radius + 1, "straight_ne", True)
        for dr in range(-campus.radius - 1, campus.radius + 2):
            roads[(cc - campus.radius - 1, rr + dr)] = UrbanRoad(cc - campus.radius - 1, rr + dr, "straight_nw", True)
            roads[(cc + campus.radius + 1, rr + dr)] = UrbanRoad(cc + campus.radius + 1, rr + dr, "straight_nw", True)

    roads = _trim_roads(roads, blocks, green_tiles, campuses)

    return UrbanLayout(blocks, roads, campuses, civic, green_tiles, buildable_tiles)
