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
