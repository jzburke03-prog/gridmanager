"""Isometric city view — the primary instrument of the game, replacing the
overhead satellite view from 1.1.

WHY ISO. The satellite renderer was built for an Atlanta-scale metro and could
not be shrunk: its road network was generated independently of its
neighbourhood count, so turning the density knobs down produced a metro-sized
highway web with almost no city on it — broken-looking rather than small.
Career mode starts at a 10,000-person town, so the view has to work at village
scale first and metro scale second. Iso does; the satellite view did not.

POPULATION DRIVES THE LAYOUT. Freeplay uses an illustrative 15,000-person town
so a regional grid does not turn the picture into an unreadable megacity;
career mode can supply its live population directly. Buildings are placed
outward from downtown until their combined residential capacity covers it.

SHAPE FOLLOWS THE VIEWPORT. The city region is short and very wide (~1400x410),
and a circular town projects to a 2:1 diamond that cannot fill it. So the built
area is an ellipse in ISO axis space rather than in tile space:

    u = col - row   (the long screen axis, x = u * TW/2)
    v = col + row   (the short screen axis, y = v * TH/2)

Sizing the u/v half-extents from the rect makes the town fill the viewport at
any aspect, and gives a river-valley elongation for free.

Two inputs drive the lighting, and they are deliberately NOT the same thing
(carried over from 1.1 §1.4 — this part of the model was right):

    activity = how brightly the city burns   (demand curve / time of day)
    served   = how much of it is energised   (supply / demand)

`activity` scales brightness uniformly across the whole city. Night dims every
district at once; it does not shrink the city into its core. `served` is the
one that decides WHO goes dark, and it does so by feeder circuit: a
half-supplied city is patchy, with dark blocks scattered across the whole map
and only a mild bias protecting downtown, because that is what dropping
feeders actually looks like. Multiplying these two into one number is a
modelling error — it leaves outlying districts dead at 04:00 on a perfectly
supplied grid, and a district does not stop existing because it is late.

PERFORMANCE. Detail this fine cannot be redrawn per frame. The static city
(ground, roads, river, trees, buildings, plant structures) is baked once into a
day layer and a night layer, cross-faded by sun angle. Window light is baked
into a small stack of concentric RING layers, so shedding the fringe is a
handful of blits rather than thousands. Only vehicles and plant animation are
per-frame. Rebuilds happen on resize or when the fleet/population changes —
never in the steady state.

All severity animation is slow, smooth, low-contrast easing, capped near 1 Hz
and well under 3 Hz. No hard on/off flashing over large areas: large-area
strobe is a real photosensitive-seizure trigger. Do not "improve" this into
snappier flicker.
"""
import math
import random

import pygame

from ui import assets
from ui.atmosphere import sample_atmosphere
from ui.grid_flow import Flow, LinePulse, ramp_speed_px_s, RAMP_LATENCY_MAX_S, NON_RAMP_SPEED_PX_S
from ui.time_of_day import daylight
from ui.road_network import bootstrap_network, grow_tick, TickResult
from ui.urban_blocks import (_district, build_urban_layout, nearest_road_tile,
                             road_path_tiles)
from ui.urban_render import (draw_municipal_civic, draw_urban_block,
                             draw_urban_road, draw_utility_campus_base)
from ui import voxel_terrain as vt
from ui import voxel_assets as va
from ui import voxel_city as vc
from ui import terrain3d

# Solar/wind ramp_up_latency represents throttle response, not a real
# generation-ramp characteristic -- excluded from the ramp-speed mapping the
# same way CONGESTION_EXCLUDED_KEYS excludes them in game_state.py.
NON_RAMP_SPEED_KEYS = ("solar", "wind")

# ---------------------------------------------------------------------------
# Illumination model. Pure functions, no display needed — test_city_model.py
# pins every one of these.
# ---------------------------------------------------------------------------
AWAKE_MIN = 0.15        # fraction of the city lit at the demand trough, fully supplied
TRAFFIC_MIN = 0.08      # roads are never completely still, even in blackout

# How much of shed order is geography (distance from downtown) versus which
# feeder circuit you happen to sit on. Well under half: outages are mostly
# patchy, with only a thumb on the scale protecting the core. Push this toward
# 1.0 and load-shedding degenerates into a shrinking bullseye, which is not
# what a half-supplied city looks like from the air.
CORE_BIAS = 0.32
FEEDER_SIZE = 5         # tiles per feeder circuit — the grain of an outage patch


def _clamp01(v):
    return max(0.0, min(1.0, v))


def activity_level(demand_level: float, awake_min: float = AWAKE_MIN) -> float:
    """How brightly the city burns, from the demand curve alone. Never zero:
    a city at 04:00 is dim, not dead."""
    return awake_min + (1.0 - awake_min) * _clamp01(demand_level)


def served_fraction(fill_pct: float) -> float:
    """How much of the city the supply can reach. 1.0 once supply meets demand;
    oversupply cannot light more than the whole city."""
    return _clamp01(fill_pct)


def lit_fraction(demand_level: float, fill_pct: float,
                 awake_min: float = AWAKE_MIN) -> float:
    """The share of the city actually illuminated. Kept as a single derived
    number for the tests and the readout; the renderer uses the two inputs
    separately, which is the whole point of the model."""
    return activity_level(demand_level, awake_min) * served_fraction(fill_pct)


def _ramp(value: float, start: float, end: float) -> float:
    return max(0.0, min(1.0, (value - start) / (end - start)))


def voltage_overload_level(ratio: float) -> float:
    return _ramp(ratio, 1.01, 1.50)


def fire_overload_level(ratio: float) -> float:
    return _ramp(ratio, 1.50, 2.00)


def _ignite_rate(fire):
    """New fires per second."""
    return fire * 8.0


def _max_fires(fire):
    return int(round(48 * fire))


def _fire_reach(fire):
    """Fraction of the city that can catch, 0..1, as a share of the
    downtown-first `_buildings` ordering. Starts as a downtown problem and
    spreads outward as things get worse."""
    return fire


def parabolic_peak(hour: float, center: float, half_width: float) -> float:
    distance = abs((hour - center + 12.0) % 24.0 - 12.0)
    x = distance / half_width
    return max(0.0, 1.0 - x * x)


def traffic_level(sim_hour: float, served: float = 1.0,
                  traffic_min: float = TRAFFIC_MIN) -> float:
    """Vehicles on the road, 0..1. A shed grid damps activity (dark signals,
    people staying put) but never kills it."""
    h = sim_hour % 24.0
    daylight_base = max(0.0, math.sin(math.pi * (h - 5.0) / 17.0))
    level = (0.06 + 0.28 * daylight_base
             + 0.62 * parabolic_peak(h, 9.0, 1.5)
             + 0.70 * parabolic_peak(h, 17.0, 1.5))
    return max(traffic_min, min(1.0, level * (0.65 + 0.35 * served)))


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
TW, TH = 16, 8          # iso tile footprint in pixels (2:1, the classic ratio)
ZOOMS = (1, 2, 4)
DEFAULT_ZOOM = 2
REGION_OVERSCAN = 0.04  # small edge safety; 1x should be game, not countryside


def required_world_size(viewport, min_zoom=ZOOMS[0]):
    """Logical region size that covers the minimum zoom plus safe scenery."""
    return (max(500, math.ceil(viewport.width / min_zoom * (1 + REGION_OVERSCAN))),
            max(300, math.ceil(viewport.height / min_zoom * (1 + REGION_OVERSCAN))))


def detail_levels_for_zoom(zoom):
    """Static art layers visible at a supported camera zoom."""
    if zoom not in ZOOMS:
        raise ValueError(f"unsupported zoom: {zoom}")
    levels = ("regional", "gameplay", "inspection")
    return levels[:ZOOMS.index(zoom) + 1]


# Population -> RoadNetwork capacity target tuning (see _layout). Squashes
# the full population range into a target well under road_network.py's
# empirical bootstrap-tick ceiling (~30,637 for master_seed=20260730),
# while keeping the mapping strictly increasing.
POPULATION_CAPACITY_SCALE = 38.0
SAFE_MAX_CAPACITY = 27_000.0  # margin below the empirical ~30,637 bootstrap-tick ceiling


def _road_adjacent_buildable_cells(network, urban):
    """Cells with cardinal road frontage that aren't already occupied --
    the minimal 'has road access' rule from the structure-growth spec,
    without its full lifecycle."""
    result = []
    for (rc, rr) in sorted(network.road_cells):
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cell = (rc + dc, rr + dr)
            if cell in network.occupied or cell in urban.green_tiles:
                continue
            if cell not in result:
                result.append(cell)
                network.occupied.add(cell)
    return result


_ARCHETYPE_PALETTE = {
    "core": ("tower", "midrise", "shop"),
    "mixed": ("midrise", "block", "shop", "house"),
    "civic": ("shop", "midrise"),
    "industrial": ("block", "shop"),
    "utility": ("block", "shop"),
}


def _pick_archetype(district, col, row):
    palette = _ARCHETYPE_PALETTE.get(district, _ARCHETYPE_PALETTE["mixed"])
    index = abs(hash((district, col, row))) % len(palette)
    return palette[index]


def _building_tile(col, row, district, archetype_name):
    from ui.urban_blocks import UrbanBlock
    block_archetype = "paved" if district in ("industrial", "utility") else (
        "civic" if district == "civic" else "urban")
    return UrbanBlock(col=col, row=row, district=district, archetype=block_archetype,
                      variant=abs(hash((col, row))) % 10_000, greenery=0.08,
                      buildings=(archetype_name,))


class Camera:
    """Small world-to-screen transform for the isometric view."""

    def __init__(self, center, zoom=DEFAULT_ZOOM):
        self.center = [float(center[0]), float(center[1])]
        self.zoom = zoom if zoom in ZOOMS else DEFAULT_ZOOM

    def world_to_screen(self, point, viewport):
        return (viewport.centerx + (point[0] - self.center[0]) * self.zoom,
                viewport.centery + (point[1] - self.center[1]) * self.zoom)

    def screen_to_world(self, point, viewport):
        return (self.center[0] + (point[0] - viewport.centerx) / self.zoom,
                self.center[1] + (point[1] - viewport.centery) / self.zoom)

    def visible_world_rect(self, viewport):
        w, h = viewport.width / self.zoom, viewport.height / self.zoom
        return pygame.Rect(round(self.center[0] - w / 2),
                           round(self.center[1] - h / 2), round(w), round(h))

    def clamp(self, viewport, world):
        half_w = viewport.width / self.zoom / 2
        half_h = viewport.height / self.zoom / 2
        if half_w * 2 >= world.width:
            self.center[0] = world.centerx
        else:
            self.center[0] = max(world.left + half_w,
                                 min(world.right - half_w, self.center[0]))
        if half_h * 2 >= world.height:
            self.center[1] = world.centery
        else:
            self.center[1] = max(world.top + half_h,
                                 min(world.bottom - half_h, self.center[1]))

    def set_zoom(self, zoom, anchor, viewport, world):
        if zoom not in ZOOMS or zoom == self.zoom:
            return
        before = self.screen_to_world(anchor, viewport)
        self.zoom = zoom
        after = self.screen_to_world(anchor, viewport)
        self.center[0] += before[0] - after[0]
        self.center[1] += before[1] - after[1]
        self.clamp(viewport, world)

# Freeplay's town is illustrative: changing from a 1 GW grid to a 40 GW region
# must not turn the city into a different-scale object. Keep this modest:
# apparent scale comes from framing and plant placement, not overpopulating the
# renderer with a dense metro that lags when zoomed.
ILLUSTRATIVE_POPULATION = 60_000
PLANT_ART_SCALE = 3


def state_population(state):
    population = getattr(state, "population", None)
    return population if population is not None else ILLUSTRATIVE_POPULATION

# Residents each building sprite stands for. A sprite is a city BLOCK, not a
# single structure — at 16px a tile cannot be one house and still let a metro
# fit on screen. These set the population-to-area relationship, so they are the
# numbers to touch if the city reads too sparse or too dense for its size.
# Only the low tiers set a small town's footprint, and only the tall tiers set
# a metro's, so the spread between them is also what compresses the 43x
# population range into a ~2.5x range of city radius — which is what lets both
# a 10,000-person town and a 430,000-person metro sit in the same viewport
# without one being a speck and the other overflowing it.
CAPACITY = {
    "house": 45,        # suburban block
    "shop": 90,         # mixed-use main street
    "block": 620,       # apartment block
    "midrise": 1800,
    "tower": 5200,
}

RINGS = 8               # light layers; shedding granularity
ROAD_SPACING = 4        # tiles between local streets (blocks are 3x3)
ARTERIAL_SPACING = 12   # every Nth street is an arterial: wider, lamp-lit

# How much of the viewport the largest city may cover. The surrounding land is
# now a narrow readability buffer; 1x should frame the playable city/grid set,
# not a small town floating in open countryside.
MAX_EXTENT = 0.58


