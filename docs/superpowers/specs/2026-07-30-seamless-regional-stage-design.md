# Seamless Regional Stage and Zoom-Aware Art Design

**Date:** 2026-07-30

**Status:** Approved for implementation planning

## Objective

Replace the finite city rectangle floating over the time/weather gradient with a
single continuous isometric region. At 1x zoom, terrain must cover the entire
screen behind the floating HUD and reveal countryside around the city. At higher
zoom levels, the same region must reveal progressively richer city, vehicle,
plant, transmission, and weather detail.

## Accepted Direction

Use a finite but oversized seamless regional stage. The camera is clamped so
the region's outer boundary is never visible at any supported window size,
aspect ratio, or zoom level. This retains deterministic layout and baked-layer
performance without the complexity of infinite procedural terrain.

The supplied reference images establish the desired clarity and richness, not
assets to copy. All production art should be original and share one coherent
2:1 isometric projection, palette, light direction, and pixel density.

## Scene Composition

The regional stage owns the full screen, including the area behind the
screen-space HUD. It contains:

- city districts and roads;
- farms, woodland, parks, water, and open terrain;
- power plant campuses and their service roads;
- switchyards, substations, transformers, and transmission corridors;
- vehicles and other live world animation;
- time-of-day lighting and weather response.

The world is sized from the minimum 1x zoom, not the default 2x zoom. It also
includes an overscan margin outside the legal camera centers. The renderer must
never rely on a separate background to conceal an undersized world.

The region should have a readable composition rather than uniform filler:

- the city core sits near the visual center;
- residential, commercial, industrial, and park districts have distinct forms;
- major roads connect the city to plant campuses and the regional edge;
- hydro occupies a water boundary or river corridor;
- wind uses open or elevated terrain;
- solar uses a broad, ordered field;
- thermal plants occupy larger industrial campuses outside dense districts;
- transmission corridors reserve clear paths between generation and demand.

## Time and Weather Integration

The current full-frame sky gradient no longer draws behind the world. Time and
weather instead modify the regional stage itself.

Time of day controls:

- terrain, roof, road, water, and vegetation color response;
- shadow strength and overall contrast;
- vehicle headlights and building/window illumination;
- plant work lights and substation lighting;
- the color and brightness of animated grid-flow markers.

Weather controls:

- moving cloud shadows over world surfaces;
- rain streaks plus darker/wetter roads and roofs;
- restrained puddle and reflection highlights at close zoom;
- snow particles plus accumulation tints on roofs, fields, and vegetation;
- ice-storm surface tint and wind-slanted precipitation;
- wind direction for trees, turbine rotors, and particles;
- heat-wave warming and subtle localized shimmer.

Screen-space particles are allowed for performance, but terrain response and
world-space cloud shadows must make the weather feel embedded in the scene.
Weather overlays must be clipped to the playable world and must not reduce HUD
or control-card readability.

The sun and moon are implied by color and lighting direction. They are not
drawn behind an isometric ground plane.

## Zoom and Level of Detail

The three supported camera zooms are also explicit art-detail levels. They use
one semantic layout and additive cached detail layers rather than three
independent city generators.

### 1x: Regional Overview

- Simplified building masses and roof silhouettes identify districts.
- Minor roads, windows, fences, parked cars, and small plant equipment vanish.
- Traffic becomes sparse, readable movement on major roads.
- Major terrain parcels, water, highways, transmission corridors, and plant
  silhouettes carry the composition.
- Substations remain visible; local transformers collapse to simple markers.
- Plant controls remain reachable and are de-conflicted from other overlays.

### 2x: Primary Gameplay

- Building types show facade divisions, roofs, selected windows, and storefronts.
- Roads show lanes, intersections, parking areas, and selected sidewalks.
- Cars, vans, buses, and trucks have recognizable bodies and direction.
- Plant campuses show their principal structures and equipment.
- Transmission towers, conductors, substations, and distribution branches are
  clearly readable without dominating the map.

### 4x: Inspection

- Vehicles gain cabs, wheels, windows, lights, cargo, and stronger shadows.
- Buildings gain entrances, signs, vents, rooftop equipment, balconies, and
  additional illuminated windows.
- Roads gain crosswalks, turn markings, curbs, signals, parked vehicles, and
  occasional restrained pedestrian detail.
- Plant campuses gain fences, pipes, transformers, cooling equipment, service
  roads, storage, and small live machinery.
- Weather gains local splashes, snow caps, wet highlights, and close cloud-shadow
  detail.
- Electrical equipment gains insulators, crossarms, busbars, cabinets, coils,
  service pads, and fence detail.

LOD transitions are discrete at the existing 1x, 2x, and 4x zoom values. Camera
motion does not regenerate the region. Static layers are baked or cached, while
vehicles, grid flow, plant animation, weather, and emergencies remain dynamic.

## City and Vehicle Art Direction

The city should read as a functioning place, not a repeated field of generic
blocks. Layout and art should distinguish:

- downtown towers and mid-rise blocks;
- mixed-use commercial streets;
- residential neighborhoods;
- industrial and warehouse districts;
- parks and civic/open space;
- parking, local roads, arterials, and regional connectors.

Building variation comes from a small reusable set of footprints, roof types,
heights, materials, and detail overlays. Variation must remain deterministic.

Traffic uses a concise original sprite family: car, van, bus, box truck, and
service vehicle. The same vehicle identity persists across zoom levels, with
more detail revealed at higher zoom rather than an unrelated sprite swap.

## Power Plant Campuses

Each source receives a distinctive campus and silhouette:

- **Nuclear:** containment dome, cooling towers, auxiliary buildings, pools,
  security perimeter, and switchyard.
