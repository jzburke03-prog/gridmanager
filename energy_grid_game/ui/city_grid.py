"""Overhead ("satellite") view of the city grid — the primary instrument of the
game, replacing the isometric water tank from 1.0.

Modelled on real aerial imagery of a sprawling metro (Atlanta), which has a very
specific structure that a naive implementation misses in two ways:

  * Streets are NOT scratches. There is a hierarchy — a few smooth highways, a
    ring, radial arterials — and, between them, a fabric of NEIGHBOURHOODS, each
    a small street grid with its own local orientation. That local coherence is
    what makes it read as a city instead of random lines.
  * Daytime ground is NOT blobs. It is a fine mottled canopy at the scale of
    individual lots, speckled with countless small bright roofs, densest along
    the road corridors. Big colour patches read as camouflage.

Two inputs drive the lighting, and they are deliberately NOT the same thing
(see SPEC-1.1 §1.4):

    activity = how brightly the city burns   (demand curve / time of day)
    served   = how much of it is energised   (supply / demand)

`activity` scales brightness uniformly across the whole metro. Night dims every
town at once; it does not shrink the city into its core. Each downtown — the
metro's and every satellite town's own — keeps a higher floor, so cores stay
livelier through the small hours.

`served` is the geographic one: falling short sheds load from the fringe inward,
downtown last, which is how load-shedding is actually prioritised.

Multiplying these into a single number was a modelling error. It left outlying
towns completely dark at 04:00 on a perfectly supplied grid — a town does not
stop existing because it is late.

PERFORMANCE. Detail this fine cannot be redrawn per frame. Three cached layers,
all rebuilt only on resize:
  * `_night_base` / `_day_base` — full-frame ground, cross-faded by sun angle,
    which also makes the day/night transition continuous instead of stepped.
  * per-neighbourhood lit sprites — pre-rendered once, then blitted with a single
    alpha each. ~150 small blits a frame instead of ~2000 line draws.

All severity animation is slow, smooth, low-contrast easing, capped near 1 Hz and
well under 3 Hz. No hard on/off flashing over large areas: large-area strobe is a
real photosensitive-seizure trigger. Do not "improve" this into snappier flicker.
"""
import bisect
import math
import random

import numpy as np
import pygame

from ui import assets
from ui.time_of_day import daylight, get_time_of_day_colors

# -- readout label (unchanged from 1.0) -------------------------------------
LABEL_DIM = (150, 158, 176)
LABEL_OK = (100, 220, 140)
LABEL_WARN = (240, 170, 80)
LABEL_BAD = (230, 90, 90)

# -- palette ----------------------------------------------------------------
GROUND_NIGHT = (7, 7, 9)
ROAD_NIGHT = (21, 20, 23)

# Daytime canopy ramp: dense dark forest through scrubby green to dry open land.
# Deliberately low-saturation and dark — aerial green is nothing like camo green.
CANOPY_DARK = (22, 30, 22)
CANOPY_MID = (37, 47, 33)
CANOPY_LIGHT = (78, 82, 56)

ROAD_DAY_MAJOR = (188, 190, 188)   # concrete: highways and arterials
ROAD_DAY_LOCAL = (128, 128, 126)   # asphalt: neighbourhood streets
ROOF_DAY = ((176, 174, 170), (150, 150, 148), (198, 196, 192), (132, 130, 128))
ROOF_CORE = ((214, 214, 212), (232, 232, 230), (188, 190, 192))

LIGHT_WARM = (255, 168, 66)        # sodium-vapour amber, the dominant city light
LIGHT_HOT = (255, 232, 186)        # near-white, densest core and interchanges
LIGHT_OVERLOAD = (255, 72, 44)
FIRE = (255, 138, 48)
SMOKE = (118, 112, 122)
TRAFFIC_WARM = (255, 236, 190)
TRAFFIC_COOL = (176, 206, 244)
TRAFFIC_GLINT = (255, 255, 250)   # sun off metal and glass at midday

# -- tunables ---------------------------------------------------------------
AWAKE_MIN = 0.15        # fraction of the network lit at the demand trough, fully supplied
TRAFFIC_MIN = 0.08      # roads are never completely still, even in blackout
CORE_BIAS = 0.72        # how strongly lighting order follows distance from downtown
N_HIGHWAYS = 5
N_ARTERIALS = 9
N_HOODS = 320
SPRAWL_SCALE = 0.19     # exponential falloff of development from downtown
RING_RADII = (0.21, 0.38)
CORE_R = 0.05
MAX_VEHICLES = 2400     # spread over whole routes, so every road carries some
TRAIL_PX = 0.0055       # motion streak behind each vehicle, normalised units
DAYLIGHT_MAX_ALPHA = 34   # sky colour cast ceiling; higher washes the frame out


def _clamp01(v):
    return max(0.0, min(1.0, v))


def activity_level(demand_level: float, awake_min: float = AWAKE_MIN) -> float:
    """How BRIGHT the city burns, 0..1, from the demand curve alone.

    Time of day dims the whole metro uniformly — every town, not just downtown.
    At 04:00 the suburbs are asleep but they are still connected and still lit;
    they do not geographically vanish into the core.
    """
    return awake_min + (1.0 - awake_min) * _clamp01(demand_level)


