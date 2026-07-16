"""Marginal generation cost model, calibrated to approximate real Southeast
U.S. (SERC region: Georgia Power, Alabama Power, Duke Carolinas, TVA, etc.)
utility dispatch costs circa 2023-2024, using typical EIA fuel-price and
plant heat-rate figures. This is a marginal/dispatch cost model, not a live
market feed — most of the Southeast is vertically-integrated utility
territory (not a real-time LMP market like ERCOT/PJM), but utilities still
compute and dispatch generation by marginal cost internally, which is what
this approximates:

    $/MWh ≈ heat_rate (Btu/kWh) × fuel_price ($/MMBtu) / 1000 + variable O&M

Reference figures used (approximate, typical 2023-2024 Southeast averages):
  Nuclear: heat rate ~10,400 Btu/kWh, fuel ~$0.75/MMBtu, O&M-heavy (staffing/
           security/NRC compliance dominate over fuel) -> ~$28/MWh
  Coal:    heat rate ~10,200 Btu/kWh, fuel ~$2.20/MMBtu, aging Southeast
           fleet has higher O&M -> ~$38/MWh
  Gas CC:  heat rate ~7,000 Btu/kWh (efficient combined-cycle), fuel
           ~$3.00/MMBtu -> ~$25-30/MWh at typical load
  Gas CT:  heat rate ~11,000+ Btu/kWh (simple-cycle peaker, much less
           efficient), dispatched only for the last slice of peak demand,
           plus gas spot prices often spike when demand is high -> $100+/MWh
  Solar/Wind: no fuel cost, small O&M -> near-zero marginal cost
  Hydro:   no fuel cost, O&M + water value -> low but nonzero marginal cost
"""

NUCLEAR_PRICE_PER_MWH = 28.0
COAL_PRICE_PER_MWH = 38.0
SOLAR_PRICE_PER_MWH = 3.0
WIND_PRICE_PER_MWH = 3.0
HYDRO_PRICE_PER_MWH = 8.0

# Natural gas is the one source whose price genuinely swings with demand: the
# grid runs efficient combined-cycle plants for most of the load, then has to
# dispatch inefficient simple-cycle peaker turbines to cover the last slice
# of peak demand — which is the real-world reason peaker power is expensive.
GAS_BASE_PRICE_PER_MWH = 28.0    # efficient combined-cycle, off-peak/typical load
GAS_PEAK_PRICE_PER_MWH = 145.0   # simple-cycle peakers dispatched + gas spot spikes

# Extreme-demand events (e.g. a heat wave) mirror real scarcity pricing during
# events like Winter Storm Elliott (Dec 2022), when Southeast wholesale gas
# and power prices spiked far above normal.
EVENT_SCARCITY_MULTIPLIER = 1.6


def gas_price(demand_level: float, scarcity: bool = False) -> float:
    """demand_level is 0..1 (trough to peak). Price stays near the efficient
    combined-cycle baseline until demand climbs past ~50%, then curves up
    sharply as peaker units get dispatched."""
    t = max(0.0, min(1.0, (demand_level - 0.5) / 0.5))
    curve = t ** 2.2
    price = GAS_BASE_PRICE_PER_MWH + (GAS_PEAK_PRICE_PER_MWH - GAS_BASE_PRICE_PER_MWH) * curve
    if scarcity:
        price *= EVENT_SCARCITY_MULTIPLIER
    return price
