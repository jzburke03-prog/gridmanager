"""Real-time 3D terrain rendering: instanced voxel meshes for countryside
tiles (grass/farm/tree/water/mountain), composited under the existing 2D
sprite city. See docs/superpowers/specs/2026-08-05-realtime-3d-terrain-
phase1-design.md.

This module is imported by main.py only; it does not import ui.iso_city, to
avoid a circular import (same discipline as ui.voxel_terrain).

Per-frame cost note: draw() renders to an offscreen FBO, and the
read_rgba() + to_surface() pair that follows each draw() performs a
synchronous GPU->CPU framebuffer readback (fbo.read()) every frame, measured
at roughly 2-3ms on typical hardware. This blocks the CPU until the GPU
finishes rendering that frame's terrain -- there is no batching, double
buffering, or async (PBO-backed) readback in Phase 1. This is a known,
accepted tradeoff for now; a future phase could hide the stall by reading
back a frame late (double-buffered FBOs) or avoiding the CPU round-trip
entirely by compositing on the GPU instead of blitting into a pygame
Surface.
"""
from pathlib import Path

import numpy as np

TW, TH = 16, 8  # MUST match ui.iso_city.TW/TH

MATERIALS = ("grass", "farm", "tree", "water", "mountain")

# Baked ground meshes (energy_grid_game/assets/terrain3d/*.npz) each span
# -1.6..+1.6 on X and Z -- a 3.2-unit footprint -- so instances must be
# spaced 3.2 world units apart per tile to avoid overlapping their
# neighbors. tree.npz is a smaller decoration-prop mesh with no separate
# ground plane (a deliberate Phase 1 simplification) and is placed on the
# same grid spacing as everything else.
TILE_SPACING = 3.2

MESH_DIR = Path(__file__).resolve().parents[1] / "assets" / "terrain3d"


def build_instances(tiles):
    """Pure tile-dict -> per-material instance offsets. No GL calls.

    `tiles` is shaped like IsoCity.tiles: {(col, row): (kind, extra)}.
    Returns {material: (N,4) float32 array of [x, y, z, yaw_degrees]} --
    every material uses this 4-column format (Phase 2 generalization),
    even terrain materials that never rotate (yaw always 0.0 for them).
    col and row are swapped (col feeds world Z, row feeds world -X) so the
    projected result matches ui.iso_city.iso_xy's (col - row, col + row)
    diamond axes -- see test_build_instances_matches_iso_xy_sign_convention.
    """
    buckets = {material: [] for material in MATERIALS}
    for (col, row), (kind, _extra) in tiles.items():
        if kind in buckets:
            buckets[kind].append(
                (-float(row) * TILE_SPACING, 0.0, float(col) * TILE_SPACING, 0.0))
    return {
        material: np.array(offsets, dtype="f4").reshape(-1, 4)
        for material, offsets in buckets.items()
        if offsets
    }


import moderngl
import pygame

LIGHT = np.array([-0.35, 0.8, 0.5])
LIGHT = LIGHT / np.linalg.norm(LIGHT)

# Same fixed isometric camera used throughout this project (see
# tools/bake_gltf_terrain.py): rotate 45 deg around Y, then ~35.264 deg
# around X, dropped to an orthographic screen. This is the same fixed
# isometric camera used throughout this project, chosen to visually match
# the existing iso_xy screen orientation (the col/row swap-and-negate in
# build_instances() above is what actually aligns the two axes; this
# camera does not by itself produce a 2:1 screen ratio).
_AY = np.deg2rad(45.0)
_AX = np.deg2rad(35.264)
_RY = np.array([[np.cos(_AY), 0, np.sin(_AY)],
                [0, 1, 0],
                [-np.sin(_AY), 0, np.cos(_AY)]])
_RX = np.array([[1, 0, 0],
                [0, np.cos(_AX), -np.sin(_AX)],
                [0, np.sin(_AX), np.cos(_AX)]])
CAM_ROT = _RX @ _RY

_VERTEX_SHADER = """
#version 330
uniform mat3 cam_rot;
uniform float px_per_unit;
uniform float zoom;
uniform vec2 img_size;
uniform vec2 origin;
in vec3 in_pos;
in vec3 in_normal;
in vec2 in_uv;
in vec3 in_offset;
in float in_yaw;
out vec2 v_uv;
out vec3 v_normal;
void main() {
    float rad = radians(in_yaw);
    float c = cos(rad);
    float s = sin(rad);
    mat3 yaw_rot = mat3(c, 0.0, -s,
                         0.0, 1.0, 0.0,
                         s, 0.0, c);
    vec3 local = yaw_rot * in_pos;
    vec3 normal = yaw_rot * in_normal;
    vec3 world = local + in_offset;
    vec3 cam = cam_rot * world;
    float sx = cam.x * px_per_unit * zoom;
    float sy = -cam.y * px_per_unit * zoom;
    float depth = -cam.y + 0.35 * cam.z;
    vec2 screen_px = vec2(sx, sy) - origin;
    float ndc_x = screen_px.x / img_size.x * 2.0 - 1.0;
    // Inverted (vs. the "1.0 - ..." convention) on purpose: FBO reads are
    // bottom-up, so flipping the sign here bakes that correction into the
    // projection instead of paying for a per-frame CPU
    // pygame.transform.flip() in to_surface() below.
    float ndc_y = screen_px.y / img_size.y * 2.0 - 1.0;
    gl_Position = vec4(ndc_x, ndc_y, -depth * 0.01, 1.0);
    v_uv = in_uv;
    v_normal = normal;
}
"""

