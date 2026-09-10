#!/usr/bin/env python3
"""Bake the full terrain glTF kit into runtime .npz mesh artifacts."""
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bake_gltf_terrain import load_gltf  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "newassets" / "terrain" / "gltf"
KIT_OUT = ROOT / "energy_grid_game" / "assets" / "terrain3d" / "kit"
MANIFEST = ROOT / "energy_grid_game" / "assets" / "terrain3d" / "kit_manifest.json"


@dataclass(frozen=True)
class AssetSpec:
    key: str
    family: str
    source: Path
    source_path: Path
    artifact: Path


def _slash_path(path):
    return Path(path).as_posix()


def asset_key(rel_path: Path | str) -> str:
    path = Path(rel_path)
    key_path = path.with_suffix("")
    return "/".join(part.lower() for part in key_path.parts)


def discover_assets(src=SRC) -> list[AssetSpec]:
    src = Path(src)
    specs = []
    for source_path in sorted(src.rglob("*.gltf"), key=lambda path: path.relative_to(src).as_posix().lower()):
        rel_source = source_path.relative_to(src)
        artifact = rel_source.with_suffix(".npz")
        specs.append(
            AssetSpec(
                key=asset_key(rel_source),
                family=rel_source.parts[0],
                source=rel_source,
                source_path=source_path,
                artifact=artifact,
            )
        )
    return specs


def bake_asset(spec, out_root=KIT_OUT) -> Path:
    pos, nrm, uv, idx, tex = load_gltf(spec.source_path)
    out_path = Path(out_root) / spec.artifact
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_path,
        pos=pos.astype("f4"),
        nrm=nrm.astype("f4"),
        uv=uv.astype("f4"),
        idx=idx.astype("i4"),
        tex=tex.astype("u1"),
    )
    return out_path


def write_manifest(specs, out_path=MANIFEST) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    assets = [
        {
            "key": spec.key,
            "family": spec.family,
            "source": _slash_path(spec.source),
            "artifact": _slash_path(spec.artifact),
        }
        for spec in specs
    ]
    manifest = {
        "source_root": "newassets/terrain/gltf",
        "artifact_root": "energy_grid_game/assets/terrain3d/kit",
        "count": len(assets),
        "assets": assets,
    }
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out_path


def main():
    specs = discover_assets()
    for spec in specs:
        out_path = bake_asset(spec)
        print(f"baked {spec.source.as_posix()} -> {out_path.relative_to(ROOT).as_posix()}")
    manifest_path = write_manifest(specs)
    print(f"wrote {manifest_path.relative_to(ROOT).as_posix()} ({len(specs)} assets)")


if __name__ == "__main__":
    main()
