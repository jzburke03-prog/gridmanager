"""Pipes routing each source's output down into the demand box, styled after
a plumbing/manifold diagram: each spigot drops a vertical pipe, the left three
and right three sources merge into two manifold trunks, and both trunks feed
into the top of the vessel.

Flow is a real (if simplified) particle system: discrete droplets spawn at the
source, travel the pipe with gravity-style easing (slow leaving the valve,
faster as they fall toward the box), and hit the box's rim end-to-end — where
they trigger a small splash ring — instead of looping forever inside the pipe.
Each droplet keeps its source's color the whole way down.
"""
import pygame

PIPE_COLOR = (70, 80, 100)
PIPE_BORDER = (40, 46, 60)
PIPE_WIDTH = 10


def _route(x_positions, spigot_bottom_y, manifold_y, merge_x, box_entry):
    """Build one manifold's pipe skeleton: per-source vertical drops down to
    the manifold height, one horizontal run to the merge point, then a final
    vertical drop into the box. Returns (per_source_vertical_segments, trunk_segments)."""
    drops = [[(x, spigot_bottom_y), (x, manifold_y)] for x in x_positions]
    trunk = [(x_positions[0], manifold_y), (x_positions[-1], manifold_y),
              (merge_x, manifold_y), box_entry]
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

    def draw(self, surface, sources, source_x_centers, spigot_bottom_y, box_top_point, box_rect,
             water_drop_px=0.0):
        dt = 1.0 / 60.0
        self.t += dt
        left_keys = ["nuclear", "coal", "gas"]
        right_keys = ["solar", "wind", "hydro"]
        by_key = {s.key: s for s in sources}

        manifold_y = spigot_bottom_y + max(30, int(box_rect.height * 0.16))
        bx, by = box_top_point
        left_entry = (bx - 46, by + 10)
        right_entry = (bx + 46, by + 10)

        left_x = [source_x_centers[k] for k in left_keys]
        right_x = [source_x_centers[k] for k in right_keys]
        left_drops, left_trunk = _route(left_x, spigot_bottom_y, manifold_y,
                                         (left_x[0] + left_x[-1]) / 2, left_entry)
        right_drops, right_trunk = _route(right_x, spigot_bottom_y, manifold_y,
                                           (right_x[0] + right_x[-1]) / 2, right_entry)

        pipe_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        all_paths = list(zip(left_keys, left_drops)) + list(zip(right_keys, right_drops))
        for _key, seg in all_paths:
            self._draw_pipe_segment(pipe_surf, seg, PIPE_COLOR, PIPE_BORDER)
        self._draw_pipe_segment(pipe_surf, left_trunk, PIPE_COLOR, PIPE_BORDER)
        self._draw_pipe_segment(pipe_surf, right_trunk, PIPE_COLOR, PIPE_BORDER)
        surface.blit(pipe_surf, (0, 0))

        flow_surf = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        for key, drop in all_paths:
            src = by_key.get(key)
            if src is None:
                continue
            trunk = left_trunk if key in left_keys else right_trunk
            # the rigid pipe casing ends at the rim (trunk's last point), but
            # the water doesn't stop there — it keeps falling, now as loose
            # droplets rather than pipe-contained flow, down to wherever the
            # tank's actual water surface currently sits before splashing in.
            # Without this, droplets vanished right at the rim opening no
            # matter how empty the tank was, reading as water disappearing
            # into nothing instead of pouring in.
            entry = trunk[-1]
            path = drop + trunk[1:] + [(entry[0], entry[1] + water_drop_px)]
            self._update_and_draw_droplets(flow_surf, path, src, dt)
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
