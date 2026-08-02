# Urban Grid Visual Rebuild

## Context

The current isometric scene still reads as a small town in a rural landscape:
power plants sit far from the city, transmission lines cross fields and woods,
and most zoomed-out space is farmland, grass, and scattered trees. Recent
changes made plants larger and reduced overscan, but they tuned the old
countryside composition instead of replacing it.

The new target is a full visual rebuild. The game should look like an actual
city grid with utility infrastructure on the city edge, not a town surrounded
by forest. Greenery should be deliberate urban detail, not filler.

Additional approved reference/source assets:

- `C:/Users/sycho/Downloads/municipal buildings.png`
- `C:/Users/sycho/Downloads/hjm-iso-houses.png`
- `C:/Users/sycho/Downloads/spr_road_2_strip29.png`
- `C:/Users/sycho/Downloads/spr_roads_1_strip15.png`
- `C:/Users/sycho/Downloads/gui.png`

Existing approved source sheets remain available:

- `C:/Users/sycho/Downloads/1x1x1.png`
- `C:/Users/sycho/Downloads/1x1x2.png`
- `C:/Users/sycho/Downloads/2x2x2.png`
- `C:/Users/sycho/Downloads/citycenters.png`
- `C:/Users/sycho/Downloads/buildings.png`

## Goals

1. Rebuild the city view around a real urban road grid instead of a countryside
   tile field.
2. Place generators on the city edge, surrounded by industrial, municipal, and
   utility districts rather than forests or open farms.
3. Make every visible block feel somewhat unique through varied building
   sprites, civic anchors, parking, sidewalks, service yards, small plazas,
   medians, and block-scale composition.
4. Use the uploaded road strips for the visual road network wherever practical,
   so the grid reads as roads first and terrain second.
5. Keep greenery intentional and sparse: street trees, small parks, school
   grounds, cemetery/graveyard, medians, and river edges.
6. Avoid solving the visual scale problem by overpopulating the map with too
   many live building sprites.
7. Preserve congestion, transmission, pricing, scoring, source physics, demand,
   and source-control behavior.

## Non-Goals

- No changes to the power simulation, congestion math, pricing, scoring, source
  ramping, line capacity, or demand curves.
- No rural biome polish. Forest, farmland, and grass filler should be removed
  from the primary gameplay composition.
- No visual approach that requires thousands of individual buildings or trees to
  make the city look full.
- No fully dynamic road simulation. Roads are visual/gameplay structure, not a
  new traffic-management system.
- No git operations for this work.

## Design Direction

Replace the terrain-first renderer with an urban-block renderer.

The world should be generated as a grid of city blocks. Roads are laid first,
then each block receives a deterministic block archetype. The player should see
a coherent city pattern at 1x: long streets, intersections, repeated block
rhythms, dense core blocks, civic landmarks, utility campuses, and industrial
edge districts.

The power plants remain at the city edge to keep the UI easier to read, but the
edge is urban. A nuclear plant can sit beyond a belt road with substations and
service yards; gas and peaker plants can sit in industrial blocks; wind and
solar can sit on the outer utility campus or brownfield parcels; hydro can sit
on an engineered river/canal edge. None should feel dropped into wilderness.

## Urban Layout

### Districts

The renderer should create several district bands:

- **Civic/commercial core:** city center sprites, municipal buildings,
  midrises, shops, plazas, and denser roads.
- **Mixed-use neighborhoods:** apartments, row houses, small shops, parking,
  alleys, and local roads.
- **Municipal anchors:** police, hospital, fire station, school, clinic,
  cemetery, storage/incinerator-style utility buildings where available.
- **Industrial edge:** warehouses, utility lots, substations, rail/service
  corridors, gas/coal/peaker/solar/wind campuses.
- **Waterfront/river utility edge:** hydro infrastructure, canal walls, service
  roads, bridges, and adjacent urban blocks.

### Roads

