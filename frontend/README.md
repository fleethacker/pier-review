# frontend

UI team's workspace: the 2D pier canvas, live dashboard and safety sheet views for the mooring assistant. The
framework and tooling are the UI team's call; nothing outside this folder depends on them.

## Goal

Build the mooring assistant's interface on top of the **drone-simulator** app that is already in this folder, instead
of starting from a blank project. The simulator gives us a working Cesium 3D globe, a React UI layer, a builder mode
for placing objects on the map, a wind system and ship models. We repurpose those for mooring operations:

> An interactive web app where a bridge team drags a ship onto a pier, picks ship class, pier and line types, and
> sees the agent's recommended tug assist, line sequence, gust warnings and safety margins. The output is an
> approved **Mooring Evolution Safety Sheet** and a graphical layout with the agent's rationale.

The UI is meant to be a reusable visualization shell, not a one-off mooring screen. Mooring is the first
application it talks to; the same UI should later drive other applications, for example one that simulates exercises,
through the same kind of API boundary. See [Multiple applications](#multiple-applications).

This is the "Physics-Informed Mooring & Tug Allocation Planning Agent" use case (Pier Review, Open Innovation track,
FLEETHACKER Norfolk 2026). Requirements that land on the UI:

- Drag-and-drop 2D pier canvas to select ship class, pier number and line types.
- Show the agent evaluating line geometry and bollard strain against NSTM 582 limits, with wind and ebb/flood current.
- Show recommended tug horsepower, line sequence, and warnings when gusts threaten line breaking thresholds.
- Review and approve the Mooring Evolution Safety Sheet, with rationale and safety margins.

The plan and module list are in [`../docs/PLAN.md`](../docs/PLAN.md). Where it differs from the contract, the contract
wins ([`../contract/README.md`](../contract/README.md)).

## Where this fits in the repo

```text
 frontend (this folder)  ──HTTP/WS──▶  agents   (:8001)  ──HTTP──▶  modeling (:8000)
        └─────────────────────────────HTTP/WS──────────────────────▶  modeling
```

`frontend/` integrates with the other pieces only through `contract/`. Never import or read the Python code to learn
an API; read the OpenAPI specs. The contract is generated from the Pydantic schemas, so never edit it by hand. If the
UI needs a contract change, it goes through the owning team's schemas and needs review from both sides.

## What is in this folder

The simulator, flattened into `frontend/`. Its original README is kept as
[`SIMULATOR_README.md`](SIMULATOR_README.md) for reference only; it describes the Domino drone demo, not this project.

| Path | What it is | Plan |
| --- | --- | --- |
| `packages/web/` | Vite + React 18 + TypeScript + Tailwind app. `src/cesium/` is the 3D engine (scene, game loop, cameras, managers, builder, wind). `src/react/` is the UI layer, connected to the engine by a typed event bridge (`cesium/bridge/`, `react/hooks/useGame*`). | **Becomes the mooring UI.** |
| `packages/web/src/cesium/builder/` | Builder mode: place and manipulate objects on the map. | Basis for the drag-and-drop pier canvas (ship, lines, fittings, tugs). |
| `packages/web/src/cesium/physics/WindSystem.ts` | Client-side wind used for the flight sim. | Replaced by wind, current and tide from the modeling API (`/ws/env`). Display only; physics stays in `modeling/`. |
| `packages/web/src/baseLocation.ts` | Location picker list (landmarks). | Replace with the contract's berths (`GET /berths`), starting at NAVSTA Norfolk Pier 12. |
| `packages/web/public/*.glb`, root `*.glb` | Aircraft, SAM and carrier models. | Keep ship models (carrier); drop the rest once nothing references them. |
| `packages/ml/`, `packages/python-yolo/` | Wind-correction ML and YOLO ISR backends for the drone demo. | **Not part of the mooring system.** Remove from the build and `app.sh` once the UI no longer proxies to them. |
| `app.sh`, `scripts/` | Domino app launcher and model-generation/deploy scripts. | Keep `app.sh` working for Domino hosting; point it only at the web package when the drone backends go. |

Drone-only features (Maverick mission, missiles, SAM sites, threat manager, touch flight controls) are not needed
for mooring and can be removed as we replace them. Prefer removing them in their own commits so history stays easy to
review.

## Multiple applications

The visualization layer must not know about mooring. Application knowledge lives in an **adapter**, one per backend
application, and the shell only deals with a neutral scene model.

```text
  mooring API (contract/)  ──▶  mooring adapter   ─┐
                                                    ├─▶  scene model  ──▶  shell: 2D view / 3D view / panels
  exercise-sim API (its own) ─▶  exercise adapter  ─┘
```

Proposed split inside `packages/web/src/`:

| Layer | Responsibility | Knows about mooring? |
| --- | --- | --- |
| `shell/` (Cesium engine, 2D and 3D views, camera, builder, timeline, status/badge components) | Renders the scene model, handles placement, selection and playback. | No |
| `scene/` | The neutral model: entities (position, orientation, model, status), links between entities (e.g. a line), overlays and annotations, a time axis, and user-editable properties. | No |
| `apps/<name>/` | An adapter: generated API client for that app, mapping from its responses to the scene model, and from user edits back to its requests. Also its app-specific panels (safety sheet, agent plan, exercise controls). | Yes, only here |

Rules:

- The shell never imports from `apps/`; apps register themselves with the shell (an app registry), and the user
  picks the active app.
- Every adapter implements the same small interface: load context, subscribe to live updates (WebSocket or SSE),
  push edits, and expose its panels. The exact interface is designed with the first adapter (mooring) and then
  checked against the exercise app before it is frozen.
- Status colors (GREEN, AMBER, RED), the backend/provenance badge and the reference/citation display are shell
  components, so every app gets them. Other apps may need other status vocabularies; the scene model maps them.
- Each app owns the OpenAPI specs for its API. For mooring, `contract/` holds the specs for both mooring services
  (`modeling.openapi.yaml` and `agents.openapi.yaml`). Where other apps' specs live and who reviews them is an open
  decision (below).

## Build against the contract, not the Python code

- Specs: [`../contract/modeling.openapi.yaml`](../contract/modeling.openapi.yaml) and
  [`../contract/agents.openapi.yaml`](../contract/agents.openapi.yaml). Conventions and the typical call flow are in
  [`../contract/README.md`](../contract/README.md).
- Example request bodies: [`../contract/examples/modeling/`](../contract/examples/modeling/).
- Mock servers: from the repo root, `make install` once, then `make mock`. Modeling runs at
  `http://localhost:8000/api/v1` (docs at `/docs`) and agents at `http://localhost:8001/api/v1`. CORS is open for
  local development.

Generate TypeScript types from the specs, for example with
[openapi-typescript](https://github.com/openapi-ts/openapi-typescript):

```bash
npx openapi-typescript ../contract/modeling.openapi.yaml -o packages/web/src/api/modeling.d.ts
npx openapi-typescript ../contract/agents.openapi.yaml -o packages/web/src/api/agents.d.ts
```

Regenerate them whenever `contract/` changes on `dev`.

## Contract conventions the UI must respect

- Units are in field names (`_kt`, `_ft`, `_lbf`, `_deg`, ...). Show Navy units.
- Wind direction is where it blows **from**; current is where it flows **toward**. Both degrees true.
- Berth frame: standing on the pier facing the water, +y points into the water and +x runs to your right.
  Ship frame: origin at midships, +x forward, +y to port. The canvas and the Cesium scene both have to convert to
  and from these frames in one place.
- A plan that is unsafe is a `200` with `status: RED` and findings, not an error. Only `404` and `422` are errors.
- Slow endpoints return `202` with a `job_id`; follow `events_url` (SSE) or poll `status_url`.

## Things to show from the responses

- `status` (GREEN, AMBER, RED) on every envelope, line, fitting and finding.
- `backend: "mock"` and `provenance.confidence` (`mock`, `estimated`, `vision`): show a banner or badge so nobody
  mistakes placeholder numbers for real ones.
- `findings[].reference` (the NSTM 582 paragraph) next to each warning.
- `result_id`s cited in agent rationale, linked to `GET /results/{result_id}` on the modeling service.

## Planned screens

Mapped to the typical call flow in the contract README.

1. **Pier canvas** (`GET /ships`, `/berths`, `POST /scenarios`, `POST /mooring/analyze`): pick ship class and pier,
   drag the ship and lines onto the fittings, color lines and fittings by `status` and `pct_wll` on every change.
2. **Live dashboard** (`WS /ws/env`, `WS /ws/alerts`, risk endpoints): wind, current, tide, gust warnings and the
   risk timeline.
3. **Agent plan** (`POST /agent/plans`, stream `events_url`): show steps, proposals and rationale as they arrive,
   including recommended tug horsepower and line sequence.
4. **Safety sheet** (`POST /safety-sheets`, `GET .../render?format=html`, `POST .../approvals`): review, approve,
   print.

## 2D and 3D views

Decided: the UI toggles between a **2D** top-down view and the **3D** Cesium view of the same scene. The 2D view is
the primary pier canvas for planning (drag and drop, line geometry, fitting loads); the 3D view is for situational
awareness and demos. Both render the same scene model, so edits and status colors stay in sync across the toggle.
The likely implementation is a top-down orthographic camera over the Cesium scene (or Cesium's 2D scene mode)
rather than a second renderer; spike this first, since it decides whether the 2D canvas can reuse the builder.

## Open decisions

- **Where other apps' API specs live.** The repo says `contract/` is the only thing shared, and it currently holds
  only the mooring specs (modeling and agents). Options: sibling folders (`contract/<app>/`), or each app's repo publishes its own spec that the
  frontend consumes. Needs agreement with whoever owns the exercise application.
- **Adapter interface.** Finalize after the mooring adapter exists and the exercise app's needs are known.
- **Units toggle.** Navy units only (as proposed in the plan) or a metric toggle.
- **Mapbox.** `packages/web/MAPBOX_SETUP.md` describes a token the simulator needs; decide whether the mooring UI
  still wants it.

## Running the simulator today

```bash
cd packages/web
npm install
npm run dev     # http://localhost:4000
```

The dev server still proxies `/api/detect`, `/api/analyze`, `/api/wind-correct` and `/api/wind-tunnel` to the drone
backends on `:5050` and `:5051`. Those go away as the UI moves to the mooring APIs.
