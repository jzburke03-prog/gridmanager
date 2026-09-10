"""Unit tests for ui.voxel_terrain pure helpers + drawing smoke tests."""
import pygame
from ui import voxel_terrain as vt


def test_season_of_boundaries():
    assert vt.season_of(12) == "winter" and vt.season_of(1) == "winter" and vt.season_of(2) == "winter"
    assert vt.season_of(3) == "spring" and vt.season_of(5) == "spring"
    assert vt.season_of(6) == "summer" and vt.season_of(8) == "summer"
    assert vt.season_of(9) == "fall" and vt.season_of(11) == "fall"


def test_palette_has_all_materials():
    keys = {"grass", "field", "water", "road", "pad", "rock", "snow", "tree"}
    for s in ("winter", "spring", "summer", "fall"):
        assert keys <= set(vt.palette(s)), s


def test_should_rebake_for_season():
    assert vt.should_rebake_for_season(None, "summer") is True
    assert vt.should_rebake_for_season("summer", "summer") is False
    assert vt.should_rebake_for_season("summer", "fall") is True


def test_elevation_zero_in_play_area():
    assert vt.elevation(0, 0, 0.0, 0.0, 24.0, 42.0) == 0
    assert vt.elevation(10, 10, 0.0, 0.0, 24.0, 42.0) == 0


def test_elevation_rises_at_edge():
    assert vt.elevation(50, 50, 0.0, 0.0, 24.0, 42.0) > 0


def test_vnoise_range():
    for x, y in ((0.1, 0.2), (3.4, 9.9), (12.0, 0.0)):
        assert 0.0 <= vt.vnoise(x, y) <= 1.0


def test_slab_draws_within_bounds():
    pygame.init()
    surf = pygame.Surface((40, 40), pygame.SRCALPHA)
    vt.slab(surf, 4, 4, (100, 150, 74))
    assert surf.get_bounding_rect().width > 0


def test_material_at_is_deterministic_and_valid():
    for col, row in ((0, 0), (7, 3), (30, 12)):
        m = vt.material_at(col, row)
        assert m in ("farm", "grass", "tree")
        assert vt.material_at(col, row) == m


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
