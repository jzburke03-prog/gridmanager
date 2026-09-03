"""Dense voxel downtown: a block grid of town buildings with a type/height
gradient (apartment towers downtown -> houses & shops at the fringe).

Pure assignment logic (unit-tested). iso_city stamps these into the tile map and
draws the sprites from ui.voxel_assets.
"""

BLOCK = 4          # tile period of the street grid; one building per block

# target on-screen width (px) per building slug, tuned to ~BLOCK tiles wide
TARGET_W = {"apartment": 66, "department_store": 74, "mall": 60, "school": 78,
            "house": 44, "market": 40}


def building_for(bx, by, dnorm):
    """Slug for the building at block-centre (bx,by), by normalised distance
    from downtown centre dnorm in [0,1]. Deterministic, varied by position."""
    h = (hash((bx, by, 0x51A7)) >> 5) & 0xFFFF
    if dnorm < 0.30:
        return "apartment"                                          # downtown towers
    if dnorm < 0.55:
        return ("apartment", "department_store", "mall", "school")[h % 4]
    if dnorm < 0.80:
        return ("house", "school", "department_store", "market")[h % 4]
    return ("house", "market", "house")[h % 3]                       # fringe


def is_building(bx, by):
    return bx % BLOCK == 2 and by % BLOCK == 2                        # block centre


def is_street(bx, by):
    return bx % BLOCK == 0 or by % BLOCK == 0                         # grid lines
