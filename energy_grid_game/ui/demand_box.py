"""Isometric fill-vessel widget: box footprint AND height both scale with demand,
so the vessel visibly expands outward (x/y) as well as taller (z), not just stretches.

The water surface runs a small 1D spring-heightfield simulation along the full
visible waterline (right-face edge + left-face edge, continuous through the near
corner), so waves propagate around the whole tank and both side faces and the top
surface deform coherently. Agitation from filling/draining feeds the sim.
"""
import math
import random
import pygame

RIM_RED = (230, 60, 60)
RIM_ORANGE = (240, 150, 50)
RIM_GREEN = (90, 220, 130)
RIM_YELLOW = (240, 220, 70)

# layered water palette, dark depths -> bright surface
WATER_RIGHT = (45, 150, 235, 205)
WATER_LEFT = (32, 126, 212, 205)
WATER_DEEP = (22, 90, 170, 120)
WATER_TOP = (85, 195, 255, 215)
WATER_BAND = (140, 220, 255, 70)
FOAM = (215, 245, 255, 170)
SHIMMER = (180, 230, 255, 40)

TINT_STRENGTH = 0.3  # how strongly the current supply mix colors the water


def _tinted(color, tint_rgb):
    if tint_rgb is None:
        return color
    r, g, b, a = color
    tr, tg, tb = tint_rgb
    return (int(r + (tr - r) * TINT_STRENGTH), int(g + (tg - g) * TINT_STRENGTH),
            int(b + (tb - b) * TINT_STRENGTH), a)


def _iso(x, y, z, origin):
    """Standard 2:1 isometric projection (30deg elevation, 45deg azimuth)."""
    ox, oy = origin
    sx = (x - y) * math.cos(math.radians(30))
    sy = (x + y) * math.sin(math.radians(30)) - z
    return ox + sx, oy + sy


# fill_pct is the live supply/demand ratio (1.0 == exactly meeting demand),
# so these bands are centered on 1.0, not on some mid-range buffer level.
def rim_color_for_fill(fill_pct: float):
    if fill_pct < 0.15:
        return RIM_RED
    elif fill_pct < 0.55:
        return RIM_ORANGE
    elif fill_pct <= 1.15:
        return RIM_GREEN
    elif fill_pct < 1.5:
        return RIM_YELLOW
    else:
        return RIM_RED


def fill_label(fill_pct: float) -> str:
    if fill_pct < 0.15:
        return "BLACKOUT WARNING"
    if fill_pct < 0.55:
        return "UNDERPOWERED"
    if fill_pct <= 1.15:
        return "IDEAL ZONE"
    if fill_pct < 1.5:
        return "NEAR CAPACITY"
    return "OVERFLOW"


