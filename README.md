# pier-review-ship-parking

Mooring assistant for FLEETHACKER Norfolk 2026. It plans safe moorings, tug assists and line sequences from wind,
current and tide, and produces a Mooring Evolution Safety Sheet. The plan, phases and module list are in
[docs/PLAN.md](docs/PLAN.md). Remaining modeling work follows the reviewed
[execution plan](docs/MODELING_EXECUTION_PLAN.md), starting with S00.

> **Mostly mock today.** Real: environmental loads (UFC 4-159-03), line geometry, NSTM 582 rule checks and the
> Physics agent's logged tool gateway. Everything else (mooring load sharing, risk, tugs, optimizer, simulations,
> agent decisions) is placeholder logic with the right shape. Every envelope carries `"backend": "mock"` or
> `"real"`; `GET /version` on each service lists module status.

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
3. The UI builds against the contract and the running mock servers. Agents call modeling through
   `agents/mooring_agents/clients.py`, never by importing physics code.
4. Each team replaces mocks behind a swap point (`modeling/modeling_api/backend.py`,
   `agents/mooring_agents/backend.py`) without changing the API.

See [CONTRIBUTING.md](CONTRIBUTING.md) for branches and pull requests.
