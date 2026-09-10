"""Congestion mechanic checks (game_state). Run: python test_congestion.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import scenarios
from game_state import GameState, LINE_HEADROOM, CONGESTION_LOSS_FRACTION


def _standard():
    return GameState(scenarios.make_standard())


def test_no_congestion_below_line_rating():
    st = _standard()
    gas = next(s for s in st.sources if s.key == "gas")
    gas.actual_pct = LINE_HEADROOM - 0.05          # under the line rating
    st._update_congestion(0.0)
    assert st.congestion_overload_mw == 0.0
    assert st.effective_supply_mw == st.total_actual_mw


def test_overload_loses_mw_and_flags_source():
    st = _standard()
    for s in st.sources:
        s.actual_pct = 0.0
    gas = next(s for s in st.sources if s.key == "gas")
    gas.actual_pct = 1.0                            # slammed to 100%
    st._update_congestion(0.0)
    cap = st.line_capacity_mw(gas)
    overload = gas.current_output_mw - cap
    assert st.congestion_overload_mw > 0.0
    assert abs(st.congestion_loss_mw - CONGESTION_LOSS_FRACTION * overload) < 1e-6
    assert st.effective_supply_mw < st.total_actual_mw
    assert st.line_overload_frac["gas"] > 0.9       # ~fully overloaded at 100%


def test_peak_is_meetable_without_congestion():
    # Firm fleet at the line rating must still cover the worst-month peak.
    st = _standard()
    firm = sum(st.line_capacity_mw(s) for s in st.sources
               if s.key in ("nuclear", "coal", "gas", "peaker", "hydro"))
    assert firm >= st.demand_peak_mw, f"{firm} < {st.demand_peak_mw}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall congestion checks passed")
