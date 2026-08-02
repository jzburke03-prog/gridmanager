"""Dialogue rewrite must not change structure. Run: python test_dialogue_schema.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from ui import tutorial_data, instructional_data

EXPECTED_STANDARD_IDS = ["intro", "readout", "city", "raise_supply",
                         "balance", "speed", "outro"]


def test_standard_step_ids_unchanged():
    assert [s["id"] for s in tutorial_data.STEPS] == EXPECTED_STANDARD_IDS


def test_conditions_keys_unchanged():
    assert set(tutorial_data.CONDITIONS) == {"supply_raised", "balanced"}
    assert set(instructional_data.CONDITIONS) == {
        "generic_raised", "balanced", "peaker_running",
        "baseload_running", "renewable_opened"}


def test_every_step_has_at_least_one_line():
    for step in tutorial_data.STEPS:
        assert step["lines"] and all(isinstance(x, str) for x in step["lines"])
    for day in instructional_data.DAYS.values():
        for step in day:
            assert step["lines"] and all(isinstance(x, str) for x in step["lines"])


def test_instructional_days_are_1_to_4():
    assert sorted(instructional_data.DAYS) == [1, 2, 3, 4]
    assert sorted(instructional_data.DAY_NOTES) == [1, 2, 3, 4]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall dialogue-schema checks passed")
