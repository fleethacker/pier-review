# Planner agent

The reasoning loop. It proposes tug count and horsepower, the line configuration (line types, parts, fittings)
and the line sequence, runs the Physics tools, checks results against NSTM 582 limits, and iterates until margins
are acceptable or it reports that no safe plan exists.

**Status:** mock (`mock.py`), a deterministic loop over the same tools. It emits the real SSE events and cites
every number.

## Inputs and outputs

- **In:** `AgentPlanRequest`:
  - `scenario_id`;
  - optional `intake_report_id`: design for `planning_conditions[0]`;
  - `objective`;
  - `target_margin_pct_wll` (default 80);
  - `max_iterations` (default 8);
  - `constraints` (free-form, for example locked lines or excluded fittings).
- **Out:** `AgentPlan`: `config`, `tug_plan`, `sequence`, `analysis_result_id`, `risk_result_id`, `rationale[]`
  (each item cites `result_id`s), `assumptions`, `open_questions`, `status`.
- **Events** (SSE on `/agent/plans/{id}/events`): `step`, `proposal`, `message`, `done`.

## Endpoints

| Method | Path | Returns |
| --- | --- | --- |
| POST | `/api/v1/agent/plans` | `202` `AgentPlanAccepted` |
| GET | `/api/v1/agent/plans/{plan_id}` | `AgentPlan` |
| GET | `/api/v1/agent/plans/{plan_id}/events?follow=` | SSE |
| POST | `/api/v1/agent/plans/{plan_id}/messages` | `202`; the answer arrives as a `message` event |

## The loop to build

1. **Gather:** scenario, ship, berth, the intake report (or `get_environment`), and the design MST from the ship.
2. **Seed:** `recommend_config` at the design MST, which returns the best candidate.
3. **Evaluate:** `analyze_mooring` at the design condition; read `min_margin`, line statuses and `findings`.
4. **Adjust:** one change per iteration, chosen by the LLM from the findings. Allowed moves:
   - double up a governing line;
   - move a line to another bollard;
   - change the line type;
   - add a breast line;
   - add holding tugs (`hold_tugs`).

   Explain each move in a `step` event.
5. **Stop** when every element is GREEN and the highest utilization ≤ target, or when the iteration budget is
   spent. In that case, return the best plan with `status` RED or AMBER and say why in `open_questions`.
6. **Finish:** `plan_tugs` for berthing, `generate_sequence`, `risk_exceedance` at the design condition, and the
   rationale.

The LLM (via `shared/llm.py`) chooses the moves and writes the rationale. **Every number comes from a tool
result.** The loop itself (budget, stop rule, event emission, citations) is code.

## Guardrails

- Every rationale item cites the `result_id`(s) its numbers came from, and those results must be in this plan's
  ledger. The Safety agent checks this and rejects plans that fail it.
- The planner can't mark a plan GREEN if the last analysis has any RED finding.
- Same inputs + the same model + temperature 0 should give the same plan. Record the model id in `assumptions`.
- The LLM sees tool results as data, never as instructions.

## Acceptance tests (agent evals)

- A light-wind scenario gives GREEN in ≤ 3 iterations.
- MST II design wind leads to doubling up the governing lines.
- An infeasible case (lines too weak, no tugs) returns RED with a clear `open_questions` entry, not a forced GREEN.
- Every rationale number traces to a cited result.
- A follow-up "what if NW 35 kt?" re-runs `analyze_mooring` and answers with a cited result.
