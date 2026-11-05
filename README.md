# pier-review-ship-parking

Mooring planning demonstrator for FLEETHACKER Norfolk 2026. It evaluates mooring configurations, tug assistance and draft
line sequences against wind, current and tide, and produces a Mooring Evolution Safety Sheet. The plan, phases and module
list are in [docs/PLAN.md](docs/PLAN.md). Current implementation and gaps are tracked in the
[build-out ledger](docs/MODELING_BUILDOUT_STATUS.md); overnight work follows
[the expanded modeling plan](docs/MODELING_OVERNIGHT_PLAN.md).

> **Real code, placeholder data.** Implemented: UFC environmental loads, static equilibrium, limiting wind and tide sweep,
> rated tug allocation, holding-plan checks, bounded line-plan search, draft sequence checks, risk sampling, bounded jobs
> and optional SQLite persistence. Risk artifacts remain unqualified. Berthing uses a real integrator with an explicitly
> synthetic vessel body; approach planning/simulation remain mock. CO-OPS observations and individual NWS/chart readers
> exist, but a complete public forecast for docking is not yet wired. Default operation stays offline with labeled
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

Optional UI handoffs are kept in [MODELING_UI_RECOMMENDATIONS.md](docs/MODELING_UI_RECOMMENDATIONS.md).

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

Prerequisite: [uv](https://docs.astral.sh/uv/) (it installs the right Python for you).

```bash
make install   # one virtualenv for both Python services
make mock      # modeling on :8000 and agents on :8001, with reload
```

- Modeling API docs: http://localhost:8000/docs
- Agents API docs: http://localhost:8001/docs

Other targets in the root `Makefile`: `make modeling` or `make agents` (one service), `make contract`
(regenerate the contract), `make test`.

## How the pieces integrate

1. Schemas are Pydantic models in `modeling/mooring/core/schemas/` and `agents/mooring_agents/schemas/`.
2. `make contract` generates `contract/modeling.openapi.yaml`, `contract/agents.openapi.yaml` and
   `contract/examples/`. A test fails if `contract/` is stale, so code and contract can't drift.
3. The UI builds against the contract and the running services. Agents call modeling through
   `agents/mooring_agents/clients.py`, never by importing physics code.
4. Each team replaces mocks behind a swap point (`modeling/modeling_api/backend.py`,
   `agents/mooring_agents/backend.py`) without changing the API.

See [CONTRIBUTING.md](CONTRIBUTING.md) for branches and pull requests.
