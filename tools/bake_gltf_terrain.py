#!/usr/bin/env python3
"""Bake curated glTF meshes from newassets/terrain/gltf/ into isometric PNG
sprites the pygame renderer can blit, matching the game's diamond tile
projection (TW=16, TH=8), using the same fixed isometric camera used
throughout this project, chosen to visually match the existing iso_xy
screen orientation.

Parses the glTF JSON + .bin buffer by hand (numpy + struct: no pygltflib
needed, this handles every mesh in the pack so far), then renders with a real
GPU pipeline (moderngl, standalone/headless context -- no window, no pygame
display needed) through the SAME fixed true-isometric camera the original
hand-rolled software rasterizer used, so output content/placement is
unchanged, just properly lit/shaded/antialiased. This is a bake-TIME-only
tool: it runs once per asset offline and commits PNGs; the game never touches
glTF or a GL context at runtime, so this doesn't add any runtime dependency
or risk to iso_city.py's pure-2D pygame rendering.
"""
import json
import struct
import sys
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "newassets" / "terrain" / "gltf"
OUT = ROOT / "energy_grid_game" / "assets" / "terrain"

COMP_SIZES = {5126: (4, "f"), 5123: (2, "H"), 5125: (4, "I")}
TYPE_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

# True-isometric camera: rotate 45 deg around Y, then ~35.264 deg around X,
# then drop to an orthographic screen. This is the same fixed isometric
# camera used throughout this project, chosen to visually match iso_xy's
# (col-row, col+row)/2 diamond orientation used everywhere else in the
# renderer (not a literal 2:1 screen ratio).
_AY = np.deg2rad(45.0)
_AX = np.deg2rad(35.264)
_RY = np.array([[np.cos(_AY), 0, np.sin(_AY)],
                [0, 1, 0],
                [-np.sin(_AY), 0, np.cos(_AY)]])
_RX = np.array([[1, 0, 0],
                [0, np.cos(_AX), -np.sin(_AX)],
                [0, np.sin(_AX), np.cos(_AX)]])
_CAM = _RX @ _RY


