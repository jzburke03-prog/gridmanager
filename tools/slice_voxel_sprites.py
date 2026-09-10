"""Slice the 'generating and town' voxel sprite strips into clean static sprites.

Each PNG is a horizontal strip of 4 isometric rotations of one voxel asset on a
pure-black background. We split into 4 frames, key out the black background
(interior dark voxels are kept -- only near-black is removed), trim to content,
and save each rotation. A manifest records them. Animation is out of scope for
now (static one-rotation use); all 4 rotations are kept so the caller can pick a
facing later.
"""
import json
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "newassets" / "generating and town"
OUT = ROOT / "energy_grid_game" / "assets" / "voxel"

# filename (without .png) -> (category, slug)
ASSETS = {
    "Nuclear power plant": ("generation", "nuclear"),
    "Nuclear fusion power plant": ("generation", "fusion"),
    "Hydro power plant": ("generation", "hydro"),
    "Hydro power plant v2": ("generation", "hydro_v2"),
    "Solar Power Station": ("generation", "solar"),
    "Thermal power plant": ("generation", "thermal"),
    "Geothermal Power Station": ("generation", "geothermal"),
    "Tidal power plant": ("generation", "tidal"),
    "Cogeneration Plant": ("generation", "cogeneration"),
    "Apartment": ("town", "apartment"),
    "Department store": ("town", "department_store"),
    "Old mall": ("town", "mall"),
    "School": ("town", "school"),
    "House": ("town", "house"),
    "Small Market": ("town", "market"),
    "Playground": ("town", "playground"),
    "Floor tile 1": ("tiles", "floor1"),
    "Floor tile 2": ("tiles", "floor2"),
}
ROTS = 4


def key_black(frame):
    """frame HxWx3 -> HxWx4 with the pure-black background removed."""
    m = frame.max(2).astype(np.float32)
    alpha = np.clip((m - 10.0) / 18.0, 0, 1)          # ramp just above pure black
    return np.dstack([frame, alpha * 255]).astype(np.uint8)


def trim(rgba, pad=2):
    a = rgba[:, :, 3]
    ys, xs = np.where(a > 30)
    if len(xs) == 0:
        return None
    y0, y1 = max(0, ys.min() - pad), min(rgba.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(rgba.shape[1], xs.max() + pad + 1)
    return rgba[y0:y1, x0:x1]


def main():
    manifest = {}
    for fname, (cat, slug) in ASSETS.items():
        path = SRC / f"{fname}.png"
        if not path.exists():
            print("MISSING", fname); continue
        img = np.asarray(Image.open(path).convert("RGB"))
        H, W, _ = img.shape
        fw = W // ROTS
        d = OUT / cat
        d.mkdir(parents=True, exist_ok=True)
        rots = []
        for r in range(ROTS):
            cell = img[:, r * fw:(r + 1) * fw]
            rgba = trim(key_black(cell))
            if rgba is None:
                continue
            fn = f"{slug}_r{r}.png"
            Image.fromarray(rgba).save(d / fn)
            rots.append({"file": f"{cat}/{fn}", "w": int(rgba.shape[1]), "h": int(rgba.shape[0])})
        manifest[slug] = {"category": cat, "rotations": rots}
        print(f"{slug:16s} {len(rots)} rots, frame ~{fw}px")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # contact board: rotation 0 of each asset
    board_items = [(slug, OUT / info["rotations"][0]["file"])
                   for slug, info in manifest.items() if info["rotations"]]
    cols = 5
    cw, chh = 300, 300
    rows = (len(board_items) + cols - 1) // cols
    from PIL import ImageDraw
    board = Image.new("RGBA", (cols * cw, rows * chh), (34, 38, 46, 255))
    dr = ImageDraw.Draw(board)
    for i, (slug, p) in enumerate(board_items):
        im = Image.open(p).convert("RGBA")
        im.thumbnail((cw - 20, chh - 36))
        x = (i % cols) * cw + (cw - im.width) // 2
        y = (i // cols) * chh + (chh - 30 - im.height) // 2 + 6
        board.alpha_composite(im, (x, max(y, (i // cols) * chh)))
        dr.text(((i % cols) * cw + 6, (i // cols) * chh + chh - 20), slug, fill=(230, 234, 240))
    board.convert("RGB").save(OUT / "_library.png")
    print("wrote library board", OUT / "_library.png")


if __name__ == "__main__":
    main()
