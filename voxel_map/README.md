# Voxel Map — GPU (pyglet) isometric renderer

A standalone voxel-pixel isometric map for the energy-grid game: the city is the
hero, the seven generating technologies sit around it, mountain ranges frame the
edges, and **season palette + time-of-day lighting are live shader uniforms
driven by the real sim clock** — one geometry upload, everything else recolours
in real time.

This is a prototype/vertical slice built to evaluate migrating the map renderer
from pygame (CPU blits, baked day/night layers) to pyglet (GPU, shader lighting,
smooth zoom). It reuses the game's own sim clock (`energy_grid_game/game_state`)
for the time of day and season.

## Run

    # from repo root, using the project venv
    .venv39/Scripts/python.exe voxel_map/voxel_map.py            # interactive window
    .venv39/Scripts/python.exe voxel_map/voxel_map.py stills OUT # render verification PNGs

### Controls (interactive)
- **scroll / + -** — zoom (GPU transform, smooth)
- **drag** — pan
- **[ ]** — scrub time of day by an hour
- **1 / 2 / 3 / 4** — force spring / summer / fall / winter
- **space** — fast-forward the clock (watch the day/night cycle)
- **c** — rejoin the live game sim clock

## How it works
- `tools/slice_sheets.py` slices the 7 sprite sheets in `../newassets/` into
  clean transparent frames under `assets/plants/<tech>/` (background removed by
  reconstructing the smooth gradient with the sprite masked out, then keying).
  Re-run it if the source sheets change.
- `voxel_map.py`:
  - **Terrain** is one batched GPU vertex list of voxel faces. Ground materials
    (grass/field/water/road/pad/rock/snow) carry a *material id*; the fragment
    shader looks their colour up in the current season's palette, so changing
    season is a uniform swap. City buildings carry a per-lot vertex colour.
  - **Mountains** rise on the edges via a noisy elevation function; peaks get a
    snow cap. Terrain fills the whole frame — no floating island.
  - **Generators** are the sliced sprite frames, drawn as depth-sorted billboards
    and animated by cycling frames (smoke / water / blades).
  - **Lighting**: `daylight(sim_hour)` → a day factor + warm dusk / cool night
    tint + sky colour, applied in the shader. Season comes from `date.month`.
    Both are read from a live `GameState` (falls back to a local clock if the
    game can't be imported).
  - A GL depth buffer sorts terrain, city, mountains and plant billboards.

## Known rough edges (prototype)
- Faint soft halos remain on a couple of the AI sprite cutouts.
- The nuclear sheet has a tiny baked frame-number that survives cropping on some
  frames (flickers past in animation).
- Ground material colour is per-material (flat) with only per-tile brightness
  jitter; a texture/noise pass would add richness.
