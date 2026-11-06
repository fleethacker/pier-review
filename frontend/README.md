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

Current integration includes `dev` through `a5a8b2f`: D1/D2/D4 #13, exercise #21, S2/S3/P5/P6/S4/S8 #22,
A3/A8/A11 #23, tab UI #26, compatibility #24 and docs #20. Combined validation is recorded below.
[Kori's delivery record](KORI_UI_DELIVERY.md) separates implemented UI, local evidence and outstanding dependencies;
the [master plan](../docs/MASTER_PLAN.md#execution-ownership) assigns Kori, Snyder, Cruz and Bixler their next work.

## What the UI shows

- **Phase 1:** choose a berth on the world map, place the ship, see analyzed colored lines; the planning agent
  streams its steps, then the safety sheet is created, approved and printed.
- **Canvas editing:** drag a supported ship along or away from the pier; drag between fittings to create a line,
  or select a line and drag an endpoint to reconnect it. Escape cancels. Numeric placement and keyboard fitting
  selectors remain available. Edits clear previous margins and trigger a fresh analysis without changing installed lengths.
- **Class coverage:** the Scenario panel separates hull/load inputs from usable mooring bitts. Classes without
  bitts on the selected side cannot start planning; catalog presence is not class qualification. A8 capability routes
  and geometry-based templates are merged; their dedicated UI integration and approved additional-class inputs remain.
- **Sequence and gust evidence:** steps distinguish failed, unevaluated and partial-restraint states, retain review
  status and citations, and flag changed layouts. Wind limits distinguish sustained/gust working limits from
  unavailable ultimate breaking thresholds. P6's assessment backend exists, but approved capacity inputs and the UI
  basis-selection workflow remain outstanding. S8's bounded static search exists; its proposal UI is not yet connected.
  Bollard structural strain remains unavailable pending P7. A11 merged in #23: the existing sheet HTML includes
  saved assessed SVG when evidence supports it. U13 sidebar integration and target PDF setup remain. See the
  [immutable fixture](../agents/tests/fixtures/reviewed_sheet.README.md); never replace it with the current canvas.
- **Motion view** (button in the sidebar): a plan view of the berthing simulator. It draws only what a frame
  supplies: hull and pier, fittings and fenders by load, lines by status and tension, tugs with velocity,
  acceleration and push, wind, current and wave glyphs, and the force breakdown. It handles both legacy frames and
  `rm0-v1` frames, shows validity and provenance badges at all times, and shows anything the simulator does not
  supply as *unavailable* or *not simulated*, never as zero. Live sessions have resume, pause, reset, tug and line
  commands; recordings have play, scrub and speed. The bundled mock recording replays with no backend.
- **Data sources and capabilities:** public per-component availability is separate from the selected workspace
  forcing. Source, age, basis and unavailable/error states remain explicit, with a standing seed-data limitation.
- **Advance planning (24 h+):** public acquisition requires the provider's exact current depth and station bin/model
  layer. The immutable composed manifest is retained; canonical resolution verifies full arrival/docking/holding
  coverage and supplies the content hash pinned by planning. Partial forecasts block assessment, without an automatic
  synthetic fallback. Training generation is a separate labeled choice. Changed inputs or revisions require recheck;
  unknown issue times stay unknown. A3 agent-wide canonical binding also merged in #23; explicit public revision
  acquisition/selection still needs connecting to that workflow. See [Bixler’s handoff](../docs/BIXLER_IMPLEMENTATION.md).
  Local tests use offline fixtures, not proof of live-provider availability.
- **Berth from an image:** upload a picture, get a draft berth with detections and confidence, confirm every flagged
  item, then use the saved berth. The draft is labeled mock or vision data.

The motion view has two modes. **Plan** is an SVG panel. **Map 2D/3D** draws the same frames in the shared Cesium
scene (ship hull with deckhouse blocks, tugs, lines colored by status) and leaves the map interactive, with camera
presets (top, bow, port quarter, pier side). The map draws roll, pitch, heave and water only when the frame supplies
them, and lists whatever the frame did not supply. Those displays do not qualify the underlying motion model.

- **Environment intake:** assesses the selected saved scenario over 24 hours: MST, windows of concern,
  berthing windows and data quality, with a summary labeled deterministic or model-written. Manual conditions are
  saved as steady synthetic conditions, not a weather forecast. The next planning run receives the displayed report;
  changing inputs clears it. A completed report is not reused against a different environment or arrangement.
- **Resilience:** every panel sits in an error boundary (a broken panel shows a message and Try again, the rest keeps
  working), API failures read as plain sentences, and decorative motion follows `prefers-reduced-motion`.
- **Direct API credentials (optional):** use **Access** in the header to enter your own runtime credential. It lives only in this tab's memory, is cleared on refresh, and is sent in HTTP headers for REST, polling, media and Planner streaming events. Changing access restarts all workspaces; save drafts first. Never put backend keys in `VITE_*` values or URLs. For WebSocket environment streams and interactive motion, use an authenticated gateway; direct API-key mode blocks these connections and session creation. The private Domino deployment uses its gateway session with internal backend bearer auth unset. This is a shared demonstrator, not per-user resource isolation or operational authorization.

## Run it

Prerequisites: Node 22 (the CI runtime) and [uv](https://docs.astral.sh/uv/) for the local services.

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
`http://127.0.0.1:8000` and `:8001`; use the numeric address, because `localhost` can resolve to IPv6 where the services do not listen). REST is under `/api/v1`, WebSockets under `/ws`. Set `VITE_MODELING_URL` or
`VITE_AGENTS_URL` to an absolute URL to bypass the proxy.

The default local demo needs no credentials. The header’s runtime Access control supports per-tab bearer credentials for
HTTP and Planner SSE; authenticated WebSockets require the gateway. No backend credential is included at build time.
The 2D and 3D views are drawn from the berth data itself.

Optional look-and-feel: set `VITE_MAPBOX_TOKEN` (a public `pk.` token) when building to put Mapbox satellite imagery
under the scene. Vite bakes it into the bundle, so it must be present at build time (on Domino, as a user or project
environment variable, since `app.sh` builds in the app container). Without it, or if Mapbox rejects it, the scene falls
back to the drawn water. Water ripples, wind and current streaks and pulsing over-limit lines are always on, and are
switched off for users who ask their system for reduced motion. The layout drawn on the imagery is the mock Pier 12,
not the real pier underneath it.

The [exercise simulator](#exercise-simulator) tab is a separate map and needs its own public access token; it can come from
the build, from the server, or be pasted into the tab. See that section.

Other scripts in `packages/web`: `npm test`, `npm run lint`, `npm run typecheck`, `npm run build`, and
`npm run types` (regenerates `src/api/*.d.ts` from `../../contract/`; commit the result when `contract/` changes).
On local Node 26, run JSDOM tests with `NODE_OPTIONS=--no-experimental-webstorage npm test -- --run`; this prevents
Node's experimental global storage from masking browser storage. CI remains on Node 22. The incoming exercise
features are preserved; component filenames/imports were disambiguated for case-insensitive macOS filesystems,
with only the necessary test-environment compatibility adjustments.
The repo-root `app.sh` starts both services and serves the built UI on `:8888`; it is the Domino app entry point
(see [Deploying as a Domino app](#deploying-as-a-domino-app)).

## Choosing a berth

Berths are chosen by docking the ship at a port on the world map in the Scenario panel: drag the ship chip onto a port
marker (or select the marker), and pick a face if the port has more than one. Only berths that already exist in the
modeling service's reference data can be chosen; the UI has no way to add one. Each marker is a berth's `origin_lat` and
`origin_lon`, so a berth added to the reference data appears on the map with no UI change. The map backdrop uses the
Mapbox token when there is one.

Every berth face sits on a real pier: Pier 12 at Naval Station Norfolk, Pier 7 at Naval Base San Diego, Hotel Pier at
Pearl Harbor, and one pier each at Yokosuka and Rota. Their position, direction and length come from OpenStreetMap and
were checked against satellite imagery (`scripts/build_berths.py` holds the surveyed values and regenerates the YAML).
The fittings, fenders and depths on each are still the notional Pier 12 layout, and the weather is synthetic, so the
data is labelled mock.

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

**Mapbox token.** Mapbox GL needs a public access token (`pk.…`). The tab looks for one in this order: the build
(`VITE_MAPBOX_TOKEN=pk.…` in `frontend/.env` or the environment of whatever builds the app; Vite inlines it, which is
fine for a public token), one pasted into this browser (the prompt the tab shows when it has none, kept in local
storage), and the server (`MAPBOX_TOKEN` in the environment of the modeling service, served from
`/api/v1/exercise/config`; on Domino, set it as an environment variable on the app and restart it; secret `sk.` tokens
are never served). The server route means the token does not have to be present at build time. The default **Standard** map style works
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
- Sensors and detection (a switch in the Scenario panel, off by default so older scenarios behave as before): units only
  know what their side's sensors can see. Radar range grows with the fourth root of the target's cross-section (so a
  radar signature a tenth the size cuts range to about 56%), is cut off by the radar horizon (an antenna 22 m up sees a
  sea skimmer at about 30 km, a jet at 8 km altitude at about 380 km) and by sea clutter on low targets; sonar hears
  noise, which is why a quiet submarine is heard at a fraction of the range at which it hears a ship. Tracks are shared
  across a side, so a scouting helicopter or aircraft can find a target for a ship that cannot see it. Missiles and
  torpedoes are held until the target is tracked and in range (the salvo then goes off at the spacing it was planned
  with, and the event list says "held: not tracked" or "held: out of range"), and ships only shoot at missiles they have
  been tracking for a few seconds. A **Detected** event marks the first time each side picks a unit up.
- Rough seas (a switch next to it): the wind sets a sea state, and small craft slow down in it (fast attack craft from
  sea state 4, carriers hardly at all). Radar also loses low targets in the clutter.
- Decoys: a ship can carry decoys and jammers. Each missile or torpedo that gets close uses one up and may be led away.
- Submarines and torpedoes: a submarine is drawn as a dark hull and sail, heard rather than seen, and fires torpedoes that run
  under the water. Ship missile defences cannot shoot torpedoes; decoys are the defence.
- Storyboard: pictures and captions that come up beside units as the run plays. See below.
- Playback: play, pause, restart, scrub, 1x to 600x. Camera: fit all, follow, chase, orbit (circles the selected ship, or
  the whole group), and **Present**, which plays the whole exercise: it fills the screen, winds back to the top, picks a
  speed that plays the run out in about a minute and a half, and starts, with the storyboard coming up as it goes and the
  caption large enough to read from the back of a room. Pause, scrub and speed are still there, *Play again* restarts it,
  and Esc or *Exit* leaves. The view opens with a fly-in to the main group. View: ship size exaggeration (so ships read when zoomed
  out), wake length, names, routes, sensor ring, storyboard bubbles.
- Look: the light preset (dawn, day, dusk, night) lights the sea, and at dusk and night the ships' navigation and deck
  lights glow. Dusk and night are the most dramatic; the presets use them.

Twelve presets ship with it: a carrier group transit, a surface contact intercept at night, a formation drill, a **missile
salvo on a carrier group**, a **minefield transit**, an **air raid with SAM defence**, a **submarine ambush** and
**over the horizon** (a hostile destroyer that cannot see the carrier group sends a helicopter to find it; sweep the
helicopter's altitude in the red team). The last five include red-team setups. Four more are large (60 to 220 units) and use
everything: a **joint task force** (carrier group with fighters, early warning, ASW helicopters and a scouting drone
against destroyers, fast attack craft, raiders, two submarines, twenty attack drones and a minefield), a **convoy
through a submarine strait** (sweep the number of escorts) and a **drone swarm defence** (sweep the number of drones
against ships with limited magazines) and a **theater campaign** (over 200 units: a carrier group and an amphibious group on two
axes against two surface groups, four submarines, two raid waves, two drone carriers, early warning on both sides and two
minefields; a run takes about three seconds, so a red-team batch wants several cores). Newer unit classes: frigate (good sonar), diesel submarine (quiet), surveillance
drone, attack drone and airborne early warning. Each large one takes a few seconds per run, so batches of them are
best on a machine with several cores (the red team uses worker threads). Use **Edit as JSON** or **Download** in the Scenario panel to save or load your own, or **Saved scenarios** to keep them
in this browser or in a **shared library** on the server that everyone using the app can open (saving over a scenario
someone else changed since you opened it is refused, so nobody's work is lost). The shared library is one JSON file per
scenario in `EXERCISE_DATA_DIR` (default `/mnt/data/exercise` if it can be written, else `.exercise-data`); in a container
whose disk is thrown away on restart, point it at a persistent volume.

**Editing on the map.** With the clock at the start, drag a ship to move where it starts. Select a ship with a route, then
drag its waypoints, or drag one of the small dots between two waypoints to add a waypoint there; right-click a waypoint to
remove it. A dashed line follows the pointer and nothing is recomputed until you let go, and Esc cancels. Dragging is off
while placing waypoints, in a replay, and for units that are launched rather than placed. **Record** plays the scenario and
saves the map as a WebM video (the map itself; panels and labels are not in the picture, and it needs a recent Chrome, Edge
or Firefox). The **Events** tab at the
bottom lists launches, hits, interceptions and losses in words (click one to jump to it) and the timeline marks them.

### Storyboard: pictures that come up as it plays

Exercises are usually storyboarded by hand, as images on slides. This does the same job against the running simulation.
A **storyboard** is a list of moments, each a picture and a line or two pinned to a time and to a unit. As the run plays,
each moment comes up in a bubble beside its unit, stays for as long as it is given, then fades; a later moment on the same
unit replaces an earlier one, and different units can have bubbles up at the same time.

- **Build from the run.** The **Storyboard** button in the map toolbar opens the panel. *Build from the run* picks the
  moments worth telling — losses, hits, mine strikes, first contacts, launches — ranks them, spreads them across the units
  so no one ship takes them all, writes a caption for each from what happened, and puts a fitting stock picture on it. Say
  how many moments you want. It is a starting point to edit, not a finished product.
- **Pictures.** Three ways: **capture the map** as it looks at that instant (the picture is taken inside a render, scaled
  down and kept in the scenario); **load a picture** from a file, which is scaled the same way; or pick one of the
  **stock pictures**. The stock set is thirteen public-domain photographs — carriers, destroyers, a frigate, a submarine,
  a missile launch at night, aircraft, a drone, damage control, a bridge watch, replenishment, and the sea from orbit —
  taken from Wikimedia Commons, nearly all United States Navy work, which is public domain as work of the federal
  government. Each one's source, author and licence are recorded in `stockImages.ts` and shown in the picker.
- **Editing.** Every moment has a title, a caption, a time, how long it stays up, and the unit it hangs on (or a spot on
  the map, for scene-setting). Click a bubble on the map to open that moment; click a moment to wind the clock to it.
- **Showing it.** **Present** in the toolbar plays the whole thing by itself, full screen, with each moment's picture and
  caption coming up as its time arrives — one button, nothing to drive.
- **On the page.** The **Storyboard** tab at the bottom shows the whole thing as a strip that runs with the clock: the
  moment that is up is lit and scrolled to, past ones are solid, ones still to come are dimmed. Click a card to jump to it.
  The moments also appear as marks above the timeline.
- **Out of the app.** *Storyboard to print* opens the whole thing as a page laid out two cards to a row, which prints or
  saves to PDF from the browser — the direct replacement for the slide deck. *Download the page* saves the same file.

Pictures you capture or load are kept inside the scenario, so a scenario travels as one file with its storyboard in it;
the panel shows how much they weigh, since the shared library refuses a scenario over about a megabyte. Stock pictures
are references, so they cost nothing to save.

Four presets ship with a written storyboard, so the feature can be seen without building one: **Missile salvo on a
carrier group** (a salvo gets one hit through the screen), **Submarine ambush** (she hears them first and is never
found), **Over the horizon** (finding the group costs the attacker seven minutes and the shot) and **Drone swarm
defence** (cheap drones against magazines that run out). Every time quoted in those captions is an event the simulation
really produces, and a test holds them to it, so retuning a scenario cannot quietly leave the words wrong.

### Red team: how likely is it?

**Red team** in the map toolbar runs the scenario hundreds or thousands of times with random variation and measures how
often things happen. You set three things, all saved with the scenario:

- **Outcomes**: the questions to ask. A unit is hit, destroyed or falls below a strength; a side loses N units; a mine goes
  off; N missiles are shot down; two units come within some distance of each other; a unit is detected (by anyone, or by one
  side). Any of them can be limited to "by this time", and they combine: **all of**, **any of** or **not** other outcomes
  listed above (so "the carrier is hit and a destroyer is lost", or "the carrier is not hit within 12 minutes").
- **What varies**: any of wind and current, or, per unit, speed, heading, start position, route position, launch time,
  altitude, hit points, damage, hit chance, defence kill chance and shots, radar signature and range, decoys and decoy
  chance, or whether it is present at all. Each draws from
  a uniform, normal, triangular or listed distribution, and replaces, adds to or multiplies the scenario's value.
  Missile hits, defensive shots and mines are chances on top of that.
- **A sweep** (optional): repeat the whole batch at several values to draw a curve, for example how the chance a carrier
  is hit grows as the salvo goes from 1 to 8 missiles.

Results show each outcome's chance with a 95% interval (Wilson), a histogram of when it happens, a ranking of which
variation drives it (the correlation between each draw and the outcome, with the average value when it happens and when it
does not), and average hits, interceptions and losses per run. Every chance carries its "±", and a chart shows it settling
as runs accumulate, with a note of how many runs would get within ±2 points. Tick **Stop early when sure enough** to end a
batch as soon as every interval is that narrow. Runs go on worker threads (up to seven, fewer on small machines; if workers
are blocked the batch quietly runs on the page's own thread), with progress and a Stop button. Results can be downloaded as
**CSV** or **JSON** (scenario, settings and results together), or opened as a printable **report**.

**Comparing.** **Keep as baseline** remembers a finished batch; change the scenario or a setting, run again, and each chance
shows how far it moved, with an interval on the change (grey arrows are within noise). This is the way to answer "does
adding a destroyer help?" without squinting at two percentages. **Show their paths together on the map** draws up to six runs
where an outcome happened (red) and six where it did not (green).

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

Tests cover the simulation (including the engagements, sensors and the Monte Carlo statistics), the storyboard, the
scenario JSON, the map view (against a fake Mapbox), the panels, and the server's library, token and error endpoints. `npm run test:e2e` drives a
production build and the real modeling service in headless Chromium (software WebGL, so it checks that things load and work,
not how the map looks); it needs Playwright, which is not a dependency: `npm i --no-save playwright && npx playwright install chromium`.
Browser problems (uncaught errors, a lost WebGL context, a refused token) are sent to the modeling service's log under the
`exercise` logger, with any Mapbox token blanked first. Check the look on a real GPU before demoing.

**Not modeled**: terrain and coastlines (the scenarios are open ocean; Mapbox draws real land, but nothing in the
simulation knows about it), electronic warfare beyond decoys, weather beyond wind and sea state, anything that flies a
deck cycle (carrier flight operations), and fuel. Detection is deterministic: in range means seen.

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
5. **Safety sheet** (overlay): the service's rendered sheet, margins, rationale, an explanation when a plan-bound layout image is unavailable, approvals by pilot,
   first lieutenant and CO, and print.

## Known limits and qualification

- Backend `real` identifies the implementation, not qualification. Seed data and synthetic uncertainty remain unqualified; inspect result validity and warnings. Do not use this UI operationally.
- Saving a scenario freezes the displayed weather into a synthetic steady snapshot, including for agent runs; it does not preserve a live forecast or replay timeline.
- Only the DDG-51 class has fitting data, so other classes show a hull only and line editing is disabled.
- Alerts and load displays retain validity; invalid or unknown assessments do not supply passing load colors or percentages.
- Wind-limit bearings use the API wind-from convention; the chart compares sustained wind to sustained limits. See [contract semantics](../docs/CONTRACT_SEMANTICS.md).
- Explicit Intake and independent Safety-review selection remain absent from the UI. Sheet creation invokes review implicitly; API clients can select those reports explicitly.
- Motion is a labeled surrogate; the 2D motion panel does not establish a qualified vessel maneuver.

## Open decisions

- **Where other apps' API specs live.** `contract/` currently holds only the mooring specs. Options: sibling folders
  (`contract/<app>/`), or each app publishes its own spec that the frontend consumes.

## Deploying as a Domino app

The repo-root [`app.sh`](../app.sh) is the Domino app entry point. It builds the UI, starts the modeling and agents services on
`127.0.0.1:8000` and `:8001`, and serves the UI on `0.0.0.0:8888`. Only the UI port is exposed; the UI's
server proxies `api/modeling/*` and `api/agents/*` to the two services (`MODELING_PROXY_TARGET` and
`AGENTS_PROXY_TARGET`). Requirements: Python 3.12 with `uv`, and **Node >=22.17 with npm**, installed in the app
environment. The launcher checks prerequisites, waits for both API proxies and stops all child processes if a
service exits. Use the reviewed release commit on `main` for a target rehearsal. Current verification is local;
Domino remains unverified. See the [deployment procedure](../docs/DEPLOYMENT_READINESS.md).

For the exercise simulator tab, add `MAPBOX_TOKEN` (a public `pk.` token, which the modeling service hands to the
page at run time, so it need not be present at build time) and `EXERCISE_DATA_DIR` (a path on a persistent volume
for the shared scenario library) to the app's environment variables, and restart the app.

## Check the integrated demo paths

```bash
make demo-check   # repo root
```

Starts both services and the built UI on private ports (the way `app.sh` does), then checks through the UI proxy:
the page and bundled fixtures, health and capabilities, all four planning chains (Intake, Planner SSE, independent
review, sheet, approve/reject), supplied training forecast planning, berth vision and a live WebSocket session.
The browser portion requires Playwright and Chromium. Missing Playwright is a failure, not a passing gate.
Set `DEMO_CHECK_BROWSER_PYTHON` to an interpreter with Playwright; optionally set
`DEMO_CHECK_BROWSER_EXECUTABLE` to an installed Chrome/Chromium executable. `PLAYWRIGHT_BROWSERS_PATH`
selects a downloaded browser location. `DEMO_CHECK_SCREEN_DIR` redirects screenshots outside the repository.
`--skip-build` reuses the built UI; `--no-browser` explicitly reports the browser portion as skipped.

The API checks preserve each case's initial and final status, review identity and validity. The browser checks
the supported AMBER/limited planning path, sheet/print controls, motion, units and estimated berth confirmation.
These are scoped integration checks: full four-case review-selection and advance-planning browser acceptance
remain incomplete. `make demo-check-readiness` fails explicitly on those and the outstanding S1/D1/A3 requirements.

Verified local example without changing project dependencies:

```sh
DEMO_CHECK_BROWSER_EXECUTABLE="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
DEMO_CHECK_SCREEN_DIR=/tmp/mooring-demo-screens \
uv run --all-packages --with playwright python scripts/demo_check.py
```


Audit workflow safeguards (F01/F02/F09/F10/F12/F13/F23/F27/F28):

- Applying an Advance arrival binds its exact forecast revision, content hash, arrival time and operation/holding interval to Intake. Planner and Safety inherit that Intake report. Starting Planner directly first runs Intake when an applied forecast has not yet been assessed; failure blocks planning instead of substituting steady conditions. Changing the selected times or source clears the binding; current manual conditions remain explicitly a steady scenario. Layout, environment and tug edits invalidate prior Planner/Safety evidence and close its sheet.
- Public acquisition can offer **Use retrieval cutoff and retry** when provider retrieval followed the chosen as-of time. This explicit action preserves the requested source layer and forecast horizon for cached re-use. The initial arrival window is 25–31 h after the hourly cutoff, leaving time for acquisition; existing user edits are never shifted. It does not shift arrival times or grant a shorter-than-24-hour planning lead; the planning form reports a lead violation until the user chooses a compliant operation.
- The transit camera uses the completed run's environment, loading and simulation clock. Other vessels come from the same series with catalog dimensions; missing dimensions prevent a request rather than silently dropping traffic. A future path ending early is sent without extrapolation and remains a backend validity limitation. Changing the selected vessel or seeking cancels/clears its previous prediction and forces the final input to refresh; continuous playback remains throttled. Transit runs have no berth binding, so their camera requests leave pier/fender coverage unknown instead of assuming Norfolk; authored camera presets retain their explicit berth. The panel labels which vessel and time its returned prediction describes.
- Exercise-library draft baselines and shared revision tokens live with the controller across tabs. Failed report saves preserve drafts. Spreadsheet exports neutralize formula-leading text. Vessel selection uses native keyboard-operable buttons.