def iso_xy(col, row):
    """Tile grid -> screen offset of the tile diamond's top corner."""
    return (col - row) * (TW // 2), (col + row) * (TH // 2)


def street_route(start_tile, end_tile, start_point, end_point, origin):
    """Polyline from equipment to equipment, with its long run on streets."""
    def junction(tile):
        return (round(tile[0] / ROAD_SPACING) * ROAD_SPACING,
                round(tile[1] / ROAD_SPACING) * ROAD_SPACING)

    def screen(tile):
        x, y = iso_xy(*tile)
        return x + origin[0] + TW // 2, y + origin[1] + TH // 2

    start, end = junction(start_tile), junction(end_tile)
    points = [start_point, screen(start), screen((end[0], start[1])),
              screen(end), end_point]
    return [point for i, point in enumerate(points)
            if i == 0 or point != points[i - 1]]


def diamond(cx, cy):
    """Top-face diamond corners for a tile whose top corner is at (cx, cy)."""
    return [(cx + TW // 2, cy), (cx + TW, cy + TH // 2),
            (cx + TW // 2, cy + TH), (cx, cy + TH // 2)]


def shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


# ---------------------------------------------------------------------------
# Palette. Carried over from the satellite view so the game keeps its look:
# low-saturation aerial greens, concrete/asphalt greys, sodium-vapour amber.
# ---------------------------------------------------------------------------
LABEL_DIM = (150, 158, 176)
LABEL_OK = (100, 220, 140)
LABEL_WARN = (240, 170, 80)
LABEL_BAD = (230, 90, 90)

CANOPY_DARK = (34, 74, 34)
CANOPY_MID = (56, 112, 48)
CANOPY_LIGHT = (96, 152, 66)

GRASS = [(104, 150, 74), (112, 158, 80), (96, 140, 66)]
PARK = [(88, 152, 66), (100, 164, 74)]
WATER = [(58, 110, 190), (68, 124, 202), (48, 96, 172)]

# Farmland is drawn as FIELDS, not as noise. Neighbouring tiles share a crop,
# so the countryside reads as a patchwork of cultivated blocks the way it does
# from the air (and in OpenTTD) rather than as olive static.
FIELDS = [
    (108, 158, 56),    # young crop
    (150, 178, 74),    # mature crop
    (198, 178, 98),    # wheat stubble
    (132, 102, 68),    # ploughed earth
    (116, 156, 72),    # pasture
]
FIELD_SIZE = 6         # tiles per field parcel
WOOD_SIZE = 8          # tiles per woodland parcel


def _edge_wobble(th):
    """Radial multiplier that turns the town's bounding ellipse into a lumpy
    outline, as a function of bearing.

    Shared by the layout and by plant siting — that is the whole point of it
    being a function. Plants used to be placed on a fixed circle while the town
    boundary wobbled out past it, so a lobe of the city would swallow whichever
    plant happened to sit on that bearing.
    """
    return (1.0
            + 0.20 * math.sin(2.0 * th + 0.7)
            + 0.15 * math.sin(3.0 * th + 1.1)
            + 0.09 * math.sin(5.0 * th + 2.4)
            + 0.05 * math.sin(9.0 * th))


def _woodland(col, row):
    """Whether a countryside parcel is forest rather than farmland.

    Clustered, not per-tile: scattering trees uniformly over the countryside
    buries the field pattern in noise and reads as green static. Real land is
    stands of woodland between cultivated blocks."""
    return (hash((col // WOOD_SIZE, row // WOOD_SIZE, 0x5EED)) >> 5) % 100 < 10

ROAD_LOCAL = (146, 146, 144)
ROAD_ARTERIAL = (186, 188, 186)


def _road_is_avenue(extra):
    return extra.avenue if hasattr(extra, "avenue") else bool(extra)

# Transmission conductor + junction-marker colours: flat steel, not glowing —
# the delivery chain is legible through accurate shape and scale (tall lattice
# tower vs. short pole vs. a substation yard), not through decorative light.
CONDUCTOR = (94, 100, 110)
JUNCTION = (150, 154, 162)

LIGHT_WARM = (255, 168, 66)
LIGHT_HOT = (255, 232, 186)
LIGHT_OVERLOAD = (255, 72, 44)
FIRE = (255, 138, 48)
SMOKE = (118, 112, 122)

NIGHT_MULT = (42, 46, 68)      # what the unlit city collapses to after dark

# (roof, sunlit wall, shadowed wall). Deliberately varied and fairly saturated:
# a city rendered in nothing but beige and grey reads as a model, not a place.
HOUSE_SETS = [
    ((176, 74, 56), (226, 214, 194), (162, 152, 136)),   # red tile
    ((92, 100, 122), (232, 226, 210), (166, 160, 148)),  # slate
    ((158, 116, 72), (206, 178, 150), (146, 124, 104)),  # terracotta
]
SHOP_SETS = [
    ((110, 104, 98), (214, 190, 146), (150, 132, 102)),  # sandstone
    ((128, 68, 62), (198, 152, 128), (138, 106, 88)),    # brick parade
    ((92, 104, 112), (222, 214, 198), (154, 148, 136)),  # painted render
]
BLOCK_SETS = [
    ((96, 94, 100), (198, 190, 178), (136, 130, 122)),   # concrete
    ((124, 84, 76), (206, 162, 142), (142, 112, 98)),    # brick
    ((84, 100, 110), (188, 196, 200), (128, 134, 138)),  # panel
]
MID_SETS = [
    ((80, 84, 92), (186, 186, 190), (124, 124, 130)),
    ((116, 88, 84), (214, 176, 162), (146, 120, 110)),   # salmon, SC3K's staple
    ((70, 92, 104), (168, 190, 200), (112, 128, 138)),
]
TOWER_SETS = [
    ((66, 72, 84), (166, 178, 198), (106, 116, 134)),    # glass curtain wall
    ((110, 84, 82), (222, 182, 168), (150, 122, 112)),   # salmon high-rise
    ((74, 86, 82), (186, 200, 194), (120, 132, 128)),    # pale green glass
    ((84, 84, 90), (208, 204, 198), (138, 134, 130)),    # white concrete
]

# industrial
STEEL = (124, 134, 156)
STEEL_DARK = (78, 88, 112)
CONCRETE = (168, 166, 160)
CONCRETE_DARK = (112, 110, 106)
PANEL_BLUE = (46, 66, 112)
PANEL_GLINT = (150, 190, 240)
STEAM = (206, 212, 226)


# ---------------------------------------------------------------------------
# Building sprites. Each returns a surface whose base diamond sits flush with
# the bottom edge, so callers blit at (sx, sy + TH - surf.get_height()).
#
# Two surfaces come back from every builder: the structure, and a matching
# "lights" surface holding only the lit windows. Baking them separately is what
# lets the renderer shed the fringe with a handful of blits instead of
# re-rendering the city every time supply moves.
# ---------------------------------------------------------------------------
def _building(rng, h, roof, wl, wd, gable=False, peak=0, windows=0,
              lit_frac=0.0):
    pad = peak + 2
    size = (TW + 1, h + TH + pad + 1)
    surf = pygame.Surface(size, pygame.SRCALPHA)
    lights = pygame.Surface(size, pygame.SRCALPHA)
    base_y = size[1] - TH - 1

    ty = base_y - h
    T, R = (TW // 2, ty), (TW, ty + TH // 2)
    B, L = (TW // 2, ty + TH), (0, ty + TH // 2)
    Rb, Bb, Lb = (TW, base_y + TH // 2), (TW // 2, base_y + TH), (0, base_y + TH // 2)

    pygame.draw.polygon(surf, wd, [L, Lb, Bb, B])      # left wall, shadowed
    pygame.draw.polygon(surf, wl, [B, Bb, Rb, R])      # right wall, sunlit

    if gable:
        a = (TW // 4, ty + TH // 4 - peak)
        b = (TW * 3 // 4, ty + TH * 3 // 4 - peak)
        pygame.draw.polygon(surf, shade(roof, 1.15), [T, R, b, a])
        pygame.draw.polygon(surf, shade(roof, 0.8), [L, B, b, a])
        pygame.draw.polygon(surf, shade(wl, 0.9), [T, L, a])
        pygame.draw.polygon(surf, shade(wd, 0.95), [R, B, b])
    else:
        pygame.draw.polygon(surf, roof, [T, R, B, L])
        pygame.draw.line(surf, shade(roof, 1.3), L, T)   # parapet catch-light

    # Window bays march up each visible wall along the iso slope. 1x2 rather
    # than single pixels so they survive when a big city gets scaled down.
    for i in range(windows):
        floor = 2 + i * 3
        if floor > h - 2:
            break
        for k in (3, 6):
            y = base_y + TH // 2 + k // 2 - floor
            surf.fill(shade(wd, 0.5), (k, y - 1, 1, 2))
            surf.fill(shade(wl, 0.55), (TW - k, y - 1, 1, 2))
            if rng.random() < lit_frac:
                lights.fill(LIGHT_HOT, (k, y - 1, 1, 2))
            if rng.random() < lit_frac:
                lights.fill(LIGHT_WARM, (TW - k, y - 1, 1, 2))
    return surf, lights


def house(rng):
    roof, wl, wd = rng.choice(HOUSE_SETS)
    return _building(rng, rng.randint(4, 6), roof, wl, wd,
                     gable=True, peak=3, windows=1, lit_frac=0.75)


def shop(rng):
    return _building(rng, rng.randint(7, 9), *rng.choice(SHOP_SETS),
                     windows=2, lit_frac=0.8)


def block(rng):
    return _building(rng, rng.randint(11, 15), *rng.choice(BLOCK_SETS),
                     windows=4, lit_frac=0.6)


def midrise(rng):
    return _building(rng, rng.randint(18, 24), *rng.choice(MID_SETS),
                     windows=7, lit_frac=0.5)


def tower(rng):
    return _building(rng, rng.randint(28, 42), *rng.choice(TOWER_SETS),
                     windows=12, lit_frac=0.45)


def _sprite_lights(sprite, rng, tier):
    lights = pygame.Surface(sprite.get_size(), pygame.SRCALPHA)
    bounds = sprite.get_bounding_rect()
    density = {
        "house": 0.22,
        "shop": 0.32,
        "block": 0.45,
        "midrise": 0.52,
        "tower": 0.58,
    }[tier]
    y_start = bounds.top + max(3, bounds.height // 5)
    y_end = bounds.bottom - max(3, bounds.height // 8)
    step_y = 4 if tier in ("house", "shop") else 5
    for y in range(y_start, y_end, step_y):
        for x in range(bounds.left + 3, bounds.right - 2, 5):
            if rng.random() < density and sprite.get_at((x, y)).a > 0:
                color = LIGHT_HOT if rng.random() < 0.35 else LIGHT_WARM
                lights.fill(color, (x, y, 1, 2))
    return lights


def _asset_building(tier, rng):
    entries = assets.iso_building_entries(tier)
    entry = rng.choice(entries)
    sprite = assets.iso_sprite(entry["file"])
    lights = _sprite_lights(sprite, rng, tier)
    return sprite, lights


PROCEDURAL_BUILDERS = {"house": house, "shop": shop, "block": block,
                       "midrise": midrise, "tower": tower}


def _building_builder(tier):
    def build(rng):
        try:
            return _asset_building(tier, rng)
        except (FileNotFoundError, KeyError, ValueError):
            return PROCEDURAL_BUILDERS[tier](rng)
    return build


BUILDERS = {tier: _building_builder(tier) for tier in PROCEDURAL_BUILDERS}


def _density(d):
    """Chance a non-road tile at normalised distance d (0 downtown, 1 edge) is
    developed. Flat across the town, then a hard shoulder at the boundary."""
    return 0.94 if d < 0.8 else 0.94 * max(0.0, 1.0 - d) / 0.2


def _urbanity(population):
    """0 (village) .. 1 (metro), on a log scale because that is how city form
    actually scales — the step from 10k to 50k changes a skyline far more than
    the step from 400k to 440k."""
    return _clamp01((math.log10(max(1000.0, population)) - 3.9) / 1.9)


def _mix(d, population):
    """The building stock at normalised distance d, as (name, share) pairs.

    Tall stock is gated on population as well as position: a 10,000-person town
    has no downtown towers however central the tile — the same scale gate that
    decides when a career player can build a reactor.

    The gates are CONTINUOUS in population rather than banded. Fixed bands made
    density jump at each threshold, and because a denser city needs less land
    for the same people, a 50,000 town could end up covering more ground than a
    130,000 one. Sliding every zone boundary with urbanity keeps city area
    strictly increasing in population, which the view depends on to mean
    anything.

    Both the sampler and the capacity estimator read this one function, so the
    town that gets drawn always houses the population its extent was solved for.
    """
    # These exponents are not free-hand: they were solved for so that city
    # radius is STRICTLY increasing across the whole 4k..430k range (smallest
    # step +0.9%). Retune them and re-check monotonicity, or a growing career
    # town will visibly shrink somewhere in the middle of its run.
    urb = _urbanity(population)
    if d < 0.30 * urb ** 2.2:
        return (("tower", 0.60), ("midrise", 0.40))
    if d < 0.58 * urb ** 1.1:
        return (("midrise", 0.50), ("block", 0.50))
    if d < urb ** 1.25:
        return (("block", 0.50), ("shop", 0.50))
    if d < 0.32 + 0.10 * urb:
        return (("shop", 0.40), ("house", 0.60))
    return (("house", 1.0),)


def _tier(d, population, rng):
    r = rng.random()
    acc = 0.0
    mix = _mix(d, population)
    for name, share in mix:
        acc += share
        if r < acc:
            return name
    return mix[-1][0]


def _expected_capacity(d, population):
    return sum(CAPACITY[name] * share for name, share in _mix(d, population))


def _glow_sprite(radius, peak_alpha, color):
    """Soft halo baked around each lit building.

    Composited into the ring layers with BLEND_RGBA_MAX, never additively: a
    dense downtown stacks hundreds of overlapping halos, and additive
    accumulation saturates the core to flat white within a few blocks, erasing
    the window detail that makes the city readable. MAX keeps the brightest
    contribution, so density still reads without blowing out.
    """
    d = radius * 2 + 1
    s = pygame.Surface((d, d), pygame.SRCALPHA)
    for r in range(radius, 0, -1):
        a = int(peak_alpha * (1.0 - r / radius) ** 2)
        pygame.draw.circle(s, (*color, a), (radius, radius), r)
    return s


GLOW = _glow_sprite(7, 96, (255, 176, 82))
GLOW_TALL = _glow_sprite(12, 118, (255, 196, 122))


def tree(rng):
    """A broadleaf with a lit crown. Bigger and brighter than the satellite
    view's specks — at this zoom a tree is a landmark, not texture."""
    size = (TW + 1, TH + 18)
    surf = pygame.Surface(size, pygame.SRCALPHA)
    base_y = size[1] - TH - 1
    cx = TW // 2
    pygame.draw.line(surf, (68, 50, 34), (cx, base_y + TH // 2), (cx, base_y - 3), 2)
    r = rng.randint(4, 6)
    cy = base_y - 3 - r
    pygame.draw.circle(surf, CANOPY_DARK, (cx, cy), r)
    pygame.draw.circle(surf, CANOPY_MID, (cx + 1, cy - 1), r - 1)
    pygame.draw.circle(surf, CANOPY_LIGHT, (cx + 2, cy - 2), max(1, r - 3))
    return surf, None


# ---------------------------------------------------------------------------
# Power plants.
#
# Every plant splits into a STATIC structure (baked into the base layer) and a
# LIVE part drawn per frame from the source's actual output — steam that thins
# when a boiler is throttled back, blades that speed up in a gust, a spillway
# that runs harder when the dam is opened. The live part is the point: it is
# how the player reads their own dispatch off the landscape instead of off a
# number.
# ---------------------------------------------------------------------------
STACK = (178, 172, 164)     # weathered concrete flue


def _stack(surf, x, base_y, h, w=4, band=True, color=None):
    """A chimney rising from (x, base_y), tapered and round.

    Shaded across its width like the cooling towers rather than filled flat —
    a flue drawn as two rectangles reads as a painted stripe, not a cylinder."""
    base = color or STACK
    top_w = max(2.0, w * 0.62)
    for i in range(h):
        t = i / max(1, h - 1)
        ww = w + (top_w - w) * t
        half = ww / 2.0
        y = base_y - i
        for dx in range(-int(half), int(half) + 1):
            nt = max(-1.0, min(1.0, dx / max(0.5, half)))
            f = 0.42 + 0.66 * max(0.0, math.cos(math.asin(nt) - 0.65))
            surf.set_at((int(x + dx), int(y)), shade(base, min(1.12, f)))
    if band and h > 12:
        for i in range(2):
            y = base_y - h + 3 + i
            pygame.draw.line(surf, (176, 88, 70),
                             (int(x - top_w / 2), y), (int(x + top_w / 2), y))


LOT = (52, 52, 56)          # asphalt pad every plant stands on
LOT_EDGE = (76, 76, 80)
BRICK = (146, 78, 58)
BRICK_DARK = (104, 55, 41)
TANK_WHITE = (204, 202, 196)
GAS_SPHERE = (94, 138, 194)
CAR_COLORS = [(198, 62, 54), (62, 108, 186), (214, 210, 202), (196, 168, 62)]


def _lot(surf, x, y, w, d, color=LOT):
    """The fenced concrete site a plant stands on.

    Every plant needs one. A generating station dropped straight onto grass
    reads as a stray building; the pad is what says 'industrial site', and it
    also visually separates the plant from the farmland it sits in."""
    back = (x, y)
    right = (x + w * TW // 2, y + w * TH // 2)
    front = (x + (w - d) * TW // 2, y + (w + d) * TH // 2)
    left = (x - d * TW // 2, y + d * TH // 2)
    pygame.draw.polygon(surf, color, [back, right, front, left])
    pygame.draw.lines(surf, LOT_EDGE, True, [back, right, front, left])
    return back, right, front, left


def solar_lot_polygon(x, y):
    """The complete 13-by-10-tile solar lot, including its far-left corner."""
    back = (x - 52, y - 34)
    return (back,
            (back[0] + 13 * TW // 2, back[1] + 13 * TH // 2),
            (back[0] + 3 * TW // 2, back[1] + 23 * TH // 2),
            (back[0] - 10 * TW // 2, back[1] + 10 * TH // 2))


def _parking(surf, x, y, n=6):
    """A row of parked cars — pure SC2K, and the cheapest possible cue that
    something industrial is staffed and running."""
    for i in range(n):
        px, py = x + i * 6, y + i * 3
        pygame.draw.rect(surf, (40, 40, 44), (px, py, 5, 3))
        surf.fill(CAR_COLORS[i % len(CAR_COLORS)], (px + 1, py, 3, 2))


def _switchyard(surf, x, y, n=3):
    """Transformer bank and take-off gantry. Every station has one, and it is
    the bit that actually connects the plant to the grid."""
    for i in range(n):
        px, py = x + i * 8, y + i * 4
        pygame.draw.rect(surf, STEEL_DARK, (px, py - 7, 5, 7))
        pygame.draw.rect(surf, STEEL, (px, py - 7, 3, 7))
        pygame.draw.line(surf, (128, 132, 144), (px + 2, py - 7), (px + 2, py - 13))
        pygame.draw.line(surf, (128, 132, 144), (px - 1, py - 12), (px + 6, py - 12))


def _tank(surf, x, base_y, r, h, color=TANK_WHITE):
    """Vertical storage cylinder, shaded round."""
    for dx in range(-r, r + 1):
        nt = max(-1.0, min(1.0, dx / r))
        f = 0.44 + 0.66 * max(0.0, math.cos(math.asin(nt) - 0.65))
        pygame.draw.line(surf, shade(color, min(1.1, f)),
                         (x + dx, base_y - h), (x + dx, base_y))
    pygame.draw.ellipse(surf, shade(color, 1.12),
                        (x - r, base_y - h - max(1, r // 2), r * 2, max(2, r)))


def _sphere(surf, cx, cy, r, color=GAS_SPHERE):
    """Spherical gas holder on legs."""
    for rr in range(r, 0, -1):
        f = 0.42 + 0.72 * (1.0 - rr / r) ** 0.55
        pygame.draw.circle(surf, shade(color, min(1.15, f)),
                           (cx + (r - rr) // 3, cy - (r - rr) // 3), rr)
    for k in (-1, 0, 1):
        pygame.draw.line(surf, STEEL_DARK, (cx + k * r // 2, cy + r - 1),
                         (cx + k * r // 2, cy + r + 3))


def _roof_units(surf, up, n=3):
    """Plant/vent boxes scattered on a shed roof, from _shed's roof corners."""
    back, right, front, left = up
    for i in range(n):
        f = (i + 1) / (n + 1.0)
        px = back[0] + (front[0] - back[0]) * f + (right[0] - back[0]) * 0.42
        py = back[1] + (front[1] - back[1]) * f + (right[1] - back[1]) * 0.42
        pygame.draw.rect(surf, (72, 74, 78), (int(px) - 3, int(py) - 4, 6, 4))
        pygame.draw.rect(surf, (104, 106, 110), (int(px) - 3, int(py) - 4, 6, 2))


def _shed(surf, x, y, w, d, h, light=CONCRETE, dark=CONCRETE_DARK, roof=None):
    """A boxy industrial hall: w x d tiles on the ground, h px tall, with (x, y)
    the BACK corner of its footprint. +1 col moves (+TW/2, +TH/2) on screen,
    +1 row moves (-TW/2, +TH/2), which fixes the four ground corners."""
    roof = roof or shade(light, 0.82)
    back = (x, y)
    right = (x + w * TW // 2, y + w * TH // 2)
    front = (x + (w - d) * TW // 2, y + (w + d) * TH // 2)
    left = (x - d * TW // 2, y + d * TH // 2)
    up = [(px, py - h) for px, py in (back, right, front, left)]
    pygame.draw.polygon(surf, dark, [up[3], up[2], front, left])    # front-left
    pygame.draw.polygon(surf, light, [up[2], up[1], right, front])  # front-right
    pygame.draw.polygon(surf, roof, up)
    return up


def cooling_tower_width(t, rim_ratio=0.82, waist_ratio=0.60):
    """Normalised hyperboloid radius from flared base to open upper rim."""
    t = _clamp01(t)
    waist_at = 0.58
    if t <= waist_at:
        f = math.sin((t / waist_at) * math.pi / 2)
        return 1.0 + (waist_ratio - 1.0) * f
    f = (t - waist_at) / (1.0 - waist_at)
    return waist_ratio + (rim_ratio - waist_ratio) * f ** 1.35


def centered_ellipse_rect(cx, cy, rx, ry):
    half_w = max(1, math.ceil(rx))
    half_h = max(1, math.ceil(ry))
    return pygame.Rect(round(cx) - half_w, round(cy) - half_h,
                       half_w * 2 + 1, half_h * 2 + 1)


def _cooling_tower(surf, x, base_y, h, r):
    """Hyperboloid natural-draught tower — the silhouette that says 'nuclear'.

    Shaded as a SOLID OF REVOLUTION, not filled scanlines. Flat-filling each row
    makes the tower read as a cardboard cut-out; what sells the volume is
    cylindrical shading across the width (dark limb on the shadow side, a bright
    band offset toward the light, a slightly darker terminator at the lit edge)
    plus an elliptical rim you can see down into. Light comes from the right,
    matching the wall shading on every other building.
    """
    light = 0.65        # radians, matching the buildings' sunlit right face

    def profile(t):
        return max(1.5, r * cooling_tower_width(t))

    # Concrete basin and cast shadow seat the shell firmly on the plant pad.
    pygame.draw.ellipse(surf, (42, 46, 50),
                        (int(x - r * 1.3), base_y - 2, int(r * 2.6), max(4, int(r * 0.58))))
    pygame.draw.ellipse(surf, (128, 132, 132),
                        (int(x - r * 1.14), base_y - 4, int(r * 2.28), max(4, int(r * 0.48))))

    center_x = round(x)
    for i in range(h):
        t = i / max(1, h - 1)
        w = profile(t)
        y = base_y - i
        depth = 0.86 + 0.14 * t          # a little aerial lift toward the rim
        for dx in range(-int(w), int(w) + 1):
            nt = max(-1.0, min(1.0, dx / w))
            f = 0.36 + 0.74 * max(0.0, math.cos(math.asin(nt) - light))
            surf.set_at((center_x + dx, int(y)), shade(CONCRETE, min(1.15, f * depth)))

    # rim: outer lip, then the shaft mouth you can see down into
    wt = profile(1.0)
    top = base_y - h
    outer_lip = centered_ellipse_rect(center_x, top, wt * 1.05, wt * 0.42)
    inner_lip = outer_lip.inflate(-2, -2)
    opening = inner_lip.inflate(-max(2, round(wt * 0.48)),
                                 -max(2, round(wt * 0.20)))
    pygame.draw.ellipse(surf, shade(CONCRETE, 0.72),
                        outer_lip)
    pygame.draw.ellipse(surf, shade(CONCRETE, 1.18),
                        inner_lip)
    pygame.draw.ellipse(surf, (48, 52, 58), opening)
    pygame.draw.arc(surf, (220, 220, 216), inner_lip,
                    math.pi, math.tau, 1)

    # A continuous flared skirt reads cleanly at game scale; individual intake
    # legs produced a jagged, detached base.
    wb = profile(0.0)
    pygame.draw.arc(surf, shade(CONCRETE, 0.45),
                    (center_x - int(wb), base_y - max(2, int(wb * 0.22)),
                     int(wb * 2), max(3, int(wb * 0.44))), 0, math.pi, 1)


def solar_panel_layout():
    """Four 3x3 arrays placed on the solar lot's own isometric tile grid."""
    blocks = (((1, 2, 3), (1, 2, 3)), ((8, 9, 10), (1, 2, 3)),
              ((1, 2, 3), (6, 7, 8)), ((8, 9, 10), (6, 7, 8)))
    tables = []
    for group, (cols, rows) in enumerate(blocks):
        for row in rows:
            for col in cols:
                dx, dy = iso_xy(col, row)
                tables.append((group, -52 + dx, -34 + dy))
    return tables


def gas_cc_train_layout():
    """Tile anchors for two complete turbine -> HRSG -> stack trains."""
    return (((1, 1), (5, 1), (8, 2)),
            ((1, 5), (5, 5), (8, 6)))


def _gas_cc_point(x, y, tile):
    dx, dy = iso_xy(*tile)
    return x - 48 + dx, y - 26 + dy


def _plume(layer, x, y, level, t, phase, color, spread, height, puffs=7):
    """Rising exhaust. Density, height and opacity all scale with `level`, so a
    throttled plant visibly stops smoking. Motion is slow and the alpha is low
    — this sits on screen permanently and must never read as flicker."""
    if level <= 0.02:
        return
    for i in range(puffs):
        f = (i / puffs + (t * 0.10 + phase) % 1.0) % 1.0
        rise = f * height * (0.45 + 0.55 * level)
        drift = math.sin(f * 3.0 + phase * 6.3) * spread * f
        r = (1.4 + f * spread * 0.9) * (0.5 + 0.5 * level)
        a = int(150 * level * (1.0 - f) ** 1.3)
        if a < 5 or r < 0.7:
            continue
        s = pygame.Surface((int(r * 2) + 2, int(r * 2) + 2), pygame.SRCALPHA)
        pygame.draw.circle(s, (*color, a), (int(r) + 1, int(r) + 1), int(r))
        layer.blit(s, (x + drift - r, y - rise - r))


def _turbine_blades(layer, x, y, r, angle, color):
    """Three blades at 120 degrees. Drawn per frame over a baked tower."""
    for k in range(3):
        a = angle + k * math.tau / 3.0
        tipx, tipy = x + math.cos(a) * r, y + math.sin(a) * r * 0.92
        pygame.draw.line(layer, color, (x, y), (tipx, tipy), 1)


# Dam geometry, shared by the static wall and the animated spillway so the
# water can never drift off the concrete it is supposed to be running down.
DAM_W, DAM_D, DAM_H = 1, 9, 13


def _dam_face(x, y):
    """The two ends of the dam's downstream (lit) face, at ground level."""
    front = (x + (DAM_W - DAM_D) * TW // 2, y + (DAM_W + DAM_D) * TH // 2)
    right = (x + DAM_W * TW // 2, y + DAM_W * TH // 2)
    return front, right


SWITCHYARD_TAKEOFF = {
    "nuclear": (-24, 21), "coal": (24, 29), "gas": (38, 29),
    "peaker": (-22, 11), "solar": (22, 35), "wind": (48, 5),
    "hydro": (-40, 52), "generic": (-12, 13),
}


class PlantSite:
    """One plant on the map: where it sits, and how to draw its live parts."""

    def __init__(self, key, col, row, sx, sy, phase):
        self.key = key
        self.col, self.row = col, row
        self.sx, self.sy = sx, sy     # screen anchor, relative to the layer
        self.phase = phase
        self.blade_angle = 0.0
        self.switchyard_offset = None

    def switchyard_anchor(self):
        """Decorative line takeoff; intentionally carries no simulation state."""
        if self.switchyard_offset is not None:
            dx, dy = self.switchyard_offset
        else:
            dx, dy = SWITCHYARD_TAKEOFF[self.key]
        return self.sx + dx, self.sy + dy


class TransformerSite:
    __slots__ = ("sub_index", "tile", "point", "priority", "buildings")

    def __init__(self, sub_index, tile, point, priority, buildings):
        self.sub_index = sub_index
        self.tile = tile
        self.point = point
        self.priority = priority
        self.buildings = tuple(buildings)


def _pylon(surf, x, y, h=18):
    """A tall lattice HV transmission tower: splayed legs with a lit inner edge,
    an X-braced body, and three insulated crossarms. Deliberately tall and bold
    — it is the grid's backbone, and the grid is the hero. The top crossarm
    (y - h + 2, half-width 6) is where the double-circuit conductors attach; the
    bake loop uses the same offset, so change them together."""
    # splayed legs (dark) with a lit inner edge for a touch of fidelity
    pygame.draw.line(surf, STEEL_DARK, (x - 4, y), (x, y - h), 1)
    pygame.draw.line(surf, STEEL_DARK, (x + 4, y), (x, y - h), 1)
    pygame.draw.line(surf, STEEL, (x - 3, y), (x, y - h + 1), 1)
    # body cross-bracing, two tiers
    for yy in (y - 3, y - 9):
        pygame.draw.line(surf, shade(STEEL_DARK, 0.9), (x - 3, yy), (x + 3, yy - 5), 1)
        pygame.draw.line(surf, shade(STEEL_DARK, 0.9), (x + 3, yy), (x - 3, yy - 5), 1)
    # three crossarms, widest at the top, insulator drops at the tips
    for cy, half in ((y - h + 2, 6), (y - h + 7, 5), (y - h + 12, 3)):
        pygame.draw.line(surf, STEEL, (x - half, cy), (x + half, cy), 1)
        pygame.draw.line(surf, (162, 166, 176), (x - half, cy), (x - half, cy + 2), 1)
        pygame.draw.line(surf, (162, 166, 176), (x + half, cy), (x + half, cy + 2), 1)
    # mast tip
    pygame.draw.line(surf, STEEL, (x, y - h + 2), (x, y - h - 1), 1)


def _pole(surf, x, y, h=6):
    """A distribution pole: one short post, one crossarm, two insulators.
    Deliberately small and plain next to `_pylon` — the height difference
    between a transmission tower (h=18, three crossarms, splayed lattice legs)
    and this single post is the step-down lesson made visible without a label."""
    pygame.draw.line(surf, STEEL_DARK, (x, y), (x, y - h), 1)
    half = 3
    pygame.draw.line(surf, shade(STEEL_DARK, 0.85), (x - half, y - h + 1),
                     (x + half, y - h + 1), 1)
    pygame.draw.line(surf, (150, 154, 162), (x - half, y - h + 1),
                     (x - half, y - h + 3), 1)
    pygame.draw.line(surf, (150, 154, 162), (x + half, y - h + 1),
                     (x + half, y - h + 3), 1)


def _span(surf, a, b, sag=3):
    """Conductors between two towers. Drawn as a few short chords with a little
    sag rather than one straight line — the catenary droop is most of what makes
    a power line read as a power line."""
    steps = 4
    pts = []
    for i in range(steps + 1):
        f = i / steps
        x = a[0] + (b[0] - a[0]) * f
        y = a[1] + (b[1] - a[1]) * f + math.sin(f * math.pi) * sag
        pts.append((int(x), int(y)))
    pygame.draw.lines(surf, CONDUCTOR, False, pts, 2)


def _substation(surf, x, y):
    """HV -> distribution step-down yard: a fenced lot packed with clustered
    transformer banks, a busbar gantry and a control house. Deliberately the
    biggest piece of grid kit in the countryside — it's the hub every
    transmission corridor lands at, so it has to read as a real substation."""
    _lot(surf, x - 20, y - 10, 4, 4)                             # fenced yard
    # busbar gantry spanning the yard (what the incoming corridor ties into)
    pygame.draw.line(surf, STEEL, (x - 16, y - 4), (x + 10, y - 4), 1)
    for gx in range(x - 16, x + 11, 8):
        pygame.draw.line(surf, STEEL_DARK, (gx, y - 8), (gx, y - 1), 1)
    # clustered transformer banks, two staggered rows
    for r in range(2):
        for c in range(3):
            _switchyard(surf, x - 16 + c * 9, y + 2 + r * 7, 2)
    _shed(surf, x + 12, y + 4, 1, 1, 7, light=CONCRETE, dark=CONCRETE_DARK)  # control house


def _node(surf, x, y, r=3, color=JUNCTION):
    """A small flat junction marker at a connection point — a plain filled
    circle with a dark edge, matching the rest of the kit's flat pixel style.
    Not a glow: the delivery chain reads through shape and scale, not light."""
    pygame.draw.circle(surf, STEEL_DARK, (x, y), r + 1)
    pygame.draw.circle(surf, color, (x, y), r)


def _transformer(surf, x, y, detailed=False):
    pygame.draw.rect(surf, (82, 88, 94), (x - 3, y - 4, 7, 5))
    pygame.draw.rect(surf, (154, 162, 166), (x - 2, y - 6, 5, 3))
    if detailed:
        for dx in (-2, 0, 2):
            pygame.draw.line(surf, (124, 86, 56), (x + dx, y - 6),
                             (x + dx, y - 9), 1)


def _draw_plant_static(surf, key, x, y, rng):
    """Bake a plant's structure. `y` is the base (ground) line."""
    if key == "nuclear":
        _lot(surf, x - 36, y - 20, 10, 7)
        up = _shed(surf, x - 44, y + 4, 3, 3, 11)              # turbine hall
        _roof_units(surf, up, 2)
        # containment: a hemisphere on a cylindrical base, not a flat disc
        cx, cy = x - 22, y - 6
        pygame.draw.rect(surf, shade(CONCRETE, 0.60), (cx - 9, cy - 7, 18, 9))
        pygame.draw.rect(surf, shade(CONCRETE, 0.88), (cx - 9, cy - 7, 9, 9))
        for r in range(9, 0, -1):
            f = 0.42 + 0.70 * (1.0 - r / 9.0) ** 0.5
            pygame.draw.circle(surf, shade(CONCRETE, min(1.1, f)),
                               (cx + (9 - r) // 3, cy - 6), r)
        _cooling_tower(surf, x + 2, y + 14, 29, 14)
        _cooling_tower(surf, x + 28, y + 22, 24, 12)
        _switchyard(surf, x - 40, y + 26, 3)
        _parking(surf, x - 58, y + 20, 4)
    elif key == "coal":
        _lot(surf, x - 52, y - 24, 12, 9)
        # Stockyard and a raised conveyor feeding the boiler house.
        for dx, w, hh in ((-64, 15, 9), (-43, 13, 8)):
            pygame.draw.polygon(surf, (38, 38, 40),
                                [(x + dx - w, y + 15), (x + dx, y + 15 - hh),
                                 (x + dx + w, y + 15)])
            pygame.draw.polygon(surf, (62, 60, 62),
                                [(x + dx, y + 15 - hh), (x + dx + w, y + 15),
                                 (x + dx + w // 2, y + 15)])
        pygame.draw.line(surf, (82, 78, 72), (x - 58, y + 2), (x - 18, y - 8), 3)
        pygame.draw.line(surf, (150, 142, 126), (x - 58, y), (x - 18, y - 10), 1)
        # Separate low turbine hall and taller boiler volume, both grounded.
        _shed(surf, x - 42, y + 10, 4, 2, 9,
              light=(146, 132, 116), dark=(92, 82, 74), roof=(92, 88, 84))
        up = _shed(surf, x - 18, y, 3, 4, 17, light=(142, 146, 150),
                   dark=(82, 88, 96), roof=(92, 98, 104))
        _roof_units(surf, up, 3)
        for f in (0.25, 0.5, 0.75):
            tx = up[1][0] + (up[2][0] - up[1][0]) * f
            ty = up[1][1] + (up[2][1] - up[1][1]) * f
            pygame.draw.line(surf, (72, 78, 84), (int(tx), int(ty)),
                             (int(tx), int(ty + 17)), 1)
        # Connected flue-gas duct and two planted stacks, not detached poles.
        pygame.draw.polygon(surf, (104, 110, 112),
                            [(x + 4, y + 5), (x + 33, y + 19),
                             (x + 33, y + 23), (x + 4, y + 9)])
        _stack(surf, x + 30, y + 22, 42, 6)
        _stack(surf, x + 45, y + 29, 36, 5)
        _switchyard(surf, x + 8, y + 38, 3)
        _parking(surf, x - 42, y + 35, 5)
    elif key == "gas":
        _lot(surf, x - 48, y - 26, 12, 9, color=(54, 58, 62))
        # A pale service aisle separates the two parallel generating trains.
        aisle = _gas_cc_point(x, y, (0, 4))
        _lot(surf, *aisle, 12, 1, color=(86, 90, 92))
        for train, (turbine_tile, recovery_tile, stack_tile) in enumerate(
                gas_cc_train_layout()):
            tx, ty = _gas_cc_point(x, y, turbine_tile)
            hx, hy = _gas_cc_point(x, y, recovery_tile)
            sx, sy = _gas_cc_point(x, y, stack_tile)

            # Long, low gas-turbine enclosure; the blue-gray palette and intake
            # louvres distinguish it from a generic brick warehouse.
            turbine = _shed(surf, tx, ty, 3, 1, 8,
                            light=(142, 154, 160), dark=(66, 80, 90),
                            roof=(92, 106, 114))
            pygame.draw.line(surf, (86, 154, 184),
                             turbine[3], turbine[2], 2)
            for i in range(3):
                px = turbine[3][0] + 5 + i * 5
                py = turbine[3][1] + 3 + i * 2
                pygame.draw.line(surf, (42, 54, 62), (px, py), (px + 4, py + 2), 1)

            # The heat-recovery steam generator is the tall rectangular box
            # immediately downstream, held inside one continuous steel frame.
            recovery = _shed(surf, hx, hy, 2, 2, 16,
                             light=(154, 164, 168), dark=(76, 88, 98),
                             roof=(106, 118, 124))
            ground = [(px, py + 16) for px, py in recovery]
            for top, foot in zip(recovery, ground):
                pygame.draw.line(surf, (176, 184, 188), top, foot, 1)
                pygame.draw.line(surf, (130, 142, 150),
                                 (top[0], top[1] - 4), top, 1)
            pygame.draw.lines(surf, (150, 162, 170), True,
                              [(px, py - 4) for px, py in recovery], 1)
            for i in range(3):
                pygame.draw.line(surf, (96, 108, 116),
                                 (recovery[3][0] + 3 + i * 4,
                                  recovery[3][1] + 4 + i * 2),
                                 (recovery[3][0] + 7 + i * 4,
                                  recovery[3][1] + 6 + i * 2), 1)

            # Exhaust duct makes the energy path legible as a single machine:
            # turbine -> recovery boiler -> its own stack.
            pygame.draw.line(surf, (186, 194, 196),
                             (turbine[1][0] - 3, turbine[1][1] + 2),
                             (recovery[3][0] + 3, recovery[3][1] + 5), 4)
            pygame.draw.line(surf, (104, 116, 122),
                             (recovery[1][0] - 2, recovery[1][1] + 7),
                             (sx, sy - 8), 4)
            _stack(surf, sx, sy, 31 - train * 2, 5)

        # Shared controls/fuel services sit at the front edge, away from the
        # two process trains, while the switchyard has a clear line takeoff.
        controls = _gas_cc_point(x, y, (2, 7))
        _shed(surf, *controls, 2, 1, 6,
              light=(132, 142, 148), dark=(68, 78, 86), roof=(94, 104, 110))
        _tank(surf, x - 88, y + 24, 4, 10)
        _tank(surf, x - 76, y + 30, 4, 10)
        _parking(surf, x - 62, y + 46, 5)
        _switchyard(surf, x + 24, y + 44, 3)
    elif key == "peaker":
        _lot(surf, x - 30, y - 12, 8, 5)
        for i in range(3):                                     # a row of CT units
            _shed(surf, x - 28 + i * 15, y + i * 4, 1, 1, 9,
                  light=STEEL, dark=STEEL_DARK)
            _stack(surf, x - 22 + i * 15, y + i * 4, 15, 4, band=False)
        _tank(surf, x + 20, y + 14, 4, 10)                     # fuel oil backup
        _switchyard(surf, x - 30, y + 20, 2)
    elif key == "solar":
        lot = solar_lot_polygon(x, y)
        back = lot[0]
        pygame.draw.polygon(surf, (92, 102, 78), lot)
        pygame.draw.lines(surf, LOT_EDGE, True, lot)
        # Two genuine isometric gravel strips divide the field into quadrants.
        lot_rect = pygame.Rect(min(px for px, _py in lot), min(py for _px, py in lot),
                               max(px for px, _py in lot) - min(px for px, _py in lot) + 1,
                               max(py for _px, py in lot) - min(py for _px, py in lot) + 1)
        strips = pygame.Surface(lot_rect.size, pygame.SRCALPHA)
        cx, cy = iso_xy(6, 0)
        _lot(strips, back[0] + cx - lot_rect.left, back[1] + cy - lot_rect.top,
             1, 10, color=(156, 148, 118))
        rx, ry = iso_xy(0, 5)
        _lot(strips, back[0] + rx - lot_rect.left, back[1] + ry - lot_rect.top,
             13, 1, color=(150, 144, 116))
        mask = pygame.Surface(lot_rect.size, pygame.SRCALPHA)
        local_lot = [(px - lot_rect.left, py - lot_rect.top) for px, py in lot]
        pygame.draw.polygon(mask, (255, 255, 255, 255), local_lot)
        pygame.draw.lines(mask, (0, 0, 0, 0), True, local_lot, 2)
        strips.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        surf.blit(strips, lot_rect.topleft)
        for _group, dx, dy in solar_panel_layout():
            px, py = x + dx, y + dy
            face = [(px, py), (px + 11, py + 5),
                    (px + 11, py + 9), (px, py + 4)]
            pygame.draw.line(surf, (70, 76, 82), (px + 2, py + 5), (px + 2, py + 8))
            pygame.draw.line(surf, (70, 76, 82), (px + 9, py + 8), (px + 9, py + 11))
            pygame.draw.polygon(surf, (26, 32, 46), face)
            inset = [(px + 1, py + 1), (px + 10, py + 5),
                     (px + 10, py + 7), (px + 1, py + 3)]
            pygame.draw.polygon(surf, PANEL_BLUE, inset)
            pygame.draw.line(surf, shade(PANEL_BLUE, 1.55), inset[0], inset[1])
            pygame.draw.line(surf, shade(PANEL_BLUE, 0.72),
                             (px + 5, py + 3), (px + 5, py + 6))
        ix, iy = iso_xy(11, 4)
        _shed(surf, back[0] + ix, back[1] + iy, 1, 2, 7,
              light=STEEL, dark=STEEL_DARK)                    # inverter house
        _shed(surf, back[0] + ix - 12, back[1] + iy + 8, 1, 1, 5,
              light=CONCRETE, dark=CONCRETE_DARK)              # controls
        _switchyard(surf, back[0] + ix + 10, back[1] + iy + 18, 2)
    elif key == "wind":
        # No pad: turbines stand in working farmland, which is the whole point
        # of onshore wind. Only the substation gets concrete.
        track = []
        for i in range(4):                         # masts only; blades are live
            px = x - 40 + i * 26
            py = y + (i % 2) * 10
            track.append((px, py + 2))
            pygame.draw.ellipse(surf, (82, 88, 82), (px - 4, py - 1, 8, 4))
            pygame.draw.polygon(surf, (174, 180, 188),
                                [(px - 2, py), (px + 2, py),
                                 (px + 1, py - 26), (px, py - 26)])
            pygame.draw.line(surf, (232, 234, 238), (px - 1, py), (px, py - 26), 1)
            pygame.draw.line(surf, (190, 76, 66), (px - 1, py - 19), (px + 1, py - 19), 1)
            pygame.draw.circle(surf, (196, 200, 210), (px, py - 26), 1)
        pygame.draw.lines(surf, (126, 116, 92), False, track, 2)
        for px, py in track:
            pygame.draw.line(surf, (184, 170, 134), (px, py), (px + 8, py + 4), 1)
        _switchyard(surf, x + 40, y + 14, 2)
    elif key == "generic":
        # Instructional Day 1's anonymous "Electricity" source. Deliberately
        # unidentifiable — a plain hall and one flue, with none of the tells
        # (cooling towers, coal pile, flue bank) that would name a technology
        # the lesson has not introduced yet.
        _lot(surf, x - 26, y - 12, 7, 5)
        up = _shed(surf, x - 24, y, 3, 3, 13)
        _roof_units(surf, up, 2)
        _stack(surf, x + 4, y + 2, 26, 5, band=False)
        _switchyard(surf, x - 20, y + 22, 2)
    elif key == "hydro":
        # A dam has to run ACROSS the channel. The river follows constant
        # v = col + row (horizontal on screen), so the wall is laid out long in
        # the row direction — the previous version ran along the current, which
        # read as a concrete ramp beside the water rather than a dam in it.
        # Reservoir lip behind the wall ensures the dam remains legible even
        # when the underlying river is partly hidden by the structure.
        pygame.draw.polygon(surf, (58, 118, 192),
                            [(x - 74, y + 26), (x - 18, y - 2),
                             (x + 10, y + 12), (x - 46, y + 40)])
        _shed(surf, x, y, DAM_W, DAM_D, DAM_H)
        a, b = _dam_face(x, y)
        # crest walkway along the top, and spillway piers down the face
        pygame.draw.line(surf, shade(CONCRETE, 1.12),
                         (a[0], a[1] - DAM_H), (b[0], b[1] - DAM_H))
        for i in range(1, 8):
            f = i / 8.0
            px = a[0] + (b[0] - a[0]) * f
            py = a[1] + (b[1] - a[1]) * f
            pygame.draw.line(surf, shade(CONCRETE, 0.62),
                             (int(px), int(py - DAM_H)), (int(px), int(py)))
        # Gate houses along the crest and penstocks down to a larger powerhouse.
        for i in (2, 5):
            f = i / 8.0
            px = a[0] + (b[0] - a[0]) * f
            py = a[1] + (b[1] - a[1]) * f
            pygame.draw.rect(surf, (128, 134, 138),
                             (int(px - 2), int(py - DAM_H - 4), 5, 4))
        powerhouse = _shed(surf, x - 70, y + 47, 4, 2, 10,
                           light=(154, 162, 166), dark=(88, 96, 104),
                           roof=(104, 112, 118))
        _roof_units(surf, powerhouse, 2)
        for i in range(3):
            pygame.draw.line(surf, (96, 108, 116),
                             (a[0] + 8 + i * 10, a[1] - 4 + i * 5),
                             (x - 47 + i * 7, y + 43 + i * 3), 2)
        _switchyard(surf, x - 48, y + 61, 2)


def _manifest_plant_sprite(key):
    entry = assets.iso_plant_entry(key)
    sprite = assets.iso_sprite(entry["file"])
    if PLANT_ART_SCALE != 1:
        sprite = pygame.transform.scale(
            sprite,
            (sprite.get_width() * PLANT_ART_SCALE,
             sprite.get_height() * PLANT_ART_SCALE),
        )
    base = entry.get("base", [sprite.get_width() // (2 * PLANT_ART_SCALE),
                              sprite.get_height() // PLANT_ART_SCALE - 2])
    base = [int(base[0]) * PLANT_ART_SCALE, int(base[1]) * PLANT_ART_SCALE]
    offset = (-int(base[0]), -int(base[1]))
    switchyard = entry.get("switchyard_anchor")
    if switchyard is not None:
        switchyard = [int(switchyard[0]) * PLANT_ART_SCALE,
                      int(switchyard[1]) * PLANT_ART_SCALE]
    visual = entry.get("visual_center", [
        sprite.get_width() // (2 * PLANT_ART_SCALE),
        sprite.get_height() // (2 * PLANT_ART_SCALE),
    ])
    visual = [int(visual[0]) * PLANT_ART_SCALE,
              int(visual[1]) * PLANT_ART_SCALE]
    return sprite, offset, switchyard, visual


# target on-screen width (px) for the voxel generation sprites, per tech
PLANT_VOXEL_WIDTH = {"nuclear": 176, "hydro": 188, "solar": 156, "coal": 156,
                     "gas": 156, "peaker": 140}

_vbldg_cache = {}


# Downtown office towers baked from City Voxel Pack's .obj export (Phase 3
# terrain revamp) -- a distinct grey office-tower style layered ALONGSIDE the
# original hand-rendered town pack (apartment/house/mall/school/etc, still the
# majority and still the better source for that content), not replacing it.
# Single fixed camera angle only, no rotation manifest -- see TOWN_TOWER_SLUGS.
TOWN_TOWER_SLUGS = ("building_2", "building_3", "building_4", "building_5")


def _voxel_building_sprite(slug, rot):
    """Cached, scaled town-building sprite for the dense downtown."""
    key = (slug, rot)
    spr = _vbldg_cache.get(key)
    if spr is None:
        if slug in TOWN_TOWER_SLUGS:
            raw = va.terrain_sprite("downtown", slug)
        else:
            raw = va.sprite(slug, rot)
        tw = vc.TARGET_W.get(slug, 56)
        sc = tw / raw.get_width()
        spr = pygame.transform.smoothscale(
            raw, (max(1, round(raw.get_width() * sc)), max(1, round(raw.get_height() * sc))))
        _vbldg_cache[key] = spr
    return spr


_terrain_ground_cache = {}
_terrain_prop_cache = {}
# Ground patches are stamped every few tiles (see _bake's wash pre-pass), not
# once per cell -- a big soft patch of real texture reads as terrain; the same
# 22px image tiled on every single grid cell read as wallpaper (fixed after
# the first pass looked like a repeating mustard hex-hatch).
TERRAIN_GROUND_W = TW * 4.5
TERRAIN_PROP_W = {"tree_1": 34, "tree_2": 38, "tree_3": 38, "bush_1": 24,
                  "cactus_1": 22, "cactus_2": 26, "bones_1": 24,
                  "stone_1": 20, "stone_2": 24}

# Base tint per region so the procedural slab (which shows between the sparse
# baked patches) already reads as that biome, not flat season-green.
REGION_TINT = {"desert": (198, 156, 84), "forest": (84, 130, 74), "plains": (152, 140, 96)}


def _terrain_ground_sprite(region, name, target_w=TERRAIN_GROUND_W):
    """Cached, tile-scaled baked-glTF ground patch (see bake_gltf_terrain.py)."""
    key = (region, name, target_w)
    spr = _terrain_ground_cache.get(key)
    if spr is None:
        raw = va.terrain_sprite(region, name)
        sc = target_w / raw.get_width()
        spr = pygame.transform.smoothscale(
            raw, (max(1, round(raw.get_width() * sc)), max(1, round(raw.get_height() * sc))))
        _terrain_ground_cache[key] = spr
    return spr


_downtown_road_cache = {}
DOWNTOWN_ROAD_W = TW * 2.2   # sparse asphalt-texture overlay, not full per-tile tiling


def _downtown_road_sprite(name, target_w=DOWNTOWN_ROAD_W):
    """Cached, tile-scaled baked-glTF road patch (asphalt texture layered over
    the flat vroad slab -- see _bake's 'vroad' branch). Stamped sparsely
    (intersections + occasional straight-run tiles), same "oversized patch,
    not per-cell tiling" lesson as the ground wash: the flat slab underneath
    already guarantees a fully connected street grid regardless of where
    these texture patches land, so they don't need pixel-perfect seams."""
    key = (name, target_w)
    spr = _downtown_road_cache.get(key)
    if spr is None:
        raw = va.terrain_sprite("downtown", name)
        sc = target_w / raw.get_width()
        spr = pygame.transform.smoothscale(
            raw, (max(1, round(raw.get_width() * sc)), max(1, round(raw.get_height() * sc))))
        _downtown_road_cache[key] = spr
    return spr


def _terrain_prop_sprite(region, name):
    """Cached, scaled baked-glTF decoration prop (tree/cactus/stone/bones)."""
    key = (region, name)
    spr = _terrain_prop_cache.get(key)
    if spr is None:
        raw = va.terrain_sprite(region, name)
        tw = TERRAIN_PROP_W.get(name, 20)
        sc = tw / raw.get_width()
        spr = pygame.transform.smoothscale(
            raw, (max(1, round(raw.get_width() * sc)), max(1, round(raw.get_height() * sc))))
        _terrain_prop_cache[key] = spr
    return spr


def _plant_static_sprite(key, rng):
    """Return (sprite, offset). Prefer the cohesive voxel generation sprite;
    fall back to the manifest sprite, then procedural art (e.g. wind)."""
    slug = va.GEN_FOR_PLANT.get(key)
    if slug and va.has(slug):
        raw = va.sprite(slug, 0)
        tw = PLANT_VOXEL_WIDTH.get(key, 156)
        sc = tw / raw.get_width()
        spr = pygame.transform.smoothscale(
            raw, (max(1, round(raw.get_width() * sc)), max(1, round(raw.get_height() * sc))))
        # anchor bottom-centre on the plant tile's front
        offset = (-spr.get_width() // 2, TH - spr.get_height())
        return spr, offset
    try:
        sprite, offset, _switchyard, _visual = _manifest_plant_sprite(key)
        return sprite, offset
    except (FileNotFoundError, KeyError, ValueError):
        pass
    origin = (140, 90)
    canvas = pygame.Surface((280, 180), pygame.SRCALPHA)
    _draw_plant_static(canvas, key, origin[0], origin[1], rng)
    bounds = canvas.get_bounding_rect()
    sprite = canvas.subsurface(bounds).copy()
    offset = (bounds.left - origin[0], bounds.top - origin[1])
    if PLANT_ART_SCALE != 1:
        sprite = pygame.transform.scale(
            sprite,
            (sprite.get_width() * PLANT_ART_SCALE,
             sprite.get_height() * PLANT_ART_SCALE),
        )
        offset = (offset[0] * PLANT_ART_SCALE, offset[1] * PLANT_ART_SCALE)
    return sprite, offset


def _draw_plant_live(layer, site, level, t, night):
    """Per-frame animation for one plant, driven by how hard it is running."""
    x, y, key = site.sx, site.sy, site.key
    # Voxel-sprite plants are static for now (animation deferred); their live
    # plume/blade offsets were tuned to the old procedural art. Wind (no voxel
    # asset) still animates its turbine below.
    _slug = va.GEN_FOR_PLANT.get(key)
    if _slug and va.has(_slug):
        return
    # Aviation warning beacons on anything tall. Slow pulse, tiny area — this
    # is the one thing on a plant that stays lit whether or not it is running.
    def beacon(bx, by, period=2.6):
        if not night:
            return
        if (t % period) < period * 0.45:
            layer.fill((236, 70, 58), (int(bx), int(by), 1, 1))

    if key == "nuclear":
        front_tower_x, rear_tower_x = int(x + 2), int(x + 28)
        _plume(layer, front_tower_x, y - 15, level, t, site.phase, STEAM, 8, 34)
        _plume(layer, rear_tower_x, y - 2, level, t, site.phase + 0.4, STEAM, 7, 28)
        beacon(front_tower_x, y - 16)
        beacon(rear_tower_x, y - 3, 3.1)
        if night and level > 0.05:
            layer.fill(LIGHT_WARM, (x - 40, y - 2, 2, 1))
    elif key == "coal":
        for i, (dx, dy, hh) in enumerate(((6, 0, 44), (14, 3, 40),
                                          (22, 6, 35), (30, 9, 30))):
            _plume(layer, x + dx, y + dy - hh, level, t,
                   site.phase + i * 0.27, SMOKE, 5, 36 - i * 3)
            beacon(x + dx, y + dy - hh - 1, 2.4 + i * 0.3)
    elif key == "gas":
        for i, (_turbine, _recovery, stack) in enumerate(gas_cc_train_layout()):
            sx, sy = _gas_cc_point(x, y, stack)
            h = 31 - i * 2
            _plume(layer, sx, sy - h, level, t, site.phase + i * 0.32,
                   STEAM, 4, 27 - i * 2)
            beacon(sx, sy - h - 1, 2.6 + i * 0.4)
    elif key == "generic":
        _plume(layer, x + 4, y - 24, level, t, site.phase, STEAM, 4, 26)
    elif key == "peaker":
        # short, sharp exhaust — peakers run hot and briefly
        for i in range(3):
            _plume(layer, x - 22 + i * 15, y + i * 4 - 15, level, t,
                   site.phase + i * 0.3, SMOKE, 3, 16, puffs=5)
    elif key == "solar":
        # panels glint rather than emit: brightness IS the availability readout
        if level > 0.05:
            a = int(150 * level)
            for _group, dx, dy in solar_panel_layout():
                s = pygame.Surface((11, 6), pygame.SRCALPHA)
                pygame.draw.line(s, (*PANEL_GLINT, a), (1, 1), (9, 5))
                layer.blit(s, (x + dx, y + dy))
    elif key == "wind":
        # blades spin at a rate set by availability, not by demand
        site.blade_angle += (0.4 + level * 7.0) * (1.0 / 60.0)
        col = (232, 234, 240) if not night else (150, 156, 174)
        for i in range(4):
            px = x - 40 + i * 26
            py = y + (i % 2) * 10 - 26
            _turbine_blades(layer, px, py, 9, site.blade_angle + i * 0.7, col)
    elif key == "hydro":
        # Spillway: how much water goes over the face IS the output readout.
        # Gates are spaced along the downstream face, and the jet from each one
        # lengthens and brightens as the dam is worked harder.
        if level > 0.03:
            a, b = _dam_face(x, y)
            gates = 8
            for i in range(gates):
                f = (i + 0.5) / gates
                px = a[0] + (b[0] - a[0]) * f
                py = a[1] + (b[1] - a[1]) * f
                jet = (2.0 + level * (DAM_H - 1))
                alpha = int(110 + 130 * level)
                # a slow vertical shimmer so the sheet reads as moving water
                wob = math.sin(t * 2.2 + i * 0.9) * 0.8
                s = pygame.Surface((2, int(jet) + 1), pygame.SRCALPHA)
                s.fill((190, 216, 240, alpha))
                layer.blit(s, (int(px), int(py - DAM_H + wob)))
            # foam boiling at the toe, drifting downstream
            for i in range(int(2 + level * 8)):
                f = ((i * 0.19 + t * 0.28) % 1.0)
                px = a[0] + (b[0] - a[0]) * f
                py = a[1] + (b[1] - a[1]) * f
                pygame.draw.circle(layer, (206, 226, 244),
                                   (int(px + math.sin(t + i) * 2), int(py + 2)), 1)


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
VEHICLE_KINDS = [
    # (kind, body colour, weight)
    ("car", (208, 210, 216), 6),
    ("car", (176, 92, 78), 3),
    ("car", (92, 118, 168), 3),
    ("van", (84, 132, 176), 2),
    ("bus", (196, 176, 92), 1),
    ("truck", (150, 152, 158), 2),
    ("service", (232, 146, 54), 1),
]
MAX_VEHICLES = 96

# Travel direction on screen, per orientation, in half-tile steps.
# +1 col moves (+TW/2, +TH/2); +1 row moves (-TW/2, +TH/2). `across` is the
# other tile axis, always chosen pointing toward the camera (+y) so the side
# face we draw is the one actually facing the viewer.
#   orient = axis * 2 + (speed > 0)
_VEH_ALONG = {0: (-2, -1), 1: (2, 1), 2: (2, -1), 3: (-2, 1)}
_VEH_ACROSS = {0: (-2, 1), 1: (-2, 1), 2: (2, 1), 3: (2, 1)}

# (body segments, cab segments, height px). A bus is one long box; a truck
# splits into trailer + cab, which is the silhouette that reads as "truck".
_VEH_SHAPE = {"car": (3, 0, 3), "van": (4, 0, 4), "bus": (5, 0, 4),
              "truck": (4, 2, 3), "service": (3, 0, 4)}

_VEH_CACHE = {}
_VEH_SURF = (30, 24)          # generous enough for the longest truck, any orient
_VEH_ANCHOR = (15, 15)        # where the road tile's centre lands in the sprite


def _iso_box_px(surf, x, y, along, across, h, roof, light, dark):
    """An iso box from pixel-space edge vectors, rather than tile counts.

    `_shed` only does tile-aligned boxes; a vehicle is sub-tile and has to sit
    on an arbitrary point along a road. Which two side faces are visible is
    derived rather than hardcoded, so one function covers all four headings:
    the two roof edges whose midpoints sit lowest on screen are the ones facing
    the camera.
    """
    ax, ay = along
    bx, by = across
    base = [(x, y), (x + ax, y + ay), (x + ax + bx, y + ay + by), (x + bx, y + by)]
    top = [(px, py - h) for px, py in base]
    edges = sorted(range(4), key=lambda i: -(base[i][1] + base[(i + 1) % 4][1]))
    for shade_col, i in ((dark, edges[0]), (light, edges[1])):
        j = (i + 1) % 4
        pygame.draw.polygon(surf, shade_col, [top[i], top[j], base[j], base[i]])
    pygame.draw.polygon(surf, roof, top)
    return top


def _build_vehicle(kind, color, orient, night):
    """One vehicle sprite. Cached: 5 kinds x 4 headings x day/night = 40 tiny
    surfaces, built lazily, independent of the city bake."""
    surf = pygame.Surface(_VEH_SURF, pygame.SRCALPHA)
    along, across = _VEH_ALONG[orient], _VEH_ACROSS[orient]
    segs, cab_segs, h = _VEH_SHAPE[kind]
    total = segs + cab_segs
    ax, ay = along
    bx, by = across

    if night:
        color = shade(color, 0.30)
    light, dark = shade(color, 1.0), shade(color, 0.62)
    roof = shade(color, 1.22)

    # start the tail so the whole vehicle straddles the tile centre
    sx = _VEH_ANCHOR[0] - (ax * total) // 2 - bx // 2
    sy = _VEH_ANCHOR[1] - (ay * total) // 2 - by // 2

    # ground shadow, one flat parallelogram under the whole footprint
    shadow = pygame.Surface(_VEH_SURF, pygame.SRCALPHA)
    pygame.draw.polygon(shadow, (0, 0, 0, 80),
                        [(sx, sy + 1), (sx + ax * total, sy + ay * total + 1),
                         (sx + ax * total + bx, sy + ay * total + by + 1),
                         (sx + bx, sy + by + 1)])
    surf.blit(shadow, (0, 0))

    _iso_box_px(surf, sx, sy, (ax * segs, ay * segs), across, h, roof, light, dark)
    if cab_segs:
        cx, cy = sx + ax * segs, sy + ay * segs
        cab = (48, 48, 54) if not night else (26, 26, 30)
        _iso_box_px(surf, cx, cy, (ax * cab_segs, ay * cab_segs), across,
                    h + 1, shade(cab, 1.35), cab, shade(cab, 0.7))
        nose = (cx + ax * cab_segs + bx // 2, cy + ay * cab_segs + by // 2)
    else:
        nose = (sx + ax * total + bx // 2, sy + ay * total + by // 2)
        if kind in ("bus", "van"):       # window band along the flank
            pygame.draw.line(surf, (150, 190, 220) if not night else (60, 70, 86),
                             (sx + bx, sy + by - h + 1),
                             (sx + ax * segs + bx, sy + ay * segs + by - h + 1))
        if kind == "service":
            pygame.draw.circle(surf, (255, 204, 70),
                               (int(sx + ax * 1.5 + bx / 2), int(sy + ay * 1.5 + by / 2 - h)), 1)

    if night:
        # headlights are what actually reads after dark; the body barely does
        surf.fill((255, 236, 190), (int(nose[0]), int(nose[1]) - h, 2, 1))
        glow = pygame.Surface((7, 5), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (255, 226, 160, 46), (0, 0, 7, 5))
        surf.blit(glow, (int(nose[0]) + (ax // 2) - 3, int(nose[1]) - h - 2),
                  special_flags=pygame.BLEND_RGBA_ADD)
    else:
        pygame.draw.line(surf, (150, 190, 220),
                         (nose[0] - bx, nose[1] - by - h + 1), (nose[0], nose[1] - h + 1))
    return surf


def _vehicle_sprite(kind, color, orient, night):
    key = (kind, color, orient, night)
    spr = _VEH_CACHE.get(key)
    if spr is None:
        spr = _VEH_CACHE[key] = _build_vehicle(kind, color, orient, night)
    return spr


def vehicle_density_for_zoom(zoom):
    return {1: 0.24, 2: 0.48, 4: 0.72}[zoom]


def road_neighbors(tiles: dict) -> dict[tuple[int, int],
                                        tuple[tuple[int, int], ...]]:
    offsets = ((1, 0), (-1, 0), (0, 1), (0, -1))
    roads = {tile for tile, (kind, _extra) in tiles.items() if kind == "road"}
    return {tile: tuple((tile[0] + dc, tile[1] + dr)
                        for dc, dr in offsets
                        if (tile[0] + dc, tile[1] + dr) in roads)
            for tile in roads}


class _Fire:
    """A burning transformer. Has a place and a lifetime, so it stays put."""
    __slots__ = ("x", "y", "age", "life", "phase")

    def __init__(self, x, y, life, phase):
        self.x, self.y = x, y
        self.age, self.life, self.phase = 0.0, life, phase


class _Vehicle:
    __slots__ = ("tile", "next_tile", "previous_tile", "progress",
                 "speed", "kind", "color")

    def __init__(self, tile, next_tile, rng):
        self.tile, self.next_tile = tile, next_tile
        self.previous_tile = tile
        self.progress = rng.random()
        self.speed = rng.uniform(0.8, 1.6)
        kind, color, _w = rng.choices(
            VEHICLE_KINDS, weights=[w for *_r, w in VEHICLE_KINDS])[0]
        self.kind, self.color = kind, color

    def advance(self, dt, neighbors, rng) -> None:
        self.progress += self.speed * dt
        while self.progress >= 1.0:
            old_tile = self.tile
            arrived = self.next_tile
            candidates = neighbors.get(arrived, ())
            onward = tuple(tile for tile in candidates if tile != old_tile)
            if onward:
                candidates = onward
            if not candidates:
                self.tile = self.next_tile = arrived
                self.previous_tile = arrived
                self.progress = 0.0
                return
            self.tile = self.previous_tile = arrived
            self.next_tile = rng.choice(candidates)
            self.progress -= 1.0


# ---------------------------------------------------------------------------
class IsoCity:
    """The city view. Constructed once with the HUD fonts, then driven from
    GameState every frame via `draw`; `draw_homes_label` renders the readout
    that floats over it."""

    def __init__(self, font, font_label=None):
        self.font = font
        self.font_label = font_label or font
        self.t = 0.0
        self._key = None          # (rect size, population bucket, fleet)
        self._tiles = {}          # populated by _layout(); safe to read before prepare()
        self._road_network = None   # persistent RoadNetwork; created once, only grows
        self._base_day = None
        self._base_night = None
        self._detail_day = {}
        self._detail_night = {}
        # Transmission layer, baked in _bake and composited flat over the city
        # in draw() — no glow, no dimming scrim.
        self._transmission = None
        self._rings = []          # RINGS light layers, core outward
        self._cum = None          # rings 0..k-1 flattened, rebuilt when k moves
        self._cum_k = -1
        self._overlay = None
        self._composite = None
        self._wash = None
        self.camera = None
        self._world_rect = pygame.Rect(0, 0, 1, 1)
        self._plants = []
        self._city_centers = []
        self._vehicles = []
        self._road_neighbors = {}
        self._transmission_routes = []
        self._transformers = []
        self._distribution_pulses = []
        self._service_pulses = []
        self._origin = (0, 0)
        # overload state. Fires persist across frames, so they live on the
        # instance rather than being re-rolled from the clock each draw.
        self._fires = []
        self._ignite_acc = 0.0
        self._arcs = []
        self._arc_acc = 0.0
        self._arc_points = []     # switchyards now; substations/pylons in 1.2
        self._rng = random.Random(90210)

    # -- layout ------------------------------------------------------------
    def _extents(self, rect):
        """Half-extents of the built area in iso axis units, sized so a full
        city fills the viewport at whatever aspect it happens to be.

        The vertical extent is deliberately well short of the rect: buildings
        rise ~40px above their own tile and plant stacks more, all of it drawn
        UPWARD from the ground line, so a city sized to the full height gets its
        skyline sheared off along the top edge."""
        u_max = rect.width * 0.98 / TW
        v_max = rect.height * 0.72 / TH
        return max(6.0, u_max), max(4.0, v_max)

    def _layout(self, rect, population, fleet):
        """Place the whole city. Deterministic for a given (size, pop, fleet),
        so the same grid always produces the same town."""
        rng = random.Random(20260730)
        u_max, v_max = self._extents(rect)

        # Population -> capacity target for the persistent road network.
        # CAPACITY_PER_ROAD_CELL in road_network.py is illustrative, not tied
        # to a real units system. A raw 1:1 population->capacity mapping was
        # tried first and empirically blows past road_network.py's
        # MAX_BOOTSTRAP_TICKS ceiling (BootstrapExhausted around capacity
        # ~30,780 for master_seed=20260730) for any population above
        # roughly 30,000 -- confirmed against every population this file's
        # tests actually exercise, including test_city_size_tracks_population's
        # highest bucket (430,000) and test_baked_city_center_sprites_have_room_in_world's
        # 200,000. sqrt-compression keeps every realistic population under a
        # safe margin below that empirical ceiling while still producing a
        # strictly increasing target across population steps.
        target_capacity = min(SAFE_MAX_CAPACITY,
                              POPULATION_CAPACITY_SCALE * math.sqrt(max(0.0, population)))
        if self._road_network is None:
            self._road_network = bootstrap_network(target_capacity=target_capacity,
                                                    master_seed=20260730)
        elif self._road_network.capacity < target_capacity:
            # Live incremental growth: run ticks against the SAME persistent
            # network, never a fresh one, until this bucket's target is met
            # or ticks are exhausted for this bake.
            for _ in range(50):
                if self._road_network.capacity >= target_capacity:
                    break
                result = grow_tick(self._road_network, target_capacity=target_capacity)
                if result == TickResult.NO_CAPACITY_NEEDED:
                    break

        network = self._road_network
        min_c, max_c, min_r, max_r = network.frontier_bounds or (0, 0, 0, 0)
        # Extent: capacity-driven (network.capacity is monotonic
        # non-decreasing by construction -- RoadNetwork.capacity only ever
        # increases via commit_project -- so this alone guarantees strict
        # monotonicity across population steps, which raw frontier_bounds
        # could not: grow_tick prefers infill over outward extension, so the
        # frontier barely moves at low capacities even as roads/capacity
        # climb substantially). Blended with the real geometric frontier
        # distance as a floor, so _extent never reports a smaller footprint
        # than what's actually built, and still tracks real geometry once
        # the frontier does extend that far.
        far_u = max(abs(min_c - min_r), abs(max_c - max_r)) / max(1.0, u_max)
        far_v = max(abs(min_c + min_r), abs(max_c + max_r)) / max(1.0, v_max)
        geometric_extent = math.hypot(far_u, far_v)
        capacity_frac = min(1.0, network.capacity / SAFE_MAX_CAPACITY)
        self._extent = min(0.94, max(0.30, max(geometric_extent,
                                                0.30 + capacity_frac * 0.64)))

        urban = build_urban_layout(rect, tuple(fleet))   # districts, campuses, civic
                                                           # anchors, green tiles -- still
                                                           # a one-shot deterministic stamp,
                                                           # UNCHANGED; only ROADS/BUILDINGS
                                                           # now come from the persistent network
        self._urban_layout = urban

        def river_v(u):
            return 0.34 * v_max + 0.10 * v_max * math.sin(
                u / max(1.0, u_max * 0.42))

        tiles = {}
        buildings = []
        for pos, road in network.roads.items():
            tiles[pos] = ("road", road)
        # Buildings: one per road-adjacent buildable cell the network has
        # opened up so far -- minimal placement (Task 7), not the full
        # structure lifecycle (deferred to sub-project B). Reuses the
        # existing district/archetype selection from urban_blocks.py.
        buildable = _road_adjacent_buildable_cells(network, urban)
        for (col, row) in buildable:
            e = math.hypot((col - row) / u_max, (col + row) / v_max)
            angle = math.atan2((col + row) / v_max, (col - row) / u_max)
            district = _district(e, angle)
            archetype_name = _pick_archetype(district, col, row)
            tiles[(col, row)] = ("urban_block", _building_tile(col, row, district, archetype_name))
            buildings.append((col, row, archetype_name, e))
        for pos in urban.green_tiles:
            if pos not in tiles:
                tiles[pos] = ("park", None)
        for campus in urban.campuses.values():
            cc, rr = round(campus.col), round(campus.row)
            for dc in range(-campus.radius, campus.radius + 1):
                for dr in range(-campus.radius, campus.radius + 1):
                    if abs(dc) + abs(dr) <= campus.radius + 1:
                        tiles[(cc + dc, rr + dr)] = ("campus", campus.key)
        # Dense voxel downtown: a street grid with one town-building per block,
        # apartment towers downtown grading out to houses/shops. This overrides the
        # central tiles and is the visible city. The road network still exists
        # underneath for transmission routing.
        dt_r = 24
        for bx in range(-dt_r, dt_r + 1):
            for by in range(-dt_r, dt_r + 1):
                if math.hypot(bx, by) > dt_r:
                    continue
                if tiles.get((bx, by), (None,))[0] == "road":
                    continue                      # keep real roads (traffic drives them)
                if vc.is_street(bx, by):
                    tiles[(bx, by)] = ("vroad", None)
                elif vc.is_building(bx, by):
                    slug = vc.building_for(bx, by, math.hypot(bx, by) / dt_r)
                    tiles[(bx, by)] = ("voxel_bldg", slug)
                else:
                    tiles[(bx, by)] = ("pad", None)

        # Restore the countryside the road-network layout stopped generating, and
        # tag edge mountains. Fills the viewport so the city never floats on void.
        # `rect` here is the world rect; the city is centred on tile (0, 0).
        w, h = rect.width, rect.height
        ox, oy = w // 2, int(h * 0.56)
        span = int(w / TW) + 4
        for col in range(-span, span):
            for row in range(-span, span):
                pos = (col, row)
                if pos in tiles:
                    continue
                sx, sy = iso_xy(col, row)
                sx += ox
                sy += oy
                if not (-TW * 3 < sx < w + TW * 3 and -400 < sy < h + TH * 3):
                    continue
                elev = vt.elevation(col, row, 0.0, 0.0, start=52.0, full=72.0)
                if elev > 0:
                    tiles[pos] = ("mountain", elev)
                    continue
                u = col - row
                if abs((col + row) - river_v(u)) < 2.4:
                    tiles[pos] = ("water", None)
                else:
                    tiles[pos] = (vt.material_at(col, row), None)

        feeders = {}

        def feeder_roll(col, row):
            fk = (col // FEEDER_SIZE, row // FEEDER_SIZE)
            if fk not in feeders:
                feeders[fk] = random.Random(hash(fk) & 0xFFFF).random()
            return feeders[fk]

        lightable = {
            (col, row): e for col, row, _name, e in buildings
        }
        lightable.update({
            (col, row): math.hypot((col - row) / u_max,
                                   (col + row) / v_max)
            for (col, row), (kind, road) in tiles.items()
            if kind == "road" and road.avenue
        })
        # the dense voxel downtown lights up too (windows + street lamps)
        lightable.update({
            (col, row): math.hypot((col - row) / u_max, (col + row) / v_max)
            for (col, row), (kind, _e) in tiles.items()
            if kind in ("voxel_bldg", "vroad")
        })
        scored = []
        for (col, row), e in lightable.items():
            e_norm = min(1.0, e / 0.72)
            scored.append((CORE_BIAS * e_norm
                           + (1.0 - CORE_BIAS) * feeder_roll(col, row), col, row))
        scored.sort()
        n = max(1, len(scored))
        self._priority = {
            (col, row): index / n
            for index, (_score, col, row) in enumerate(scored)
        }

        # ONE switchyard adjacent to the city (front edge of downtown): every
        # plant's transmission corridor terminates here, and distribution feeders
        # pulse from here into downtown. Single hub keeps corridors convergent and
        # clear of the edge dials.
        # Just OUTSIDE the downtown, front-centre (toward the camera): transmission
        # arrives here from the plant ring without crossing the city, and
        # distribution pulses from here up into downtown.
        # Two switchyards sitting OUTSIDE the dense downtown (dt_r=24), in the
        # clear ring between the city edge and the plant ring: one front-centre,
        # one top-centre. Transmission terminates here without crossing the city;
        # distribution pulses inward from here into downtown.
        self._sub_sites = [(21, 21), (-19, -19)]
        self._switchyard_tile = self._sub_sites[0]
        self._tiles = tiles
        self._buildings = buildings
        self._city_centers = self._choose_city_centers(buildings, tiles)
        self._u_max, self._v_max = u_max, v_max
        self._place_plants(rect, fleet, rng, river_v)
        # Give each generating technology its own clear, flat floor: replace any
        # mountain/greenery/water tiles in a pad around the plant with flat "pad"
        # ground so no plant sits on a mountainside or in the trees.
        for site in self._plants:
            pc, pr = round(site.col), round(site.row)
            rad = 2 if site.key == "hydro" else 3
            for dc in range(-rad, rad + 1):
                for dr in range(-rad, rad + 1):
                    if abs(dc) + abs(dr) > rad + 1:
                        continue
                    t = (pc + dc, pr + dr)
                    k = self._tiles.get(t, (None,))[0]
                    if k in ("mountain", "farm", "grass", "tree", "park", None):
                        self._tiles[t] = ("pad", None)
        # clear a flat pad for each switchyard (override even city tiles so the
        # yard sits in its own clearing, readable as a hub)
        for swc, swr in self._sub_sites:
            for dc in range(-3, 4):
                for dr in range(-3, 4):
                    if abs(dc) + abs(dr) <= 4:
                        t = (swc + dc, swr + dr)
                        if self._tiles.get(t, (None,))[0] != "road":
                            self._tiles[t] = ("pad", None)
        self._make_roads(rng)
        return rng

    def _choose_city_centers(self, buildings, tiles):
        entries = assets.iso_city_center_entries()
        chosen = []
        used = set()
        central = sorted(
            (item for item in buildings
             if abs(item[0] - item[1]) <= 10 and abs(item[0] + item[1]) <= 10),
            key=lambda item: (item[3], item[0] + item[1], item[0] - item[1]),
        )
        for index, (col, row, _name, _e) in enumerate(central):
            if len(chosen) >= min(3, len(entries)):
                break
            if (col, row) in used:
                continue
            entry = entries[index % len(entries)]
            tiles[(col, row)] = ("bldg", "tower")
            chosen.append((col, row, entry))
            used.add((col, row))
        return chosen

    # Where each plant sits on the ring around town, as an angle. Chosen to
    # land in the CORNERS of the viewport: the city is an ellipse, so at 40-ish
    # degrees a point just past the built edge is comfortably outside the town
    # and still on screen, which is the only region that stays free even when
    # the city has grown to fill the whole rect.
    _PLANT_ANGLES = {
        "coal": 236.0, "nuclear": 200.0, "gas": 37.0,
        "peaker": 322.0, "wind": 108.0, "solar": 300.0,
        # Instructional Day 1 only, and never on screen beside gas: the
        # generic valve loses its capacity the moment gas is unlocked.
        "generic": 37.0,
    }

    def _place_plants(self, rect, fleet, rng, river_v):
        """Plants sit outside the built edge — on the river for hydro, on open
        ground for the rest — at fixed bearings so they never stack, and at a
        radius that tracks the town so they hug a village instead of stranding
        themselves at the horizon."""
        self._plants = []
        if not fleet:
            return
        u_max, v_max = self._u_max, self._v_max
        urban = getattr(self, "_urban_layout", None)
        for key in ("hydro", "generic", "coal", "nuclear", "gas", "peaker",
                    "wind", "solar"):
            if key not in fleet:
                continue
            # Every plant sits on its OWN distinct bearing in the clear ring
            # between the built city and the mountains (which start ~tile-dist 36),
            # so they never stack on each other, on the city, or on a mountainside.
            if key == "hydro":
                # A dam has to be IN the channel: sit on the river in the SAME
                # clear ring as the other plants (capped below the mountains), not
                # walked out to the horizon.
                r = min(0.46, max(self._extent * 1.0, 0.40))
                u = -u_max * r
                v = river_v(u)
                col, row = (u + v) / 2.0, (v - u) / 2.0
                row -= DAM_D / 2.0
            else:
                a = math.radians(self._PLANT_ANGLES[key])
                # Ring capped below the mountain radius so a plant never lands on
                # a slope; floored so it clears the built city edge.
                ring = min(0.66, max(self._extent * _edge_wobble(a) * 0.9 + 0.05, 0.56))
                u = u_max * ring * math.cos(a)
                v = v_max * ring * math.sin(a)
                col, row = (u + v) / 2.0, (v - u) / 2.0
            sx, sy = iso_xy(col, row)
            # Clamp the actual artwork bounds, not a guessed radius. Solar is
            # intentionally asymmetric around its logical origin; the old
            # fixed 58px allowance cropped its left corner and made its pin
            # appear shifted to the right.
            sprite, offset = _plant_static_sprite(key, rng)
            ox, oy, margin = rect.width // 2, int(rect.height * 0.56), 4
            sx = max(margin - ox - offset[0],
                     min(rect.width - margin - ox - offset[0] - sprite.get_width(), sx))
            sy = max(margin - oy - offset[1],
                     min(rect.height - margin - oy - offset[1] - sprite.get_height(), sy))
            site = PlantSite(key, col, row, sx, sy, rng.random())
            site.sprite = sprite
            site.sprite_offset = offset
            try:
                _sprite, _offset, switchyard, visual = _manifest_plant_sprite(key)
            except (FileNotFoundError, KeyError, ValueError):
                switchyard, visual = None, None
            if switchyard is not None:
                site.switchyard_offset = (switchyard[0] + offset[0],
                                          switchyard[1] + offset[1])
            if visual is not None:
                site.visual_dx = offset[0] + visual[0]
                site.visual_dy = offset[1] + visual[1]
            else:
                site.visual_dx = offset[0] + sprite.get_width() / 2.0
                site.visual_dy = offset[1] + sprite.get_height() / 2.0
            self._plants.append(site)

    # -- transmission ------------------------------------------------------
    # Bearings for the neighbourhood substations, spread so that a plant on any
    # bearing has one on its own side of town — a line then crosses countryside
    # and the fringe, never the middle of downtown.
    _SUB_ANGLES = (90.0, 210.0, 330.0)
    _SUB_RADIUS = 0.88          # of `extent`: just INSIDE the built edge

    def _substation_sites(self, extent, u_max, v_max):
        """-> ([(col, row)], {tiles to keep clear}). Candidates only; which ones
        actually get built is decided later by whether a plant routes to them."""
        sites, claimed = [], set()
        for deg in self._SUB_ANGLES:
            a = math.radians(deg)
            r = extent * self._SUB_RADIUS * _edge_wobble(a)
            u, v = u_max * r * math.cos(a), v_max * r * math.sin(a)
            col, row = int(round((u + v) / 2.0)), int(round((v - u) / 2.0))
            sites.append((col, row))
            for dc in range(-1, 2):
                for dr in range(-1, 2):
                    claimed.add((col + dc, row + dr))
        return sites, claimed

    def _takeoff(self, key, x, y):
        """Where a plant's conductors leave the site: the last gantry crossarm
        of its decorative switchyard, matching `_draw_plant_static`."""
        off = SWITCHYARD_TAKEOFF.get(key, (0, 0))
        return x + off[0], y + off[1]

    def _route_transmission(self, ox, oy):
        """Route plant conductors to substations, using streets in urban maps."""
        self._routes = []
        self._transmission_routes = self._routes
        self._subs_used = []
        if not self._plants or not self._sub_sites:
            return
        subs = [(iso_xy(c, r)[0] + ox, iso_xy(c, r)[1] + oy) for c, r in self._sub_sites]
        urban = getattr(self, "_urban_layout", None)
        if urban is not None:
            def screen(tile):
                x, y = iso_xy(*tile)
                return x + ox + TW // 2, y + oy + TH // 2

            def add_tile(points, tile):
                point = screen(tile)
                if point != points[-1]:
                    points.append(point)

            def central_route_tiles(entry, exit_tile):
                central = nearest_road_tile(urban, 0, 0)
                tiles = [entry]
                for target in (central, exit_tile):
                    segment = road_path_tiles(urban, tiles[-1], target)
                    for tile in segment[1:]:
                        if tile != tiles[-1]:
                            tiles.append(tile)
                return tiles

        used = set()
        for site in self._plants:
            ax, ay = site.switchyard_anchor()
            start = (ax + ox, ay + oy)
            # DIRECT corridor plant -> switchyard. Electrons flow straight to the
            # yard and terminate there -- they must NOT detour through downtown
            # (distribution, below, is what carries power from the yard into town).
            i = min(range(len(subs)),
                    key=lambda k: math.hypot(subs[k][0] - start[0],
                                             subs[k][1] - start[1]))
            used.add(i)
            mx, my = (start[0] + subs[i][0]) / 2.0, (start[1] + subs[i][1]) / 2.0
            self._routes.append((site.key, i, [start, (mx, my), subs[i]]))
            self._arc_points.append((mx, my))
        self._subs_used = sorted(used)
        self._sub_screen = subs
        return

    def _build_distribution(self, ox, oy):
        """Connect each feeder-sized building cluster to its nearest substation."""
        self._transformers = []
        self._distribution_pulses = []
        self._service_pulses = []
        if not self._subs_used:
            return
        groups = {}
        for col, row, _kind, _e in self._buildings:
            groups.setdefault((col // FEEDER_SIZE, row // FEEDER_SIZE), []).append((col, row))
        for group_key in sorted(groups):
            buildings = groups[group_key]
            col, row = min(buildings, key=lambda cr: self._priority.get(cr, 1.0))
            sx, sy = iso_xy(col, row)
            point = (sx + ox + TW // 2, sy + oy + TH // 2)
            sub_index = min(self._subs_used,
                            key=lambda i: math.hypot(self._sub_screen[i][0] - point[0],
                                                     self._sub_screen[i][1] - point[1]))
            priority = sum(self._priority.get(cr, 1.0) for cr in buildings) / len(buildings)
            site = TransformerSite(sub_index, (col, row), point, priority, buildings)
            index = len(self._transformers)
            self._transformers.append(site)
            route = street_route(self._sub_sites[sub_index], (col, row),
                                 self._sub_screen[sub_index], point, (ox, oy))
            self._distribution_pulses.append(
                (index, LinePulse(route, seed=abs(hash(("tx", group_key))) & 0xFFFF)))
            # A couple of endpoint branches make the final hop into the blocks
            # legible without covering the whole city in animated lines.
            for end_col, end_row in buildings[::max(1, len(buildings) // 2)][:2]:
                ex, ey = iso_xy(end_col, end_row)
                end = (ex + ox + TW // 2, ey + oy + TH // 2)
                route = street_route((col, row), (end_col, end_row),
                                     point, end, (ox, oy))
                self._service_pulses.append(
                    (index, LinePulse(route, seed=abs(hash(("svc", end_col, end_row))) & 0xFFFF)))

    def _make_roads(self, rng):
        """Build the street graph and seed vehicles on connected road edges."""
        self._road_neighbors = road_neighbors(self._tiles)
        edges = [(tile, neighbor)
                 for tile in sorted(self._road_neighbors)
                 for neighbor in self._road_neighbors[tile]
                 if tile < neighbor]
        self._vehicles = []
        if not edges:
            return
        for _ in range(MAX_VEHICLES):
            tile, next_tile = rng.choice(edges)
            if rng.random() < 0.5:
                tile, next_tile = next_tile, tile
            self._vehicles.append(_Vehicle(tile, next_tile, rng))

    # -- baking ------------------------------------------------------------
    def _bake(self, rect, population, fleet, ramp_by_key=None):
        ramp_by_key = ramp_by_key or {}
        # The art is authored on a 16x8 logical pixel grid and displayed at the
        # default 2x camera zoom, giving a crisp 32x16 master tile. Baking the
        # compact logical world once keeps all zoom levels cheap and avoids a
        # second, high-resolution copy of every light layer.
        w, h = required_world_size(rect)
        world_rect = pygame.Rect(0, 0, w, h)
        rng = self._layout(world_rect, population, fleet)
        # Origin: centre horizontally, and bias upward so tall towers and plant
        # stacks at the back of the city have somewhere to rise into.
        ox, oy = w // 2, int(h * 0.56)
        self._origin = (ox, oy)
        old_camera = self.camera
        self._world_rect = world_rect
        self.camera = Camera(world_rect.center,
                             old_camera.zoom if old_camera is not None else DEFAULT_ZOOM)

        day = pygame.Surface((w, h), pygame.SRCALPHA)
        night = pygame.Surface((w, h), pygame.SRCALPHA)
        detail_day = {
            "gameplay": pygame.Surface((w, h), pygame.SRCALPHA),
            "inspection": pygame.Surface((w, h), pygame.SRCALPHA),
        }
        rings = [pygame.Surface((w, h), pygame.SRCALPHA) for _ in range(RINGS)]

        srng = random.Random(4242)
        urban = getattr(self, "_urban_layout", None)
        season = getattr(self, "_pending_season", "summer")
        self._bake_season = season
        pal = vt.palette(season)
        region_code = getattr(self, "_pending_region", None)
        biome_weights = vt.region_weighted_biomes(region_code)

        # Regional ground wash: sparse, oversized baked-glTF patches (real
        # desert/forest/plains texture) drawn once, BEFORE the per-tile loop,
        # so they always sit underneath every tile/building/mountain baked
        # afterward regardless of iso depth order -- this is a background
        # wash, not a tile that needs occlusion. A first pass stamped a small
        # baked image on every single grid cell instead and produced a
        # repeating hex-hatch "wallpaper" look; sparse+oversized+jittered
        # patches read as organic ground instead.
        if season != "winter" and not terrain3d.is_enabled():
            wash_rng = random.Random(777)
            countryside = [(c, r) for (c, r), (k, _) in self._tiles.items()
                           if k in ("grass", "farm")]
            if countryside:
                cols = [c for c, _ in countryside]
                rows = [r for _, r in countryside]
                STEP = 5
                for wc in range(min(cols), max(cols) + 1, STEP):
                    for wr in range(min(rows), max(rows) + 1, STEP):
                        jc = wc + wash_rng.randint(-2, 2)
                        jr = wr + wash_rng.randint(-2, 2)
                        if self._tiles.get((jc, jr), (None,))[0] not in ("grass", "farm"):
                            continue
                        region = vt.region_of(jc, jr, 0.0, 0.0, weights=biome_weights)
                        variants = vt.GROUND_VARIANTS.get(region)
                        if not variants:
                            continue
                        gname = variants[wash_rng.randrange(len(variants))]
                        if not va.has_terrain(region, gname):
                            continue
                        wsx, wsy = iso_xy(jc, jr)
                        wsx += ox
                        wsy += oy
                        scale = TERRAIN_GROUND_W * (0.85 + 0.3 * wash_rng.random())
                        gspr = _terrain_ground_sprite(region, gname, target_w=scale)
                        gpos = (wsx + TW // 2 - gspr.get_width() // 2,
                               wsy + TH // 2 - gspr.get_height() // 2)
                        day.blit(gspr, gpos)
                        gnd = gspr.copy()
                        gnd.fill(NIGHT_MULT + (255,), None, pygame.BLEND_RGB_MULT)
                        night.blit(gnd, gpos)

        for (col, row) in sorted(self._tiles, key=lambda t: t[0] + t[1]):
            kind, extra = self._tiles[(col, row)]
            if terrain3d.is_enabled() and kind in ("grass", "farm", "tree", "water", "mountain", "road"):
                continue
            sx, sy = iso_xy(col, row)
            sx += ox
            sy += oy
            if not (-TW * 3 < sx < w + TW * 3 and -400 < sy < h + TH * 3):
                continue
            d = diamond(sx, sy)

            if kind == "mountain":
                elev_px = extra
                jit = 0.9 + 0.2 * srng.random()
                # snow caps only in winter; other seasons keep the region rock
                # colour (a lighter rock on the true peaks), never always-white.
                cap = pal["snow"] if (season == "winter" and elev_px >= 8) else (
                    shade(pal["rock"], 1.2) if elev_px >= 12 else None)
                height = elev_px * 2 + vt.VOX_DEPTH
                vt.column(day, sx, sy, height, pal["rock"], cap=cap, jit=jit)
                vt.column(night, sx, sy, height, shade(pal["rock"], 0.34),
                          cap=shade(cap, 0.34) if cap else None, jit=jit)
                continue

            if kind == "water":
                c = pal["water"]
                vt.slab(day, sx, sy, c)
                vt.slab(night, sx, sy, shade(c, 0.30))
                continue
            if kind == "road" and hasattr(extra, "role"):
                draw_urban_road(day, sx, sy, extra)
                draw_urban_road(night, sx, sy, extra, night=True)
                if extra.avenue:
                    ring = rings[self._ring_of(self._priority.get((col, row), 1.0))]
                    ring.fill((*LIGHT_WARM, 210), (sx + TW // 2, sy + TH // 2, 2, 1))
                continue
            if kind == "urban_block":
                seed = abs(hash(("urban_block", col, row))) & 0xFFFF
                draw_urban_block(day, sx, sy, extra, random.Random(seed))
                draw_urban_block(night, sx, sy, extra, random.Random(seed), night=True)
                role = urban.civic.get((col, row)) if urban is not None else None
                if role is not None:
                    civic_seed = abs(hash(("civic", role, col, row))) & 0xFFFF
                    draw_municipal_civic(day, sx, sy, role, random.Random(civic_seed))
                    draw_municipal_civic(night, sx, sy, role,
                                         random.Random(civic_seed), night=True)
                ring = rings[self._ring_of(self._priority.get((col, row), 1.0))]
                ring.fill((*LIGHT_WARM, 170), (sx + TW // 2, sy + TH // 2, 2, 1))
                continue
            if kind == "vroad":
                vt.slab(day, sx, sy, (62, 64, 70))
                vt.slab(night, sx, sy, (34, 36, 42))
                # Sparse baked-asphalt texture on top of the flat slab: the
                # slab alone already guarantees a fully connected street grid,
                # so these patches only need to read as "textured pavement,"
                # not tile edge-to-edge (crossing at every intersection,
                # straight texture every other tile along a run).
                cross = (col % vc.BLOCK == 0) and (row % vc.BLOCK == 0)
                rname = None
                if cross:
                    rname = "road_crossing"
                elif col % vc.BLOCK == 0 and row % 2 == 0:
                    rname = "road_straight_a"
                elif row % vc.BLOCK == 0 and col % 2 == 0:
                    rname = "road_straight_b"
                if rname and va.has_terrain("downtown", rname):
                    rspr = _downtown_road_sprite(rname)
                    rpos = (sx + TW // 2 - rspr.get_width() // 2,
                            sy + TH // 2 - rspr.get_height() // 2)
                    day.blit(rspr, rpos)
                    rnd = rspr.copy()
                    rnd.fill(NIGHT_MULT + (255,), None, pygame.BLEND_RGB_MULT)
                    night.blit(rnd, rpos)
                continue
            if kind == "voxel_bldg":
                vt.slab(day, sx, sy, pal["pad"])
                vt.slab(night, sx, sy, shade(pal["pad"], 0.30))
                spr = _voxel_building_sprite(extra, (col * 2 + row) & 3)
                pos = (sx + TW // 2 - spr.get_width() // 2, sy + TH - spr.get_height() + 2)
                day.blit(spr, pos)
                nd = spr.copy()
                nd.fill(NIGHT_MULT + (255,), None, pygame.BLEND_RGB_MULT)
                night.blit(nd, pos)
                ring = rings[self._ring_of(self._priority.get((col, row), 1.0))]
                ring.fill((*LIGHT_WARM, 180), (sx + TW // 2, sy + TH // 2, 2, 1))
                continue
            if kind == "campus":
                campus = urban.campuses.get(extra) if urban is not None else None
                radius = campus.radius if campus is not None else 2
                draw_utility_campus_base(day, sx, sy, radius)
                draw_utility_campus_base(night, sx, sy, radius, night=True)
                continue
            if kind == "road":
                avenue = _road_is_avenue(extra)
                c = ROAD_ARTERIAL if avenue else ROAD_LOCAL
                pygame.draw.polygon(day, c, d)
                pygame.draw.polygon(night, shade(c, 0.17), d)
                # Sparse lane paint gives the enlarged master tiles scale and
                # direction without turning every local street into striping.
                if avenue and (col + row) % 3 == 0:
                    center = (sx + TW // 2, sy + TH // 2)
                    if col % ARTERIAL_SPACING == 0:
                        ends = ((center[0] + 3, center[1] - 1),
                                (center[0] - 3, center[1] + 1))
                    else:
                        ends = ((center[0] - 3, center[1] - 1),
                                (center[0] + 3, center[1] + 1))
                    pygame.draw.line(detail_day["gameplay"], (226, 214, 146), *ends)
                    if col % ARTERIAL_SPACING == 0 and row % ARTERIAL_SPACING == 0:
                        for off in (-2, 0, 2):
                            pygame.draw.line(detail_day["inspection"], (220, 224, 216),
                                             (center[0] - 3 + off, center[1] - 2),
                                             (center[0] - 1 + off, center[1] + 2))
                if avenue:      # arterials carry street lighting
                    ring = rings[self._ring_of(self._priority.get((col, row), 1.0))]
                    ring.fill((*LIGHT_WARM, 210), (sx + TW // 2, sy + TH // 2, 2, 1))
                continue

            # Real-world-flavoured biome base tint: countryside away from the
            # city reads as forest / desert / plains rather than one uniform
            # green, blended with the season palette rather than overriding it
            # (winter snow cover still whites the whole map out).
            region = vt.region_of(col, row, 0.0, 0.0, weights=biome_weights)
            tint = REGION_TINT.get(region) if season != "winter" else None
            if kind == "farm":
                base = pal["field"]
            elif tint:
                base = tuple((t + g) // 2 for t, g in zip(tint, pal["grass"]))
            else:
                base = pal["grass"]
            jit = 0.9 + 0.2 * srng.random()
            # earth-toned block sides so grass/field turf reads as sitting on a
            # chunky soil voxel (winter tints the "soil" toward frozen grey).
            if season == "winter":
                day_side, night_side = (150, 150, 158), (86, 88, 96)
            else:
                day_side, night_side = (120, 92, 58), (72, 54, 36)
            vt.slab(day, sx, sy, base, jit=jit, side=day_side)
            vt.slab(night, sx, sy, shade(base, 0.22), jit=jit, side=night_side)

            if kind in ("tree", "park") and (kind == "tree" or srng.random() < 0.55):
                props = vt.DECOR_PROPS.get(region) if season != "winter" else None
                if props and all(va.has_terrain(region, p) for p in props):
                    pname = props[abs(hash((col, row, "prop"))) % len(props)]
                    pspr = _terrain_prop_sprite(region, pname)
                    ppos = (sx + TW // 2 - pspr.get_width() // 2,
                            sy + TH - pspr.get_height() + 2)
                    day.blit(pspr, ppos)
                    pnd = pspr.copy()
                    pnd.fill(NIGHT_MULT + (255,), None, pygame.BLEND_RGB_MULT)
                    night.blit(pnd, ppos)
                else:
                    spr, _ = tree(srng)
                    self._blit_pair(day, night, spr, sx, sy)
                continue
            if kind != "bldg":
                continue

            spr, lights = BUILDERS[extra](srng)
            self._blit_pair(day, night, spr, sx, sy)
            center_entry = next((entry for c, r, entry in self._city_centers
                                 if c == col and r == row), None)
            if center_entry is not None:
                center_sprite = assets.iso_sprite(center_entry["file"])
                base = center_entry.get(
                    "base",
                    [center_sprite.get_width() // 2, center_sprite.get_height() - 2],
                )
                self._blit_manifest_sprite_pair(day, night, center_sprite, base, sx, sy)
            roof_y = sy + TH - spr.get_height()
            pygame.draw.line(detail_day["gameplay"], (188, 194, 192),
                             (sx + 4, roof_y + 2), (sx + 11, roof_y + 2))
            pygame.draw.rect(detail_day["inspection"], (96, 108, 112),
                             (sx + 7, roof_y + 3, 3, 2))
            if lights is not None:
                ring = rings[self._ring_of(self._priority.get((col, row), 1.0))]
                # halo first (MAX, so overlaps don't stack), crisp windows on top
                g = GLOW_TALL if spr.get_height() > 22 else GLOW
                gr = g.get_width() // 2
                ring.blit(g, (sx + TW // 2 - gr, sy + TH // 2 - gr),
                          special_flags=pygame.BLEND_RGBA_MAX)
                ring.blit(lights, (sx, sy + TH - lights.get_height()))

        # Transmission, baked BEFORE the plants so conductors pass behind the
        # switchyards they leave from rather than over the top of them.
        #
        # `conductor_paths[(key, i)][arm]` collects the SAME elevated, offset
        # tower-by-tower point sequence used to draw each conductor (arm=-6 or
        # +6, at crossarm height y-16) — this is what fixes electrons actually
        # riding the drawn wire instead of a separate, silently mismatched
        # ground-level route. Previously the electron Flow was built from the
        # raw `path` (ground level, no offset) while the art used this
        # elevated/offset geometry independently; they had never been the
        # same points.
        self._route_transmission(ox, oy)
        grid = pygame.Surface((w, h), pygame.SRCALPHA)
        for i in self._subs_used:
            _substation(grid, *self._sub_screen[i])
        conductor_paths = {}
        for key, i, path in self._routes:
            arm_paths = {-6: [], 6: []}
            route_towers = []
            for (x0, y0), (x1, y1) in zip(path, path[1:]):
                span = math.hypot(x1 - x0, y1 - y0)
                n = max(1, int(span / 46.0))
                towers = [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n)
                          for k in range(n + 1)]
                # double-circuit conductors off the upper crossarm tips (+/-6)
                for a, b in zip(towers, towers[1:]):
                    for arm in (-6, 6):
                        _span(grid, (a[0] + arm, a[1] - 16), (b[0] + arm, b[1] - 16))
                for tx, ty in towers:
                    if not route_towers or route_towers[-1] != (tx, ty):
                        route_towers.append((tx, ty))
                for arm in (-6, 6):
                    for tx, ty in towers:
                        pt = (tx + arm, ty - 16)
                        if not arm_paths[arm] or arm_paths[arm][-1] != pt:
                            arm_paths[arm].append(pt)
            # Sparse, bold towers spaced by cumulative distance along the WHOLE
            # corridor (not per-segment), so the conductor lines carry it and the
            # towers are occasional punctuation -- never a lattice wall.
            acc = 1e9
            first_tower = True
            for j, (tx, ty) in enumerate(route_towers):
                if j > 0:
                    acc += math.hypot(tx - route_towers[j - 1][0], ty - route_towers[j - 1][1])
                if acc >= 150 or j == len(route_towers) - 1 or first_tower:
                    # a BOLD tower at the plant end (start), then sparse towers
                    _pylon(grid, int(tx), int(ty), h=30 if first_tower else 22)
                    first_tower = False
                    acc = 0.0
            conductor_paths[(key, i)] = arm_paths
        # small flat junction markers at every connection point, drawn last so
        # they sit on top of the conductors and substation kit
        for i in self._subs_used:
            _node(grid, int(self._sub_screen[i][0]), int(self._sub_screen[i][1]), r=4)
        for _key, _i, path in self._routes:
            _node(grid, int(path[0][0]), int(path[0][1]))
        # Transmission is not folded into the city bases — it composites flat
        # over the city in draw(), which is a compositing-order convenience,
        # not a brightness effect: no glow, no dimming scrim.
        self._transmission = grid

        # plant structures, drawn last so their stacks stand over the skyline
        self._arc_points = [self._sub_screen[i] for i in self._subs_used]
        for site in self._plants:
            px, py = site.sx + ox, site.sy + oy
            sprite = site.sprite
            offset = site.sprite_offset
            pos = (px + offset[0], py + offset[1])
            day.blit(sprite, pos)
            dark = sprite.copy()
            dark.fill(NIGHT_MULT + (255,), None, pygame.BLEND_RGB_MULT)
            night.blit(dark, pos)
            ax, ay = site.switchyard_anchor()
            self._arc_points.append((ax + ox, ay + oy))

        # Two electron Flows per corridor -- one per physical conductor,
        # built from the exact elevated/offset points the wire was drawn
        # with (conductor_paths, above) -- so pulses ride the real wire and
        # arrive exactly at the substation. Speed comes from that plant's
        # real ramp-up latency (see ramp_speed_px_s); rate still comes from
        # output, inside Flow.update_and_draw.
        self._flows = {}
        for key, i, path in self._routes:
            if key in NON_RAMP_SPEED_KEYS:
                speed = NON_RAMP_SPEED_PX_S
            else:
                speed = ramp_speed_px_s(ramp_by_key.get(key, RAMP_LATENCY_MAX_S))
            arm_paths = conductor_paths[(key, i)]
            self._flows[(key, i)] = [
                Flow(arm_paths[arm], speed_px_s=speed,
                    seed=abs(hash((key, i, arm))) & 0xFFFF)
                for arm in (-6, 6)
            ]
        self._build_distribution(ox, oy)
        # Distribution feeders read WARM (amber) and low-poled, clearly distinct
        # from the cool grey transmission corridors carrying electrons to the yard.
        DIST_AMBER = (232, 168, 78)
        for _index, pulse in self._distribution_pulses:
            for a, b, _length in pulse.segs:
                pygame.draw.line(detail_day["gameplay"], DIST_AMBER, a, b, 2)
                _pole(detail_day["gameplay"], int(a[0]), int(a[1]))
            if pulse.segs:
                last = pulse.segs[-1][1]
                _pole(detail_day["gameplay"], int(last[0]), int(last[1]))
        for _index, pulse in self._service_pulses:
            for a, b, _length in pulse.segs:
                pygame.draw.line(detail_day["inspection"], shade(CONDUCTOR, 1.1), a, b, 1)
                _pole(detail_day["inspection"], int(a[0]), int(a[1]), h=4)
        for transformer in self._transformers:
            _transformer(detail_day["gameplay"], *transformer.point)
            _transformer(detail_day["inspection"], *transformer.point, detailed=True)
            self._arc_points.append(transformer.point)

        # Fires hold layer-relative coordinates, so a rebake invalidates them.
        self._fires = []
        self._arcs = []
        detail_night = {}
        for name, layer in detail_day.items():
            dark = layer.copy()
            dark.fill(NIGHT_MULT + (255,), None, pygame.BLEND_RGB_MULT)
            detail_night[name] = dark
        self._base_day, self._base_night, self._rings = day, night, rings
        self._detail_day, self._detail_night = detail_day, detail_night
        self._overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        self._composite = pygame.Surface((w, h), pygame.SRCALPHA)
        self._wash = pygame.Surface((w, h), pygame.SRCALPHA)
        self._cum = pygame.Surface((w, h), pygame.SRCALPHA)
        self._cum_k = -1

    def _ring_of(self, priority):
        return min(RINGS - 1, max(0, int(priority * RINGS)))

    def _blit_pair(self, day, night, spr, sx, sy):
        pos = (sx, sy + TH - spr.get_height())
        day.blit(spr, pos)
        dark = spr.copy()
        dark.fill(NIGHT_MULT + (255,), None, pygame.BLEND_RGB_MULT)
        night.blit(dark, pos)

    def _blit_manifest_sprite_pair(self, day, night, sprite, base, sx, sy):
        pos = (sx - int(base[0]), sy + TH - int(base[1]))
        day.blit(sprite, pos)
        dark = sprite.copy()
        dark.fill(NIGHT_MULT + (255,), None, pygame.BLEND_RGB_MULT)
        night.blit(dark, pos)
        return pos

    # -- drawing -----------------------------------------------------------
    def zoom_at(self, direction, pos, rect):
        if self.camera is None:
            return
        i = ZOOMS.index(self.camera.zoom)
        i = max(0, min(len(ZOOMS) - 1, i + (1 if direction > 0 else -1)))
        self.camera.set_zoom(ZOOMS[i], pos, rect, self._world_rect)

    def pan_by(self, dx, dy, rect):
        if self.camera is None:
            return
        self.camera.center[0] -= dx / self.camera.zoom
        self.camera.center[1] -= dy / self.camera.zoom
        self.camera.clamp(rect, self._world_rect)

    def plant_markers(self, rect):
        """Camera-aware target, reachable anchor, and visibility per plant."""
        if self.camera is None:
            return {}
        markers = {}
        margin = 26
        usable = rect.inflate(-72, -72)
        for site in self._plants:
            sprite = getattr(site, "sprite", None)
            offset = getattr(site, "sprite_offset", None)
            if sprite is not None and offset is not None:
                art_world = (site.sx + self._origin[0] + offset[0],
                             site.sy + self._origin[1] + offset[1])
                art_screen = self.camera.world_to_screen(art_world, rect)
                art_rect = pygame.Rect(round(art_screen[0]), round(art_screen[1]),
                                       sprite.get_width() * self.camera.zoom,
                                       sprite.get_height() * self.camera.zoom)
                visible = art_rect.colliderect(usable)
            else:
                visible = None
            visual_dx = getattr(site, "visual_dx", 0.0)
            visual_dy = getattr(site, "visual_dy", 0.0)
            target = self.camera.world_to_screen(
                (site.sx + visual_dx + self._origin[0],
                 site.sy + visual_dy + self._origin[1]), rect)
            if visible is None:
                visible = usable.collidepoint(target)
            markers[site.key] = {
                "target": target,
                "anchor": (
                    max(rect.left + margin, min(rect.right - margin, target[0])),
                    max(rect.top + margin, min(rect.bottom - margin, target[1])),
                ),
                "visible": visible,
            }
        return markers

    def focus_plant(self, key, rect):
        site = next((site for site in self._plants if site.key == key), None)
        if site is None or self.camera is None:
            return False
        self.camera.center[:] = [site.sx + self._origin[0],
                                 site.sy + self._origin[1]]
        self.camera.clamp(rect, self._world_rect)
        return True

    def _present(self, surface, rect):
        """Crop the visible world before scaling, then place it in `rect`."""
        camera = self.camera
        camera.clamp(rect, self._world_rect)
        visible = camera.visible_world_rect(rect).clip(self._world_rect)
        if visible.width <= 0 or visible.height <= 0:
            return
        view = self._composite.subsurface(visible)
        size = (visible.width * camera.zoom, visible.height * camera.zoom)
        scaled = view if camera.zoom == 1 else pygame.transform.scale(view, size)
        dest = camera.world_to_screen(visible.topleft, rect)
        surface.blit(scaled, (round(dest[0]), round(dest[1])))

    @property
    def tiles(self):
        """Read-only view of the current tile layout: {(col, row): (kind, extra)}."""
        return self._tiles

    @property
    def layout_key(self):
        """Opaque key that changes exactly when _layout() has re-run (rect
        size, population bucket, fleet). Consumers that cache derived state
        from `tiles` (e.g. terrain3d's instance buffers) should key their
        cache on this."""
        return self._key

    @property
    def plants(self):
        """Read-only view of the current plant placements: list[PlantSite]."""
        return self._plants

    def prepare(self, rect, state):
        """Ensure camera, world layers, and plant markers exist for this frame.

        The persistent RoadNetwork survives across bakes (created once, only
        grows); a bake is still needed whenever population/fleet/viewport
        changes, since the RASTER layers (day/night surfaces) are baked
        images, not something updated incrementally -- only the underlying
        road/building DATA is incremental. `_layout` (called from `_bake`)
        is what actually decides whether to bootstrap fresh or grow the
        existing network.
        """
        population = state_population(state)
        fleet = tuple(sorted(s.key for s in state.sources if s.max_output_mw > 0))
        world_size = required_world_size(rect)
        # Season drives the ground palette; a season boundary forces exactly one
        # re-bake by participating in the bake key. _bake reads _pending_season.
        pending_season = vt.season_of(getattr(getattr(state, "date", None), "month", 8))
        self._pending_season = pending_season
        # Real-world grid region (EIA balancing-authority code from scenarios.py,
        # e.g. "PJM"/"ISNE"/"ERCO"; None for the national-average Standard grid)
        # biases countryside biome selection -- same key/re-bake mechanism as season.
        pending_region = getattr(getattr(state, "config", None), "region_code", None)
        self._pending_region = pending_region
        key = (world_size, round(population / 5000.0), fleet, pending_season, pending_region)
        if key != self._key:
            self._key = key
            ramp_by_key = {s.key: s.ramp_up_latency for s in state.sources}
            self._bake(rect, population, fleet, ramp_by_key)

    def draw(self, surface, rect, state, atmosphere=None):
        dt = 1.0 / 60.0
        self.t += dt
        self.prepare(rect, state)

        activity = activity_level(state.demand_level)
        served = served_fraction(state.fill_pct_display)
        ratio = state.total_actual_mw / state.demand_mw if state.demand_mw > 0 else 1.0
        voltage = voltage_overload_level(ratio)
        fire = fire_overload_level(ratio)
        day = daylight(state.sim_hour)
        atmosphere = atmosphere or sample_atmosphere(
            state.sim_hour, state.active_event.kind if state.active_event else None)

        # Continuous cross-fade rather than stepped: no rebuild, no hitch.
        world = self._composite
        world.fill((0, 0, 0, 0))
        world.blit(self._base_night, (0, 0))
        if day > 0.004:
            self._base_day.set_alpha(int(255 * day))
            world.blit(self._base_day, (0, 0))
        for name in detail_levels_for_zoom(self.camera.zoom)[1:]:
            world.blit(self._detail_night[name], (0, 0))
            if day > 0.004:
                self._detail_day[name].set_alpha(int(255 * day))
                world.blit(self._detail_day[name], (0, 0))
        wash_alpha = int(18 + 16 * day + 18 * atmosphere.wetness
                         + 24 * atmosphere.snow_cover + 10 * atmosphere.ice)
        self._wash.fill((*atmosphere.world_tint, wash_alpha))
        world.blit(self._wash, (0, 0))

        self._draw_vehicles(world, traffic_level(state.sim_hour, served), day, dt)
        self._draw_lights(world, self._world_rect, activity, served, day)

        # Transmission composites flat over the city — accurate shape and
        # scale carry the teaching, not glow or a dimming scrim.
        world.blit(self._transmission, (0, 0))

        # per-frame grid animation + plant/overload effects ride on top
        layer = self._overlay
        layer.fill((0, 0, 0, 0))
        self._draw_power_flow(layer, state, dt)
        self._draw_plants(layer, state, day)
        self._update_fires(dt, fire)
        if voltage > 0.0 or fire > 0.0 or self._fires or self._arcs:
            self._draw_overload(layer, self._world_rect, voltage, fire)
        world.blit(layer, (0, 0))
        self._present(surface, rect)

    def _draw_lights(self, surface, rect, activity, served, day):
        """`activity` is brightness (uniform, from the clock); `served` is reach
        (sheds the fringe first). Keeping them separate is what lets an outlying
        district be dim at 4 AM but never dead.

        Daylight drowns streetlights out in reality; a floor is kept so the
        supply readout never disappears at midday. A deliberate departure —
        how much of the city is lit IS the instrument.
        """
        if served <= 0 or activity <= 0:
            return
        strength = (1.0 - 0.55 * day) * activity
        if strength <= 0.01:
            return
        edge = served * RINGS
        k = int(edge)                     # rings fully lit; k is the boundary

        # Blitting all twelve ring layers every frame costs more than the rest
        # of the renderer put together, and the set that is fully lit only
        # changes when supply crosses a ring boundary — rarely. So flatten
        # rings 0..k-1 into one surface and reuse it until k moves.
        if k != self._cum_k:
            self._cum_k = k
            self._cum.fill((0, 0, 0, 0))
            for ring in self._rings[:k]:
                ring.set_alpha(255)
                self._cum.blit(ring, (0, 0))

        a = int(255 * strength)
        if k > 0 and a > 3:
            self._cum.set_alpha(a)
            surface.blit(self._cum, rect.topleft)
        # the boundary ring fades in rather than popping, so shedding reads as
        # a front moving inward instead of a row of blocks snapping off
        if k < RINGS:
            fa = int(a * min(1.0, edge - k))
            if fa > 3:
                self._rings[k].set_alpha(fa)
                surface.blit(self._rings[k], rect.topleft)

    def _occluded(self, col, row):
        """Is this road tile hidden behind a building nearer the camera?

        Vehicles are drawn in the per-frame overlay, on top of the baked city,
        so without this they drive straight through buildings. A full depth
        buffer is the general answer, but on a strict iso grid only three tiles
        can ever be in front of a given one — so three dict lookups settle it,
        with no bake cost and no memory.
        """
        for dc, dr in ((1, 0), (0, 1), (1, 1)):
            t = self._tiles.get((int(col) + dc, int(row) + dr))
            if t is not None and t[0] == "bldg":
                return True
        return False

    def _draw_vehicles(self, layer, level, day, dt):
        return   # cars removed by design -- the city reads its power via lighting
        n = int(len(self._vehicles) * level * vehicle_density_for_zoom(self.camera.zoom))
        ox, oy = self._origin
        night = day < 0.35
        ax, ay = _VEH_ANCHOR
        for veh in self._vehicles[:n]:
            veh.advance(dt, self._road_neighbors, self._rng)
            dc = veh.next_tile[0] - veh.tile[0]
            dr = veh.next_tile[1] - veh.tile[1]
            col = veh.tile[0] + dc * veh.progress - dr * 0.10
            row = veh.tile[1] + dr * veh.progress + dc * 0.10
            if self._occluded(col, row):
                continue
            sx, sy = iso_xy(col, row)
            orient = ((1 if dc > 0 else 0) if dc
                      else (3 if dr > 0 else 2))
            spr = _vehicle_sprite(veh.kind, veh.color, orient, night)
            layer.blit(spr, (sx + ox + TW // 2 - ax, sy + oy + TH // 2 - ay))

    def _draw_power_flow(self, layer, state, dt):
        """Per-frame animation for the whole delivery chain.

        Transmission: individual electron pulses, one Flow per conductor per
        corridor, riding the real elevated/offset conductor geometry and
        arriving exactly at the substation. Rate follows `actual_pct` — the
        ramped output, not what the player just asked for — so a plant that
        has been throttled back keeps its line lit until it has actually
        wound down. A plant at zero leaves a dark but still-drawn line: a
        dead circuit is still a circuit. Speed is fixed per Flow at bake
        time from the plant's real ramp-up latency (see ramp_speed_px_s).

        Distribution and service lines: no discrete particles — a travelling
        LinePulse wave, present only while that branch is actually
        energised (same served/priority gate the window-lighting ring model
        uses), so a dead feeder just stays dark and static.
        """
        by_key = {s.key: s for s in state.sources}
        for (key, i), flows in self._flows.items():
            src = by_key.get(key)
            out = 0.0 if src is None or src.max_output_mw <= 0 else src.actual_pct
            color = src.color if src is not None else (120, 200, 255)
            if key in ("solar", "gas", "peaker"):
                color = tuple(int(c * 0.72 + 78 * 0.28) for c in color[:3])
            frac = state.line_overload_frac.get(key, 0.0)
            for flow in flows:
                flow.update_and_draw(layer, out, dt, color=color, overload=frac)

        served = served_fraction(state.fill_pct_display)
        levels = detail_levels_for_zoom(self.camera.zoom)
        if "gameplay" in levels:
            for index, pulse in self._distribution_pulses:
                # intensity = how much power is actually flowing to this feeder
                # (0 when its circuit is shed); pulses speed up + brighten with it.
                intensity = served if self._transformers[index].priority < served else 0.0
                pulse.draw(layer, self.t, intensity, color=(255, 190, 92))
        if "inspection" in levels:
            for index, pulse in self._service_pulses:
                energised = self._transformers[index].priority < served
                pulse.draw(layer, self.t, energised)

    def _draw_plants(self, layer, state, day):
        by_key = {s.key: s for s in state.sources}
        ox, oy = self._origin
        night = day < 0.35
        for site in self._plants:
            src = by_key.get(site.key)
            if src is None or src.max_output_mw <= 0:
                continue
            level = _clamp01(src.current_output_mw / max(1.0, src.max_output_mw))
            saved = site.sx, site.sy
            site.sx, site.sy = site.sx + ox, site.sy + oy
            _draw_plant_live(layer, site, level, self.t, night)
            site.sx, site.sy = saved

    def _update_fires(self, dt, fire):
        """Ignite, age and retire transformer fires.

        Fires PERSIST. The previous version reseeded its RNG from the clock every
        half second, so the whole set teleported to different buildings twice a
        second — it read as noise rather than as a city burning. A fire now has a
        place and a life: it ignites small, grows, peaks and dies out, and when
        the player pulls the grid back the ignitions simply stop and the
        remaining fires burn themselves out.
        """
        for f in self._fires:
            f.age += dt
        self._fires = [f for f in self._fires if f.age < f.life]

        if fire <= 0.0:
            return
        self._ignite_acc += _ignite_rate(fire) * dt
        cap = _max_fires(fire)
        reach = _fire_reach(fire)
        while self._ignite_acc >= 1.0:
            self._ignite_acc -= 1.0
            if len(self._fires) >= cap or not self._buildings:
                break
            # _buildings is sorted nearest-downtown-first, so slicing the head
            # of it IS the spread model: a narrow reach keeps fires downtown, a
            # wide one lets the whole city catch.
            col, row, _n, _e = self._buildings[
                self._rng.randrange(max(1, int(len(self._buildings) * reach)))]
            sx, sy = iso_xy(col, row)
            self._fires.append(_Fire(sx + self._origin[0] + TW // 2,
                                     sy + self._origin[1],
                                     6.0 + self._rng.random() * 8.0,
                                     self._rng.random()))

    def _draw_overload(self, layer, rect, voltage, fire):
        """Oversupply: the grid cooking itself.

        The warning is restricted to the world edges. The center of the playfield
        stays clear so the city, plant controls, and transmission teaching remain
        readable while the edge still signals danger.
        """
        pulse = 0.5 + 0.5 * math.sin(self.t * 1.6)
        a = int(30 * voltage * (0.55 + 0.45 * pulse))
        if a > 3:
            thickness = int(12 + 24 * voltage)
            edge = pygame.Surface(rect.size, pygame.SRCALPHA)
            for i in range(thickness):
                k = 1.0 - i / max(1, thickness)
                alpha = int(a * k * k)
                if alpha <= 0:
                    continue
                pygame.draw.rect(edge, (*LIGHT_OVERLOAD, alpha),
                                 pygame.Rect(i, i,
                                             rect.width - i * 2,
                                             rect.height - i * 2),
                                 width=1)
            layer.blit(edge, (0, 0))

        for f in self._fires if fire > 0.0 else ():
            k = f.age / f.life
            size = 1.0 + 3.0 * math.sin(math.pi * k)        # ignite, peak, die
            r = size * (0.85 + 0.15 * math.sin(self.t * 5.0 + f.phase * 6.3))
            if r < 0.6:
                continue
            x, y = int(f.x), int(f.y)
            # A saturated red halo under the flame. Without it a fire is just
            # another warm dot among thousands of lit windows at night — the
            # one thing on screen that must never be missed reads as scenery.
            halo = int(r) + 4
            g = pygame.Surface((halo * 2, halo * 2), pygame.SRCALPHA)
            pygame.draw.circle(g, (255, 60, 24, 70), (halo, halo), halo)
            pygame.draw.circle(g, (255, 96, 32, 110), (halo, halo), max(1, halo - 2))
            layer.blit(g, (x - halo, y - halo))
            pygame.draw.circle(layer, FIRE, (x, y), int(r) + 1)
            pygame.draw.circle(layer, (255, 232, 176), (x, y), max(1, int(r) - 1))
            _plume(layer, f.x, f.y - 2, 0.4 + 0.5 * (1.0 - k), self.t,
                   f.phase, SMOKE, 3, 14, puffs=4)

        # Arcing at the switchyards: brief, tiny, and allowed to be sharp.
        if voltage > 0.4 and self._arc_points:
            self._arc_acc += voltage * 3.0 * (1.0 / 60.0)
            while self._arc_acc >= 1.0 and len(self._arcs) < 3:
                self._arc_acc -= 1.0
                ax, ay = self._rng.choice(self._arc_points)
                pts = [(ax + self._rng.randint(-5, 5), ay + self._rng.randint(-7, 1))
                       for _ in range(4)]
                self._arcs.append([0.0, pts])
        for arc in self._arcs if voltage > 0.4 else ():
            arc[0] += 1.0 / 60.0
            if arc[0] < 0.12:
                pygame.draw.lines(layer, (214, 236, 255), False, arc[1], 1)
                pygame.draw.circle(layer, (180, 214, 255), arc[1][0], 2, 1)
        self._arcs = ([a for a in self._arcs if a[0] < 0.12]
                      if voltage > 0.4 else [])

    # -- readout -----------------------------------------------------------
    def draw_homes_label(self, surface, anchor, homes_out: float, homes_total: float):
        """"Homes Without Power" readout, centred on the anchor rect's column."""
        if homes_out > 500:
            color = LABEL_BAD if homes_out > homes_total * 0.5 else LABEL_WARN
            value = f"{homes_out:,.0f}"
        else:
            color, value = LABEL_OK, "0"
        cap_txt = self.font.render("HOMES WITHOUT POWER", True, LABEL_DIM)
        val_txt = self.font_label.render(value, True, color)
        pop_icon = assets.resource_icon("population", 14)
        cx = anchor.centerx
        cap_x = cx - cap_txt.get_width() // 2
        # dark scrim so the readout stays legible over the lit city behind it
        block_h = cap_txt.get_height() + val_txt.get_height() + 4
        block_w = max(cap_txt.get_width() + 20, val_txt.get_width()) + 24
        scrim = pygame.Surface((block_w, block_h + 10), pygame.SRCALPHA)
        scrim.fill((10, 13, 21, 165))
        surface.blit(scrim, (cx - block_w // 2, anchor.top - 5))
        surface.blit(pop_icon, (cap_x - pop_icon.get_width() - 4,
                                anchor.top + (cap_txt.get_height() - 14) // 2))
        surface.blit(cap_txt, (cap_x, anchor.top))
        surface.blit(val_txt, (cx - val_txt.get_width() // 2,
                               anchor.top + cap_txt.get_height() + 2))
