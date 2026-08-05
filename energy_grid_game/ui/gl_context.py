"""Headless moderngl context creation for the 3D terrain renderer.

No pygame GL window is used -- see the "Mechanism note" in
docs/superpowers/plans/2026-08-05-realtime-3d-terrain-phase1.md. This is a
standalone (windowless) context, the same kind tools/bake_gltf_terrain.py
already uses successfully for offline baking; the terrain renderer reads its
framebuffer back to CPU each frame and blits it as an ordinary pygame
Surface into the existing software-rendered window.
"""
import moderngl

MIN_VERSION_CODE = 330  # OpenGL 3.3 core, minimum moderngl instancing needs


class UnsupportedGLError(RuntimeError):
    """Raised when the driver's GL context is below MIN_VERSION_CODE."""


def _version_str(version_code):
    major, minor = version_code // 100, (version_code % 100) // 10
    return f"{major}.{minor}"


def format_unsupported_message(version_code, min_version_code):
    return (f"Grid Manager requires OpenGL {_version_str(min_version_code)}+; "
            f"your driver reports {_version_str(version_code)}")


def create_context(min_version_code=MIN_VERSION_CODE):
    """Create a headless GL context, or raise UnsupportedGLError with a
    readable message if the driver's GL version is too old. No fallback
    renderer -- callers should let this propagate to a clean startup exit."""
    ctx = moderngl.create_standalone_context()
    if ctx.version_code < min_version_code:
        version_code = ctx.version_code
        ctx.release()
        raise UnsupportedGLError(format_unsupported_message(version_code, min_version_code))
    return ctx
