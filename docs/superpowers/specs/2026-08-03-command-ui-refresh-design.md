# Command UI refresh

## Context

Grid Manager already has a strong modern-retro identity: voxel/isometric city
art, chunky pixel UI assets, a dusk skyline title scene, bevelled square panels,
and monospace utility typography. The current presentation is readable, but the
game's core lesson is not clear enough at a glance. The player is balancing the
grid while managing cost, yet the top HUD splits that story across several
readouts, the homes-without-power value is a separate bottom-right overlay, and
the demand curve still reads like a plain callout rather than a game-native
instrument.

The front-end screens have a similar issue. The title, mode menu, day-complete
panel, and game-over screen all function, but their most important emotional
beats are underplayed. The revamp should preserve the current voxel-pixel DNA
while making the interface feel like an operator's dispatch console inside this
world.

## Goals

1. Make the top HUD clearly communicate the primary loop: match supply to
   demand, control spending, and keep homes powered.
2. Move "Homes Without Power" out of the bottom-right in-game box and into the
   main top HUD as a prominent status number.
3. Restyle the bottom-left demand curve as a game-native pixel utility monitor,
   not a plain callout box.
4. Elevate the title/main-menu, game-over, and day-complete screens with a
   cohesive operator-console visual language.
5. Preserve gameplay behavior, simulation math, scoring, chart data, and
   existing input semantics.
6. Keep the playfield readable and avoid covering the center or lower-middle
   city view during normal play.

## Non-goals

- No changes to demand, pricing, scoring, failure, or homes-without-power
  calculations.
- No rewrite of the renderer, menu state machine, or day-complete state machine.
- No new external UI framework or asset dependency.
- No redesign of plant pins, tutorial dialogue, city rendering, or source
  controls beyond the specific screen composition needed for the refresh.
- No broad color-theme replacement. The new UI must remain consistent with the
  existing voxel-pixel art direction.

## Approved Approach

Use an "operator console HUD refresh" rather than a full-width app dashboard.
The top of the screen remains a soft, readable scrim over the city, but the
content is organized into clearer pixel instruments:

- A central grid-balance module with the large balance percentage and
  supply-versus-demand numbers.
- A money module that makes total spend and live operating cost obvious.
- A homes-powered module that promotes homes without power to a top-level
  warning number.
- A score module that remains visible but is secondary to balance and cost.

The demand chart becomes a compact dispatch monitor with a bevelled pixel frame,
header strip, internal grid/tick styling, and the existing generation stack and
demand line. Outcome and menu screens reuse the same material language:
square-corner command panels, pixel bevels, source/status accent colors, strong
headers, and restrained state-driven motion.

## Visual Direction

The game fantasy is a grid operator managing a living voxel region from a
retro-futurist dispatch console. Materials should feel like dark enamel panels,
CRT/SCADA monitors, amber warning lamps, green power status indicators, steel
bevels, and chunky pixel hardware. Typography remains monospace and crisp.

The palette should stay close to the existing game:

- Near-black and deep navy panel bases.
- Steel-blue and muted grey borders.
- Green for balanced/safe/powered states.
- Amber/yellow for oversupply, cost, caution, stars, and next actions.
- Red for blackout, severe homes-out, and failure states.
- Source colors remain the generation-mix language.

Motion should be purposeful and low frequency: subtle glow/pulse on balance
state, warning breathing in dangerous states, and small button/selection
feedback. Avoid busy constant animation.

## In-Game HUD Design

### Layout

The top HUD keeps one centered persistent cluster over the soft scrim. The
cluster remains under roughly the current vertical footprint so the city still
owns the screen.

Left zone:

- Clock, date, season, temperature.
- Speed controls and audio indicator remain nearby.
- Active grid event banner continues below when present.

Center zone:

- Large balance percentage remains the primary number.
- Status label below it remains color-coded.
- Supply and demand appear as a paired objective readout with explicit labels:
  `SUPPLY NOW` and `DEMAND TARGET`.
- The color relationship should make clear that the player is trying to align
  the two values, not merely maximize output.

Right zone:

- Homes without power becomes a major number with a population icon and
  severity color.
- Total spent and live operating cost/grid price sit close enough to read as
  one money module.
- Score and best remain visible but visually subordinate to balance, homes, and
  money.

The bottom-right homes box is removed. `IsoCity.draw_homes_label()` should no
longer be called during the main render path. The function can remain for tests
or future use unless removal is straightforward and safe.

### Homes Severity

Reuse the current threshold behavior:

- `0` when homes out is small.
- Green when effectively all homes are powered.
- Amber when outages are meaningful but not catastrophic.
- Red when more than half the homes are out.

The promoted readout should use the actual `state.homes_without_power` and
`state.homes_total` values, with no behavior change.

### Money Clarity

When economics are enabled, show:

- `TOTAL SPENT` as the accumulated cost.
- `GRID PRICE` and hourly burn as the live operating pressure.

When economics are not enabled, preserve the instructional behavior by hiding
or soft-disabling money fields rather than introducing new tutorial text.

## Demand Monitor Design

`DemandChart` keeps the same data model:

- Existing demand profile preview for future hours.
- Recorded real demand for elapsed hours.
- Generation stack filled from history.
- Current demand marker.
- Existing source color mapping.

