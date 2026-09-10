"""Frozen launcher for the portable Grid Keeper bundle.

The project source is bundled as runtime data so the demo's existing relative
asset paths continue to behave the same way they do from the repository.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
if "--smoke-test" in sys.argv:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# These imports make PyInstaller collect the binary runtime packages. The game
# imports them again from its own entry point after sys.path is set below.
import certifi  # noqa: F401
import numpy  # noqa: F401
import pygame  # noqa: F401


def bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def main() -> None:
    root = bundle_root()
    game_dir = root / "energy_grid_game"
    if not game_dir.exists():
        raise RuntimeError(f"Bundled game directory not found: {game_dir}")

    sys.path.insert(0, str(game_dir))
    sys.path.insert(0, str(root))
    os.chdir(root)
    if "--smoke-test" in sys.argv:
        smoke_test(root)
        return
    runpy.run_path(str(game_dir / "main.py"), run_name="__main__")


def smoke_test(root: Path) -> None:
    required = [
        root / "energy_grid_game" / "main.py",
        root / "assets" / "iso" / "manifest.json",
        root / "energy_grid_game" / "assets" / "voxel" / "manifest.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Missing bundled files: " + ", ".join(missing))

    pygame.display.init()
    pygame.display.set_mode((8, 8))

    from ui import assets, voxel_assets

    assets.button("confirm", "idle")
    plant_entry = assets.iso_plant_entry("nuclear")
    assets.iso_sprite(plant_entry["file"])
    voxel_assets.sprite("apartment", 0)
    pygame.display.quit()


if __name__ == "__main__":
    main()
