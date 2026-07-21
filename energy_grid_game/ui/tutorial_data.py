"""Tutorial script and completion conditions, kept out of the render code.

Every step below teaches something the game actually implements: the SUPPLY vs
DEMAND readout the HUD draws, the reservoir tank, the per-source sliders in the
spigot panel, and the speed/pause controls. No invented commands.

`wait_for` names a key in CONDITIONS; `highlight` names a region key that
main.py supplies from the real layout rects.
"""
from ui import portraits

SPEAKER = "Gattie"

# Ideal band lifted straight from game_state.score_delta: this is the range that
# actually scores +10/s, so the tutorial is teaching the real target, not a
# number invented for the tutorial.
IDEAL_LOW, IDEAL_HIGH = 0.90, 1.10


def _supply_demand_ratio(state) -> float:
    demand = state.demand_mw
    return state.total_actual_mw / demand if demand > 0 else 1.0


def _supply_raised(state, ctx) -> bool:
    """Any source's requested output pushed meaningfully above where it started.
    Accepts whichever plant the player reaches for, not just the suggested one."""
    baseline = ctx.get("baseline_requested", {})
    return any(s.requested_pct > baseline.get(s.key, 0.0) + 0.02 for s in state.sources)


def _balanced(state, ctx) -> bool:
    return IDEAL_LOW <= _supply_demand_ratio(state) <= IDEAL_HIGH


CONDITIONS = {
    "supply_raised": _supply_raised,
    "balanced": _balanced,
}

STEPS = [
    {
        "id": "intro",
        "portrait": portraits.EXPLAINING,
        "speaker": SPEAKER,
        "lines": [
            "0400 hours. Whole city's asleep. The grid never gets to be.",
            "Name's Gattie. Thirty years on this desk. Couple minutes, it's yours.",
        ],
    },
    {
        "id": "readout",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "supply_demand",
        "lines": [
            "SUPPLY is what we're making. DEMAND is what the city's pulling.",
            "Those two have to match. Every second.",
            "You can't store this stuff. You make it, the city burns it, right now.",
        ],
    },
    {
        "id": "tank",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "tank",
        "lines": [
            "That tank is the same balance, in water. Level holds when supply meets demand.",
            "Let it run dry and the city browns out.",
            "Overfill it and you're cooking the hardware. Keep the rim green.",
        ],
    },
    {
        "id": "raise_supply",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "gas_card",
        "wait_for": "supply_raised",
        "lines": [
            "Right now we're short. Demand's climbing and we're behind it.",
            "Grab a plant's handle and pull it up.",
            "Reach for gas first. It ramps in seconds. Nuclear and coal take their time.",
        ],
        "action_hint": "Pull a plant's handle up",
        "success": {
            "portrait": portraits.HAPPY,
            "text": "There it is. Watch the supply climb to meet the load.",
        },
        "correction": {
            "portrait": portraits.TALKING,
            "text": "Not there. The handles are on the plant cards up top.",
        },
    },
    {
        "id": "balance",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "supply_demand",
        "wait_for": "balanced",
        "lines": [
            "Now feather it in. Get supply inside ten percent of demand.",
            "Overshoot, ease it back. When it settles, the number goes green: BALANCED.",
        ],
        "action_hint": "Land supply within 10% of demand",
        "success": {
            "portrait": portraits.HAPPY,
            "text": "Balanced. Frequency's steady, every home's lit. That's the job.",
        },
        "correction": {
            "portrait": portraits.TALKING,
            "text": "Work the handles slow. Watch the big number, not the plants.",
        },
    },
    {
        "id": "speed",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "speed_control",
        "lines": [
            "Clock's down here. Run it fast when it's quiet, slow when it's hairy.",
            "SPACE stops the clock. R starts the day over.",
        ],
    },
    {
        "id": "outro",
        "portrait": portraits.NEUTRAL,
        "speaker": SPEAKER,
        "lines": [
            "Load climbs all morning as the city wakes.",
            "It peaks in the evening. Everyone home, every AC running.",
            "Stay ahead of it. She's your grid now. Don't let the lights go out.",
        ],
    },
]