def served_fraction(fill_pct: float) -> float:
    """What SHARE of the network is energised at all, 0..1, from supply alone.

    Deliberately separate from activity_level. Running short of generation sheds
    load geographically — the fringe drops first, downtown last — which is a
    different thing from the city going quiet at night, and conflating the two
    left outlying towns permanently dark no matter how well supplied they were.
    """
    return _clamp01(fill_pct)


def lit_fraction(demand_level: float, fill_pct: float, awake_min: float = AWAKE_MIN) -> float:
    """Total share of the city actually alight — brightness times reach.

    Retained as the single "how lit is the city" summary; the renderer uses the
    two factors above independently.
    """
    return activity_level(demand_level, awake_min) * served_fraction(fill_pct)


def overload_level(fill_pct: float, meltdown: float) -> float:
    """0..1 how far past balanced the grid is, normalised so 1.0 lands exactly on
    the difficulty's meltdown line.

    Deliberately not a fixed percentage: `meltdown` spans 1.15 (Expert) to 2.10
    (Easy), so a hardcoded threshold would show a city on fire at a supply level
    that is comfortably safe on one tier and show nothing at all right up to the
    moment the run ends on another.
    """
    if fill_pct <= 1.0:
        return 0.0
    return min(1.0, (fill_pct - 1.0) / max(0.01, meltdown - 1.0))


# Traffic by hour of day. Anchors, linearly interpolated and wrapped at 24.
# Twin rush-hour peaks, a high midday plateau, a steep fall after 23:00 and a
# deep 01:00-05:00 trough. Cars do not run on the grid, so this is a function of
# the clock, not of supply.
_TRAFFIC_BY_HOUR = [
    (0.0, 0.20), (1.0, 0.09), (3.0, 0.05), (5.0, 0.10), (6.5, 0.34),
    (8.0, 0.92), (9.0, 1.00), (10.0, 0.88), (12.0, 0.82), (14.0, 0.80),
    (16.0, 0.94), (17.0, 1.00), (18.0, 0.92), (20.0, 0.62), (22.0, 0.44),
    (23.0, 0.34), (24.0, 0.20),
]


def traffic_level(sim_hour: float, served: float = 1.0,
                  traffic_min: float = TRAFFIC_MIN) -> float:
    """Road activity 0..1 for an hour of the day.

    Shaped by the clock rather than by the grid: a blackout does not stop cars.
    A badly shed grid still damps it somewhat — dark signals, closed businesses —
    but never below the floor, because roads are never completely still.
    """
    h = sim_hour % 24.0
    for (h0, v0), (h1, v1) in zip(_TRAFFIC_BY_HOUR, _TRAFFIC_BY_HOUR[1:]):
        if h0 <= h <= h1:
            t = (h - h0) / (h1 - h0)
            base = v0 + (v1 - v0) * (t * t * (3.0 - 2.0 * t))   # smoothstep
            break
    else:
        base = _TRAFFIC_BY_HOUR[0][1]
    return max(traffic_min, base * (0.55 + 0.45 * _clamp01(served)))


def _lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class _Seg:
    """A major road: highway, ring or arterial. Normalised 0..1 coordinates."""
    __slots__ = ("a", "b", "width", "priority", "phase")

    def __init__(self, a, b, width, priority=0.0, phase=0.0):
        self.a = a
        self.b = b
        self.width = width
        self.priority = priority
        self.phase = phase

    @property
    def mid(self):
        return ((self.a[0] + self.b[0]) * 0.5, (self.a[1] + self.b[1]) * 0.5)


class _Hood:
    """A neighbourhood: a small street grid with its own orientation.

    This is the unit of fine detail. Its streets are baked into the day layer
    once, and its night appearance is pre-rendered to a sprite so lighting it
    costs one blit rather than a dozen line draws.
    """
    __slots__ = ("pos", "rx", "ry", "angle", "spacing", "priority", "phase",
                 "streets", "sprite_warm", "sprite_hot", "blit_at", "core_weight")

    def __init__(self, pos, rx, ry, angle, spacing, phase, core_weight=0.0):
        self.pos = pos
        self.rx = rx
        self.ry = ry
        self.angle = angle
        self.spacing = spacing
        self.phase = phase
        # 0..1 how much of a downtown this sits in — its own town's centre
        # counts, not just the metro's. Keeps activity higher in every core.
        self.core_weight = core_weight
        self.priority = 0.0
        self.streets = []          # normalised (a, b) pairs
        self.sprite_warm = None
        self.sprite_hot = None
        self.blit_at = (0, 0)


class _Route:
    """A whole road end to end — a highway, a ring, an arterial.

    Traffic runs along routes, never along individual segments. Segment-bound
    vehicles put cars on a handful of disconnected stretches and left the roads
    beside them visibly empty, which no real network ever looks like.
    """
    __slots__ = ("points", "cum", "total", "importance")

    def __init__(self, points, importance):
        self.points = points
        self.cum = [0.0]
        run = 0.0
        for a, b in zip(points, points[1:]):
            run += math.hypot(b[0] - a[0], b[1] - a[1])
            self.cum.append(run)
        self.total = max(1e-6, run)
        self.importance = importance

    def point_at(self, f):
        d = _clamp01(f) * self.total
        i = bisect.bisect_right(self.cum, d) - 1
        i = min(max(i, 0), len(self.points) - 2)
        a, b = self.points[i], self.points[i + 1]
        seg = self.cum[i + 1] - self.cum[i]
        t = (d - self.cum[i]) / seg if seg > 1e-9 else 0.0
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


