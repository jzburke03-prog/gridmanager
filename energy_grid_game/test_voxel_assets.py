"""Tests for the voxel sprite loader."""
import pygame
from ui import voxel_assets as va


def _init():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((64, 64))


def test_manifest_and_mapping():
    assert va.has("apartment") and va.has("nuclear")
    assert va.GEN_FOR_PLANT["coal"] == "thermal"
    assert va.GEN_FOR_PLANT["gas"] == "cogeneration"
    assert va.GEN_FOR_PLANT["wind"] is None


def test_sprite_loads_and_caches():
    _init()
    s = va.sprite("apartment")
    assert s.get_width() > 0 and s.get_height() > 0
    assert va.sprite("apartment") is s          # cached
    assert va.sprite("nuclear").get_width() > 0


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")
