"""Voxel-pixel isometric map -- GPU (pyglet) renderer.

Terrain fills the frame with mountain ranges on the edges; the city is the hero;
the seven generators are the sliced sprite-sheet assets, animated. Season palette
and continuous time-of-day lighting are live shader uniforms driven by the game's
sim clock. Run with no args for the interactive window; `stills` renders
verification PNGs offscreen.

    python voxel_map.py                 # interactive
    python voxel_map.py stills OUTDIR   # render verification frames
"""
import json
import math
import random
import sys
from pathlib import Path

import pyglet
from pyglet.gl import (GL_TRIANGLES, GL_BLEND, GL_DEPTH_TEST, GL_LEQUAL,
                       GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_COLOR_BUFFER_BIT,
                       GL_DEPTH_BUFFER_BIT, glEnable, glDisable, glBlendFunc,
                       glDepthFunc, glClearColor, glClear, glViewport)
from pyglet.graphics.shader import Shader, ShaderProgram

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "energy_grid_game"))

W, H = 1360, 860
TW, TH, GH, UZ = 34, 17, 9, 11

# ---------------------------------------------------------------------------
# Sim clock: pull real sim_hour + season from the game; fall back to a local
# clock if the game import fails so the app always runs.
# ---------------------------------------------------------------------------
class SimClock:
    def __init__(self):
        self.state = None
        try:
            import scenarios
            from game_state import GameState
            self.state = GameState(scenarios.make_standard())
        except Exception as e:      # noqa
            print("[clock] game import failed, using local clock:", e)
        self._h = 4.0
        self._month = 8

    def update(self, dt, speed=1.0):
        if self.state is not None:
            try:
                self.state.update(dt * speed * 220.0)
                return
            except Exception:
                self.state = None
        self._h = (self._h + dt * speed * 1.4) % 24.0

    @property
    def hour(self):
        return getattr(self.state, "sim_hour", self._h) if self.state else self._h

    @property
    def month(self):
        if self.state is not None and getattr(self.state, "date", None):
            return self.state.date.month
        return self._month


def season_of(month):
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring",
            5: "spring", 6: "summer", 7: "summer", 8: "summer", 9: "fall",
            10: "fall", 11: "fall"}[month]


def daylight(hour):
    """-> (day_factor 0..1, tint rgb, sky rgb). Smooth dawn/day/dusk/night."""
    h = hour % 24.0
    # day factor: night floor 0.08, full day 1.0, ramps at dawn(5-7)/dusk(17-19)
    if h < 5 or h >= 20:
        day = 0.08
    elif h < 7:
        day = 0.08 + 0.92 * (h - 5) / 2.0
    elif h < 17:
        day = 1.0
    elif h < 20:
        day = 1.0 - 0.92 * (h - 17) / 3.0
    else:
        day = 0.08
    warm = max(0.0, 1.0 - abs(h - 18.0) / 2.5) + max(0.0, 1.0 - abs(h - 6.0) / 2.5)
    warm = min(1.0, warm)
    tint = (0.55 * warm + 0.02 * (1 - day), 0.28 * warm, 0.10 * warm + 0.14 * (1 - day))
    sky_day = (0.53, 0.62, 0.74)
    sky_night = (0.05, 0.06, 0.12)
    sky = tuple(sky_night[i] + (sky_day[i] - sky_night[i]) * day for i in range(3))
    sky = tuple(min(1.0, sky[i] + tint[i] * 0.5) for i in range(3))
    return day, tint, sky


# ---------------------------------------------------------------------------
# Season material palettes (0-255). Materials:
# 0 grass 1 field 2 water 3 road 4 pad 5 rock 6 snowcap
# ---------------------------------------------------------------------------
SEASONS = {
    "spring": dict(grass=(84,152,76), field=(126,168,82), water=(60,122,196),
                   road=(96,98,104), pad=(120,122,128), rock=(104,100,96), snow=(232,238,246)),
    "summer": dict(grass=(150,168,72), field=(200,188,96), water=(60,120,196),
                   road=(100,100,98), pad=(124,124,126), rock=(120,112,100), snow=(236,240,246)),
    "fall":   dict(grass=(146,146,72), field=(190,138,70), water=(58,110,182),
                   road=(98,92,84), pad=(126,118,106), rock=(112,98,84), snow=(232,236,244)),
    "winter": dict(grass=(226,232,238), field=(214,222,232), water=(158,190,214),
                   road=(120,124,132), pad=(150,154,162), rock=(150,156,166), snow=(244,248,252)),
}
MAT_ORDER = ("grass", "field", "water", "road", "pad", "rock", "snow")

