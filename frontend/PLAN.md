# Frontend plan

How we turn the drone-simulator in this folder into the mooring assistant UI, as a reusable shell that other
applications can plug into. Goals, structure and conventions are in [README.md](README.md). The repo-wide plan is
[`../docs/PLAN.md`](../docs/PLAN.md); the frontend's first milestone is its gate **G0** ("the UI can render a scenario
from mocks"), and the frontend demo contribution is part of **G2** (approved safety sheet for DDG 51 at a mock pier).

## Status

| Phase | State | Notes |
| --- | --- | --- |
| 0 Foundations | Done | Tokens are optional; 2D/3D works in one Cesium scene; lint, tests, generated types. |
| 1 Strip and rebase | Done | Drone code, models and backends removed; `app.sh` and the dev/preview proxies rewritten. |
| 2 Scene model and shell | Done | Rotating entities was left out (nothing needs it yet). |
| 3 Mooring adapter (G0) | Done | DDG 51 at Pier 12 North renders from the mocks with analyzed, colored lines. |
| 4 Canvas editing, 2D/3D | Done | Ship drag, click-to-add lines, recommend, saved scenarios. Ships are generated hulls with per-class deck profiles. |
| 5 Live dashboard | Done | Env streams (live, replay, storm ramp), alerts, forecast, wind limits, gust risk. |
| 6 Agent plan | Done | SSE steps, proposal preview, apply with undo, tugs on canvas, line sequence, follow-ups. |
| 7 Safety sheet | Done | Service-rendered sheet, margins, rationale links, layout image, approvals, print. |
| 8 Demo hardening | Done for the mock stack | Error and retry states, accessibility fixes, production build checked, [DEMO.md](DEMO.md). |
| 9 Exercise simulator | Done (client-side) | Second app on the shell: Mapbox 3D map, deterministic ship simulation, scenario editor, presets. Added the shell's `Canvas` slot and app tabs. See the README. |

Verified in headless Chromium (software WebGL) against the running mock servers, plus 41 unit tests, type checking and
lint. Since the first pass: Cesium is lazy-loaded and split from the app (app code 251 kB, Cesium its own chunk), a
Navy/Metric toggle was added, ships got per-class superstructure, and a regression where the app's empty overlay layer
swallowed every canvas click was fixed and covered by a test.

Unused simulator leftovers (carrier models, model-generation script, the old README, the root package.json) and the
unused lucide-react dependency have been deleted; they are in git history.

Still not done: rotating entities (nothing needs it), real 3D ship models (none in the repo), testing on a real GPU, a
real backend (mock responses only), and any browser other than Chromium.

## What the simulator gave us, and what it did not (at the start)

Checked against the code, not the file names. Kept for the record; the work below has since been done.

| Area | Today | Consequence for the plan |
| --- | --- | --- |
| Boot | `main-cesium-react.ts` shows a token screen, then a landmark picker, then a cinematic earth zoom, then spawns an aircraft and starts the game loop. | Replace with a plain boot: load app, pick app and berth, frame the scene. |
| React and Cesium link | `GameBridge`: a typed event emitter plus public methods. Adding a feature means editing `bridge/types.ts`, `GameBridge.ts`, `hooks/useGameMethod.ts`, then the component. `BuilderHUD` polls every 500 ms. | Too hand-wired for adapters. Replace with a scene store that both React and Cesium subscribe to. |
| Builder | Places **waypoints only**, by moving a cursor with WASD. No picking, selection, drag or rotate. `GameObject` has `{id, type, position, rotation, properties}`. | Drag-and-drop pier canvas is **new work**, not a reskin. The `GameObject` shape is a usable starting point. |
| Cameras and modes | One hard-wired follow camera. Modes are `play` and `builder`. No top-down, orthographic or 2D support. | The 2D/3D toggle needs a camera/view layer built from scratch. |
| Ground and imagery | Cesium globe is hidden; the ground is Google Photorealistic 3D Tiles via a Cesium Ion token. Mapbox token also required (geocoder, minimap, static images). The app will not boot without both tokens. | Biggest environmental risk, see "Risks". 2D top-down needs a ground that works without these. |
| Models | `StaticModel` loads a GLB at a fixed pose. We have a carrier, aircraft and SAM models. `scripts/generate-*.mjs` build models procedurally. | We need DDG 51, CG 47, CVN 68 and LHD 1 representations. |
| Wind | `WindSystem.ts` simulates gusts for the aircraft only. | Not reused. Wind comes from the modeling API. |
| Quality gates | No tests, no lint, no formatter. `tsc` strict runs in the build. | Add them in Phase 0. |
| Backends | Vite proxies `/api/detect`, `/api/analyze` (:5050) and `/api/wind-*` (:5051). | Dropped with the drone features. |

Drone-only code (aircraft and car vehicles, autopilot, Maverick mission, missiles, SAM sites, threat manager, touch
flight input, detection, wind tunnel, crash and tracking features) gets deleted, in separate commits.

