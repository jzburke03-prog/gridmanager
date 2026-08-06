"""3D terrain renderer checks. Run: python test_terrain3d.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from ui.terrain3d import (BUILDING_MATERIALS, CAM_ROT, MATERIALS, MESH_DIR,
                           PX_PER_UNIT, ROAD_MATERIALS,
                           ROAD_ROLE_TO_SHAPE_YAW, TILE_SPACING,
                           build_instances)
from ui.iso_city import IsoCity, iso_xy
from ui.urban_blocks import UrbanRoad

import os as _os
_os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
pygame.display.set_mode((1, 1))     # sprite baking (IsoCity._layout) needs a video surface

from ui.gl_context import create_context
from ui.terrain3d import (create_framebuffer, create_program, draw,
                           load_meshes, read_rgba, to_surface,
                           upload_instances)
from ui.terrain3d import billboard_quad, camera_basis, create_dynamic_texture
from ui.terrain3d import build_plant_billboards
from ui.terrain3d import load_billboards


def test_build_instances_buckets_by_material_and_skips_unrecognized_kinds():
    tiles = {
        (0, 0): ("grass", None),
        (1, 0): ("farm", None),
        (2, 0): ("tree", None),
        (3, 0): ("water", None),
        (4, 0): ("mountain", 7),
        (5, 0): ("nonsense_kind", None),  # not a terrain/road/building kind, skip
    }
    instances = build_instances(tiles)
    assert set(instances) == {"grass", "farm", "tree", "water", "mountain"}
    for material in MATERIALS:
        assert instances[material].shape == (1, 4)
        assert instances[material].dtype == np.float32


def test_build_instances_raises_on_unrecognized_road_role():
    tiles = {(0, 0): ("road", UrbanRoad(col=0, row=0, role="not_a_real_role", avenue=False))}
    try:
        build_instances(tiles)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_build_instances_raises_on_unrecognized_building_archetype():
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ui.iso_city import _building_tile
    tile = _building_tile(0, 0, "Downtown", "not_a_real_archetype")
    tiles = {(0, 0): ("urban_block", tile)}
    try:
        build_instances(tiles)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_build_instances_offset_matches_col_row():
    tiles = {(3, 5): ("grass", None)}
    instances = build_instances(tiles)
    expected = np.array([-5.0 * TILE_SPACING, 0.0, 3.0 * TILE_SPACING, 0.0], dtype="f4")
    assert np.array_equal(instances["grass"][0], expected)


def test_build_instances_groups_multiple_tiles_of_the_same_material():
    tiles = {(0, 0): ("grass", None), (1, 1): ("grass", None), (2, 2): ("grass", None)}
    instances = build_instances(tiles)
    assert instances["grass"].shape == (3, 4)


def test_build_instances_omits_materials_with_no_tiles():
    instances = build_instances({(0, 0): ("water", None)})
    assert set(instances) == {"water"}


def test_build_instances_matches_iso_xy_sign_convention():
    """The bug this test exists to catch: negating only `row` (the old
    formula) gets screen_x right but mirrors screen_y. Project a handful of
    build_instances() offsets through the actual camera math (CAM_ROT) that
    terrain3d.py uses at draw time, derive (sx, screen_y) the same way
    _VERTEX_SHADER does (sx = cam.x * scale, screen_y = -cam.y * scale --
    scale is a positive constant so only the signs matter here), and check
    those signs against ui.iso_city.iso_xy(col, row)'s (x, y) signs for
    several distinct tiles. (0, 0) is skipped since both axes are zero
    there and (1, 1) is skipped since its projected screen_x lands exactly
    on zero -- neither has a sign to compare."""
    for col, row in [(1, 0), (0, 1), (2, 1)]:
        tiles = {(col, row): ("grass", None)}
        offset = build_instances(tiles)["grass"][0]
        cam = CAM_ROT @ offset[:3]
        sx = cam[0]
        screen_y = -cam[1]
        iso_x, iso_y = iso_xy(col, row)
        assert np.sign(sx) == np.sign(iso_x), (col, row, sx, iso_x)
        assert np.sign(screen_y) == np.sign(iso_y), (col, row, screen_y, iso_y)


def _project(offset):
    """Project a build_instances() (x, y, z, yaw) offset through the same
    camera math draw()/_VERTEX_SHADER apply at render time (yaw=0 here, so
    the yaw rotation matrix is the identity and can be skipped): cam =
    CAM_ROT @ world, sx = cam.x * PX_PER_UNIT, screen_y = -cam.y *
    PX_PER_UNIT (zoom is a runtime multiplier applied equally to both axes,
    so it's omitted here since only the ratio/proportionality matters)."""
    cam = CAM_ROT @ offset[:3]
    return cam[0] * PX_PER_UNIT, -cam[1] * PX_PER_UNIT


def test_build_instances_projection_matches_iso_xy_proportionally():
    """Stronger than the sign-convention test above: confirms the corrected
    CAM_ROT (_AX = 30 degrees) and PX_PER_UNIT together make the projected
    (sx, screen_y) genuinely PROPORTIONAL to ui.iso_city.iso_xy(col, row) --
    not just sign-matched -- across several distinct (col, row) pairs, with
    the same proportionality constant each time. This is what actually
    guarantees the 3D terrain tiles line up with the 2D city grid on
    screen."""
    pairs = [(1, 0), (0, 1), (2, 1), (3, 5), (7, 1), (2, 6)]
    ratios_x = []
    ratios_y = []
    for col, row in pairs:
        tiles = {(col, row): ("grass", None)}
        offset = build_instances(tiles)["grass"][0]
        sx, screen_y = _project(offset)
        iso_x, iso_y = iso_xy(col, row)
        assert iso_x != 0
        ratios_x.append(sx / iso_x)
        if iso_y != 0:
            ratios_y.append(screen_y / iso_y)
    # All x-ratios agree with each other (proportionality)...
    for r in ratios_x:
        assert abs(r - ratios_x[0]) < 1e-4, (ratios_x, r)
    for r in ratios_y:
        assert abs(r - ratios_y[0]) < 1e-4, (ratios_y, r)
    # ...and the x- and y-ratios agree with EACH OTHER too, confirming the
    # 2:1 ratio itself (not just two independently-scaled axes).
    assert abs(ratios_x[0] - ratios_y[0]) < 1e-4, (ratios_x[0], ratios_y[0])
    # Sanity: the shared constant should be close to 1.0 (exact scale match
    # to iso_xy, not just proportional up to some arbitrary factor).
    assert abs(ratios_x[0] - 1.0) < 1e-3, ratios_x[0]


def _road_tile(col, row, role):
    # Build a real UrbanRoad the same way RoadNetwork.commit_project does,
    # so this test breaks (loudly) if road tile payloads stop being
    # UrbanRoad instances (see Finding 1: build_instances used to read the
    # raw payload as if it were a bare role string, which meant every real
    # road tile silently never matched ROAD_ROLE_TO_SHAPE_YAW).
    return UrbanRoad(col=col, row=row, role=role, avenue=False)


def test_build_instances_buckets_road_tiles_by_shape_with_correct_yaw():
    tiles = {
        (0, 0): ("road", _road_tile(0, 0, "straight_ne")),
        (1, 0): ("road", _road_tile(1, 0, "straight_nw")),
        (2, 0): ("road", _road_tile(2, 0, "cross")),
        (3, 0): ("road", _road_tile(3, 0, "corner_nw")),
        (4, 0): ("road", _road_tile(4, 0, "tee_ne")),
    }
    instances = build_instances(tiles)
    assert instances["straight"].shape == (2, 4)
    yaws = sorted(instances["straight"][:, 3].tolist())
    assert yaws == [0.0, 90.0]
    assert instances["cross"].shape == (1, 4)
    assert instances["cross"][0, 3] == 0.0
    assert instances["corner"].shape == (1, 4)
    assert instances["corner"][0, 3] == 180.0
    assert instances["tee"].shape == (1, 4)
    assert instances["tee"][0, 3] == 180.0


def test_road_role_to_shape_yaw_covers_all_seven_roles():
    assert set(ROAD_ROLE_TO_SHAPE_YAW) == {
        "straight_ne", "straight_nw", "corner_ne", "corner_nw",
        "tee_ne", "tee_nw", "cross"}
    for shape, yaw in ROAD_ROLE_TO_SHAPE_YAW.values():
        assert shape in ROAD_MATERIALS
        assert yaw in (0.0, 90.0, 180.0, 270.0)


def test_build_instances_buckets_urban_block_tiles_by_archetype():
    # Build a real urban_block tile the same way IsoCity does, so this test
    # breaks (loudly) if _building_tile's payload shape ever changes.
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ui.iso_city import _building_tile
    tile = _building_tile(0, 0, "Downtown", "house")
    tiles = {(0, 0): ("urban_block", tile)}
    instances = build_instances(tiles)
    assert "house" in instances
    assert instances["house"].shape == (1, 4)


def test_build_instances_produces_road_instances_from_a_real_city_layout():
    """Integration check for Finding 1/3: a real IsoCity layout at a
    population large enough to trigger road network growth (per the P2
    review's own investigation) must actually produce road instances once
    build_instances() correctly reads UrbanRoad.role. Before the Finding 1
    fix, this test would fail with road_instance_count == 0 because the raw
    UrbanRoad payload was never matching ROAD_ROLE_TO_SHAPE_YAW.

    Building instances are deliberately NOT asserted here: the review found
    urban_block tiles never survive _layout()'s dense-downtown overwrite for
    any population tested, so BUILDING_MATERIALS counts are legitimately
    zero right now -- a separate, already-tracked issue this fix pass does
    not touch (iso_city.py's layout logic is out of scope)."""
    rect = pygame.Rect(0, 0, 1400, 410)
    city = IsoCity(None)
    city._layout(rect, 2_000_000, ("gas",))
    instances = build_instances(city.tiles)
    road_instance_count = sum(len(v) for k, v in instances.items() if k in ROAD_MATERIALS)
    assert road_instance_count > 0


def _mesh_open_arms(shape, threshold=1.5):
    """For a baked road mesh's `pos` array, return the set of unit (x, z)
    directions whose extreme value reaches close to the tile edge -- i.e.
    the mesh's open "connection arms" at yaw=0. A simple, GL-free geometry
    check standing in for a full render: it only inspects the bounding box
    of baked vertex positions, not actual rendered pixels."""
    data = np.load(MESH_DIR / "roads" / f"{shape}.npz")
    pos = data["pos"]
    arms = set()
    for axis, positive in (("x", True), ("x", False), ("z", True), ("z", False)):
        col = pos[:, 0] if axis == "x" else pos[:, 2]
        extreme = col.max() if positive else col.min()
        if abs(extreme) >= threshold:
            vec = (1, 0) if axis == "x" else (0, 1)
            if not positive:
                vec = (-vec[0], -vec[1])
            arms.add(vec)
    return arms


def _rotate(vec, yaw_deg):
    """Same 2D rotation the vertex shader applies to (x, z). The shader
    builds `mat3(c,0,-s, 0,1,0, s,0,c)` via GLSL's column-major constructor,
    which is the matrix [[c,0,s],[0,1,0],[-s,0,c]]: new_x = x*cos(yaw) +
    z*sin(yaw), new_z = -x*sin(yaw) + z*cos(yaw)."""
    theta = np.deg2rad(yaw_deg)
    c, s = np.cos(theta), np.sin(theta)
    x, z = vec
    return (round(x * c + z * s), round(-x * s + z * c))


# Each role's required neighbor directions in (x, z) unit vectors, per
# ui.road_network.assign_roles's docstring and this module's position
# formula (up/row-1 -> +X, down/row+1 -> -X, left/col-1 -> -Z,
# right/col+1 -> +Z).
_ROLE_REQUIRED_ARMS = {
    "straight_ne": {(1, 0), (-1, 0)},           # up + down
    "straight_nw": {(0, 1), (0, -1)},           # left + right
    "corner_ne": {(1, 0), (0, 1)},              # up + right
    "corner_nw": {(-1, 0), (0, -1)},            # down + left
    "tee_ne": {(1, 0), (-1, 0), (0, -1)},       # up + down + left
    "tee_nw": {(0, 1), (0, -1), (-1, 0)},       # left + right + down
}


def test_road_mesh_geometry_arms_match_yaw_rotated_role_connectivity():
    """Pure numpy/geometry check tying each baked road mesh's actual open
    arms (from its .npz bounding box) to the neighbor connectivity its role
    name requires, once rotated by ROAD_ROLE_TO_SHAPE_YAW's yaw -- no GL
    context needed. `cross` is 4-way symmetric so it is not checked here
    (any yaw is equally valid for it)."""
    for role, required in _ROLE_REQUIRED_ARMS.items():
        shape, yaw = ROAD_ROLE_TO_SHAPE_YAW[role]
        base_arms = _mesh_open_arms(shape)
        rotated_arms = {_rotate(arm, yaw) for arm in base_arms}
        assert required <= rotated_arms, (role, shape, yaw, required, rotated_arms)


class _FakeCamera:
    def __init__(self, center=(0.0, 0.0), zoom=1.0):
        self.center = list(center)
        self.zoom = zoom


def test_load_meshes_covers_terrain_road_and_building_materials():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        assert set(meshes) == set(MATERIALS) | set(ROAD_MATERIALS) | set(BUILDING_MATERIALS)
    finally:
        ctx.release()


def test_draw_produces_a_readable_framebuffer_with_visible_content():
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        upload_instances(ctx, meshes, {"grass": np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4")})
        fbo = create_framebuffer(ctx, (64, 64))
        draw(ctx, prog, meshes, fbo, _FakeCamera(center=(0.0, 0.0), zoom=1.0))
        rgba, size = read_rgba(fbo)
        assert size == (64, 64)
        pixels = np.frombuffer(rgba, dtype="u1").reshape(64, 64, 4)
        # A single grass instance at the origin, camera centered on it, must
        # paint at least some non-background pixels near the middle.
        assert pixels[:, :, 3].max() > 0
    finally:
        ctx.release()


def test_to_surface_returns_a_surface_of_the_requested_size():
    rgba = bytes([255, 0, 0, 255] * (8 * 8))
    surf = to_surface(rgba, (8, 8))
    assert isinstance(surf, pygame.Surface)
    assert surf.get_size() == (8, 8)


def test_instance_yaw_actually_rotates_the_rendered_mesh():
    """The `straight` road mesh is longer along one axis than the other (a
    road segment, not a symmetric tile) -- render it once at yaw=0 and once
    at yaw=90 into separate framebuffers and confirm the rendered alpha
    footprints differ, proving the shader's per-instance rotation actually
    executes rather than being a no-op."""
    ctx = create_context()
    try:
        prog = create_program(ctx)
        meshes = load_meshes(ctx, prog)
        camera = _FakeCamera(center=(0.0, 0.0), zoom=1.0)

        upload_instances(ctx, meshes, {"straight": np.array([[0.0, 0.0, 0.0, 0.0]], dtype="f4")})
        fbo_a = create_framebuffer(ctx, (128, 128))
        draw(ctx, prog, meshes, fbo_a, camera)
        rgba_a, _ = read_rgba(fbo_a)

        upload_instances(ctx, meshes, {"straight": np.array([[0.0, 0.0, 0.0, 90.0]], dtype="f4")})
        fbo_b = create_framebuffer(ctx, (128, 128))
        draw(ctx, prog, meshes, fbo_b, camera)
        rgba_b, _ = read_rgba(fbo_b)

        assert rgba_a != rgba_b
    finally:
        ctx.release()


def test_camera_basis_vectors_are_orthonormal():
    right, up, facing = camera_basis()
    for v in (right, up, facing):
        assert abs(np.linalg.norm(v) - 1.0) < 1e-6
    assert abs(np.dot(right, up)) < 1e-6
    assert abs(np.dot(right, facing)) < 1e-6
    assert abs(np.dot(up, facing)) < 1e-6
    # up should be world-vertical: billboards stand upright, matching the
    # existing 2D sprites' "flat cutout standing on the ground" convention.
    assert np.allclose(up, np.array([0.0, 1.0, 0.0]), atol=1e-6)
    # facing must point back TOWARD the camera, not into the scene: for the
    # fixed CAM_ROT (_AY=45deg, _AX=30deg) that horizontal direction is
    # (-0.7071, 0, 0.7071), the negation of the away-from-camera direction a
    # sign flip would produce. Orthonormality alone can't catch a sign bug.
    assert np.allclose(facing, np.array([-0.70710678, 0.0, 0.70710678]), atol=1e-6)


def test_billboard_quad_has_four_verts_and_two_triangles():
    pos, nrm, uv, idx = billboard_quad(2.0, 3.0)
    assert pos.shape == (4, 3)
    assert nrm.shape == (4, 3)
    assert uv.shape == (4, 2)
    assert idx.shape == (2, 3)
    # bottom edge at y=0, top edge at y=height, centered on x=0 in the
    # camera-facing basis (before the per-instance world offset is added)
    assert np.isclose(pos[:, 1].min(), 0.0)
    assert np.isclose(pos[:, 1].max(), 3.0)


def test_create_dynamic_texture_matches_surface_size():
    ctx = create_context()
    try:
        surf = pygame.Surface((17, 23), pygame.SRCALPHA)
        surf.fill((255, 0, 0, 255))
        tex = create_dynamic_texture(ctx, surf)
        assert tex.size == (17, 23)
    finally:
        ctx.release()


class _FakePlantSite:
    def __init__(self, key, col, row, w, h):
        self.key = key
        self.col, self.row = col, row
        self.sprite = pygame.Surface((w, h), pygame.SRCALPHA)


def test_build_plant_billboards_converts_col_row_and_sprite_size():
    plants = [_FakePlantSite("gas", 3, -5, 32, 64)]
    billboards = build_plant_billboards(plants)
    assert len(billboards) == 1
    b = billboards[0]
    assert b["key"] == "gas"
    assert np.allclose(b["offset"], (5.0 * TILE_SPACING, 0.0, 3.0 * TILE_SPACING))
    assert np.isclose(b["width_world"], 32 / PX_PER_UNIT)
    # height is corrected for camera vertical foreshortening (see
    # billboard_quad's docstring note): dividing by PX_PER_UNIT alone would
    # render the billboard ~13% too short relative to its width, since
    # up_world isn't perpendicular to the camera view direction the way
    # right_world is. Dividing by PX_PER_UNIT * cos(30deg) instead makes the
    # on-screen height match the sprite's pixel aspect ratio.
    assert np.isclose(
        b["height_world"], 64 / (PX_PER_UNIT * np.cos(np.deg2rad(30.0)))
    )
    assert b["surface"] is plants[0].sprite


def test_build_plant_billboards_handles_multiple_plants():
    plants = [_FakePlantSite("gas", 0, 0, 10, 10), _FakePlantSite("solar", 5, 5, 20, 20)]
    assert len(build_plant_billboards(plants)) == 2


def _count_red_pixels(ctx, prog, tower_offset_xyz, camera):
    """Render a 'tower' building instance at `tower_offset_xyz` together
    with a solid-red billboard fixed at the world origin, and return how
    many rendered pixels read back as "red" (the billboard's shaded fill).

    Under this file's banded lighting (LIGHT vs. the billboard's fixed
    facing_normal from camera_basis()), a pure (255,0,0,255) fill renders at
    R ~= 178.5 (lambert ~= 0.597, banded to the 1/3 band, bright = 0.55 +
    0.45*(1/3) = 0.70, 255*0.70 = 178.5) -- NOT the R > 200 an earlier
    version of this test checked for, which could never fire since nothing
    in this scene renders above that value. R > 150 sits safely below the
    actual rendered value with margin, while staying well above the (25,
    28, 33) background clear color and other meshes' shading."""
    meshes = load_meshes(ctx, prog)
    upload_instances(
        ctx, meshes,
        {"tower": np.array([[*tower_offset_xyz, 0.0]], dtype="f4")},
    )
    red_surface = pygame.Surface((32, 64), pygame.SRCALPHA)
    red_surface.fill((255, 0, 0, 255))
    billboards = [{"key": "test", "offset": (0.0, 0.0, 0.0),
                   "width_world": 2.0, "height_world": 2.0, "surface": red_surface}]
    billboard_meshes = load_billboards(ctx, prog, billboards)
    fbo = create_framebuffer(ctx, (128, 128))
    draw(ctx, prog, meshes, fbo, camera, billboard_meshes=billboard_meshes)
    rgba, size = read_rgba(fbo)
    pixels = np.frombuffer(rgba, dtype="u1").reshape(size[1], size[0], 4)
    is_red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 60) & (pixels[:, :, 2] < 60)
    for mesh in meshes.values():
        mesh.release()
    for mesh in billboard_meshes:
        mesh.release()
    fbo.color_attachments[0].release()
    fbo.depth_attachment.release()
    fbo.release()
    return int(is_red.sum())


def test_billboard_is_occluded_by_a_nearer_building_instance():
    """Synthetic proof of the core Phase 3a claim: a billboard is hidden by
    a building instance that is nearer to the camera, because both share
    the same depth buffer.

    The billboard stays fixed at the world origin. The tower instance is
    slid along CAM_ROT[2] -- the camera's own view-direction axis in world
    space (row index 2 of CAM_ROT, i.e. the direction cam_rot @ world maps
    onto cam.z) -- by a scalar `t`. Moving an object along this axis keeps
    its projected screen position (sx, sy) pixel-identical (since only
    cam.z, which feeds `depth`, changes -- sx/sy come from cam.x/cam.y) while
    changing how near/far it is from the camera. This is deliberately NOT
    the tower-at-origin/billboard-offset-(0,0,5) setup an earlier version of
    this test used: numeric analysis showed those two objects never share a
    screen pixel at all under this camera (disjoint sx ranges), so that
    setup could not have exercised depth testing regardless of any
    threshold fix. Camera center is offset to (-64,-64) (fbo is 128x128) so
    the world origin -- where both objects sit at t=0 -- projects to the
    center of the frame rather than to a screen corner, where an earlier
    version of this test's camera setup left it invisible/clipped.

    t < 0 moves the tower AWAY from the camera along that axis (behind the
    billboard); t > 0 moves it TOWARD the camera (in front of, i.e. nearer
    than, the billboard). Two assertions:
      1. Positive control: with the tower behind the billboard (t=-6), the
         billboard's red pixels are fully visible (proving this setup CAN
         detect the billboard at all when nothing occludes it -- a test
         that can't pass this can't meaningfully test occlusion either).
      2. The actual claim: with the tower in front of the billboard (t=+6),
         the red pixel count drops substantially, since the tower's nearer
         fragments win the depth test over the same screen pixels.
    Empirically (see this test's development notes) t=-6 renders 48 red
    pixels (full billboard silhouette) and t=+6 renders 16 (only the
    fringe peeking around the tower's narrower footprint) -- a large,
    unambiguous drop, not a borderline threshold."""
    ctx = create_context()
    try:
        prog = create_program(ctx)
        camera = _FakeCamera(center=(-64.0, -64.0), zoom=1.0)
        axis = CAM_ROT[2]

        behind_count = _count_red_pixels(ctx, prog, tuple(-6.0 * axis), camera)
        assert behind_count >= 30, (
            "positive control failed: billboard should be fully visible "
            f"with nothing in front of it, got {behind_count} red pixels"
        )

        front_count = _count_red_pixels(ctx, prog, tuple(6.0 * axis), camera)
        assert front_count < behind_count / 2, (
            "tower in front of the billboard should occlude most of it: "
            f"behind={behind_count} front={front_count}"
        )
    finally:
        ctx.release()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall terrain3d checks passed")
