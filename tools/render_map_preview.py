#!/usr/bin/env python3
"""Standalone approval render for the hard-pivot map direction.

This tool is deliberately not wired into run_game.py. It renders one proposed
world look from only assets/map and assets/tech so the visual direction can be
reviewed before runtime integration.
"""
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bake_gltf_terrain import load_gltf  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APPROVED_MAP_ROOT = ROOT / "assets" / "map"
APPROVED_TECH_ROOT = ROOT / "assets" / "tech"
MAP_GLTF_ROOT = APPROVED_MAP_ROOT / "gltf"
DEFAULT_OUT = (
    Path(os.environ.get("TEMP", ROOT))
    / "gridmanager_map_preview"
    / "map_tech_preview.png"
)

_AY = np.deg2rad(45.0)
_AX = np.deg2rad(35.264)
_RY = np.array([[np.cos(_AY), 0, np.sin(_AY)],
                [0, 1, 0],
                [-np.sin(_AY), 0, np.cos(_AY)]], dtype="f4")
_RX = np.array([[1, 0, 0],
                [0, np.cos(_AX), -np.sin(_AX)],
                [0, np.sin(_AX), np.cos(_AX)]], dtype="f4")
CAM_ROT = _RX @ _RY
LIGHT = np.array([-0.35, 0.85, 0.45], dtype="f4")
LIGHT = LIGHT / np.linalg.norm(LIGHT)
TILE = 3.2


@dataclass(frozen=True)
class MeshInstance:
    path: Path
    role: str
    offset: tuple[float, float, float]
    yaw: float = 0.0
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    tint: tuple[float, float, float] = (1.0, 1.0, 1.0)


@dataclass(frozen=True)
class TechBillboard:
    path: Path
    role: str
    offset: tuple[float, float, float]
    width: int


@dataclass
class PreviewScene:
    meshes: list[MeshInstance]
    tech: list[TechBillboard]
    conductors: list[tuple[tuple[float, float, float], tuple[float, float, float]]]

    @property
    def asset_paths(self):
        return [m.path for m in self.meshes] + [b.path for b in self.tech]

    @property
    def role_counts(self):
        counts = Counter(m.role for m in self.meshes)
        counts["tech"] = len(self.tech)
        return counts


def _gltf(rel):
    return MAP_GLTF_ROOT / rel


def _tech(name):
    return APPROVED_TECH_ROOT / f"{name}_frame_01.png"


def _hash(col, row, salt=0):
    n = (col * 374761393 + row * 668265263 + salt * 1442695041) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return n & 0xFFFFFFFF


def _world(col, row, y=0.0):
    return (-row * TILE, y, col * TILE)


def _inside_city(col, row):
    core = -27 <= col <= 27 and -18 <= row <= 18
    north_utility = -22 <= col <= 22 and -25 <= row <= -19
    south_utility = -25 <= col <= 25 and 19 <= row <= 24
    east_utility = 28 <= col <= 35 and -14 <= row <= 14
    west_utility = -35 <= col <= -28 and -14 <= row <= 14
    return core or north_utility or south_utility or east_utility or west_utility


def _is_road(col, row):
    return _inside_city(col, row) and (
        col % 4 == 0 or row % 4 == 0 or
        (abs(col) <= 5 and abs(row) <= 18) or
        (abs(row) <= 5 and abs(col) <= 28)
    )


def _road_mesh(col, row):
    vertical = _inside_city(col, row - 1) and _inside_city(col, row + 1) and col % 4 == 0
    horizontal = _inside_city(col - 1, row) and _inside_city(col + 1, row) and row % 4 == 0
    if vertical and horizontal:
        return _gltf("Roads/road-edgy-4-way-crossing-1.gltf"), 0.0
    if vertical:
        return _gltf("Roads/road-straight-1.gltf"), 0.0
    if horizontal:
        return _gltf("Roads/road-straight-1.gltf"), 90.0
    return _gltf("Asphalt/asphalt-plane.gltf"), 0.0