- **Coal:** boiler/turbine building, coal piles, conveyors, stack, cooling
  equipment, delivery area, and switchyard.
- **Gas combined cycle:** turbine halls, heat-recovery units, stacks, tanks,
  piping, and switchyard.
- **Gas peaker:** compact modular turbine packages and fuel infrastructure.
- **Solar:** ordered panel rows, inverter buildings, service lanes, and perimeter
  planting.
- **Wind:** multiple turbines, service tracks, local transformer equipment, and
  animated rotors.
- **Hydro:** reservoir edge, dam face, spillway, powerhouse, and transmission
  connection.

Plant animation remains restrained and operationally meaningful where possible:
rotor speed, exhaust, cooling activity, and work lights follow actual output.

## Transmission and Distribution

The visible delivery chain is:

**plant -> plant switchyard -> high-voltage transmission -> regional substation
-> neighborhood transformer -> homes and businesses**

Each plant campus has a fenced switchyard containing transformers, breakers,
busbars, insulators, and gantries. In this phase, switchyards are visual only:
they add no controls, costs, failures, capacity, simulation state, or click
targets. Flow paths may pass through their visual anchor without making them a
gameplay node.

High-voltage routes use deliberate corridors and avoid arbitrary crossings of
buildings and water. Regional substations branch power into street-aligned or
utility-corridor distribution paths. Smaller transformers serve deterministic
clusters of residential, commercial, and industrial buildings.

Electricity is represented by restrained blue flowing markers:

- plant-to-substation marker rate and density follow actual source output;
- an offline plant leaves its physical line visible but emits no markers;
- downstream flow follows delivered/served power rather than requested output;
- undersupply stops flow on selected feeder branches and darkens their associated
  building clusters;
- oversupply increases flow intensity and can support existing stress effects,
  but must never create rapid full-screen flashing;
- arrival pulses at substations and transformers make branching legible.

These markers are an intuitive visualization of energy delivery, not a literal
simulation of electron drift velocity.

## UI and Interaction

Demand chart, homes-without-power readout, HUD, speed controls, tutorial callouts,
and plant controls remain screen-space UI. The stage renderer owns no gameplay
input other than camera pan/zoom and plant-control anchoring.

The old opaque top band is removed. Its content is regrouped into three rounded,
semi-translucent HUD islands floating over the live region:

- **Left operations:** clock, date, season, temperature, speed, zoom, sound, and
  the active-event banner.
- **Center grid status:** supply/demand percentage, balance state, MW totals,
  grid price/cost, and critical grid warning.
- **Right score:** score, score trend, personal best, and total spend.

The panels use one restrained dark-glass treatment with a thin low-contrast
edge and small corner radius. Their opacity must preserve text contrast at noon
and in snow without turning them into a visually continuous bar. Landscape
remains visible between and behind the islands. The three panels use one compact
shared height and content-sized widths, forming a horizontally centered group
with equal 24px internal gaps and equal outer breathing room. Event and warning
banners may sit directly below their owning island, but must not recreate a
full-width HUD horizon.

Plant controls anchor to the actual top-center of their campus artwork rather
than to an abstract site origin. This keeps the solar control centered above its
asymmetric panel field and prevents controls from covering machinery. At 1x,
the complete fleet overview remains accessible. At 2x and 4x, a plant control is
shown only when the visual center of that campus is comfortably inside the
camera view; off-screen controls and their edge-spanning leader lines disappear.
At 4x, the solar control uses only the clean vertically centered slot above its
wide field; if that slot is blocked by the HUD, the control stays hidden until
the camera provides it. Controls continue to avoid one another plus the chart
and homes readout.

## Performance Strategy

- Generate the semantic layout only on resize, population change, or fleet change.
- Keep terrain and shared structures in reusable baked layers.
- Add cached 2x gameplay-detail and 4x inspection-detail layers selected by zoom.
- Cull all dynamic objects against the camera's visible world rectangle.
- Reuse procedural sprite caches for repeated buildings, vehicles, transformers,
  towers, trees, and equipment.
- Do not allocate full-world temporary surfaces during steady-state drawing.
- Preserve the existing slow, low-contrast severity animation constraints.

The target is a steady 60 FPS at 1400x900 on the existing headless benchmark,
with no material regression from the current approximately 10 ms/frame 4x
render measurement.

## Acceptance Criteria

- No background or opaque top band is visible at 1x, 2x, or 4x; the regional
  landscape extends behind all three HUD islands to the top edge.
- No world boundary is visible after any legal pan at supported window sizes.
- 1x reveals more countryside rather than shrinking the world into a rectangle.
- Each zoom level visibly changes information density, not only pixel size.
- Time and weather visibly affect world materials and animation.
- Every active plant has an identifiable campus and switchyard.
- Blue flow is traceable from active plants through substations and transformers
  toward homes and businesses.
- Offline sources emit no flow; undersupply visibly de-energizes downstream
  branches and associated building clusters.
- Switchyards remain aesthetic-only and do not alter simulation behavior.
- At 1x all plant controls remain accessible; at 2x/4x only visibly framed
  campuses expose controls, and those controls sit above the artwork.
- Asymmetric plant art, especially the solar field, is never clipped by a
  guessed site radius and its control is centered over its true visual bounds.
- Automated model tests, visual captures, and the steady-state render benchmark
  pass before implementation is considered complete.

## Non-Goals

- Infinite or streaming procedural terrain.
- User-built transmission routes.
- Switchyard control, capacity, economics, failure, or maintenance simulation.
- A full electrical load-flow or electron-physics simulation.
- Copying or tracing the supplied stock/reference artwork.
- Adding new source types, economic rules, or demand mechanics.
