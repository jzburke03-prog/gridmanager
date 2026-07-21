"""Hand-authored 16-bit pixel-art sprites for the menu selection screens.

No image-generation tool or art assets are available here, so every icon is
written directly as a tiny character grid + palette and rendered to a
nearest-neighbor-scaled surface at runtime — the same procedural approach the
rest of the game uses. Sprites are cached per (name, scale, tint).
"""
import pygame

_cache = {}

# transparent cell marker
_T = "."


def _render(grid, palette, scale):
    h = len(grid)
    w = max(len(r) for r in grid)
    surf = pygame.Surface((w * scale, h * scale), pygame.SRCALPHA)
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            col = palette.get(ch)
            if col:
                surf.fill(col, (x * scale, y * scale, scale, scale))
    return surf


# ---------------------------------------------------------------------------
# Difficulty icons: monochrome (two shades), tinted with the tier accent.
#   X = main, o = shadow
# ---------------------------------------------------------------------------
_DIFF_GRIDS = {
    "easy": [           # leaf — calm, low-stakes
        "............",
        ".......XX...",
        ".....XXXXo..",
        "....XXXXXoo.",
        "...XXXXoXoo.",
        "..XXXXo.Xoo.",
        "..XXXo..Xoo.",
        "..oXo...Xo..",
        "........Xo..",
        ".......Xo...",
        "....oooo....",
        "............",
    ],
    "moderate": [       # gauge / dial — balanced
        "............",
        "...XXXXXX...",
        "..X......X..",
        ".X...XX...X.",
        ".X..XX....X.",
        ".X.XX.....X.",
        ".X.X......X.",
        "..X......X..",
        "...XoooX....",
        "..ooooooo...",
        "............",
        "............",
    ],
    "hard": [           # lightning bolt — punishing
        "......XXX...",
        ".....XXo....",
        "....XXo.....",
        "...XXo......",
        "..XXXXXo....",
        "....XXo.....",
        "...XXo......",
        "..XXo.......",
        ".XXo........",
        ".Xo.........",
        "............",
        "............",
    ],
    "expert": [         # skull — lethal
        "...XXXXXX...",
        "..XXXXXXXX..",
        ".XXXXXXXXXX.",
        ".XXoXXXXoXX.",
        ".XXoXXXXoXX.",
        ".XXXXXXXXXX.",
        ".XXXX..XXXX.",
        "..XXXXXXXX..",
        "...X.XX.X...",
        "...XoXXoX...",
        "............",
        "............",
    ],
}


# ---------------------------------------------------------------------------
# Region / mode emblems: full-color little scenes.
# ---------------------------------------------------------------------------
_SUN = (255, 210, 96)
_SUN2 = (240, 150, 60)
_WIND = (228, 234, 246)
_WIND2 = (150, 162, 180)
_WATER = (92, 172, 232)
_WATER2 = (48, 112, 182)
_STEEL = (124, 134, 156)
_STEEL2 = (78, 88, 112)
_STEAM = (206, 212, 226)
_FLAME = (245, 150, 60)
_FLAME2 = (255, 214, 110)
_FLAME3 = (228, 84, 58)
_ICE = (200, 226, 255)
_AMBER = (240, 190, 100)
_AMBER2 = (176, 132, 66)

