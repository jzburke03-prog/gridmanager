#!/usr/bin/env python3
"""One-shot asset repair for the mentor art that ships without real alpha.

Scope is deliberately narrow: only the three files in TARGETS below. Two of the
five mentor PNGs (Gattie_Explaining_Talking, Gattie_Explaining_Pointing) and
chatbox.png were authored as RGB with the light "transparency checkerboard"
pattern baked into their pixels, so ~76% of each portrait is an opaque near-white
slab. Gattie_GoodJob and Gattie_Angry already have real alpha and are NOT touched.

This is NOT a general white-removal pass. A blanket "make white transparent" rule
would punch holes straight through Gattie's hair, beard, eyes, gingham shirt and
specular highlights, all of which contain near-white pixels. Instead:

  1. Flood fill from the image border through near-white pixels only. Interior
     whites (hair, shirt) are never reachable from the border, so they survive.
  2. Remove enclosed matte remnants: both explaining portraits have a blob of
     background trapped in the narrow seam between the arm and the torso, pinched
     off from the border by anti-aliasing so step 1 cannot reach it. These are
     identified by being large AND sitting in near-black, which separates them
     cleanly from every legitimate white (measured: remnants sit in luminance
     ~17-19, while hair/gingham/eye whites sit in ~117-156).
  3. Erode the white anti-aliasing fringe left where the character meets the
     matte, but only into pixels that are BOTH very light AND nearly neutral in
     hue AND already touching the background. A red-brown hair edge or a blue
     jacket edge fails the neutrality test and is kept.
  4. Feather what remains of the fringe by estimating coverage from how white
     each edge pixel still is, so the silhouette doesn't turn into hard jaggies.

Originals are copied to assets/mentor/original/ before anything is overwritten.

Run from the repo root:
    .venv39/Scripts/python tools/fix_portrait_mattes.py          # repair
    .venv39/Scripts/python tools/fix_portrait_mattes.py --check  # report only
"""
import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import pygame

REPO_ROOT = Path(__file__).resolve().parents[1]
MENTOR_DIR = REPO_ROOT / "assets" / "mentor"
BACKUP_DIR = MENTOR_DIR / "original"

# Only these. The other mentor assets already have correct alpha.
TARGETS = (
    "Gattie_Explaining_Talking.png",
    "Gattie_Explaining_Pointing.png",
    "chatbox.png",
)

# The baked checkerboard alternates between roughly 243 and 255.
MATTE_THRESHOLD = 238

# Fringe erosion: a pixel is matte spill only if it is this light, this close to
# neutral grey, and touching background. Gattie's lightest *kept* features (hair
# highlights, shirt checks) sit below FRINGE_LIGHT or carry visible hue.
FRINGE_LIGHT = 226
FRINGE_NEUTRAL = 16      # max(chan) - min(chan) must be under this to be "white"
FRINGE_PASSES = 2

# Feathering: remaining edge pixels between these two get partial alpha.
FEATHER_LOW = 198
FEATHER_HIGH = 226

# Enclosed matte remnants: a white island is only background if it is BOTH large
# and sitting in near-black. Both tests are required. Size alone would be
# arbitrary; darkness alone would eventually catch an eye white. Measured on the
# real assets, the two remnants score (223px, lum 17) and (515px, lum 19), while
# the largest legitimate island is (52px, lum 117) -- a 6x separation.
ISLAND_MIN_PX = 100
ISLAND_MAX_SURROUND_LUM = 90

# Removing an island leaves its anti-aliased halo behind as a bright outline
# around the new hole. Because an island is only ever removed when it sits in
# near-black (median surround luminance < 90, measured 17-19), anything still
# this bright next to it is halo, not artwork -- the jacket's own highlights
# there sit around 60-90. This erosion is local to removed islands only.
ISLAND_HALO_LUM = 110
ISLAND_HALO_PASSES = 4


def _flood_matte(light: np.ndarray) -> np.ndarray:
    """Scanline flood fill from the border through `light` pixels only."""
    w, h = light.shape
    filled = np.zeros_like(light)
    stack = []
    for x in range(w):
        for y in (0, h - 1):
            if light[x, y]:
                stack.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if light[x, y]:
                stack.append((x, y))

    while stack:
        x, y = stack.pop()
        if filled[x, y] or not light[x, y]:
            continue
        row, done = light[:, y], filled[:, y]
        x0 = x
        while x0 > 0 and row[x0 - 1] and not done[x0 - 1]:
            x0 -= 1
        x1 = x
        while x1 < w - 1 and row[x1 + 1] and not done[x1 + 1]:
            x1 += 1
        filled[x0:x1 + 1, y] = True
        for ny in (y - 1, y + 1):
            if not (0 <= ny < h):
                continue
            span = light[x0:x1 + 1, ny] & ~filled[x0:x1 + 1, ny]
            idx = np.flatnonzero(span)
            if idx.size == 0:
                continue
            breaks = np.flatnonzero(np.diff(idx) > 1)
            for s in np.concatenate(([idx[0]], idx[breaks + 1])):
                stack.append((x0 + int(s), ny))
    return filled


