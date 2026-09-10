"""Marginal-cost sanity checks (pricing.py). Run: python test_pricing.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pricing


def test_nuclear_is_marginal_not_all_in():
    # Nuclear marginal cost = fuel (~$7) + variable O&M (~$2.5) ~= $9-12/MWh,
    # NOT its ~$33 all-in generating cost. It must be the cheapest firm source.
    assert 8.0 <= pricing.NUCLEAR_PRICE_PER_MWH <= 13.0


def test_merit_order_firm_sources():
    # Cheapest dispatch first: nuclear < coal < gas baseline < peaker baseline.
    assert pricing.NUCLEAR_PRICE_PER_MWH < pricing.COAL_PRICE_PER_MWH
    assert pricing.NUCLEAR_PRICE_PER_MWH < pricing.GAS_BASE_PRICE_PER_MWH
    assert pricing.GAS_BASE_PRICE_PER_MWH < pricing.PEAKER_BASE_PRICE_PER_MWH


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn(); print(f"ok  {name}")
    print("\nall pricing checks passed")
