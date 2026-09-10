"""Checks for the standalone map preview renderer.

Run: python tools/test_render_map_preview.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _is_relative_to(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def test_preview_uses_only_approved_asset_roots():
    from tools import render_map_preview

    scene = render_map_preview.build_preview_scene()
    allowed_roots = (
        render_map_preview.APPROVED_MAP_ROOT,
        render_map_preview.APPROVED_TECH_ROOT,
    )
    for path in scene.asset_paths:
        assert any(_is_relative_to(path, root) for root in allowed_roots), path


def test_preview_scene_is_city_and_grid_forward():
    from tools import render_map_preview

    scene = render_map_preview.build_preview_scene()
    counts = scene.role_counts

    assert counts["city_ground"] > counts["natural_ground"]
    assert counts["road"] >= 180
    assert counts["building"] >= 220
    assert counts["tech"] >= 7


if __name__ == "__main__":
    failures = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"ok  {name}")
            except Exception as exc:
                print(f"FAIL {name}: {exc}")
                failures.append(name)
    if failures:
        print(f"\n{len(failures)} test(s) failed: {', '.join(failures)}")
        sys.exit(1)
    print("\nall render_map_preview checks passed")
