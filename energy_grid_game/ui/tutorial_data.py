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
        "portrait": portraits.NEUTRAL,
        "speaker": SPEAKER,
        "lines": [
            "04:00. The city's asleep. The grid isn't.",
            "I'm Gattie. Two minutes and you're running it.",
        ],
    },
    {
        "id": "readout",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "supply_demand",
        "lines": [
            "SUPPLY on the left, DEMAND on the right.",
            "Matching those two is the whole job.",
        ],
    },
    {
        "id": "tank",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "tank",
        "lines": [
            "The tank shows the same ratio, in water.",
            "Green rim is good. Empty blacks out, overfull melts down.",
        ],
    },
    {
        "id": "raise_supply",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "gas_card",
        "wait_for": "supply_raised",
        "lines": [
            "You're short right now. Fix it.",
            "Drag a plant's white handle up. Natural Gas responds fastest.",
        ],
        "action_hint": "Drag a handle upward",
        "success": {
            "portrait": portraits.HAPPY,
            "text": "That's it — watch the supply climb.",
        },
        "correction": {
            "portrait": portraits.ANGRY,
            "text": "Not there. The handles are on the plant cards.",
        },
    },
    {
        "id": "balance",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "supply_demand",
        "wait_for": "balanced",
        "lines": [
            "Now land it. Get supply within 10% of demand.",
            "The big number turns green and reads BALANCED.",
        ],
        "action_hint": "Bring the ratio to 90-110%",
        "success": {
            "portrait": portraits.HAPPY,
            "text": "Balanced. Every home on the grid is lit.",
        },
        "correction": {
            "portrait": portraits.ANGRY,
            "text": "Use the sliders. Watch the big number as you drag.",
        },
    },
    {
        "id": "speed",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "speed_control",
        "lines": [
            "Clock controls. SPACE pauses, R restarts.",
        ],
    },
    {
        "id": "outro",
        "portrait": portraits.NEUTRAL,
        "speaker": SPEAKER,
        "lines": [
            "Demand climbs 'til evening, then spikes again at 8.",
            "Keep them matched. She's your grid now.",
        ],
    },
]
