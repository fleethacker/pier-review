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

## What the UI shows

- **Phase 1:** choose a berth on the world map, place the ship, see analyzed colored lines; the planning agent
  streams its steps, then the safety sheet is created, approved and printed.
- **Motion view** (button in the sidebar): a plan view of the berthing simulator. It draws only what a frame
  supplies: hull and pier, fittings and fenders by load, lines by status and tension, tugs with velocity,
  acceleration and push, wind, current and wave glyphs, and the force breakdown. It handles both legacy frames and
  `rm0-v1` frames, shows validity and provenance badges at all times, and shows anything the simulator does not
  supply as *unavailable* or *not simulated*, never as zero. Live sessions have resume, pause, reset, tug and line
  commands; recordings have play, scrub and speed. The bundled mock recording replays with no backend.
- **Data sources and capabilities** panel and a standing "all results limited: seed data" banner.
- **Berth from an image:** upload a picture, get a draft berth with detections and confidence, confirm every flagged
  item, then use the saved berth. The draft is labeled mock or vision data.

The motion view has two modes. **Plan** is an SVG panel. **Map 2D/3D** draws the same frames in the shared Cesium
scene (ship hull with deckhouse blocks, tugs, lines colored by status) and leaves the map interactive, with camera
presets (top, bow, port quarter, pier side). The map draws position, heading and heave only when heave is simulated;
roll, pitch and a water surface are not drawn, and it lists whatever the frame did not supply.

- **Environment intake:** asks the intake agent for the next 24 hours at the chosen berth: MST, windows of concern,
  berthing windows and data quality (mock data is flagged), with a summary labeled deterministic or model-written.
- **Resilience:** every panel sits in an error boundary (a broken panel shows a message and Try again, the rest keeps
  working), API failures read as plain sentences, and decorative motion follows `prefers-reduced-motion`.
- **Bearer token (optional):** set `VITE_API_BEARER_TOKEN` to send `Authorization: Bearer ...` on REST and job polling
  for services run with `MOORING_AUTH_REQUIRED=1`. The token is built into the bundle, so use it for local or trusted
  networks. Browsers cannot attach headers to WebSocket or EventSource, so the live streams, the planner's SSE steps
  and motion sessions still need a trusted gateway in front of an authenticated deployment.

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
`http://127.0.0.1:8000` and `:8001`; use the numeric address, because `localhost` can resolve to IPv6 where the services do not listen). REST is under `/api/v1`, WebSockets under `/ws`. Set `VITE_MODELING_URL` or
`VITE_AGENTS_URL` to an absolute URL to bypass the proxy.

The default local demo needs no credentials. This UI does not yet implement bearer authentication for HTTP, SSE or WebSockets; authenticated deployments require a separate reviewed integration. The 2D and 3D views are drawn from the berth data itself.

Optional look-and-feel: set `VITE_MAPBOX_TOKEN` (a public `pk.` token) when building to put Mapbox satellite imagery
under the scene. Vite bakes it into the bundle, so it must be present at build time (on Domino, as a user or project
environment variable, since `app.sh` builds in the app container). Without it, or if Mapbox rejects it, the scene falls
back to the drawn water. Water ripples, wind and current streaks and pulsing over-limit lines are always on, and are
switched off for users who ask their system for reduced motion. The layout drawn on the imagery is the mock Pier 12,
not the real pier underneath it.

Other scripts in `packages/web`: `npm test`, `npm run lint`, `npm run typecheck`, `npm run build`, and
`npm run types` (regenerates `src/api/*.d.ts` from `../../contract/`; commit the result when `contract/` changes).
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
- Status colors (GREEN, AMBER, RED), the backend badge and the citation chip are shell components.
- Each app owns the OpenAPI specs for its API. Where other apps' specs live is still open.
- The scene model was designed from what the shell needs to draw. It has been exercised by the mooring adapter and
  the demo app; check it against the exercise application before freezing it.

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

The repo-root [`app.sh`](../app.sh) is the Domino app entry point. It starts the modeling and agents services on
`127.0.0.1:8000` and `:8001`, builds the UI, and serves it on `0.0.0.0:8888`. Only the UI port is exposed; the UI's
server proxies `api/modeling/*` and `api/agents/*` to the two services (`MODELING_PROXY_TARGET` and
`AGENTS_PROXY_TARGET`). Requirements: Python 3.12 with `uv`, and Node 20 with npm (the script downloads Node 20 if the
environment lacks it). Entry script: `app.sh`; branch: `ui/frontend`. A hardware tier with at least 4 GiB of memory
is enough for the build. This script has not been run on Domino yet; check the first start's logs.

## Check the integrated demo paths

```bash
make demo-check   # repo root
```

Starts both services and the built UI on private ports (the way `app.sh` does), then checks through the UI proxy:
the page and bundled fixtures, health and capabilities, the Phase 1 chain (scenario, agent plan over SSE, safety
sheet, approval), a berth vision round trip, and a motion session over a WebSocket (resume, command, pause, reset).
The browser portion requires Playwright and Chromium. Missing Playwright is a failure, not a passing gate.
Set `DEMO_CHECK_BROWSER_PYTHON` to an interpreter with Playwright; optionally set
`DEMO_CHECK_BROWSER_EXECUTABLE` to an installed Chrome/Chromium executable. `PLAYWRIGHT_BROWSERS_PATH`
selects a downloaded browser location. `DEMO_CHECK_SCREEN_DIR` redirects screenshots outside the repository.
`--skip-build` reuses the built UI; `--no-browser` explicitly reports the browser portion as skipped.

The API check uses the supported-limited named scenario, explicit Intake and independent Safety review,
and asserts AMBER/limited before sheet approval. The browser checks planning, sheet/print controls, motion,
units and estimated berth confirmation. These are scoped integration checks: explicit Intake/review UI
selection and the full four-case browser acceptance flow remain incomplete.

Verified local example without changing project dependencies:

```sh
DEMO_CHECK_BROWSER_EXECUTABLE="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
DEMO_CHECK_SCREEN_DIR=/tmp/mooring-demo-screens \
uv run --all-packages --with playwright python scripts/demo_check.py
```
