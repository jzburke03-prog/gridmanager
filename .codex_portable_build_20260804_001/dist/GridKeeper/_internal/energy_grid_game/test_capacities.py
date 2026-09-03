"""Checks for the Standard grid capacity table (SPEC-1.1 §2).

The published table is only true if _ensure_playable never fires — it silently
adds MW to gas when firm capacity can't cover peak, and it does so on every
month independently. Run: python test_capacities.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import datetime

import scenarios
from scenarios import STANDARD_CAPACITIES, _DISPATCHABLE

SPEC_TOTAL = 1750.0
SPEC = {"gas": 750.0, "peaker": 50.0, "coal": 250.0, "wind": 225.0,
        "solar": 175.0, "nuclear": 150.0, "hydro": 150.0}


def test_table_matches_spec():
    assert STANDARD_CAPACITIES == SPEC
    assert sum(STANDARD_CAPACITIES.values()) == SPEC_TOTAL


def test_class_defaults_agree():
    """The per-class defaults and STANDARD_CAPACITIES are two declarations of the
    same fleet. They drifted before 1.1; keep them agreeing.

    Constructs the sources directly — going via GameState would prove nothing,
    since _apply_config stamps the config's capacities over the class defaults
    and the assertion would pass however far the defaults had drifted.
    """
    from sources.coal import CoalSource
    from sources.hydro import HydroSource
    from sources.natural_gas import GasSource
    from sources.nuclear import NuclearSource
    from sources.peaker import PeakerSource
    from sources.solar import SolarSource
    from sources.wind import WindSource

    for cls in (NuclearSource, CoalSource, GasSource, PeakerSource,
                SolarSource, WindSource, HydroSource):
        src = cls()
        assert src.max_output_mw == SPEC[src.key], (
            f"{src.key}: class default {src.max_output_mw} != table {SPEC[src.key]}")


def test_ensure_playable_never_fires():
    """Every month, in both directions: the loaded capacities must equal the
    published ones. If this fails the table is fiction and the player is quietly
    handed extra gas."""
    for month in range(1, 13):
        cfg = scenarios.make_standard(datetime.date(2025, month, 15))
        assert cfg.capacities == SPEC, f"month {month}: {cfg.capacities}"
        assert sum(cfg.capacities.values()) == SPEC_TOTAL


def test_firm_margin_is_thin_but_positive():
    """Documents the 16 MW of slack the table actually has, so a future change
    that eats it fails here rather than silently in _ensure_playable."""
    firm = sum(STANDARD_CAPACITIES[k] for k in _DISPATCHABLE)
    worst_peak = scenarios.STANDARD_DEMAND_PEAK_MW * max(
        d for d, _s in scenarios._SEASON.values())
    required = worst_peak * 1.15
    assert firm >= required, f"firm {firm} < required {required:.0f}"
    assert firm - required < 40, "margin grew — re-check the spec's arithmetic"


def test_eia_capacity_builder_halves_observed_source_peaks():
    hourly = [1000.0] * 24
    fuel = {key: hourly for key in ("nuclear", "coal", "gas", "hydro", "wind", "solar")}
    cfg = scenarios._build_from_eia(
        {"demand_hourly": hourly, "fuel_hourly": fuel, "source": "cache"},
        scenarios.DIFFICULTIES["moderate"], "Test Grid", "TEST",
        datetime.date(2025, 8, 14), None, "region")

    for key in ("nuclear", "coal", "gas", "hydro", "wind", "solar"):
        assert cfg.capacities[key] == 500.0
    assert cfg.capacities["peaker"] == 50.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("\nall capacity checks passed")