Roads become the visual skeleton. Use the provided road strip assets to build:

- orthogonal isometric streets,
- T and cross intersections,
- curves only where needed for ramps/service roads,
- medians and lane markings,
- block-edge roads around generator campuses.

The road grid should be visible at every zoom. Transmission and distribution
routes should follow roads, service corridors, substations, and utility rights
of way instead of cutting arbitrarily through open grass.

### Blocks

Each block should be a composed unit, not a single random tile. A block may
contain:

- 1-4 building sprites selected from compatible families,
- sidewalks or paved lots,
- parked cars or service details,
- small trees or planters,
- civic structures when assigned,
- yard/parking/roof variety,
- optional small utility equipment.

Blocks should vary deterministically by position and district. Two adjacent
blocks should rarely have the same exact composition.

## Asset Strategy

Use a new or expanded slicer to curate:

- road tiles from `spr_road_2_strip29.png` and `spr_roads_1_strip15.png`,
- municipal/civic buildings from `municipal buildings.png`,
- additional residential/commercial references or usable sprites from
  `hjm-iso-houses.png`,
- existing city/building/power sprites from the previous sheets,
- optional GUI sheet pieces only if they help with icons or overlays.

The asset manifest should grow from plant/building entries into semantic
families:

- `roads`
- `blocks`
- `buildings`
- `municipal`
- `plants`
- `utility`
- `details`

Each manifest entry should include draw metadata: file, base point, footprint,
district tags, approximate weight, and optional visual center.

## Performance Model

The rebuild must make the city look full without increasing live render cost.

Rules:

- Bake full block surfaces into static day/night layers.
- Keep live animation limited to plant effects, traffic accents, flow pulses,
  outage lighting, and warnings.
- Prefer composed block sprites/surfaces over thousands of individual trees or
  houses.
- Cap freeplay visible building/detail counts with tests.
- Remove broad countryside tile generation from the primary viewport.
- Use deterministic asset selection so cache reuse and test captures stay
  stable.

Target budgets:

- The visible 1x scene should be mostly urban/grid/campus content.
- Freeplay should stay under a bounded building/detail count chosen from
  profiling the current renderer.
- Rural filler tiles should not dominate the baked tile count.
- Capture generation should not regress materially versus the current local
  capture harness.

## Required Visual Changes

1. Remove forest/farm/grass filler as the default outside-city material.
2. Replace it with urban block pavement, roads, lots, sidewalks, and industrial
   surfaces.
3. Increase building variety by using more sliced sprites and block
   archetypes.
4. Treat parks/trees as designed city elements, not background noise.
5. Make roads visibly continuous and grid-like.
6. Move power plants into city-edge utility districts.
7. Keep plant controls attached to the relevant generator visual center.
8. Keep warning overlays as subtle edge vignettes, not full-screen washes.

## Testing

Add or update tests for:

- road manifest loading and alpha bounds,
- road-grid continuity,
- block variety at fixed seed,
- civic/municipal building placement,
- low greenery ratio in the zoomed-out viewport,
- utility campus context around each generator,
- capped block/building/detail counts,
- plant marker target alignment after the rebuild,
- transmission route starts/ends still tied to switchyard/substation anchors,
- capture harness completion.

Existing congestion, pricing, grid-flow, and source-behavior tests must still
pass unchanged.

## Acceptance Criteria

The rebuild is acceptable when:

1. A 1x screenshot no longer reads as a small town in a forest.
2. The red-marked style of empty greenery/farmland is gone from the main
   gameplay composition.
3. The city reads as a real grid: roads, blocks, intersections, civic anchors,
   utility campuses, and dense urban context.
4. Every block has visible variation without relying on excessive sprite
   counts.
5. Plants are city-edge infrastructure, not remote rural landmarks.
6. Zooming in does not lag from overpopulation.
7. The current congestion/transmission system continues to pass tests.
8. Captures show the new look clearly at 1x, 2x, and 4x.
