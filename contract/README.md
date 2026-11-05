# API contract

The only thing `frontend/`, `modeling/` and `agents/` share. **Generated, never edited by hand:** change the
Pydantic schemas or endpoints, run `make contract` from the repo root, and commit the result in the same PR.

| File | Service | Base URL (local mock) |
| --- | --- | --- |
| `modeling.openapi.yaml` | Physics and ML modeling | `http://localhost:8000/api/v1` |
| `agents.openapi.yaml` | LLM agents | `http://localhost:8001/api/v1` |
| `examples/modeling/*.json` | A valid request body for every modeling POST endpoint (DDG 51 at mock Pier 12 North) | — |

## Conventions (apply to every endpoint)

- **Units are in field names:** `_kt`, `_ft`, `_lbf`, `_ftlbf`, `_lt`, `_hp`, `_deg`, `_circ_in`, `_utc`.
- **Directions:** wind is where it blows **from**; current is where it flows **toward**. Both degrees true.
- **Berth frame:** standing on the pier facing the water, +y points into the water and +x runs to your right.
  `face_bearing_true_deg` is the true bearing of +x. Starboard side to puts the bow toward +x.
- **Ship frame:** origin at midships on the waterline; +x forward, +y to port.
- **Envelopes:** every compute endpoint returns `{result_id, model, model_version, backend, inputs_hash,
  computed_at_utc, status, assumptions, warnings, result}`. Fetch any past result with `GET /results/{result_id}`.
- **Jobs:** slow endpoints return `202` with `{job_id, status_url, events_url}`. Poll `status_url` (the envelope
  is in `result` when `state` is `succeeded`) or stream `events_url` (Server-Sent Events: `progress`, `done`).
- **Errors:** `404` for an unknown id in the path, `422` for invalid bodies or references to things that don't
  exist (unknown fields are rejected too). A plan that is unsafe is not an error: it returns `200` with
  `status: RED` and findings.
- **WebSockets** (modeling) are listed under `x-websockets` in `modeling.openapi.yaml`. Their message schemas
  (`EnvironmentSnapshot`, `Alert`, `SimFrame`, `Sim*Message`, `TelemetryRecord`) are in `components/schemas`.
- **Agent plan events** stream from `GET /agent/plans/{plan_id}/events`: `step`, `proposal`, `message`, `done`
  (schemas `AgentStepEvent`, `AgentProposalEvent`, `AgentMessageEvent`, `AgentDoneEvent`).

## Typical UI flow

1. `GET /ships`, `GET /berths`, `GET /berths/{id}`: draw the pier and fittings.
2. `POST /scenarios`: save ship, berth, side and line configuration from the canvas.
3. `POST /mooring/analyze` on every canvas change: color lines and fittings by `status` and `pct_wll`.
4. `WS /ws/env` and `WS /ws/alerts`: live wind, current, tide and gust warnings.
5. Agents: `POST /intake/reports` → `POST /agent/plans` (with `intake_report_id`) → stream `events_url` →
   `GET /agent/plans/{id}`.
6. Agents: `POST /safety/reviews` → `POST /safety-sheets` (with `review_id`) →
   `GET /safety-sheets/{id}/render?format=html` → `POST .../approvals`. Live gust warnings:
   `GET /safety/watch/{plan_id}` (SSE `warning` events).
7. Agents: `GET /physics/calls?plan_id=` shows every physics call behind a plan (audit trail).

### Optional forecast binding, layout and prediction consumers

`IntakeRequest.forecast_request` accepts the modeling `ForecastResolveRequest`: a supplied series or a scenario
binding, berth, availability cutoff and interval. Its interval must match `horizon_hours`. Intake, Planner and Safety
each log a canonical resolve and preserve the same `forecast_manifest` (source, revision, content/binding hashes).
Their `forecast_result_id` values identify those independent resolves. A changed selection requires new assessment;
it cannot inherit approvals from an earlier plan. Safety watch uses that selected source within its assessed interval.
Public latest-revision discovery still requires D2; a supplied `source_id` is not a provider lookup.

New `SafetySheet.layout` records contain a self-contained SVG or an explicit unavailable reason, bound to sheet ID,
version, plan, review and analysis plus reference/geometry hashes. Render this saved SVG; never capture a later canvas
for an older sheet. Printable HTML embeds it. Legacy or invalid layouts stay unavailable. `forecast_manifest` and
`forecast_result_id` on the sheet retain the independent review's binding. The existing sheet HTML iframe works;
the U13 sidebar consumer remains separate work.

`GET /predictions/{result_id}/brief` on agents explains a saved, caller-owned prediction with immutable citations,
model warnings and explicit hazard/uncertainty limitations. The `predict_trajectory`, `get_prediction` and
`resolve_forecast` physics tools expose logged access to their modeling interfaces. See the
[narration contract notes](../agents/mooring_agents/prediction/README.md).

Modeling `GET /ships/{class_id}/capabilities` and `POST /ships/validate` return `AssetQualification`, including
side-specific template gates and an aggregate draft-sequence capability. Validation accepts an unsaved `ShipClass`; it neither installs it nor
grants engineering approval. Missing CG-47, LHD-1 and CVN-68 fitting data still prevents their automatic mooring plans.

## Where the contract differs from docs/PLAN.md

The plan's examples were a first draft; this folder is authoritative. Changes made while building:

- Berth frame +x is defined by handedness (above), not "toward the outer end of the pier".
- Pier fittings carry `capacity_nominal_lbf` (NSTM Table 582-5-6 "Nom.") plus optional horizontal and 45° ratings.
- Envelopes include `backend` (`mock` or `real`).
- Approach requests use `origin` instead of `from`.
- Agents are a separate service on `:8001` with their own spec: Intake, Physics (tool gateway), Planner,
  Safety/Brief and Berth Map agents.