# Lighting is quantized into 3 discrete bands (not a smooth Lambert term) --
# this is what gives the flat/voxel look the design calls for, deliberately
# different from tools/bake_gltf_terrain.py's smooth-shaded sprite bake.
_FRAGMENT_SHADER = """
#version 330
uniform sampler2D tex;
uniform vec3 light_dir;
uniform float ambient;
in vec2 v_uv;
in vec3 v_normal;
out vec4 f_color;
void main() {
    vec4 texel = texture(tex, v_uv);
    if (texel.a < 0.01) discard;
    vec3 n = normalize(v_normal);
    float lambert = max(dot(n, light_dir), 0.0);
    float banded = floor(lambert * 3.0) / 3.0;
    float bright = ambient + (1.0 - ambient) * banded;
    f_color = vec4(texel.rgb * bright, texel.a);
}
"""


def create_program(ctx):
    return ctx.program(vertex_shader=_VERTEX_SHADER, fragment_shader=_FRAGMENT_SHADER)


class GLMesh:
    def __init__(self, ctx, prog, pos, nrm, uv, idx, tex):
        verts = np.hstack([pos, nrm, uv]).astype("f4")
        self.vbo = ctx.buffer(verts.tobytes())
        self.ibo = ctx.buffer(idx.astype("i4").tobytes())
        self.instance_vbo = ctx.buffer(reserve=16)  # 1 instance (x,y,z,yaw) placeholder
        self.vao = ctx.vertex_array(
            prog,
            [(self.vbo, "3f 3f 2f", "in_pos", "in_normal", "in_uv"),
             (self.instance_vbo, "3f 1f/i", "in_offset", "in_yaw")],
            self.ibo,
        )
        tex_h, tex_w = tex.shape[0], tex.shape[1]
        self.texture = ctx.texture((tex_w, tex_h), 4, tex.astype("u1").tobytes())
        self.texture.filter = moderngl.NEAREST, moderngl.NEAREST
        self.instance_count = 0

    def set_instances(self, offsets):
        data = offsets.astype("f4").tobytes()
        self.instance_vbo.orphan(max(len(data), 16))
        if len(data):
            self.instance_vbo.write(data)
        self.instance_count = len(offsets)

    def render(self):
        if self.instance_count:
            self.texture.use(0)
            self.vao.render(instances=self.instance_count)


def load_meshes(ctx, prog, mesh_dir=MESH_DIR):
    meshes = {}
    for material in MATERIALS:
        data = np.load(mesh_dir / f"{material}.npz")
        meshes[material] = GLMesh(ctx, prog, data["pos"], data["nrm"],
                                    data["uv"], data["idx"], data["tex"])
    return meshes


def upload_instances(ctx, meshes, instances):
    empty = np.zeros((0, 4), dtype="f4")
    for material, mesh in meshes.items():
        mesh.set_instances(instances.get(material, empty))


def create_framebuffer(ctx, size):
    size = (max(1, size[0]), max(1, size[1]))
    return ctx.framebuffer(
        color_attachments=[ctx.texture(size, 4)],
        depth_attachment=ctx.depth_renderbuffer(size),
    )


def draw(ctx, prog, meshes, fbo, camera, px_per_unit=26.0, ambient=0.55):
    fbo.use()
    ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
    ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
    ctx.clear(0.10, 0.11, 0.13, 1.0)
    prog["cam_rot"].write(CAM_ROT.T.astype("f4").tobytes())
    prog["px_per_unit"].value = float(px_per_unit)
    prog["zoom"].value = float(camera.zoom)
    prog["img_size"].value = (float(fbo.size[0]), float(fbo.size[1]))
    prog["origin"].value = (float(camera.center[0]), float(camera.center[1]))
    prog["tex"].value = 0
    prog["light_dir"].value = tuple(LIGHT.astype("f4"))
    prog["ambient"].value = float(ambient)
    for mesh in meshes.values():
        mesh.render()


def read_rgba(fbo):
    return fbo.read(components=4), fbo.size


def to_surface(rgba_bytes, size):
    """Pure pygame conversion, no GL involved. FBO reads are bottom-up, but
    unlike tools/bake_gltf_terrain.py (which flips via PIL's
    FLIP_TOP_BOTTOM after the fact), the vertical flip here is baked into
    _VERTEX_SHADER's ndc_y sign convention, so no per-frame CPU
    pygame.transform.flip() is needed."""
    return pygame.image.frombuffer(rgba_bytes, size, "RGBA")
