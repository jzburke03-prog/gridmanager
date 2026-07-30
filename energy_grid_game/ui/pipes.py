"""Trunk mains routing each source's output down into the city, styled after a
plumbing/manifold diagram: each spigot drops a vertical pipe, the left four and
right three sources merge into two manifold trunks, and both trunks discharge
into the city grid below.

Flow is a real (if simplified) particle system: discrete droplets spawn at the
source, travel the pipe with gravity-style easing (slow leaving the valve,
faster as they fall), and hit the discharge point end-to-end — where they
trigger a small splash ring — instead of looping forever inside the pipe. Each
droplet keeps its source's color the whole way down.

The hydraulic metaphor is deliberate and load-bearing (SPEC-1.1 §1.6): these
channels are the substrate for the transmission/congestion model in 1.2. Keep
each source's path an independent object with its own flow state — do NOT merge
them into a single aggregate feed for rendering economy, because per-path
throughput is where a carrying capacity and a congestion penalty will attach.
"""
import pygame

PIPE_COLOR = (70, 80, 100)
PIPE_BORDER = (40, 46, 60)
PIPE_WIDTH = 10

# Which manifold each source feeds, and the order along it. Sources absent from
# the panel are skipped, so these are an ordering, not a requirement.
LEFT_ORDER = ["generic", "nuclear", "coal", "gas", "peaker"]
RIGHT_ORDER = ["solar", "wind", "hydro"]


def _route(x_positions, spigot_bottom_y, manifold_y, merge_x, entry_y):
    """Build one manifold's pipe skeleton: per-source vertical drops down to the
    manifold height, one horizontal run along it, then a straight vertical drop
    at the merge point down into the city.

    The final leg is deliberately vertical rather than diagonal — a slanted run
    to an off-axis discharge point reads as a stray stick lying across the city
    rather than as a main descending into it.
    """
    drops = [[(x, spigot_bottom_y), (x, manifold_y)] for x in x_positions]
    trunk = [(x_positions[0], manifold_y), (x_positions[-1], manifold_y),
              (merge_x, manifold_y), (merge_x, entry_y)]
    return drops, trunk


def _ease(t):
    """Gravity-flavored easing: droplets leave the valve slowly and accelerate
    as they fall toward the box, instead of gliding at one flat speed."""
    return t * t * (3.0 - 2.0 * t) if t < 0.5 else t ** 0.7


class _Droplet:
    __slots__ = ("progress", "speed", "size_jitter")

    def __init__(self, speed, size_jitter):
        self.progress = 0.0
        self.speed = speed
        self.size_jitter = size_jitter