BUILDING_COLORS = [(150,170,210),(176,186,208),(120,150,200),(200,206,216),
                   (168,150,140),(140,176,170),(196,176,150)]

# organic (non-radial) plant placement -- some near, some far
ZONES = {"coal": (10, 9), "nuclear": (20, 5), "gas": (33, 15), "peaker": (34, 30),
         "wind": (27, 35), "solar": (12, 32), "hydro": (6, 29)}
CITY = {(gx, gy) for gx in range(13, 27) for gy in range(13, 27)}
CITY_CX, CITY_CY = 19.5, 19.5
GRID = range(-30, 70)
OX, OY = W // 2, 150


def iso(gx, gy):
    return OX + (gx - gy) * (TW // 2), OY + (gx + gy) * (TH // 2)


# value noise for mountain ridgelines
def _h2(a, b):
    n = (a * 374761393 + b * 668265263) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return (n & 0xFFFF) / 65535.0


def vnoise(x, y):
    xi, yi = math.floor(x), math.floor(y)
    xf, yf = x - xi, y - yi
    def sm(t): return t * t * (3 - 2 * t)
    u, v = sm(xf), sm(yf)
    a = _h2(xi, yi); b = _h2(xi + 1, yi)
    c = _h2(xi, yi + 1); d = _h2(xi + 1, yi + 1)
    return (a * (1 - u) + b * u) * (1 - v) + (c * (1 - u) + d * u) * v


def elevation(gx, gy):
    """Voxel height (in Z units) for a tile: 0 in the play area, rising into
    mountain ranges toward the edges with noisy ridgelines."""
    d = math.hypot(gx - CITY_CX, gy - CITY_CY)
    start, full = 24.0, 42.0
    if d <= start:
        return 0
    ramp = min(1.0, (d - start) / (full - start))
    ridge = 0.45 + 0.55 * vnoise(gx * 0.16, gy * 0.16)
    peak = 0.55 + 0.75 * vnoise(gx * 0.24 + 10, gy * 0.24 + 10)
    return int(ramp * (3 + 10 * ridge) * peak * 0.9)


# ---------------------------------------------------------------------------
# Terrain geometry -> one GPU vertex list. Attributes: position(2), depth(1),
# color(3, used when material<0), material(1), shade(1).
# ---------------------------------------------------------------------------
POS, DEP, COL, MAT, SHA = [], [], [], [], []
_lo, _hi = GRID.start, GRID.stop
_SUMSPAN = 2.0 * (_hi - _lo)


def _depth(gx, gy):
    return 1.0 - ((gx + gy) - 2 * _lo) / _SUMSPAN     # nearer (big sum) -> small z


def _v(x, y, dep, c, m, s):
    POS.extend((x, y)); DEP.append(dep); COL.extend(c); MAT.append(m); SHA.append(s)


def _quad(p, dep, c, m, s):
    a, b, cc, d = p
    for pt in (a, b, cc, a, cc, d):
        _v(pt[0], pt[1], dep, c, m, s)


def emit_column(gx, gy, height_px, m, c=(0, 0, 0), jit=1.0, capm=None):
    """Column rising `height_px` above the tile apex at (gx,gy)."""
    sx, sy = iso(gx, gy)
    dep = _depth(gx, gy)
    L, B, R = (sx - TW // 2, sy + TH // 2), (sx, sy + TH), (sx + TW // 2, sy + TH // 2)
    top = -height_px
    Lu, Bu, Ru = (L[0], L[1] + top), (B[0], B[1] + top), (R[0], R[1] + top)
    if height_px > 0:
        _quad([Lu, Bu, B, L], dep, c, m, 0.68 * jit)
        _quad([Bu, Ru, R, B], dep, c, m, 0.50 * jit)
    tmat = capm if capm is not None else m
    T = (sx, sy - height_px)
    _quad([T, (sx + TW // 2, sy + TH // 2 - height_px), Bu, Lu], dep, c, tmat, 1.0 * jit)
    # small ground skirt so flat tiles still have voxel thickness
    if height_px <= 0:
        Ld, Bd, Rd = (L[0], L[1] + GH), (B[0], B[1] + GH), (R[0], R[1] + GH)
        _quad([L, B, Bd, Ld], dep, c, m, 0.68 * jit)
        _quad([B, R, Rd, Bd], dep, c, m, 0.50 * jit)


GRASS, FIELD, WATER, ROAD, PAD, ROCK, SNOW = range(7)


def river_tiles():
    t = set()
    for gx in GRID:
        gy = int(30 - gx * 0.55 + 2.5 * math.sin(gx / 5.0))
        for w in (-1, 0, 1):
            if (gx, gy + w) not in CITY:
                t.add((gx, gy + w))
    return t


def road_tiles():
    core, t = (19, 19), set()
    for gx, gy in ZONES.values():
        steps = max(abs(gx - core[0]), abs(gy - core[1]))
        for i in range(steps + 1):
            f = i / max(1, steps)
            t.add((round(core[0] + (gx - core[0]) * f), round(core[1] + (gy - core[1]) * f)))
    return t


def build_terrain():
    rng = random.Random(7)
    river, roads = river_tiles(), road_tiles()
    for s in range(2 * _lo, 2 * _hi):
        for gx in range(_lo, _hi):
            gy = s - gx
            if not (_lo <= gy < _hi):
                continue
            sx, sy = iso(gx, gy)
            if sx < -TW * 2 or sx > W + TW * 2 or sy < -400 or sy > H + TH * 3:
                continue
            jit = 0.9 + 0.2 * _h2(gx & 4095, gy & 4095)
            elev = elevation(gx, gy)
            if elev > 0:                          # mountain
                snowline = 9
                capm = SNOW if elev >= snowline else ROCK
                emit_column(gx, gy, elev * UZ + GH, ROCK, jit=jit, capm=capm)
                continue
            if (gx, gy) in river:
                emit_column(gx, gy, 0, WATER, jit=jit)
            elif (gx, gy) in roads and (gx, gy) not in CITY:
                emit_column(gx, gy, 0, ROAD, jit=jit)
            elif (gx, gy) in CITY:
                emit_column(gx, gy, 0, PAD, jit=jit)
                dc = math.hypot(gx - CITY_CX, gy - CITY_CY)
                floors = max(3, min(12, int(round(12 - dc * 0.9 + rng.uniform(-1.6, 1.6)))))
                emit_column(gx, gy, UZ * floors, -1.0, c=rng.choice(BUILDING_COLORS))
            elif (gx // 4 + gy // 4) % 3 == 0:
                emit_column(gx, gy, 0, FIELD, jit=jit)
            else:
                emit_column(gx, gy, 0, GRASS, jit=jit)


# ---------------------------------------------------------------------------
# Shaders
# ---------------------------------------------------------------------------
TERRAIN_VERT = """#version 330 core
in vec2 position; in float depth; in vec3 acolor; in float amat; in float ashade;
out vec3 vcolor; out float vmat; out float vshade;
uniform vec2 u_scale, u_offset, u_res, u_pivot;
void main(){
    vec2 p = (position - u_pivot) * u_scale + u_pivot + u_offset;
    gl_Position = vec4(p.x/u_res.x*2.0-1.0, 1.0 - p.y/u_res.y*2.0, depth*2.0-1.0, 1.0);
    vcolor = acolor/255.0; vmat = amat; vshade = ashade;
}"""
TERRAIN_FRAG = """#version 330 core
in vec3 vcolor; in float vmat; in float vshade; out vec4 f;
uniform vec3 u_pal[7];
uniform float u_day; uniform vec3 u_tint;
void main(){
    vec3 base = (vmat < -0.5) ? vcolor : u_pal[int(vmat + 0.5)];
    base *= vshade;
    float amb = 0.30 + 0.70 * u_day;
    f = vec4(clamp(base*amb + u_tint*(1.0-u_day), 0.0, 1.0), 1.0);
}"""

SPRITE_VERT = """#version 330 core
in vec2 position; in vec2 tex; in float depth;
out vec2 vtex;
uniform vec2 u_scale, u_offset, u_res, u_pivot;
void main(){
    vec2 p = (position - u_pivot) * u_scale + u_pivot + u_offset;
    gl_Position = vec4(p.x/u_res.x*2.0-1.0, 1.0 - p.y/u_res.y*2.0, depth*2.0-1.0, 1.0);
    vtex = tex;
}"""
SPRITE_FRAG = """#version 330 core
in vec2 vtex; out vec4 f;
uniform sampler2D u_tex; uniform float u_day; uniform vec3 u_tint;
void main(){
    vec4 c = texture(u_tex, vtex);
    if (c.a < 0.25) discard;
    float amb = 0.55 + 0.45 * u_day;              // plants keep lit windows at night
    f = vec4(clamp(c.rgb*amb + u_tint*(1.0-u_day)*0.6, 0.0, 1.0), c.a);
}"""


# ---------------------------------------------------------------------------
# Plant sprites
# ---------------------------------------------------------------------------
# target on-screen WIDTH in px at zoom 1 (normalises the differently-sized
# sliced frames to a sensible footprint next to the city)
PLANT_TARGET_W = {"coal": 120, "nuclear": 128, "gas": 120, "peaker": 108,
                  "solar": 124, "wind": 118, "hydro": 140}
PLANT_FPS = {"coal": 6, "nuclear": 5, "gas": 8, "peaker": 8,
             "solar": 3, "wind": 14, "hydro": 10}


class Plants:
    def __init__(self):
        man = json.loads((HERE / "assets/plants/manifest.json").read_text())
        self.frames = {}
        for tech, info in man.items():
            imgs = []
            for fn in info["frames"]:
                im = pyglet.image.load(str(HERE / "assets/plants" / tech / fn))
                t = im.get_texture()
                imgs.append(t)
            self.frames[tech] = imgs
        self.t = 0.0

    def update(self, dt):
        self.t += dt

    def cur(self, tech):
        fr = self.frames[tech]
        i = int(self.t * PLANT_FPS[tech]) % len(fr)
        return fr[i]


def sprite_quad(tech, tex):
    gx, gy = ZONES[tech]
    sx, sy = iso(gx, gy)
    sc = PLANT_TARGET_W[tech] / tex.width
    w, h = tex.width * sc, tex.height * sc
    # anchor bottom-centre at the tile's front-centre
    bx, by = sx, sy + TH + 4
    x0, x1 = bx - w / 2, bx + w / 2
    y0, y1 = by - h, by
    dep = _depth(gx, gy) - 0.0005
    tc = tex.tex_coords    # (u,v,?) x4
    pos = [x0, y1, x1, y1, x1, y0, x0, y1, x1, y0, x0, y0]
    uv = [tc[0], tc[1], tc[3], tc[4], tc[6], tc[7],
          tc[0], tc[1], tc[6], tc[7], tc[9], tc[10]]
    dep6 = [dep] * 6
    return pos, uv, dep6


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
class VoxelMap:
    def __init__(self, visible=True):
        self.win = pyglet.window.Window(W, H, "Voxel Grid", visible=visible)
        glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LEQUAL)
        self.tprog = ShaderProgram(Shader(TERRAIN_VERT, "vertex"), Shader(TERRAIN_FRAG, "fragment"))
        self.sprog = ShaderProgram(Shader(SPRITE_VERT, "vertex"), Shader(SPRITE_FRAG, "fragment"))
        build_terrain()
        self.tlist = self.tprog.vertex_list(
            len(MAT), GL_TRIANGLES, position=("f", POS), depth=("f", DEP),
            acolor=("f", COL), amat=("f", MAT), ashade=("f", SHA))
        self.plants = Plants()
        self.clock = SimClock()
        self.zoom = 1.0
        self.offset = [0.0, 0.0]
        for p in (self.tprog, self.sprog):
            p["u_res"] = (float(W), float(H)); p["u_pivot"] = (W / 2.0, H / 2.0)
        self.time_speed = 1.0
        self.hud = pyglet.text.Label("", font_name="Consolas", font_size=13,
                                     x=14, y=H - 12, anchor_y="top",
                                     color=(235, 238, 245, 255))
        self.help = pyglet.text.Label(
            "scroll/+- zoom  ·  drag pan  ·  [ ] scrub time  ·  1-4 season  ·  space fast  ·  c live clock",
            font_name="Consolas", font_size=11, x=14, y=10,
            color=(200, 206, 216, 200))
        self.win.push_handlers(on_draw=self.on_draw, on_mouse_scroll=self.on_scroll,
                               on_mouse_drag=self.on_drag, on_key_press=self.on_key)
        pyglet.clock.schedule_interval(self.update, 1 / 60.0)

    def on_scroll(self, x, y, sx, sy):
        self.zoom = max(0.5, min(4.0, self.zoom * (1.1 if sy > 0 else 0.9)))

    def on_drag(self, x, y, dx, dy, *a):
        self.offset[0] += dx; self.offset[1] -= dy

    def on_key(self, sym, mod):
        from pyglet.window import key
        if sym in (key.EQUAL, key.PLUS, key.NUM_ADD):
            self.zoom = min(4.0, self.zoom * 1.15)
        elif sym in (key.MINUS, key.NUM_SUBTRACT):
            self.zoom = max(0.5, self.zoom / 1.15)
        elif sym == key.BRACKETLEFT:
            self.clock.state = None; self.clock._h = (self.clock._h - 1) % 24
        elif sym == key.BRACKETRIGHT:
            self.clock.state = None; self.clock._h = (self.clock._h + 1) % 24
        elif sym in (key._1, key._2, key._3, key._4):
            self.clock.state = None
            self.clock._month = {key._1: 4, key._2: 7, key._3: 10, key._4: 1}[sym]
        elif sym == key.SPACE:
            self.time_speed = 12.0 if self.time_speed == 1.0 else 1.0
        elif sym == key.C:
            self.clock = SimClock()               # rejoin the live game clock

    def update(self, dt):
        self.clock.update(dt, self.time_speed)
        self.plants.update(dt)

    def _set_uniforms(self):
        season = season_of(self.clock.month)
        pal = SEASONS[season]
        flat = [tuple(c / 255.0 for c in pal[k]) for k in MAT_ORDER]  # 7 vec3
        day, tint, sky = daylight(self.clock.hour)
        self.tprog["u_pal"] = flat
        for p in (self.tprog, self.sprog):
            p["u_day"] = day; p["u_tint"] = tint
            p["u_scale"] = (self.zoom, self.zoom)
            p["u_offset"] = tuple(self.offset)
        return sky

    def on_draw(self):
        sky = self._set_uniforms()
        glViewport(0, 0, W, H)
        glClearColor(*sky, 1.0); glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self.tprog.use(); self.tlist.draw(GL_TRIANGLES); self.tprog.stop()
        # plants back-to-front
        self.sprog.use()
        order = sorted(ZONES, key=lambda t: ZONES[t][0] + ZONES[t][1])
        for tech in order:
            tex = self.plants.cur(tech)
            pos, uv, dep = sprite_quad(tech, tex)
            pyglet.gl.glBindTexture(tex.target, tex.id)
            vl = self.sprog.vertex_list(6, GL_TRIANGLES,
                                        position=("f", pos), tex=("f", uv), depth=("f", dep))
            vl.draw(GL_TRIANGLES); vl.delete()
        self.sprog.stop()
        # HUD (season + clock), drawn without depth test
        glDisable(GL_DEPTH_TEST)
        h = self.clock.hour
        season = season_of(self.clock.month)
        self.hud.text = (f"{season.upper():>6}   {int(h):02d}:{int((h%1)*60):02d}"
                         f"   zoom {self.zoom:.1f}x"
                         + ("   [FAST]" if self.time_speed != 1.0 else ""))
        self.hud.draw(); self.help.draw()
        glEnable(GL_DEPTH_TEST)


def render_stills(outdir):
    out = Path(outdir); out.mkdir(parents=True, exist_ok=True)
    app = VoxelMap(visible=False)
    shots = [("summer", 13.0, 1.0, (0, 0), "01_summer_noon"),
             ("summer", 18.5, 1.0, (0, 0), "02_summer_dusk"),
             ("summer", 2.0, 1.0, (0, 0), "03_summer_night"),
             ("winter", 12.0, 1.0, (0, 0), "04_winter"),
             ("fall", 9.0, 1.0, (0, 0), "05_fall"),
             ("summer", 13.0, 1.7, (0, 90), "06_zoom")]
    monthmap = {"winter": 1, "spring": 4, "summer": 7, "fall": 10}
    for season, hour, zoom, off, name in shots:
        app.clock.state = None
        app.clock._h = hour; app.clock._month = monthmap[season]
        app.plants.t = 3.3
        app.zoom = zoom; app.offset = list(off)
        app.win.switch_to()
        app.on_draw()
        pyglet.image.get_buffer_manager().get_color_buffer().save(str(out / f"{name}.png"))
        print("wrote", name)
    app.win.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stills":
        render_stills(sys.argv[2] if len(sys.argv) > 2 else "stills")
    else:
        VoxelMap(visible=True)
        pyglet.app.run()
