"""Instructional Mode's four-day script (SPEC-1.1 §3).

Same step schema and same gating mechanism as ui/tutorial_data.py: id, portrait,
speaker, lines, highlight, wait_for, action_hint, success, correction, plus two
additions:

    "learn_more": "<source_key>"   optional; renders a two-pager button when
                                  ui/callouts has an entry for that key
    "action_regions": ["<key>"]    optional; gameplay click-through targets
                                  when the visual highlight is elsewhere
    DAY_NOTES[day]                 one line for the end-of-day summary

Every step teaches something the game actually implements. Conditions gate on
real state, so a player cannot be talked past a lesson they haven't performed.
"""
from ui import portraits
from ui.tutorial_data import IDEAL_HIGH, IDEAL_LOW, _supply_demand_ratio

SPEAKER = "Gattie"


def _source(state, key):
    for s in state.sources:
        if s.key == key:
            return s
    return None


def _generic_raised(state, ctx):
    src = _source(state, "generic")
    return src is not None and src.requested_pct > 0.05


def _balanced(state, ctx):
    return IDEAL_LOW <= _supply_demand_ratio(state) <= IDEAL_HIGH


def _peaker_running(state, ctx):
    src = _source(state, "peaker")
    return src is not None and src.actual_pct > 0.05


def _baseload_running(state, ctx):
    """Both slow plants actually carrying load, not merely requested."""
    return all((s := _source(state, k)) is not None and s.actual_pct > 0.15
               for k in ("coal", "nuclear"))


def _renewable_opened(state, ctx):
    return any((s := _source(state, k)) is not None and s.requested_pct > 0.2
               for k in ("solar", "wind", "hydro"))


CONDITIONS = {
    "generic_raised": _generic_raised,
    "balanced": _balanced,
    "peaker_running": _peaker_running,
    "baseload_running": _baseload_running,
    "renewable_opened": _renewable_opened,
}

_ON_BALANCE = {
    "portrait": portraits.HAPPY,
    "text": "Balanced. Every home lit, frequency steady. That's the whole job right there.",
}
_WORK_THE_HANDLES = {
    "portrait": portraits.TALKING,
    "text": "Work the handles slowly. Watch the big number, not the plants.",
}