def load_gltf(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    bin_path = path.parent / doc["buffers"][0]["uri"]
    buf = bin_path.read_bytes()

    def accessor(idx):
        acc = doc["accessors"][idx]
        bv = doc["bufferViews"][acc["bufferView"]]
        size, fmt = COMP_SIZES[acc["componentType"]]
        n = TYPE_COUNTS[acc["type"]]
        off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
        count = acc["count"]
        data = struct.unpack_from(f"<{count * n}{fmt}", buf, off)
        arr = np.array(data, dtype=np.float64 if fmt == "f" else np.int64)
        return arr.reshape(count, n) if n > 1 else arr

    prim = doc["meshes"][0]["primitives"][0]
    pos = accessor(prim["attributes"]["POSITION"])
    nrm = accessor(prim["attributes"]["NORMAL"])
    uv = accessor(prim["attributes"]["TEXCOORD_0"])
    idx = accessor(prim["indices"]).reshape(-1, 3)
    tex_path = path.parent / doc["images"][0]["uri"]
    tex = np.asarray(Image.open(tex_path).convert("RGBA"), dtype=np.float64)
    return pos, nrm, uv, idx, tex


LIGHT = np.array([-0.35, 0.8, 0.5])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


# -- GPU renderer (Phase 1) -------------------------------------------------
# Standalone/headless moderngl context: no window, no pygame display. This
# matters because iso_city.py's tests call _bake() directly without a live
# pygame display in some paths -- a bake tool that required a display would
# be a needless coupling. Created lazily and reused across bake() calls.
_ctx = None
_prog = None

_VERTEX_SHADER = """
#version 330
uniform mat3 cam_rot;
uniform float px_per_unit;
uniform vec2 img_size;
uniform vec2 origin;
in vec3 in_pos;
in vec3 in_normal;
in vec2 in_uv;
out vec2 v_uv;
out vec3 v_normal;
void main() {
    vec3 cam = cam_rot * in_pos;
    float sx = cam.x * px_per_unit;
    float sy = -cam.y * px_per_unit;
    float depth = -cam.y + 0.35 * cam.z;
    vec2 screen_px = vec2(sx, sy) - origin;
    float ndc_x = screen_px.x / img_size.x * 2.0 - 1.0;
    float ndc_y = 1.0 - screen_px.y / img_size.y * 2.0;
    gl_Position = vec4(ndc_x, ndc_y, -depth * 0.05, 1.0);
    v_uv = in_uv;
    v_normal = in_normal;
}
"""

# Lambert term is dotted against the OBJECT-space normal (not camera-rotated)
# -- matches the original software rasterizer exactly: since every mesh is
# baked from the same fixed camera, a light fixed in object space reads as
# "always lit from the same relative direction" across the whole asset set,
# same as before.
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
    float bright = ambient + (1.0 - ambient) * lambert;
    f_color = vec4(texel.rgb * bright, texel.a);
}
"""


def _get_ctx():
    global _ctx, _prog
    if _ctx is None:
        _ctx = moderngl.create_standalone_context()
        _ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
        _ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        _prog = _ctx.program(vertex_shader=_VERTEX_SHADER, fragment_shader=_FRAGMENT_SHADER)
    return _ctx, _prog


def load_obj(path):
    """Parse a MagicaVoxel-exported .obj + .mtl (e.g. City Voxel Pack): plain
    Wavefront OBJ referencing a 256x1 palette-strip PNG via map_Kd. No new
    dependency -- OBJ is plain text, same hand-rolled-parser spirit as
    load_gltf's manual glTF decode. Returns the same (pos, nrm, uv, idx, tex)
    contract as load_gltf so both feed the same GPU renderer below."""
    verts, normals, uvs, faces = [], [], [], []
    tex_name = None
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts:
            continue
        tag = parts[0]
        if tag == "v":
            verts.append([float(x) for x in parts[1:4]])
        elif tag == "vn":
            normals.append([float(x) for x in parts[1:4]])
        elif tag == "vt":
            uvs.append([float(x) for x in parts[1:3]])
        elif tag == "f":
            idx_triplets = [p.split("/") for p in parts[1:]]
            # fan-triangulate any face with more than 3 verts
            for i in range(1, len(idx_triplets) - 1):
                faces.append((idx_triplets[0], idx_triplets[i], idx_triplets[i + 1]))
        elif tag == "mtllib":
            mtl_path = path.parent / parts[1]
            if mtl_path.exists():
                for mline in mtl_path.read_text(encoding="utf-8").splitlines():
                    if mline.strip().startswith("map_Kd"):
                        tex_name = mline.split(None, 1)[1].strip()

    verts = np.array(verts, dtype=np.float64)
    normals = np.array(normals or [[0.0, 1.0, 0.0]], dtype=np.float64)
    uvs = np.array(uvs or [[0.0, 0.0]], dtype=np.float64)

    pos_out, nrm_out, uv_out, idx_out = [], [], [], []
    for tri in faces:
        for comp in tri:
            vi = int(comp[0]) - 1
            ti = int(comp[1]) - 1 if len(comp) > 1 and comp[1] else 0
            ni = int(comp[2]) - 1 if len(comp) > 2 and comp[2] else 0
            idx_out.append(len(pos_out))
            pos_out.append(verts[vi])
            uv_out.append(uvs[ti] if ti < len(uvs) else [0.0, 0.0])
            nrm_out.append(normals[ni] if ni < len(normals) else [0.0, 1.0, 0.0])

    pos_arr = np.array(pos_out, dtype=np.float64)
    nrm_arr = np.array(nrm_out, dtype=np.float64)
    uv_arr = np.array(uv_out, dtype=np.float64)
    idx_arr = np.arange(len(idx_out), dtype=np.int64).reshape(-1, 3)

    tex_path = path.parent / (tex_name or "texture.png")
    tex = np.asarray(Image.open(tex_path).convert("RGBA"), dtype=np.float64)
    return pos_arr, nrm_arr, uv_arr, idx_arr, tex


def _bake_mesh(pos, nrm, uv, idx, tex, out_path, px_per_unit=26.0, ambient=0.55,
              yaw_offset_deg=0.0):
    """Shared GPU render core: place already-loaded mesh arrays through the
    fixed true-isometric camera and save a cropped, alpha-matted PNG. Used by
    both bake() (glTF) and bake_obj() (MagicaVoxel .obj) so the camera/shader
    path is identical regardless of source format."""
    ctx, prog = _get_ctx()

    if yaw_offset_deg:
        a = np.deg2rad(yaw_offset_deg)
        yaw = np.array([[np.cos(a), 0, np.sin(a)],
                        [0, 1, 0],
                        [-np.sin(a), 0, np.cos(a)]])
        pos = pos @ yaw.T
        nrm = nrm @ yaw.T

    # Bbox sizing stays in numpy: cheap (vertex-count-sized, not pixel-sized)
    # and reuses the exact same math as the camera uniforms below, so the
    # rendered content lands inside the FBO we allocate.
    cam = pos @ _CAM.T
    sx = cam[:, 0] * px_per_unit
    sy = -cam[:, 1] * px_per_unit
    pad = 4
    min_x, max_x = sx.min() - pad, sx.max() + pad
    min_y, max_y = sy.min() - pad, sy.max() + pad
    w = max(1, int(np.ceil(max_x - min_x)))
    h = max(1, int(np.ceil(max_y - min_y)))

    verts = np.hstack([pos, nrm, uv]).astype("f4")
    vbo = ctx.buffer(verts.tobytes())
    ibo = ctx.buffer(idx.astype("i4").tobytes())
    vao = ctx.vertex_array(
        prog, [(vbo, "3f 3f 2f", "in_pos", "in_normal", "in_uv")], ibo)

    tex_h, tex_w = tex.shape[0], tex.shape[1]
    gl_tex = ctx.texture((tex_w, tex_h), 4, tex.astype("u1").tobytes())
    gl_tex.filter = moderngl.LINEAR, moderngl.LINEAR
    gl_tex.use(0)

    fbo = ctx.framebuffer(
        color_attachments=[ctx.texture((w, h), 4)],
        depth_attachment=ctx.depth_renderbuffer((w, h)),
    )
    fbo.use()
    ctx.clear(0.0, 0.0, 0.0, 0.0)

    # GLSL mat3 uniforms are column-major; numpy arrays are row-major (C
    # order) by default, so transpose before flattening to bytes -- otherwise
    # the shader silently receives cam_rot.T instead of cam_rot.
    prog["cam_rot"].write(_CAM.T.astype("f4").tobytes())
    prog["px_per_unit"].value = float(px_per_unit)
    prog["img_size"].value = (float(w), float(h))
    prog["origin"].value = (float(min_x), float(min_y))
    prog["tex"].value = 0
    prog["light_dir"].value = tuple(LIGHT.astype("f4"))
    prog["ambient"].value = float(ambient)

    vao.render()

    data = fbo.read(components=4)
    img = Image.frombytes("RGBA", (w, h), data).transpose(Image.FLIP_TOP_BOTTOM)

    vao.release()
    vbo.release()
    ibo.release()
    gl_tex.release()
    fbo.release()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return w, h


def bake(gltf_path, out_path, px_per_unit=26.0, ambient=0.55, yaw_offset_deg=0.0):
    """Render one glTF mesh -- see _bake_mesh. `yaw_offset_deg` rotates the
    MESH (not the camera) around Y before projection -- e.g. baking a
    road-straight piece at 0 and 90 gives the two orientations a real
    orthogonal street grid needs, still through the same locked camera."""
    pos, nrm, uv, idx, tex = load_gltf(gltf_path)
    return _bake_mesh(pos, nrm, uv, idx, tex, out_path, px_per_unit, ambient, yaw_offset_deg)


def bake_obj(obj_path, out_path, px_per_unit=26.0, ambient=0.55, yaw_offset_deg=0.0):
    """Render one MagicaVoxel-exported .obj mesh -- see _bake_mesh."""
    pos, nrm, uv, idx, tex = load_obj(obj_path)
    return _bake_mesh(pos, nrm, uv, idx, tex, out_path, px_per_unit, ambient, yaw_offset_deg)


# Curated bake list: one flat/base tile per biome ground, a couple of edge
# transition pieces, and a few decoration props. Keeps the bake fast and the
# shipped asset count sane instead of baking all ~1900 source meshes.
JOBS = [
    ("Desert/desert-1.gltf", "desert/ground_1.png"),
    ("Desert/desert-2.gltf", "desert/ground_2.png"),
    ("Cactus/cactus-1.gltf", "desert/cactus_1.png"),
    ("Cactus/cactus-2.gltf", "desert/cactus_2.png"),
    ("Bones/bones-1.gltf", "desert/bones_1.png"),
    ("Forest/forest-1.gltf", "forest/ground_1.png"),
    ("Forest/forest-2.gltf", "forest/ground_2.png"),
    ("Trees/tree-1.gltf", "forest/tree_1.png"),
    ("Trees/tree-2.gltf", "forest/tree_2.png"),
    ("Trees/tree-3.gltf", "forest/tree_3.png"),
    ("Bushes/bush-1.gltf", "forest/bush_1.png"),
    ("Dirt/dirt-1.gltf", "plains/ground_1.png"),
    ("Dirt/dirt-2.gltf", "plains/ground_2.png"),
    ("Stones/stone-1.gltf", "plains/stone_1.png"),
    ("Stones/stone-2.gltf", "plains/stone_2.png"),
    ("Mountains/mountain-1.gltf", "mountains/peak_1.png"),
    ("Water/water-1.gltf", "coast/water_1.png"),
    ("Water/water-2.gltf", "coast/water_2.png"),
    ("City/city-1.gltf", "downtown/ground_1.png"),
    ("Buildings/city-building.gltf", "downtown/building_1.png"),
    ("Roads/road-straight-1.gltf", "downtown/road_straight_a.png"),
    ("Roads/road-straight-1.gltf", "downtown/road_straight_b.png", 90.0),
    ("Roads/road-rounded-4-way-crossing-1.gltf", "downtown/road_crossing.png"),
]

# City Voxel Pack (MagicaVoxel .obj export, shared 256x1 palette texture):
# real additional downtown-building variety, layered alongside (not replacing)
# the existing curated town-pack buildings from newassets/"generating and
# town" -- those are already hand-rendered, high-quality, and correctly
# sourced for this purpose, nothing to improve there. This is genuinely new
# material the terrain glTF kit doesn't have (it ships exactly one generic
# building block).
OBJ_SRC = ROOT / "newassets" / "City Voxel Pack" / "OBJ"
OBJ_JOBS = [
    ("Building02.obj", "downtown/building_2.png"),
    ("Building03.obj", "downtown/building_3.png"),
    ("Building04.obj", "downtown/building_4.png"),
    ("Building05.obj", "downtown/building_5.png"),
]


def main():
    jobs = [j for j in JOBS if j]
    for job in jobs:
        rel_src, rel_out = job[0], job[1]
        yaw = job[2] if len(job) > 2 else 0.0
        src = SRC / rel_src
        if not src.exists():
            print("SKIP (missing)", rel_src)
            continue
        out = OUT / rel_out
        w, h = bake(src, out, yaw_offset_deg=yaw)
        print(f"baked {rel_src} -> {rel_out} ({w}x{h})")

    for rel_src, rel_out in OBJ_JOBS:
        src = OBJ_SRC / rel_src
        if not src.exists():
            print("SKIP (missing)", rel_src)
            continue
        out = OUT / rel_out
        w, h = bake_obj(src, out)
        print(f"baked (obj) {rel_src} -> {rel_out} ({w}x{h})")


if __name__ == "__main__":
    main()
