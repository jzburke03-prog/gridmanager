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
import os
from pathlib import Path

import numpy as np


def is_enabled():
    """Whether the opt-in 3D terrain pipeline is active. Shared by main.py
    (decides whether to create a GL context at all) and ui.iso_city (decides
    whether to skip drawing 2D tiles that now have a 3D equivalent)."""
    return os.environ.get("GRIDMANAGER_TERRAIN3D", "").strip().lower() in ("1", "true", "yes")


TW, TH = 16, 8  # MUST match ui.iso_city.TW/TH

MATERIALS = ("grass", "farm", "tree", "water", "mountain")
ROAD_MATERIALS = ("straight", "corner", "tee", "cross")
BUILDING_MATERIALS = ("house", "shop", "block", "midrise", "tower")

# Derived by rotating each baked mesh's default (yaw=0) open "arms" -- read
# from its .npz `pos` bounding box -- against the neighbor directions
# ui.road_network.assign_roles's docstring assigns to each role, using this
# module's own position formula (x = -row*TILE_SPACING, z = col*TILE_SPACING,
# so up/row-1 -> +X, down/row+1 -> -X, left/col-1 -> -Z, right/col+1 -> +Z)
# and the shader's yaw rotation. The shader builds `mat3(c,0,-s, 0,1,0, s,0,c)`
# from GLSL's *column-major* constructor argument order, which works out to
# the matrix [[c,0,s],[0,1,0],[-s,0,c]] -- i.e. new_x = x*cos(yaw) + z*sin(yaw),
# new_z = -x*sin(yaw) + z*cos(yaw). (An earlier fix pass used the transposed
# form new_x = x*cos - z*sin, new_z = x*sin + z*cos, which is rotation by
# -yaw instead of +yaw; that only happened to be invisible for the other
# roles and silently miscomputed tee_nw. A later independent re-derivation
# caught the transpose and confirmed the values below numerically against
# the baked tee.npz mesh.)
#   straight.npz default arms: +X, -X (the through-axis is X at yaw=0).
#     straight_ne wants up+down (+-X) -> yaw 0. straight_nw wants
#     left+right (+-Z) -> yaw 90 rotates the X arms onto Z.
#   corner.npz default arms: +X, +Z.
#     corner_ne wants up+right (+X,+Z) -> yaw 0 (exact match already).
#     corner_nw wants down+left (-X,-Z) -> yaw 180 (negates both arms).
#   tee.npz default arms: +X, -X, +Z (missing -Z).
#     tee_ne wants up+down+left (+X,-X,-Z) -> yaw 180 turns the missing arm
#     from -Z to +Z... i.e. rotating the {+X,-X,+Z} set by 180 gives
#     {-X,+X,-Z}, which matches. tee_nw wants left+right+down (-Z,+Z,-X) --
#     applying the correct (non-transposed) rotation, yaw 270 rotates
#     {+X,-X,+Z} to {+Z,-Z,-X}, which is an exact match. (yaw 90 gives
#     {-Z,+Z,+X} instead -- it has +X where -X is needed, so it's wrong.)
#   cross.npz is 4-way symmetric, so its yaw is irrelevant; 0 is as good as
#   any other value.
ROAD_ROLE_TO_SHAPE_YAW = {
    "straight_ne": ("straight", 0.0), "straight_nw": ("straight", 90.0),
    "corner_ne": ("corner", 0.0), "corner_nw": ("corner", 180.0),
    "tee_ne": ("tee", 180.0), "tee_nw": ("tee", 270.0),
    "cross": ("cross", 0.0),
}

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
    Combined with CAM_ROT/PX_PER_UNIT below (tuned to the same 2:1 ratio and
    absolute scale as iso_xy), the projected screen position is not just
    sign-matched but proportional to iso_xy(col, row) -- see
    test_build_instances_projection_matches_iso_xy_proportionally.

    Phase 2 also buckets `road` tiles (payload is a
    ui.road_network.RoadNetwork/ui.urban_blocks.UrbanRoad instance whose
    `.role` attribute is a role string like "straight_ne", mapped to a
    shape+yaw via ROAD_ROLE_TO_SHAPE_YAW) and `urban_block` tiles (payload is
    a ui.urban_blocks.UrbanBlock whose .buildings[0] is the archetype name,
    e.g. "house") into the ROAD_MATERIALS/BUILDING_MATERIALS buckets
    alongside the terrain ones.

    An unrecognized road role or building archetype raises ValueError rather
    than silently dropping the tile -- a previous silent-skip here is exactly
    what let every real road tile go undrawn undetected (the payload's
    `.role` wasn't even being read). Fully unrecognized top-level `kind`
    values (e.g. "park", "campus", "pad") are still silently skipped, since
    that's established Phase 1 behavior for tile kinds this module simply
    doesn't render.
    """
    buckets = {m: [] for m in MATERIALS + ROAD_MATERIALS + BUILDING_MATERIALS}
    for (col, row), (kind, extra) in tiles.items():
        x = -float(row) * TILE_SPACING
        z = float(col) * TILE_SPACING
        if kind in MATERIALS:
            buckets[kind].append((x, 0.0, z, 0.0))
        elif kind == "road":
            role = getattr(extra, "role", None)
            if role not in ROAD_ROLE_TO_SHAPE_YAW:
                raise ValueError(f"unrecognized road role: {role!r}")
            shape, yaw = ROAD_ROLE_TO_SHAPE_YAW[role]
            buckets[shape].append((x, 0.0, z, yaw))
        elif kind == "urban_block":
            archetype = extra.buildings[0]
            if archetype not in BUILDING_MATERIALS:
                raise ValueError(f"unrecognized building archetype: {archetype!r}")
            buckets[archetype].append((x, 0.0, z, 0.0))
    return {
        m: np.array(offsets, dtype="f4").reshape(-1, 4)
        for m, offsets in buckets.items()
        if offsets
    }


import moderngl
import pygame

LIGHT = np.array([-0.35, 0.8, 0.5])
LIGHT = LIGHT / np.linalg.norm(LIGHT)

# Camera tuned to exactly match ui.iso_city.iso_xy's 2:1 diamond projection
# ((col-row)*(TW//2), (col+row)*(TH//2)), NOT the true cube-diagonal
# isometric angle used by tools/bake_gltf_terrain.py's offline sprite bake
# (that tool bakes separate, already-shipped 2D sprite assets and is
# intentionally left alone -- see that file's own camera setup).
#
# Derivation: CAM_ROT = RX(_AX) @ RY(45deg) applied to a world offset
# (X, 0, Z) gives (after expanding the matrix product):
#   cam.x = (X+Z) * sqrt(2)/2
#   cam.y = -(Z-X) * sqrt(2)/2 * sin(_AX)
# build_instances() sets X = -row*TILE_SPACING, Z = col*TILE_SPACING, so
# X+Z = TILE_SPACING*(col-row) and Z-X = TILE_SPACING*(col+row). The vertex
# shader computes sx = cam.x*px_per_unit*zoom and
# screen_y = -cam.y*px_per_unit*zoom, giving:
#   sx        = TILE_SPACING * sqrt(2)/2 * px_per_unit * (col-row)
#   screen_y  = TILE_SPACING * sqrt(2)/2 * px_per_unit * sin(_AX) * (col+row)
# For this to be proportional to iso_xy's ((col-row)*8, (col+row)*4) -- a
# 2:1 ratio between the (col-row) and (col+row) coefficients -- we need
# sin(_AX) = 1/2, i.e. _AX = 30 degrees (not the ~35.264 degree true
# isometric angle). Matching the sx coefficient to iso_xy's absolute scale
# (TW//2 = 8) then pins px_per_unit = TW / (sqrt(2) * TILE_SPACING) (see
# PX_PER_UNIT below), which also makes the screen_y coefficient equal
# TH//2 = 4 exactly. This camera therefore DOES now produce iso_xy's exact
# 2:1 screen ratio and scale; the col/row swap-and-negate in
# build_instances() above additionally aligns the two axes' orientation.
_AY = np.deg2rad(45.0)
_AX = np.deg2rad(30.0)
_RY = np.array([[np.cos(_AY), 0, np.sin(_AY)],
                [0, 1, 0],
                [-np.sin(_AY), 0, np.cos(_AY)]])
_RX = np.array([[1, 0, 0],
                [0, np.cos(_AX), -np.sin(_AX)],
                [0, np.sin(_AX), np.cos(_AX)]])
CAM_ROT = _RX @ _RY

# px_per_unit that makes the camera's projected scale match iso_xy's
# TW//2 = 8 px per (col-row) unit exactly (see derivation above).
PX_PER_UNIT = TW / (2 ** 0.5 * TILE_SPACING)


def camera_basis():
    """World-space basis for a camera-facing billboard, derived once from
    the fixed CAM_ROT. right_world/up_world span the billboard's plane;
    facing_normal points back toward the camera (used so a billboard's
    fragment lighting reads as close to fully lit/undistorted as the shared
    banded-lighting shader allows, keeping the plant sprite's original
    colors close to their 2D appearance).

    facing_normal points toward the camera, which lands in the shared
    banded-lighting shader's middle band (~70% brightness) rather than full
    brightness -- billboarded plants will read visibly darker than their 2D
    counterparts until Phase 3b addresses this (e.g. an unlit/full-bright
    shader path for billboards).

    up_world is pinned to world-vertical (0, 1, 0) -- billboards stand
    upright, matching the existing 2D sprites' "flat cutout standing on the
    ground" convention -- rather than the camera's true local "up" axis.
    CAM_ROT tilts the camera down by 30 degrees (see the CAM_ROT derivation
    comment above), so the camera's raw local up/forward directions are NOT
    orthogonal to world-vertical: transforming camera-space (0,0,-1)
    straight into world space via CAM_ROT.T (valid since CAM_ROT is
    orthonormal, so its inverse is its transpose) gives a vector with
    dot(up_world, that) == -sin(30deg) == -0.5, nowhere near the 0 an
    orthonormal basis requires. So this uses the standard cylindrical/
    vertical-billboard construction instead: derive right_world as the
    horizontal axis perpendicular to both world-up and the camera's raw
    view direction (a cross product with world-up is always perpendicular
    to world-up by construction), then re-derive facing_normal as
    cross(right_world, up_world) so all three vectors end up mutually
    orthogonal by construction rather than merely close.  The resulting
    facing_normal is the raw camera direction's horizontal projection --
    it points toward the camera's side of the scene with no vertical
    component, which is the correct "faces the camera" direction for a
    billboard whose up edge must stay world-vertical."""
    inv = CAM_ROT.T
    up_world = np.array([0.0, 1.0, 0.0])
    raw_facing = inv @ np.array([0.0, 0.0, -1.0])
    right_world = np.cross(raw_facing, up_world)
    right_world = right_world / np.linalg.norm(right_world)
    # cross(right_world, up_world) (not up x right) so facing_normal points
    # back toward the camera rather than into the scene -- verified
    # numerically: with CAM_ROT's fixed _AY=45/_AX=30, this yields
    # (-0.7071, 0, 0.7071), matching the horizontal projection of
    # CAM_ROT.T @ (0,0,1) (the true toward-camera direction).
    facing_normal = np.cross(right_world, up_world)
    facing_normal = facing_normal / np.linalg.norm(facing_normal)
    return right_world, up_world, facing_normal


def billboard_quad(width_world, height_world, basis=None):
    """A single camera-facing quad: bottom edge at local y=0 (ground), top
    edge at y=height_world, centered on x=0. `basis` overrides
    camera_basis() for testing; production callers use the default.

    NOTE for whoever adds sprite-pixel-height -> world-unit conversion
    (e.g. a future build_plant_billboards()): unlike right_world, up_world
    is pinned to world-vertical rather than being perpendicular to the
    camera's view direction, so vertical extents get foreshortened by
    cos(_AX) = cos(30deg) ~= 0.866 on screen under this camera's pitch. A
    caller that wants a specific on-screen pixel height should divide the
    world-unit height by that factor before passing it in here."""
    right_world, up_world, facing_normal = (
        basis if basis is not None else camera_basis()
    )
    half_w = width_world / 2.0
    bottom_left = -half_w * right_world
    bottom_right = half_w * right_world
    top_left = bottom_left + height_world * up_world
    top_right = bottom_right + height_world * up_world
    pos = np.array([bottom_left, bottom_right, top_right, top_left], dtype="f4")
    nrm = np.tile(facing_normal.astype("f4"), (4, 1))
    uv = np.array([[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]], dtype="f4")
    idx = np.array([[0, 1, 2], [0, 2, 3]], dtype="i4")
    return pos, nrm, uv, idx


# Correction factor for build_plant_billboards()'s height conversion -- see
# billboard_quad()'s docstring note above: up_world is pinned to
# world-vertical rather than being perpendicular to the camera's view
# direction, so a billboard's vertical extent renders on-screen at only
# cos(30deg) of what its horizontal extent would at the same world-unit
# size. Dividing the height conversion by this factor (in addition to
# PX_PER_UNIT) cancels that foreshortening so the billboard's on-screen
# aspect ratio matches the source sprite's pixel aspect ratio, same as its
# width does.
_VERTICAL_FORESHORTENING = np.cos(_AX)


def build_plant_billboards(plants):
    """Pure PlantSite-list -> billboard placement data. No GL calls. Uses
    the same (-row*TILE_SPACING, 0, col*TILE_SPACING) world convention as
    build_instances(), NOT the clamped 2D sx/sy IsoCity uses for its own
    on-screen anchor (see Phase 3a design doc's scope note).

    height_world divides by PX_PER_UNIT * _VERTICAL_FORESHORTENING (not
    just PX_PER_UNIT, unlike width_world) to counteract the camera's
    vertical foreshortening described above."""
    billboards = []
    for site in plants:
        w, h = site.sprite.get_size()
        billboards.append({
            "key": site.key,
            "offset": (-float(site.row) * TILE_SPACING, 0.0, float(site.col) * TILE_SPACING),
            "width_world": w / PX_PER_UNIT,
            "height_world": h / (PX_PER_UNIT * _VERTICAL_FORESHORTENING),
            "surface": site.sprite,
        })
    return billboards


def _surface_to_rgba_array(surface):
    """Shared pygame-Surface -> (h, w, 4) uint8 RGBA array conversion, used
    by both create_dynamic_texture() (which wraps it in a moderngl.Texture)
    and load_billboards() (which needs the raw array for GLMesh.__init__)."""
    w, h = surface.get_size()
    data = pygame.image.tostring(surface.convert_alpha(), "RGBA", False)
    return np.frombuffer(data, dtype="u1").reshape(h, w, 4)


def create_dynamic_texture(ctx, surface):
    """Runtime GL texture from a pygame Surface (plant sprites are drawn
    procedurally at bake time, not baked offline like terrain/road/building
    meshes -- there is no .npz for these)."""
    array = _surface_to_rgba_array(surface)
    h, w = array.shape[0], array.shape[1]
    tex = ctx.texture((w, h), 4, array.tobytes())
    tex.filter = moderngl.NEAREST, moderngl.NEAREST
    return tex

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

    def release(self):
        """Release this mesh's GL resources (buffers, VAO, texture). Needed
        by callers (e.g. main.py's per-layout-change billboard rebuild) that
        replace a list of GLMesh instances with a new one -- without this,
        every rebuild leaks a VBO/IBO/instance VBO/VAO/texture set per mesh,
        matching the same "release old before creating new" discipline
        main.py already applies to its terrain3d FBO's attachments."""
        self.vbo.release()
        self.ibo.release()
        self.instance_vbo.release()
        self.vao.release()
        self.texture.release()


def load_meshes(ctx, prog, mesh_dir=MESH_DIR):
    meshes = {}
    for material in MATERIALS:
        data = np.load(mesh_dir / f"{material}.npz")
        meshes[material] = GLMesh(ctx, prog, data["pos"], data["nrm"],
                                    data["uv"], data["idx"], data["tex"])
    for shape in ROAD_MATERIALS:
        data = np.load(mesh_dir / "roads" / f"{shape}.npz")
        meshes[shape] = GLMesh(ctx, prog, data["pos"], data["nrm"],
                                 data["uv"], data["idx"], data["tex"])
    for archetype in BUILDING_MATERIALS:
        data = np.load(mesh_dir / "buildings" / f"{archetype}.npz")
        meshes[archetype] = GLMesh(ctx, prog, data["pos"], data["nrm"],
                                     data["uv"], data["idx"], data["tex"])
    return meshes


def load_billboards(ctx, prog, billboards):
    """One GLMesh per plant billboard, each with its own single-quad
    geometry (sized/facing per its `width_world`/`height_world` via
    billboard_quad()) and its own runtime texture (from its `surface`), each
    carrying exactly one instance at the plant's world offset with yaw=0.0
    (billboards are camera-facing by construction, not by per-instance
    rotation)."""
    meshes = []
    for b in billboards:
        pos, nrm, uv, idx = billboard_quad(b["width_world"], b["height_world"])
        tex_data = _surface_to_rgba_array(b["surface"])
        mesh = GLMesh(ctx, prog, pos, nrm, uv, idx, tex_data)
        mesh.set_instances(np.array([[*b["offset"], 0.0]], dtype="f4"))
        meshes.append(mesh)
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


def draw(ctx, prog, meshes, fbo, camera, px_per_unit=PX_PER_UNIT, ambient=0.55,
         billboard_meshes=None):
    """Draws the material meshes, then any billboard_meshes (e.g. from
    load_billboards()) in the SAME pass -- same fbo, same depth state, no
    ctx.clear() between the two groups -- so billboards are properly
    depth-tested against the terrain/road/building geometry rather than
    composited on top of it. `billboard_meshes` defaults to None so existing
    callers that don't pass it behave exactly as before."""
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
    for mesh in (billboard_meshes or []):
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
