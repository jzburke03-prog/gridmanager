"""GL context creation and version fail-fast checks. Run: python test_gl_context.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import moderngl

from ui.gl_context import UnsupportedGLError, create_context, format_unsupported_message


def test_format_unsupported_message_reports_both_versions():
    msg = format_unsupported_message(210, 330)
    assert "3.3" in msg
    assert "2.1" in msg
    assert "Grid Manager" in msg


def test_create_context_returns_a_working_context_on_this_machine():
    # This repo's dev/CI machines are expected to have a GL 3.3+ capable
    # driver (moderngl.create_standalone_context uses Mesa/EGL/ANGLE
    # software fallback where no real GPU is present), matching what
    # tools/bake_gltf_terrain.py already relies on for its offline bake.
    ctx = create_context()
    assert ctx.version_code >= 330
    ctx.release()


def test_create_context_wraps_backend_failure_as_unsupported_gl_error():
    # Simulates a machine with no usable GL backend at all (the more common
    # real-world failure than "GL version too old"): create_context() must
    # not let the raw moderngl/driver exception escape unwrapped.
    original = moderngl.create_standalone_context

    def _boom(*args, **kwargs):
        raise moderngl.Error("no suitable GL backend found")

    moderngl.create_standalone_context = _boom
    try:
        try:
            create_context()
        except UnsupportedGLError as exc:
            assert "Grid Manager requires OpenGL" in str(exc)
            assert "no suitable GL backend found" in str(exc)
        else:
            raise AssertionError("expected UnsupportedGLError")
    finally:
        moderngl.create_standalone_context = original


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall gl_context checks passed")