class DemandBox:
    N_EDGE = 16  # heightfield samples per visible edge (total 2*N_EDGE+1)

    def __init__(self, center, time_ms=0):
        self.center = center  # screen point where the BASE (z=0) footprint is centered
        self.t = time_ms / 1000.0
        n = self.N_EDGE * 2 + 1
        self._wave_h = [0.0] * n
        self._wave_v = [0.0] * n
        self._rng = random.Random()
        self._ripples = []  # active puddle ripple rings: [age, jitter_x, jitter_y]

    # -- water heightfield -------------------------------------------------

    def _step_water(self, agitation: float):
        """One fixed step of the spring-heightfield. agitation in [-1.5, 1.5]:
        net inflow(+)/outflow(-) normalized; magnitude drives surface churn."""
        h, v = self._wave_h, self._wave_v
        n = len(h)
        churn = min(1.0, abs(agitation))

        # ambient ripples + flow-driven kicks
        if self._rng.random() < 0.05 + churn * 0.45:
            i = self._rng.randrange(n)
            v[i] += self._rng.uniform(0.4, 1.2) * (1.0 + 3.5 * churn)

        tension, spring, damp = 0.18, 0.015, 0.045
        acc = [0.0] * n
        for i in range(n):
            left = h[i - 1] if i > 0 else h[i]
            right = h[i + 1] if i < n - 1 else h[i]
            acc[i] = tension * (left + right - 2 * h[i]) - spring * h[i] - damp * v[i]
        for i in range(n):
            v[i] += acc[i]
            h[i] += v[i]

    def _waterline_xy(self, i: int, hw: float, hd: float):
        """Sample i along the visible waterline: corner1 (hw,-hd) -> corner2
        (hw,hd) -> corner3 (-hw,hd). Index N_EDGE is the shared near corner."""
        m = self.N_EDGE
        if i <= m:
            f = i / m
            return hw, -hd + 2 * hd * f
        f = (i - m) / m
        return hw - 2 * hw * f, hd

    # -- main draw -----------------------------------------------------------

    def draw(self, surface: pygame.Surface, height_px: float, footprint_px: float,
             fill_pct: float, agitation: float = 0.0, tint_rgb=None):
        self.t += 1.0 / 60.0
        ox, oy = self.center
        hw, hd = footprint_px / 2.0, footprint_px / 2.0
        h = height_px

        # Corner index layout: 0=(-hw,-hd) back, 1=(hw,-hd) right, 2=(hw,hd)
        # near, 3=(-hw,hd) left. The two visible faces share the near edge.
        corners_xy = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
        top = [_iso(x, y, h, (ox, oy)) for x, y in corners_xy]
        base = [_iso(x, y, 0, (ox, oy)) for x, y in corners_xy]

        right_face = [base[1], base[2], top[2], top[1]]
        left_face = [base[2], base[3], top[3], top[2]]
        glass = (60, 75, 100)

        pygame.draw.polygon(surface, (34, 42, 62), right_face)
        pygame.draw.polygon(surface, (22, 28, 42), left_face)

        clamped_fill = max(0.0, min(1.0, fill_pct))
        # even a true 0% reservoir keeps a thin visible puddle — this is a
        # fluid tank that's nearly empty, not a broken/blank render
        water_h = max(3.0, clamped_fill * h) if h > 6 else clamped_fill * h

        # when overflowing, the surface visibly domes/crests ABOVE the rim
        # line before spilling over the sides, instead of just flattening out
        # at the rim height with no indication liquid is piling up
        overflow_amt = max(0.0, fill_pct - 1.0)
        crest_bulge = min(1.0, overflow_amt / 0.4) * (h * 0.14)
        water_h += crest_bulge

        if water_h > 0:
            self._step_water(agitation)
            self._draw_water(surface, ox, oy, hw, hd, h, water_h, fill_pct, tint_rgb)
            if fill_pct >= 1.0:
                self._draw_overflow(surface, ox, oy, hw, hd, h, fill_pct - 1.0)

        rim = rim_color_for_fill(fill_pct)
        pulse = int(60 + 60 * abs(math.sin(self.t * (4 if fill_pct < 0.2 or fill_pct >= 1.0 else 1.5))))
        rim_draw = tuple(min(255, c + pulse if fill_pct < 0.2 or fill_pct >= 1.0 else c) for c in rim)
        pygame.draw.polygon(surface, rim_draw, top, width=4)
        pygame.draw.polygon(surface, (18, 22, 34), right_face, width=2)
        pygame.draw.polygon(surface, (18, 22, 34), left_face, width=2)
        if fill_pct < 1.0:
            pygame.draw.polygon(surface, glass, top, width=2)

        return rim, fill_label(fill_pct)

    def _draw_water(self, surface, ox, oy, hw, hd, h, water_h, fill_pct, tint_rgb=None):
        m = self.N_EDGE
        n = 2 * m + 1

        # wave amplitude: fades out for very shallow water so waves never dip
        # through the floor, and settles when pinned against the rim
        amp = min(1.0, water_h / 25.0)
        if fill_pct >= 1.0:
            amp *= 0.35

        # cap allows water_h to exceed h when cresting over the rim during
        # overflow; only clamp the wobble from pushing it absurdly far
        z_cap = max(h, water_h) + 6.0

        wave_pts = []       # projected waterline, corner1 -> corner2 -> corner3
        wave_z = []
        for i in range(n):
            x, y = self._waterline_xy(i, hw, hd)
            z = water_h + self._wave_h[i] * amp
            z = max(2.0, min(z, z_cap))  # stay inside the vessel (or crest above the rim)
            wave_z.append(z)
            wave_pts.append(_iso(x, y, z, (ox, oy)))

        # Base water body on its own layer. NOTE: pygame.draw on an SRCALPHA
        # surface overwrites pixels (no blending), so translucent decorations
        # must go on a SEPARATE layer or they punch holes in the water.
        water_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)

        # side faces with wavy waterlines (top edge follows the heightfield)
        right_poly = [_iso(hw, -hd, 0, (ox, oy)), _iso(hw, hd, 0, (ox, oy))]
        right_poly += [wave_pts[i] for i in range(m, -1, -1)]
        pygame.draw.polygon(water_surf, _tinted(WATER_RIGHT, tint_rgb), right_poly)

        left_poly = [_iso(hw, hd, 0, (ox, oy)), _iso(-hw, hd, 0, (ox, oy))]
        left_poly += [wave_pts[i] for i in range(n - 1, m - 1, -1)]
        pygame.draw.polygon(water_surf, _tinted(WATER_LEFT, tint_rgb), left_poly)

        # Top surface cap: its far corner is interpolated from the near corner
        # (fill=0, cap collapses to nothing) toward the true back corner
        # (fill=1, cap matches the rim exactly). This is required — a flat
        # horizontal diamond's PROJECTED SIZE in isometric view is independent
        # of its height, only its vertical position shifts. Using the fixed
        # back corner at any depth always draws a full footprint-sized cap,
        # which makes a nearly-empty tank look half-full. Scaling the cap's
        # own extent with fill% is what makes shallow water look shallow.
        clamped_fill = max(0.0, min(1.0, fill_pct))
        back_x = hw + (-hw - hw) * clamped_fill
        back_y = hd + (-hd - hd) * clamped_fill
        back_pt = _iso(back_x, back_y, water_h, (ox, oy))
        top_poly = [back_pt] + wave_pts
        pygame.draw.polygon(water_surf, _tinted(WATER_TOP, tint_rgb), top_poly)

        surface.blit(water_surf, (0, 0))

        # decoration layer, alpha-blended over the water body
        deco_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)

        # darker depth band along the bottom third of both faces
        deep_h = water_h * 0.38
        deep_poly = [_iso(hw, -hd, 0, (ox, oy)), _iso(hw, hd, 0, (ox, oy)),
                     _iso(-hw, hd, 0, (ox, oy)), _iso(-hw, hd, deep_h, (ox, oy)),
                     _iso(hw, hd, deep_h, (ox, oy)), _iso(hw, -hd, deep_h, (ox, oy))]
        pygame.draw.polygon(deco_surf, _tinted(WATER_DEEP, tint_rgb), deep_poly)

        # caustic shimmer: two shrunken diamond rings drifting on the surface,
        # additionally scaled by fill% for the same reason as the top cap above
        for ring_i, f in enumerate((0.62, 0.34)):
            f *= clamped_fill
            ring = []
            for k, (cx, cy) in enumerate([(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]):
                wob = 2.5 * math.sin(self.t * 1.7 + ring_i * 2.1 + k * 1.6)
                ring.append(_iso(cx * f + wob, cy * f - wob, water_h + 1, (ox, oy)))
            pygame.draw.polygon(deco_surf, SHIMMER, ring, width=2)

        # bright near-surface band just under the waterline on both faces
        band = 9.0
        band_poly = []
        for i in range(n):
            x, y = self._waterline_xy(i, hw, hd)
            band_poly.append(_iso(x, y, max(1.0, wave_z[i] - band), (ox, oy)))
        pygame.draw.polygon(deco_surf, _tinted(WATER_BAND, tint_rgb), wave_pts + band_poly[::-1])

        surface.blit(deco_surf, (0, 0))

        # foam line riding the waterline crest
        pygame.draw.lines(surface, FOAM[:3], False, wave_pts, 2)

    # -- overflow ------------------------------------------------------------

    def _draw_overflow(self, surface, ox, oy, hw, hd, h, overflow_amt):
        """Swaying tapered streams pour off the rim, droplets fall with gravity
        (accelerating streaks), and the splash puddle ripples with expanding
        rings. Everything scales with how far past capacity the tank is."""
        intensity = max(0.0, min(1.0, overflow_amt / 1.5))
        over_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        spill_len = 30 + 80 * intensity

        edges = [((hw, -hd), (hw, hd)), ((hw, hd), (-hw, hd))]

        # --- splash puddle (own layer so ripple rings blend instead of
        # overwriting each other's alpha) ---
        puddle_scale = 1.0 + 0.7 * intensity
        pc = _iso(hw, hd, 0, (ox, oy))
        pw, ph = hw * 1.3 * puddle_scale, 15 * puddle_scale
        puddle_rect = pygame.Rect(0, 0, int(pw * 2), int(ph * 2))
        puddle_rect.center = (int(pc[0]), int(pc[1] + 10))
        pygame.draw.ellipse(over_surf, (85, 190, 255, int(35 + 40 * intensity)),
                            puddle_rect.inflate(int(pw * 0.5), int(ph * 0.5)))
        pygame.draw.ellipse(over_surf, (55, 160, 240, int(60 + 60 * intensity)), puddle_rect)

        # a few expanding ripple rings where the water lands
        if self._rng.random() < 0.02 + 0.08 * intensity:
            self._ripples.append([0.0, self._rng.uniform(-0.45, 0.45), self._rng.uniform(-0.35, 0.35)])
        for r in self._ripples:
            r[0] += 1.0 / 60.0
        self._ripples = [r for r in self._ripples if r[0] < 1.2]
        ring_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        for age, jx, jy in self._ripples:
            life = age / 1.2
            rw = max(3, int(pw * 0.55 * (0.2 + 0.8 * life)))
            rh = max(2, int(ph * 0.55 * (0.2 + 0.8 * life)))
            ring_rect = pygame.Rect(0, 0, rw * 2, rh * 2)
            ring_rect.center = (int(pc[0] + jx * pw * 0.6), int(pc[1] + 10 + jy * ph * 0.6))
            alpha = int(120 * (1.0 - life))
            pygame.draw.ellipse(ring_surf, (170, 225, 255, alpha), ring_rect, width=2)

        # --- swaying tapered streams pouring off both visible rim edges ---
        n_per_edge = 3 + int(9 * intensity)
        segs = 7
        for e_idx, (p0, p1) in enumerate(edges):
            for i in range(n_per_edge):
                rand_a = ((i * 37 + e_idx * 11) % 13) / 13.0
                rand_b = ((i * 53 + e_idx * 7) % 17) / 17.0
                tpos = (i + 0.5) / n_per_edge
                x = p0[0] + (p1[0] - p0[0]) * tpos
                y = p0[1] + (p1[1] - p0[1]) * tpos

                cycle = (self.t * (0.6 + 0.8 * intensity) + rand_b) % 1.6
                grow = min(1.0, cycle)
                length = grow * (0.35 + 0.65 * rand_a) * (h * 0.55 + spill_len)

                rim_pt = _iso(x, y, h, (ox, oy))
                pts = [rim_pt]
                phase = rand_a * 6.28
                for s in range(1, segs + 1):
                    depth_frac = s / segs
                    dz = length * depth_frac
                    sway = 3.0 * math.sin(self.t * 2.5 + phase + depth_frac * 2.2) * depth_frac
                    px, py = _iso(x, y, h - dz, (ox, oy))
                    pts.append((px + sway, py))
                base_alpha = int((110 + 100 * intensity) * (0.5 + 0.5 * grow))
                # tapered: thick bright core near rim thinning to a thread
                for s in range(segs):
                    seg_frac = s / segs
                    width = max(1, int((4 + 2 * intensity) * (1.0 - 0.75 * seg_frac)))
                    alpha = int(base_alpha * (1.0 - 0.55 * seg_frac))
                    pygame.draw.line(over_surf, (110, 200, 255, alpha), pts[s], pts[s + 1], width)
                # glinting tip where the stream currently ends
                tip = pts[-1]
                pygame.draw.circle(over_surf, (200, 240, 255, base_alpha),
                                   (int(tip[0]), int(tip[1])), 2)

        surface.blit(over_surf, (0, 0))
        surface.blit(ring_surf, (0, 0))

        # --- gravity droplets: accelerating streaks, drawn in front ---
        n_drops = int(10 + 40 * intensity)
        fall_len = spill_len * 0.9 + h * 0.35
        drop_layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        for i in range(n_drops):
            e_idx = i % 2
            p0, p1 = edges[e_idx]
            half = max(1, n_drops // 2)
            tpos = ((i // 2) + 0.5) / half
            x = p0[0] + (p1[0] - p0[0]) * tpos
            y = p0[1] + (p1[1] - p0[1]) * tpos
            frac = (self.t * (1.0 + 1.0 * intensity) + (i * 41 % 19) / 19.0) % 1.0
            drop_y_off = fall_len * (frac ** 1.7)  # gravity: accelerates downward
            streak = 4 + 10 * frac                 # longer motion streak as it speeds up
            rim_pt = _iso(x, y, h, (ox, oy))
            alpha = int(220 * (1.0 - frac * 0.85))
            x_px, y_px = rim_pt[0], rim_pt[1] + drop_y_off
            pygame.draw.line(drop_layer, (170, 230, 255, alpha),
                             (x_px, y_px - streak), (x_px, y_px), 2)
        surface.blit(drop_layer, (0, 0))