## Target architecture

```text
packages/web/src/
  shell/      Cesium scene, 2D/3D view controller, cameras, picking and drag, layers, timeline, shared UI
              (status colors, backend badge, citations). Knows nothing about mooring.
  scene/      Neutral model and store: entities, links, overlays, time axis, editable properties, selection.
  apps/
    mooring/  Adapter: generated API clients, API -> scene mapping, edits -> requests, mooring panels.
  api/        Generated TypeScript types for each app's specs (mooring: modeling.d.ts, agents.d.ts).
```

- `shell/` never imports from `apps/`. Apps register with the shell; the user picks one.
- The scene store replaces the event bridge. React renders from it; the Cesium layers subscribe to it. Edits go
  through store actions, and the active adapter turns them into API calls.
- The scene model must be defined from what the shell needs to draw, not from the mooring schema, then checked
  against the exercise-simulation app before it is frozen.

## Phases

Each phase ends with something runnable. Phase 3 is gate G0.

### Phase 0: Foundations (spikes and tooling) - done

Results (spikes were run in headless Chromium with software WebGL, then thrown away):

1. **Imagery and tokens.** Cesium boots and renders with **no tokens**: `baseLayer: false`, globe shown with a flat
   water color, and the pier, ship and lines drawn as vector entities in the berth frame. Decision: tokens are
   optional. The app never gates on them. If `VITE_CESIUM_TOKEN` is set, 3D adds Google Photorealistic 3D Tiles as
   real-world context; the 2D canvas is always the schematic. Mapbox is dropped (it only served the drone minimap and
   detection images). `.env` lives in `frontend/` (Vite's `envDir`).
2. **2D/3D.** Works in Cesium with no second renderer: `camera.switchToOrthographicFrustum()` plus a top-down
   `setView` gives the 2D canvas (set `frustum.width` to zoom); `switchToPerspectiveFrustum()` gives 3D. Picking
   (`scene.pick`) works in both. Dragging uses `camera.getPickRay` intersected with the berth's horizontal plane
   (`IntersectionTests.rayPlane`), with camera inputs disabled during the drag; a 150 px drag moved the ship
   as expected. For the 2D view, set the camera heading to `face_bearing_true_deg - 90` degrees with pitch -90: screen
   up is then the berth's +y (into the water) and screen right is +x.
3. **Tooling.** Added ESLint (flat config), Prettier, Vitest, `@testing-library/react`, openapi-typescript. Scripts in
   `packages/web/package.json`: `npm run lint | format | test | typecheck | types`. Generated types are committed in
   `packages/web/src/api/` (regenerate with `npm run types`). `package-lock.json` is now tracked.
4. **Dev loop.** `make mock` at the repo root, then `npm run dev` in `packages/web`. Calls go straight to
   `:8000` and `:8001` (CORS is open); a proxy can be added for hosting if needed.

### Phase 1: Strip and rebase the shell - done

1. Delete drone-only features (separate commits per area; build must pass after each).
2. Replace the boot with: load, choose app, choose berth, frame the scene. Remove the cinematic, location picker,
   token gate (or reduce it to whatever Phase 0 decides).
3. Replace `GameBridge` and the `useGame*` hooks with the scene store. Keep `Scene.ts`, `GameLoop.ts` and the
   Cesium plumbing that survives.
4. Remove the drone backends and the `/api/*` proxies; update `app.sh` to build and serve only the web package.

### Phase 2: Scene model and shell - done

1. Define `scene/` types and the store (entities, links, overlays, selection, time).
2. Layers that render the model in 3D: entity models/placeholders, lines as colored polylines, labels, overlays.
3. Picking and selection. Move and rotate gizmo or drag handles for entities that are marked editable.
4. Shared UI components: status chips (GREEN/AMBER/RED), backend/provenance badge, citation chip, property panel.
5. App registry and app switcher (with a trivial test app to prove the shell does not depend on mooring).

### Phase 3: Mooring adapter, read-only (gate G0) - done

1. Generate API types and clients for modeling and agents.
2. Load `GET /ships`, `/berths`, `/lines`, `/tugs`; map a berth to scene entities: pier outline, fittings (by `kind`
   and `condition`), fenders. Convert between the berth frame (origin lat/lon, `face_bearing_true_deg`, +x right,
   +y into the water) and Cesium world coordinates in **one tested module**.
3. Place a ship (frame: midships origin, +x forward, +y to port) with its fittings, at a berth and side-to.
4. `POST /scenarios` and `POST /mooring/analyze` for a canned configuration from `contract/examples/`; color lines
   and fittings by `status` and `pct_wll`; show findings with their NSTM 582 `reference`.
5. Show the mock badge from `backend` and `provenance.confidence`.

**Done when:** DDG 51 at NAVSTA Norfolk Pier 12 North renders in 3D from the running mock servers with analyzed,
colored lines and a findings list.

### Phase 4: Pier canvas editing and the 2D/3D toggle - done

1. 2D top-down view and the toggle, per the Phase 0 spike. Selection and status colors identical in both.
2. Select ship class and berth, side-to, loading condition. Drag the ship along the pier (`ship_x_ft`).
3. Add, remove and edit lines: choose a ship fitting, then a pier fitting; pick `spec_id`, parts, pretension.
   Block or warn on suspect and do-not-use fittings, and on fittings occupied by another ship.
4. Debounced `POST /mooring/analyze` on every edit with cancellation of stale requests; show pending state.
5. Save and load scenarios (`/scenarios`).
6. Ship visuals for DDG 51, CG 47, CVN 68, LHD 1: real models if available, otherwise generated hull shapes sized
   from `loa_ft` and `beam_ft` (the generator scripts are a starting point).

### Phase 5: Live dashboard - done

1. `WS /ws/env` (live, replay, scenario modes): wind, gust, current, tide stage; wind and current arrows on the
   canvas (wind from, current toward).
2. `WS /ws/alerts`: gust warnings, as a feed and as canvas annotations.
3. `POST /risk/timeline` and `/mooring/envelope`: limiting-wind envelope and timeline charts. Use the dataviz skill
   for chart styling.
4. Replay control for the storm replay needed at G2.

### Phase 6: Agent plan - done

1. `POST /agent/plans`, then stream `events_url`: steps, proposals, messages; reconnect on drop.
2. A proposal can be previewed on the canvas and applied or rejected; applying updates the scene and re-analyzes.
3. Rationale panel: every number links to its `result_id` (`GET /results/{id}`).
4. Follow-up chat via `/agent/plans/{id}/messages`.
5. Recommended tug horsepower and line sequence shown on the canvas (tug icons at push points, numbered lines).

### Phase 7: Safety sheet - done

1. `POST /safety-sheets`, then `GET .../render?format=html` in a viewer with print support.
2. Review with citations and safety margins; approval flow (`POST .../approvals`) with clear signed/unsigned state.
3. Export the canvas as an image for the sheet and the fielding brief.

### Phase 8: Demo hardening - done for the mock stack

1. Scripted demo path and seed scenarios (the G2 walkthrough: GREEN plan, tug horsepower, gust warning in replay,
   approved sheet).
2. Error, loading and empty states; behavior when a service is down; keyboard and basic accessibility checks.
3. Domino app hosting through `app.sh`; production build size (the 3D assets are large).
4. Demo walkthrough notes for the one-page fielding brief.

### After the mooring milestone

- Berthing simulator view (`WS /ws/sim/{session_id}`, 10 Hz `SimFrame`): this stresses the scene model's time axis,
  so check it early rather than late.
- Second application adapter (exercise simulation) once its API is known; this is the real test of the shell and
  the scene model. Expect to change the scene model after it.
- Approach planner (route and under-keel clearance) overlays.

## Cross-cutting rules

- Build against `contract/`; never read Python code. Regenerate types when `contract/` changes on `dev`.
- Navy units everywhere unless the units decision changes; convert only at the edge, and name units in code.
- A RED plan is a normal response; show it, do not treat it as an error. Only `404` and `422` are errors.
- Every number from the backend that a user can see should carry its status and, where the response has one, its
  citation. Placeholder (`mock`) data is always labelled.
- Each phase lands as small PRs from `ui/...` branches into `dev` (see [`../CONTRIBUTING.md`](../CONTRIBUTING.md)).
- Tests: Vitest for pure logic (frame conversion, scene mapping, edit-to-request mapping), plus a smoke test that
  renders a scenario from recorded example responses so the UI is testable without the mock servers.

## Risks and open questions (current)

| Risk or question | Why it matters | Resolve in |
| --- | --- | --- |
| ~~Cesium Ion and Mapbox tokens required to boot~~ | Resolved in Phase 0: tokens are optional | Done |
| ~~2D top-down view reuse~~ | Resolved in Phase 0: ortho camera over the same scene works with picking and dragging | Done |
| ~~Drag-and-drop, selection and picking did not exist~~ | Resolved: drag along the pier, click selection, click-to-add lines. Rotation is not built. | Done |
| Ship visuals are generated shapes, not models | Visual credibility; no ship models in the repo | Open |
| Scene model designed from one real app plus a demo | Could encode mooring assumptions | Check against the exercise app before freezing |
| Where other apps' API specs live | Needs the owner of the exercise application | Open |
| ~~Navy units only versus a metric toggle~~ | Resolved: both, Navy by default | Done |
| Everything verified against mock backends and software WebGL | Real services and GPUs may differ (frame times, response shapes, job latency) | Before the demo |
| Cesium is 4.2 MB of JavaScript (1.1 MB gzip) plus its static assets | Slow first load on poor links; the app shell itself is small and loads first | Mitigated by lazy loading |
| Contract changes while we build | Generated types break at compile time; that is the intended signal | Ongoing |
