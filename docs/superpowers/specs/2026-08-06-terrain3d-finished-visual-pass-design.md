# Terrain3D Finished Visual Pass Design

## Goal

Make the default Terrain3D presentation look like a finished game board instead of a technical demo: visible real kit roads, dense downtown variety, and terrain that uses the new kit catalog with deterministic variation and elevation.
The populated area should dominate the normal playfield; nature is a smaller surrounding buffer, and the metro footprint must not be an arbitrary circle.

## Root Cause

The full `newassets/terrain/gltf` kit is baked, but the live renderer only chooses a small active set of terrain and road meshes. `build_instances()` places every tile at `y=0`, so the older 2D elevation richness disappears once Terrain3D suppresses covered 2D terrain. Downtown also compresses many source building slugs into a few repeated runtime buckets.

## Design

Terrain3D should keep loading from the baked kit manifest, but the active runtime mesh set should expand from a few base meshes into deterministic variants:

- terrain variants for forest, dirt/farm, water, trees, and mountains;
- road variants for straight, curve, tee, and cross meshes;
- distinct downtown building variants mapped from existing dense-downtown slugs, with the mature dense-downtown sprite layer allowed to draw over the 3D layer for clear building variety at gameplay zoom;
- elevation-aware placement for mountain tiles and subtle terrain undulation for non-road terrain.
- a larger non-circular dense metro footprint with slight edge variation, replacing the old circular downtown mask.

The renderer should remain efficient: it should not instantiate all 373 GL meshes at launch. It should load a richer semantic active set and select variants per tile using stable tile coordinates.

## Quality Gates

Automated tests must catch:

- active kit source count dropping back to demo scale;
- all terrain instances being flat at `y=0`;
- dense downtown rendering with too few building buckets or suppressed sprite overlay variety;
- regressions that shrink the populated area back into a small circular town surrounded by too much nature;
- road-orientation tests checking the active kit road assets, not stale legacy roads.

Visual QC must include a fresh capture smoke and spot checks of normal gameplay, night, snow, and overload frames.
