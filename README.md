# Pier Review

**What we are building: a backup camera for ships.** A car's backup camera draws where the car will go given its steering;
this project predicts and draws where a ship will go over the next minutes from its current position and motion, the
commands in force (rudder, engine, tugs, lines) and current conditions (wind, current, tide), with an honest uncertainty
corridor and contact warnings. Around that core: mooring and docking planning with a Mooring Evolution Safety Sheet, berthing
and port-transit simulation, and mission storyboarding that ties a recorded track to timestamped images and reports. See the
[north star in the master plan](docs/MASTER_PLAN.md#north-star-a-backup-camera-for-ships). The initial transit-based prediction service
and missions/Transit overlay are merged (#14), with limited validity. The berthing prediction engine, complete starting
state, coastline checks and calibrated uncertainty remain unfinished; see [PREDICTION.md](docs/PREDICTION.md).

Mooring planning demonstrator for FLEETHACKER Norfolk 2026. It evaluates mooring configurations, tug assistance and draft
line sequences against wind, current and tide, and produces a Mooring Evolution Safety Sheet. The plan, phases and module
list are in [docs/PLAN.md](docs/PLAN.md). Current implementation and gaps are tracked in the
[build-out ledger](docs/MODELING_BUILDOUT_STATUS.md); **priorities, owners and
sequence for the rest of the build are in the [master plan](docs/MASTER_PLAN.md).**

Repository: [fleethacker/pier-review](https://github.com/fleethacker/pier-review). Branch from `dev` and open feature PRs with `--base dev`. To update an existing checkout, run `git remote set-url origin https://github.com/fleethacker/pier-review.git` and `git fetch origin`.

> **Real code, placeholder data.** Implemented: UFC environmental loads, static equilibrium, limiting wind and tide sweep,
> rated tug allocation, holding-plan checks, bounded line-plan search, draft sequence checks, risk sampling, bounded jobs
> and optional SQLite persistence. Risk artifacts remain unqualified. Berthing uses a real integrator with an explicitly
> synthetic vessel body; approach planning/simulation remain mock. CO-OPS observations and individual NWS/CBOFS/chart readers
> exist, but a complete public forecast for docking is not yet wired. Public provider/composer work is implemented in open [PR #13](https://github.com/fleethacker/pier-review/pull/13), pending its separate review/merge. Default operation stays offline with labeled
> synthetic data. Supplied forecast snapshots support planning at least 24 hours before arrival; see
> [FORECAST_DOCKING.md](docs/FORECAST_DOCKING.md).
>
> Seed-data results are limited, or invalid where inputs or checks fail. `backend=real` does not establish qualification.
> See [DEPLOYMENT_READINESS.md](docs/DEPLOYMENT_READINESS.md) before use beyond the local demonstration;
> `GET /capabilities` lists qualification blockers.
>
> Intake, Planner, Safety/Brief and Berth Map have deterministic implementations with optional guarded LLM support.
> Without a vision model, Berth Map creates a draft from supplied metadata/catalog geometry, not image extraction.
> Drafts require confirmation; sequence rules and durations need deck-officer/pilot review.

Two further features merged in PR #10. PR #14 addressed several transit defects, but the original review is not
closed as a whole; the [finding ledger](docs/MODELING_BUILDOUT_STATUS.md#pr-10-review-disposition) assigns the remaining work. **Mission storyboarding** rebuilds a ship's path from recorded fixes and ties timestamped
images and reports to it (see gap and extrapolation requirements in
[MISSION_STORYBOARD.md](docs/MISSION_STORYBOARD.md)), and **port transit simulation** runs own-thrust and tug-assisted
ships along demonstration routes with a surrogate maneuvering model, always of limited validity
([PORT_TRANSIT.md](docs/PORT_TRANSIT.md)). A 5-minute demo script for both, with data preparation, is in
[DEMO_MISSIONS_TRANSIT.md](docs/DEMO_MISSIONS_TRANSIT.md) (open the UI with `?app=missions`).

Optional UI handoffs are kept in [MODELING_UI_RECOMMENDATIONS.md](docs/MODELING_UI_RECOMMENDATIONS.md).

The Bixler implementation branch adds explicit forecast binding through Intake, Planner and Safety, saved vector
layouts in printable Safety Sheets, cited explanations of saved predictions, and ship-input validation/capability
endpoints. These remain limited by their source inputs. See the [implementation and acceptance record](docs/BIXLER_IMPLEMENTATION.md)
for consumer interfaces and outstanding UI, modeling and source dependencies.

## Layout

The repo is split into three independently built pieces that integrate only through the API contract.

| Folder | What it is | Owned by | Runs on |
| --- | --- | --- | --- |
| [`contract/`](contract/) | OpenAPI specs and example requests: the only thing the other three share | Everyone (changes need review from both sides) | — |
| [`frontend/`](frontend/) | The pier canvas, dashboard and safety sheet UI | UI team | your dev server |
| [`modeling/`](modeling/) | Physics and ML: environment, loads, mooring solver, risk, tugs, optimizer, berthing and approach simulation | Physics/ML team | `:8000` |
| [`agents/`](agents/) | LLM agents: berth map analysis, planning agent, safety sheet drafting. Calls `modeling/` over HTTP | Agents team | `:8001` |

```text
 frontend  ──HTTP/WS──▶  agents   (:8001)  ──HTTP──▶  modeling (:8000)
     └──────────────────HTTP/WS──────────────────────▶  modeling
```

## Quick start

Prerequisite: [uv](https://docs.astral.sh/uv/) (it installs the pinned Python 3.12 for you). The UI and `app.sh` also require Node.js **22.17 or newer** with npm, matching the locked Cesium dependencies.

```bash
make install   # one virtualenv for both Python services
make mock      # modeling on :8000 and agents on :8001, with reload
```

- Modeling API docs: http://localhost:8000/docs
- Agents API docs: http://localhost:8001/docs

Other targets in the root `Makefile`: `make modeling` or `make agents` (one service), `make contract`
(regenerate the contract), `make test`.

For the combined app, run `./app.sh`; it installs locked dependencies, builds the UI and serves it on port 8888 with REST, SSE and WebSocket proxies. Set `VITE_MAPBOX_TOKEN` in the app environment before startup if using Mapbox imagery. Native PDF libraries are optional: HTML sheets and browser printing remain available. See [deployment readiness](docs/DEPLOYMENT_READINESS.md) for the Domino rehearsal procedure and access boundary.

`make demo-check` exercises the four API planning chains and saved sheet diagrams, a supplied forecast manifest through independent review, cited prediction narration, and the motion proxy including scene/recording validation, speed and reconnect, plus the browser smoke when Playwright is installed. `make demo-check DEMO_CHECK_ARGS=--no-browser` explicitly limits coverage to API/proxy checks. `make demo-check-readiness` additionally fails on outstanding master-plan acceptance requirements; a green baseline is not full release readiness. CI runs the baseline API/proxy checks for PRs and merges to `dev` and `main`.

## How the pieces integrate

1. Schemas are Pydantic models in `modeling/mooring/core/schemas/` and the agent packages under `agents/mooring_agents/`.
2. `make contract` generates `contract/modeling.openapi.yaml`, `contract/agents.openapi.yaml` and
   `contract/examples/`. A test fails if `contract/` is stale, so code and contract can't drift.
3. The UI builds against the contract and the running services. Agents call modeling through
   `agents/mooring_agents/physics/`, never by importing physics code.
4. Each team replaces mocks behind a swap point (`modeling/modeling_api/backend.py`,
   `agents/mooring_agents/backend.py`) without changing the API.

See [CONTRIBUTING.md](CONTRIBUTING.md) for branches and pull requests.