DAYS = {
    # ---------------------------------------------------------------- day 1
    1: [
        {
            "id": "d1_intro",
            "portrait": portraits.EXPLAINING,
            "speaker": SPEAKER,
            "lines": [
                "It's four in the morning. The city's asleep, but the grid is already awake.",
                "Name's Gattie. Give me four days and this desk is yours.",
                "Today there's just one handle. Everything else can wait.",
            ],
        },
        {
            "id": "d1_readout",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "supply_demand",
            "lines": [
                "SUPPLY is what we're making. DEMAND is what the city's pulling from us.",
                "Those two have to match, every second of every day.",
                "You can't store this stuff. The moment you make it, the city burns it.",
            ],
        },
        {
            "id": "d1_city",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "city",
            "lines": [
                "That's the city from above. Every lit block is one we're carrying.",
                "Dark right now is fine. Nobody is up yet. Watch it wake as the day comes on.",
                "Come up short and blocks go dark, the outskirts first.",
            ],
        },
        {
            "id": "d1_raise",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "pin_generic",
            "wait_for": "generic_raised",
            "lines": [
                "One handle, marked ELECTRICITY. Grab it and pull it up.",
                "No fuel stack, no warm-up story, no bill yet. Just supply. Move it and watch.",
            ],
            "action_hint": "Pull the electricity handle up",
            "success": {
                "portrait": portraits.HAPPY,
                "text": "There it is. Supply's climbing to meet the load.",
            },
            "correction": {
                "portrait": portraits.TALKING,
                "text": "Not there. The handle sits right over the plant itself.",
            },
        },
        {
            "id": "d1_balance",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "supply_demand",
            "action_regions": ["pins"],
            "wait_for": "balanced",
            "lines": [
                "Now feather it in. Get supply within ten percent of demand.",
                "If you overshoot, ease it back. When it settles, the number goes green.",
            ],
            "action_hint": "Land supply within 10% of demand",
            "success": _ON_BALANCE,
            "correction": _WORK_THE_HANDLES,
        },
        {
            "id": "d1_curve",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "chart",
            "learn_more": "demand_curve",
            "lines": [
                "That shape is the demand curve. It's the whole game right there.",
                "Flat overnight, climbing as the city wakes, peaking when everyone's home.",
                "Your job is to stay on it. Not near it, on it.",
            ],
        },
        {
            "id": "d1_outro",
            "portrait": portraits.NEUTRAL,
            "speaker": SPEAKER,
            "highlight": "speed_control",
            "lines": [
                "The clock's down here. Run it fast when it's quiet, slow when it gets hairy.",
                "SPACE stops it. Ride the curve to four in the morning and we'll talk.",
            ],
        },
    ],
    # ---------------------------------------------------------------- day 2
    2: [
        {
            "id": "d2_intro",
            "portrait": portraits.EXPLAINING,
            "speaker": SPEAKER,
            "lines": [
                "Day two. That training handle is gone because real grids do not have magic power.",
                "Real power comes from plants that burn something. We start with gas.",
            ],
        },
        {
            "id": "d2_gas",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "pin_gas",
            "learn_more": "gas",
            "lines": [
                "This is combined-cycle gas. It is flexible and efficient for gas, but it is not instant.",
                "In this sim it moves quickly so you can feel the dispatch decision. Every MW costs real money now.",
            ],
        },
        {
            "id": "d2_price",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "supply_demand",
            "lines": [
                "The spend module is live now. Price per MWh shows what the next slice of power costs.",
                "It is not fixed. Gas gets more expensive as the grid leans harder on it.",
            ],
        },
        {
            "id": "d2_peaker",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "pin_peaker",
            "wait_for": "peaker_running",
            "learn_more": "peaker",
            "lines": [
                "Here's why. Gas alone won't cover the evening peak.",
                "So you reach for the peaker: a simple-cycle turbine kept for short, expensive peaks.",
                "Open it and watch the price. That jump is the lesson right there.",
            ],
            "action_hint": "Bring the gas peaker online",
            "success": {
                "portrait": portraits.HAPPY,
                "text": "See the price move? That is the peaker setting the marginal cost. Useful, but costly.",
            },
            "correction": {
                "portrait": portraits.TALKING,
                "text": "The peaker's the little jet-engine plant. Go open its handle.",
            },
        },
        {
            "id": "d2_outro",
            "portrait": portraits.NEUTRAL,
            "speaker": SPEAKER,
            "lines": [
                "Balance still comes first. Nobody thanks you for a cheap blackout.",
                "But keep an eye on the spend. Tonight I'll show you the bill.",
            ],
        },
    ],
    # ---------------------------------------------------------------- day 3
    3: [
        {
            "id": "d3_intro",
            "portrait": portraits.EXPLAINING,
            "speaker": SPEAKER,
            "lines": [
                "Day three. Running the whole city on gas gets expensive fast. You saw the bill.",
                "Meet the steady plants: coal and nuclear. Cheap energy, heavy machinery, slow decisions.",
            ],
        },
        {
            "id": "d3_baseload",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "pins",
            "wait_for": "baseload_running",
            "learn_more": "coal",
            "lines": [
                "Coal can move more than nuclear, but both are plants you plan ahead.",
                "Set them under the load and let them carry the floor while gas covers the swing.",
                "Bring both of them up and give them time to settle.",
            ],
            "action_hint": "Bring coal and nuclear online",
            "success": {
                "portrait": portraits.HAPPY,
                "text": "Good. That is your floor now. Gas only has to cover the swing.",
            },
            "correction": {
                "portrait": portraits.TALKING,
                "text": "Coal and nuclear, both of them. They are slow plants, so give them a moment.",
            },
        },
        {
            "id": "d3_nuclear",
            "portrait": portraits.TALKING,
            "speaker": SPEAKER,
            "highlight": "pin_nuclear",
            "learn_more": "nuclear",
            "lines": [
                "One rule about nuclear, and I mean it.",
                "Never drop it hard. Pull it below its minimum and it SCRAMs.",
                "That is a reactor trip: ninety seconds of nothing and a ruined day.",
            ],
        },
        {
            "id": "d3_price",
            "portrait": portraits.EXPLAINING,
            "speaker": SPEAKER,
            "lines": [
                "Their prices barely move because the fuel is cheap and they are meant to run steadily.",
                "That's the trade: gas is fast and expensive, baseload is cheap and stubborn.",
            ],
        },
    ],
    # ---------------------------------------------------------------- day 4
    4: [
        {
            "id": "d4_intro",
            "portrait": portraits.EXPLAINING,
            "speaker": SPEAKER,
            "lines": [
                "Last day. Everything is yours now, including the ones you cannot command.",
                "Solar, wind, hydro: free power, but on their schedule, not yours.",
            ],
        },
        {
            "id": "d4_renewables",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "pins",
            "wait_for": "renewable_opened",
            "learn_more": "solar",
            "lines": [
                "Solar peaks at midday and is gone by suppertime. Wind comes and goes.",
                "You do not throttle these like gas. You open them up and take what the weather gives.",
                "Open one up and watch what it actually gives you against what you asked for.",
            ],
            "action_hint": "Open a renewable source",
            "success": {
                "portrait": portraits.HAPPY,
                "text": "Handle's wide open, output's whatever the weather says. That's the deal.",
            },
            "correction": {
                "portrait": portraits.TALKING,
                "text": "Solar, wind, or hydro. Any of the three. Open it up wide.",
            },
        },
        {
            "id": "d4_weather",
            "portrait": portraits.TALKING,
            "speaker": SPEAKER,
            "learn_more": "wind",
            "lines": [
                "Weather's live today. A gust puts wind at maximum for a while.",
                "Rain dims the panels but fills the reservoirs. Cloud kills solar outright.",
                "You cannot stop any of it. You can only leave yourself room.",
            ],
        },
        {
            "id": "d4_outro",
            "portrait": portraits.NEUTRAL,
            "speaker": SPEAKER,
            "highlight": "supply_demand",
            "lines": [
                "Seven handles, one curve, no storage. Cheap, clean, reliable. You will feel the tradeoffs.",
                "Ride it to four in the morning and the desk is yours.",
            ],
        },
    ],
}

# One line per day for the end-of-day summary, framing what that day was about.
DAY_NOTES = {
    1: "Day one came down to one thing: does supply track demand? Check the time "
       "you held the band. That number is the job.",
    2: "Today you started paying for it. Balance still comes first, but notice "
       "what the peak cost you while the peaker was running.",
    3: "Baseload carries the floor cheaply; gas covers the swing. Compare today's "
       "spend against yesterday's.",
    4: "Full grid, live weather, real stakes. From here on out, the lights are "
       "yours to keep on.",
}
