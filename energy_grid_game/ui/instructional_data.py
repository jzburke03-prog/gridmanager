"""Instructional Mode's four-day script (SPEC-1.1 §3).

Same step schema and same gating mechanism as ui/tutorial_data.py — id, portrait,
speaker, lines, highlight, wait_for, action_hint, success, correction — plus two
additions:

    "learn_more": "<source_key>"   optional; renders a two-pager button when
                                  ui/callouts has an entry for that key
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
    "text": "Balanced. Every home lit, frequency steady. That's the whole job.",
}
_WORK_THE_HANDLES = {
    "portrait": portraits.TALKING,
    "text": "Work the handles slow. Watch the big number, not the plants.",
}


DAYS = {
    # ---------------------------------------------------------------- day 1
    1: [
        {
            "id": "d1_intro",
            "portrait": portraits.EXPLAINING,
            "speaker": SPEAKER,
            "lines": [
                "0400. City's asleep. The grid never gets to be.",
                "Name's Gattie. Four days, then this desk is yours.",
                "Today there's one handle. Everything else can wait.",
            ],
        },
        {
            "id": "d1_readout",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "supply_demand",
            "lines": [
                "SUPPLY is what we're making. DEMAND is what the city's pulling.",
                "Those two have to match. Every second of every day.",
                "You can't store this stuff. You make it, the city burns it, right now.",
            ],
        },
        {
            "id": "d1_city",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "city",
            "lines": [
                "That's the city from above. Every lit block is one we're carrying.",
                "Dark right now is fine — nobody's up. Watch it wake as the day comes.",
                "Come up short and blocks drop, outskirts first.",
            ],
        },
        {
            "id": "d1_raise",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "spigot_panel",
            "wait_for": "generic_raised",
            "lines": [
                "One handle. Marked ELECTRICITY. Grab it and pull it up.",
                "No fuel, no warm-up, no bill. Just supply. Move it and watch.",
            ],
            "action_hint": "Pull the electricity handle up",
            "success": {
                "portrait": portraits.HAPPY,
                "text": "There it is. Supply climbing to meet the load.",
            },
            "correction": {
                "portrait": portraits.TALKING,
                "text": "Not there. The handle's on the card up top.",
            },
        },
        {
            "id": "d1_balance",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "supply_demand",
            "wait_for": "balanced",
            "lines": [
                "Now feather it in. Get supply inside ten percent of demand.",
                "Overshoot, ease it back. When it settles the number goes green.",
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
                "That shape is the demand curve. It's the whole game.",
                "Flat overnight. Climbs as the city wakes. Peaks when everyone's home.",
                "Your job is to stay on it. Not near it — on it.",
            ],
        },
        {
            "id": "d1_outro",
            "portrait": portraits.NEUTRAL,
            "speaker": SPEAKER,
            "highlight": "speed_control",
            "lines": [
                "Clock's down here. Run it fast when it's quiet, slow when it's hairy.",
                "SPACE stops it. Ride the curve to 0400 and we'll talk.",
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
                "Day two. That magic handle's gone — it was never real.",
                "Real power comes from plants that burn something. Starting with gas.",
            ],
        },
        {
            "id": "d2_gas",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "gas_card",
            "learn_more": "gas",
            "lines": [
                "Combined-cycle gas. Ramps in seconds, does most of the work.",
                "Same job as yesterday's handle — but this one costs money.",
            ],
        },
        {
            "id": "d2_price",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "supply_demand",
            "lines": [
                "New readout: GRID PRICE. What the last megawatt cost us.",
                "It isn't fixed. Gas gets dearer the harder the whole grid is pulling.",
            ],
        },
        {
            "id": "d2_peaker",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "spigot_panel",
            "wait_for": "peaker_running",
            "learn_more": "peaker",
            "lines": [
                "Here's why. Gas alone won't cover the evening peak.",
                "So you reach for the peaker — a jet engine on a slab. Thirsty.",
                "Open it and watch the price. That jump is the lesson.",
            ],
            "action_hint": "Bring the gas peaker online",
            "success": {
                "portrait": portraits.HAPPY,
                "text": "See the price move? That's the peaker setting it. Costly minutes.",
            },
            "correction": {
                "portrait": portraits.TALKING,
                "text": "The peaker's the small one next to gas. Open its handle.",
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
                "Day three. Running the whole city on gas is madness — you saw the bill.",
                "Meet baseload. Coal and nuclear. Cheap, steady, and slow.",
            ],
        },
        {
            "id": "d3_baseload",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "spigot_panel",
            "wait_for": "baseload_running",
            "learn_more": "coal",
            "lines": [
                "These take their time. Minutes, not seconds. So you set them early.",
                "Park them under the load and let them carry the floor all day.",
                "Bring both up and leave them there.",
            ],
            "action_hint": "Bring coal and nuclear online",
            "success": {
                "portrait": portraits.HAPPY,
                "text": "Good. That's your floor. Now gas only has to cover the swing.",
            },
            "correction": {
                "portrait": portraits.TALKING,
                "text": "Coal and nuclear both. They're slow — give them a moment.",
            },
        },
        {
            "id": "d3_nuclear",
            "portrait": portraits.TALKING,
            "speaker": SPEAKER,
            "highlight": "spigot_panel",
            "learn_more": "nuclear",
            "lines": [
                "One rule about nuclear, and I mean it.",
                "Never drop it hard. Pull it below its minimum and it SCRAMs.",
                "That's a reactor trip. Ninety seconds of nothing and a ruined day.",
            ],
        },
        {
            "id": "d3_price",
            "portrait": portraits.EXPLAINING,
            "speaker": SPEAKER,
            "lines": [
                "Their prices barely move — the fuel's cheap and they never stop.",
                "That's the trade: gas is fast and dear, baseload is cheap and stubborn.",
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
                "Last day. Everything's yours now — including the ones you can't command.",
                "Solar, wind, hydro. Free power, on their schedule and not yours.",
            ],
        },
        {
            "id": "d4_renewables",
            "portrait": portraits.POINTING,
            "speaker": SPEAKER,
            "highlight": "spigot_panel",
            "wait_for": "renewable_opened",
            "learn_more": "solar",
            "lines": [
                "Solar peaks at midday and is gone by supper. Wind comes and goes.",
                "You don't throttle these — you open them and take what's there.",
                "Open one up. Watch what it actually gives you against what you asked.",
            ],
            "action_hint": "Open a renewable source",
            "success": {
                "portrait": portraits.HAPPY,
                "text": "Handle's wide open, output's whatever the weather says. That's the deal.",
            },
            "correction": {
                "portrait": portraits.TALKING,
                "text": "Solar, wind or hydro — any of the three. Open it wide.",
            },
        },
        {
            "id": "d4_weather",
            "portrait": portraits.TALKING,
            "speaker": SPEAKER,
            "learn_more": "wind",
            "lines": [
                "Weather's live today. A gust puts wind at maximum for a while.",
                "Rain dims the panels and fills the reservoirs. Cloud kills solar outright.",
                "You can't stop any of it. You can only leave yourself room.",
            ],
        },
        {
            "id": "d4_outro",
            "portrait": portraits.NEUTRAL,
            "speaker": SPEAKER,
            "highlight": "supply_demand",
            "lines": [
                "Seven handles, one curve, no storage. Cheap, clean, reliable — pick two.",
                "Ride it to 0400 and the desk is yours.",
            ],
        },
    ],
}

# One line per day for the end-of-day summary, framing what that day was about.
DAY_NOTES = {
    1: "Day one was one thing only: does supply track demand? Check the time you "
       "held the band — that number is the job.",
    2: "Today you started paying for it. Balance first, but notice what the peak "
       "cost you when the peaker was running.",
    3: "Baseload carries the floor cheaply; gas covers the swing. Compare today's "
       "spend against yesterday's.",
    4: "Full grid, live weather, real stakes. From here on the lights are yours "
       "to keep on.",
}
