# UI agent log

Branch: `ui/frontend-updates` (off `dev` at `191a41a`). Not merged into `dev`: the owner asked to keep building on this
branch until they say otherwise.

## Log

- U0 baseline: `tsc`, `eslint` clean, 81 unit tests pass. `npm` is not installed on this host, so checks run through
  `node_modules/.bin/*`; `app.sh` downloads Node 20 itself.
- U0 fix: the dev proxy defaulted to `http://localhost:800x`, which resolves to `::1` here while the services listen on
  `127.0.0.1`, so every call returned 500. Defaults are now `127.0.0.1` (`app.sh` already set them explicitly).
- U0 fix: duplicate React keys in the agent panel (steps, rationale, assumptions) logged warnings on every plan.
- U2 motion view (2D): `src/apps/mooring/motion/`. Frame adapter for legacy and `rm0-v1` frames, controller for live
  sessions and recording playback, SVG plan canvas, badges, readouts and controls. Contract-consumer tests read the
  example frames from `contract/examples/modeling/`.
- Verified in headless Chromium against `make mock`: plan, apply, open motion view, start session, resume, tug command
  and recording replay, with no console errors.

- U3: data-source and capability panel (`status/`), standing "all results limited: seed data" banner.
- U5: berth-from-image panel (`vision/`): upload, detections overlay, confirmation gate, save and select.
- U6: `make demo-check` (`scripts/demo_check.py`, `scripts/demo_check_browser.py`): 20 checks on a fresh production
  build, including the WebSocket through the preview proxy. Screenshots in `docs/overnight/screens/`.
- U1 (partial): readable errors for 429/502/503/504/timeouts (`describeError`), duplicate React keys fixed in every
  text-keyed list (the safety sheet repeats rationale sentences).
- Findings worth knowing: safety-sheet creation can exceed the physics tool's 30 s limit when the CPU is busy
  (headless software WebGL does that); the UI now says so plainly and the check retries. The simulator allows 4
  sessions at once, shared by all clients.

## Decisions

- Motion view draws in an SVG panel fed by the motion store, not in the Cesium scene. The doc allows this fallback; the
  Cesium scene is a different coordinate setup and the SVG view is testable without WebGL.
- Live frames render through a latest-frame slot (one paint per animation frame), never a queue.
- Sessions are scarce (4 per principal, shared by all clients, held 30 min). "Restart session" resets the running
  session when the layout is unchanged; closing the view pauses and keeps the session.
- Legacy frames carry no scene, so the berth orientation is assumed (`090`) and flagged with a badge.
- Absent validity is `unknown`; absent components are `unavailable`; plain-text legacy alerts get no invented severity.

## Interfaces

- Proxy: `/api/modeling/*` and `/api/agents/*` (REST and WebSocket, `ws: true`). Targets from `MODELING_PROXY_TARGET` and
  `AGENTS_PROXY_TARGET` (default `http://127.0.0.1:8000` and `:8001`).
- Fixtures served from `./fixtures/` (copied from `contract/examples/modeling/` at build): `sim_recording_60s.json`,
  `sim_scene.json`.
- Contract fields the motion view consumes: `SimFrame` legacy fields, `schema_version`, `sequence`, `run_id`, `scene_id`,
  `motion.*`, `tug_states`, `line_states`, `fitting_loads`, `fender_states`, `environment.*`, `forces.*`, `validity`,
  `provenance`, `structured_alerts`; `SimScene` outline, fittings, fenders; `SimLifecycle.state`; `SimSessionCreated.scene_url`.

## Requests

- To the simulation agent: (1) the live frames are still legacy (no rm0 fields, no scene, no tug positions), so the
  live view shows lines, tugs and environment as unavailable. (2) The WS protocol has pause, resume and reset only; a
  speed control needs a new client message. Live speed is disabled and labeled until then.

## Tomorrow

- Cesium-scene version of the motion view (shared camera) and the 3D view (U4).
- Live speed control, once the protocol has it.

## Final report

**What works** (all verified by `make demo-check`, 20 of 20, plus 135 unit tests, `tsc` and `eslint` clean):
Phase 1 in the browser (plan with SSE steps, safety sheet, approval, print), the 2D motion view for live sessions and
recordings, the data-source and capability panel, berth from an image, Navy/Metric in the new views.

**How to run it:** `make install && make mock`, then `cd frontend/packages/web && npm install && npm run dev`; or
`make demo-check` for the headless run (set `DEMO_CHECK_BROWSER_PYTHON` to an interpreter with Playwright).

**Labeled limited, mock or synthetic:** every result (seed data); the motion fixture (mock, authored values); the vision
backend (mock: it copies the seed Pier 12 berth and says so); environment (mock, "live" mode still serves the mock);
waves, wake and telemetry (unavailable, never zero).

**Done since the first report:** Cesium map mode and 3D camera presets (U4), the intake agent in the UI, per-panel error
boundaries, reduced-motion support, narrow-width layout, a per-frame cost test, optional bearer token for REST.

**Still not done:**
- Live speed control: the session protocol has pause, resume and reset only. Needs a new client message from the simulation
  agent (logged under Requests); the UI shows the control disabled and says why.
- The map mode cannot draw roll, pitch or a water surface (the scene Pose has neither); it says so on screen.
- Bearer tokens cover REST and job polling only; WebSocket and EventSource cannot carry headers, so an authenticated
  deployment needs a trusted gateway.
- Live frames are still legacy, so live tugs, lines and environment stay "unavailable" until the simulator publishes
  `rm0-v1` frames and a scene.
- Full accessibility audit (contrast, screen-reader pass) and a profile of the React render path with real 10 Hz frames in
  a browser; only the adapter and mapper cost is measured.

**Left unmerged on purpose:** the branch `ui/frontend-updates` has not been merged into `dev`, as asked.
