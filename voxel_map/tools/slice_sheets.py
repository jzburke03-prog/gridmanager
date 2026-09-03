"""Slice the newassets generator sprite sheets into clean, transparent frames.

Each sheet is a regular grid of animation frames on a smooth gradient
background. We remove the background per-cell with bilinear-corner subtraction:
the 4 cell corners are pure background, so a bilinear interpolation of them
models the local gradient; pixels far from that model are the sprite (and its
soft smoke), pixels close to it become transparent. Frames are trimmed to
content and saved anchored at bottom-centre (so smoke grows upward without
shifting the plant base).
"""
import json
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]          # D:/Github/gridmanager
SRC = ROOT / "newassets"
OUT = ROOT / "voxel_map" / "assets" / "plants"

# filename -> (tech, rows, cols)
SHEETS = {
    "ChatGPT Image Aug 3, 2026, 04_15_57 AM (1).png": ("peaker", 3, 6),
    "ChatGPT Image Aug 3, 2026, 04_15_58 AM (2).png": ("nuclear", 3, 6),
    "ChatGPT Image Aug 3, 2026, 04_15_58 AM (3).png": ("gas", 3, 5),
    "ChatGPT Image Aug 3, 2026, 04_15_58 AM (4).png": ("solar", 4, 6),
    "ChatGPT Image Aug 3, 2026, 04_15_59 AM (5).png": ("wind", 4, 5),
    "ChatGPT Image Aug 3, 2026, 04_15_59 AM (6).png": ("hydro", 4, 5),
    "ChatGPT Image Aug 3, 2026, 04_15_59 AM (7).png": ("coal", 4, 5),
}


def box_blur(a, r):
    """Fast box blur (radius r) via integral image; keeps channel dim if 3D."""
    if a.ndim == 2:
        a = a[:, :, None]
        squeeze = True
    else:
        squeeze = False
    H, Wd, C = a.shape
    pad = np.pad(a, ((r + 1, r), (r + 1, r), (0, 0)), mode="edge")
    integ = pad.cumsum(0).cumsum(1)
    ys = np.arange(H) + 2 * r + 1
    xs = np.arange(Wd) + 2 * r + 1
    y0, x0 = np.arange(H), np.arange(Wd)
    S = (integ[ys][:, xs] - integ[y0][:, xs]
         - integ[ys][:, x0] + integ[y0][:, x0])
    area = (2 * r + 1) ** 2
    out = S / area
    return out[:, :, 0] if squeeze else out


def remove_bg(cell):
    """cell: HxWx3 float -> HxWx4 uint8. Reconstruct the smooth background
    (gradient + centre glow) by blurring the cell with detailed sprite pixels
    masked out, then key pixels that match it."""
    h, w, _ = cell.shape
    luma = cell.mean(2)
    var = box_blur(luma ** 2, 3) - box_blur(luma, 3) ** 2
    std = np.sqrt(np.clip(var, 0, None))            # local detail
    content0 = std > 5.5                            # textured sprite body/edges
    dil = box_blur(content0.astype(np.float32), 5) > 0.05   # grow the mask
    bgmask = (~dil).astype(np.float32)
    R = max(24, min(h, w) // 3)                     # big blur to fill under sprite
    num = box_blur(cell * bgmask[:, :, None], R)
    den = np.clip(box_blur(bgmask, R), 1e-3, None)[:, :, None]
    bg = num / den                                  # smooth bg incl. glow
    dist = np.sqrt(((cell - bg) ** 2).sum(2))
    t0, t1 = 11.0, 30.0
    alpha = np.clip((dist - t0) / (t1 - t0), 0, 1)
    alpha = np.maximum(alpha, (std > 8.0).astype(np.float32))   # keep crisp detail
    alpha = box_blur(alpha, 2)                                  # despeckle
    alpha = np.clip((alpha - 0.52) / 0.30, 0, 1)                # cut faint halo
    out = np.dstack([cell, alpha * 255]).astype(np.uint8)
    return out


def trim(rgba, pad=3):
    a = rgba[:, :, 3]
    ys, xs = np.where(a > 24)
    if len(xs) == 0:
        return None
    y0, y1 = max(0, ys.min() - pad), min(rgba.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(rgba.shape[1], xs.max() + pad + 1)
    return rgba[y0:y1, x0:x1]


def main():
    manifest = {}
    contact_items = []
    for fname, (tech, rows, cols) in SHEETS.items():
        img = np.asarray(Image.open(SRC / fname).convert("RGB")).astype(np.float32)
        H, W, _ = img.shape
        ch, cw = H / rows, W / cols
        techdir = OUT / tech
        techdir.mkdir(parents=True, exist_ok=True)
        # pass 1: extract every cell
        raw = []
        # nuclear sheet has large baked frame numbers; others have little/none
        numstrip = int((0.17 if tech == "nuclear" else 0.03) * ch)
        for r in range(rows):
            for c in range(cols):
                y0, y1 = int(r * ch), int((r + 1) * ch) - numstrip
                x0, x1 = int(c * cw), int((c + 1) * cw)
                rgba = trim(remove_bg(img[y0:y1, x0:x1]))
                if rgba is not None:
                    raw.append(rgba)
        # pass 2: drop broken/near-empty extractions (opaque area far below median)
        areas = [int((r[:, :, 3] > 40).sum()) for r in raw]
        med = float(np.median(areas)) if areas else 0.0
        frames = []
        for rgba, area in zip(raw, areas):
            if area < 0.45 * med:
                continue
            fn = f"f{len(frames):02d}.png"
            Image.fromarray(rgba).save(techdir / fn)
            frames.append(fn)
        manifest[tech] = {"frames": frames, "count": len(frames)}
        print(f"{tech}: {len(frames)} frames (kept of {len(raw)})")
        contact_items.append((tech, techdir, frames))

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # contact sheet for eyeball verification (first, mid, last frame per tech)
    from PIL import Image as I
    cellw, cellh = 260, 260
    board = I.new("RGBA", (cellw * 3, cellh * len(contact_items)), (30, 32, 38, 255))
    for row, (tech, d, frames) in enumerate(contact_items):
        picks = [frames[0], frames[len(frames) // 2], frames[-1]] if frames else []
        for col, fn in enumerate(picks):
            fr = I.open(d / fn).convert("RGBA")
            fr.thumbnail((cellw - 16, cellh - 16))
            board.alpha_composite(fr, (col * cellw + 8, row * cellh + 8))
    board.convert("RGB").save(OUT / "_contact.png")
    print("wrote contact sheet", OUT / "_contact.png")


if __name__ == "__main__":
    main()