class PipeSystem:
    def __init__(self):
        self.t = 0.0
        self._droplets = {}      # source key -> list[_Droplet]
        self._spawn_acc = {}     # source key -> fractional spawn accumulator
        self._splashes = []      # active splash rings: [age, x, y, color]
        self._rng_state = 12345

    def _rand(self):
        # tiny deterministic LCG so we don't need to import random per-particle
        self._rng_state = (1103515245 * self._rng_state + 12345) & 0x7FFFFFFF
        return (self._rng_state % 10000) / 10000.0

    def draw(self, surface, sources, source_x_centers, spigot_bottom_y, city_entry_y, city_rect):
        """`city_entry_y` is the depth into the city at which the trunks discharge.
        Each trunk descends at its own group's merge point, so the two mains feed
        the city at two separate distribution points."""
        dt = 1.0 / 60.0
        self.t += dt
        by_key = {s.key: s for s in sources}

        # Groups are derived from the sources actually on the panel, never
        # hardcoded: Instructional Mode hands us anything from a single generic
        # valve to the full fleet, and a fixed key list KeyErrors on every day
        # but the last. An empty group is simply not routed.
        manifold_y = spigot_bottom_y + max(26, int(city_rect.height * 0.10))
        groups = []
        for order in (LEFT_ORDER, RIGHT_ORDER):
            keys = [k for k in order if k in by_key and k in source_x_centers]
            if not keys:
                continue
            xs = [source_x_centers[k] for k in keys]
            drops, trunk = _route(xs, spigot_bottom_y, manifold_y,
                                  (xs[0] + xs[-1]) / 2, city_entry_y)
            groups.append((keys, drops, trunk))
        if not groups:
            return

        pipe_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        for _keys, drops, trunk in groups:
            for seg in drops:
                self._draw_pipe_segment(pipe_surf, seg, PIPE_COLOR, PIPE_BORDER)
            self._draw_pipe_segment(pipe_surf, trunk, PIPE_COLOR, PIPE_BORDER)
        surface.blit(pipe_surf, (0, 0))

        flow_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        for keys, drops, trunk in groups:
            for key, drop in zip(keys, drops):
                # Droplets run the full casing and splash at the discharge
                # point. In 1.0 they carried on past the trunk's end down to the
                # tank's moving water surface; with no vessel, the main simply
                # ends where it meets the city.
                self._update_and_draw_droplets(flow_surf, drop + trunk[1:],
                                               by_key[key], dt)
        surface.blit(flow_surf, (0, 0))

        self._draw_splashes(surface, dt)

    def _draw_pipe_segment(self, surf, points, fill, border):
        pts = [(int(x), int(y)) for x, y in points]
        for a, b in zip(pts, pts[1:]):
            pygame.draw.line(surf, border, a, b, PIPE_WIDTH + 4)
        for a, b in zip(pts, pts[1:]):
            pygame.draw.line(surf, fill, a, b, PIPE_WIDTH)
        for p in pts:
            pygame.draw.circle(surf, fill, p, PIPE_WIDTH // 2)

    def _path_length(self, path):
        total = 0.0
        segs = []
        for a, b in zip(path, path[1:]):
            d = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            segs.append((a, b, d))
            total += d
        return segs, total

    def _point_at(self, segs, total, frac):
        dist = max(0.0, min(1.0, frac)) * total
        acc = 0.0
        for a, b, d in segs:
            if acc + d >= dist:
                f = (dist - acc) / d if d > 0 else 0
                return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
            acc += d
        return segs[-1][1] if segs else (0, 0)

    def _update_and_draw_droplets(self, surf, path, src, dt):
        output = src.actual_pct
        segs, total = self._path_length(path)
        if total <= 0:
            return
        key = src.key

        droplets = self._droplets.setdefault(key, [])

        # spawn rate scales with throttle: closed valve spawns ~nothing
        if output > 0.01:
            spawn_rate = 0.8 + output * 7.0  # droplets/sec
            acc = self._spawn_acc.get(key, 0.0) + spawn_rate * dt
            while acc >= 1.0 and len(droplets) < 40:
                speed = 0.55 + output * 0.9 + (self._rand() - 0.5) * 0.15
                droplets.append(_Droplet(speed, 0.7 + self._rand() * 0.6))
                acc -= 1.0
            self._spawn_acc[key] = acc

        end_x, end_y = path[-1]
        alive = []
        for d in droplets:
            d.progress += d.speed * dt
            if d.progress >= 1.0:
                self._splashes.append([0.0, end_x, end_y, src.color])
                continue
            alive.append(d)
        self._droplets[key] = alive

        radius_base = 2.2 + output * 2.6
        for d in alive:
            eased = _ease(d.progress)
            x, y = self._point_at(segs, total, eased)
            r = max(1, int(radius_base * d.size_jitter))
            alpha = int(150 + 90 * output)
            pygame.draw.circle(surf, (*src.color, alpha), (int(x), int(y)), r)
            # tiny motion trail so droplets read as flowing, not teleporting
            trail_frac = max(0.0, eased - 0.03)
            tx, ty = self._point_at(segs, total, trail_frac)
            pygame.draw.line(surf, (*src.color, alpha // 2), (tx, ty), (x, y), max(1, r - 1))

    def _draw_splashes(self, surface, dt):
        splash_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        alive = []
        for s in self._splashes:
            s[0] += dt
            if s[0] < 0.4:
                alive.append(s)
            age, x, y, color = s
            life = age / 0.4
            radius = int(3 + 12 * life)
            alpha = int(200 * (1.0 - life))
            if alpha > 0:
                pygame.draw.circle(splash_surf, (*color, alpha), (int(x), int(y)), radius, width=2)
        self._splashes = alive
        surface.blit(splash_surf, (0, 0))