def _terrain_mesh(col, row):
    if row > 26 and -25 < col < 17:
        return _gltf(f"Water/water-{1 + (_hash(col, row, 1) % 4)}.gltf"), "water"
    if abs(col) > 39 or row < -30 or row > 31:
        return _gltf("Mountains/mountain-1.gltf"), "natural_ground"
    if (col + row) % 7 == 0:
        return _gltf(f"Forest/forest-{1 + (_hash(col, row, 2) % 4)}.gltf"), "natural_ground"
    return _gltf(f"Dirt/dirt-{1 + (_hash(col, row, 3) % 4)}.gltf"), "natural_ground"


def _building_scale(col, row):
    center = max(abs(col) / 27.0, abs(row) / 18.0)
    base_h = 1.0 + max(0.0, 1.0 - center) * 3.2
    jitter = ((_hash(col, row, 4) & 0xFF) / 255.0) * 0.9
    xz = 0.62 + ((_hash(col, row, 5) & 0x3F) / 255.0)
    return (xz, base_h + jitter, xz)


def _building_tint(col, row):
    palette = (
        (0.86, 0.95, 1.05), (1.05, 0.92, 0.84), (0.96, 1.02, 0.90),
        (1.05, 0.98, 0.90), (0.92, 0.92, 1.05), (1.00, 0.88, 1.00),
    )
    return palette[_hash(col, row, 6) % len(palette)]


def build_preview_scene():
    meshes = []
    tech = []
    conductors = []
    city_ground = _gltf("City/city-1.gltf")
    building = _gltf("Buildings/city-building.gltf")
    tree = _gltf("Trees/tree-3.gltf")
    stone = _gltf("Stones/stone-2.gltf")

    for col in range(-42, 43):
        for row in range(-33, 34):
            if _inside_city(col, row):
                meshes.append(MeshInstance(city_ground, "city_ground", _world(col, row)))
                if _is_road(col, row):
                    path, yaw = _road_mesh(col, row)
                    meshes.append(MeshInstance(path, "road", _world(col, row, 0.08), yaw=yaw))
                elif (col + row) % 2 == 0:
                    meshes.append(MeshInstance(
                        building, "building", _world(col, row, 0.10),
                        yaw=float((_hash(col, row, 7) % 4) * 90),
                        scale=_building_scale(col, row),
                        tint=_building_tint(col, row),
                    ))
            else:
                path, role = _terrain_mesh(col, row)
                meshes.append(MeshInstance(path, role, _world(col, row, -0.04)))
                if role == "natural_ground" and _hash(col, row, 8) % 100 < 7:
                    meshes.append(MeshInstance(
                        tree if _hash(col, row, 9) % 3 else stone,
                        "prop",
                        _world(col, row, 0.18),
                        yaw=float((_hash(col, row, 10) % 4) * 90),
                        scale=(1.7, 2.2, 1.7),
                    ))

    tech_specs = (
        ("nuclear_power", -34, -20, 168),
        ("coal_power", -16, -27, 150),
        ("solar_power", 18, -26, 160),
        ("natural_gas_peaker", 35, -10, 150),
        ("natural_gas_combined_cycle", 35, 11, 154),
        ("hydroelectric_power", -28, 27, 172),
        ("wind_power", -6, 25, 130),
    )
    hub_a = _world(0, -6, 1.15)
    hub_b = _world(0, 7, 1.15)
    for name, col, row, width in tech_specs:
        for dc in range(-3, 4):
            for dr in range(-3, 4):
                if max(abs(dc), abs(dr)) <= 3:
                    meshes.append(MeshInstance(_gltf("Asphalt/asphalt-plane.gltf"),
                                               "city_ground", _world(col + dc, row + dr, 0.05)))
        pos = _world(col, row, 1.0)
        tech.append(TechBillboard(_tech(name), "tech", pos, width))
        target = hub_a if row < 0 else hub_b
        conductors.append((pos, target))

    return PreviewScene(meshes=meshes, tech=tech, conductors=conductors)


