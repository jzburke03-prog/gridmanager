# Power-flow accuracy (sub-project A of 3)

## Context

Players report the animated "electron" flow along transmission corridors looks
random and doesn't track the drawn wires. Investigation (rendering and
inspecting a close-up frame) confirmed a real geometry bug: `Flow` particles
travel the raw, unelevated routing polyline, while the drawn conductors are
rendered offset ±6px and raised to crossarm height (`y-16`) as a double-circuit
bundle. The two were never the same geometry — particles visibly float off the
wire.

Separately, the player asked for particle **speed** to vary "accurately" by
technology. Researched and confirmed real electron drift velocity in an AC line
is effectively zero (electrons oscillate, they don't travel), and the thing
that does propagate — the electromagnetic signal — moves at ~50–90% light speed
on transmission and distribution lines alike, indistinguishable to the eye
([Physics Forums](https://www.physicsforums.com/threads/propagation-speed-and-lc-model-of-transmission-line.1055609/),
[All About Circuits](https://forum.allaboutcircuits.com/threads/drift-velocity-and-propagation-velocity.75363/)).
Literal physical speed cannot be the "accurate" signal here — it would be
instantaneous. The grounded, honest signal is each plant's **real ramp-rate
responsiveness**, values already researched and present in the codebase (every
`sources/*.py` file declares `ramp_up_latency`/`ramp_down_latency` in seconds),
and it teaches something the game's own tutorial dialogue already states
("gas ramps in seconds, nuclear and coal take their time").

This is sub-project A of three approved in sequence (A → B → C): A = power-flow
accuracy (this spec), B = congestion-as-collision, C = city layout + art
overhaul. B and C are out of scope here.

## Goals

1. Electrons travel the **exact drawn conductor geometry** — both parallel
   wires of a double-circuit bundle, at every tower span, terminating exactly
   at the substation (triggering its arrival flash for real).
2. Pulse **rate** (particles/sec) scales with the plant's actual output
   (`actual_pct`) — already implemented, needs verification + a locking test
   now that the geometry is fixed and testable end to end.
3. Pulse **speed** (px/sec) is derived from the plant's real
   `ramp_up_latency`, log-scaled across the fleet's actual range, so a
   fast-responding plant (peaker, gas) visibly darts and a slow one (nuclear,
   coal) visibly crawls.
4. The full real delivery chain is represented distinctly end to end:
   **plant → switchyard (step-up) → [individual electrons, both conductors] →
   transmission → substation (step-down) → [pulsing glow, no particles] →
   distribution feeder → neighborhood transformer → [pulsing glow] → service
   line → house.**
5. Distribution/service pulsing must respect the existing accessibility rule
   (`iso_city.py` module docstring): smooth, low-contrast, capped well under
   3Hz, and explicitly must NOT read as one large-area synchronized flash.

## Non-goals

- No change to congestion math, scoring, or pricing (`game_state.py`).
- No change to the hot-overload color lerp on transmission (`overload=`
  parameter on `Flow.update_and_draw`) — orthogonal to this fix.
- No change to city layout, building density, or art style (sub-project C).
- No literal particle-collision physics — that's sub-project B's subject, and
  even there it will very likely reuse the existing MW-threshold congestion
  math rather than simulate true collisions (to be decided when B is
  brainstormed).

## Design

### 1. Geometry fix — electrons on the real conductor lines

Currently (`ui/iso_city.py`, `_bake`): the drawn conductors are two `_span()`
calls per inter-tower segment, offset `arm in (-6, 6)` from each tower's
`(x, y-16)`. The `Flow` objects backing the animation are built from
`self._routes`' raw `path` (the 2–5 point `street_route` output, at ground
level, no offset). Fix: build the tower-height, per-conductor point sequence
once (the same sequence `_span` already iterates for drawing) and hand THAT to
`Flow`, not the raw route. Concretely: after computing `towers` (the evenly
spaced tower positions along a corridor — already done in the bake loop),
construct two point lists — `[(tx + arm, ty - 16) for tx, ty in towers]` for
`arm in (-6, 6)` — and build one `Flow` per conductor from each. Both
conductors' `Flow`s share the same underlying output/color/overload inputs
(same plant), just offset visually.

`_route_transmission`'s substation endpoint must also resolve to this same
elevated/offset geometry so the arrival flash lands where the conductor
visually terminates, not at the old ground-level substation anchor point.

### 2. Remove the truncation (`ELECTRON_REACH`)

Superseded by the destination-locking requirement: electrons now travel the
full corridor and must arrive at the substation. Remove `ELECTRON_REACH`,
its use in `_bake`, and the `_truncate_path` helper + its test
(`test_truncate_path_stops_short_of_the_end`) — once unused, per this
project's established YAGNI practice (the same helper's predecessor,
`distribution_level`, was already removed for the same reason).

### 3. Speed = ramp responsiveness

New `Flow.update_and_draw` behavior: replace the flat
`step = (60 + output*90) / total` with a per-Flow **fixed** px/s speed set at
construction time (each corridor's plant doesn't change its ramp rate at
runtime, so this is static, not recomputed per frame). Mapping:

```
speed_px_s = SPEED_MIN + (SPEED_MAX - SPEED_MIN) * (1 - norm_log(ramp_up_latency))
```

where `norm_log` log-normalizes `ramp_up_latency` across the fleet's real
range (0.05s generic / 1s solar / 1.5s peaker / 2s wind / 3s gas / 5s hydro /
20s coal / 45s nuclear) to 0..1, clamped. `SPEED_MIN`/`SPEED_MAX` are tuning
constants (starting guess 40–220 px/s, converged by render — nuclear should
read as a deliberate crawl, a peaker as a brisk dart, without either being
illegible). `output` no longer drives speed; it continues to modulate minor
visual weight (radius/alpha), which stays as-is.

### 4. Rate = output, verified

`rate = (0.8 + output * 7.0) * (length / REFERENCE_LEN)` is unchanged — it
already scales spawn rate with `actual_pct`. Add a test asserting spawn count
over a fixed window is monotonically non-decreasing in `output`, so this
stays true as the surrounding code changes.

### 5. Distribution + service lines: pulse, not particles

Both `_distribution_flows` (substation → neighborhood transformer) and
`_service_flows` (transformer → house) stop being backed by particle-emitting
`Flow` objects entirely (they already draw a static line + poles; that stays).
Add a lightweight per-branch pulse: a brightness/alpha oscillation drawn along
each static line segment, driven by:

- **Presence**: only pulses if the branch is actually energized (reuse the
  existing served/priority signal the illumination-ring model already
  computes — a branch feeding a dark block does not pulse, matching "dark and
  static" for unserved areas).
- **Phase**: staggered per branch, derived deterministically from the
  branch's position (e.g. `hash(branch_key) % period`), so the city does not
  blink in lockstep — a synchronized citywide flash is exactly the large-area
  strobe the accessibility rule forbids.
- **Frequency**: slow, ~0.6–1 Hz, well under the 3Hz cap, smooth sinusoidal
  easing (no hard on/off).

This replaces the deleted `distribution_level` function's intent (a
served/priority-driven downstream signal) with a visual expression suited to
"pulse the line" rather than "animate particles along it."

## What's preserved

- Congestion's hot-color lerp (`overload=` on `Flow.update_and_draw`) —
  unaffected; still applies to the transmission (electron) layer only.
- Per-source color on transmission electrons — unchanged.
- City layout, building/pole art from the prior session — unchanged (belongs
  to sub-project C).
- `line_capacity_mw`, `congestion_loss_mw`, scoring, pricing — untouched.

## Plugin usage (gamedev-claude-plugins)

Per the user's request to use the newly-added [gamedev-claude-plugins](https://github.com/sponticelli/gamedev-claude-plugins) suite. That repo prescribes no rigid pipeline — it's context-driven ("Foundation → Execution → Polish" is offered as a pattern, not a mandate) — so agents are picked here for genuine domain fit to *this* feature (particle/line animation, timing, feel), not invoked as a checklist. Three fit:

- **`technical-art:shader-architect`** — the distribution/service pulse (§5) is a lightweight visual-effect problem (oscillating brightness along a line, phase-staggered, accessibility-capped). This agent designs the pulse's technical approach (how the oscillation is parameterized and driven) before implementation, so it's engineered as a small reusable effect rather than one-off code. Engaged during planning, before the implementation task for §5 is written.
- **`juice:juice-consultant`** — game-feel is the actual subject of §3 (ramp-rate speed) and §5 (pulse rhythm): does slow-vs-fast read as intended, does the pulse feel alive rather than mechanical. Engaged as a **feel-pass review** after the render-verified implementation of §1, §3, and §5, on the running result — not as an upfront brief, since particle feel is judged by looking at it move, not by reading a spec.
- **`engineering:gameplay-coder`** ("implements game mechanics and gameplay features with proper feel and maintainability") — used as the **implementer agent type** for this plan's coding tasks (in place of a generic implementer), since its stated remit is exactly this class of work.

Not engaged, and why: `engineering:performance-detective` (particle counts here are a few dozen at most — no profiling need); `art:*`/`technical-art:pipeline-architect`/`technical-art:art-pipeline-spec` (asset-pipeline and city art belong to sub-project C, not A); `game-design:mechanics-architect` (the "speed = ramp rate" teaching rationale was already grounded via direct research and cross-checked against the game's existing tutorial dialogue — re-litigating it through another design agent would be redundant, not additive).

## Open items resolved during brainstorming

- Both conductors of a double-circuit bundle animate (not a single
  centerline) — confirmed by the user.
- Electrons travel the full plant→substation path and terminate there exactly
  — confirmed, supersedes the prior session's partial-reach design.
- Distribution pulses instead of remaining fully static — confirmed as a new
  requirement, extending (not contradicting) the prior session's "no
  distribution particles" decision.
