# Modeling capabilities the UI can expose

Living handoff from modeling to UI, 4–5 November 2026. These are suggestions for the UI agent to adopt, adapt or defer against its own plan; they do not require a new screen for every endpoint. Prioritize the existing Phase 1 flow and motion acceptance gate. Wire shapes and runnable fixtures in `contract/` take precedence over this guide. Modeling updates this document when it publishes a capability.

## First: make the existing workflow dependable

| Suggested UI behavior | Backend / evidence | Status and constraints |
| --- | --- | --- |
| Four named demo choices, with initial and final outcomes shown separately | `GET /api/v1/demo/docking-cases`; `contract/examples/modeling/demo_ddg-*.json` | Implemented. Supported case finishes AMBER/limited; storm RED/reject; invalid depth RED/invalid/revise. Initially underconstrained plan can be repaired by the planner. Do not label its repaired result undetermined. |
| Explicit intake → plan → independent review → sheet flow | Agents intake reports, plans, safety reviews and sheets in `contract/agents.openapi.yaml` | Implemented. Pass `intake_report_id` to planning; retain returned review identity when showing a sheet. Completion does not imply feasibility or approval. |
| Progress and cancellation without blocking the map | Real asynchronous jobs, planner SSE `step`, `proposal`, `done`; `DELETE /jobs/{id}` | Implemented. Poll/consume terminal state after HTTP 202. Respect 429 `Retry-After`; display failed/cancelled states. Keep bounded event/frame history. |
| Explain what limits a plan | Result findings, validity, governing element and immutable `result_id` references | Implemented. Keep operational status, data validity and computation outcome distinct. `backend=real` is implementation provenance, not qualification. Unknown/null limits are unavailable, not zero. |
| Preserve assistance actually assessed | Final `holding_tugs`, candidate `tugs`, analysis references | Implemented. Berthing `tug_plan` assignments are a different purpose; do not substitute them into the holding analysis. |
| Gust warning with the right threshold | Envelope `limit_gust_kt` / `advisory_gust_kt`; sustained `limit_wind_kt` | Implemented. Compare gust to gust, sustained to sustained. Breaking gust is unavailable where the solver cannot establish it. |

## Advance docking planning (optional compact panel)

A practical first UI is an arrival-window form next to the existing planner, followed by a table/timeline of alternatives. Keep the detailed modeling controls collapsed.

1. Show **planning as-of time**, candidate arrivals at least 24 hours later, operation duration and holding duration. Display UTC alongside a clearly named local timezone. Fetch enough coverage to include the end of holding, not just the next 24 hours.
2. Show source, issue time, valid interval, coverage gaps, missing components and any unknown wind averaging basis before submission. A training scenario is not a weather forecast. Public composite forecasting is still being integrated; supplied complete snapshots already work.
3. Submit `POST /api/v1/mooring/forecast-plan`, follow its job, and display `ForecastDockingResponse`. Full request: `contract/examples/modeling/mooring_forecast_plan.json`; details: [FORECAST_DOCKING.md](FORECAST_DOCKING.md).
4. Render each arrival's computed outcome, governing time/element, utilization and result links. Distinguish unavailable inputs from undetermined computation and an assessed overloaded plan. A selected arrival only means the static sampled holding checks met the requested target; it does not approve navigation or line handling.
5. Offer to inspect/apply the returned line configuration using the existing map. Retain its arrival tide, forecast provenance and tug assumptions. `optimize_lines` searches a common configuration; no synthetic conversion from utilization into a new line rating.
6. Show a **recheck required** state when forecast, arrival, loading, geometry, lines or tugs change. Do not visually carry a previous approval onto changed inputs. Backend results remain immutable; automatic UI invalidation/replanning is a suggestion, not yet implemented here.

Draft sequences use the existing sequence/planner/review interfaces; the forecast result does not currently bundle an approved sequence. Keep durations and intermediate handling assumptions labeled unreviewed. Pilot/deck-officer acceptance, UKC, tug availability and traffic are separate requirements.

## Training and scenario controls

| Suggested UI capability | Interface | Honesty / implementation notes |
| --- | --- | --- |
| Seeded weather scenario editor with preview | `POST /api/v1/data-simulation/forecast` | Implemented: UTC anchor, seed, baseline, gust pulse/noise and optional water-level oscillation. Source `scenario`, `not_a_forecast`. Implementation isolated in `modeling/mooring/data_simulation/`; reusable for a later training UI. |
| Compare arrival choices under one scenario | Supply the generated series to forecast-plan | Implemented composition. Keep the seed and request for reproducibility; no automatic replacement of failed public data. |
| Tide/tending timeline | `POST /api/v1/mooring/tide-sweep`, optional `water_level_forecast` | Implemented. No series means explicitly synthetic training tide. Supplied invalid/gapped series is rejected. Wind/current stay fixed; tending is advisory, not an approved deck procedure. |
| Berth image draft review | Vision upload/job/confirm; optional `berth_id`, pier-face pixel anchors and scale | Implemented. Show `extraction_source`, note, estimated capacities and `needs_confirmation`. No-LLM catalog output is not image extraction. Confirmation registers a selectable runtime berth; durable berth administration remains open. |

## Integration checklist for the UI agent

- Regenerate types after merging `dev`; use generated examples as consumer fixtures. Report missing/ambiguous fields in `docs/overnight/modeling-agents.md` → Requests.
- Keep seed/synthetic/limited labels visible on map, alternatives and sheet, including when a review is ready for signature.
- Display partial/stale/missing forecasts without filling values. Future missing coverage is a risk finding, even if present conditions look moderate.
- Auth is off for the local demo. Optional authenticated HTTP/SSE clients need headers; never place bearer keys in URLs. Do not infer verified approver authority from a typed name.
- PDF may return 501 when the renderer is unavailable; HTML remains usable for browser print. Show the actual renderer result.
- Report which suggestions were picked up in the UI inbox's Interfaces section. Defer optional forecast/training panels if they jeopardize the required end-to-end flow.

## Coordination

Use the shared inbox protocol in [team_agent_instructions/README.md](../team_agent_instructions/README.md). Watch `origin/dev`, active UI/data/modeling branches and the three `docs/overnight/` files at each integration point. Publish endpoint changes, fixtures, assumptions and test status before consumers depend on them. Never auto-merge unchecked work or edit another agent's worktree.
