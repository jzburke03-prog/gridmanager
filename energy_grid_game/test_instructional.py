"""Checks for Instructional Mode's day gating (SPEC-1.1 §3).

Run: python test_instructional.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import scenarios
from game_state import GameState
from sources.base_source import SourceStatus


def _instructional(day=1):
    st = GameState(scenarios.make_instructional())
    st.day = day
    return st


def test_day_one_is_a_single_generic_valve():
    st = _instructional(1)
    assert [s.key for s in st.active_sources] == ["generic"]
    generic = st.active_sources[0]
    assert generic.name == "Electricity"
    # Instant response and no minimum: nothing to learn but supply vs demand.
    assert generic.ramp_up_latency <= 0.05
    assert generic.min_stable_output == 0.0
    assert generic.price_at(1.0) == 0.0
    # One handle must be able to cover peak demand, or Day 1 is unwinnable.
    assert generic.max_output_mw > st.demand_peak_mw


def test_unlocks_are_cumulative_and_complete():
    seen = []
    for day in (1, 2, 3, 4):
        keys = [s.key for s in _instructional(day).active_sources]
        seen.append(set(keys))
    assert seen[1] == {"gas", "peaker"}
    assert seen[2] == {"gas", "peaker", "coal", "nuclear"}
    assert seen[3] == {"gas", "peaker", "coal", "nuclear", "solar", "wind", "hydro"}
    # Day 1's generic valve is retired, never carried forward.
    for later in seen[1:]:
        assert "generic" not in later
    # Days 2-4 only ever add.
    assert seen[1] < seen[2] < seen[3]


def test_other_modes_are_never_gated():
    st = GameState(scenarios.make_standard())
    assert st.active_sources is st.sources
    assert len(st.sources) == 7          # no generic valve outside instructional
    assert st.show_economics and st.can_fail


def test_retired_source_is_zeroed_on_rollover():
    """The rollover hazard: if the generic valve keeps generating after Day 1,
    Day 2 opens with supply silently doubled."""
    st = _instructional(1)
    generic = st.active_sources[0]
    generic.set_handle(1.0)
    for _ in range(120):
        st.update(1 / 60.0)
    assert generic.current_output_mw > 100, "valve should be carrying load"

    st.start_next_day()
    assert generic.current_output_mw == 0.0
    assert generic.requested_pct == 0.0
    assert generic.status == SourceStatus.OFFLINE
    assert st.total_actual_mw == 0.0


def test_days_one_to_three_cannot_lose():
    for day in (1, 2, 3):
        st = _instructional(day)
        st._trigger_game_over("TOTAL BLACKOUT")
        assert not st.game_over, f"day {day} must be unloseable"
    st = _instructional(4)
    st._trigger_game_over("TOTAL BLACKOUT")
    assert st.game_over, "day 4 runs for real"


def test_economics_and_events_arrive_on_schedule():
    assert not _instructional(1).show_economics
    for day in (2, 3, 4):
        assert _instructional(day).show_economics
    for day in (1, 2, 3):
        assert not _instructional(day).events_active
    assert _instructional(4).events_active


def test_mode_ends_after_the_last_scripted_day():
    assert not _instructional(3).is_final_day
    assert _instructional(4).is_final_day
    # Past the script the whole fleet stays unlocked rather than vanishing.
    assert len(_instructional(9).active_sources) == 7


def test_four_day_progression_through_the_real_day_panel():
    """Drives days 1->4 through DayCompletePanel itself, which owns the rollover.
    Covers the paths main()'s loop takes: unlock swap, retired-source zeroing,
    and the terminal return-to-menu on the final day."""
    import pygame
    pygame.init()
    pygame.display.set_mode((320, 240))
    from ui.day_panel import DayCompletePanel, DayPhase

    font = pygame.font.Font(pygame.font.match_font("menlo,monospace"), 13)
    panel = DayCompletePanel(font, font, font)
    st = GameState(scenarios.make_instructional())

    seen_days = []
    for _ in range(4):
        seen_days.append(st.day)
        for s in st.active_sources:      # carry some load so the day is real
            s.set_handle(0.5)
        # run the day out to its 24 sim-hours
        guard = 0
        while not st.day_complete and guard < 200000:
            st.update(1 / 60.0)
            guard += 1
        assert st.day_complete, f"day {st.day} never completed"
        assert not st.game_over, "instructional days 1-3 must not end the run"

        panel.update(1 / 60.0, st, {})           # DAY_ACTIVE -> PAUSED
        assert panel.phase == DayPhase.DAY_COMPLETE_PAUSED
        panel.confirm()

        if st.is_final_day:
            assert panel.take_return_to_menu(), "final day must return to menu"
            assert not panel.take_return_to_menu(), "one-shot only"
            break
        panel.update(1 / 60.0, st, {})           # ADVANCING_DAY -> start_next_day
        panel.update(1 / 60.0, st, {})           # NEXT_DAY_START -> DAY_ACTIVE
        assert not panel.take_return_to_menu()

    assert seen_days == [1, 2, 3, 4]
    # Retired sources left nothing running behind the panel.
    active = {s.key for s in st.active_sources}
    for s in st.sources:
        if s.key not in active:
            assert s.current_output_mw == 0.0, f"{s.key} still generating"


def test_progress_file_keeps_both_keys():
    """Completion and high score share one file; writing either must not drop
    the other."""
    import game_state as gs
    original = gs._load_progress()
    try:
        gs.save_high_score(1234.0)
        gs.mark_instructional_complete()
        assert gs.load_high_score() == 1234.0
        assert gs.instructional_complete()
        gs.save_high_score(5678.0)
        assert gs.instructional_complete(), "high score write clobbered completion"
    finally:
        with open(gs.HIGHSCORE_PATH, "w") as f:
            import json
            json.dump(original, f)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall instructional checks passed")
