# frontend

UI team's workspace: the pier canvas, live dashboard and safety sheet views for the mooring assistant. The framework
and tooling are the UI team's call; nothing outside this folder depends on them.

## Goal

An interactive web app where a bridge team places a ship at a pier, picks ship class, pier and line types, and sees
the agent's recommended tug assist, line sequence, gust warnings and safety margins. The output is an approved
**Mooring Evolution Safety Sheet** and a graphical layout with the agent's rationale. This is the "Physics-Informed
Mooring & Tug Allocation Planning Agent" use case (Pier Review, Open Innovation, FLEETHACKER Norfolk 2026).

The UI is a reusable visualization shell, not a one-off mooring screen. Mooring is the first application it talks
to; the same shell should later drive other applications (for example an exercise simulator) through the same kind of
API boundary. See [Multiple applications](#multiple-applications).

It started from the drone-simulator (Cesium, React, TypeScript, Vite, Tailwind) and kept its rendering engine and
look. The drone-specific code, models and backends were removed. The demo script is in [DEMO.md](DEMO.md); the build
plan, decisions and status are in [PLAN.md](PLAN.md).

## Run it

Prerequisites: Node 20+ and [uv](https://docs.astral.sh/uv/) for the mock services.

```bash
# repo root: mock modeling (:8000) and agents (:8001)
make install && make mock

# another terminal
cd frontend/packages/web
npm install
npm run dev          # http://localhost:4000
```

The browser only talks to its own origin. Vite forwards `api/modeling/*` to the modeling service and `api/agents/*`
to the agents service (set `MODELING_PROXY_TARGET` and `AGENTS_PROXY_TARGET` in `frontend/.env` to override
`http://localhost:8000` and `:8001`). REST is under `/api/v1`, WebSockets under `/ws`. Set `VITE_MODELING_URL` or
`VITE_AGENTS_URL` to an absolute URL to bypass the proxy.

The mooring app needs no tokens: its 2D and 3D views are drawn from the berth data itself, with no imagery. The
[exercise simulator](#exercise-simulator) tab draws on Mapbox and needs a public access token.

Other scripts in `packages/web`: `npm test`, `npm run lint`, `npm run typecheck`, `npm run build`, and
`npm run types` (regenerates `src/api/*.d.ts` from `../../contract/`; commit the result when `contract/` changes).
The repo-root `app.sh` starts both services and serves the built UI on `:8888`; it is the Domino app entry point
(see [Deploying as a Domino app](#deploying-as-a-domino-app)).

## Where this fits in the repo

```text
 frontend (this folder)  ──HTTP/WS──▶  agents   (:8001)  ──HTTP──▶  modeling (:8000)
        └─────────────────────────────HTTP/WS──────────────────────▶  modeling
```

`frontend/` integrates with the other pieces only through `contract/`. Never import or read the Python code to learn
an API; read the OpenAPI specs. `contract/` holds the specs for both mooring services (`modeling.openapi.yaml` and
`agents.openapi.yaml`). It is generated from the Pydantic schemas, so never edit it by hand. If the UI needs a
contract change, it goes through the owning team's schemas and needs review from both sides. Where the contract and
[`../docs/PLAN.md`](../docs/PLAN.md) differ, the contract wins.

## Layout

```text
packages/web/src/
  shell/        Cesium renderer, 2D/3D camera, picking and dragging, layout, shared UI (status, badges,
                citations). Knows nothing about mooring.
  scene/        The neutral model (entities, links, arrows), its store, geometry helpers, the app registry.
  apps/
    mooring/    The mooring adapter: API clients, mapping to the scene, controller, panels, agent session.
    exercise/   The exercise simulator: a Mapbox 3D map, a ship simulation and scenario editor (open /?app=exercise).
    demo/       A tiny non-mooring app that exercises the shell (dev builds only; open /?app=demo).
  api/          Types generated from the contract. Do not edit.
  lib/, styles/ Small helpers and the Tailwind theme.
```

Ship shapes are generated: a hull outline sized from LOA and beam plus a rough above-deck profile per hull type
(destroyer and cruiser deckhouses, carrier and amphibious flight decks with an island). Clicking or dragging any part
acts on the ship. There are no ship 3D models in the repo.

## Multiple applications

The shell must not know about mooring. Application knowledge lives in an **adapter**, one per backend application,
and the shell only deals with the scene model.

```text
  mooring API (contract/)  ──▶  mooring adapter   ─┐
                                                    ├─▶  scene model  ──▶  shell: 2D view / 3D view / panels
  exercise-sim API (its own) ─▶  exercise adapter  ─┘
```

- `shell/` never imports from `apps/`. Apps register themselves in `main.tsx`; the user picks one.
- An app implements `AppDefinition` ([`scene/app.ts`](packages/web/src/scene/app.ts)): `start(host)` returns an
  instance with optional `Sidebar`, `Bottom`, `Banner` and `Overlay` components and an `onEdit` handler. The shell
  forwards canvas edits (such as dragging a ship) to `onEdit`; the app decides what they mean and updates the scene
  through the store.
- Apps appear as tabs in the header. An app that brings its own renderer sets `canvas: 'custom'` on its definition and
  returns a `Canvas` component; the shell then skips the Cesium canvas (and never loads Cesium for that tab). The
  exercise simulator does this because it draws on Mapbox.
- Status colors (GREEN, AMBER, RED), the backend badge and the citation chip are shell components.
- Each app owns the OpenAPI specs for its API. Where other apps' specs live is still open.
- The scene model was designed from what the shell needs to draw. It has been exercised by the mooring adapter and
  the demo app; check it against the exercise application before freezing it.

## Exercise simulator

A second tab: replay a naval exercise in 3D on a Mapbox map. Ships move across open ocean with wakes, routes,
formations and conditions you configure. There is no backend; the simulation runs in the browser.

**Mapbox token.** Mapbox GL needs a public access token (`pk.…`). Either put `VITE_MAPBOX_TOKEN=pk.…` in `frontend/.env`
(or the environment of whatever builds the app; Vite inlines it, which is fine for a public token) or paste it into the
prompt the tab shows when it has none (kept in this browser's local storage). The default **Standard** map style works
with any valid token. The **Satellite** styles also need raster-tile access, which some tokens and plans do not have;
the tab says so if Mapbox refuses.

**What you can configure** (all of it is plain JSON, so scenarios can be saved, shared and edited by hand):

- Scenario: name, length, light (dawn, day, dusk, night; on the Standard styles), and the starting view.
- Environment: wind (speed, direction it blows from) and current (speed, direction it flows toward). Current sets every
  ship over the ground; wind pushes ships downwind a little, small craft more.
- Units: ships (CVN, LHD, CG, DDG, fast attack craft, merchant), **aircraft** (fighter, helicopter), **missiles**
  (anti-ship, surface-to-air) and **mines**. Each has a side (blue, red, neutral), start position, heading, speed and an
  optional turn-rate limit. Every unit has one behavior: follow a **route** (waypoints with optional per-leg speed and,
  for aircraft, altitude; optional loop; click the map to add waypoints), keep **station** on another unit, **pursue**
  one, **circle** a point (aircraft), **strike** a unit (missiles) or **hold** (ships drift, helicopters hover, fixed-wing
  aircraft circle where they are, mines stay put).
- Launches: any unit can be launched by another at a set time (a missile fired, an aircraft launched). It appears at the
  launcher; if the launcher has been destroyed by then, the launch does not happen. **+ Add salvo** fires several
  missiles in turn.
- Damage: every ship and aircraft has hit points and every missile and mine has a damage rating, a fuze radius and a hit
  chance. Anything that does at least a unit's hit points in one hit destroys it; a ship below half strength slows to half
  speed; a destroyed ship stays where it is, dark and burning, and a destroyed aircraft is gone. Ships also shoot at
  missiles aimed at their own side (a shot kill chance, shots per missile, a reload time, a magazine and a radar-horizon
  range), which is what makes a salvo a contest. All of these are set per class and can be overridden per unit.
- Playback: play, pause, restart, scrub, 1x to 600x. Camera: fit all, follow, chase, orbit (circles the selected ship, or
  the whole group), and **Present**, which hides the panels and fills the screen with the map plus a minimal HUD (Esc
  exits). The view opens with a fly-in to the main group. View: ship size exaggeration (so ships read when zoomed
  out), wake length, names, routes, sensor ring.
- Look: the light preset (dawn, day, dusk, night) lights the sea, and at dusk and night the ships' navigation and deck
  lights glow. Dusk and night are the most dramatic; the presets use them.

Six presets ship with it: a carrier group transit, a surface contact intercept at night, a formation drill, a **missile
salvo on a carrier group**, a **minefield transit** and an **air raid with SAM defence**. The last three include red-team
setups. Use **Edit as JSON** or **Download** in the Scenario panel to save or load your own. The **Events** tab at the
bottom lists launches, hits, interceptions and losses in words (click one to jump to it) and the timeline marks them.

### Red team: how likely is it?

**Red team** in the map toolbar runs the scenario hundreds or thousands of times with random variation and measures how
often things happen. You set three things, all saved with the scenario:

- **Outcomes**: the questions to ask. A unit is hit, destroyed or falls below a strength; a side loses N units; a mine goes
  off; N missiles are shot down; two units come within some distance of each other.
- **What varies**: any of wind and current, or, per unit, speed, heading, start position, route position, launch time,
  altitude, hit points, damage, hit chance, defence kill chance and shots, or whether it is present at all. Each draws from
  a uniform, normal, triangular or listed distribution, and replaces, adds to or multiplies the scenario's value.
  Missile hits, defensive shots and mines are chances on top of that.
- **A sweep** (optional): repeat the whole batch at several values to draw a curve, for example how the chance a carrier
  is hit grows as the salvo goes from 1 to 8 missiles.

Results show each outcome's chance with a 95% interval (Wilson), a histogram of when it happens, a ranking of which
variation drives it (the correlation between each draw and the outcome, with the average value when it happens and when it
does not), and average hits, interceptions and losses per run. Runs go in the browser in short slices so the page stays
usable, with progress and a Stop button.

Every batch is reproducible: the same seed, scenario and settings give the same numbers, and every run can be **replayed
on the map** (choose a run where an outcome happened, or one where it did not) with the same random draws and the same
chance rolls. Replays are in the batch's own scenario, not yours, which is untouched; **Exit replay** goes back. Sweep
values share the same random draws run for run, so the curve is not noise.

These are chances on illustrative numbers, so the output is only as good as what you put in: the point is to see which
assumptions the answer depends on, not to predict a real engagement.

**How it works.** `apps/exercise/sim.ts` runs the whole scenario up front at a fixed step (deterministic, so scrubbing
and rewinding are free) and the map interpolates between samples. Ships are generated hull outlines with
class-specific superstructure (masts, radar domes, flight-deck markings and parked aircraft on the carriers, container
stacks on the merchant), drawn as Mapbox fill-extrusions at true size times the size slider. Hulls are stacked slices,
which gives a dark waterline band and a flared deck edge. Wakes are a fading center trail plus a V; foam around the hull
scales with speed; lights are tiny emissive pillars with a soft glow. Aircraft are drawn at their altitude with a
glow on the sea beneath them, missiles are drawn large enough to see with an exhaust glow and a faint line to their target,
and hits, interceptions and launches flash where they happen. `montecarlo.ts` draws the random variation, runs batches
and computes the statistics; `sim.ts` takes a seed for the chance rolls so any run can be repeated. Ship dimensions and handling are rounded, illustrative figures, not for operational use. Handling is simple on
purpose: speed and turn rate are limited per class, and escorts hold station with a proportional controller. Formation
turns need a slow guide turn rate (see `maxTurnRateDegPerS` in the presets), because an escort 1.5 km abeam cannot keep
up with a guide that turns on a 300 m radius.

Tests cover the simulation (including the engagements and the Monte Carlo statistics), the scenario JSON, the map view
(against a fake Mapbox) and the panels. The map itself was checked in headless Chromium with software WebGL; check it on a
real GPU before demoing.

## Contract conventions the UI follows

- Units are in field names (`_kt`, `_ft`, `_lbf`, `_deg`, ...). The UI shows Navy units by default and has a Navy /
  Metric toggle in the header (meters, kN, kW, tonnes; speeds stay in knots). All conversion is at the display edge in
  `apps/mooring/units.ts`; the API always receives Navy units and the scene model is in meters. The service-rendered
  safety sheet is always in Navy units.
- Wind direction is where it blows **from**; current is where it flows **toward**. Both degrees true. Arrows on the
  canvas show the direction of motion.
- Berth frame: standing on the pier facing the water, +y points into the water and +x runs to your right. Ship frame:
  midships origin, +x forward, +y to port. Starboard side to the pier puts the bow toward +x. All frame conversion
  lives in `scene/geometry.ts` and `apps/mooring/mapping.ts`, with tests.
- A plan that is unsafe is a `200` with `status: RED` and findings, not an error. Only `404` and `422` are errors.
- Slow endpoints may return `202` with a `job_id`; the client polls `status_url`. Agent plans stream over SSE.

## What the UI shows from the responses

- `status` (GREEN, AMBER, RED) on lines, fittings, findings and plans.
- `backend: "mock"` as a banner and badge, and `provenance.confidence` for berth data, so nobody mistakes
  placeholder numbers for real ones.
- `findings[].reference` (the NSTM 582 paragraph) next to each warning.
- `result_id`s cited in agent rationale open the stored result (`GET /results/{id}`).

## Screens

1. **Pier canvas** (centre): berth, ship, fittings, lines colored by `pct_wll`, tugs and wind/current arrows. Toggle
   2D (top-down, +x right, water up) and 3D. Drag the ship along the pier, click a ship bitt then a pier fitting to
   add a line, click anything to inspect it.
2. **Scenario panel** (left): pier, ship class, loading, side to, position, standoff, environment values, line list,
   analysis findings, recommended layouts, saved scenarios.
3. **Planning agent** (left): runs the agent, shows its steps and rationale with cited results, applies its lines and
   tugs to the canvas (with undo), shows the line sequence, takes follow-up questions.
4. **Dashboard** (bottom): live, replay and storm-ramp environment streams, the alert feed, a 24 h forecast, a
   limiting-wind chart and gust risk.
5. **Safety sheet** (overlay): the service's rendered sheet, margins, rationale, a layout image, approvals by pilot,
   first lieutenant and CO, and print.

## Known limits (mock backends)

- Only the DDG-51 class has fitting data, so other classes show a hull only and line editing is disabled.
- The mock alert stream does not escalate during a storm ramp. The UI therefore also raises warnings from the plan
  analysis and labels them as coming from the analysis, not the service.
- The mock's reported line lengths do not match the contract's geometry; the canvas draws from the contract's frames
  and the inspector shows the service's numbers.
- The meaning of `wind_rel_deg` in the wind-limit chart is not defined in the contract; the chart shows it as
  reported.

## Open decisions

- **Where other apps' API specs live.** `contract/` currently holds only the mooring specs. Options: sibling folders
  (`contract/<app>/`), or each app publishes its own spec that the frontend consumes.

## Deploying as a Domino app

The repo-root [`app.sh`](../app.sh) is the Domino app entry point. It starts the modeling and agents services on
`127.0.0.1:8000` and `:8001`, builds the UI, and serves it on `0.0.0.0:8888`. Only the UI port is exposed; the UI's
server proxies `api/modeling/*` and `api/agents/*` to the two services (`MODELING_PROXY_TARGET` and
`AGENTS_PROXY_TARGET`). Requirements: Python 3.12 with `uv`, and Node 20 with npm (the script downloads Node 20 if the
environment lacks it). Entry script: `app.sh`; branch: `ui/frontend`. A hardware tier with at least 4 GiB of memory
is enough for the build. This script has not been run on Domino yet; check the first start's logs.
