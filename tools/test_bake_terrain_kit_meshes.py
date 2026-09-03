"""Full terrain-kit bake checks. Run: python tools/test_bake_terrain_kit_meshes.py"""
import os
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bake_terrain_kit_meshes import (  # noqa: E402
    ROOT,
    SRC,
    asset_key,
    bake_asset,
    discover_assets,
    write_manifest,
)


SAFE_KEY = re.compile(r"^[a-z0-9][a-z0-9._/-]*[a-z0-9]$")


def test_discover_assets_covers_every_source_gltf():
    specs = discover_assets()
    expected_count = len(list(SRC.rglob("*.gltf")))
    assert len(specs) == expected_count


def test_asset_keys_are_unique_path_safe_and_include_expected_families():
    specs = discover_assets()
    keys = [spec.key for spec in specs]
    families = {spec.family for spec in specs}
    assert len(keys) == len(set(keys))
    assert {"Roads", "Tracks", "ForestWater", "Mountains", "Trees"} <= families
    for key in keys:
        assert "\\" not in key
        assert ".." not in Path(key).parts
        assert SAFE_KEY.match(key), key


def test_asset_key_normalizes_to_stable_slash_separated_key():
    assert asset_key(Path("Roads") / "road-straight-1.gltf") == "roads/road-straight-1"
    assert asset_key("ForestWater/forest-water-corner-1.gltf") == "forestwater/forest-water-corner-1"


def test_bake_asset_writes_loadable_npz_with_runtime_schema():
    specs = discover_assets()
    sample = next(spec for spec in specs if spec.source == Path("Roads/road-straight-1.gltf"))
    out_root = Path(tempfile.mkdtemp())
    out_path = bake_asset(sample, out_root=out_root)
    assert out_path == out_root / "Roads" / "road-straight-1.npz"
    assert out_path.exists()

    data = np.load(out_path)
    assert set(data.files) == {"pos", "nrm", "uv", "idx", "tex"}
    assert data["pos"].dtype == np.float32
    assert data["nrm"].dtype == np.float32
    assert data["uv"].dtype == np.float32
    assert data["idx"].dtype == np.int32
    assert data["tex"].dtype == np.uint8
    assert data["pos"].ndim == 2 and data["pos"].shape[1] == 3
    assert data["nrm"].shape == data["pos"].shape
    assert data["uv"].ndim == 2 and data["uv"].shape[1] == 2
    assert data["idx"].ndim == 2 and data["idx"].shape[1] == 3
    assert data["tex"].ndim == 3 and data["tex"].shape[2] == 4


def test_write_manifest_entries_include_required_paths():
    specs = discover_assets()
    out_dir = Path(tempfile.mkdtemp())
    out_path = write_manifest(specs, out_path=out_dir / "kit_manifest.json")

    import json

    manifest = json.loads(out_path.read_text(encoding="utf-8"))
    assert manifest["source_root"] == "newassets/terrain/gltf"
    assert manifest["artifact_root"] == "energy_grid_game/assets/terrain3d/kit"
    assert manifest["count"] == len(list((ROOT / "newassets" / "terrain" / "gltf").rglob("*.gltf")))
    assert len(manifest["assets"]) == manifest["count"]

    entry = next(asset for asset in manifest["assets"] if asset["source"] == "Roads/road-straight-1.gltf")
    assert entry == {
        "key": "roads/road-straight-1",
        "family": "Roads",
        "source": "Roads/road-straight-1.gltf",
        "artifact": "Roads/road-straight-1.npz",
    }
    for entry in manifest["assets"]:
        assert set(entry) == {"key", "family", "source", "artifact"}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall bake_terrain_kit_meshes checks passed")