_VERTEX_SHADER = """
#version 330
uniform mat3 cam_rot;
uniform float px_per_unit;
uniform vec2 img_size;
uniform vec2 origin;
in vec3 in_pos;
in vec3 in_normal;
in vec2 in_uv;
in vec3 in_offset;
in float in_yaw;
in vec3 in_scale;
in vec3 in_tint;
out vec2 v_uv;
out vec3 v_normal;
out vec3 v_tint;
void main() {
    float rad = radians(in_yaw);
    float c = cos(rad);
    float s = sin(rad);
    mat3 yaw_rot = mat3(c, 0.0, -s,
                         0.0, 1.0, 0.0,
                         s, 0.0, c);
    vec3 local = yaw_rot * (in_pos * in_scale);
    vec3 world = local + in_offset;
    vec3 cam = cam_rot * world;
    float sx = cam.x * px_per_unit;
    float sy = -cam.y * px_per_unit;
    float depth = -cam.y + 0.42 * cam.z;
    vec2 screen_px = vec2(sx, sy) - origin;
    float ndc_x = screen_px.x / img_size.x * 2.0 - 1.0;
    float ndc_y = 1.0 - screen_px.y / img_size.y * 2.0;
    gl_Position = vec4(ndc_x, ndc_y, -depth * 0.004, 1.0);
    v_uv = in_uv;
    v_normal = yaw_rot * in_normal;
    v_tint = in_tint;
}
"""

_FRAGMENT_SHADER = """
#version 330
uniform sampler2D tex;
uniform vec3 light_dir;
in vec2 v_uv;
in vec3 v_normal;
in vec3 v_tint;
out vec4 f_color;
void main() {
    vec4 texel = texture(tex, v_uv);
    if (texel.a < 0.01) discard;
    vec3 n = normalize(v_normal);
    float lambert = max(dot(n, light_dir), 0.0);
    float banded = floor(lambert * 3.0) / 3.0;
    float bright = 0.52 + 0.48 * banded;
    f_color = vec4(clamp(texel.rgb * bright * v_tint, 0.0, 1.0), texel.a);
}
"""


class _Batch:
    def __init__(self, ctx, prog, path, instances):
        pos, nrm, uv, idx, tex = load_gltf(path)
        verts = np.hstack([pos, nrm, uv]).astype("f4")
        self.vbo = ctx.buffer(verts.tobytes())
        self.ibo = ctx.buffer(idx.astype("i4").tobytes())
        data = np.array([
            [*m.offset, m.yaw, *m.scale, *m.tint] for m in instances
        ], dtype="f4")
        self.instance_count = len(data)
        self.instance_vbo = ctx.buffer(data.tobytes())
        self.vao = ctx.vertex_array(
            prog,
            [(self.vbo, "3f 3f 2f", "in_pos", "in_normal", "in_uv"),
             (self.instance_vbo, "3f 1f 3f 3f/i",
              "in_offset", "in_yaw", "in_scale", "in_tint")],
            self.ibo,
        )
        tex = tex.astype("u1")
        self.texture = ctx.texture((tex.shape[1], tex.shape[0]), 4, tex.tobytes())
        self.texture.filter = moderngl.NEAREST, moderngl.NEAREST

    def render(self):
        self.texture.use(0)
        self.vao.render(instances=self.instance_count)


def _project(point, px_per_unit, origin):
    cam = CAM_ROT @ np.array(point, dtype="f4")
    return (
        float(cam[0] * px_per_unit - origin[0]),
        float(-cam[1] * px_per_unit - origin[1]),
    )


