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
from ui.grid_flow import Flow
from ui.time_of_day import daylight

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
CORE_BIAS = 0.42
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


def distribution_level(priority, served, upstream):
    """Visible downstream flow for one feeder branch."""
    return _clamp01(upstream) if priority < served else 0.0


def lit_fraction(demand_level: float, fill_pct: float,
                 awake_min: float = AWAKE_MIN) -> float:
    """The share of the city actually illuminated. Kept as a single derived
    number for the tests and the readout; the renderer uses the two inputs
    separately, which is the whole point of the model."""
    return activity_level(demand_level, awake_min) * served_fraction(fill_pct)


def overload_level(fill_pct: float, meltdown: float) -> float:
    """0..1 severity of oversupply, normalised so 1.0 lands exactly on the
    difficulty's meltdown line — the visual peak and the run-ending condition
    always coincide, at every tier."""
    if fill_pct <= 1.0 or meltdown <= 1.0:
        return 0.0
    return _clamp01((fill_pct - 1.0) / (meltdown - 1.0))


# Overload escalation.
#
# `overload_level` saturates at 1.0 exactly on the meltdown line, which is right
# for "how bad is this" but leaves NO resolution in the window where the player
# is actually about to lose — on Expert, meltdown is 1.15 while fill_pct runs to
# 2.3. So severity takes a second input, `crisis`, from how long the grid has sat
# past the line (danger_timer / danger_grace). That is in seconds, identical
# across tiers, and already bleeds off at 1.5x on recovery, so the fires recede
# when the player fixes the problem — which is the feedback that makes it a
# readout rather than decoration.
FIRE_FROM = 0.55        # `over` at which the first transformer lets go


def _ignite_rate(over, crisis):
    """New fires per second."""
    return max(0.0, over - FIRE_FROM) * 4.0 + crisis * 6.0


def _max_fires(over, crisis):
    return int(4 + 28 * over + 20 * crisis)


def _fire_reach(over, crisis):
    """Fraction of the city that can catch, 0..1, as a share of the
    downtown-first `_buildings` ordering. Starts as a downtown problem and
    spreads outward as things get worse."""
    return min(1.0, 0.12 + 0.88 * (0.5 * over + 0.5 * crisis))


# Traffic follows the clock, not the grid: cars do not run on electricity.
# Hourly weights, linearly interpolated and continuous across midnight.
_TRAFFIC_BY_HOUR = [
    0.06, 0.04, 0.04, 0.05, 0.10, 0.26, 0.55, 0.82,   # 00-07
    0.95, 1.00, 0.86, 0.80, 0.78, 0.80, 0.82, 0.88,   # 08-15
    0.96, 1.00, 0.92, 0.74, 0.58, 0.44, 0.30, 0.14,   # 16-23
]


def traffic_level(sim_hour: float, served: float = 1.0,
                  traffic_min: float = TRAFFIC_MIN) -> float:
    """Vehicles on the road, 0..1. A shed grid damps activity (dark signals,
    people staying put) but never kills it."""
    h = sim_hour % 24.0
    i = int(h)
    frac = h - i
    base = (_TRAFFIC_BY_HOUR[i] * (1.0 - frac)
            + _TRAFFIC_BY_HOUR[(i + 1) % 24] * frac)
    damp = 0.55 + 0.45 * _clamp01(served)
    return max(traffic_min, base * damp)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
TW, TH = 16, 8          # iso tile footprint in pixels (2:1, the classic ratio)
ZOOMS = (1, 2, 4)
DEFAULT_ZOOM = 2
REGION_OVERSCAN = 0.18  # total extra world span beyond a full 1x viewport


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
# must not turn the city into a different-scale object. Career mode can provide
# a real `state.population`, which then drives the same layout directly.
ILLUSTRATIVE_POPULATION = 15_000


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

# How much of the viewport the largest city may cover. Well short of 1.0: the
# city has to sit IN a landscape, with fields and woodland around it and room
# for the plants to stand out in open country. A city grown to the frame edge
# reads as wallpaper and leaves the plants nowhere to go.
MAX_EXTENT = 0.72


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