def _enclosed_matte_islands(white: np.ndarray, whiteish: np.ndarray,
                            lum: np.ndarray, border_matte: np.ndarray) -> np.ndarray:
    """White regions the border flood fill could not reach, that are background
    anyway: large, and surrounded by near-black rather than by skin/hair/fabric."""
    from collections import deque

    w, h = white.shape
    candidates = white & ~border_matte
    seen = np.zeros_like(candidates)
    out = np.zeros_like(candidates)

    for sx, sy in zip(*np.where(candidates)):
        if seen[sx, sy]:
            continue
        queue = deque([(sx, sy)])
        seen[sx, sy] = True
        pixels = []
        while queue:
            x, y = queue.popleft()
            pixels.append((x, y))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and candidates[nx, ny] and not seen[nx, ny]:
                    seen[nx, ny] = True
                    queue.append((nx, ny))

        if len(pixels) < ISLAND_MIN_PX:
            continue
        # Sample luminance a few px out so the reading is of the material around
        # the island, not of the island's own anti-aliased halo.
        xs = [p[0] for p in pixels]
        ys = [p[1] for p in pixels]
        x0, x1 = max(0, min(xs) - 4), min(w - 1, max(xs) + 4)
        y0, y1 = max(0, min(ys) - 4), min(h - 1, max(ys) + 4)
        around = lum[x0:x1 + 1, y0:y1 + 1][~whiteish[x0:x1 + 1, y0:y1 + 1]]
        if around.size and float(np.median(around)) < ISLAND_MAX_SURROUND_LUM:
            for x, y in pixels:
                out[x, y] = True
    return out


def _neighbours(mask: np.ndarray) -> np.ndarray:
    """True where a pixel is 4-adjacent to a True cell in `mask`."""
    out = np.zeros_like(mask)
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def build_alpha(rgb: np.ndarray):
    """rgb: (w, h, 3) uint8 -> (alpha (w,h) uint8, stats dict)."""
    rgb_i = rgb.astype(np.int16)
    lo = rgb_i.min(axis=2)
    hi = rgb_i.max(axis=2)
    lum = rgb_i.mean(axis=2)
    neutral = (hi - lo) <= FRINGE_NEUTRAL

    # 1) background reachable from the image border
    matte = _flood_matte((rgb_i >= MATTE_THRESHOLD).all(axis=2))
    flood_px = int(matte.sum())

    # 2) background trapped inside the silhouette (arm/torso seam)
    white = (lo >= MATTE_THRESHOLD) & neutral
    whiteish = (lo >= 200) & ((hi - lo) <= 24)   # island + its halo
    islands = _enclosed_matte_islands(white, whiteish, lum, matte)
    if islands.any():
        # eat each island's bright halo so the hole doesn't get a white outline
        for _ in range(ISLAND_HALO_PASSES):
            spill = _neighbours(islands) & ~islands & ~matte & (lum >= ISLAND_HALO_LUM)
            if not spill.any():
                break
            islands |= spill
    island_px = int(islands.sum())
    matte |= islands

    # 3) erode the white halo, only into light + neutral + border-touching pixels.
    #    Runs after the islands are merged in, so their halos are cleaned too.
    fringe_px = 0
    for _ in range(FRINGE_PASSES):
        spill = _neighbours(matte) & ~matte & neutral & (lo >= FRINGE_LIGHT)
        if not spill.any():
            break
        fringe_px += int(spill.sum())
        matte |= spill

    alpha = np.where(matte, 0, 255).astype(np.uint8)

    # 4) feather whatever fringe survives, by how white it still is
    edge = _neighbours(matte) & ~matte & neutral
    band = edge & (lo > FEATHER_LOW) & (lo < FEATHER_HIGH)
    if band.any():
        coverage = (FEATHER_HIGH - lo[band]).astype(np.float32) / (FEATHER_HIGH - FEATHER_LOW)
        alpha[band] = np.clip(coverage * 255.0, 0, 255).astype(np.uint8)

    return alpha, {
        "flood": flood_px,
        "islands": island_px,
        "fringe": fringe_px,
        "feather": int(band.sum()),
        "kept": int((alpha > 0).sum()),
    }


def repair(path: Path, check_only: bool) -> bool:
    surface = pygame.image.load(str(path))
    has_alpha = surface.get_bitsize() == 32 and surface.get_masks()[3] != 0
    if has_alpha:
        print(f"  {path.name:38s} already has alpha - skipped")
        return False
    if check_only:
        print(f"  {path.name:38s} NEEDS REPAIR (RGB, no alpha channel)")
        return True

    rgb = pygame.surfarray.array3d(surface)
    alpha, stats = build_alpha(rgb)

    out = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    pygame.surfarray.blit_array(out, rgb)
    pygame.surfarray.pixels_alpha(out)[:] = alpha

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / path.name
    if not backup.exists():
        shutil.copy2(path, backup)

    pygame.image.save(out, str(path))
    total = rgb.shape[0] * rgb.shape[1]
    print(f"  {path.name:38s} matte {stats['flood'] / total:5.1%}  "
          f"islands {stats['islands']:4d}px  fringe {stats['fringe']:5d}px  "
          f"feather {stats['feather']:5d}px  kept {stats['kept'] / total:5.1%}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report which targets need repair; write nothing")
    args = parser.parse_args()

    pygame.init()
    pygame.display.set_mode((1, 1))

    missing = [n for n in TARGETS if not (MENTOR_DIR / n).is_file()]
    if missing:
        sys.exit(f"missing mentor assets: {', '.join(missing)}")

    print(f"{'checking' if args.check else 'repairing'} {MENTOR_DIR}")
    changed = sum(repair(MENTOR_DIR / name, args.check) for name in TARGETS)
    if not args.check and changed:
        print(f"originals backed up to {BACKUP_DIR}")
    print(f"{changed} file(s) {'need repair' if args.check else 'repaired'}")
    pygame.quit()


if __name__ == "__main__":
    main()
