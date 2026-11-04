# agents

LLM agent service (FastAPI, port 8001). Agents reason and explain; **they never compute physics**. Every number
comes from the modeling service through the Physics agent's logged toolkit and is cited by its `result_id`.

## The agents

| Folder | Agent | Job | Status |
| --- | --- | --- | --- |
| [`intake/`](mooring_agents/intake/README.md) | Environment/Intake | Environment data → windows of concern, MST assessment, conditions to design for | mock |
| [`physics/`](mooring_agents/physics/README.md) | Physics/Load | Logged tool gateway to modeling: forces, line geometry, bollard strain. No LLM, no math | real gateway |
| [`planner/`](mooring_agents/planner/README.md) | Planner | Proposes tugs, lines and sequence; runs physics; iterates to acceptable margins | mock |
| [`safety/`](mooring_agents/safety/README.md) | Safety/Brief | Independent review, gust warnings vs working-load and breaking limits, Safety Sheet | mock review, real sheet |
| [`vision/`](mooring_agents/vision/README.md) | Berth Map | Berth image → draft berth and line placement, human-confirmed | mock |

Each folder's README is that agent's plan and spec. Each folder holds `schemas.py` (its API types), `mock.py` (the
current placeholder) and, once built, the real agent beside it.

## How they work together

```text
            ┌──────────────┐  IntakeReport   ┌──────────────┐  AgentPlan   ┌───────────────┐
 UI ──────▶ │ Intake agent │ ──────────────▶ │ Planner      │ ───────────▶ │ Safety/Brief  │ ──▶ Safety Sheet
            └──────┬───────┘                 └──────┬───────┘              └──────┬────────┘     + approvals
                   │                                │                             │  live gust warnings (SSE)
                   └──────────────┬─────────────────┴─────────────┬───────────────┘
                                  ▼                               ▼
                       Physics agent: tool catalog + ledger  ──HTTP──▶  modeling/ (:8000)
```

API flow: `POST /intake/reports` → `POST /agent/plans` (with `intake_report_id`) → `POST /safety/reviews` →
`POST /safety-sheets` → `POST /safety-sheets/{id}/approvals`, with `GET /safety/watch/{plan_id}` for live warnings.
Full spec: `contract/agents.openapi.yaml`.

## Layout

```text
mooring_agents/
  shared/llm.py   provider-agnostic LLM interface every agent codes to (no provider wired yet)
  physics/        client.py, tools.py, toolkit.py (ledger), schemas.py
  intake/ planner/ safety/ vision/   README.md, schemas.py, mock.py (+ safety/sheet.py)
  schemas.py      re-exports every agent's schemas for the contract
  backend.py      swap point: which implementation serves each agent
  api/            main.py, state.py, routers/ (one per agent)
tests/            run modeling in-process behind an HTTP transport
```

## Rules for every agent

1. Physics only through `PhysicsToolkit`, never by importing `mooring` physics or mock code, and never by doing
   arithmetic on physics quantities.
2. Pass/fail, thresholds, budgets and stop rules are code. The LLM chooses moves and writes words.
3. Every number in LLM-written text must come from a cited tool result or a structured field. Test it.
4. LLM access only through `shared/llm.py`. Provider, model and keys come from environment variables. With no LLM
   configured, agents fall back to their deterministic behavior so tests and demos run offline.
5. Keep the API shapes. If one must change, run `make contract` and tag the UI team.
6. Replace a mock by adding the real agent beside it and switching one import in `backend.py`.