class _Vehicle:
    __slots__ = ("route", "pos", "speed", "warm")

    def __init__(self, route, pos, speed, warm):
        self.route = route
        self.pos = pos
        self.speed = speed
        self.warm = warm


class CityGrid:
    def __init__(self, font, font_label=None):
        self.font = font
        self.font_label = font_label or font
        self.t = 0.0
        self._rng = random.Random(2024)
        self.segments, self.nodes, self.routes = self._make_majors()
        self.hoods, self.towns = self._make_hoods()
        self._connect_towns()
        self._assign_priorities()
        self.vehicles = self._make_vehicles()

        self._layer_size = None
        self._night_base = None
        self._day_base = None
        self._overlay = None

    # -- layout: major roads ------------------------------------------------
    def _make_majors(self):
        """Highways, ring roads and arterials.

        Curvature is a smooth per-road bias, NOT a per-step random walk. A random
        walk produces the jittery scratches this replaced: real highways sweep.
        """
        rng = self._rng
        cx, cy = 0.5, 0.5
        segs = []
        routes = []
        nodes = [((cx, cy), 1.0, 0.0)]      # downtown always lights first

        def polar(r, ang):
            return (cx + math.cos(ang) * r, cy + math.sin(ang) * r)

        def chain(points, width, importance=1.0):
            for p, q in zip(points, points[1:]):
                segs.append(_Seg(p, q, width, phase=rng.random() * math.tau))
            routes.append(_Route(points, importance))

        # Highways: long smooth sweeps crossing the metro. Each is displaced
        # perpendicular to its own heading so they do NOT all converge on
        # downtown — every highway through the exact centre reads as a drawn
        # asterisk, which is the single most artificial thing this can do.
        for i in range(N_HIGHWAYS):
            ang = (i / N_HIGHWAYS) * math.pi + rng.uniform(-0.25, 0.25)
            curve = rng.uniform(-0.30, 0.30)
            miss = rng.uniform(-0.17, 0.17)      # how far it passes from downtown
            nx, ny = -math.sin(ang) * miss, math.cos(ang) * miss
            pts = []
            for s in range(-26, 27):
                t = s / 26.0
                bend = curve * t * t * (1 if t > 0 else -1)
                r = abs(t) * 0.95
                p = polar(r, (ang + bend) if t >= 0 else (ang + bend + math.pi))
                pts.append((p[0] + nx, p[1] + ny))
            chain(pts, 3.2, importance=3.0)

        # Ring roads as irregular POLYGONS, not curves. A real beltway (I-285)
        # is a sequence of long straight runs meeting at distinct angles; drawing
        # it as any kind of smooth closed curve — circle, ellipse, lobed sinusoid
        # — reads immediately as a drawn shape rather than a road.
        for ring_r in RING_RADII:
            n_vertices = rng.randint(9, 13)
            verts = []
            for i in range(n_vertices):
                ang = (i / n_vertices) * math.tau + rng.uniform(-0.16, 0.16)
                verts.append(polar(ring_r * rng.uniform(0.80, 1.20), ang))
            verts.append(verts[0])          # close the loop

            # walk the polygon, breaking it into runs with occasional gaps
            i = 0
            while i < len(verts) - 1:
                run_len = rng.randint(2, 4)
                pts = verts[i:i + run_len + 1]
                if len(pts) < 2:
                    break
                # subdivide each straight run so lighting has granularity along it
                dense = []
                for a, b in zip(pts, pts[1:]):
                    for s in range(4):
                        dense.append((a[0] + (b[0] - a[0]) * s / 4,
                                      a[1] + (b[1] - a[1]) * s / 4))
                dense.append(pts[-1])
                chain(dense, 2.3, importance=1.6)
                for v in pts:
                    nodes.append((v, 0.35, 0.26 + ring_r))
                i += run_len + (1 if rng.random() < 0.25 else 0)   # occasional gap

        # Arterials. Origins are scattered around the core rather than all
        # starting from one point — a perfect radial fan plus a ring is what
        # made the whole thing read as concentric.
        for i in range(N_ARTERIALS):
            ang = (i / N_ARTERIALS) * math.tau + rng.uniform(-0.28, 0.28)
            curve = rng.uniform(-0.6, 0.6)
            reach = rng.uniform(0.36, 0.74)
            start_r = rng.uniform(0.0, CORE_R * 2.6)
            start_a = rng.uniform(0, math.tau)
            ox, oy = math.cos(start_a) * start_r, math.sin(start_a) * start_r
            pts = []
            steps = 16
            for s in range(steps + 1):
                t = s / steps
                p = polar(CORE_R + (reach - CORE_R) * t, ang + curve * t * t)
                # the offset fades out along the road, so it still heads outward
                pts.append((p[0] + ox * (1 - t), p[1] + oy * (1 - t)))
            chain(pts, 1.9, importance=1.0)

        # Downtown street tangle.
        for _ in range(26):
            a = rng.uniform(0, math.tau)
            chain([polar(rng.uniform(0, CORE_R * 1.3), a),
                   polar(rng.uniform(0, CORE_R * 1.3), a + rng.uniform(-1.4, 1.4))], 2.0,
                  importance=0.5)
        return segs, nodes, routes

    # -- layout: neighbourhoods --------------------------------------------
    def _make_hoods(self):
        """Urban sprawl: a continuous density gradient outward from downtown,
        plus discrete satellite towns beyond it.

        Sprawl is not a scatter of patches around the beltway. It starts at the
        centre and diffuses — packed and overlapping enough near the core to form
        one continuous fabric, thinning steadily outward. Separately, real metros
        have their own towns past the perimeter (Marietta, Lawrenceville) that
        are dense in their own right with open country between.
        """
        rng = self._rng
        cx, cy = 0.5, 0.5
        hoods = []

        def add(x, y, dist, tightness=1.0, core_weight=0.0):
            # lots get bigger and streets further apart the further out you go
            size = rng.uniform(0.016, 0.040) * (0.55 + dist * 1.5) * tightness
            hood = _Hood((x, y), size, size * rng.uniform(0.55, 0.95),
                         rng.uniform(0, math.pi),
                         rng.uniform(0.0040, 0.0060) * (0.85 + dist),
                         rng.random() * math.tau, core_weight)
            hood.streets = self._hood_streets(hood, rng)
            hoods.append(hood)

        # --- the sprawl itself: exponential falloff from the origin ---------
        for _ in range(int(N_HOODS * 0.82)):
            r = -SPRAWL_SCALE * math.log(max(1e-6, 1.0 - rng.random()))
            if r > 0.85:
                continue
            ang = rng.uniform(0, math.tau)
            # squashed vertically so the metro fills a wide frame
            add(cx + math.cos(ang) * r, cy + math.sin(ang) * r * 0.72, r,
                core_weight=_clamp01(1.0 - r / 0.22))

        # --- satellite towns: dense pockets out past the perimeter ----------
        towns = []
        for _ in range(rng.randint(6, 8)):
            ang = rng.uniform(0, math.tau)
            r = rng.uniform(0.40, 0.80)
            tx = cx + math.cos(ang) * r
            ty = cy + math.sin(ang) * r * 0.72
            towns.append((tx, ty))
            for _ in range(rng.randint(9, 17)):
                d = abs(rng.gauss(0, 0.032))
                a2 = rng.uniform(0, math.tau)
                # A town has its own downtown. Without this, outlying centres
                # never brighten and sit dead in an otherwise busy metro.
                add(tx + math.cos(a2) * d, ty + math.sin(a2) * d * 0.8,
                    r * 0.55, tightness=0.8,
                    core_weight=_clamp01(1.0 - d / 0.030) * 0.85)
        return hoods, towns

    @staticmethod
    def _hood_streets(hood, rng):
        """A local grid at the hood's own angle. Coherent orientation within a
        neighbourhood, different between neighbourhoods — that contrast is the
        whole reason this reads as a built environment."""
        ca, sa = math.cos(hood.angle), math.sin(hood.angle)
        ox, oy = hood.pos
        out = []

        def place(u, v):
            return (ox + u * ca - v * sa, oy + u * sa + v * ca)

        # Clip the grid to an ellipse with a jittered edge. A rectangular grid
        # leaves a hard rotated-rectangle silhouette, and a field of those reads
        # as scattered tiles rather than as neighbourhoods growing into each
        # other, which is the single most artificial thing the day layer showed.
        def half(extent, other, other_extent):
            k = 1.0 - (other / other_extent) ** 2 if other_extent else 0.0
            if k <= 0:
                return 0.0
            return extent * math.sqrt(k) * rng.uniform(0.80, 1.06)

        n_long = max(2, int(hood.ry * 2 / hood.spacing))
        for i in range(n_long + 1):
            v = -hood.ry + i * (hood.ry * 2 / max(1, n_long))
            u_max = half(hood.rx, v, hood.ry)
            if u_max <= hood.spacing:
                continue
            out.append((place(-u_max, v), place(u_max, v)))
        n_cross = max(2, int(hood.rx * 2 / (hood.spacing * 1.5)))
        for i in range(n_cross + 1):
            u = -hood.rx + i * (hood.rx * 2 / max(1, n_cross))
            v_max = half(hood.ry, u, hood.rx)
            if v_max <= hood.spacing:
                continue
            out.append((place(u, -v_max), place(u, v_max)))
        return out

    def _connect_towns(self):
        """Run roads out to the satellite towns, and cross-link neighbouring
        arterials.

        Outlying towns floating unconnected is what made some roads past the
        perimeter look like stubs going nowhere: the network stopped at the
        beltway while development carried on well beyond it.
        """
        rng = self._rng
        cx, cy = 0.5, 0.5

        def bend(a, b, sag, steps=10):
            """A gently bowed line, so connectors don't read as ruler-drawn."""
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            nx, ny = -(b[1] - a[1]) * sag, (b[0] - a[0]) * sag
            ctrl = (mx + nx, my + ny)
            pts = []
            for s in range(steps + 1):
                t = s / steps
                u = 1 - t
                pts.append((u * u * a[0] + 2 * u * t * ctrl[0] + t * t * b[0],
                            u * u * a[1] + 2 * u * t * ctrl[1] + t * t * b[1]))
            return pts

        def add(points, width, importance):
            for p, q in zip(points, points[1:]):
                self.segments.append(_Seg(p, q, width, phase=rng.random() * math.tau))
            self.routes.append(_Route(points, importance))

        # every town gets a spur inward, plus sometimes a link to a neighbour
        for tx, ty in self.towns:
            ang = math.atan2(ty - cy, tx - cx)
            inner = (cx + math.cos(ang) * RING_RADII[1] * rng.uniform(0.85, 1.1),
                     cy + math.sin(ang) * RING_RADII[1] * 0.72 * rng.uniform(0.85, 1.1))
            add(bend((tx, ty), inner, rng.uniform(-0.16, 0.16)), 2.0, 1.4)
            self.nodes.append(((tx, ty), 0.45, 0.0))     # the town's own centre
            if rng.random() < 0.55 and len(self.towns) > 1:
                other = rng.choice([t for t in self.towns if t != (tx, ty)])
                add(bend((tx, ty), other, rng.uniform(-0.22, 0.22)), 1.5, 0.7)

        # chords between arterials, so the outer network is a mesh not a fan
        outer = [s for s in self.segments if s.width <= 2.0
                 and math.hypot(s.mid[0] - cx, s.mid[1] - cy) > RING_RADII[0]]
        for _ in range(14):
            if len(outer) < 2:
                break
            a, b = rng.choice(outer).mid, rng.choice(outer).mid
            if 0.10 < math.hypot(a[0] - b[0], a[1] - b[1]) < 0.42:
                add(bend(a, b, rng.uniform(-0.25, 0.25), steps=8), 1.4, 0.6)

    def _assign_priorities(self):
        """Rank-normalise so priority is uniform on [0, 1] across everything that
        lights. The raw core-distance score is heavily clustered, and comparing
        it against lit_frac directly lit ~1% of the city when it claimed 15%.
        Ranking preserves the lighting ORDER while making lit_frac mean the
        fraction it says."""
        rng = self._rng
        cx, cy = 0.5, 0.5
        items = []
        for s in self.segments:
            mx, my = s.mid
            dist = min(1.0, math.hypot(mx - cx, my - cy) / 0.62)
            trunk = (s.width - 1.5) / 2.0 * 0.34      # highways outlast lanes
            items.append((CORE_BIAS * dist - trunk + (1 - CORE_BIAS) * rng.random(), s))
        for h in self.hoods:
            dist = min(1.0, math.hypot(h.pos[0] - cx, h.pos[1] - cy) / 0.62)
            # neighbourhoods shed before the trunks that feed them
            items.append((CORE_BIAS * dist + 0.16 + (1 - CORE_BIAS) * rng.random(), h))
        items.sort(key=lambda kv: kv[0])
        # Divide by the COUNT, not count-1: the renderer tests `priority >= served`,
        # so a top priority of exactly 1.0 would leave the last item permanently
        # dark even on a fully supplied grid.
        n = max(1, len(items))
        for rank, (_score, obj) in enumerate(items):
            obj.priority = rank / n
        self.segments.sort(key=lambda s: s.priority)
        self.hoods.sort(key=lambda h: h.priority)

    def _make_vehicles(self):
        """Distribute traffic across every route, weighted by importance and
        length, and interleave the list so thinning it for a low traffic level
        thins the whole network evenly instead of emptying whole roads.

        Speed is normalised by route length so a car crosses the screen at the
        same rate whatever road it is on — otherwise short routes flicker and
        long ones crawl.
        """
        rng = self._rng
        if not self.routes:
            return []
        weights = [r.importance * r.total for r in self.routes]
        picks = rng.choices(self.routes, weights=weights, k=MAX_VEHICLES)
        vehicles = [_Vehicle(r, rng.random(),
                             rng.uniform(0.020, 0.045) / r.total
                             * (1 if rng.random() < 0.5 else -1),
                             rng.random() < 0.72)
                    for r in picks]
        rng.shuffle(vehicles)
        return vehicles

    # -- cached layers ------------------------------------------------------
    def _px(self, p, size):
        return (int(p[0] * size[0]), int(p[1] * size[1]))

    def _ensure_layers(self, size):
        if self._layer_size == size:
            return
        self._layer_size = size
        self._night_base = self._build_night(size)
        self._day_base = self._build_day(size)
        self._build_hood_sprites(size)
        self._overlay = pygame.Surface(size, pygame.SRCALPHA)

    def _build_night(self, size):
        base = pygame.Surface(size)
        base.fill(GROUND_NIGHT)
        for s in self.segments:
            pygame.draw.line(base, ROAD_NIGHT, self._px(s.a, size), self._px(s.b, size),
                             max(1, int(s.width)))
        return base

    def _canopy(self, size):
        """Mottled tree cover, generated as multi-octave noise rather than drawn
        blobs. Blobs at any size read as camouflage; noise reads as canopy."""
        w, h = size
        rs = np.random.RandomState(2024)

        def octave(divisor):
            sw, sh = max(2, w // divisor), max(2, h // divisor)
            a = (rs.rand(sw, sh) * 255).astype(np.uint8)
            surf = pygame.surfarray.make_surface(np.repeat(a[:, :, None], 3, axis=2))
            return pygame.surfarray.array3d(
                pygame.transform.smoothscale(surf, size))[:, :, 0].astype(np.float32)

        # Weighted toward the FINE octaves. Tree canopy from the air is grain at
        # the scale of individual crowns; coarse-dominant noise makes broad soft
        # patches of a few greens, which is the definition of camouflage.
        v = (0.10 * octave(22) + 0.16 * octave(8)
             + 0.28 * octave(3) + 0.46 * octave(2)) / 255.0
        v = np.clip((v - 0.34) / 0.34, 0.0, 1.0)
        # Gamma pushes most of the frame into the dark end: real canopy is a
        # narrow band of dark green, with pale open ground genuinely rare rather
        # than a third of the range.
        v = v ** 1.75

        lo = np.array(CANOPY_DARK, dtype=np.float32)
        mid = np.array(CANOPY_MID, dtype=np.float32)
        hi = np.array(CANOPY_LIGHT, dtype=np.float32)
        t = v[:, :, None]
        low_half = lo + (mid - lo) * np.clip(t * 1.6, 0, 1)
        high_half = mid + (hi - mid) * np.clip((t - 0.62) / 0.38, 0, 1)
        rgb = np.where(t < 0.62, low_half, high_half)
        return pygame.surfarray.make_surface(rgb.astype(np.uint8))

    def _build_day(self, size):
        """The daylit city: canopy, then neighbourhood streets and roofs, then
        the major roads on top. Built once — it is far too detailed for a frame
        budget, and it is what makes noon look like an aerial photograph."""
        rng = random.Random(7)
        day = self._canopy(size)
        w, h = size

        for hood in self.hoods:
            for a, b in hood.streets:
                pygame.draw.line(day, ROAD_DAY_LOCAL, self._px(a, size),
                                 self._px(b, size), 1)
            # roofs and lots crowding the streets: the fine bright speckle that
            # separates a built area from open ground at this scale
            for a, b in hood.streets:
                steps = max(2, int(math.hypot((b[0] - a[0]) * w, (b[1] - a[1]) * h) / 5))
                for i in range(steps):
                    t = (i + rng.random()) / steps
                    px = int((a[0] + (b[0] - a[0]) * t) * w) + rng.randint(-3, 3)
                    py = int((a[1] + (b[1] - a[1]) * t) * h) + rng.randint(-3, 3)
                    if rng.random() < 0.55:
                        day.fill(rng.choice(ROOF_DAY), (px, py, rng.randint(1, 2),
                                                        rng.randint(1, 2)))

        for s in self.segments:
            pygame.draw.line(day, ROAD_DAY_MAJOR, self._px(s.a, size),
                             self._px(s.b, size), max(1, int(s.width)))

        # downtown: a tight mass of bright towers, not a diffuse glow
        cx, cy = w // 2, h // 2
        for _ in range(900):
            ang = rng.uniform(0, math.tau)
            r = rng.random() ** 0.6 * CORE_R * 1.9
            px = int(cx + math.cos(ang) * r * w)
            py = int(cy + math.sin(ang) * r * h)
            day.fill(rng.choice(ROOF_CORE), (px, py, rng.randint(1, 3), rng.randint(1, 3)))
        return day

    def _build_hood_sprites(self, size):
        """Pre-render each neighbourhood's night appearance so lighting it costs
        one blit. Two colour variants — amber normally, red under overload —
        cross-faded, which avoids per-frame recolouring entirely.

        Crucially this is NOT the street grid drawn in light. At this scale a
        real night image shows only the major roads as distinct lines; the
        neighbourhoods between them are a soft mottled glow speckled with
        individual lights. Drawing their grids literally produced an orange
        chain-link mesh that looked nothing like a city.
        """
        w, h = size
        rng = random.Random(11)
        for hood in self.hoods:
            rx = max(3, int(hood.rx * w) + 6)
            ry = max(3, int(hood.ry * h) + 6)
            sw, sh = rx * 2, ry * 2
            hood.blit_at = (int(hood.pos[0] * w) - rx, int(hood.pos[1] * h) - ry)

            # fixed speckle positions, denser toward the middle of the hood
            dots = []
            for _ in range(int(rx * ry * 0.05) + 8):
                u = rng.gauss(0, 0.42)
                v = rng.gauss(0, 0.42)
                if abs(u) > 1 or abs(v) > 1:
                    continue
                dots.append((int(rx + u * rx), int(ry + v * ry),
                             rng.choice((1, 1, 1, 2))))

            def render(color):
                surf = pygame.Surface((sw, sh), pygame.SRCALPHA)
                # soft elliptical haze: the diffuse glow of a lit suburb
                for i in range(7, 0, -1):
                    f = i / 7.0
                    pygame.draw.ellipse(
                        surf, (*color, int(13 * (1.0 - f) + 5)),
                        pygame.Rect(rx - rx * f, ry - ry * f, rx * 2 * f, ry * 2 * f))
                for dx, dy, r in dots:
                    pygame.draw.circle(surf, (*color, 205), (dx, dy), r)
                return surf

            hood.sprite_warm = render(LIGHT_WARM)
            hood.sprite_hot = render(LIGHT_OVERLOAD)

    # -- draw --------------------------------------------------------------
    def draw(self, surface, rect, state):
        """Render the whole city. `rect` is the full region the old tank occupied."""
        dt = 1.0 / 60.0
        self.t += dt
        self._ensure_layers(rect.size)

        activity = activity_level(state.demand_level)
        served = served_fraction(state.fill_pct_display)
        lit = activity * served
        over = overload_level(state.fill_pct_display, state.difficulty.meltdown)
        day = daylight(state.sim_hour)

        # Continuous cross-fade rather than stepped: no rebuild, no hitch.
        surface.blit(self._night_base, rect.topleft)
        if day > 0.004:
            self._day_base.set_alpha(int(255 * day))
            surface.blit(self._day_base, rect.topleft)
        if day > 0.02:
            _top, bottom = get_time_of_day_colors(state.sim_hour)
            wash = pygame.Surface(rect.size, pygame.SRCALPHA)
            wash.fill((*bottom, int(DAYLIGHT_MAX_ALPHA * day)))
            surface.blit(wash, rect.topleft)

        layer = self._overlay
        layer.fill((0, 0, 0, 0))
        self._draw_lights(layer, rect, activity, served, over, day)
        self._draw_traffic(layer, rect, traffic_level(state.sim_hour, served), dt, day)
        if over > 0.04:
            self._draw_overload(layer, rect, over)
        surface.blit(layer, rect.topleft)

    def _draw_lights(self, layer, rect, activity, served, over, day):
        """`activity` is brightness (time of day, uniform across the metro);
        `served` is reach (supply, sheds the fringe first). Keeping them separate
        is what lets an outlying town be dim at 4 AM but never dead."""
        # Daylight drowns streetlights out in reality; keep a floor so the
        # supply readout never disappears at midday. A deliberate departure —
        # how much of the city is lit IS the instrument.
        strength = 1.0 - 0.44 * day
        if served <= 0 or activity <= 0:
            return

        # neighbourhoods: one or two blits each, never per-street line draws
        for hood in self.hoods:
            if hood.priority >= served:
                break                      # sorted, so the rest are shed too
            headroom = (served - hood.priority) / max(0.02, served)
            dim = 0.0
            if headroom < 0.3:
                wob = 0.5 + 0.5 * math.sin(self.t * 0.9 + hood.phase)
                dim = (1.0 - headroom / 0.3) * wob * 0.65
            glow = 0.0
            if over > 0:
                glow = min(1.0, over * (0.5 + 0.5 * (0.5 + 0.5 * math.sin(
                    self.t * 0.7 + hood.phase))))
            # Downtowns — the metro's and each town's own — stay livelier through
            # the small hours instead of dimming with everywhere else.
            local = activity + (1.0 - activity) * hood.core_weight * 0.55
            a = 255 * strength * local * max(0.12, 1.0 - dim)
            if a < 4:
                continue
            hood.sprite_warm.set_alpha(int(a * (1.0 - glow)))
            layer.blit(hood.sprite_warm, hood.blit_at)
            if glow > 0.02:
                hood.sprite_hot.set_alpha(int(a * glow))
                layer.blit(hood.sprite_hot, hood.blit_at)

        lit_frac = served
        for s in self.segments:
            if s.priority >= lit_frac:
                break
            headroom = (lit_frac - s.priority) / max(0.02, lit_frac)
            dim = 0.0
            if headroom < 0.3:
                wob = 0.5 + 0.5 * math.sin(self.t * 0.9 + s.phase)
                dim = (1.0 - headroom / 0.3) * wob * 0.6
            glow = 0.0
            if over > 0:
                gw = 0.5 + 0.5 * math.sin(self.t * 0.7 + s.phase)
                glow = min(1.0, over * (0.5 + 0.5 * gw))

            hot = _clamp01((s.width - 1.5) / 2.0)
            color = _lerp_color(LIGHT_WARM, LIGHT_HOT, hot * 0.65)
            if glow > 0:
                color = _lerp_color(color, LIGHT_OVERLOAD, glow)
            a = self._px(s.a, rect.size)
            b = self._px(s.b, rect.size)
            w = max(1, int(s.width))
            fade = max(0.15, 1.0 - dim)
            # The halo falls off faster than the core line (strength squared):
            # downtown stacks many overlapping segments, and a linear halo
            # saturated the core into a white starburst at midday.
            road_lit = strength * (0.45 + 0.55 * activity)
            pygame.draw.line(layer, (*color, int(50 * road_lit * road_lit * fade)), a, b, w + 5)
            pygame.draw.line(layer, (*color, int(215 * road_lit * fade)), a, b, w)

        for pos, weight, priority in self.nodes:
            if priority >= lit_frac:
                continue
            p = self._px(pos, rect.size)
            r = int(5 + 26 * weight)
            glow = strength * strength
            pygame.draw.circle(layer, (*LIGHT_HOT, int(24 * glow)), p, r)
            pygame.draw.circle(layer, (*LIGHT_HOT, int(58 * glow)), p, max(3, r // 2))
            pygame.draw.circle(layer, (*LIGHT_HOT, int(120 * strength)), p, max(2, r // 4))

    def _draw_traffic(self, layer, rect, level, dt, day=0.0):
        """Vehicles run the full length of a route and wrap at its end. The
        list is pre-shuffled across routes, so taking a prefix thins traffic
        network-wide rather than leaving whole roads deserted."""
        count = int(MAX_VEHICLES * level)
        if count <= 0:
            return
        w, h = rect.size
        line = pygame.draw.line
        # In daylight cars are the most visible thing on a road — sun glinting
        # off metal and glass — so traffic brightens rather than fades, and goes
        # white instead of amber.
        warm = _lerp_color(TRAFFIC_WARM, TRAFFIC_GLINT, day)
        cool = _lerp_color(TRAFFIC_COOL, TRAFFIC_GLINT, day)
        alpha = int(190 + 65 * day)

        for v in self.vehicles[:count]:
            v.pos += v.speed * dt
            if not 0.0 <= v.pos <= 1.0:
                v.pos = 0.0 if v.speed > 0 else 1.0   # wrap to the far end
            r = v.route
            # One bisect, and the tail derived from the same segment's direction
            # rather than a second lookup — at this vehicle count the saved work
            # is the difference between comfortable and over budget.
            d = v.pos * r.total
            i = bisect.bisect_right(r.cum, d) - 1
            if i < 0:
                i = 0
            elif i > len(r.points) - 2:
                i = len(r.points) - 2
            a, b = r.points[i], r.points[i + 1]
            span = r.cum[i + 1] - r.cum[i]
            t = (d - r.cum[i]) / span if span > 1e-9 else 0.0
            dx, dy = b[0] - a[0], b[1] - a[1]
            hx, hy = a[0] + dx * t, a[1] + dy * t
            k = TRAIL_PX / (math.hypot(dx, dy) or 1.0)
            if v.speed < 0:
                k = -k
            line(layer, (*(warm if v.warm else cool), alpha),
                 (int((hx - dx * k) * w), int((hy - dy * k) * h)),
                 (int(hx * w), int(hy * h)), 1)

    def _draw_overload(self, layer, rect, over):
        """Staged collapse. `over` == 1.0 is the meltdown line, so the visual
        peak and the run-ending condition coincide on every difficulty.

        Front-loaded on purpose: barely over is nearly invisible, but by the time
        you are pushing half again what the grid can take, the metro should look
        like it is coming apart. The stages overlap so nothing pops on.

        Every effect is slow smooth easing under ~1.2 Hz. However catastrophic
        this gets, it must never become large-area strobe.
        """
        w, h = rect.size
        sev = over ** 0.85           # front-load: 150% should already look dire

        # 1. substation arcing ------------------------------------------------
        arc = _clamp01((sev - 0.10) / 0.30)
        if arc > 0:
            for pos, weight, _priority in self.nodes:
                pulse = 0.5 + 0.5 * math.sin(self.t * 1.2 + weight * 9.0)
                a = int(230 * pulse * arc)
                if a > 4:
                    p = self._px(pos, rect.size)
                    pygame.draw.circle(layer, (255, 210, 130, a // 3), p, int(5 + 12 * arc))
                    pygame.draw.circle(layer, (255, 236, 190, a), p, 3)

        # 2. fires along the network -----------------------------------------
        fire = _clamp01((sev - 0.25) / 0.75)
        burning = []
        if fire > 0:
            stride = max(2, int(6 - 4 * fire))      # denser as it worsens
            burning = self.segments[:int(len(self.segments) * fire)][::stride]
            for s in burning:
                flick = 0.70 + 0.30 * math.sin(self.t * 1.1 + s.phase)
                p = self._px(s.mid, rect.size)
                r = int(2 + 5 * fire)
                pygame.draw.circle(layer, (*FIRE, int(52 * flick * fire)), p, int(r * 1.7))
                pygame.draw.circle(layer, (*FIRE, int(220 * flick)), p, r)
                pygame.draw.circle(layer, (255, 236, 180, int(200 * flick)), p, max(1, r // 2))

        # 3. smoke, thickening into a pall ------------------------------------
        smoke = _clamp01((sev - 0.35) / 0.65)
        if smoke > 0:
            for s in burning[::2]:
                for k in range(4):
                    age = (self.t * 0.26 + s.phase + k * 0.25) % 1.0
                    p = self._px(s.mid, rect.size)
                    sp = (p[0] + int(age * 34), p[1] - int(age * 60))
                    a = int(46 * (1.0 - age) * smoke)
                    if a > 4:
                        pygame.draw.circle(layer, (*SMOKE, a), sp, int(3 + age * 11))

        # 4. burnt-out districts: the lights that will not come back ----------
        dead = _clamp01((sev - 0.60) / 0.40)
        if dead > 0:
            for hood in self.hoods[::3]:
                if hood.priority > dead:
                    continue
                sink = 0.5 + 0.5 * math.sin(self.t * 0.55 + hood.phase)
                a = int(95 * dead * sink)
                if a > 6:
                    rx = max(2, int(hood.rx * w))
                    ry = max(2, int(hood.ry * h))
                    scar = pygame.Surface((rx * 2, ry * 2), pygame.SRCALPHA)
                    pygame.draw.ellipse(scar, (6, 4, 5, a), scar.get_rect())
                    layer.blit(scar, (int(hood.pos[0] * w) - rx,
                                      int(hood.pos[1] * h) - ry))

        # 5. firestorm haze over everything -----------------------------------
        haze = _clamp01((sev - 0.50) / 0.55)
        if haze > 0:
            breathe = 0.82 + 0.18 * math.sin(self.t * 0.9)
            wash = pygame.Surface(rect.size, pygame.SRCALPHA)
            wash.fill((150, 26, 10, int(44 * haze * breathe)))
            layer.blit(wash, (0, 0))
            # embers riding the updraught
            n = int(160 * haze)
            for i in range(n):
                ph = i * 2.399
                ex = (math.sin(ph * 3.1) * 0.5 + 0.5)
                ey = ((self.t * 0.11 + math.cos(ph * 1.7) * 0.5 + 0.5) % 1.0)
                a = int(190 * haze * (1.0 - ey))
                if a > 6:
                    pygame.draw.circle(layer, (255, 170, 70, a),
                                       (int(ex * w), int((1.0 - ey) * h)), 1)

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
        surface.blit(val_txt, (cx - val_txt.get_width() // 2, anchor.top + cap_txt.get_height() + 2))