GRASS = [(86, 132, 58), (94, 142, 62), (78, 122, 52)]
PARK = [(74, 136, 54), (88, 150, 62)]
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
    return (hash((col // WOOD_SIZE, row // WOOD_SIZE, 0x5EED)) >> 5) % 100 < 28

ROAD_LOCAL = (146, 146, 144)
ROAD_ARTERIAL = (186, 188, 186)

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
    ((132, 92, 58), (214, 200, 172), (152, 140, 120)),   # brown tile
    ((72, 108, 88), (226, 220, 202), (160, 154, 142)),   # green metal
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


BUILDERS = {"house": house, "shop": shop, "block": block,
            "midrise": midrise, "tower": tower}


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

    for i in range(h):
        t = i / max(1, h - 1)
        w = profile(t)
        y = base_y - i
        depth = 0.86 + 0.14 * t          # a little aerial lift toward the rim
        for dx in range(-int(w), int(w) + 1):
            nt = max(-1.0, min(1.0, dx / w))
            f = 0.36 + 0.74 * max(0.0, math.cos(math.asin(nt) - light))
            surf.set_at((int(x + dx), int(y)), shade(CONCRETE, min(1.15, f * depth)))

    # rim: outer lip, then the shaft mouth you can see down into
    wt = profile(1.0)
    ry = max(2, int(wt * 0.42))
    top = base_y - h
    pygame.draw.ellipse(surf, shade(CONCRETE, 0.72),
                        (int(x - wt * 1.05), top - ry, int(wt * 2.1), ry * 2))
    pygame.draw.ellipse(surf, shade(CONCRETE, 1.18),
                        (int(x - wt), top - ry - 1, int(wt * 2), ry * 2))
    pygame.draw.ellipse(surf, (48, 52, 58),
                        (int(x - wt * 0.76), top - int(ry * 0.76) - 1,
                         int(wt * 1.52), max(2, int(ry * 1.52))))
    pygame.draw.arc(surf, (220, 220, 216),
                    (int(x - wt), top - ry - 1, int(wt * 2), ry * 2),
                    math.pi, math.tau, 1)

    # A continuous flared skirt reads cleanly at game scale; individual intake
    # legs produced a jagged, detached base.
    wb = profile(0.0)
    pygame.draw.arc(surf, shade(CONCRETE, 0.45),
                    (int(x - wb), base_y - max(2, int(wb * 0.22)),
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

    def switchyard_anchor(self):
        """Decorative line takeoff; intentionally carries no simulation state."""
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


def _pylon(surf, x, y, h=11):
    """A lattice tower: two splayed legs and a crossarm."""
    pygame.draw.line(surf, STEEL_DARK, (x - 3, y), (x, y - h), 1)
    pygame.draw.line(surf, STEEL_DARK, (x + 3, y), (x, y - h), 1)
    pygame.draw.line(surf, STEEL, (x, y - h + 3), (x, y - h), 1)
    pygame.draw.line(surf, STEEL, (x - 4, y - h + 1), (x + 4, y - h + 1), 1)
    pygame.draw.line(surf, shade(STEEL_DARK, 0.8), (x - 2, y - h + 5),
                     (x + 2, y - h + 5), 1)


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
    pygame.draw.lines(surf, (58, 62, 70), False, pts, 1)


def _substation(surf, x, y):
    """Where transmission steps back down to distribution."""
    _lot(surf, x - 16, y - 8, 3, 3)
    _switchyard(surf, x - 14, y + 6, 3)
    _switchyard(surf, x - 2, y + 12, 3)
    _shed(surf, x + 10, y + 2, 1, 1, 7, light=CONCRETE, dark=CONCRETE_DARK)


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
        pygame.draw.line(surf, (206, 170, 74),
                         (x - 83, y + 20), (x - 26, y + 43), 1)
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
        back = (x - 52, y - 34)
        _lot(surf, *back, 13, 10, color=(92, 102, 78))
        # Two genuine isometric gravel strips divide the field into quadrants.
        cx, cy = iso_xy(6, 0)
        _lot(surf, back[0] + cx, back[1] + cy, 1, 10, color=(156, 148, 118))
        rx, ry = iso_xy(0, 5)
        _lot(surf, back[0] + rx, back[1] + ry, 13, 1, color=(150, 144, 116))
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


def _plant_static_sprite(key, rng):
    """Render one plant into a tight local surface and return (sprite, offset)."""
    origin = (120, 90)
    canvas = pygame.Surface((240, 180), pygame.SRCALPHA)
    _draw_plant_static(canvas, key, origin[0], origin[1], rng)
    bounds = canvas.get_bounding_rect()
    sprite = canvas.subsurface(bounds).copy()
    return sprite, (bounds.left - origin[0], bounds.top - origin[1])


def _draw_plant_live(layer, site, level, t, night):
    """Per-frame animation for one plant, driven by how hard it is running."""
    x, y, key = site.sx, site.sy, site.key
    # Aviation warning beacons on anything tall. Slow pulse, tiny area — this
    # is the one thing on a plant that stays lit whether or not it is running.
    def beacon(bx, by, period=2.6):
        if not night:
            return
        if (t % period) < period * 0.45:
            layer.fill((236, 70, 58), (int(bx), int(by), 1, 1))

    if key == "nuclear":
        _plume(layer, x + 2, y - 15, level, t, site.phase, STEAM, 8, 34)
        _plume(layer, x + 28, y - 2, level, t, site.phase + 0.4, STEAM, 7, 28)
        beacon(x + 2, y - 16)
        beacon(x + 28, y - 3, 3.1)
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
MAX_VEHICLES = 260

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
    return {1: 0.42, 2: 0.76, 4: 1.0}[zoom]


class _Fire:
    """A burning transformer. Has a place and a lifetime, so it stays put."""
    __slots__ = ("x", "y", "age", "life", "phase")

    def __init__(self, x, y, life, phase):
        self.x, self.y = x, y
        self.age, self.life, self.phase = 0.0, life, phase


class _Vehicle:
    __slots__ = ("axis", "line", "pos", "lo", "hi", "speed", "kind", "color")

    def __init__(self, axis, line, lo, hi, rng):
        self.axis, self.line, self.lo, self.hi = axis, line, lo, hi
        self.pos = rng.uniform(lo, hi)
        self.speed = rng.uniform(1.4, 3.0) * rng.choice((1, -1))
        kind, color, _w = rng.choices(
            VEHICLE_KINDS, weights=[w for *_r, w in VEHICLE_KINDS])[0]
        self.kind, self.color = kind, color


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
        self._base_day = None
        self._base_night = None
        self._detail_day = {}
        self._detail_night = {}
        self._rings = []          # RINGS light layers, core outward
        self._cum = None          # rings 0..k-1 flattened, rebuilt when k moves
        self._cum_k = -1
        self._overlay = None
        self._composite = None
        self._wash = None
        self.camera = None
        self._world_rect = pygame.Rect(0, 0, 1, 1)
        self._plants = []
        self._vehicles = []
        self._road_lines = []
        self._transformers = []
        self._distribution_flows = []
        self._service_flows = []
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

        # Candidate tiles, nearest-downtown first.
        #
        # The generated region is a RECTANGLE in iso axis space large enough to
        # cover the whole viewport, not just the town ellipse: power plants sit
        # outside the built edge, and with terrain stopping at the ellipse they
        # stood on empty background. The city ellipse is then carved out of this
        # landscape, and everything past its edge is countryside.
        u_lim, v_lim = u_max * 1.06, v_max * 1.75
        m = int((u_lim + v_lim) / 2) + 2
        coords = []
        for col in range(-m, m + 1):
            for row in range(-m, m + 1):
                u, v = col - row, col + row
                if abs(u) > u_lim or abs(v) > v_lim:
                    continue
                # A clean ellipse reads as a machined lens. Stacked harmonics on
                # the radius push the boundary into lobes and notches — towns
                # grow along corridors and stall against terrain, so the outline
                # should be lumpy at several scales, not merely dented.
                th = math.atan2(v / v_max, u / u_max)
                coords.append((math.hypot(u / u_max, v / v_max) / _edge_wobble(th),
                               col, row))
        coords.sort()

        # The river runs along the long axis, so it reads across a wide
        # viewport, and wanders enough not to look surveyed.
        def river_v(u):
            return 0.30 * v_max + 0.16 * v_max * math.sin(u / (u_max * 0.34))

        # How far the town reaches is SOLVED FOR, not chosen: find the smallest
        # extent whose building stock houses the population. Capacity rises
        # monotonically with extent, so a bisection lands it in a few passes,
        # and the estimator below is the exact expectation of the sampling loop
        # (same mix table), so the two cannot drift apart.
        buildable = [(e, col, row) for e, col, row in coords
                     if abs((col + row) - river_v(col - row)) >= 1.4
                     and col % ROAD_SPACING != 0 and row % ROAD_SPACING != 0]

        def capacity_at(extent):
            total = 0.0
            for e, _c, _r in buildable:
                if e > extent:
                    break
                d = e / max(0.02, extent)
                total += _density(d) * _expected_capacity(d, population)
            return total

        if capacity_at(MAX_EXTENT) <= population:
            extent = MAX_EXTENT     # a metro that has outgrown the viewport
        else:
            lo, hi = 0.02, MAX_EXTENT
            for _ in range(24):
                mid = (lo + hi) / 2.0
                if capacity_at(mid) < population:
                    lo = mid
                else:
                    hi = mid
            extent = hi

        # Lay the town down at that extent. Density stays high right out to the
        # edge and then stops: real towns end abruptly against farmland rather
        # than fading out, and a gradual fade is exactly what made a
        # 10,000-person town read as a hamlet of fifty.
        # Substation sites, reserved BEFORE anything is built on them. Doing it
        # inside this loop rather than bulldozing afterwards keeps `buildings`
        # and `_priority` consistent — a building that was placed and then
        # deleted would still be carrying a lighting rank.
        sub_sites, sub_tiles = self._substation_sites(extent, u_max, v_max)

        tiles = {}
        buildings = []
        for e, col, row in coords:
            u, v = col - row, col + row
            if abs(v - river_v(u)) < 1.4:
                tiles[(col, row)] = ("water", None)
                continue
            if e > extent:
                continue
            if (col, row) in sub_tiles:
                tiles[(col, row)] = ("grass", None)
                continue
            if col % ROAD_SPACING == 0 or row % ROAD_SPACING == 0:
                tiles[(col, row)] = ("road", (col % ARTERIAL_SPACING == 0
                                              or row % ARTERIAL_SPACING == 0))
                continue
            d = e / max(0.02, extent)
            if rng.random() >= _density(d):
                tiles[(col, row)] = ("park" if rng.random() < 0.45 else "grass", None)
                continue
            name = _tier(d, population, rng)
            tiles[(col, row)] = ("bldg", name)
            buildings.append((col, row, name, e))

        # Everything past the town edge is countryside: woodland thinning into
        # cultivated fields. It also gives the plants something to stand on.
        for e, col, row in coords:
            if (col, row) in tiles:
                continue
            r = rng.random()
            if _woodland(col, row):
                kind = "tree" if r < 0.52 else "grass"
            elif r < 0.04:
                kind = "tree"                 # a hedgerow standard or two
            elif r < 0.76:
                kind = "farm"
            else:
                kind = "grass"
            tiles[(col, row)] = (kind, None)

        # Shed order.
        #
        # Utilities do not shed a neat disc from the fringe inward — they drop
        # FEEDER CIRCUITS, and a feeder serves one neighbourhood-sized patch
        # while its neighbours stay live. So a half-supplied city is patchy:
        # dark blocks scattered right across the map, not a shrinking bullseye.
        # What survives the longest is the core, because downtown circuits carry
        # hospitals, signals and substations and are shed last by policy.
        #
        # priority = CORE_BIAS * (how far out you are) + the rest * (which
        # feeder you happen to sit on). The feeder term is drawn per PATCH, not
        # per building, which is what makes outages come in blocks.
        feeders = {}

        def feeder_roll(col, row):
            fk = (col // FEEDER_SIZE, row // FEEDER_SIZE)
            if fk not in feeders:
                feeders[fk] = random.Random(hash(fk) & 0xFFFF).random()
            return feeders[fk]

        lightable = [(col, row, e) for col, row, _name, e in buildings]
        lightable += [(col, row, e) for e, col, row in coords
                      if tiles.get((col, row), (None, None))[0] == "road"
                      and tiles[(col, row)][1]]
        scored = []
        for col, row, e in lightable:
            e_norm = min(1.0, e / max(0.02, extent))
            scored.append((CORE_BIAS * e_norm
                           + (1.0 - CORE_BIAS) * feeder_roll(col, row), col, row))
        # Rank-normalise so `priority < served` really does light that share of
        # the city. The raw score is heavily clustered, and without ranking a
        # nominal 15% lit came out near 1% and the 04:00 city was black.
        scored.sort()
        n = max(1, len(scored))
        self._priority = {(c, r): i / n for i, (_s, c, r) in enumerate(scored)}

        self._sub_sites = sub_sites
        self._tiles = tiles
        self._buildings = buildings
        self._extent = extent
        self._u_max, self._v_max = u_max, v_max
        self._place_plants(rect, fleet, rng, river_v)
        self._make_roads(rng)
        return rng

    # Where each plant sits on the ring around town, as an angle. Chosen to
    # land in the CORNERS of the viewport: the city is an ellipse, so at 40-ish
    # degrees a point just past the built edge is comfortably outside the town
    # and still on screen, which is the only region that stays free even when
    # the city has grown to fill the whole rect.
    _PLANT_ANGLES = {
        "coal": 143.0, "nuclear": 218.0, "gas": 37.0,
        "peaker": 322.0, "wind": 108.0, "solar": 288.0,
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
        for key in ("hydro", "generic", "coal", "nuclear", "gas", "peaker",
                    "wind", "solar"):
            if key not in fleet:
                continue
            if key == "hydro":
                # A dam has to be IN the channel. Walk upstream until the river
                # is clear of the built-up area, then sit on it.
                r = max(self._extent, 0.24)
                for _ in range(24):
                    u = -u_max * r
                    v = river_v(u)
                    th = math.atan2(v / v_max, u / u_max)
                    if math.hypot(u / u_max, v / v_max) > self._extent * _edge_wobble(th) * 1.18:
                        break
                    r += 0.05
                col, row = (u + v) / 2.0, (v - u) / 2.0
                # the wall extends DAM_D tiles along +row, so shift the anchor
                # back by half of that to straddle the water rather than start
                # at it and run off into the fields
                row -= DAM_D / 2.0
            else:
                a = math.radians(self._PLANT_ANGLES[key])
                # Clear the town's ACTUAL edge on this bearing, not a nominal
                # circle — the boundary bulges by up to ~50% on some bearings.
                ring = max(self._extent * _edge_wobble(a) * 1.30 + 0.07, 0.34)
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
            site.visual_dx = offset[0] + sprite.get_width() / 2.0
            site.visual_dy = offset[1]
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
        """One straight corridor per plant to its nearest substation.

        Straight, not street-following: real transmission runs a cleared
        corridor cross-country, and the plants already sit outside the built
        edge, so the line only ever crosses fields and the fringe.
        """
        self._routes = []
        self._subs_used = []
        if not self._plants or not self._sub_sites:
            return
        subs = [(iso_xy(c, r)[0] + ox, iso_xy(c, r)[1] + oy) for c, r in self._sub_sites]
        used = set()
        for site in self._plants:
            start = self._takeoff(site.key, site.sx + ox, site.sy + oy)
            i = min(range(len(subs)),
                    key=lambda k: math.hypot(subs[k][0] - start[0],
                                             subs[k][1] - start[1]))
            used.add(i)
            path = street_route((site.col, site.row), self._sub_sites[i],
                                start, subs[i], (ox, oy))
            self._routes.append((site.key, i, path))
        # only substations something actually feeds get built
        self._subs_used = sorted(used)
        self._sub_screen = subs

    def _build_distribution(self, ox, oy):
        """Connect each feeder-sized building cluster to its nearest substation."""
        self._transformers = []
        self._distribution_flows = []
        self._service_flows = []
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
            self._distribution_flows.append(
                (index, Flow(route, cap=10,
                             seed=abs(hash(("tx", group_key))) & 0xFFFF)))
            # A couple of endpoint branches make the final hop into the blocks
            # legible without covering the whole city in animated lines.
            for end_col, end_row in buildings[::max(1, len(buildings) // 2)][:2]:
                ex, ey = iso_xy(end_col, end_row)
                end = (ex + ox + TW // 2, ey + oy + TH // 2)
                route = street_route((col, row), (end_col, end_row),
                                     point, end, (ox, oy))
                self._service_flows.append(
                    (index, Flow(route, cap=5,
                                 seed=abs(hash(("svc", end_col, end_row))) & 0xFFFF)))

    def _make_roads(self, rng):
        """Collect each street as CONTIGUOUS RUNS so vehicles have tarmac to
        drive on.

        Storing only a line's min and max is not enough: the river cuts gaps in
        the lattice, and a vehicle interpolating between the extremes drove
        straight across open water. Splitting each line at its gaps keeps
        traffic on the road, and costs one sort per line at bake time.
        """
        axes = {}
        for (col, row), (kind, _v) in self._tiles.items():
            if kind != "road":
                continue
            if col % ROAD_SPACING == 0:
                axes.setdefault((1, col), []).append(row)
            if row % ROAD_SPACING == 0:
                axes.setdefault((0, row), []).append(col)

        self._road_lines = []
        for (axis, idx), vals in axes.items():
            vals = sorted(set(vals))
            run_start = vals[0]
            for k in range(1, len(vals) + 1):
                if k == len(vals) or vals[k] != vals[k - 1] + 1:
                    if vals[k - 1] - run_start >= 4:
                        self._road_lines.append((axis, idx, run_start, vals[k - 1]))
                    if k < len(vals):
                        run_start = vals[k]
        self._vehicles = []
        if not self._road_lines:
            return
        for _ in range(MAX_VEHICLES):
            axis, line, lo, hi = rng.choice(self._road_lines)
            self._vehicles.append(_Vehicle(axis, line, lo, hi, rng))

    # -- baking ------------------------------------------------------------
    def _bake(self, rect, population, fleet):
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
        for (col, row) in sorted(self._tiles, key=lambda t: t[0] + t[1]):
            kind, extra = self._tiles[(col, row)]
            sx, sy = iso_xy(col, row)
            sx += ox
            sy += oy
            if not (-TW * 3 < sx < w + TW * 3 and -200 < sy < h + TH * 3):
                continue
            d = diamond(sx, sy)

            if kind == "water":
                c = srng.choice(WATER)
                pygame.draw.polygon(day, c, d)
                pygame.draw.polygon(night, shade(c, 0.30), d)
                continue
            if kind == "road":
                c = ROAD_ARTERIAL if extra else ROAD_LOCAL
                pygame.draw.polygon(day, c, d)
                pygame.draw.polygon(night, shade(c, 0.17), d)
                # Sparse lane paint gives the enlarged master tiles scale and
                # direction without turning every local street into striping.
                if extra and (col + row) % 3 == 0:
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
                if extra:      # arterials carry street lighting
                    ring = rings[self._ring_of(self._priority.get((col, row), 1.0))]
                    ring.fill((*LIGHT_WARM, 210), (sx + TW // 2, sy + TH // 2, 2, 1))
                continue

            if kind == "farm":
                # one crop per parcel, so fields read as cultivated blocks
                fk = (col // FIELD_SIZE, row // FIELD_SIZE)
                c = FIELDS[(hash(fk) >> 3) % len(FIELDS)]
            else:
                c = srng.choice(PARK if kind == "park" else GRASS)
            pygame.draw.polygon(day, c, d)
            pygame.draw.polygon(night, shade(c, 0.22), d)

            if kind in ("tree", "park") and (kind == "tree" or srng.random() < 0.55):
                spr, _ = tree(srng)
                self._blit_pair(day, night, spr, sx, sy)
                continue
            if kind != "bldg":
                continue

            spr, lights = BUILDERS[extra](srng)
            self._blit_pair(day, night, spr, sx, sy)
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
        self._route_transmission(ox, oy)
        grid = pygame.Surface((w, h), pygame.SRCALPHA)
        for i in self._subs_used:
            _substation(grid, *self._sub_screen[i])
        for _key, _i, path in self._routes:
            first = True
            for (x0, y0), (x1, y1) in zip(path, path[1:]):
                span = math.hypot(x1 - x0, y1 - y0)
                n = max(1, int(span / 46.0))
                towers = [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n)
                          for k in range(n + 1)]
                for a, b in zip(towers, towers[1:]):
                    _span(grid, (a[0], a[1] - 11), (b[0], b[1] - 11))
                for tx, ty in towers[1 if first else 0:]:
                    _pylon(grid, int(tx), int(ty))
                first = False
        day.blit(grid, (0, 0))
        grid.fill(NIGHT_MULT + (255,), None, pygame.BLEND_RGB_MULT)
        night.blit(grid, (0, 0))

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

        # One live flow per transmission route, then a visible distribution
        # graph from substations through neighbourhood transformers to blocks.
        self._flows = {(k, i): Flow(path, seed=abs(hash((k, i))) & 0xFFFF)
                       for k, i, path in self._routes}
        self._build_distribution(ox, oy)
        for _index, flow in self._distribution_flows:
            for a, b, _length in flow.segs:
                pygame.draw.line(detail_day["gameplay"], (82, 88, 92), a, b, 1)
        for _index, flow in self._service_flows:
            for a, b, _length in flow.segs:
                pygame.draw.line(detail_day["inspection"], (104, 110, 112), a, b, 1)
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

    def plant_anchors(self, rect):
        """Screen anchor per visible plant; off-screen sites pin to the edge."""
        if self.camera is None:
            return {}
        anchors = {}
        margin = 26
        for site in self._plants:
            sprite = getattr(site, "sprite", None)
            offset = getattr(site, "sprite_offset", None)
            if self.camera.zoom > 1 and sprite is not None and offset is not None:
                art_world = (site.sx + self._origin[0] + offset[0],
                             site.sy + self._origin[1] + offset[1])
                art_screen = self.camera.world_to_screen(art_world, rect)
                art_rect = pygame.Rect(round(art_screen[0]), round(art_screen[1]),
                                       sprite.get_width() * self.camera.zoom,
                                       sprite.get_height() * self.camera.zoom)
                # At close zoom, a sliver of a campus at the frame edge is not
                # enough context for a 148px control card. Require the artwork's
                # visual centre to be on camera; this removes orphaned edge pins
                # and their long diagonal leaders.
                if not rect.inflate(-72, -72).collidepoint(art_rect.center):
                    continue
            visual_dx = getattr(site, "visual_dx", 0.0)
            visual_dy = getattr(site, "visual_dy", 0.0)
            point = self.camera.world_to_screen(
                (site.sx + visual_dx + self._origin[0],
                 site.sy + visual_dy + self._origin[1]), rect)
            anchors[site.key] = (
                max(rect.left + margin, min(rect.right - margin, point[0])),
                max(rect.top + margin, min(rect.bottom - margin, point[1])),
            )
        return anchors

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

    def prepare(self, rect, state):
        """Ensure camera, world layers, and plant anchors exist for this frame."""
        population = state_population(state)
        fleet = tuple(sorted(s.key for s in state.sources if s.max_output_mw > 0))
        world_size = required_world_size(rect)
        key = (world_size, round(population / 5000.0), fleet)
        if key != self._key:
            self._key = key
            self._bake(rect, population, fleet)

    def draw(self, surface, rect, state, atmosphere=None):
        dt = 1.0 / 60.0
        self.t += dt
        self.prepare(rect, state)

        activity = activity_level(state.demand_level)
        served = served_fraction(state.fill_pct_display)
        over = overload_level(state.fill_pct_display, state.difficulty.meltdown)
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

        self._draw_lights(world, self._world_rect, activity, served, day)

        layer = self._overlay
        layer.fill((0, 0, 0, 0))
        self._draw_vehicles(layer, traffic_level(state.sim_hour, served), day)
        self._draw_transmission(layer, state, dt)
        self._draw_plants(layer, state, day)
        # danger_timer also runs on the BLACKOUT side of the band, so it only
        # means "this grid is cooking" while we are actually oversupplied.
        crisis = (_clamp01(state.danger_timer / max(0.1, state.difficulty.danger_grace))
                  if over > 0 else 0.0)
        self._update_fires(dt, over, crisis)
        if over > 0.04 or self._fires:
            self._draw_overload(layer, self._world_rect, over, crisis)
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

    def _draw_vehicles(self, layer, level, day):
        n = int(len(self._vehicles) * level * vehicle_density_for_zoom(self.camera.zoom))
        ox, oy = self._origin
        night = day < 0.35
        ax, ay = _VEH_ANCHOR
        for veh in self._vehicles[:n]:
            veh.pos += veh.speed * (1.0 / 60.0) * 6.0
            if veh.pos > veh.hi or veh.pos < veh.lo:
                veh.speed = -veh.speed
                veh.pos = max(veh.lo, min(veh.hi, veh.pos))
            col, row = ((veh.pos, veh.line) if veh.axis == 0
                        else (veh.line, veh.pos))
            if self._occluded(col, row):
                continue
            sx, sy = iso_xy(col, row)
            spr = _vehicle_sprite(veh.kind, veh.color,
                                  veh.axis * 2 + (veh.speed > 0), night)
            layer.blit(spr, (sx + ox + TW // 2 - ax, sy + oy + TH // 2 - ay))

    def _draw_transmission(self, layer, state, dt):
        """Blue pulses out along each plant's line, then on into the streets.

        Rate follows `actual_pct` — the ramped output, not what the player just
        asked for — so a plant that has been throttled back keeps its line lit
        until it has actually wound down, which is the lag the whole game is
        about. A plant at zero leaves a dark but still-drawn line: a dead
        circuit is still a circuit.
        """
        by_key = {s.key: s for s in state.sources}
        load = {}
        for (key, i), flow in self._flows.items():
            src = by_key.get(key)
            out = 0.0 if src is None or src.max_output_mw <= 0 else src.actual_pct
            flow.update_and_draw(layer, out, dt)
            got, cap = load.get(i, (0.0, 0.0))
            mw = src.max_output_mw if src else 0.0
            load[i] = (got + out * mw, cap + mw)
        if self.camera.zoom < 2:
            return
        served = served_fraction(state.fill_pct_display)
        branch_levels = {}
        for index, flow in self._distribution_flows:
            transformer = self._transformers[index]
            got, cap = load.get(transformer.sub_index, (0.0, 0.0))
            upstream = got / cap if cap > 0 else 0.0
            level = distribution_level(transformer.priority, served, upstream)
            branch_levels[index] = level
            flow.update_and_draw(layer, level, dt)
        for index, flow in self._service_flows:
            flow.update_and_draw(layer, branch_levels.get(index, 0.0), dt)

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

    def _update_fires(self, dt, over, crisis):
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

        if over <= FIRE_FROM and crisis <= 0.0:
            return
        self._ignite_acc += _ignite_rate(over, crisis) * dt
        cap = _max_fires(over, crisis)
        reach = _fire_reach(over, crisis)
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

    def _draw_overload(self, layer, rect, over, crisis):
        """Oversupply: the grid cooking itself.

        The full-rect wash keeps its ~0.25 Hz envelope at EVERY severity —
        `crisis` raises its peak alpha and nothing else. Speeding a large-area
        pulse up with severity is the intuitive move and it is exactly the
        photosensitive-seizure trigger this file refuses to ship. Flames and
        arcs may flicker faster because they are a few pixels each.
        """
        pulse = 0.5 + 0.5 * math.sin(self.t * 1.6)
        a = int((46 + 26 * crisis) * over * (0.55 + 0.45 * pulse))
        if a > 3:
            wash = pygame.Surface(rect.size, pygame.SRCALPHA)
            wash.fill((*LIGHT_OVERLOAD, a))
            layer.blit(wash, (0, 0))

        for f in self._fires:
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
        if crisis > 0.2 and self._arc_points:
            self._arc_acc += crisis * 3.0 * (1.0 / 60.0)
            while self._arc_acc >= 1.0 and len(self._arcs) < 3:
                self._arc_acc -= 1.0
                ax, ay = self._rng.choice(self._arc_points)
                pts = [(ax + self._rng.randint(-5, 5), ay + self._rng.randint(-7, 1))
                       for _ in range(4)]
                self._arcs.append([0.0, pts])
        for arc in self._arcs:
            arc[0] += 1.0 / 60.0
            if arc[0] < 0.12:
                pygame.draw.lines(layer, (214, 236, 255), False, arc[1], 1)
                pygame.draw.circle(layer, (180, 214, 255), arc[1][0], 2, 1)
        self._arcs = [a for a in self._arcs if a[0] < 0.12]

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