_EMBLEMS = {
    "sun": ([
        "......SS......",
        "..o...SS...o..",
        "...o.SSSS.o...",
        "....SSSSSS....",
        "..SSSSSSSSSS..",
        "S.SSSSSSSSSS.S",
        "S.SSSSSSSSSS.S",
        "..SSSSSSSSSS..",
        "....SSSSSS....",
        "...o.SSSS.o...",
        "..o...SS...o..",
        "......SS......",
        ".............."],
     {"S": _SUN, "o": _SUN2}),
    "wind": ([
        "......W.......",
        ".....WW.......",
        "..WW.WW..W....",
        "...WWWW.WW....",
        "....WWWWW.....",
        "..WWW.p.WWW...",
        ".W...WpW...W..",
        ".....WpW......",
        "......p.......",
        "......p.......",
        "......p.......",
        ".....ppp......",
        "....ppppp....."],
     {"W": _WIND, "p": _WIND2}),
    "hydro": ([
        "......B.......",
        "......BB......",
        ".....BBBB.....",
        ".....BBBB.....",
        "....BBBBBB....",
        "...BBBBBBb....",
        "..BBBBBBBBb...",
        "..BBBBBBBBb...",
        "..BBBBBBBbb...",
        "..bBBBBBbb....",
        "...bBBBbb.....",
        "....bbbb......",
        "......b......."],
     {"B": _WATER, "b": _WATER2}),
    "tower": ([
        "...s...ss.....",
        "..s.s.s.s.....",
        "...ssss.......",
        "....ss........",
        "...TTTTTT.....",
        "...T....T.....",
        "..TT....TT....",
        "..T......T....",
        ".TT......TT...",
        ".T........T...",
        ".TTTTTTTTTT...",
        ".tttttttttt...",
        ".tttttttttt..."],
     {"T": _STEEL, "t": _STEEL2, "s": _STEAM}),
    "flame": ([
        "......F.......",
        ".....FF.......",
        "....FyF.......",
        "...FyyF.......",
        "...FyyyF......",
        "..FyyyyF......",
        "..FyyyyyF.....",
        ".FyyyyyyF.....",
        ".ryyyyyyF.....",
        ".rryyyyrr.....",
        "..rryyrr......",
        "...rrrr.......",
        ".............."],
     {"F": _FLAME, "y": _FLAME2, "r": _FLAME3}),
    "snow": ([
        "......C.......",
        "...C..C..C....",
        "....C.C.C.....",
        ".....CCC......",
        ".C.CCCCCCC.C..",
        "..CCCCCCCCC...",
        "CCCCCCCCCCCCC.",
        "..CCCCCCCCC...",
        ".C.CCCCCCC.C..",
        ".....CCC......",
        "....C.C.C.....",
        "...C..C..C....",
        "......C......."],
     {"C": _ICE}),
    "grid": ([
        "......G.......",
        ".....GGG......",
        "....G.G.G.....",
        "...GG.G.GG....",
        "..G..GGG..G...",
        "...GGG.GGG....",
        "....G.G.G.....",
        "...GG.G.GG....",
        "..G...G...G...",
        "......G.......",
        ".....gGg......",
        "....gg.gg.....",
        "...gg...gg...."],
     {"G": _AMBER, "g": _AMBER2}),
}

# region EIA code (None = Standard) -> emblem
REGION_EMBLEM = {
    None: "grid",
    "ERCO": "flame",
    "CAL": "sun",
    "NYIS": "hydro",
    "PJM": "tower",
    "MISO": "wind",
    "ISNE": "snow",
    "SWPP": "wind",
}


def difficulty_icon(key, color, scale=3):
    ck = ("diff", key, color, scale)
    if ck not in _cache:
        pal = {"X": color, "o": tuple(int(c * 0.55) for c in color)}
        _cache[ck] = _render(_DIFF_GRIDS[key], pal, scale)
    return _cache[ck]


def emblem(name, scale=3):
    ck = ("emb", name, scale)
    if ck not in _cache:
        grid, pal = _EMBLEMS[name]
        _cache[ck] = _render(grid, pal, scale)
    return _cache[ck]


def region_emblem(code, scale=3):
    return emblem(REGION_EMBLEM.get(code, "grid"), scale)


def play_glyph(color, scale=4):
    """A chunky pixel play-triangle for the START button."""
    ck = ("play", color, scale)
    if ck not in _cache:
        grid = [
            "X...",
            "XX..",
            "XXX.",
            "XXXX",
            "XXX.",
            "XX..",
            "X...",
        ]
        _cache[ck] = _render(grid, {"X": color}, scale)
    return _cache[ck]
