# UI, Plant, and Traffic Polish Design

**Date:** 2026-07-30
**Status:** Approved for implementation

## Goal

Correct the remaining legibility and geometry problems in the regional stage,
make plant controls coherent while panning and zooming, improve road traffic,
unify the top HUD, and make city damage communicate absolute oversupply
severity from 101% through 200%.

## Scope

This pass changes presentation and map interaction only. It does not change
plant capacities, prices, ramp rates, the demand simulation, difficulty loss
thresholds, or the decorative-only role of switchyards.

## Plant Controls

### Visible plants

A plant whose artwork intersects the usable viewport receives its full control
card. Full cards increase from 148 pixels to a width large enough for the
longest supported output string, including values such as `450/750 MW`, with at
least eight pixels of right padding. The dial, status, output, and price remain
directly interactive.

Cards no longer use leader lines. A small downward-pointing chevron attaches to
the lower edge of each card and points toward the visible plant. The card and
chevron share a subtle vertical bob of no more than two pixels, with a slow
period so the motion reads as a map marker rather than an alert. Layout still
avoids the HUD, demand chart, homes readout, and other plant controls.

### Off-screen plants

Every active source remains represented when its plant is outside the camera.
Instead of a full control card, it receives a compact edge tab placed on the
nearest viewport edge. The tab contains the source name, current MW output, and
a chevron aimed toward the off-screen plant's true screen-space direction.
Tabs stack along an edge with consistent spacing and avoid the HUD and inset
cards. Clicking a tab recenters the camera on that plant; the tab then becomes
the normal full control card once the plant is visible. Off-screen tabs do not
expose the dial, preventing a dense ring of miniature controls.

## Unified HUD

The three separated HUD islands become one centered translucent rounded panel.
Its overall content order stays unchanged:

1. clock, date, weather, speed, and audio;
2. balance, supply, demand, grid price, and cost rate;
3. score, score rate, best score, and total spend.

The panel uses the current compact 150-pixel height and approximately the same
total width. Two subtle vertical dividers organize the three zones without
opening gaps through which the landscape shows. The single outer rectangle is
the HUD hit-test and plant-card obstacle. Warning and event banners remain
anchored immediately below their related zone.

## Plant Geometry Corrections

### Nuclear cooling towers

Every cooling-tower rim is built from one centered bounding rectangle with an
odd pixel width. The concrete lip, inner dark opening, upper highlight, shell
profile, plume origin, and beacon all use the same integer centerline. This
removes the half-pixel rounding drift that currently makes the crest appear
offset from the body.

### Solar campus

The solar foundation is drawn first as one complete 13-by-10-tile isometric
lot with all four corners preserved. Internal gravel lanes are clipped to the
lot rather than extending or visually replacing its perimeter. Panel tables,
inverter buildings, and the switchyard are then drawn inside that footprint.
The local plant sprite bounds must include the complete lot so no rear-left or
front-left corner is cropped.

### Combined-cycle gas plant

Remove the thin yellow decorative fuel line that currently crosses the plant
pavement. The two turbine-to-recovery-to-stack trains, service buildings,
parking, tanks, and switchyard remain.

## Traffic Routing and Density

Traffic uses the existing road tiles as a connected graph. At bake time, every
road tile records its orthogonal road neighbors. A vehicle owns a short route
through that graph instead of one straight road interval. On reaching an
intersection it chooses a connected continuation, avoids an immediate U-turn
unless at a dead end, and updates its sprite orientation from the active route
segment. A small direction-dependent lane offset separates opposing traffic.
Vehicles remain hidden where foreground buildings occlude the road.

The maximum generated fleet drops substantially from 260 to a value near 100.
The number drawn each frame follows a continuous daily traffic curve:

- very low from midnight through the early morning;
- a smooth parabolic morning peak spanning 8–10 AM and centered near 9 AM;
- a lower midday baseline;
- a smooth parabolic evening peak spanning 4–6 PM and centered near 5 PM;
- a steady decline after the evening rush.

The two peaks must be visibly higher than midday and nighttime traffic. Zoom
still controls detail density, but even inspection zoom never draws the entire
generated fleet. Grid outages may damp traffic slightly without eliminating
it.

## Scaled Overcapacity Effects

City damage uses the instantaneous supply-to-demand ratio for visual severity,
separate from the existing difficulty-dependent loss mechanics. This makes the
map communicate the percentage displayed in the center HUD consistently across
difficulties.

- At or below 101%, no overload damage is shown.
- From 101% to 120%, use only a subtle warm electrical glow or tint; no fires.
- From 120% to 150%, progressively increase the tint and occasional transformer
  or switchyard arcs; no large fire outbreak.
- From 150% to 200%, progressively increase persistent fires, smoke, arcs, and
  their geographic spread.
- At 200% and above, clamp visual severity at the maximum citywide state.

All large-area pulses retain their current slow, photosensitivity-conscious
timing. Severity changes amplitude and the count of small local effects, not
the flash frequency of the whole screen.

## Implementation Boundaries

- `ui/plant_pins.py` owns full-card sizing, chevrons, edge-tab layout, drawing,
  and hit targets.
- `ui/iso_city.py` owns true plant coordinates, camera visibility, corrected
  plant artwork, the road graph, vehicle routes, traffic density, and overload
  visuals.
- `ui/hud.py` owns the unified outer panel and internal zone rectangles.
- `main.py` passes the unified HUD obstacle, dispatches edge-tab clicks, and
  recenters the camera through an `IsoCity` method.
- `test_city_model.py` exercises the pure geometry, layout, routing, traffic,
  and overload contracts.
- `tools/capture_moments.py` captures representative 1x, 2x, 4x, off-screen-tab,
  rush-hour, and overload states for visual review.

No new dependencies or raster assets are required.

## Verification

Automated checks must demonstrate that:

- the longest MW string stays inside every full card;
- visible controls use chevrons and no leader line is drawn;
- every active off-screen plant receives a non-overlapping edge tab whose
  direction points toward its plant;
- clicking an edge tab recenters the camera;
- the HUD is one continuous panel with two internal zones and no landscape gaps;
- cooling-tower rim rectangles share the shell centerline;
- the solar lot retains all four corners inside its sprite bounds;
- the gas pavement contains no yellow fuel-line artifact;
- every vehicle route consists only of adjacent road tiles, turns at valid
  intersections, and does not immediately reverse when another exit exists;
- traffic at 9 AM and 5 PM is higher than at midday and overnight, with smooth
  changes around both rush windows;
- 101% produces no fires, while fire count and geographic reach increase from
  150% to 200%; and
- the complete city-model, capacity, and instructional suites remain green.

Final visual review uses fresh captures for the five reported problem areas,
both rush hours, representative pan/zoom positions, and 101%, 150%, and 200%
oversupply.