The visual frame changes:

- Replace the simple rounded callout look with a square-corner pixel monitor.
- Use a bevelled outer frame, darker inner screen, and top header strip.
- Add subtle gridlines or ticks inside the chart to read as a utility display.
- Keep the axis labels compact and pixel-crisp.
- Preserve time-of-day coloration, but darken/tint it so it feels embedded in
  the monitor rather than a plain panel background.

The monitor stays bottom-left and compact enough not to interfere with map
interaction.

## Main Menu And Splash Design

The title screen keeps the procedural pixel skyline, but the controls become
part of the scene:

- Title remains prominent in the sky/signal area.
- PLAY becomes a stronger dispatch-console button with pixel bevel, glow, and
  clear hover feedback.
- Events toggle becomes a compact hardware-style switch or status chip, not a
  plain rectangular text box.
- The "press any key" affordance should not compete with the PLAY button.

Mode, freeplay, scenario, and fetching screens continue using the shared dimmed
pixel backdrop, but their cards and headers should feel like the same command
console material as the updated HUD and outcome screens.

## Outcome Screens

### Game Over

The game-over overlay becomes a stronger emergency dispatch alert:

- Darkened city remains visible enough to connect failure to the world.
- Failure reason becomes a large red/amber alert banner with icon.
- Explanation, final score, best score, and controls are grouped in a clear
  command panel.
- The mentor portrait stays, but composition should frame it as an emotional
  reaction rather than a loose image beside text.
- Retry and menu instructions remain `R` and `ESC`.

### Day Complete

The day-complete panel becomes a celebratory operations report:

- Stronger header with day label, star rating, score, and spend.
- The large chart and right-side stat blocks stay, but the surrounding panel
  adopts the same pixel-console material language.
- Continue/finish button becomes a clearer call to action with matching bevel
  and hover behavior.
- Instructional day notes remain supported without colliding with stats.

## Architecture

Keep the changes small and localized:

- `energy_grid_game/ui/hud.py` for the top HUD and game-over overlay.
- `energy_grid_game/ui/demand_chart.py` for the demand monitor restyle.
- `energy_grid_game/ui/day_panel.py` for the day-complete panel restyle.
- `energy_grid_game/ui/menu.py` and possibly `energy_grid_game/ui/splash.py`
  for title/menu composition.
- `energy_grid_game/main.py` only to stop drawing the bottom-right homes box and
  adjust layout if the readout rect is no longer needed.

Shared helpers are acceptable if they reduce duplication between HUD, menu, and
outcome panels, but they should stay lightweight. Existing helpers such as
pixel panel drawing, asset loading, resource icons, and portrait loading should
be reused where possible.

## Data Flow

1. `main.py` computes the normal layout and draws the city.
2. `HUD.draw()` receives `state` and renders the promoted balance, homes,
   money, and score modules.
3. `DemandChart.draw()` receives the same chart inputs as today and renders
   them in the new monitor frame.
4. `DayCompletePanel` continues to freeze the completed state and render its
   report from that snapshot.
5. `HUD.draw_game_over()` continues to render failure from `state.game_over`
   and `state.game_over_reason`.
6. `MenuSystem` continues producing `RunConfig` values through the existing
   state machine.

## Error Handling

The refresh should not introduce new loading failure points unless it reuses
existing assets through `ui.assets`. Missing optional icons should fall back to
plain text only if there is an established local pattern; otherwise missing
asset references should fail clearly during development, matching current asset
loader behavior.

Text must fit at supported window sizes. The existing minimum window size is
1000 x 680, and the HUD should be designed against that lower bound.

## Testing And Verification

Focused checks:

- HUD homes readout displays `0`, amber, and red values correctly from state.
- `main.py` no longer draws the bottom-right homes-without-power box.
- Demand chart still draws with short history, full history, and source mixes
  including Instructional Mode's `generic` source.
- Day-complete input behavior still blocks gameplay and advances exactly once.
- Game-over still accepts `R` retry and `ESC` menu behavior through existing
  main-loop handling.

Regression checks:

- Run focused tests for HUD/day panel/chart if present.
- Run `energy_grid_game/test_city_model.py` only if touched indirectly by
  layout changes.
- Run or update visual captures with `tools/capture_moments.py` and inspect:
  title, mode, game, day complete, and game over.

## Acceptance Criteria

- A new player can tell from the top HUD that the goal is matching supply to
  demand while managing spend.
- Homes without power is a prominent top-level status and the old bottom-right
  homes box is gone.
- The demand curve feels like a stylized pixel utility monitor that belongs in
  the game.
- Main menu, game-over, and day-complete screens feel more polished and
  cohesive while preserving the current voxel-pixel aesthetic.
- The city remains readable during gameplay, with no large new center-screen
  overlays during normal play.
- Existing gameplay, scoring, pricing, demand, and failure behavior are
  unchanged.

## Risks

- The promoted top HUD could become too dense at the minimum window size.
  Mitigation: keep score secondary, use compact modules, and verify at
  1000 x 680.
- Restyling the demand chart could reduce data readability. Mitigation:
  preserve line weights, source colors, and axis labels while improving the
  frame.
- The outcome panels may become too visually heavy over the city. Mitigation:
  keep the background visible but dimmed and use strong hierarchy rather than
  more boxes.
