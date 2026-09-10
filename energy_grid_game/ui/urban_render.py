"""Drawing helpers for baked urban blocks and roads."""
from __future__ import annotations

import random

import pygame

from ui import assets
from ui.urban_blocks import UrbanBlock, UrbanRoad

TW, TH = 16, 8
ASPHALT = (50, 55, 58)
ASPHALT_LIT = (64, 68, 72)
PAVEMENT = (92, 92, 88)
PAVEMENT_DARK = (64, 66, 68)
LOT = (57, 58, 62)
LINE = (188, 188, 160)
TREE = (56, 100, 62)


def _shade(c: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(v * f))) for v in c)


def _diamond(x: int, y: int, w: int = 4, d: int = 4) -> list[tuple[int, int]]:
    return [
        (x, y),
        (x + w * TW // 2, y + w * TH // 2),
        (x + (w - d) * TW // 2, y + (w + d) * TH // 2),
        (x - d * TW // 2, y + d * TH // 2),
    ]


def draw_urban_road(surface: pygame.Surface, x: int, y: int,
                    road: UrbanRoad, night: bool = False) -> None:
    color = ASPHALT_LIT if road.avenue else ASPHALT
    if night:
        color = _shade(color, 0.34)
    pygame.draw.polygon(surface, color, _diamond(x, y, 4, 4))
    line = _shade(LINE, 0.45) if night else LINE
    if road.role == "cross":
        pygame.draw.line(surface, line, (x - 24, y + 14), (x + 24, y + 38), 1)
        pygame.draw.line(surface, line, (x + 24, y + 14), (x - 24, y + 38), 1)
    elif road.role == "straight_ne":
        pygame.draw.line(surface, line, (x - 22, y + 22), (x + 22, y + 44), 1)
    else:
        pygame.draw.line(surface, line, (x + 22, y + 22), (x - 22, y + 44), 1)


def _blit_building(surface: pygame.Surface, tier: str, x: int, y: int,
                   rng: random.Random, night: bool = False) -> pygame.Rect:
    entries = assets.iso_building_entries(tier)
    entry = entries[rng.randrange(len(entries))]
    sprite = assets.iso_sprite(entry["file"])
    if night:
        sprite = sprite.copy()
        sprite.fill((42, 46, 68, 255), None, pygame.BLEND_RGB_MULT)
    base = entry.get("base", [sprite.get_width() // 2, sprite.get_height() - 2])
    pos = (round(x - base[0]), round(y + TH - base[1]))
    surface.blit(sprite, pos)
    return pygame.Rect(pos, sprite.get_size())


def draw_urban_block(surface: pygame.Surface, x: int, y: int,
                     block: UrbanBlock, rng: random.Random,
                     night: bool = False) -> list[pygame.Rect]:
    base_color = LOT if block.district in ("industrial", "utility") else PAVEMENT
    if night:
        base_color = _shade(base_color, 0.34)
    pygame.draw.polygon(surface, base_color, _diamond(x, y, 4, 4))
    edge_color = _shade(PAVEMENT_DARK, 0.45) if night else PAVEMENT_DARK
    pygame.draw.lines(surface, edge_color, True, _diamond(x, y, 4, 4), 1)
    rects: list[pygame.Rect] = []
    offsets = [(-12, 10), (10, 16), (0, 30), (-24, 24)]
    for index, tier in enumerate(block.buildings[:4]):
        dx, dy = offsets[index]
        rects.append(_blit_building(surface, tier, x + dx, y + dy, rng, night))
    if block.archetype == "civic":
        tree = _shade(TREE, 0.34) if night else TREE
        pygame.draw.circle(surface, tree, (x - 20, y + 30), 4)
        pygame.draw.circle(surface, tree, (x + 18, y + 26), 3)
    elif block.district in ("mixed", "core") and block.variant % 3 == 0:
        pygame.draw.rect(surface, _shade((42, 44, 48), 0.45) if night else (42, 44, 48),
                         (x + 16, y + 30, 12, 6))
        pygame.draw.line(surface, _shade((210, 198, 116), 0.45) if night else (210, 198, 116),
                         (x + 17, y + 33),
                         (x + 26, y + 33))
    return rects


def draw_municipal_civic(surface: pygame.Surface, x: int, y: int,
                         role: str, rng: random.Random,
                         night: bool = False) -> pygame.Rect:
    entries = assets.iso_municipal_entries(role)
    entry = entries[rng.randrange(len(entries))]
    sprite = assets.iso_sprite(entry["file"])
    if night:
        sprite = sprite.copy()
        sprite.fill((42, 46, 68, 255), None, pygame.BLEND_RGB_MULT)
    base = entry.get("base", [sprite.get_width() // 2, sprite.get_height() - 2])
    pos = (round(x - base[0]), round(y + TH - base[1]))
    surface.blit(sprite, pos)
    return pygame.Rect(pos, sprite.get_size())


def draw_utility_campus_base(surface: pygame.Surface, x: int, y: int,
                             radius: int, night: bool = False) -> pygame.Rect:
    w = max(5, radius * 3)
    d = max(5, radius * 3)
    poly = _diamond(x, y, w, d)
    pygame.draw.polygon(surface, _shade(LOT, 0.34) if night else LOT, poly)
    pygame.draw.lines(surface, _shade((104, 108, 112), 0.45) if night else (104, 108, 112),
                      True, poly, 2)
    bounds = pygame.Rect(poly[0], (1, 1))
    for point in poly[1:]:
        bounds.union_ip(pygame.Rect(point, (1, 1)))
    return bounds
