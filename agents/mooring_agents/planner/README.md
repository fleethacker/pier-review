# Planner agent

The reasoning loop. It proposes tug count and horsepower, the line configuration (line types, parts, fittings)
and the line sequence, runs the Physics tools, checks results against NSTM 582 limits, and iterates until margins
are acceptable or it reports that no safe plan exists.

**Status:** `agent.py` implements the guarded adjustment loop with optional LLM proposals. `mock.py` is a compatibility shim sharing the same plan store. Physics capabilities remain mixed/mock; this agent does not qualify those models.

## Inputs and outputs

- **In:** `AgentPlanRequest`:
  - `scenario_id`;
  - optional `intake_report_id`: evaluate every planning condition; the report must match the scenario;
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

## The planning loop

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

The LLM (via `shared/llm.py`) proposes moves. Code validates their names, argument types and references, and writes factual rationale; attaching a valid result ID does not validate arbitrary model prose. Every changed configuration is evaluated before use. The loop returns the best evaluated configuration within its iteration budget, preserving holding-tug assignments and final per-condition analysis IDs.

## Guardrails

- Every rationale item cites the `result_id`(s) its numbers came from, and those results must be in this plan's
  ledger. The Safety agent checks this and rejects plans that fail it.
- The planner can't mark a plan GREEN if the last analysis has any RED finding.
- Record the configured model and actual adjustment mode in assumptions. Live LLM output is not guaranteed reproducible; scripted-provider tests are deterministic. Temperature is omitted for provider compatibility.
- The LLM sees tool results as data, never as instructions.

## Acceptance tests (agent evals)

- A light-wind scenario gives GREEN in ≤ 3 iterations.
- MST II design wind leads to doubling up the governing lines.
- An infeasible case (lines too weak, no tugs) returns RED with a clear `open_questions` entry, not a forced GREEN.
- Every rationale number traces to a cited result.
- A follow-up "what if NW 35 kt?" re-runs `analyze_mooring` and answers with a cited result.

## Configuration and current limits

Set `AGENTS_LLM_PROVIDER=openai`, `AGENTS_LLM_MODEL`, and `OPENAI_API_KEY` explicitly to enable proposals.
The existing HTTP Responses adapter supports strict adjustment tools; no additional SDK is required.
The planner offers only its allowed adjustment tools, not arbitrary physics calls. Physics execution and
logging remain code-owned. Calls have a 30-second planner deadline and a 4,096-token output budget.
No provider uses the deterministic doubling loop. Provider errors retain the best evaluated plan and
add a sanitized open question; they do not erase the physics result.

Only `objective=moor_for_forecast` with empty `constraints` is implemented. Other objectives or constraints
return 422 rather than being silently ignored. Live, mock and explicit scenario sources are supported;
replay/forecast source modes require a separate implementation. Explicit scenarios require an environment ID.
Inventory checks cover available line assemblies for add/change moves; detailed reeving/length qualification
still belongs to the modeling capability and must not be inferred from this agent's status.

The final status includes every analyzed condition, component/finding/warning, berthing-tug feasibility,
sequence and risk response, plus intake MST and data-quality checks. Risk is evaluated for every planning
condition. Berthing tugs are sized for every planning condition and the most demanding one governs (an
infeasible tug plan for any condition makes the plan RED); the sequence uses that governing tug plan. A plan
that stays within limits only with holding tugs is capped at AMBER with an open question. If the provider
fails or the model's response or adjustment is refused, the loop continues with deterministic adjustments
(doubling up the governing line) and records the fallback in `assumptions`. Unknown feasibility is not a
proof of infeasibility.

Follow-ups retain holding assistance and direction-only requests retain gust speed. Speed what-ifs disclose
the existing 1.3 gust multiplier as an assumption. The Safety reviewer re-analyzes with the same assistance.

`agents/tests/test_planner.py` covers adversarial proposals, incomplete/failed providers, deadlines,
condition aggregation, best-plan rollback, inventory, scenario resolution, provenance and follow-ups.