def _scene_bounds(scene, px_per_unit):
    points = []
    for inst in scene.meshes:
        pos, _nrm, _uv, _idx, _tex = load_gltf(inst.path)
        mins = pos.min(axis=0) * np.array(inst.scale)
        maxs = pos.max(axis=0) * np.array(inst.scale)
        corners = np.array([
            (x, y, z)
            for x in (mins[0], maxs[0])
            for y in (mins[1], maxs[1])
            for z in (mins[2], maxs[2])
        ], dtype="f4")
        rad = np.deg2rad(inst.yaw)
        c, s = np.cos(rad), np.sin(rad)
        yaw = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype="f4")
        world = corners @ yaw.T + np.array(inst.offset, dtype="f4")
        cam = world @ CAM_ROT.T
        points.append(np.column_stack((cam[:, 0] * px_per_unit, -cam[:, 1] * px_per_unit)))
    pts = np.vstack(points)
    return pts.min(axis=0), pts.max(axis=0)


def render_preview(scene, out_path=DEFAULT_OUT, size=(1600, 1000)):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    rough_px = 7.5
    mn, mx = _scene_bounds(scene, rough_px)
    scene_size = mx - mn
    margin = 64
    px_per_unit = min((width - margin * 2) / scene_size[0],
                      (height - margin * 2) / scene_size[1]) * rough_px
    mn, mx = _scene_bounds(scene, px_per_unit)
    origin = (float(mn[0] - margin), float(mn[1] - margin))

    ctx = moderngl.create_standalone_context()
    try:
        prog = ctx.program(vertex_shader=_VERTEX_SHADER, fragment_shader=_FRAGMENT_SHADER)
        fbo = ctx.framebuffer(
            color_attachments=[ctx.texture((width, height), 4)],
            depth_attachment=ctx.depth_renderbuffer((width, height)),
        )
        fbo.use()
        ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        ctx.clear(0.075, 0.083, 0.095, 1.0)
        prog["cam_rot"].write(CAM_ROT.T.astype("f4").tobytes())
        prog["px_per_unit"].value = float(px_per_unit)
        prog["img_size"].value = (float(width), float(height))
        prog["origin"].value = origin
        prog["tex"].value = 0
        prog["light_dir"].value = tuple(LIGHT)

        grouped = defaultdict(list)
        for inst in scene.meshes:
            grouped[inst.path].append(inst)
        batches = [_Batch(ctx, prog, path, insts) for path, insts in grouped.items()]
        for batch in batches:
            batch.render()

        raw = fbo.read(components=4)
        image = Image.frombytes("RGBA", (width, height), raw).transpose(Image.FLIP_TOP_BOTTOM)
    finally:
        ctx.release()

    draw = ImageDraw.Draw(image, "RGBA")
    for a, b in scene.conductors:
        ax, ay = _project(a, px_per_unit, origin)
        bx, by = _project(b, px_per_unit, origin)
        draw.line((ax, ay, bx, by), fill=(88, 96, 110, 235), width=5)
        draw.line((ax, ay - 4, bx, by - 4), fill=(236, 196, 86, 230), width=2)
        draw.line((ax, ay + 4, bx, by + 4), fill=(154, 218, 236, 220), width=2)

    for billboard in sorted(scene.tech, key=lambda b: b.offset[0] + b.offset[2]):
        tech_img = Image.open(billboard.path).convert("RGBA")
        tech_img.thumbnail((billboard.width, billboard.width), Image.Resampling.LANCZOS)
        shadow = Image.new("RGBA", tech_img.size, (0, 0, 0, 0))
        alpha = tech_img.getchannel("A").filter(ImageFilter.GaussianBlur(4))
        shadow.putalpha(alpha.point(lambda v: int(v * 0.35)))
        x, y = _project(billboard.offset, px_per_unit, origin)
        px = int(x - tech_img.width / 2)
        py = int(y - tech_img.height + 14)
        image.alpha_composite(shadow, (px + 8, py + 10))
        image.alpha_composite(tech_img, (px, py))

    image.save(out_path)
    return out_path


def main(argv=None):
    argv = argv or sys.argv[1:]
    out_path = Path(argv[0]) if argv else DEFAULT_OUT
    scene = build_preview_scene()
    rendered = render_preview(scene, out_path)
    print(rendered)


if __name__ == "__main__":
    main()
