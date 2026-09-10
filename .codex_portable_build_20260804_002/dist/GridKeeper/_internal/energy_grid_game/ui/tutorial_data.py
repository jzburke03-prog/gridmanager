"""Tutorial script and completion conditions, kept out of the render code.

Every step below teaches something the game actually implements: the SUPPLY vs
DEMAND readout the HUD draws, the isometric city, the per-source plant pins, and
the speed/pause controls. No invented commands.

`wait_for` names a key in CONDITIONS; `highlight` names a region key that
main.py supplies from the real layout rects. `action_regions` optionally names
additional region keys that should receive gameplay clicks while a different
region is highlighted.
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
            "It's four in the morning. The whole city is asleep, but the grid is already awake.",
            "Name's Gattie. Thirty years at this desk. Give me a couple of minutes and it's yours.",
        ],
    },
    {
        "id": "readout",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "supply_demand",
        "lines": [
            "SUPPLY is what we're making. DEMAND is what the city's pulling from us.",
            "Those two have to match, every single second.",
            "You can't store this stuff. The moment you make it, the city burns it.",
        ],
    },
    {
        "id": "city",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "city",
        "lines": [
            "That's the city, straight down below us. Every lit block is one we're carrying.",
            "Dark at this hour is normal. Nobody is up yet. Watch it wake as the day comes on.",
            "Come up short and blocks go dark, the outskirts first. Push too much and things burn.",
        ],
    },
    {
        "id": "raise_supply",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "pin_gas",
        "wait_for": "supply_raised",
        "lines": [
            "Right now we're short. Demand's climbing and we're behind it.",
            "Grab a plant's handle and pull it up.",
            "Reach for gas first. It is the flexible plant here. Coal is slower, and nuclear is slower still.",
        ],
        "action_hint": "Pull a plant's handle up",
        "success": {
            "portrait": portraits.HAPPY,
            "text": "There it is. Watch the supply climb up to meet the load.",
        },
        "correction": {
            "portrait": portraits.TALKING,
            "text": "Not there. The handle sits right over the gas plant itself.",
        },
    },
    {
        "id": "balance",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "supply_demand",
        "action_regions": ["pins"],
        "wait_for": "balanced",
        "lines": [
            "Now feather it in. Get supply within ten percent of demand.",
            "If you overshoot, ease it back. When it settles, the number turns green: BALANCED.",
        ],
        "action_hint": "Land supply within 10% of demand",
        "success": {
            "portrait": portraits.HAPPY,
            "text": "Balanced. Frequency's steady, every home's lit up. That's the job.",
        },
        "correction": {
            "portrait": portraits.TALKING,
            "text": "Work the handles slowly. Watch the big number, not the plants.",
        },
    },
    {
        "id": "speed",
        "portrait": portraits.POINTING,
        "speaker": SPEAKER,
        "highlight": "speed_control",
        "lines": [
            "The clock's down here. Run it fast when it's quiet, slow when it gets hairy.",
            "SPACE stops the clock. R starts the day over.",
        ],
    },
    {
        "id": "outro",
        "portrait": portraits.NEUTRAL,
        "speaker": SPEAKER,
        "lines": [
            "Load climbs all morning as the city wakes up.",
            "It peaks in the evening: everyone home, every AC running.",
            "Stay ahead of it. She's your grid now. Don't let the lights go out.",
        ],
    },
]
